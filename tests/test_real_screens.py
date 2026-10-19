"""Real R2 screenshots from the customer's PC (1600x900, 2026-10-19):

- plain.png          nothing selected
- selected.png       after a left click: nameplate "황동석 문지기" with a green HP bar above it
- right_clicked.png  after left + right click: also the target panel at the bottom centre

The nameplate check and the right-click confirmation are calibrated on these.
"""
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from r2clicker.config import Settings
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping
from r2clicker.vision import target_panel_shown, verify

REAL = Path(__file__).resolve().parent / "real"
M = Mapping(0, 0, 1600, 900)
MOB = (540, 420)    # a click on the selected mob's body (its nameplate is at about (557, 322))


def load(name):
    return np.asarray(Image.open(REAL / f"{name}.png").convert("RGB"))


@pytest.fixture(scope="module")
def shots():
    return {n: load(n) for n in ("plain", "selected", "right_clicked")}


@pytest.mark.parametrize("name", ["selected", "right_clicked"])
def test_real_nameplate_is_found_near_the_click(shots, name):
    r = verify(shots[name], Settings(), M, near=MOB)
    assert r.ok, r.summary()
    bx1, by1, bx2, by2 = r.box
    assert bx1 <= 557 <= bx2 and by1 - 5 <= 322 <= by2 + 5  # on the real "황동석 문지기" text


def test_screen_without_a_selection_never_passes(shots):
    for near in [None, MOB, (800, 300), (1000, 500), (600, 600)]:
        r = verify(shots["plain"], Settings(), M, near=near)
        assert not r.ok, (near, r.summary())


def test_new_white_threshold_sits_between_real_text_and_background(shots):
    """0.3.x needed only 60 white px (the customer's false OKs had white=61); the plain screen
    already has ~55 in a text-sized box, the real nameplate ~320."""
    bg = verify(shots["plain"], Settings(plate_min_white=1), M).white
    real = verify(shots["selected"], Settings(), M, near=MOB).white
    assert bg < 60 < Settings().plate_min_white < real, (bg, real)


def test_far_click_does_not_take_the_nameplate(shots):
    r = verify(shots["selected"], Settings(), M, near=(1200, 650))
    assert not r.ok, r.summary()


@pytest.mark.parametrize("name, shown", [("right_clicked", True), ("selected", False), ("plain", False)])
def test_target_panel_marks_a_registered_right_click(shots, name, shown):
    ok, detail = target_panel_shown(shots[name], Settings(), M)
    assert ok is shown, detail


def test_target_panel_follows_a_scaled_client(shots):
    big = np.asarray(Image.fromarray(shots["right_clicked"]).resize((1920, 1080), Image.BILINEAR))
    ok, detail = target_panel_shown(big, Settings(), Mapping(0, 0, 1920, 1080))
    assert ok, detail


# --- the whole cycle on the real screens --------------------------------------------------------


class RealGame:
    """Shows plain.png until the mob is left clicked, selected.png after that, and right_clicked.png
    once a right click lands on the mob. ignore_right: how many right clicks the game drops."""

    live = False

    def __init__(self, shots, ignore_right=0):
        self.shots = shots
        self.m = Mapping(0, 0, 1600, 900)
        self.state = "plain"
        self.ignore_right = ignore_right
        self.left_clicks, self.right_clicks = [], []

    def move(self, x, y):
        pass

    def _on_mob(self, x, y):
        return math.hypot(x - MOB[0], y - MOB[1]) <= 40

    def left_click(self, x, y):
        self.left_clicks.append((x, y))
        if self._on_mob(x, y):
            self.state = "selected"

    def right_click(self, x, y):
        self.right_clicks.append((x, y))
        if self.state == "selected" and self._on_mob(x, y):
            if self.ignore_right:
                self.ignore_right -= 1
            else:
                self.state = "right_clicked"

    def release(self):
        pass

    def grab(self, m):
        return self.shots[self.state].copy()


def run_one(game, **kw):
    s = Settings(manual_points=[(1000, 500), (700, 600), MOB, (900, 300)], settle_delay=0, verify_delay=0,
                 verify_timeout=0, panel_timeout=0.1, wait_interval=0, emergency_hotkey="",
                 corner_failsafe=False, max_cycles=1, **kw)
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "real"))
    bot.run()
    return bot


def test_cycle_right_clicks_only_the_selected_mob_and_confirms(shots, caplog):
    game = RealGame(shots)
    with caplog.at_level("INFO", logger="r2clicker"):
        run_one(game)
    assert game.left_clicks == [(1000, 500), (700, 600), MOB]  # misses first, then the mob
    assert game.right_clicks == [MOB] and game.state == "right_clicked"
    assert "right click confirmed" in caplog.text


def test_dropped_right_click_is_sent_again(shots, caplog):
    game = RealGame(shots, ignore_right=1)
    with caplog.at_level("INFO", logger="r2clicker"):
        run_one(game)
    assert game.right_clicks == [MOB, MOB] and game.state == "right_clicked"
    assert "right clicking again" in caplog.text and "right click confirmed" in caplog.text


def test_right_click_never_registering_is_reported(shots, caplog):
    game = RealGame(shots, ignore_right=99)
    with caplog.at_level("INFO", logger="r2clicker"):
        run_one(game, right_click_retries=2)
    assert game.right_clicks == [MOB] * 3
    assert "right click NOT confirmed" in caplog.text


def test_confirmation_can_be_turned_off(shots):
    game = RealGame(shots, ignore_right=99)
    run_one(game, confirm_right_click=False)
    assert game.right_clicks == [MOB]
