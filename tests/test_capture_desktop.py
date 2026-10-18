"""Capture against real windows on this desktop (no game, no clicks).

A patterned "game" window runs in a separate process (tests/winfixture.py), because the helper
never targets its own process. These tests briefly show small windows on screen.
Set R2_SKIP_DESKTOP_TESTS=1 to skip them (e.g. on a locked or headless session).
"""
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from r2clicker.capture import CaptureError, Grabber, point_belongs_to
from r2clicker.geometry import find_window, resolve_mapping

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("R2_SKIP_DESKTOP_TESTS") == "1", reason="needs a Windows desktop"
)

FIXTURE = Path(__file__).parent / "winfixture.py"
TARGET_COLORS = {(192, 192, 0), (32, 32, 96)}  # winfixture --pattern with base colour c0c000


class Win:
    def __init__(self, title, x, y, w, h, color, *flags):
        self.title = title
        self.p = subprocess.Popen([sys.executable, str(FIXTURE), title, str(x), str(y), str(w), str(h), color, *flags],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        line = self.p.stdout.readline()
        assert line.startswith("ready"), line
        end = time.time() + 5
        while not find_window(title):
            assert time.time() < end, f"window {title} never appeared"
            time.sleep(0.05)
        time.sleep(0.2)  # let DWM compose it

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(5)
        except Exception:
            self.p.kill()


@pytest.fixture
def target():
    w = Win(f"R2CapTarget-{uuid.uuid4().hex[:8]}", 200, 200, 400, 300, "c0c000", "--pattern", "--topmost")
    yield w
    w.close()


def colours(img):
    u, c = np.unique(img.reshape(-1, 3), axis=0, return_counts=True)
    return {tuple(int(v) for v in k): int(n) for k, n in zip(u, c)}


def assert_only_target(img, tolerance=0.01):
    cols = colours(img)
    other = sum(n for k, n in cols.items() if k not in TARGET_COLORS)
    assert other <= tolerance * img.shape[0] * img.shape[1], sorted(cols.items(), key=lambda kv: -kv[1])[:6]
    assert all(cols.get(c, 0) > 0.4 * img.shape[0] * img.shape[1] for c in TARGET_COLORS), cols


def grab_with_retry(g, m, tries=10):
    err = None
    for _ in range(tries):
        try:
            return g.grab(m)
        except CaptureError as e:
            err = e
            time.sleep(0.1)
    raise err


def test_window_capture_excludes_external_overlapping_window(target):
    occ = Win(f"R2Occluder-{uuid.uuid4().hex[:8]}", 300, 250, 150, 120, "ff0000", "--topmost")
    try:
        m, _ = resolve_mapping(target.title)
        img = grab_with_retry(Grabber("window"), m)
        assert img.shape == (300, 400, 3)
        assert_only_target(img, tolerance=0.0)  # PrintWindow: exactly the target's own pixels
        assert (255, 0, 0) not in colours(img)
    finally:
        occ.close()


def test_screen_capture_refuses_when_external_window_covers(target):
    occ = Win(f"R2Occluder-{uuid.uuid4().hex[:8]}", 300, 250, 150, 120, "ff0000", "--topmost")
    try:
        m, _ = resolve_mapping(target.title)
        with pytest.raises(CaptureError, match=occ.title):
            Grabber("screen").grab(m)
    finally:
        occ.close()


def test_click_guard_sees_covering_window(target):
    occ = Win(f"R2Occluder-{uuid.uuid4().hex[:8]}", 300, 250, 150, 120, "ff0000", "--topmost")
    try:
        m, _ = resolve_mapping(target.title)
        assert not point_belongs_to(m.hwnd, 360, 300)          # under the occluder
        assert point_belongs_to(m.hwnd, m.left + 380, m.top + 280)  # bare target
    finally:
        occ.close()


@pytest.fixture
def helper_app(tk_root, tmp_path, monkeypatch):
    """The real GUI, visible and topmost, deliberately placed over the target window."""
    import tkinter as tk

    from r2clicker import gui

    monkeypatch.setenv("R2_HELPER_HOME", str(tmp_path))
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: errors.append(msg))
    top = tk.Toplevel(tk_root)
    top.geometry("+120+120")
    top.attributes("-topmost", True)
    app = gui.App(top)
    app.errors = errors
    top.geometry("+120+120")  # App centres itself; put it deliberately over the target again
    top.update()
    time.sleep(0.3)
    top.update()
    yield app
    app.on_close()


def _capture_twice(app, title, backend):
    app.vars["window_title"][0].set(title)  # typed, no Enter
    app.vars["capture_backend"][0].set(backend)
    for _ in range(2):  # the second capture would show the first one inside the preview
        app.capture_preview()
        app.root.update()


