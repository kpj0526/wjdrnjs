"""Checks run right before Start (and by "Preflight check" / `--preflight out.json`).

Every problem that would make a run click the wrong place, or not click at all, is reported
here with what to do about it, instead of surfacing mid-run. A report with any FAIL item must
not start a run; the GUI enforces that. Nothing here clicks or moves the mouse.

Checked:
- settings (including manual points) are valid
- the game window is found, not minimized, with a usable client area
- this process is DPI aware and the client size matches the reference aspect ratio
- one frame can be captured, has the client size and is not blank
- the candidate points (manual or automatic) map inside the client
- admin rights: a game running as administrator blocks clicks from a normal process
- DRY RUN / LIVE state
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field
from typing import Callable

from .candidates import build_candidates
from .capture import CaptureError, is_blank
from .config import Settings
from .geometry import Mapping, WindowNotFound, resolve_mapping

OK, INFO, WARN, FAIL = "ok", "info", "warn", "FAIL"
ASPECT_TOLERANCE = 0.02  # client w/h may differ this much from ref_w/ref_h before points stretch
MIN_CLIENT = (640, 360)


@dataclass
class Item:
    name: str
    status: str
    message: str

    def line(self) -> str:
        return f"[{self.status}] {self.name}: {self.message}"


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    mapping: Mapping | None = None

    def add(self, name: str, status: str, message: str) -> None:
        self.items.append(Item(name, status, message))

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def failures(self) -> list[Item]:
        return [i for i in self.items if i.status == FAIL]

    @property
    def warnings(self) -> list[Item]:
        return [i for i in self.items if i.status == WARN]

    def text(self) -> str:
        head = "PREFLIGHT PASSED" if self.ok else f"PREFLIGHT FAILED ({len(self.failures)} problem(s)); nothing is clicked"
        return "\n".join([head] + [i.line() for i in self.items])

    def as_dict(self) -> dict:
        return {"ok": self.ok, "items": [i.__dict__ for i in self.items]}


# --- Win32 probes (each returns None when it cannot tell) ---------------------------------------


def process_dpi_awareness() -> int | None:
    """0 = unaware (coordinates virtualized), 1 = system aware, 2 = per-monitor aware."""
    if sys.platform != "win32":
        return None
    u = ctypes.windll.user32
    try:
        u.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        return int(u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext()))
    except (AttributeError, OSError):  # before Windows 10 1607
        try:
            aw = ctypes.c_int()
            ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(aw))
            return aw.value
        except (AttributeError, OSError):
            return None


def window_dpi(hwnd: int) -> int | None:
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        u = ctypes.windll.user32
        u.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        return int(u.GetDpiForWindow(hwnd)) or None
    except (AttributeError, OSError):
        return None


def _token_elevated(process_handle) -> bool | None:
    from ctypes import wintypes

    adv = ctypes.windll.advapi32
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    tok = wintypes.HANDLE()
    if not adv.OpenProcessToken(process_handle, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
        return None
    try:
        val, n = wintypes.DWORD(), wintypes.DWORD()
        if not adv.GetTokenInformation(tok, 20, ctypes.byref(val), 4, ctypes.byref(n)):  # TokenElevation
            return None
        return bool(val.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(tok)


def self_elevated() -> bool | None:
    if sys.platform != "win32":
        return None
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    return _token_elevated(k.GetCurrentProcess())


def window_elevated(hwnd: int) -> bool | None:
    """Whether the process owning hwnd runs elevated; None if Windows does not let us read it
    (which, from a non-elevated process, usually means it is elevated or protected)."""
    if sys.platform != "win32" or not hwnd:
        return None
    from ctypes import wintypes

    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    k.OpenProcess.restype = wintypes.HANDLE
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    h = k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        return _token_elevated(h)
    finally:
        k.CloseHandle(h)


# --- the checks ---------------------------------------------------------------------------------


def run_preflight(
    s: Settings,
    grab: Callable[[Mapping], object],
    live: bool,
    resolve: Callable[[str, int, int], tuple[Mapping, str]] = resolve_mapping,
    dpi_awareness: Callable[[], int | None] = process_dpi_awareness,
    dpi_of: Callable[[int], int | None] = window_dpi,
    me_elevated: Callable[[], bool | None] = self_elevated,
    game_elevated: Callable[[int], bool | None] = window_elevated,
) -> Report:
    """All checks for one planned run. `live` = real clicks will be sent (DRY RUN off)."""
    r = Report()

    # 1. mode
    if live:
        r.add("mode", WARN, "LIVE: real clicks will be sent to the game window")
    else:
        r.add("mode", INFO, "DRY RUN: nothing is clicked, the log shows what would be clicked")

    # 2. settings
    problems = s.validate()
    if problems:
        for p in problems:
            r.add("settings", FAIL, p)
        return r
    r.add("settings", OK, f"valid ({len(s.manual_points)} manual points)" if s.manual_points else "valid")

    # 3. game window
    try:
        m, desc = resolve(s.window_title, s.ref_w, s.ref_h)
    except WindowNotFound as e:
        r.add("game window", FAIL, f"{e}. Start the game (not minimized) and check 'Game window title "
                                   "contains' (part of the title shown in the game's title bar/taskbar)")
        return r
    except Exception as e:  # a Win32 failure must still end as a clear message
        r.add("game window", FAIL, f"window lookup failed: {e}")
        return r
    r.mapping = m
    if not s.window_title:
        r.add("game window", WARN, f"title is empty: the whole primary screen is the target ({desc})")
    else:
        r.add("game window", OK, desc)

    # 4. client size and DPI
    aw = dpi_awareness()
    if aw == 0:
        r.add("DPI", FAIL, "this process is not DPI aware: with Windows display scaling the click "
                           "coordinates would be wrong. Restart the tool (it enables DPI awareness at start)")
    elif aw is None:
        r.add("DPI", INFO, "DPI awareness could not be read")
    else:
        dpi = dpi_of(m.hwnd)
        scale = f", game monitor scaling {round(dpi / 96 * 100)}%" if dpi else ""
        status = OK if aw == 2 or not dpi or dpi == 96 else WARN
        extra = "" if status == OK else " (system-aware only: keep the game on the main monitor)"
        r.add("DPI", status, f"awareness {('unaware', 'system', 'per-monitor')[aw] if aw in (0, 1, 2) else aw}"
                             f"{scale}{extra}")
    if m.width < MIN_CLIENT[0] or m.height < MIN_CLIENT[1]:
        r.add("client size", FAIL, f"game client is only {m.width}x{m.height}; make the game window larger "
                                   f"(at least {MIN_CLIENT[0]}x{MIN_CLIENT[1]})")
    else:
        aspect, ref_aspect = m.width / m.height, s.ref_w / s.ref_h
        if abs(aspect / ref_aspect - 1) > ASPECT_TOLERANCE:
            r.add("client size", WARN, f"client {m.width}x{m.height} is not {s.ref_w}:{s.ref_h}; points are "
                                       "stretched. Use a 16:9 game resolution or re-pick the ROI/points on a capture")
        else:
            r.add("client size", OK, f"{m.width}x{m.height} (scale {m.sx:.3f} x {m.sy:.3f} of the reference)")

    # 5. capture
    frame = None
    try:
        frame = grab(m)
    except CaptureError as e:
        r.add("capture", FAIL, str(e))
    except Exception as e:
        r.add("capture", FAIL, f"capture failed: {e}")
    else:
        if is_blank(frame):
            r.add("capture", FAIL, "the captured game frame is blank (black or one colour): the nameplate "
                                   "check cannot work. Bring the game to the front, or try capture backend "
                                   "'screen' / 'window'")
            frame = None
        else:
            r.add("capture", OK, f"frame {frame.shape[1]}x{frame.shape[0]}")

    # 6. candidates
    cands = build_candidates(s, frame, m if frame is not None else None)
    outside = [(c.x, c.y) for c in cands if not m.contains_screen(*m.to_screen(c.x, c.y))]
    kind = "manual points (in list order)" if s.manual_points else "automatic grid points"
    if not cands:
        r.add("candidates", FAIL, f"no clickable {kind}: the ROI is fully covered by the player/HUD areas")
    elif outside:
        r.add("candidates", FAIL, f"{len(outside)} points map outside the game client, e.g. {outside[0]}")
    else:
        r.add("candidates", OK, f"{len(cands)} {kind}; first {min(len(cands), s.max_attempts)} tried per cycle")

    # 7. administrator rights
    me, game = me_elevated(), game_elevated(m.hwnd) if m.hwnd else None
    if not m.hwnd:
        r.add("admin rights", INFO, "not checked (no game window)")
    elif game and not me:
        r.add("admin rights", FAIL if live else WARN,
              "the game runs as administrator but this tool does not: Windows blocks its clicks. "
              "Close the tool and start R2TargetHelper.exe with 'Run as administrator'")
    elif game is None and not me:
        r.add("admin rights", WARN, "could not read the game's rights (it may run as administrator or be "
                                    "protected). If clicks do nothing, start this tool as administrator")
    else:
        r.add("admin rights", OK, f"tool {'administrator' if me else 'normal user'}, "
                                  f"game {'administrator' if game else 'normal user'}")
    return r


def main(out: str) -> int:
    """`R2TargetHelper.exe --preflight out.json`: check the saved settings against the running game.
    Writes the report as JSON (a windowed exe has no console). Never clicks. Exit 0 = passed."""
    import json
    from pathlib import Path

    from .capture import Grabber
    from .geometry import enable_dpi_awareness
    from .paths import settings_path

    enable_dpi_awareness()
    s = Settings.load(settings_path())
    r = run_preflight(s, Grabber(s.capture_backend).grab, live=not s.dry_run)
    d = r.as_dict() | {"settings_file": str(settings_path()), "settings_warnings": s.load_warnings}
    Path(out).write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    if sys.stdout:
        print(r.text())
    return 0 if r.ok else 1
