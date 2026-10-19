"""Candidate click points inside the ROI: grid, exclusions, ordering, optional pixel scoring.

Manual points (Settings.manual_points) replace the grid when there are any: they are used
as picked, in order, with the same ROI/player/HUD exclusions and no re-ranking.

Everything here works in reference coordinates. Pixel scoring takes a client
image plus a Mapping so it also works when the client is not 1600x900.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Rect, Settings
from .geometry import Mapping

ORDERS = ("center_out", "raster", "snake", "spiral")


@dataclass
class Candidate:
    x: int
    y: int
    score: float = 0.0


def grid_points(roi: Rect, step: int, stagger: bool = True) -> list[list[tuple[int, int]]]:
    """Grid rows inside the ROI, half a step in from the edges. Rows are returned top to bottom."""
    x1, y1, x2, y2 = roi
    step = max(5, int(step))
    rows: list[list[tuple[int, int]]] = []
    y = y1 + step // 2
    r = 0
    while y < y2:
        off = step // 2 if (stagger and r % 2) else 0
        x = x1 + step // 2 + off
        row = []
        while x < x2:
            row.append((x, y))
            x += step
        if row:
            rows.append(row)
        y += step
        r += 1
    return rows


def exclusion_reason(p: tuple[int, int], s: Settings) -> str | None:
    x, y = p
    cx, cy = s.player_center
    if s.player_radius > 0 and math.hypot(x - cx, y - cy) < s.player_radius:
        return "player"
    for (x1, y1, x2, y2) in s.ui_rects:
        if x1 <= x < x2 and y1 <= y < y2:
            return "ui"
    return None


def manual_point_reason(p, s: Settings) -> str | None:
    """Why a manual point must not be clicked, or None if it is safe (same rules as the grid)."""
    if len(p) != 2:
        return "needs x,y"
    x, y = p
    if not (0 <= x < s.ref_w and 0 <= y < s.ref_h):
        return f"outside the {s.ref_w}x{s.ref_h} game client"
    x1, y1, x2, y2 = s.roi
    if not (x1 <= x < x2 and y1 <= y < y2):
        return "outside the ROI"
    why = exclusion_reason((x, y), s)
    if why == "player":
        return "inside the player avoid radius"
    if why == "ui":
        return "inside a UI rect to avoid"
    return None


def _spiral_key(p, c):
    dx, dy = p[0] - c[0], p[1] - c[1]
    ring = max(abs(dx), abs(dy))
    ang = math.atan2(dy, dx) % (2 * math.pi)
    return (ring, ang)


def order_points(rows: list[list[tuple[int, int]]], order: str, center: tuple[float, float]) -> list[tuple[int, int]]:
    if order == "raster":
        return [p for row in rows for p in row]
    if order == "snake":
        return [p for i, row in enumerate(rows) for p in (row if i % 2 == 0 else row[::-1])]
    pts = [p for row in rows for p in row]
    if order == "spiral":
        return sorted(pts, key=lambda p: _spiral_key(p, center))
    if order == "center_out":
        return sorted(pts, key=lambda p: (round(math.hypot(p[0] - center[0], p[1] - center[1])), p[1], p[0]))
    raise ValueError(f"unknown order {order!r}; expected one of {ORDERS}")


def mob_scores(img: np.ndarray, pts: list[tuple[int, int]], mapping: Mapping, radius_ref: int) -> list[float]:
    """Cheap 'is something here' score per point: local texture (gradient energy) * brightness.

    The R2 floor is dark, flat stone; mobs are bright, busy models with moss.
    This is a ranking heuristic only, never a decision.
    """
    a = img[..., :3].astype(np.float32)
    lum = a.mean(axis=2)
    gx = np.abs(np.diff(lum, axis=1, append=lum[:, -1:]))
    gy = np.abs(np.diff(lum, axis=0, append=lum[-1:, :]))
    energy = (gx + gy) * (lum / 255.0)
    ii = np.pad(energy, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    h, w = lum.shape
    r = mapping.scale_len(radius_ref)
    out = []
    for (x, y) in pts:
        cx, cy = round(x * mapping.sx), round(y * mapping.sy)
        xa, xb = max(0, cx - r), min(w, cx + r + 1)
        ya, yb = max(0, cy - r), min(h, cy + r + 1)
        if xb <= xa or yb <= ya:
            out.append(0.0)
            continue
        total = ii[yb, xb] - ii[ya, xb] - ii[yb, xa] + ii[ya, xa]
        out.append(float(total / ((xb - xa) * (yb - ya))))
    return out


def build_candidates(
    s: Settings,
    image: np.ndarray | None = None,
    mapping: Mapping | None = None,
    last_success: tuple[int, int] | None = None,
) -> list[Candidate]:
    """Ordered candidate list for one cycle (reference coordinates)."""
    if s.manual_points:
        # the user's order is the order: no pixel scoring, no sticky re-ranking. Unsafe points
        # are dropped here too, although validate() already refuses a run that has any.
        return [Candidate(int(x), int(y)) for (x, y) in s.manual_points if manual_point_reason((x, y), s) is None]
    rows = grid_points(s.roi, s.grid_step, s.stagger)
    rows = [[p for p in row if exclusion_reason(p, s) is None] for row in rows]
    rows = [row for row in rows if row]
    x1, y1, x2, y2 = s.roi
    # center_out/spiral start at the player when it is inside the ROI: mobs gather around the player
    cx, cy = s.player_center
    if not (x1 <= cx < x2 and y1 <= cy < y2):
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    pts = order_points(rows, s.order, (cx, cy))
    cands = [Candidate(x, y) for (x, y) in pts]

    if image is not None and mapping is not None and s.prefer_mob_pixels:
        scores = mob_scores(image, pts, mapping, max(6, s.grid_step // 3))
        for c, sc in zip(cands, scores):
            c.score = sc
        if s.mob_score_min > 0:
            cands = [c for c in cands if c.score >= s.mob_score_min]
        # stable sort: score buckets first, the chosen pattern breaks ties
        top = max((c.score for c in cands), default=0.0) or 1.0
        cands.sort(key=lambda c: -round(4 * c.score / top))

    if last_success is not None and s.sticky_radius > 0:
        lx, ly = last_success
        near = [c for c in cands if math.hypot(c.x - lx, c.y - ly) <= s.sticky_radius]
        near.sort(key=lambda c: math.hypot(c.x - lx, c.y - ly))
        far = [c for c in cands if math.hypot(c.x - lx, c.y - ly) > s.sticky_radius]
        cands = near + far
    return cands
