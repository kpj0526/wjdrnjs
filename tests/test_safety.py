"""Failure handling: stop paths, window errors, focus loss, covered points, mouse recovery, dry-run guard."""
import threading
import time

import numpy as np
import pytest

from r2clicker.capture import CaptureError, Grabber, check_frame
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping, WindowNotFound
from r2clicker.winput import DryRunMouse, InputBlocked

from test_engine import POINTS, FakeGame, fast_settings, make_bot


class LiveFake(FakeGame):
    """FakeGame that claims to be the real mouse (to exercise live-only code paths)."""

    live = True


def run_in_thread(bot):
    t = threading.Thread(target=bot.run, daemon=True)
    t.start()
    return t


def wait_for(cond, timeout=5):
    end = time.perf_counter() + timeout
    while not cond():
        assert time.perf_counter() < end, "timed out"
        time.sleep(0.01)


def live_settings(**kw):
    return fast_settings(dry_run=False, corner_failsafe=False, emergency_hotkey="F12", **kw)


def live_bot(game, s, **kw):
    kw.setdefault("hotkey_fn", lambda k: False)
    kw.setdefault("foreground_fn", lambda h: True)
    kw.setdefault("point_fn", lambda h, x, y: True)
    return make_bot(game, s, **kw)


def test_window_not_found_stops_cleanly():
    game = FakeGame()

    def missing():
        raise WindowNotFound("no visible window title contains 'R2'")

    bot = Bot(fast_settings(), game, mapping_fn=missing)
    bot.run()
    assert "no visible window" in bot.stop_reason
    assert not game.clicks and game.released


def test_blocked_input_stops_with_its_message():
    game = FakeGame()

    def blocked(x, y):
        raise InputBlocked("SendInput was blocked; run this tool as administrator too")

    game.left_click = blocked
    bot = make_bot(game, fast_settings())
    bot.run()
    assert "administrator" in bot.stop_reason and game.released


def test_unexpected_mouse_error_stops_and_releases():
    game = FakeGame()

    def boom(x, y):
        raise OSError("device lost")

    game.right_click = boom
    bot = make_bot(game, fast_settings())
    bot.run()
    assert bot.stop_reason.startswith("error:") and game.released and bot.stop_event.is_set()


def test_frame_size_mismatch_detected():
    m = Mapping(0, 0, 1600, 900)
    with pytest.raises(CaptureError, match="DPI"):
        check_frame(np.zeros((720, 1280, 3), np.uint8), m)
    with pytest.raises(CaptureError):
        check_frame(None, m)
    assert check_frame(np.zeros((900, 1600, 4), np.uint8), m).shape == (900, 1600, 3)


def test_grabber_wraps_backend_errors(monkeypatch):
    g = Grabber()

    def fail(m):
        raise RuntimeError("mss died")

    monkeypatch.setattr(g, "_grab", fail)
    with pytest.raises(CaptureError, match="mss died"):
        g.grab(Mapping(0, 0, 10, 10))


def test_emergency_hotkey_stops_during_wait():
    game = FakeGame()
    pressed = threading.Event()
    bot = make_bot(game, fast_settings(wait_interval=30, emergency_hotkey="F12"),
                   hotkey_fn=lambda k: k == "F12" and pressed.is_set(), cursor_fn=lambda: None)
    t = run_in_thread(bot)
    wait_for(lambda: len(game.right_clicks) == len(POINTS))
    pressed.set()
    t.join(3)
    assert not t.is_alive() and bot.stop_reason == "emergency hotkey F12"
    assert len(game.right_clicks) == len(POINTS)


def test_emergency_hotkey_stops_mid_cycle():
    game = FakeGame()
    pressed = threading.Event()
    orig = game.left_click

    def left(x, y):
        orig(x, y)
        pressed.set()

    game.left_click = left
    bot = make_bot(game, fast_settings(point_delay=0.3, emergency_hotkey="F12"),
                   hotkey_fn=lambda k: pressed.is_set(), cursor_fn=lambda: None)
    bot.run()
    assert bot.stop_reason.startswith("emergency") and len(game.left_clicks) == 1


@pytest.mark.parametrize("corner, cursor, stops", [
    ((0, 0), (1, 2), True),
    ((-1920, 0), (-1919, 1), True),      # left monitor with negative coordinates
    ((0, -1080), (0, -1080), True),      # monitor above the primary one
    ((-1920, 0), (5, 5), False),
    ((0, 0), (500, 400), False),
])
def test_corner_failsafe_per_monitor(corner, cursor, stops):
    game = FakeGame()
    s = fast_settings(wait_interval=0.3, corner_failsafe=True, max_cycles=2)
    bot = make_bot(game, s, hotkey_fn=lambda k: False, cursor_fn=lambda: cursor, corner_fn=lambda x, y: corner)
    bot.run()
    assert (bot.stop_reason == "cursor in top-left corner (failsafe)") == stops, bot.stop_reason


def test_broken_safety_probe_stops_run():
    game = FakeGame()

    def bad_cursor():
        raise OSError("no desktop")

    bot = make_bot(game, fast_settings(wait_interval=30, corner_failsafe=True), hotkey_fn=lambda k: False,
                   cursor_fn=bad_cursor)
    t = run_in_thread(bot)
    t.join(3)
    assert not t.is_alive() and "watchdog" in bot.stop_reason


def test_dry_run_refuses_live_mouse():
    game = LiveFake()
    bot = make_bot(game, fast_settings(max_cycles=1, dry_run=True))
    assert isinstance(bot.mouse, DryRunMouse)
    bot.run()
    assert not game.clicks


def test_live_mode_pauses_while_game_not_foreground():
    game = LiveFake()
    focused = threading.Event()
    m = Mapping(game.m.left, game.m.top, 1600, 900, hwnd=1234)
    seen = []
    bot = Bot(live_settings(max_cycles=1), game, mapping_fn=lambda: (m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: seen.append(h) or focused.is_set(), point_fn=lambda h, x, y: True)
    t = run_in_thread(bot)
    time.sleep(0.6)
    assert not game.clicks and t.is_alive()  # paused, not clicking into another window
    focused.set()
    t.join(5)
    assert len(game.right_clicks) == len(POINTS) and seen[0] == 1234


def test_focus_lost_mid_cycle_stops_clicking():
    game = LiveFake()
    bot = live_bot(game, live_settings(), foreground_fn=lambda h: len(game.left_clicks) < 2)
    r = bot.run_cycle()
    assert r.skipped and len(game.left_clicks) == 2 and len(game.right_clicks) == 2


def test_live_clicks_skip_points_covered_by_other_windows():
    game = LiveFake()
    covered = game.m.to_screen(*POINTS[0])  # e.g. the helper window sits over the first point
    asked = []

    def point_fn(hwnd, x, y):
        asked.append((x, y))
        return (x, y) != covered

    r = live_bot(game, live_settings(), point_fn=point_fn).run_cycle()
    assert covered not in game.left_clicks and covered not in game.right_clicks
    assert r.clicked == POINTS[1:] and asked


def test_dry_run_does_not_consult_click_guard():
    game = FakeGame()
    bot = make_bot(game, fast_settings(), point_fn=lambda h, x, y: pytest.fail("not used in dry run"),
                   foreground_fn=lambda h: pytest.fail("not used in dry run"))
    assert bot.run_cycle().clicked == POINTS
