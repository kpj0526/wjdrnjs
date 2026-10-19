"""The select -> verify -> right click -> wait loop.

Screen capture, mouse, window mapping, the clock and the safety probes (hotkey, cursor,
foreground window) are injected so the whole loop runs offline in tests.

Timing of one cycle:
    park cursor, baseline shot
    repeat up to max_attempts: left click, park, wait verify_delay, check until verify_timeout
    on success: wait right_click_delay, right click, park
    wait_interval  <- measured from the end of the cycle to the start of the next one
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .candidates import Candidate, build_candidates
from .capture import CaptureError, is_blank, point_belongs_to
from .config import Settings
from .geometry import Mapping, WindowNotFound, is_foreground, monitor_top_left, resolve_mapping
from .vision import VerifyResult, load_template, verify
from .winput import DryRunMouse, InputBlocked, cursor_pos, key_down

log = logging.getLogger("r2clicker")

# errors that end a run with a one-line message instead of a traceback
EXPECTED_ERRORS = (WindowNotFound, CaptureError, InputBlocked)


@dataclass
class CycleResult:
    success: bool
    attempts: int
    candidate: Candidate | None = None
    verify: VerifyResult | None = None
    tried: list[tuple[int, int]] = field(default_factory=list)
    skipped: str = ""  # non-empty: the cycle did not run (e.g. game not in foreground)


class Bot:
    def __init__(
        self,
        settings: Settings,
        grab: Callable[[Mapping], np.ndarray],
        mouse=None,
        mapping_fn: Callable[[], tuple[Mapping, str]] | None = None,
        sleep: Callable[[float], None] | None = None,
        hotkey_fn: Callable[[str], bool] = key_down,
        cursor_fn: Callable[[], tuple[int, int] | None] = cursor_pos,
        corner_fn: Callable[[int, int], tuple[int, int]] = monitor_top_left,
        foreground_fn: Callable[[int], bool] = is_foreground,
        point_fn: Callable[[int, int, int], bool] = point_belongs_to,
    ) -> None:
        self.s = settings
        self.grab = grab
        mouse = mouse or DryRunMouse()
        if settings.dry_run and getattr(mouse, "live", False):
            log.warning("dry_run is on: ignoring the live mouse, no clicks will be sent")
            mouse = DryRunMouse()
        self.mouse = mouse
        self.mapping_fn = mapping_fn or (lambda: resolve_mapping(settings.window_title, settings.ref_w, settings.ref_h))
        self.hotkey_fn = hotkey_fn
        self.cursor_fn = cursor_fn
        self.corner_fn = corner_fn
        self.foreground_fn = foreground_fn
        self.point_fn = point_fn
        self.stop_event = threading.Event()
        self.stop_reason = ""
        self._sleep_override = sleep
        self.last_success: tuple[int, int] | None = None
        self._template_cache: tuple[str, float, np.ndarray | None] | None = None

    @property
    def live(self) -> bool:
        return bool(getattr(self.mouse, "live", False))

    # --- helpers -----------------------------------------------------------
    def stop(self, why: str = "stop requested") -> None:
        if not self.stop_event.is_set():
            self.stop_reason = why
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
            log.warning("template %s not usable; falling back to box search", path)
        return t

    def _save_shot(self, img: np.ndarray, tag: str) -> None:
        if not self.s.save_failure_shots:
            return
        try:
            from PIL import Image

            from .paths import resolve_in_data_dir

            d = resolve_in_data_dir(self.s.log_dir) / "shots"
            d.mkdir(parents=True, exist_ok=True)
            Image.fromarray(img).save(d / f"{time.strftime('%Y%m%d-%H%M%S')}_{tag}.png")
        except Exception as e:  # a full disk must not stop the run
            log.warning("could not save screenshot: %s", e)

    def _clickable(self, m: Mapping, x: int, y: int) -> bool:
        """Live clicks only where the game itself is visible (not under this helper or another window)."""
        return not self.live or self.point_fn(m.hwnd, x, y)

    def _game_ready(self, m: Mapping) -> bool:
        """Live clicks only go to the game when it is the active window."""
        return not self.live or self.foreground_fn(m.hwnd)

    # --- one cycle -----------------------------------------------------------
    def run_cycle(self) -> CycleResult:
        s = self.s
        m, desc = self.mapping_fn()
        log.debug("mapping: %s", desc)
        if not self._game_ready(m):
            return CycleResult(False, 0, skipped="game window is not in the foreground")
        park = m.to_screen(*s.park_point)
        if not m.contains_screen(*park):
            raise ValueError(f"park point {s.park_point} maps outside the game client")
        self.mouse.move(*park)
        if not self._sleep(s.settle_delay):
            return CycleResult(False, 0)
        baseline = self.grab(m)
        if is_blank(baseline):  # a black/one-colour frame: clicking would be blind, so stop the run
            raise CaptureError("the captured game frame is blank; nothing was clicked. Bring the game "
                               "to the front or change the capture backend")
        tmpl = self._template(m)
        cands = build_candidates(s, baseline, m, self.last_success)[: max(0, s.max_attempts)]
        if s.manual_points:
            log.info("cycle: %d manual candidates (in the order picked)", len(cands))
        else:
            log.info("cycle: %d candidates (order=%s, step=%d)", len(cands), s.order, s.grid_step)
        tried: list[tuple[int, int]] = []
        res: VerifyResult | None = None

        for i, c in enumerate(cands, 1):
            if self.stop_event.is_set():
                break
            sx, sy = m.to_screen(c.x, c.y)
            if not m.contains_screen(sx, sy):
                log.error("candidate ref(%d,%d) maps outside the client; skipped", c.x, c.y)
                continue
            if not self._game_ready(m):
                return CycleResult(False, len(tried), None, res, tried, skipped="game window lost focus")
            if not self._clickable(m, sx, sy):
                log.warning("screen(%d,%d) is covered by another window; not clicked", sx, sy)
                continue
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
                if not self._clickable(m, *target):
                    log.warning("right-click point screen%s is covered by another window; not clicked", target)
                    return CycleResult(False, i, c, res, tried, skipped="right-click point covered")
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
        self.stop_reason = ""
        problems = s.validate()
        if problems:
            for p in problems:
                log.error("invalid setting: %s", p)
            self.stop("invalid settings")
            return
        log.info("start (%s): wait_interval=%.3fs max_attempts=%d max_cycles=%s", "LIVE" if self.live else "DRY-RUN",
                 s.wait_interval, s.max_attempts, s.max_cycles or "inf")
        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()
        cycles = failed = 0
        paused = False
        try:
            while not self.stop_event.is_set():
                if s.max_cycles and cycles >= s.max_cycles:
                    self.stop_reason = self.stop_reason or "max cycles reached"
                    log.info("max cycles reached")
                    break
                r = self.run_cycle()
                t_end = time.perf_counter()
                if self.stop_event.is_set():
                    break
                if r.skipped:
                    if not paused:
                        log.warning("paused: %s (click the game window to resume)", r.skipped)
                    paused = True
                    self._sleep(0.5)
                    continue
                if paused:
                    log.info("resumed")
                    paused = False
                cycles += 1
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
                log.info("waiting %.3fs before the next cycle", s.wait_interval)
                if not self._wait_until(t_end + s.wait_interval):
                    break
        except EXPECTED_ERRORS as e:
            self.stop(str(e))
        except Exception as e:
            log.exception("run aborted by error")
            self.stop(f"error: {e}")
        finally:
            try:
                self.mouse.release()  # never leave a mouse button held
            except Exception as e:
                log.error("mouse release failed: %s", e)
            self.stop_reason = self.stop_reason or "stopped"
            self.stop_event.set()
            log.info("stopped after %d cycles (%s)", cycles, self.stop_reason)

    def _watchdog(self) -> None:
        """Emergency stop: hotkey held, or cursor pushed into the top-left corner of its monitor."""
        s = self.s
        while not self.stop_event.is_set():
            try:
                if s.emergency_hotkey and self.hotkey_fn(s.emergency_hotkey):
                    self.stop(f"emergency hotkey {s.emergency_hotkey}")
                    return
                if s.corner_failsafe:
                    p = self.cursor_fn()
                    if p is not None:
                        cx, cy = self.corner_fn(*p)
                        if p[0] - cx <= 2 and p[1] - cy <= 2:
                            self.stop("cursor in top-left corner (failsafe)")
                            return
            except Exception as e:  # a broken probe must stop the run, not silently disable safety
                self.stop(f"safety watchdog error: {e}")
                return
            time.sleep(0.02)
