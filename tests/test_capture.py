"""Capture backend selection and occlusion logic, with the Win32 calls stubbed out."""
import numpy as np
import pytest

from r2clicker import capture
from r2clicker.capture import CaptureError, Grabber, WinInfo, is_blank, overlapping
from r2clicker.geometry import Mapping

M = Mapping(100, 50, 160, 90, hwnd=4242)
CONTENT = np.dstack([np.tile(np.arange(160, dtype=np.uint8), (90, 1))] * 3)  # a gradient: not blank
BLANK = np.zeros((90, 160, 3), np.uint8)
SCREEN = np.full((90, 160, 3), 77, np.uint8)
SCREEN[0, 0] = 200


class Stub:
    def __init__(self, monkeypatch, frames, above=()):
        self.frames = list(frames)
        self.print_calls = 0
        self.screen_calls = 0
        self.above = list(above)
        monkeypatch.setattr(capture, "print_window", self.print_window)
        monkeypatch.setattr(capture, "windows_above", lambda h: self.above)
        self.flags = []
        monkeypatch.setattr(capture.time, "sleep", lambda s: pytest.fail("capture must not sleep"))

    def print_window(self, hwnd, w, h, flags=3):
        self.print_calls += 1
        self.flags.append(flags)
        f = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        if isinstance(f, Exception):
            raise f
        return f(flags) if callable(f) else f

    def screen(self, g, monkeypatch):
        def grab(m):
            self.screen_calls += 1
            return SCREEN.copy()

        monkeypatch.setattr(g, "_mss_grab", grab)


def test_blank_detection():
    assert is_blank(BLANK) and is_blank(np.full((90, 160, 3), 128, np.uint8))
    assert not is_blank(CONTENT)


def test_overlapping_rectangles():
    client = (100, 50, 260, 140)
    wins = [WinInfo(1, "left of it", (0, 0, 100, 200)),       # touches the edge only
            WinInfo(2, "covers corner", (250, 130, 400, 300)),
            WinInfo(3, "helper", (120, 60, 200, 100)),
            WinInfo(4, "far away", (1000, 1000, 1100, 1100))]
    assert [w.hwnd for w in overlapping(client, wins, excluded=set())] == [2, 3]
    assert [w.hwnd for w in overlapping(client, wins, excluded={3})] == [2]


def test_window_backend_ignores_overlapping_windows(monkeypatch):
    st = Stub(monkeypatch, [CONTENT], above=[WinInfo(9, "Other app", (0, 0, 5000, 5000))])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    img = g.grab(M)
    assert (img == CONTENT).all() and g.last_backend == "window" and st.screen_calls == 0


def test_blank_once_is_retried_before_falling_back(monkeypatch):
    st = Stub(monkeypatch, [BLANK, CONTENT])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    assert (g.grab(M) == CONTENT).all() and st.print_calls == 2 and st.screen_calls == 0


def test_auto_falls_back_to_screen_when_uncovered(monkeypatch):
    st = Stub(monkeypatch, [BLANK])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    assert (g.grab(M) == SCREEN).all() and g.last_backend == "screen"
    calls = st.print_calls
    g.grab(M)  # within REPROBE_S: no new PrintWindow attempt
    assert st.print_calls == calls and st.screen_calls == 2


def test_auto_reprobes_window_capture_later(monkeypatch):
    st = Stub(monkeypatch, [BLANK, BLANK, CONTENT])
    now = [1000.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: now[0])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    assert g.grab(M) is not None and g.last_backend == "screen"
    now[0] += capture.REPROBE_S + 1
    assert (g.grab(M) == CONTENT).all() and g.last_backend == "window"


def test_screen_fallback_refused_when_covered(monkeypatch):
    st = Stub(monkeypatch, [BLANK], above=[WinInfo(9, "Some browser", (150, 60, 300, 120))])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    with pytest.raises(CaptureError, match="covered by 'Some browser'"):
        g.grab(M)
    assert st.screen_calls == 0


def test_excluded_helper_does_not_block_screen_capture(monkeypatch):
    st = Stub(monkeypatch, [BLANK], above=[WinInfo(77, "R2 target helper", (150, 60, 300, 120))])
    monkeypatch.setattr(capture, "exclude_from_capture", lambda h: True)
    g = Grabber("screen")
    st.screen(g, monkeypatch)
    assert g.exclude_window(77)
    assert (g.grab(M) == SCREEN).all()


def test_helper_that_cannot_be_excluded_blocks_screen_capture(monkeypatch):
    st = Stub(monkeypatch, [BLANK], above=[WinInfo(77, "R2 target helper", (150, 60, 300, 120))])
    monkeypatch.setattr(capture, "exclude_from_capture", lambda h: False)
    g = Grabber("screen")
    st.screen(g, monkeypatch)
    assert not g.exclude_window(77)
    with pytest.raises(CaptureError, match="R2 target helper"):
        g.grab(M)


def test_window_backend_reports_blank_clearly(monkeypatch):
    Stub(monkeypatch, [BLANK])
    with pytest.raises(CaptureError, match="blank image.*hardware rendering"):
        Grabber("window").grab(M)


def test_whole_screen_mapping_checks_own_windows(monkeypatch):
    st = Stub(monkeypatch, [CONTENT])
    whole = Mapping(0, 0, 160, 90)  # hwnd 0: empty title -> whole screen
    monkeypatch.setattr(capture, "exclude_from_capture", lambda h: False)
    monkeypatch.setattr(capture, "_visible_rect", lambda h: (10, 10, 50, 50))
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    g.exclude_window(5)
    with pytest.raises(CaptureError, match="captured area contains"):
        g.grab(whole)
    assert st.print_calls == 0  # no window to print


def test_size_mismatch_from_print_window(monkeypatch):
    Stub(monkeypatch, [np.dstack([np.tile(np.arange(100, dtype=np.uint8), (50, 1))] * 3)])
    with pytest.raises(CaptureError, match="client is 160x90"):
        Grabber("window").grab(M)


FAST, FULL = capture.PW_CLIENTONLY, capture.PW_CLIENTONLY | capture.PW_RENDERFULLCONTENT


def test_steady_state_is_one_fast_printwindow_per_grab(monkeypatch):
    st = Stub(monkeypatch, [CONTENT])
    monkeypatch.setattr(capture, "windows_above", lambda h: pytest.fail("window mode needs no Z-order walk"))
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    for _ in range(5):
        g.grab(M)
    assert st.flags == [FAST] * 5 and st.screen_calls == 0


def test_hardware_rendered_window_remembers_full_content_mode(monkeypatch):
    # like a DirectX game: the fast mode returns black, the full-content mode returns pixels
    st = Stub(monkeypatch, [lambda flags: CONTENT if flags == FULL else BLANK])
    g = Grabber("auto")
    st.screen(g, monkeypatch)
    for _ in range(4):
        assert (g.grab(M) == CONTENT).all()
    assert st.flags == [FAST, FULL, FULL, FULL, FULL]  # probe once, then one call per grab


def test_transient_printwindow_failure_is_retried_once_without_sleep(monkeypatch):
    st = Stub(monkeypatch, [CaptureError("PrintWindow failed"), CONTENT])
    assert (Grabber("window").grab(M) == CONTENT).all() and st.print_calls == 2


def test_persistent_printwindow_failure_is_reported(monkeypatch):
    Stub(monkeypatch, [CaptureError("PrintWindow failed for the game window")])
    with pytest.raises(CaptureError, match="PrintWindow failed"):
        Grabber("window").grab(M)
