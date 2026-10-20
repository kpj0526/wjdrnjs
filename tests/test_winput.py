"""Win32Mouse against a recording user32: what the game actually receives, without real input."""
import sys
import time

import pytest

from r2clicker import gui, winput
from r2clicker.config import Settings

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 input")

LEFT_DOWN, LEFT_UP = winput.MOUSEEVENTF_LEFTDOWN, winput.MOUSEEVENTF_LEFTUP
RIGHT_DOWN, RIGHT_UP = winput.MOUSEEVENTF_RIGHTDOWN, winput.MOUSEEVENTF_RIGHTUP


class FakeUser32:
    """Records SendInput/SetCursorPos with timestamps. Virtual desktop: 3200x900 starting at x=-1600."""

    metrics = {76: -1600, 77: 0, 78: 3200, 79: 900}

    def __init__(self, block=False):
        self.events = []  # (t, kind, flags, dx, dy) or (t, "pos", x, y); mouse_event is kind "input" too
        self.block = block

    def mouse_event(self, f, dx, dy, data, extra):
        self.events.append((time.perf_counter(), "input", f, dx, dy))

    def SendInput(self, n, ref, size):
        mi = ref._obj.mi
        self.events.append((time.perf_counter(), "input", mi.dwFlags, mi.dx, mi.dy))
        return 0 if self.block else 1

    def SetCursorPos(self, x, y):
        self.events.append((time.perf_counter(), "pos", x, y))
        return 1

    def GetSystemMetrics(self, i):
        return self.metrics[i]

    def inputs(self):
        return [e for e in self.events if e[1] == "input"]

    def time_of(self, flags):
        return next(e[0] for e in self.events if e[1] == "input" and e[2] == flags)


@pytest.fixture
def mouse(monkeypatch):
    m = winput.Win32Mouse(right_hover_s=0.08, right_press_s=0.12, right_api="sendinput")
    m._u = FakeUser32()
    monkeypatch.setattr(winput, "cursor_pos", lambda: (1500, 300))
    return m


def test_right_click_never_moves_the_cursor_with_sendinput(mouse):
    """Absolute SendInput moves reach R2's raw input as a jump and it ignores the right click:
    the cursor is placed with SetCursorPos only, exactly like the left click."""
    mouse.right_click(1012, 633)
    assert [e[2] for e in mouse._u.inputs()] == [RIGHT_DOWN, RIGHT_UP]
    kinds = [(e[1], e[2]) if e[1] == "input" else (e[1], (e[2], e[3])) for e in mouse._u.events]
    assert kinds == [("pos", (1012, 633)), ("input", RIGHT_DOWN), ("input", RIGHT_UP)]
    assert not hasattr(winput, "MOUSEEVENTF_ABSOLUTE") and not hasattr(mouse, "glide")


def test_right_click_rests_on_target_then_clicks_like_the_left_click(mouse):
    mouse.right_click(1012, 633)
    pinned = next(e[0] for e in mouse._u.events if e[1] == "pos")
    down, up = mouse._u.time_of(RIGHT_DOWN), mouse._u.time_of(RIGHT_UP)
    assert down - pinned >= 0.08 - 0.005  # the configured rest
    assert 0.12 - 0.005 <= up - down < 0.12 + 0.08  # the configured right press time


def test_left_click_is_unchanged(mouse):
    mouse.left_click(900, 500)
    assert [e[2] for e in mouse._u.inputs()] == [LEFT_DOWN, LEFT_UP]
    assert 0.03 - 0.005 <= mouse._u.time_of(LEFT_UP) - mouse._u.time_of(LEFT_DOWN) < 0.1


def test_right_click_on_the_cursor_position_goes_out_at_once(monkeypatch):
    m = winput.Win32Mouse(right_hover_s=0)
    m._u = FakeUser32()
    monkeypatch.setattr(winput, "cursor_pos", lambda: (900, 500))
    t0 = time.perf_counter()
    m.right_click(900, 500)
    assert [e[2] for e in m._u.inputs()] == [RIGHT_DOWN, RIGHT_UP]  # no move input at all
    assert m._u.time_of(RIGHT_DOWN) - t0 < 0.01


def test_blocked_sendinput_raises_input_blocked(monkeypatch):
    m = winput.Win32Mouse(right_api="sendinput")
    m._u = FakeUser32(block=True)
    monkeypatch.setattr(winput, "cursor_pos", lambda: (0, 0))
    with pytest.raises(winput.InputBlocked):
        m.right_click(10, 10)
    assert [e[2] for e in m._u.inputs()] == [RIGHT_DOWN]  # the refused press is all that was tried


