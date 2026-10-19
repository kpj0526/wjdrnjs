"""The auto-click loop: every click point in order gets a left click and right after it a right
click, then the loop waits wait_interval. Nothing on screen is checked.

Mouse, window mapping, the clock and the safety probes (hotkey, cursor, foreground window,
covered points) are injected so the whole loop runs offline in tests.

Timing of one cycle:
    for each point: left click, wait right_click_delay, right click, wait point_delay (not after the last)
    wait_interval  <- from the cycle's last right click to the next cycle's first left click
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .capture import point_belongs_to
from .config import Settings
from .geometry import Mapping, WindowNotFound, is_foreground, monitor_top_left, resolve_mapping
from .winput import DryRunMouse, InputBlocked, cursor_pos, key_down

log = logging.getLogger("r2clicker")

# errors that end a run with a one-line message instead of a traceback
EXPECTED_ERRORS = (WindowNotFound, InputBlocked)


@dataclass
class CycleResult:
    clicked: list[tuple[int, int]] = field(default_factory=list)  # reference points left+right clicked
    skipped: str = ""  # non-empty: the cycle did not run or was cut short (e.g. game not in foreground)


class Bot:
    def __init__(
        self,
        settings: Settings,
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
        r = CycleResult()
        if not self._game_ready(m):
            r.skipped = "game window is not in the foreground"
            return r
        n = len(s.manual_points)
        for i, (x, y) in enumerate(s.manual_points, 1):
            if self.stop_event.is_set():
                break
            sx, sy = m.to_screen(x, y)
            if not m.contains_screen(sx, sy):
                log.error("point %d ref(%d,%d) maps outside the game client; skipped", i, x, y)
                continue
            if not self._game_ready(m):
                r.skipped = "game window lost focus"
                return r
            if not self._clickable(m, sx, sy):
                log.warning("point %d screen(%d,%d) is covered by another window; not clicked", i, sx, sy)
                continue
            self.mouse.left_click(sx, sy)
            if not self._sleep(s.right_click_delay):
                break
            self.mouse.right_click(sx, sy)
            r.clicked.append((x, y))
            log.info("point %d/%d ref(%d,%d) screen(%d,%d): left + right click", i, n, x, y, sx, sy)
            if i < n and not self._sleep(s.point_delay):
                break
        return r

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
        log.info("start (%s): %d click points, wait_interval=%.3fs max_cycles=%s", "LIVE" if self.live else "DRY-RUN",
                 len(s.manual_points), s.wait_interval, s.max_cycles or "inf")
        watchdog = threading.Thread(target=self._watchdog, daemon=True)
        watchdog.start()
        cycles = 0
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
                if r.skipped and not r.clicked:
                    if not paused:
                        log.warning("paused: %s (click the game window's title bar to resume)", r.skipped)
                    paused = True
                    self._sleep(0.5)
                    continue
                if paused:
                    log.info("resumed")
                    paused = False
                cycles += 1
                if not r.clicked:
                    log.warning("cycle %d: nothing clicked (every point was covered or outside the game)", cycles)
                if s.max_cycles and cycles >= s.max_cycles:
                    continue
                log.info("cycle %d done; waiting %.3fs", cycles, s.wait_interval)
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
