"""The select -> verify -> right click -> wait loop.

Screen capture, mouse, window mapping and the clock are injected so the whole
loop runs offline in tests against synthetic frames.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .candidates import Candidate, build_candidates
from .config import Settings
from .geometry import Mapping, resolve_mapping
from .vision import VerifyResult, load_template, verify
from .winput import DryRunMouse, cursor_pos, key_down

log = logging.getLogger("r2clicker")


@dataclass
class CycleResult:
    success: bool
    attempts: int
    candidate: Candidate | None = None
    verify: VerifyResult | None = None
    tried: list[tuple[int, int]] = field(default_factory=list)


class Bot:
    def __init__(
        self,
        settings: Settings,
        grab: Callable[[Mapping], np.ndarray],
        mouse=None,
        mapping_fn: Callable[[], tuple[Mapping, str]] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.s = settings
        self.grab = grab
        self.mouse = mouse or DryRunMouse()
        self.mapping_fn = mapping_fn or (lambda: resolve_mapping(settings.window_title, settings.ref_w, settings.ref_h))
        self.stop_event = threading.Event()
        self._sleep_override = sleep
        self.last_success: tuple[int, int] | None = None
        self._template_cache: tuple[str, float, np.ndarray | None] | None = None

    # --- helpers -----------------------------------------------------------
    def stop(self, why: str = "stop requested") -> None:
        if not self.stop_event.is_set():
            log.warning("STOP: %s", why)
        self.stop_event.set()

    def _sleep(self, seconds: float) -> bool:
        """Interruptible sleep. Returns False if a stop was requested."""
        if seconds <= 0:
            return not self.stop_event.is_set()
        if self._sleep_override:
            self._sleep_override(seconds)
            return not self.stop_event.is_set()
        return not self.stop_event.wait(seconds)

    def _wait_until(self, deadline: float) -> bool:
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                return not self.stop_event.is_set()
            if not self._sleep(min(left, 0.05)):
                return False

    def _template(self, m: Mapping) -> np.ndarray | None:
        path = self.s.template_path
        if not path:
            return None
        scale = (m.sx + m.sy) / 2
        if self._template_cache and self._template_cache[:2] == (path, scale):
            return self._template_cache[2]
        t = load_template(path, self.s, scale)
        self._template_cache = (path, scale, t)
        if t is None:
            log.warning("template %s has too few white pixels; falling back to box search", path)
        return t

    def _save_shot(self, img: np.ndarray, tag: str) -> None:
        if not self.s.save_failure_shots:
            return
        from PIL import Image

        d = Path(self.s.log_dir) / "shots"
        d.mkdir(parents=True, exist_ok=True)
        Image.fromarray(img).save(d / f"{time.strftime('%H%M%S')}_{tag}.png")

    # --- one cycle -----------------------------------------------------------
    def run_cycle(self) -> CycleResult:
        s = self.s
        m, desc = self.mapping_fn()
        log.debug("mapping: %s", desc)
        park = m.to_screen(*s.park_point)
        self.mouse.move(*park)
        if not self._sleep(s.settle_delay):
            return CycleResult(False, 0)
        baseline = self.grab(m)
        tmpl = self._template(m)
        cands = build_candidates(s, baseline, m, self.last_success)[: max(0, s.max_attempts)]
        log.info("cycle: %d candidates (order=%s, step=%d)", len(cands), s.order, s.grid_step)
        tried: list[tuple[int, int]] = []
        res: VerifyResult | None = None

        for i, c in enumerate(cands, 1):
            if self.stop_event.is_set():
                break
            sx, sy = m.to_screen(c.x, c.y)
            tried.append((c.x, c.y))
            t_click = time.perf_counter()
            self.mouse.left_click(sx, sy)
            self.mouse.move(*park)  # hover highlights must not look like a selection
            if not self._wait_until(t_click + s.verify_delay):
                break
            while True:
                after = self.grab(m)
                res = verify(after, s, m, before=baseline if s.verify_mode == "diff" else None, template=tmpl)
                if res.ok or time.perf_counter() - t_click >= s.verify_timeout or self.stop_event.is_set():
                    break
                self._sleep(0.04)
            log.info(
                "attempt %d/%d left ref(%d,%d) screen(%d,%d) score=%.1f -> %s",
                i, len(cands), c.x, c.y, sx, sy, c.score, res.summary(),
            )
            if res.ok:
                if not self._sleep(s.right_click_delay):
                    break
                target = (sx, sy) if s.right_click_target == "same" else park
                self.mouse.right_click(*target)
                self.mouse.move(*park)
                log.info("selected at ref(%d,%d); right click at screen%s", c.x, c.y, target)
                self.last_success = (c.x, c.y)
                return CycleResult(True, i, c, res, tried)
            self._save_shot(after, f"fail{i}")
            baseline = after  # cursor is parked, so the latest frame is the best baseline
        return CycleResult(False, len(tried), None, res, tried)

    # --- full run --------------------------------------------------------------
    def run(self) -> None:
        s = self.s
        self.stop_event.clear()
        mode = "LIVE" if getattr(self.mouse, "live", False) else "DRY-RUN"
        log.info("start (%s): interval=%.3fs max_attempts=%d max_cycles=%s", mode, s.wait_interval,
                 s.max_attempts, s.max_cycles or "inf")
        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()
        cycles = failed = 0
        try:
            while not self.stop_event.is_set():
                if s.max_cycles and cycles >= s.max_cycles:
                    log.info("max cycles reached")
                    break
                cycles += 1
                r = self.run_cycle()
                t_end = time.perf_counter()
                if self.stop_event.is_set():
                    break
                if r.success:
                    failed = 0
                else:
                    failed += 1
                    log.warning("cycle %d: no selection after %d attempts (%d failed in a row)", cycles, r.attempts, failed)
                    if s.max_consecutive_failed_cycles and failed >= s.max_consecutive_failed_cycles:
                        self.stop("too many failed cycles in a row")
                        break
                if s.max_cycles and cycles >= s.max_cycles:
                    continue
                log.info("waiting %.3fs", s.wait_interval)
                if not self._wait_until(t_end + s.wait_interval):
                    break
                log.debug("waited %.3fs", time.perf_counter() - t_end)
        except Exception:
            log.exception("run aborted by error")
        finally:
            self.stop_event.set()
            log.info("stopped after %d cycles", cycles)

    def _watchdog(self) -> None:
        """Emergency stop: hotkey held, or cursor slammed into the top-left screen corner."""
        s = self.s
        while not self.stop_event.is_set():
            if key_down(s.emergency_hotkey):
                self.stop(f"emergency hotkey {s.emergency_hotkey}")
                return
            if s.corner_failsafe:
                p = cursor_pos()
                if p is not None and p[0] <= 2 and p[1] <= 2:
                    self.stop("cursor in top-left corner (failsafe)")
                    return
            time.sleep(0.02)
