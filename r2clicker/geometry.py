"""Reference (1600x900) <-> screen coordinate mapping and game-window lookup."""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from .config import Rect


@dataclass(frozen=True)
class Mapping:
    """Maps reference coordinates onto a client area at (left, top) of size (width, height)."""

    left: int
    top: int
    width: int
    height: int
    ref_w: int = 1600
    ref_h: int = 900
    hwnd: int = 0  # game window handle (0 = whole screen / offline)

    def contains_screen(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    @property
    def sx(self) -> float:
        return self.width / self.ref_w

    @property
    def sy(self) -> float:
        return self.height / self.ref_h

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return (self.left + round(x * self.sx), self.top + round(y * self.sy))

    def to_ref(self, sx: float, sy: float) -> tuple[float, float]:
        return ((sx - self.left) / self.sx, (sy - self.top) / self.sy)

    def rect_to_client(self, r: Rect) -> Rect:
        """Reference rect -> pixel rect inside a client-sized image (no screen offset)."""
        x1, y1, x2, y2 = r
        return (round(x1 * self.sx), round(y1 * self.sy), round(x2 * self.sx), round(y2 * self.sy))

    def scale_len(self, n: float) -> int:
        return max(1, round(n * (self.sx + self.sy) / 2))


if sys.platform == "win32":  # pointer-sized HWNDs (the ctypes default int would truncate them)
    from ctypes import wintypes as _wt

    _u32 = ctypes.windll.user32
    _u32.IsIconic.argtypes = [_wt.HWND]
    _u32.GetClientRect.argtypes = [_wt.HWND, ctypes.POINTER(_wt.RECT)]
    _u32.ClientToScreen.argtypes = [_wt.HWND, ctypes.POINTER(_wt.POINT)]
    _u32.IsWindowVisible.argtypes = [_wt.HWND]
    _u32.GetWindowTextLengthW.argtypes = [_wt.HWND]
    _u32.GetWindowTextW.argtypes = [_wt.HWND, _wt.LPWSTR, ctypes.c_int]


def enable_dpi_awareness() -> None:
    """Make Win32 coordinates physical pixels so they match screenshots."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def primary_screen_mapping(ref_w: int = 1600, ref_h: int = 900) -> Mapping:
    if sys.platform != "win32":
        return Mapping(0, 0, ref_w, ref_h, ref_w, ref_h)
    u = ctypes.windll.user32
    return Mapping(0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1), ref_w, ref_h)


def window_title(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    u = ctypes.windll.user32
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_window(title_substring: str) -> int | None:
    """HWND of the first visible top-level window whose title contains the text.

    Windows of this process are skipped: the tool's own title ("R2 target helper") would
    otherwise match the default filter "R2".
    """
    if sys.platform != "win32" or not title_substring:
        return None
    import os
    from ctypes import wintypes

    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    me = os.getpid()
    found: list[int] = []
    needle = title_substring.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value.lower():
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(cb, 0)
    return found[0] if found else None


def client_mapping(hwnd: int, ref_w: int = 1600, ref_h: int = 900) -> Mapping:
    from ctypes import wintypes

    u = ctypes.windll.user32
    rc = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wintypes.POINT(0, 0)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    return Mapping(pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top, ref_w, ref_h, hwnd)


_title_of = window_title  # resolve_mapping's parameter shadows the function name


class WindowNotFound(RuntimeError):
    pass


def resolve_mapping(window_title: str, ref_w: int = 1600, ref_h: int = 900) -> tuple[Mapping, str]:
    """Mapping for the game window's client area. Returns (mapping, description).

    An empty title explicitly means "the whole primary screen". A non-empty title that matches
    no window, or a minimized/zero-size window, raises WindowNotFound: silently falling back to
    the screen would click into whatever else is there.
    """
    if not window_title:
        m = primary_screen_mapping(ref_w, ref_h)
        return m, f"primary screen {m.width}x{m.height}"
    hwnd = find_window(window_title)
    if not hwnd:
        raise WindowNotFound(f"no visible window title contains '{window_title}'")
    if sys.platform == "win32" and ctypes.windll.user32.IsIconic(hwnd):
        raise WindowNotFound(f"window '{window_title}' is minimized")
    m = client_mapping(hwnd, ref_w, ref_h)
    if m.width <= 0 or m.height <= 0:
        raise WindowNotFound(f"window '{window_title}' has an empty client area")
    return m, f"window '{_title_of(hwnd)}' client {m.width}x{m.height} at ({m.left},{m.top})"


def is_foreground(hwnd: int) -> bool:
    """True if hwnd (or offline mapping with hwnd 0) is the active window."""
    if not hwnd or sys.platform != "win32":
        return True
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.GetAncestor.restype = ctypes.c_void_p
    u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    fg = u.GetForegroundWindow()
    if not fg:
        return False
    return fg == hwnd or u.GetAncestor(fg, 2) == hwnd  # GA_ROOT


def activate(hwnd: int) -> bool:
    """Bring hwnd to the front (right after the user pressed Start, so Windows allows it)."""
    if not hwnd or sys.platform != "win32":
        return False
    u = ctypes.windll.user32
    u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    return bool(u.SetForegroundWindow(hwnd))


def monitor_top_left(x: int, y: int) -> tuple[int, int]:
    """Top-left corner of the monitor containing (x, y). Works with negative coordinates."""
    if sys.platform != "win32":
        return (0, 0)
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    u = ctypes.windll.user32
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    hmon = u.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not hmon or not u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return (0, 0)
    return (mi.rcMonitor.left, mi.rcMonitor.top)
