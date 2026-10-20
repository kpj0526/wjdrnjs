"""Helper window placement: always reachable, centred by default, saved positions corrected."""
import pytest

from r2clicker.winplace import MARGIN, fit_geometry, parse_geometry

FULLHD = (0, 0, 1920, 1040)        # 1920x1080 minus a 40 px taskbar
LAPTOP = (0, 0, 1366, 728)
LEFT = (-1920, 0, 0, 1040)         # second monitor left of the primary (negative x)
ABOVE = (0, -1080, 1920, 0)        # second monitor above the primary (negative y)


def inside(w, h, x, y, area):
    l, t, r, b = area
    return l <= x and t <= y and x + w <= r and y + h <= b


@pytest.mark.parametrize("g, want", [
    ("1333x782+293+149", (1333, 782, 293, 149)),
    ("1200x800+-1500+20", (1200, 800, -1500, 20)),
    ("1200x800+10+-900", (1200, 800, 10, -900)),
    ("", None), ("garbage", None), ("0x10+1+1", None), ("100x100", None),
])
def test_parse_geometry(g, want):
    assert parse_geometry(g) == want


def test_default_is_centred_on_primary():
    w, h, x, y = fit_geometry(1333, 782, [FULLHD, LEFT])
    assert (w, h) == (1333, 782)
    assert abs((x + w / 2) - 960) <= 1 and abs((y + h / 2) - 520) <= 1


def test_too_big_for_a_small_screen_is_shrunk_and_fully_visible():
    w, h, x, y = fit_geometry(1333, 900, [LAPTOP])
    assert inside(w, h, x, y, LAPTOP)
    assert h == 728 - 2 * MARGIN and w == 1333


@pytest.mark.parametrize("saved, areas, expect_area", [
    ("1100x700+-1800+100", [FULLHD, LEFT], LEFT),        # kept on the left monitor
    ("1100x700+200+-1000", [FULLHD, ABOVE], ABOVE),      # kept on the monitor above
    ("1100x700+-1800+100", [FULLHD], FULLHD),            # that monitor was unplugged: back to primary
    ("1100x700+5000+5000", [FULLHD, LEFT], FULLHD),      # far off-screen
    ("1100x700+300+-500", [FULLHD], FULLHD),             # title bar above the screen: unreachable
    ("1100x700+1700+300", [FULLHD], FULLHD),             # mostly off the right edge: pulled in
])
def test_saved_position_is_corrected_onto_a_monitor(saved, areas, expect_area):
    w, h, x, y = fit_geometry(1333, 782, areas, saved)
    assert inside(w, h, x, y, expect_area), (w, h, x, y)
    assert (w, h) == (1100, 700)


def test_reachable_saved_position_is_kept_exactly():
    assert fit_geometry(1333, 782, [FULLHD], "1100x700+100+120") == (1100, 700, 100, 120)


def test_saved_size_larger_than_new_screen_is_shrunk():
    w, h, x, y = fit_geometry(1333, 782, [LAPTOP], "1800x1000+10+10")
    assert inside(w, h, x, y, LAPTOP)


def test_no_monitor_info_does_not_crash():
    assert fit_geometry(800, 600, []) == (800, 600, 0, 0)
