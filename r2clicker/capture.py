"""Capture of the game client area, without anything that happens to be on top of it.

Backends (Settings.capture_backend):
- "window": PrintWindow(PW_CLIENTONLY | PW_RENDERFULLCONTENT) into a memory bitmap. Only the
  target window's own pixels, even when other windows (including this helper) overlap it.
  Some hardware-rendered games/browsers return a blank image here; that is reported as an
  error, never used.
- "screen": screen pixels via mss. Correct only if nothing covers the client area, so every
  grab first checks the windows above the target in Z-order and fails if any overlaps it.
  This helper's own windows are excluded from screen capture (SetWindowDisplayAffinity) and
  then do not count; if exclusion is unsupported they count like any other window.
- "auto" (default): "window", falling back to "screen" when the window capture is blank.
  After falling back, window capture is probed again every REPROBE_S seconds.

Window capture first tries the fast PrintWindow mode and switches to the full-content mode only
if the fast one returns a blank frame; the mode that works is remembered per window, so a steady
state grab is one PrintWindow call. A failed call is retried once immediately (no sleep).

A mapping with hwnd 0 (whole primary screen, empty title) always uses the screen backend.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np

from .geometry import Mapping

log = logging.getLogger("r2clicker")

BACKENDS = ("auto", "window", "screen")
REPROBE_S = 10.0


class CaptureError(RuntimeError):
    pass


def check_frame(img, m: Mapping) -> np.ndarray:
    """Reject frames that do not match the client size (e.g. DPI virtualization, window resized)."""
    if not isinstance(img, np.ndarray) or img.ndim != 3 or img.shape[2] < 3:
        raise CaptureError(f"capture returned {type(img).__name__}, not an RGB image")
    if img.shape[:2] != (m.height, m.width):
        raise CaptureError(
            f"capture is {img.shape[1]}x{img.shape[0]} but the client is {m.width}x{m.height}; "
            "check Windows display scaling (DPI) or whether the window was resized"
        )
    return img[..., :3]


def is_blank(img: np.ndarray) -> bool:
    """A uniform frame (typically all black) is what PrintWindow returns for content it cannot read."""
    a = img[::4, ::4, :3]
    return int(a.max()) - int(a.min()) <= 8


@dataclass(frozen=True)
class WinInfo:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]  # left, top, right, bottom (screen)


def overlapping(client: tuple[int, int, int, int], above: list[WinInfo], excluded: set[int]) -> list[WinInfo]:
    """Windows above the target whose rectangle intersects the client rectangle."""
    l, t, r, b = client
    out = []
    for w in above:
        if w.hwnd in excluded:
            continue
        wl, wt, wr, wb = w.rect
        if wl < r and wr > l and wt < b and wb > t:
            out.append(w)
    return out


# --- Win32 plumbing -----------------------------------------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    _u32 = ctypes.windll.user32
    _gdi = ctypes.windll.gdi32
    _dwm = ctypes.windll.dwmapi

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    _u32.GetDC.argtypes = [wintypes.HWND]
    _u32.GetDC.restype = wintypes.HDC
    _u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _u32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _u32.GetWindow.restype = wintypes.HWND
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _u32.WindowFromPoint.argtypes = [wintypes.POINT]
    _u32.WindowFromPoint.restype = wintypes.HWND
    _u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _u32.GetAncestor.restype = wintypes.HWND
    _gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi.CreateCompatibleDC.restype = wintypes.HDC
    _gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    _gdi.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi.SelectObject.restype = wintypes.HGDIOBJ
    _gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi.DeleteDC.argtypes = [wintypes.HDC]
    _dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]


PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
PW_MODES = (PW_CLIENTONLY, PW_CLIENTONLY | PW_RENDERFULLCONTENT)  # fast first
WDA_EXCLUDEFROMCAPTURE = 0x11
WS_EX_TRANSPARENT = 0x20
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9


def print_window(hwnd: int, width: int, height: int, flags: int = PW_CLIENTONLY | PW_RENDERFULLCONTENT) -> np.ndarray:
    """Client-area pixels of hwnd rendered by the window itself (not the screen). RGB uint8.

    PW_CLIENTONLY alone is fast (a few ms) and enough for GDI-drawn windows. PW_RENDERFULLCONTENT
    also reads DirectX/DWM content but waits for a composition frame (~17 ms at 60 Hz).
    """
    if sys.platform != "win32":
        raise CaptureError("window capture needs Windows")
    hdc_win = _u32.GetDC(hwnd)
    if not hdc_win:
        raise CaptureError("GetDC failed for the game window")
    hdc = _gdi.CreateCompatibleDC(hdc_win)
    bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hbmp = _gdi.CreateDIBSection(hdc_win, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        if not hbmp or not bits:
            raise CaptureError("CreateDIBSection failed")
        old = _gdi.SelectObject(hdc, hbmp)
        ok = _u32.PrintWindow(hwnd, hdc, flags)
        _gdi.SelectObject(hdc, old)
        if not ok:
            raise CaptureError("PrintWindow failed for the game window")
        buf = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
        bgra = np.frombuffer(buf, np.uint8).reshape(height, width, 4)
        return bgra[..., 2::-1].copy()
    finally:
        if hbmp:
            _gdi.DeleteObject(hbmp)
        _gdi.DeleteDC(hdc)
        _u32.ReleaseDC(hwnd, hdc_win)


def _visible_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    # extended frame bounds exclude the invisible resize border of modern windows
    if _dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        _u32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def windows_above(hwnd: int) -> list[WinInfo]:
    """Visible, uncloaked, non-click-through top-level windows above hwnd in Z-order."""
    if sys.platform != "win32":
        return []
    from .geometry import window_title

    out = []
    h = _u32.GetWindow(hwnd, 3)  # GW_HWNDPREV
    guard = 0
    while h and guard < 5000:
        guard += 1
        if _u32.IsWindowVisible(h) and not _u32.IsIconic(h):
            cloaked = wintypes.DWORD(0)
            _dwm.DwmGetWindowAttribute(h, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            exstyle = _u32.GetWindowLongW(h, -20)  # GWL_EXSTYLE
            if not cloaked.value and not exstyle & WS_EX_TRANSPARENT:
                rect = _visible_rect(h)
                if rect[2] > rect[0] and rect[3] > rect[1]:
                    out.append(WinInfo(h, window_title(h), rect))
        h = _u32.GetWindow(h, 3)
    return out


def exclude_from_capture(hwnd: int) -> bool:
    """Hide a window of this process from screen capture (Windows 10 2004+). It stays visible on screen."""
    if sys.platform != "win32" or not hwnd:
        return False
    return bool(_u32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def include_in_capture(hwnd: int) -> bool:
    """Undo exclude_from_capture (WDA_NONE)."""
    if sys.platform != "win32" or not hwnd:
        return False
    return bool(_u32.SetWindowDisplayAffinity(hwnd, 0))


def point_belongs_to(hwnd: int, x: int, y: int) -> bool:
    """True if the screen point (x, y) shows hwnd (or one of its child windows) - i.e. a click lands there."""
    if sys.platform != "win32" or not hwnd:
        return True
    h = _u32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return bool(h) and (h == hwnd or _u32.GetAncestor(h, 2) == hwnd)  # GA_ROOT


# --- grabber ------------------------------------------------------------------------------


class Grabber:
    """Captures the mapped client area as an RGB uint8 array (height, width, 3)."""

    def __init__(self, backend: str = "auto") -> None:
        self.backend = backend
        self.own: set[int] = set()       # this app's top-level windows
        self.excluded: set[int] = set()  # ... of which proven hidden from screen capture
        self._local = threading.local()
        self._pw_flags: dict[int, int] = {}         # hwnd -> PrintWindow flags that gave real content
        self._screen_since: dict[int, float] = {}   # hwnd -> when auto fell back to the screen
        self.last_backend = ""

    def exclude_window(self, hwnd: int) -> bool:
        """Register a window of this app and hide it from screen capture if Windows supports it."""
        self.own.add(hwnd)
        ok = exclude_from_capture(hwnd)
        if ok:
            self.excluded.add(hwnd)
        return ok

    def include_window(self, hwnd: int) -> None:
        """Show a window of this app in screen captures again (it then counts as an occluder)."""
        self.own.add(hwnd)
        include_in_capture(hwnd)
        self.excluded.discard(hwnd)

    def grab(self, m: Mapping) -> np.ndarray:
        try:
            img = self._grab(m)
        except CaptureError:
            raise
        except Exception as e:
            self._local.sct = None  # a broken mss handle is recreated on the next call
            raise CaptureError(f"screen capture failed: {e}") from e
        return check_frame(img, m)

    @staticmethod
    def _print(m: Mapping, flags: int) -> np.ndarray:
        try:
            return print_window(m.hwnd, m.width, m.height, flags)
        except CaptureError:  # PrintWindow occasionally fails once while the window is busy
            return print_window(m.hwnd, m.width, m.height, flags)

    def _window_frame(self, m: Mapping) -> tuple[np.ndarray | None, list[str]]:
        """(frame, []) from the first PrintWindow mode that gives real content, else (None, reasons).

        A mode that fails (PrintWindow/GetDC refused even after one retry) or returns a blank frame
        just counts as unusable; the caller decides between the next option and an error.
        """
        known = self._pw_flags.get(m.hwnd)
        modes = [known] + [f for f in PW_MODES if f != known] if known else list(PW_MODES)
        reasons = []
        for flags in modes:
            name = "full-content" if flags & PW_RENDERFULLCONTENT else "fast"
            try:
                img = self._print(m, flags)
            except CaptureError as e:
                reasons.append(f"{name} mode: {e}")
                continue
            if not is_blank(img):
                self._pw_flags[m.hwnd] = flags
                return img, []
            reasons.append(f"{name} mode: blank image")
        self._pw_flags.pop(m.hwnd, None)
        return None, reasons

    def _grab(self, m: Mapping) -> np.ndarray:
        if not m.hwnd or self.backend == "screen":
            return self._screen(m)
        since = self._screen_since.get(m.hwnd)
        if self.backend == "window" or since is None or time.monotonic() - since >= REPROBE_S:
            img, reasons = self._window_frame(m)
            if img is not None:
                self._screen_since.pop(m.hwnd, None)
                self.last_backend = "window"
                return img
            if self.backend == "window":
                refused = any("blank" not in r for r in reasons)
                raise CaptureError(
                    ("window capture failed: Windows refused PrintWindow for the game window"
                     if refused else
                     "window capture returned a blank image (the game may use hardware rendering that "
                     "PrintWindow cannot read, or it is minimized)")
                    + f" [{'; '.join(reasons)}]; set the capture backend to 'auto' (falls back to screen "
                    "capture) or 'screen'"
                )
            if since is None:
                log.warning("window capture unusable (%s); using screen capture, retrying window "
                            "capture every %.0f s", "; ".join(reasons), REPROBE_S)
            self._screen_since[m.hwnd] = time.monotonic()
        return self._screen(m)

    def _screen(self, m: Mapping) -> np.ndarray:
        client = (m.left, m.top, m.left + m.width, m.top + m.height)
        if m.hwnd:
            covers = overlapping(client, windows_above(m.hwnd), self.excluded)
            what = "the game window is covered by"
        else:  # whole screen: only this app's own windows are known to be in the way
            covers = overlapping(client, [WinInfo(h, "R2 target helper", _visible_rect(h))
                                          for h in self.own - self.excluded], set())
            what = "the captured area contains"
        if covers:
            names = ", ".join(f"'{w.title or hex(w.hwnd)}'" for w in covers[:3])
            raise CaptureError(f"{what} {names}; screen capture would include it. "
                               "Move that window off the game or bring the game to the front")
        self.last_backend = "screen"
        return self._mss_grab(m)

    def _mss_grab(self, m: Mapping) -> np.ndarray:
        sct = getattr(self._local, "sct", None)
        if sct is None:
            try:
                import mss

                sct = (getattr(mss, "MSS", None) or mss.mss)()
            except Exception:
                sct = False
            self._local.sct = sct
        if sct:
            shot = sct.grab({"left": m.left, "top": m.top, "width": m.width, "height": m.height})
            return np.asarray(shot)[..., 2::-1].copy()  # BGRA -> RGB
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(m.left, m.top, m.left + m.width, m.top + m.height), all_screens=True)
        return np.asarray(img.convert("RGB"))