@pytest.mark.parametrize("backend", ["auto", "window"])
def test_preview_capture_never_contains_the_helper(target, helper_app, backend):
    """Regression: the helper window used to appear (recursively) inside its own game capture.
    Window capture reads only the game's own pixels: no exclusion needed (default: off)."""
    app = helper_app
    m, _ = resolve_mapping(target.title)
    assert app.root.winfo_rootx() < m.left and app.root.winfo_rooty() < m.top  # really overlapping
    assert not app.grabber.excluded  # default: the helper is NOT hidden from capture
    _capture_twice(app, target.title, backend)
    assert not app.errors, app.errors
    assert app.frame.shape == (300, 400, 3)
    assert_only_target(app.frame)
    assert app.grabber.last_backend == "window"


def test_screen_backend_refuses_while_helper_overlaps(target, helper_app):
    """Default (not excluded): screen capture fails safely instead of capturing the helper."""
    app = helper_app
    before = app.frame
    _capture_twice(app, target.title, "screen")
    assert app.errors and all("R2 target helper" in e for e in app.errors), app.errors
    assert app.frame is before  # the preview was not replaced by a frame containing the helper


def test_screen_backend_with_explicit_opt_in_excludes_helper(target, helper_app):
    app = helper_app
    hwnd = int(app.root.wm_frame(), 16)
    try:
        assert app.grabber.exclude_window(hwnd)  # what ticking the checkbox does
        app.root.update()
        time.sleep(0.2)
        _capture_twice(app, target.title, "screen")
        assert not app.errors, app.errors
        assert_only_target(app.frame)
    finally:
        app.grabber.include_window(hwnd)


def test_runtime_grab_uses_the_same_rules(target, helper_app):
    # Start() hands the same Grabber to the engine
    app = helper_app
    m, _ = resolve_mapping(target.title)
    app.grabber.backend = "window"
    assert_only_target(grab_with_retry(app.grabber, m))
    app.grabber.backend = "screen"
    with pytest.raises(CaptureError, match="R2 target helper"):
        app.grabber.grab(m)


# --- the helper window itself must be visible (customer: black window / taskbar preview) ---


def _affinity(hwnd):
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    u.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    v = wintypes.DWORD(99)
    assert u.GetWindowDisplayAffinity(hwnd, ctypes.byref(v))
    return v.value


def _screen_vs_self_render(app):
    """Compare what the screen/DWM shows for the helper (the same composition path that the taskbar
    thumbnail and screen sharing use) with what the window renders itself (PrintWindow)."""
    from r2clicker.capture import print_window
    from r2clicker.geometry import Mapping

    app.root.lift()
    app.root.attributes("-topmost", True)
    app.root.update()
    time.sleep(0.3)
    app.root.update()
    client = int(app.root.winfo_id())
    x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
    w, h = app.root.winfo_width(), app.root.winfo_height()
    own = print_window(client, w, h).astype(np.int16)
    shown = Grabber("screen")._mss_grab(Mapping(x, y, w, h)).astype(np.int16)
    return own, shown, float(np.abs(own - shown).mean())


def test_helper_window_is_displayed_normally_by_default(helper_app):
    app = helper_app
    hwnd = int(app.root.wm_frame(), 16)
    assert _affinity(hwnd) == 0  # WDA_NONE: shown everywhere, including the taskbar preview
    own, shown, diff = _screen_vs_self_render(app)
    assert own.std() > 10  # the window really has UI content
    assert shown.max() - shown.min() > 50, "window composited as a flat (black) area"
    assert diff < 12, f"on-screen content differs from the window's own rendering (mean {diff:.1f})"


def test_display_check_detects_an_excluded_window(helper_app):
    """Proves the check above would catch the customer's symptom: once excluded, the composited
    view of the window no longer matches its own rendering."""
    app = helper_app
    hwnd = int(app.root.wm_frame(), 16)
    try:
        assert app.grabber.exclude_window(hwnd)
        assert _affinity(hwnd) == 0x11
        _, _, diff = _screen_vs_self_render(app)
        assert diff >= 12, diff
    finally:
        app.grabber.include_window(hwnd)
    assert _affinity(hwnd) == 0


def test_window_capture_speed_budget(target):
    """Performance regression guard: steady-state window capture is one fast PrintWindow call."""
    import statistics

    from r2clicker import capture

    m, _ = resolve_mapping(target.title)
    g = Grabber("auto")
    grab_with_retry(g, m)  # probe
    assert g._pw_flags[m.hwnd] == capture.PW_CLIENTONLY  # GDI window: the fast mode suffices
    ts = []
    for _ in range(30):
        t0 = time.perf_counter()
        g.grab(m)
        ts.append((time.perf_counter() - t0) * 1000)
    med = statistics.median(ts)
    print(f"window capture 400x300: median {med:.1f} ms")
    assert med < 25, ts  # one full-content frame is ~17 ms; the fast mode is far below
