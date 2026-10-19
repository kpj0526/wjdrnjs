"""Manual candidate points: settings, validation, candidate order and the run loop (offline)."""
import json

import numpy as np
import pytest

from r2clicker.candidates import build_candidates, manual_point_reason
from r2clicker.config import MAX_MANUAL_POINTS, Settings
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping
from r2clicker.winput import DryRunMouse

from test_engine import FakeGame, fast_settings, make_bot
from test_safety import LiveFake

PTS = [(600, 300), (1000, 250), (500, 550)]  # inside the default ROI, away from player and HUD


def test_default_is_empty_and_valid():
    s = Settings()
    assert s.manual_points == [] and s.validate() == []


def test_roundtrip_keeps_order(tmp_path):
    p = tmp_path / "settings.json"
    Settings(manual_points=list(PTS)).save(p)
    assert json.loads(p.read_text(encoding="utf-8"))["manual_points"] == [list(x) for x in PTS]
    s = Settings.load(p)
    assert s.manual_points == PTS and all(isinstance(x, tuple) for x in s.manual_points)
    assert not s.load_warnings


@pytest.mark.parametrize("bad", ["600,300", [[1, 2, 3]], [5], 7, [["a", "b"]]])
def test_malformed_points_keep_default_with_warning(tmp_path, bad):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"manual_points": bad, "wait_interval": 2.0}), encoding="utf-8")
    s = Settings.load(p)
    assert s.manual_points == [] and s.wait_interval == 2.0
    assert any("manual_points" in w for w in s.load_warnings)


@pytest.mark.parametrize("pt, needle", [
    ((100, 400), "outside the ROI"),           # left of the ROI
    ((1700, 400), "outside the 1600x900"),     # off the client
    ((800, 440), "player"),                    # on the player
    ((360, 140), None),                        # just inside the ROI corner
])
def test_point_reasons(pt, needle):
    why = manual_point_reason(pt, Settings())
    assert (why is None) if needle is None else (needle in why), why


def test_hud_point_inside_roi_is_refused():
    s = Settings(ui_rects=[(550, 250, 650, 350)])
    assert "UI" in manual_point_reason((600, 300), s)


def test_unsafe_points_fail_validation_but_gui_can_skip_them():
    s = Settings(manual_points=[(600, 300), (800, 440), (100, 100)])
    errs = s.validate()
    assert any("manual point 2" in e and "player" in e for e in errs)
    assert any("manual point 3" in e and "ROI" in e for e in errs)
    assert s.validate(include_manual=False) == []


def test_too_many_points_refused():
    s = Settings(manual_points=[(600, 300)] * (MAX_MANUAL_POINTS + 1))
    assert any("at most" in e for e in s.validate())


def test_manual_points_replace_grid_in_order(base):
    s = Settings(manual_points=list(PTS), sticky_radius=500)
    # pixel scoring and the sticky last hit must not reorder the user's list
    cands = build_candidates(s, base, Mapping(0, 0, 1600, 900), last_success=PTS[-1])
    assert [(c.x, c.y) for c in cands] == PTS


def test_unsafe_manual_points_are_never_candidates():
    s = Settings(manual_points=[(800, 440), (600, 300), (100, 100)])
    assert [(c.x, c.y) for c in build_candidates(s)] == [(600, 300)]


def test_empty_manual_list_keeps_automatic_grid(base):
    m = Mapping(0, 0, 1600, 900)
    auto = build_candidates(Settings(), base, m)
    assert len(auto) > 50
    assert [(c.x, c.y) for c in build_candidates(Settings(manual_points=[]), base, m)] == [(c.x, c.y) for c in auto]


# --- run loop: same mapping and safety checks as grid candidates ----------------------------


def test_cycle_clicks_manual_points_in_order_with_window_offset(base_img):
    game = FakeGame(base_img, mob=PTS[2])
    s = fast_settings(manual_points=list(PTS))
    r = make_bot(game, s).run_cycle()
    assert r.success and r.attempts == 3 and r.tried == PTS
    assert game.left_clicks == [game.m.to_screen(*p) for p in PTS]  # client offset applied
    assert game.right_clicks == [game.left_clicks[-1]]


def test_max_attempts_caps_manual_points(base_img):
    game = FakeGame(base_img, selectable=False)
    r = make_bot(game, fast_settings(manual_points=list(PTS), max_attempts=2)).run_cycle()
    assert not r.success and r.tried == PTS[:2]


def test_scaled_client_maps_manual_points(base_img):
    from PIL import Image

    m = Mapping(100, 40, 1920, 1080)
    mouse = DryRunMouse()
    s = fast_settings(manual_points=list(PTS), max_cycles=1, max_consecutive_failed_cycles=1)
    big = np.asarray(base_img.resize((1920, 1080), Image.BILINEAR))
    Bot(s, lambda _m: big, mouse, mapping_fn=lambda: (m, "fake")).run()
    lefts = [a[1:] for a in mouse.actions if a[0] == "left"]
    assert lefts == [m.to_screen(*p) for p in PTS]


def test_run_with_unsafe_manual_point_never_clicks(base_img):
    game = FakeGame(base_img)
    bot = make_bot(game, fast_settings(manual_points=[(600, 300), (800, 440)]))
    bot.run()
    assert bot.stop_reason == "invalid settings" and not game.left_clicks


def test_covered_manual_point_is_skipped_live(base_img):
    game = LiveFake(base_img, mob=PTS[1])
    covered = game.m.to_screen(*PTS[0])
    s = fast_settings(manual_points=list(PTS), dry_run=False, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: True, point_fn=lambda h, x, y: (x, y) != covered)
    assert bot.live
    r = bot.run_cycle()
    assert r.success and covered not in game.left_clicks and r.tried == [PTS[1]]


def test_focus_loss_pauses_before_manual_clicks(base_img):
    game = LiveFake(base_img, mob=PTS[0])
    s = fast_settings(manual_points=list(PTS), dry_run=False, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: False, point_fn=lambda h, x, y: True)
    r = bot.run_cycle()
    assert r.skipped and not game.left_clicks


def test_dry_run_with_manual_points_sends_nothing(base_img):
    game = FakeGame(base_img, mob=PTS[0])
    mouse = DryRunMouse()
    Bot(fast_settings(manual_points=list(PTS), max_cycles=1, max_consecutive_failed_cycles=1), game.grab, mouse,
        mapping_fn=lambda: (game.m, "fake")).run()
    assert [a[1:] for a in mouse.actions if a[0] == "left"] == [game.m.to_screen(*p) for p in PTS]
    assert not game.left_clicks
