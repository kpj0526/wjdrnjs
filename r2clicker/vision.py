"""Screenshot-based selection check: did a white nameplate with green markers appear?

No learning involved: colour thresholds, a frame difference against the
pre-click baseline, and a box search with integral images. An optional
template (a cropped screenshot of the real nameplate) adds a binary
cosine-similarity match on the white mask.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .config import Rect, Settings
from .geometry import Mapping


@dataclass
class VerifyResult:
    ok: bool
    reason: str
    white: int = 0          # white pixels in the best text box
    green: int = 0          # green pixels around that box
    box: Rect | None = None  # best text box, reference coordinates
    template_score: float | None = None
    ms: float = 0.0

    def summary(self) -> str:
        t = f" tmpl={self.template_score:.2f}" if self.template_score is not None else ""
        b = f" box={self.box}" if self.box else ""
        return f"{'OK' if self.ok else 'no'} ({self.reason}) white={self.white} green={self.green}{t}{b} {self.ms:.0f}ms"


def white_mask(a: np.ndarray, s: Settings) -> np.ndarray:
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    return (mn >= s.white_min) & ((mx - mn) <= s.white_max_spread)


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    """Square binary dilation by r pixels (no wrap-around)."""
    if r <= 0:
        return m
    H, W = m.shape
    p = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy:dy + H, dx:dx + W]
    return out


def outlined_white(a: np.ndarray, s: Settings) -> np.ndarray:
    """White pixels with a dark pixel nearby: rendered text, not a bright glow."""
    dark = a.mean(axis=2) <= s.outline_dark_max
    return white_mask(a, s) & dilate(dark, s.outline_radius)


def _long_runs_1d(m: np.ndarray, n: int) -> np.ndarray:
    """Pixels that belong to a run of >= n consecutive True values along axis 1."""
    H, W = m.shape
    if n > W:
        return np.zeros_like(m)
    c = np.pad(m.astype(np.int32), ((0, 0), (1, 0))).cumsum(axis=1)
    full = (c[:, n:] - c[:, :-n]) == n  # window starting at x is all True
    out = np.zeros_like(m)
    for k in range(n):  # spread each full window over its n pixels
        out[:, k:k + full.shape[1]] |= full
    return out


def strip_long_runs(m: np.ndarray, n: int) -> np.ndarray:
    """Remove straight horizontal/vertical white runs (bars, frames, box rims). Text strokes are short."""
    if n <= 1:
        return m
    return m & ~_long_runs_1d(m, n) & ~_long_runs_1d(m.T, n).T


def green_mask(a: np.ndarray, s: Settings) -> np.ndarray:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (g >= s.green_min_g) & (g - r >= s.green_min_delta) & (g - b >= s.green_min_delta)


def _integral(m: np.ndarray) -> np.ndarray:
    return np.pad(m.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def _box_sums(ii: np.ndarray, bw: int, bh: int) -> np.ndarray:
    """Sum of every bw x bh window; result[y, x] is the window with top-left (x, y)."""
    return ii[bh:, bw:] - ii[:-bh, bw:] - ii[bh:, :-bw] + ii[:-bh, :-bw]


def _expanded_sums(ii: np.ndarray, bw: int, bh: int, m: int, shape: tuple[int, int]) -> np.ndarray:
    """For each bw x bh window position, the sum over that window grown by m on every side (clipped)."""
    H, W = shape
    ny, nx = H - bh + 1, W - bw + 1
    ys = np.arange(ny)
    xs = np.arange(nx)
    y0 = np.clip(ys - m, 0, H)[:, None]
    y1 = np.clip(ys + bh + m, 0, H)[:, None]
    x0 = np.clip(xs - m, 0, W)[None, :]
    x1 = np.clip(xs + bw + m, 0, W)[None, :]
    return ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]


def verify_area(s: Settings, mapping: Mapping, shape: tuple[int, int]) -> Rect:
    """ROI grown by verify_margin, in client pixels, clipped to the image."""
    x1, y1, x2, y2 = s.roi
    g = s.verify_margin
    cx1, cy1, cx2, cy2 = mapping.rect_to_client((x1 - g, y1 - g, x2 + g, y2 + g))
    H, W = shape
    return (max(0, cx1), max(0, cy1), min(W, cx2), min(H, cy2))


def load_template(path: str, s: Settings, scale: float = 1.0) -> np.ndarray | None:
    """White mask of a nameplate crop taken at reference scale, resized to the live client scale."""
    if not path:
        return None
    from PIL import Image

    try:
        img = Image.open(path).convert("RGB")
    except (OSError, ValueError) as e:
        logging.getLogger("r2clicker").warning("template %s unreadable (%s); using box search", path, e)
        return None
    if abs(scale - 1.0) > 0.01:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.BILINEAR)
    a = np.asarray(img).astype(np.int16)
    t = white_mask(a, s)
    return t if t.sum() >= 10 else None


def template_score(mask: np.ndarray, tmpl: np.ndarray) -> tuple[float, tuple[int, int]]:
    """Best binary cosine similarity of tmpl over mask (FFT correlation). Returns (score, (x, y))."""
    H, W = mask.shape
    th, tw = tmpl.shape
    if th > H or tw > W:
        return 0.0, (0, 0)
    fh, fw = H + th, W + tw
    f = np.fft.rfft2(mask.astype(np.float32), (fh, fw))
    t = np.fft.rfft2(tmpl[::-1, ::-1].astype(np.float32), (fh, fw))
    corr = np.fft.irfft2(f * t, (fh, fw))[th - 1:H, tw - 1:W]
    win = _box_sums(_integral(mask), tw, th)
    denom = np.sqrt(float(tmpl.sum()) * np.maximum(win, 1))
    score = corr / denom
    idx = int(np.argmax(score))
    y, x = divmod(idx, score.shape[1])
    return float(score[y, x]), (x, y)


def verify(
    after: np.ndarray,
    s: Settings,
    mapping: Mapping,
    before: np.ndarray | None = None,
    template: np.ndarray | None = None,
) -> VerifyResult:
    """Look for the selection nameplate in `after` (client-sized RGB array)."""
    import time

    t0 = time.perf_counter()
    if before is not None and before.shape != after.shape:
        return VerifyResult(False, "frame size changed since baseline")
    H, W = after.shape[:2]
    ax1, ay1, ax2, ay2 = verify_area(s, mapping, (H, W))
    a = after[ay1:ay2, ax1:ax2, :3].astype(np.int16)
    wm = outlined_white(a, s) if s.require_outline else white_mask(a, s)
    gm = green_mask(a, s)

    if s.verify_mode == "diff" and before is not None:
        b = before[ay1:ay2, ax1:ax2, :3].astype(np.int16)
        changed = np.abs(a - b).max(axis=2) >= s.diff_min
        wm &= changed
        gm &= changed

    # HUD text (buff timers, chat) is white too: never look there
    for r in [*s.ui_rects, *s.verify_ignore_rects]:
        x1, y1, x2, y2 = mapping.rect_to_client(r)
        wm[max(0, y1 - ay1):max(0, y2 - ay1), max(0, x1 - ax1):max(0, x2 - ax1)] = False
        gm[max(0, y1 - ay1):max(0, y2 - ay1), max(0, x1 - ax1):max(0, x2 - ax1)] = False

    wm = strip_long_runs(wm, mapping.scale_len(s.max_stroke_run))

    def done(ok, reason, **kw):
        return VerifyResult(ok, reason, ms=(time.perf_counter() - t0) * 1000, **kw)

    bw, bh = mapping.scale_len(s.plate_w), mapping.scale_len(s.plate_h)
    m = mapping.scale_len(s.marker_search)
    if wm.shape[0] < bh or wm.shape[1] < bw:
        return done(False, "verify area too small")

    if template is not None:
        tsc, (tx, ty) = template_score(wm, template)
        th, tw = template.shape
        box_c = (ax1 + tx, ay1 + ty, ax1 + tx + tw, ay1 + ty + th)
        gy0, gx0 = max(0, ty - m), max(0, tx - m)
        green = int(gm[gy0:ty + th + m, gx0:tx + tw + m].sum())
        white = int(wm[ty:ty + th, tx:tx + tw].sum())
        box = _client_box_to_ref(box_c, mapping)
        ok = tsc >= s.template_min_score and green >= s.marker_min_green
        reason = "template match" if ok else ("template weak" if tsc < s.template_min_score else "no green markers")
        return done(ok, reason, white=white, green=green, box=box, template_score=tsc)

    wsum = _box_sums(_integral(wm), bw, bh)
    gsum = _expanded_sums(_integral(gm), bw, bh, m, wm.shape)
    # text, not a flash: enough white but not a solid blob
    text_like = (wsum >= s.plate_min_white) & (wsum <= 0.75 * bw * bh)
    passing = text_like & (gsum >= s.marker_min_green)

    if passing.any():
        score = np.where(passing, wsum, -1)
    elif text_like.any():
        score = np.where(text_like, gsum, -1)  # report the box closest to passing
    else:
        score = wsum
    y, x = divmod(int(np.argmax(score)), score.shape[1])
    white, green = int(wsum[y, x]), int(gsum[y, x])
    box = _client_box_to_ref((ax1 + x, ay1 + y, ax1 + x + bw, ay1 + y + bh), mapping)
    if passing.any():
        return done(True, "nameplate", white=white, green=green, box=box)
    if text_like.any():
        return done(False, "white text but no green markers", white=white, green=green, box=box)
    return done(False, "no nameplate text", white=white, green=green, box=box)


def _client_box_to_ref(b: Rect, mapping: Mapping) -> Rect:
    x1, y1, x2, y2 = b
    return (round(x1 / mapping.sx), round(y1 / mapping.sy), round(x2 / mapping.sx), round(y2 / mapping.sy))
