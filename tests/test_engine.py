"""The auto-click loop against a fake mouse: order, left -> right on every point, timing."""
import threading
import time

from r2clicker.config import Settings
from r2clicker.engine import Bot
from r2clicker.geometry import Mapping
from r2clicker.winput import DryRunMouse

OFFSET = (200, 50)  # game client is not at the screen origin
POINTS = [(600, 300), (1000, 250), (820, 520)]


class FakeGame:
    """Records every click (screen coordinates) with a timestamp. Doubles as the mouse."""

    live = False

    def __init__(self, width=1600, height=900):
        self.m = Mapping(OFFSET[0], OFFSET[1], width, height)
        self.clicks = []  # (button, x, y)
        self.times = []   # (button, t)
        self.released = False

    def move(self, x, y):
        pass

    def left_click(self, x, y):
        self.clicks.append(("left", x, y))
        self.times.append(("left", time.perf_counter()))

    def right_click(self, x, y):
        self.clicks.append(("right", x, y))
        self.times.append(("right", time.perf_counter()))

    def release(self):
        self.released = True

    @property
    def left_clicks(self):
        return [c[1:] for c in self.clicks if c[0] == "left"]

    @property
    def right_clicks(self):
        return [c[1:] for c in self.clicks if c[0] == "right"]


def fast_settings(**kw):
    base = dict(right_click_delay=0, point_delay=0, wait_interval=0, corner_failsafe=False, emergency_hotkey="",
                manual_points=list(POINTS))
    base.update(kw)
    return Settings(**base)


def make_bot(game, s, **kw):
    return Bot(s, game, mapping_fn=lambda: (game.m, "fake"), **kw)


def test_every_point_gets_left_then_right_click_in_order():
    game = FakeGame()
    r = make_bot(game, fast_settings()).run_cycle()
    expect = []
    for x, y in POINTS:
        sx, sy = game.m.to_screen(x, y)  # shifted by the window position
        expect += [("left", sx, sy), ("right", sx, sy)]
    assert game.clicks == expect
    assert r.clicked == POINTS and not r.skipped


def test_points_follow_the_window_scale():
    game = FakeGame(1920, 1080)
    make_bot(game, fast_settings(manual_points=[(800, 450)])).run_cycle()
    assert game.clicks == [("left", 200 + 960, 50 + 540), ("right", 200 + 960, 50 + 540)]


def test_right_click_follows_left_click_after_right_click_delay():
    game = FakeGame()
    make_bot(game, fast_settings(manual_points=[(600, 300)], right_click_delay=0.15)).run_cycle()
    (b1, t1), (b2, t2) = game.times
    assert (b1, b2) == ("left", "right") and 0.15 <= t2 - t1 < 0.15 + 0.15


def test_right_click_right_away_by_default():
    assert Settings().right_click_delay == 0 and Settings().right_click_hover == 0
    game = FakeGame()
    make_bot(game, fast_settings(manual_points=[(600, 300)], right_click_delay=Settings().right_click_delay)).run_cycle()
    (_, t1), (_, t2) = game.times
    assert t2 - t1 < 0.05


def test_pause_between_points_not_after_the_last():
    game = FakeGame()
    t0 = time.perf_counter()
    make_bot(game, fast_settings(point_delay=0.1)).run_cycle()
    rights = [t for b, t in game.times if b == "right"]
    lefts = [t for b, t in game.times if b == "left"]
    gaps = [lefts[i + 1] - rights[i] for i in range(len(POINTS) - 1)]
    assert all(0.1 <= g < 0.1 + 0.15 for g in gaps), gaps
    assert time.perf_counter() - rights[-1] < 0.05  # the cycle ends right after the last right click
    assert rights[-1] - t0 < 0.1 * len(POINTS)


def test_wait_interval_runs_from_last_right_click_to_next_first_left_click():
    game = FakeGame()
    make_bot(game, fast_settings(wait_interval=0.4, max_cycles=3)).run()
    assert len(game.left_clicks) == 3 * len(POINTS)
    n = 2 * len(POINTS)
    waits = [game.times[(c + 1) * n][1] - game.times[(c + 1) * n - 1][1] for c in range(2)]
    assert all(0.4 <= w <= 0.4 + 0.2 for w in waits), waits


def test_max_cycles():
    game = FakeGame()
    bot = make_bot(game, fast_settings(max_cycles=4))
    bot.run()
    assert len(game.right_clicks) == 4 * len(POINTS) and bot.stop_reason == "max cycles reached"


def test_no_points_never_clicks():
    game = FakeGame()
    bot = make_bot(game, fast_settings(manual_points=[]))
    bot.run()
    assert bot.stop_reason == "invalid settings" and not game.clicks


def test_stop_interrupts_wait():
    game = FakeGame()
    bot = make_bot(game, fast_settings(wait_interval=30))
    t = threading.Thread(target=bot.run)
    t0 = time.perf_counter()
    t.start()
    while len(game.right_clicks) < len(POINTS):
        time.sleep(0.01)
    bot.stop("test")
    t.join(2)
    assert not t.is_alive() and time.perf_counter() - t0 < 5 and game.released


def test_stop_during_the_pause_between_points_clicks_nothing_more():
    game = FakeGame()
    bot = make_bot(game, fast_settings(point_delay=0.3))
    t = threading.Thread(target=bot.run)
    t.start()
    while not game.right_clicks:
        time.sleep(0.005)
    bot.stop("test")
    t.join(2)
    sx, sy = game.m.to_screen(*POINTS[0])
    assert game.clicks == [("left", sx, sy), ("right", sx, sy)]


def test_dry_run_mouse_records_only():
    game = FakeGame()
    mouse = DryRunMouse()
    Bot(fast_settings(max_cycles=1), mouse, mapping_fn=lambda: (game.m, "fake")).run()
    assert [a[0] for a in mouse.actions].count("left") == len(POINTS)
    assert [a[0] for a in mouse.actions].count("right") == len(POINTS)
    assert not game.clicks  # nothing reached the "game"
