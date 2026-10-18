"""Where the helper window opens: always fully reachable on some monitor.

Pure geometry (fit_geometry) is separate from the Win32 monitor query so it can be tested
with any monitor layout, including monitors at negative coordinates.
"""
from __future__ import annotations

import ctypes
import re
import sys

Area = tuple[int, int, int, int]  # left, top, right, bottom (work area: screen minus taskbar)

MARGIN = 8          # keep this far from work-area edges
MIN_VISIBLE_W = 160  # a saved position is kept only if this much of the title bar is on a monitor
MIN_VISIBLE_H = 40
_GEOM = re.compile(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$")


def parse_geometry(g: str) -> tuple[int, int, int, int] | None:
    """'WxH+X+Y' (Tk format, X/Y may be negative) -> (w, h, x, y); None if malformed."""
    m = _GEOM.match((g or "").strip())
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    x, y = (int(v.replace("+-", "-")) for v in (m.group(3), m.group(4)))  # Tk writes "+-120" for x=-120
    return (w, h, x, y) if w > 0 and h > 0 else None


def _visible(x: int, y: int, w: int, a: Area) -> bool:
    """Enough of the title bar (top strip) of a window at x,y lies inside work area a."""
    l, t, r, b = a
    vis_w = min(x + w, r) - max(x, l)
    vis_h = min(y + MIN_VISIBLE_H, b) - max(y, t)
    return vis_w >= min(MIN_VISIBLE_W, w) and vis_h >= MIN_VISIBLE_H and t <= y


def fit_geometry(req_w: int, req_h: int, areas: list[Area], saved: str = "") -> tuple[int, int, int, int]:
    """(w, h, x, y) for the window.

    - Size: the saved size (or the requested size), shrunk to fit the chosen monitor.
    - Position: the saved position if its title bar is reachable on some monitor, then pulled
      fully inside that monitor; otherwise centred on the primary monitor (areas[0]).
    """
    if not areas:
        return req_w, req_h, 0, 0
    sv = parse_geometry(saved)
    w, h = (sv[0], sv[1]) if sv else (req_w, req_h)
    area = areas[0]
    pos = None
    if sv:
        for a in areas:
            if _visible(sv[2], sv[3], w, a):
                area, pos = a, (sv[2], sv[3])
                break
    l, t, r, b = area
    w = max(200, min(w, r - l - 2 * MARGIN))
    h = max(150, min(h, b - t - 2 * MARGIN))
    if pos is None:
        x, y = l + (r - l - w) // 2, t + (b - t - h) // 2
    else:
        x = min(max(pos[0], l + MARGIN), r - MARGIN - w)
        y = min(max(pos[1], t + MARGIN), b - MARGIN - h)
    return w, h, x, y


def monitor_work_areas() -> list[Area]:
    """Work areas of all monitors, primary first. Empty list if unavailable."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    u = ctypes.windll.user32
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    areas: list[tuple[bool, Area]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def cb(hmon, hdc, rect, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            w = mi.rcWork
            areas.append((bool(mi.dwFlags & 1), (w.left, w.top, w.right, w.bottom)))  # MONITORINFOF_PRIMARY
        return True

    try:
        u.EnumDisplayMonitors(None, None, cb, 0)
    except Exception:
        return []
    areas.sort(key=lambda pa: not pa[0])
    return [a for _, a in areas]


def is_remote_session() -> bool:
    """Running inside Remote Desktop (capture-excluded windows are invisible to the remote viewer)."""
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.GetSystemMetrics(0x1000))  # SM_REMOTESESSION
