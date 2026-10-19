"""Failure handling: stop paths, window/capture errors, focus loss, mouse recovery, dry-run guard."""
import threading
import time

import numpy as np
import pytest

from r2clicker.capture import CaptureError, Grabber, check_frame
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping, WindowNotFound
from r2clicker.winput import DryRunMouse

from test_engine import FakeGame, fast_settings, make_bot


class LiveFake(FakeGame):
    """FakeGame that claims to be the real mouse (to exercise live-only code paths)."""

    live = True


def run_in_thread(bot, timeout=5):
    t = threading.Thread(target=bot.run, daemon=True)
    t.start()
    return t


def wait_for(cond, timeout=5):
    end = time.perf_counter() + timeout
    while not cond():
        assert time.perf_counter() < end, "timed out"
        time.sleep(0.01)


def test_invalid_settings_never_click(base_img):
    game = FakeGame(base_img)
    bot = make_bot(game, fast_settings(max_attempts=0))
    bot.run()
    assert bot.stop_reason == "invalid settings" and not game.left_clicks


def test_window_not_found_stops_cleanly(base_img):
    game = FakeGame(base_img)

    def missing():
        raise WindowNotFound("no visible window title contains 'R2'")

    bot = Bot(fast_settings(), game.grab, game, mapping_fn=missing)
    bot.run()
    assert "no visible window" in bot.stop_reason
    assert not game.left_clicks and game.released


def test_capture_failure_stops_and_releases(base_img):
    game = FakeGame(base_img)

    def broken(m):
        raise CaptureError("screen capture failed: boom")

    bot = Bot(fast_settings(), broken, game, mapping_fn=lambda: (game.m, "fake"))
    bot.run()
    assert "capture failed" in bot.stop_reason and game.released and not game.left_clicks


def test_unexpected_mouse_error_stops_and_releases(base_img):
    game = FakeGame(base_img)

    def boom(x, y):
        raise OSError("device lost")

    game.left_click = boom
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


def test_emergency_hotkey_stops_during_wait(base_img):
    game = FakeGame(base_img)
    pressed = threading.Event()
    s = fast_settings(wait_interval=30, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"),
              hotkey_fn=lambda k: k == "F12" and pressed.is_set(), cursor_fn=lambda: None)
    t = run_in_thread(bot)
    wait_for(lambda: game.right_clicks)
    pressed.set()
    t.join(3)
    assert not t.is_alive() and bot.stop_reason == "emergency hotkey F12"
    assert len(game.right_clicks) == 1


def test_emergency_hotkey_stops_mid_cycle(base_img):
    game = FakeGame(base_img, selectable=False)
    pressed = threading.Event()
    orig = game.left_click

    def left(x, y):
        orig(x, y)
        if len(game.left_clicks) == 3:
            pressed.set()

    game.left_click = left
    s = fast_settings(verify_delay=0.1, verify_timeout=0.1, max_attempts=100, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"),
              hotkey_fn=lambda k: pressed.is_set(), cursor_fn=lambda: None)
    bot.run()
    assert bot.stop_reason.startswith("emergency") and len(game.left_clicks) <= 4


@pytest.mark.parametrize("corner, cursor, stops", [
    ((0, 0), (1, 2), True),
    ((-1920, 0), (-1919, 1), True),      # left monitor with negative coordinates
    ((0, -1080), (0, -1080), True),      # monitor above the primary one
    ((-1920, 0), (5, 5), False),
    ((0, 0), (500, 400), False),
])
def test_corner_failsafe_per_monitor(base_img, corner, cursor, stops):
    game = FakeGame(base_img)
    s = fast_settings(wait_interval=0.3, corner_failsafe=True, max_cycles=2, sticky_radius=120)
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"),
              hotkey_fn=lambda k: False, cursor_fn=lambda: cursor, corner_fn=lambda x, y: corner)
    bot.run()
    assert (bot.stop_reason == "cursor in top-left corner (failsafe)") == stops, bot.stop_reason


def test_broken_safety_probe_stops_run(base_img):
    game = FakeGame(base_img)

    def bad_cursor():
        raise OSError("no desktop")

    s = fast_settings(wait_interval=30, corner_failsafe=True)
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False, cursor_fn=bad_cursor)
    t = run_in_thread(bot)
    t.join(3)
    assert not t.is_alive() and "watchdog" in bot.stop_reason


def test_dry_run_refuses_live_mouse(base_img):
    game = LiveFake(base_img)
    bot = make_bot(game, fast_settings(max_cycles=1, dry_run=True))
    assert isinstance(bot.mouse, DryRunMouse)
    bot.run()
    assert not game.left_clicks and not game.right_clicks


def test_live_mode_pauses_while_game_not_foreground(base_img):
    game = LiveFake(base_img)
    focused = threading.Event()
    s = fast_settings(dry_run=False, corner_failsafe=False, emergency_hotkey="F12", max_cycles=1)
    m = Mapping(game.m.left, game.m.top, 1600, 900, hwnd=1234)
    seen = []
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: seen.append(h) or focused.is_set(), point_fn=lambda h, x, y: True)
    t = run_in_thread(bot)
    time.sleep(0.6)
    assert not game.left_clicks and t.is_alive()  # paused, not clicking into another window
    focused.set()
    t.join(5)
    assert game.right_clicks and seen[0] == 1234


def test_focus_lost_mid_cycle_stops_clicking(base_img):
    game = LiveFake(base_img, selectable=False)
    s = fast_settings(dry_run=False, corner_failsafe=False, emergency_hotkey="F12", max_attempts=20)
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: len(game.left_clicks) < 2, point_fn=lambda h, x, y: True)
    r = bot.run_cycle()
    assert r.skipped and len(game.left_clicks) == 2


def test_wait_interval_setting_drives_engine(base_img):
    # the same value the GUI writes into Settings.wait_interval is what the engine waits
    game = FakeGame(base_img)
    make_bot(game, fast_settings(wait_interval=0.25, max_cycles=2, sticky_radius=120)).run()
    t = game.right_click_times[0]
    wait = min(g for g in game.grab_times if g > t) - t
    assert 0.25 <= wait <= 0.45, wait


def test_live_clicks_skip_points_covered_by_other_windows(base_img):
    game = LiveFake(base_img)
    s = fast_settings(dry_run=False, corner_failsafe=False, emergency_hotkey="F12")
    covered = set()
    asked = []

    def point_fn(hwnd, x, y):
        asked.append((x, y))
        return (x, y) not in covered

    ref_bot = make_bot(FakeGame(base_img), fast_settings())
    first = ref_bot.run_cycle().tried[0]
    covered.add(game.m.to_screen(*first))  # e.g. the helper window sits over the first point
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: True, point_fn=point_fn)
    r = bot.run_cycle()
    assert game.m.to_screen(*first) not in game.left_clicks
    assert r.success and game.right_clicks and asked


def test_right_click_not_sent_when_its_point_is_covered(base_img):
    game = LiveFake(base_img)
    s = fast_settings(dry_run=False, corner_failsafe=False, emergency_hotkey="F12")
    bot = Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"), hotkey_fn=lambda k: False,
              foreground_fn=lambda h: True, point_fn=lambda h, x, y: not game.selected)
    r = bot.run_cycle()
    assert game.selected and not game.right_clicks and r.skipped == "right-click point covered"


def test_dry_run_does_not_consult_click_guard(base_img):
    game = FakeGame(base_img)
    bot = Bot(fast_settings(), game.grab, game, mapping_fn=lambda: (game.m, "fake"),
              point_fn=lambda h, x, y: pytest.fail("not used in dry run"))
    assert bot.run_cycle().success
