"""Win32Mouse against a recording user32: what the game actually receives, without real input."""
import sys
import time

import pytest

from r2clicker import gui, winput
from r2clicker.config import Settings

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 input")

LEFT_DOWN, LEFT_UP = winput.MOUSEEVENTF_LEFTDOWN, winput.MOUSEEVENTF_LEFTUP
RIGHT_DOWN, RIGHT_UP = winput.MOUSEEVENTF_RIGHTDOWN, winput.MOUSEEVENTF_RIGHTUP
ABS_MOVE = winput.MOUSEEVENTF_MOVE | winput.MOUSEEVENTF_ABSOLUTE | winput.MOUSEEVENTF_VIRTUALDESK


class FakeUser32:
    """Records SendInput/SetCursorPos with timestamps. Virtual desktop: 3200x900 starting at x=-1600."""

    metrics = {76: -1600, 77: 0, 78: 3200, 79: 900}

    def __init__(self, block=False):
        self.events = []  # (t, kind, flags, dx, dy) or (t, "pos", x, y)
        self.block = block

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
    m = winput.Win32Mouse(right_hover_s=0.08, right_hold_s=0.12)
    m._u = FakeUser32()
    monkeypatch.setattr(winput, "cursor_pos", lambda: (1500, 300))
    return m


def test_right_click_glides_onto_the_target_with_real_mouse_moves(mouse):
    mouse.right_click(1012, 633)
    moves = [e for e in mouse._u.inputs() if e[2] == ABS_MOVE]
    assert len(moves) == winput.GLIDE_STEPS
    # last SendInput move lands on the target pixel (absolute 0..65535 over the virtual desktop)
    x = -1600 + moves[-1][3] * (3200 - 1) / 65535
    y = moves[-1][4] * (900 - 1) / 65535
    assert abs(x - 1012) < 1 and abs(y - 633) < 1
    # then the exact pixel is pinned, and only then is the button pressed
    kinds = [(e[1], e[2]) if e[1] == "input" else (e[1], (e[2], e[3])) for e in mouse._u.events]
    assert kinds[-3:] == [("pos", (1012, 633)), ("input", RIGHT_DOWN), ("input", RIGHT_UP)]


def test_right_click_rests_on_target_and_holds_the_button(mouse):
    mouse.right_click(1012, 633)
    pinned = next(e[0] for e in mouse._u.events if e[1] == "pos")
    down, up = mouse._u.time_of(RIGHT_DOWN), mouse._u.time_of(RIGHT_UP)
    assert down - pinned >= 0.08 - 0.005
    assert up - down >= 0.12 - 0.005


def test_left_click_is_unchanged(mouse):
    mouse.left_click(900, 500)
    assert [e[2] for e in mouse._u.inputs()] == [LEFT_DOWN, LEFT_UP]
    assert mouse._u.time_of(LEFT_UP) - mouse._u.time_of(LEFT_DOWN) < 0.1


def test_blocked_glide_raises_input_blocked_and_never_presses(monkeypatch):
    m = winput.Win32Mouse()
    m._u = FakeUser32(block=True)
    monkeypatch.setattr(winput, "cursor_pos", lambda: (0, 0))
    with pytest.raises(winput.InputBlocked):
        m.right_click(10, 10)
    assert RIGHT_DOWN not in [e[2] for e in m._u.inputs()]


def test_right_click_timing_settings_validate():
    assert Settings().validate() == []
    errs = Settings(right_click_hold=0, right_click_hover=5).validate()
    assert any("right_click_hold" in e for e in errs) and any("right_click_hover" in e for e in errs)


def test_gui_form_offers_the_right_click_timing():
    names = [f[0] for f in gui.FORM]
    assert "right_click_hover" in names and "right_click_hold" in names
