"""Fast screen capture of the game client area (mss, Pillow fallback)."""
from __future__ import annotations

import threading

import numpy as np

from .geometry import Mapping


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
        sct = self._mss()
        if sct:
            shot = sct.grab({"left": m.left, "top": m.top, "width": m.width, "height": m.height})
            return np.asarray(shot)[..., 2::-1].copy()  # BGRA -> RGB
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(m.left, m.top, m.left + m.width, m.top + m.height), all_screens=True)
        return np.asarray(img.convert("RGB"))
