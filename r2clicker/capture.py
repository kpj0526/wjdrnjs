"""Fast screen capture of the game client area (mss, Pillow fallback)."""
from __future__ import annotations

import threading

import numpy as np

from .geometry import Mapping


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


class Grabber:
    """Captures the mapped client rectangle as an RGB uint8 array (height, width, 3).

    mss handles are thread-local, so one is created lazily per thread.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def _mss(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            try:
                import mss

                sct = mss.mss()
            except Exception:
                sct = False
            self._local.sct = sct
        return sct

    def grab(self, m: Mapping) -> np.ndarray:
        try:
            img = self._grab(m)
        except CaptureError:
            raise
        except Exception as e:
            self._local.sct = None  # a broken mss handle is recreated on the next call
            raise CaptureError(f"screen capture failed: {e}") from e
        return check_frame(img, m)

    def _grab(self, m: Mapping) -> np.ndarray:
        sct = self._mss()
        if sct:
            shot = sct.grab({"left": m.left, "top": m.top, "width": m.width, "height": m.height})
            return np.asarray(shot)[..., 2::-1].copy()  # BGRA -> RGB
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(m.left, m.top, m.left + m.width, m.top + m.height), all_screens=True)
        return np.asarray(img.convert("RGB"))
