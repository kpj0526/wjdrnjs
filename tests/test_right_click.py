"""Guards and diagnostics around the right click: re-mapping a moved window, focus right before
the right click, the park target and the dry-run log. Offline, never clicks."""
import logging

import pytest

from r2clicker.config import Settings
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping

from test_engine import FakeGame, fast_settings, make_bot
from test_preflight import pf, status
from test_safety import LiveFake


@pytest.fixture
def logs(caplog):
    """Engine log lines (the GUI tests may turn off propagation of the r2clicker logger)."""
    lg = logging.getLogger("r2clicker")
    lg.addHandler(caplog.handler)
    old = lg.level
    lg.setLevel(logging.INFO)
    yield lambda: caplog.text
    lg.removeHandler(caplog.handler)
    lg.setLevel(old)


def test_dry_run_right_click_is_logged_as_not_sent(base_img, logs):
    game = FakeGame(base_img)
    r = make_bot(game, fast_settings()).run_cycle()
    assert r.success and game.right_clicks == [game.left_clicks[-1]]
    assert "right click on the mob at screen" in logs() and "[DRY RUN: not sent]" in logs()


def test_window_moved_during_check_remaps_the_right_click(base_img, logs):
    game = FakeGame(base_img)
    m1, m2 = game.m, Mapping(game.m.left + 30, game.m.top + 20, 1600, 900)
    calls = []

    def mapping():
        calls.append(1)
        return (m1 if len(calls) == 1 else m2), "fake"

    s = fast_settings()
    r = Bot(s, game.grab, game, mapping_fn=mapping).run_cycle()
    assert r.success and len(calls) == 2
    assert game.right_clicks == [m2.to_screen(r.candidate.x, r.candidate.y)]
    assert game.cursor == m2.to_screen(*s.park_point)
    assert "moved/resized" in logs()


def test_unchanged_window_keeps_the_left_click_point(base_img, logs):
    game = FakeGame(base_img)
    make_bot(game, fast_settings()).run_cycle()
    assert game.right_clicks == [game.left_clicks[-1]] and "moved/resized" not in logs()


def test_focus_lost_before_right_click_sends_nothing(base_img, logs):
    game = LiveFake(base_img)
    s = fast_settings(dry_run=False, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: not game.selected, point_fn=lambda h, x, y: True)
    r = bot.run_cycle()
    assert game.selected and not game.right_clicks and r.skipped == "game window lost focus"
    assert "lost focus before the right click" in logs()


def test_park_target_is_flagged(base_img, logs):
    game = FakeGame(base_img)
    s = fast_settings(right_click_target="park", max_cycles=1)
    make_bot(game, s).run()
    assert game.right_clicks == [game.m.to_screen(*s.park_point)]
    text = logs()
    assert "right_click_target=park" in text and "PARK POINT (not on the mob)" in text
    assert status(pf(Settings(right_click_target="park")), "right click") == ["warn"]
    assert status(pf(), "right click") == ["ok"]


def test_failed_cycle_says_why_there_was_no_right_click(base_img, logs):
    game = FakeGame(base_img, selectable=False)
    make_bot(game, fast_settings(max_attempts=3)).run_cycle()
    assert "no right click this cycle: the nameplate check never passed" in logs()


def test_run_logs_the_right_click_setup_and_dry_run(base_img, logs):
    make_bot(FakeGame(base_img), fast_settings(max_cycles=1)).run()
    text = logs()
    assert "right click: target=same api=mouse_event" in text and "confirm=off" in text
    assert "DRY RUN: no click reaches the game" in text


def test_unconfirmed_dry_run_right_click_says_nothing_was_sent(base_img, logs):
    game = FakeGame(base_img)  # the synthetic game never shows the target panel
    make_bot(game, fast_settings(confirm_right_click=True, panel_timeout=0, right_click_retries=0)).run_cycle()
    assert "right click NOT confirmed" in logs() and "DRY RUN: nothing was sent" in logs()
