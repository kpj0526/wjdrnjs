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
    top.update()
    time.sleep(0.3)
    top.update()
    yield app
    app.on_close()


@pytest.mark.parametrize("backend", ["auto", "window", "screen"])
def test_preview_capture_never_contains_the_helper(target, helper_app, backend):
    """Regression: the helper window used to appear (recursively) inside its own game capture."""
    app = helper_app
    m, _ = resolve_mapping(target.title)
    hx, hy = app.root.winfo_rootx(), app.root.winfo_rooty()
    assert hx < m.left and hy < m.top  # the helper really overlaps the target on screen
    app.vars["window_title"][0].set(target.title)  # typed, no Enter
    app.vars["capture_backend"][0].set(backend)
    for _ in range(2):  # the second capture would show the first one inside the preview
        app.capture_preview()
        app.root.update()
    assert not app.errors, app.errors
    assert app.frame.shape == (300, 400, 3)
    assert_only_target(app.frame)
    assert app.grabber.last_backend == ("screen" if backend == "screen" else "window")


def test_runtime_grab_shares_the_exclusion(target, helper_app):
    # Start() hands the same Grabber to the engine, so run-time grabs exclude the helper too
    app = helper_app
    app.grabber.backend = "screen"
    m, _ = resolve_mapping(target.title)
    assert_only_target(grab_with_retry(app.grabber, m))
