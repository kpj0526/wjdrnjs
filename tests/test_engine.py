"""Whole select/verify/right-click loop against a simulated game screen."""
import math
import threading
import time

import numpy as np

from r2clicker.candidates import build_candidates
from r2clicker.config import Settings
from r2clicker.engine import Bot
from r2clicker.fixtures import draw_nameplate, jitter
from r2clicker.geometry import Mapping
from r2clicker.winput import DryRunMouse

OFFSET = (200, 50)  # game client is not at the screen origin


def mob_spot(base_img, rank=10):
    """A mob position the real candidate ordering reaches within max_attempts (its rank-th point)."""
    c = build_candidates(Settings(sticky_radius=0), np.asarray(base_img), Mapping(0, 0, 1600, 900))[rank - 1]
    return (c.x, c.y)


class FakeGame:
    """Selecting works only by left clicking within `radius` of the mob. Then a nameplate floats
    above the mob and drifts a little each frame. Hovering the mob (cursor not parked) shows a
    white hover label without green markers, which must not count as selected."""

    live = False

    def __init__(self, base_img, mob=None, radius=25, selectable=True):
        self.base_img = base_img
        self.mob = mob or mob_spot(base_img)
        self.radius = radius
        self.selectable = selectable
        self.m = Mapping(OFFSET[0], OFFSET[1], 1600, 900)
        self.selected = False
        self.cursor = (0, 0)
        self.frames = 0
        self.left_clicks = []
        self.right_clicks = []
        self.right_click_times = []
        self.grab_times = []

    def _on_mob(self, x, y):
        rx, ry = self.m.to_ref(x, y)
        return math.hypot(rx - self.mob[0], ry - self.mob[1]) <= self.radius

    # mouse interface
    def move(self, x, y):
        self.cursor = (x, y)

    def left_click(self, x, y):
        self.cursor = (x, y)
        self.left_clicks.append((x, y))
        self.selected = self.selectable and self._on_mob(x, y)

    def right_click(self, x, y):
        self.cursor = (x, y)
        self.right_clicks.append((x, y))
        self.right_click_times.append(time.perf_counter())

    def release(self):
        self.released = True

    # capture interface
    def grab(self, m):
        assert (m.width, m.height) == (1600, 900)
        self.frames += 1
        self.grab_times.append(time.perf_counter())
        img = self.base_img.copy()
        if self._on_mob(*self.cursor):
            draw_nameplate(img, (self.mob[0], self.mob[1] - 60), markers=False)  # hover label
        if self.selected:
            drift = (self.frames % 5) * 3  # the label moves with the mob
            draw_nameplate(img, (self.mob[0] + drift, self.mob[1] - 60 - drift))
        return jitter(np.asarray(img), self.frames, 4)


def fast_settings(**kw):
    base = dict(settle_delay=0, verify_delay=0.0, verify_timeout=0.0, right_click_delay=0, wait_interval=0,
                corner_failsafe=False, emergency_hotkey="", sticky_radius=0)
    base.update(kw)
    return Settings(**base)


def make_bot(game, s):
    return Bot(s, game.grab, game, mapping_fn=lambda: (game.m, "fake"))


def test_cycle_selects_then_right_clicks(base_img):
    game = FakeGame(base_img)
    s = fast_settings()
    bot = make_bot(game, s)
    r = bot.run_cycle()
    assert r.success, r
    # exactly as many left clicks as there are candidates ahead of the first hit in the order
    expected = build_candidates(s, np.asarray(base_img), Mapping(0, 0, 1600, 900))
    mx, my = game.mob
    first_hit = next(i for i, c in enumerate(expected, 1) if math.hypot(c.x - mx, c.y - my) <= 25)
    assert first_hit <= 10
    assert r.attempts == first_hit == len(game.left_clicks)
    m = game.m
    for x, y in game.left_clicks:  # inside the ROI, shifted by the window position
        rx, ry = m.to_ref(x, y)
        assert 350 <= rx < 1250 and 130 <= ry < 670
    assert game.right_clicks == [game.left_clicks[-1]]
    assert game.cursor == m.to_screen(*s.park_point)
    assert bot.last_success == (r.candidate.x, r.candidate.y)


def test_hover_label_alone_never_counts(base_img):
    game = FakeGame(base_img, selectable=False)
    s = fast_settings(max_attempts=60)
    r = make_bot(game, s).run_cycle()
    assert not r.success and r.attempts == 60 and not game.right_clicks


def test_max_attempts_limits_clicks(base_img):
    game = FakeGame(base_img, selectable=False)
    r = make_bot(game, fast_settings(max_attempts=7)).run_cycle()
    assert not r.success and len(game.left_clicks) == 7 and not game.right_clicks


def test_run_stops_after_consecutive_failures(base_img):
    game = FakeGame(base_img, selectable=False)
    bot = make_bot(game, fast_settings(max_attempts=3, max_consecutive_failed_cycles=2))
    bot.run()
    assert len(game.left_clicks) == 6 and bot.stop_event.is_set()


def test_sticky_second_cycle_hits_first_try(base_img):
    game = FakeGame(base_img)
    bot = make_bot(game, fast_settings(sticky_radius=120))
    assert bot.run_cycle().success
    game.selected = False
    n = len(game.left_clicks)
    assert bot.run_cycle().success
    assert len(game.left_clicks) - n == 1


def test_wait_interval_is_respected(base_img):
    game = FakeGame(base_img)
    make_bot(game, fast_settings(wait_interval=0.4, max_cycles=3, sticky_radius=120)).run()
    assert len(game.right_click_times) == 3
    # The interval runs from the end of a cycle (its right click) to the start of the next cycle
    # (its baseline screenshot). Right-click-to-right-click would also include the next cycle's
    # capture/scoring/verify work, which depends on machine load.
    waits = [min(g for g in game.grab_times if g > t) - t for t in game.right_click_times[:-1]]
    assert all(0.4 <= w <= 0.4 + 0.2 for w in waits), waits


def test_stop_interrupts_wait(base_img):
    game = FakeGame(base_img)
    bot = make_bot(game, fast_settings(wait_interval=30))
    t = threading.Thread(target=bot.run)
    t0 = time.perf_counter()
    t.start()
    while not game.right_clicks:
        time.sleep(0.01)
    bot.stop("test")
    t.join(2)
    assert not t.is_alive() and time.perf_counter() - t0 < 5


def test_dry_run_mouse_records_only(base_img):
    game = FakeGame(base_img)
    mouse = DryRunMouse()
    bot = Bot(fast_settings(max_attempts=5, max_cycles=1), game.grab, mouse, mapping_fn=lambda: (game.m, "fake"))
    bot.run()
    assert [a[0] for a in mouse.actions].count("left") == 5
    assert not game.left_clicks  # nothing reached the "game"
