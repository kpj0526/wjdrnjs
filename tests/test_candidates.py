import math

from r2clicker.candidates import build_candidates, exclusion_reason, grid_points, order_points
from r2clicker.config import Settings
from r2clicker.geometry import Mapping


def test_grid_stays_inside_roi():
    rows = grid_points((350, 130, 1250, 670), 60, stagger=False)
    pts = [p for r in rows for p in r]
    assert len(pts) == 15 * 9
    assert all(350 <= x < 1250 and 130 <= y < 670 for x, y in pts)
    assert pts[0] == (380, 160)


def test_stagger_offsets_odd_rows():
    rows = grid_points((0, 0, 200, 200), 50, stagger=True)
    assert rows[0][0][0] == 25 and rows[1][0][0] == 50


def test_exclusions():
    s = Settings()
    assert exclusion_reason((800, 440), s) == "player"
    assert exclusion_reason((1000, 750), s) == "ui"   # hotbar
    assert exclusion_reason((80, 80), s) == "ui"      # minimap
    assert exclusion_reason((600, 300), s) is None


def test_no_candidate_hits_player_or_ui():
    s = Settings()
    cands = build_candidates(s)
    assert cands
    for c in cands:
        assert exclusion_reason((c.x, c.y), s) is None
        x1, y1, x2, y2 = s.roi
        assert x1 <= c.x < x2 and y1 <= c.y < y2


def test_orders():
    rows = [[(0, 0), (10, 0), (20, 0)], [(0, 10), (10, 10), (20, 10)]]
    assert order_points(rows, "raster", (0, 0)) == [(0, 0), (10, 0), (20, 0), (0, 10), (10, 10), (20, 10)]
    assert order_points(rows, "snake", (0, 0)) == [(0, 0), (10, 0), (20, 0), (20, 10), (10, 10), (0, 10)]
    co = order_points(rows, "center_out", (10, 5))
    d = [math.hypot(x - 10, y - 5) for x, y in co]
    assert d == sorted(d)
    sp = order_points(rows, "spiral", (10, 5))
    assert sorted(sp) == sorted(p for r in rows for p in r)


def test_center_out_starts_next_to_player():
    s = Settings(prefer_mob_pixels=False, sticky_radius=0)
    cands = build_candidates(s)
    d = [math.hypot(c.x - 800, c.y - 440) for c in cands]
    assert d == sorted(d, key=round)
    assert d[0] >= s.player_radius


def test_mob_scoring_prefers_cluster_over_floor(base):
    s = Settings(sticky_radius=0)
    cands = build_candidates(s, base, Mapping(0, 0, 1600, 900))
    # the first 15 tries land on the mob cluster, not the empty floor near the ROI edges
    for c in cands[:15]:
        assert 520 <= c.x <= 1250 and 140 <= c.y <= 670, (c.x, c.y)
    first = {(c.x, c.y) for c in cands[:20]}
    assert (377, 157) not in first and (1229, 212) not in first


def test_sticky_last_success_first():
    s = Settings(prefer_mob_pixels=False, sticky_radius=100)
    cands = build_candidates(s, last_success=(500, 300))
    assert math.hypot(cands[0].x - 500, cands[0].y - 300) <= 40


def test_scaled_client_gives_same_ordering(base_img):
    import numpy as np
    from PIL import Image

    s = Settings(sticky_radius=0)
    a = build_candidates(s, np.asarray(base_img), Mapping(0, 0, 1600, 900))
    big = np.asarray(base_img.resize((1920, 1080), Image.BILINEAR))
    b = build_candidates(s, big, Mapping(0, 0, 1920, 1080))
    assert [(c.x, c.y) for c in a] == [(c.x, c.y) for c in b] or \
        len({(c.x, c.y) for c in a[:10]} & {(c.x, c.y) for c in b[:10]}) >= 7