def test_right_click_timing_settings_validate():
    assert Settings().validate() == []
    errs = Settings(right_click_hover=5, right_click_press=0).validate()
    assert any("right_click_hover" in e for e in errs) and any("right_click_press" in e for e in errs)


def test_gui_form_offers_the_right_click_timing():
    names = [f[0] for f in gui.FORM]
    assert "right_click_hover" in names and "right_click_press" in names


def test_default_right_press_is_longer_than_the_left_click(monkeypatch):
    assert Settings().right_click_press == 0.15
    m = winput.Win32Mouse()
    m._u = FakeUser32()
    monkeypatch.setattr(winput, "cursor_pos", lambda: (900, 500))
    m.left_click(900, 500)
    m.right_click(900, 500)
    left = m._u.time_of(LEFT_UP) - m._u.time_of(LEFT_DOWN)
    right = m._u.time_of(RIGHT_UP) - m._u.time_of(RIGHT_DOWN)
    assert left < 0.1 and 0.15 - 0.005 <= right < 0.15 + 0.08, (left, right)


def test_mouse_event_api_sends_the_same_right_click(monkeypatch):
    m = winput.Win32Mouse(right_hover_s=0, right_press_s=0.05, right_api="mouse_event")
    fake = FakeUser32()
    legacy = []
    fake.mouse_event = lambda f, x, y, d, e: legacy.append((time.perf_counter(), f))
    fake.SendInput = lambda n, ref, size: fake.events.append((0, "sendinput", ref._obj.mi.dwFlags)) or 1
    m._u = fake
    monkeypatch.setattr(winput, "cursor_pos", lambda: (900, 500))
    m.right_click(900, 500)
    assert [f for _, f in legacy] == [RIGHT_DOWN, RIGHT_UP]
    assert legacy[1][0] - legacy[0][0] >= 0.05 - 0.005
    assert not [e for e in fake.events if e[1] == "sendinput"]  # nothing went through SendInput
    m.left_click(900, 500)
    assert [e[2] for e in fake.events if e[1] == "sendinput"] == [LEFT_DOWN, LEFT_UP]  # left click unchanged


def test_right_click_here_does_not_move_the_cursor(monkeypatch):
    m = winput.Win32Mouse(right_press_s=0.01)
    m._u = FakeUser32()
    m.right_click_here()
    assert [e[2] for e in m._u.inputs()] == [RIGHT_DOWN, RIGHT_UP]
    assert not [e for e in m._u.events if e[1] == "pos"]


def test_unknown_api_is_refused():
    with pytest.raises(ValueError):
        winput.Win32Mouse(right_api="hid")


def test_the_right_button_defaults_to_mouse_event():
    assert Settings().right_click_api == "mouse_event"
    assert winput.Win32Mouse().right_api == "mouse_event"


class PostUser32(FakeUser32):
    """Adds the window functions: the game window's client starts at screen (100, 50)."""

    def __init__(self, posted=True):
        super().__init__()
        self.posted = posted

    def WindowFromPoint(self, pt):
        return 0x1234

    def ScreenToClient(self, hwnd, ref):
        ref._obj.x -= 100
        ref._obj.y -= 50
        return 1

    def PostMessageW(self, hwnd, msg, wp, lp):
        self.events.append((time.perf_counter(), "post", msg, wp, (lp & 0xFFFF, lp >> 16), hwnd))
        return 1 if self.posted else 0


def test_postmessage_api_posts_the_right_button_to_the_window_under_the_cursor(monkeypatch):
    m = winput.Win32Mouse(right_hover_s=0, right_press_s=0.05, right_api="postmessage")
    m._u = PostUser32()
    m.right_click(612, 450)
    posts = [e for e in m._u.events if e[1] == "post"]
    assert [(e[2], e[3]) for e in posts] == [(winput.WM_MOUSEMOVE, 0), (winput.WM_RBUTTONDOWN, winput.MK_RBUTTON),
                                             (winput.WM_RBUTTONUP, 0)]
    assert {e[4] for e in posts} == {(512, 400)} and {e[5] for e in posts} == {0x1234}  # client coordinates
    assert posts[2][0] - posts[1][0] >= 0.05 - 0.005
    assert not m._u.inputs()  # no device input for the right button
    assert [e for e in m._u.events if e[1] == "pos"][-1][2:] == (612, 450)  # the cursor is still placed


def test_blocked_postmessage_raises_input_blocked():
    m = winput.Win32Mouse(right_hover_s=0, right_api="postmessage")
    m._u = PostUser32(posted=False)
    with pytest.raises(winput.InputBlocked):
        m.right_click(612, 450)
