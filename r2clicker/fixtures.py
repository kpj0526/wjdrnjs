"""Synthetic frames for offline validation.

We have a real screenshot of the mob cluster but none with the selection
nameplate visible, so this draws an approximation of it: white Korean text
'활동성 문지기' with a dark outline and a green marker on each side.
Replace with a real crop (Settings.template_path) once one is available.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

NAME = "활동성 문지기"
GREEN = (40, 230, 40)
FONT_CANDIDATES = [r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc"]


def _font(size: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def draw_nameplate(img: Image.Image, center: tuple[int, int], size: int = 12, markers: bool = True) -> tuple[int, int, int, int]:
    """Draw the nameplate centred on `center`. Returns the text bbox."""
    d = ImageDraw.Draw(img)
    font = _font(size)
    x1, y1, x2, y2 = d.textbbox((0, 0), NAME, font=font)
    w, h = x2 - x1, y2 - y1
    tx, ty = center[0] - w // 2 - x1, center[1] - h // 2 - y1
    d.text((tx, ty), NAME, font=font, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
    bx1, by1, bx2, by2 = tx + x1, ty + y1, tx + x2, ty + y2
    if markers:
        cy = (by1 + by2) // 2
        for mx in (bx1 - 9, bx2 + 9):
            d.polygon([(mx, cy - 5), (mx + 5, cy), (mx, cy + 5), (mx - 5, cy)], fill=GREEN)
    return (bx1, by1, bx2, by2)


def frame_with_nameplate(base: Image.Image, center: tuple[int, int], **kw) -> np.ndarray:
    img = base.convert("RGB").copy()
    draw_nameplate(img, center, **kw)
    return np.asarray(img)


def jitter(frame: np.ndarray, seed: int, amount: int = 6) -> np.ndarray:
    """Small per-pixel noise, to mimic animation/compression differences between two frames."""
    rng = np.random.default_rng(seed)
    n = rng.integers(-amount, amount + 1, frame.shape, dtype=np.int16)
    return np.clip(frame.astype(np.int16) + n, 0, 255).astype(np.uint8)


def save_nameplate_template(path: str | Path, size: int = 12) -> None:
    """A tight crop of the synthetic nameplate on a dark background (template-mode fixture)."""
    img = Image.new("RGB", (120, 24), (40, 34, 26))
    bb = draw_nameplate(img, (60, 12), size=size, markers=False)
    img.crop((bb[0] - 1, bb[1] - 1, bb[2] + 1, bb[3] + 1)).save(path)
