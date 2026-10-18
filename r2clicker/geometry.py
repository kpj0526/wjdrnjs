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


def find_window(title_substring: str) -> int | None:
    """Return the HWND of the first visible top-level window whose title contains the text."""
    if sys.platform != "win32" or not title_substring:
        return None
    from ctypes import wintypes

    u = ctypes.windll.user32
    found: list[int] = []
    needle = title_substring.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
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
    return Mapping(pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top, ref_w, ref_h)


def resolve_mapping(window_title: str, ref_w: int = 1600, ref_h: int = 900) -> tuple[Mapping, str]:
    """Mapping for the game window if found, else the primary screen. Returns (mapping, description)."""
    hwnd = find_window(window_title)
    if hwnd:
        m = client_mapping(hwnd, ref_w, ref_h)
        if m.width > 0 and m.height > 0:
            return m, f"window '{window_title}' client {m.width}x{m.height} at ({m.left},{m.top})"
    m = primary_screen_mapping(ref_w, ref_h)
    why = f"window '{window_title}' not found; " if window_title else ""
    return m, f"{why}using primary screen {m.width}x{m.height}"
