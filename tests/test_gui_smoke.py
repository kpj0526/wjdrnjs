"""Headless GUI smoke test: import, build the window hidden, exercise form -> Settings, close.
Never starts a run and never captures the screen.

Every App is built with R2_HIDE_TEST_WINDOWS=1, so no window is shown on screen. The two tests
that need a visible window are desktop tests (skipped with R2_SKIP_DESKTOP_TESTS=1)."""
import os
import sys

import pytest

tk = pytest.importorskip("tkinter")

from r2clicker.geometry import Mapping  # noqa: E402

desktop = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("R2_SKIP_DESKTOP_TESTS") == "1", reason="shows a window on the desktop"
)


@pytest.fixture(autouse=True)
def _hidden_windows(monkeypatch):
    monkeypatch.setenv("R2_HIDE_TEST_WINDOWS", "1")


class _Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _click(app, ref_x, ref_y):
    """Click the preview at a reference point (the canvas is half of 1600x900)."""
    app._on_release(_Ev(ref_x // 2, ref_y // 2))


def test_gui_module_imports():
    from r2clicker import gui

    assert callable(gui.main) and gui.FORM


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    monkeypatch.setenv("R2_HELPER_HOME", str(tmp_path))
    from r2clicker import gui

    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: errors.append(msg))
    root = tk.Toplevel(tk_root)
    root.withdraw()
    a = gui.App(root)
    a.errors = errors
    root.update()
    yield a
    a.on_close()


def test_window_builds_with_sample_and_preview(app, tmp_path):
    assert app.frame is not None and app.frame.shape == (900, 1600, 3)
    assert app.canvas.find_all()  # preview overlay drawn
    assert app.settings_file == tmp_path / "settings.json"
    assert app.log_file == tmp_path / "logs" / "r2helper.log" and app.log_file.exists()
    assert not app.root.winfo_viewable()  # R2_HIDE_TEST_WINDOWS: nothing appears on screen


def test_wait_interval_field_reaches_settings(app):
    var, kind = app.vars["wait_interval"]
    var.set("12.5")
    s = app.read_form()
    assert s is not None and s.wait_interval == 12.5 and s.dry_run is True


def test_invalid_form_shows_error_and_returns_none(app):
    app.vars["wait_interval"][0].set("-3")
    assert app.read_form() is None
    assert any("wait_interval" in e for e in app.errors)
    app.vars["wait_interval"][0].set("abc")
    assert app.read_form() is None


def test_save_writes_settings_into_data_dir(app, tmp_path):
    app.vars["wait_interval"][0].set("3.75")
    app.save()
    from r2clicker.config import Settings

    assert Settings.load(tmp_path / "settings.json").wait_interval == 3.75


# --- every action uses the form as typed, without Enter/Apply -----------------------------


def _fake_capture(app, monkeypatch, gui):
    calls = []

    def resolve(title, ref_w, ref_h):
        calls.append(title)
        return Mapping(0, 0, 1600, 900, ref_w, ref_h), f"fake '{title}'"

    monkeypatch.setattr(gui, "resolve_mapping", resolve)
    monkeypatch.setattr(app.grabber, "grab", lambda m: app.frame.copy())
    return calls


def test_capture_uses_title_typed_without_enter(app, monkeypatch):
    from r2clicker import gui

    calls = _fake_capture(app, monkeypatch, gui)
    app.vars["window_title"][0].set("MyGameClient")  # typed only, no Apply/Enter
    app.capture_preview()
    assert calls == ["MyGameClient"]
    assert app.settings.window_title == "MyGameClient" and not app.errors


def test_capture_refused_when_form_invalid(app, monkeypatch):
    from r2clicker import gui

    calls = _fake_capture(app, monkeypatch, gui)
    before = app.settings
    app.vars["window_title"][0].set("NewTitle")
    app.vars["wait_interval"][0].set("-1")  # invalid
    app.capture_preview()
    assert calls == [] and app.errors
    assert app.settings is before and app.settings.window_title != "NewTitle"


def test_load_image_applies_typed_form_first(app, monkeypatch):
    from r2clicker import gui
    from r2clicker.paths import sample_image

    opened = []
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: opened.append(1) or str(sample_image()))
    app.vars["point_delay"][0].set("0.4")
    app.load_image()
    assert opened and app.settings.point_delay == 0.4


def test_load_image_not_opened_when_form_invalid(app, monkeypatch):
    from r2clicker import gui

    opened = []
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: opened.append(1) or "")
    app.vars["point_delay"][0].set("abc")
    app.load_image()
    assert not opened and app.errors


def test_start_uses_typed_wait_interval(app, monkeypatch):
    from r2clicker import gui

    started = []

    class FakeBot:
        def __init__(self, s, mouse):
            started.append((s, mouse))
            self.stop_reason = ""

        def run(self):
            pass

        def stop(self, why=""):
            pass

    monkeypatch.setattr(gui, "Bot", FakeBot)
    _fake_capture(app, monkeypatch, gui)  # preflight needs a game window
    _click(app, 600, 300)
    app.vars["wait_interval"][0].set("9.5")
    app.vars["window_title"][0].set("Typed")
    app.start()
    app.thread.join(2)
    (s, mouse), = started
    assert s.wait_interval == 9.5 and s.window_title == "Typed"
    assert isinstance(mouse, gui.DryRunMouse) and s.dry_run  # default stays dry run


def test_start_refused_when_form_invalid(app, monkeypatch):
    from r2clicker import gui

    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("must not start"))
    app.vars["wait_interval"][0].set("-1")
    app.start()
    assert app.thread is None and app.errors


def test_start_ignored_while_running(app, monkeypatch):
    import threading

    from r2clicker import gui

    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("must not start twice"))
    gate = threading.Event()
    app.thread = threading.Thread(target=gate.wait)
    app.thread.start()
    before = app.settings
    app.vars["wait_interval"][0].set("1.0")
    app.start()
    assert app.settings is before  # nothing applied mid-run
    gate.set()
    app.thread.join()
    app.thread = None


# --- window placement and startup-only work ---------------------------------------------------


def _new_app(tk_root, monkeypatch, tmp_path, **kw):
    import tkinter as tk

    from r2clicker import gui

    monkeypatch.setenv("R2_HELPER_HOME", str(tmp_path))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: None)
    top = tk.Toplevel(tk_root)
    top.withdraw()
    return gui.App(top, **kw)


@desktop
def test_window_opens_visible_inside_a_monitor(tk_root, tmp_path, monkeypatch):
    from r2clicker.winplace import monitor_work_areas, parse_geometry

    monkeypatch.delenv("R2_HIDE_TEST_WINDOWS")  # this test is about showing the window
    app = _new_app(tk_root, monkeypatch, tmp_path)  # show=True: deiconify/lift/focus
    app.root.update()
    try:
        assert app.root.state() == "normal" and app.root.winfo_viewable()
        w, h, x, y = parse_geometry(app.root.geometry())
        areas = monitor_work_areas() or [(0, 0, app.root.winfo_screenwidth(), app.root.winfo_screenheight())]
        assert any(l <= x and t <= y and x + w <= r and y + h <= b for l, t, r, b in areas), (app.root.geometry(), areas)
    finally:
        app.on_close()


@desktop
def test_offscreen_saved_position_is_corrected_and_geometry_remembered(tk_root, tmp_path, monkeypatch):
    from r2clicker.config import Settings
    from r2clicker.winplace import parse_geometry

    Settings(window_geometry="1200x700+9000+-4000", wait_interval=4.0).save(tmp_path / "settings.json")
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    w, h, x, y = parse_geometry(app.root.geometry())
    assert 0 <= x < app.root.winfo_screenwidth() and 0 <= y < app.root.winfo_screenheight()
    app.vars["wait_interval"][0].set("99")  # an unsaved edit must not be written on close
    app.root.deiconify()
    app.root.update()
    app.on_close()
    s = Settings.load(tmp_path / "settings.json")
    assert parse_geometry(s.window_geometry) and s.wait_interval == 4.0


def test_monitor_query_and_remote_check_run_once_at_startup(tk_root, tmp_path, monkeypatch):
    from r2clicker import gui
    from r2clicker.geometry import Mapping

    calls = {"areas": 0, "remote": 0}
    real_areas = gui.monitor_work_areas
    monkeypatch.setattr(gui, "monitor_work_areas", lambda: calls.__setitem__("areas", calls["areas"] + 1) or real_areas())
    monkeypatch.setattr(gui, "is_remote_session", lambda: calls.__setitem__("remote", calls["remote"] + 1) or False)
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    assert calls == {"areas": 1, "remote": 1}
    monkeypatch.setattr(gui, "resolve_mapping", lambda *a: (Mapping(0, 0, 1600, 900), "fake"))
    monkeypatch.setattr(app.grabber, "grab", lambda m: app.frame.copy())
    started = []
    monkeypatch.setattr(gui, "Bot", lambda s, mouse: started.append(1) or type(
        "B", (), {"run": lambda self: None, "stop": lambda self, w="": None, "stop_reason": ""})())
    for _ in range(3):
        app.capture_preview()
        app.apply()
    _click(app, 600, 300)
    app.start()
    app.thread.join(2)
    assert started and calls == {"areas": 1, "remote": 1}
    app.on_close()


def test_remote_session_keeps_helper_visible_to_capture(tk_root, tmp_path, monkeypatch):
    from r2clicker import capture, gui

    monkeypatch.setattr(gui, "is_remote_session", lambda: True)
    monkeypatch.setattr(capture, "exclude_from_capture", lambda h: pytest.fail("must not hide under RDP"))
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    assert not app.grabber.excluded and app.grabber.own
    app.on_close()


def _affinity_spy(monkeypatch):
    from r2clicker import capture, gui

    monkeypatch.setattr(gui, "is_remote_session", lambda: False)
    calls = []
    monkeypatch.setattr(capture, "exclude_from_capture", lambda h: calls.append("ex") or True)
    monkeypatch.setattr(capture, "include_in_capture", lambda h: calls.append("in") or True)
    return calls


def test_new_install_never_hides_the_window(tk_root, tmp_path, monkeypatch):
    calls = _affinity_spy(monkeypatch)
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    assert app.settings.hide_helper_from_capture is False
    assert "ex" not in calls and not app.grabber.excluded
    app.on_close()


@pytest.mark.parametrize("answer, kept", [(True, True), (False, False)])
def test_opt_in_is_kept_only_if_user_confirms_window_visible(tk_root, tmp_path, monkeypatch, answer, kept):
    from r2clicker import gui

    calls = _affinity_spy(monkeypatch)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: asked.append(1) or answer)
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    calls.clear()
    app.vars["hide_helper_from_capture"][0].set(True)
    app.apply()
    assert asked == [1]
    assert app.settings.hide_helper_from_capture is kept
    assert app.vars["hide_helper_from_capture"][0].get() is kept
    assert calls == (["ex"] if kept else ["ex", "in"])
    assert bool(app.grabber.excluded) is kept
    app.apply()  # unchanged afterwards: no further Win32 call, no second question
    assert asked == [1] and len(calls) == (1 if kept else 2)
    app.on_close()


def test_legacy_settings_true_is_reset_so_window_is_visible(tk_root, tmp_path, monkeypatch):
    import json

    calls = _affinity_spy(monkeypatch)
    # a settings.json written by the previous release: the old default True, no settings_version
    (tmp_path / "settings.json").write_text(json.dumps({"hide_helper_from_capture": True, "wait_interval": 3.0}),
                                            encoding="utf-8")
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    assert app.settings.hide_helper_from_capture is False and app.settings.wait_interval == 3.0
    assert "ex" not in calls and not app.grabber.excluded
    app.on_close()


def test_explicit_v2_opt_in_is_honoured_at_startup(tk_root, tmp_path, monkeypatch):
    from r2clicker.config import Settings

    calls = _affinity_spy(monkeypatch)
    Settings(hide_helper_from_capture=True).save(tmp_path / "settings.json")
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    assert app.settings.hide_helper_from_capture is True and calls == ["ex"]
    app.on_close()


def test_show_window_flag_overrides_an_opt_in(tk_root, tmp_path, monkeypatch):
    from r2clicker.config import Settings

    calls = _affinity_spy(monkeypatch)
    Settings(hide_helper_from_capture=True).save(tmp_path / "settings.json")
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False, force_visible=True)
    assert app.settings.hide_helper_from_capture is False and "ex" not in calls
    app.on_close()


def test_startup_crash_is_written_to_a_log(tmp_path, monkeypatch):
    from r2clicker import gui

    monkeypatch.setenv("R2_HELPER_HOME", str(tmp_path))
    shown = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: shown.append(msg))
    monkeypatch.setattr(gui.tk, "Tk", lambda: (_ for _ in ()).throw(RuntimeError("no Tcl")))
    with pytest.raises(RuntimeError):
        gui.main()
    assert "no Tcl" in (tmp_path / "startup-error.log").read_text(encoding="utf-8")


# --- manual candidate points ------------------------------------------------------------------


def test_clicking_the_preview_adds_numbered_points_in_click_order(app):
    for p in ((600, 300), (1000, 250), (500, 550), (800, 440), (100, 850)):  # player and HUD spots too
        _click(app, *p)
    assert app.settings.manual_points == [(600, 300), (1000, 250), (500, 550), (800, 440), (100, 850)]
    labels = [app.canvas.itemcget(i, "text") for i in app.canvas.find_withtag("manual_label")]
    assert labels == ["1", "2", "3", "4", "5"]
    assert app.manual_list.size() == 5 and app.manual_list.get(1).strip().startswith("2. (1000, 250)")


def test_point_outside_the_game_client_is_refused(app):
    assert not app.add_manual_point(1700, 300)
    assert app.settings.manual_points == []
    assert "not added" in app.manual_info.cget("text") and "outside" in app.manual_info.cget("text")


def test_clicking_an_existing_point_selects_it(app):
    _click(app, 600, 300)
    _click(app, 1000, 250)
    _click(app, 602, 302)  # within PICK_RADIUS of point 1: select, do not add
    assert len(app.settings.manual_points) == 2 and app.manual_list.curselection() == (0,)


def test_delete_move_and_clear_manual_points(app, monkeypatch):
    from r2clicker import gui

    for p in ((600, 300), (1000, 250), (500, 550)):
        _click(app, *p)
    app.manual_list.selection_clear(0, "end")
    app.manual_list.selection_set(2)
    app.move_manual_point(-1)
    assert app.settings.manual_points == [(600, 300), (500, 550), (1000, 250)]
    assert app.manual_list.curselection() == (1,)
    app.move_manual_point(-1)
    app.move_manual_point(-1)  # already first: no change
    assert app.settings.manual_points == [(500, 550), (600, 300), (1000, 250)]
    app.delete_manual_point()
    assert app.settings.manual_points == [(600, 300), (1000, 250)]
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    app.clear_manual_points()
    assert len(app.settings.manual_points) == 2  # cancelled
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app.clear_manual_points()
    assert app.settings.manual_points == [] and app.manual_list.size() == 0
    assert not app.canvas.find_withtag("manual")


def test_manual_points_saved_and_loaded_as_reference_coordinates(app, tk_root, tmp_path, monkeypatch):
    from r2clicker.config import Settings

    _click(app, 600, 300)
    _click(app, 1000, 250)
    app.save()
    assert Settings.load(tmp_path / "settings.json").manual_points == [(600, 300), (1000, 250)]
    again = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    try:
        assert again.settings.manual_points == [(600, 300), (1000, 250)]
        assert again.manual_list.size() == 2 and len(again.canvas.find_withtag("manual_label")) == 2
    finally:
        again.on_close()


def test_loaded_point_off_the_client_is_marked_and_start_is_blocked(app, monkeypatch):
    from r2clicker import gui

    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("must not start with a bad point"))
    app._set_manual_points([(600, 300), (1700, 300)])  # e.g. from a hand-edited settings.json
    assert "REFUSED" in app.manual_list.get(1) and "REFUSED" not in app.manual_list.get(0)
    app.start()
    assert app.thread is None and any("click point 2" in e for e in app.errors)


def test_start_without_points_is_refused(app, monkeypatch):
    from r2clicker import gui

    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("must not start"))
    app.start()
    assert app.thread is None and any("no click points" in e for e in app.errors)


def test_start_passes_manual_points_to_bot_in_order(app, monkeypatch):
    from r2clicker import gui

    started = []

    class FakeBot:
        def __init__(self, s, mouse):
            started.append((s, mouse))
            self.stop_reason = ""

        def run(self):
            pass

        def stop(self, why=""):
            pass

    monkeypatch.setattr(gui, "Bot", FakeBot)
    _fake_capture(app, monkeypatch, gui)
    _click(app, 1000, 250)
    _click(app, 600, 300)
    app.start()
    app.thread.join(2)
    (s, mouse), = started
    assert s.manual_points == [(1000, 250), (600, 300)]
    assert s.dry_run and isinstance(mouse, gui.DryRunMouse)
    _click(app, 500, 550)  # editing after start must not change the running bot's settings
    assert s.manual_points == [(1000, 250), (600, 300)]


# --- preflight gate ----------------------------------------------------------------------------


def test_start_refused_when_preflight_fails_even_live(app, monkeypatch):
    from r2clicker import gui

    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("must not start"))
    monkeypatch.setattr(gui, "Win32Mouse", lambda **k: pytest.fail("no live input before preflight passes"))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: pytest.fail("no live prompt either"))
    _click(app, 600, 300)
    app.vars["window_title"][0].set("NoSuchWindow-r2-gui-test")
    app.dry_var.set(False)
    app.start()
    assert app.thread is None and any("game window" in e for e in app.errors)


def test_live_prompt_lists_preflight_warnings(app, monkeypatch):
    from r2clicker import gui, preflight

    _fake_capture(app, monkeypatch, gui)
    monkeypatch.setattr(preflight, "window_elevated", lambda h: None)
    monkeypatch.setattr(preflight, "self_elevated", lambda: False)
    asked = []
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda title, msg, **k: asked.append(msg) or False)
    monkeypatch.setattr(gui, "Bot", lambda *a, **k: pytest.fail("declined: must not start"))
    _click(app, 600, 300)
    app.vars["window_title"][0].set("")  # whole screen: warns
    app.dry_var.set(False)
    app.start()
    assert asked and "Preflight warnings" in asked[0] and "game window" in asked[0]
    assert app.thread is None


def test_preflight_button_shows_result(app, monkeypatch):
    from r2clicker import gui

    _fake_capture(app, monkeypatch, gui)
    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda title, msg: shown.append(title))
    _click(app, 600, 300)
    app.preflight_check()
    assert shown == ["Preflight passed"] and not app.errors
    app.settings.manual_points.append((1700, 440))  # bad point loaded from a file
    app.preflight_check()
    assert any("click point 2" in e for e in app.errors)


def test_gui_save_keeps_unknown_keys(tk_root, tmp_path, monkeypatch):
    import json

    (tmp_path / "settings.json").write_text(json.dumps({"future_option": 5, "wait_interval": 2.0}), encoding="utf-8")
    app = _new_app(tk_root, monkeypatch, tmp_path, show=False)
    try:
        app.vars["wait_interval"][0].set("3.0")
        app.save()
        d = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert d["future_option"] == 5 and d["wait_interval"] == 3.0
    finally:
        app.on_close()


def test_live_start_uses_the_typed_right_click_timing(app, monkeypatch):
    from r2clicker import gui, preflight

    _fake_capture(app, monkeypatch, gui)
    monkeypatch.setattr(preflight, "window_elevated", lambda h: None)
    monkeypatch.setattr(preflight, "self_elevated", lambda: False)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    made = []
    monkeypatch.setattr(gui, "Win32Mouse", lambda **k: made.append(k) or gui.DryRunMouse())
    monkeypatch.setattr(gui, "Bot", lambda s, mouse: type(
        "B", (), {"run": lambda self: None, "stop": lambda self, why="": None, "stop_reason": ""})())
    _click(app, 600, 300)
    app.vars["window_title"][0].set("")
    app.vars["right_click_hover"][0].set("0.2")  # typed, no Apply/Enter
    app.vars["right_click_hold"][0].set("0.3")
    app.dry_var.set(False)
    app.start()
    if app.thread:
        app.thread.join(2)
    assert made == [{"right_hover_s": 0.2, "right_hold_s": 0.3}]


@pytest.mark.parametrize("dry, activated", [(False, [4321]), (True, [])])
def test_live_start_brings_the_game_window_to_the_front(app, monkeypatch, dry, activated):
    from r2clicker import gui, preflight

    monkeypatch.setattr(gui, "resolve_mapping", lambda t, w, h: (Mapping(0, 0, 1600, 900, w, h, hwnd=4321), "game"))
    monkeypatch.setattr(preflight, "window_elevated", lambda h: False)
    monkeypatch.setattr(preflight, "self_elevated", lambda: False)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui, "Win32Mouse", lambda **k: gui.DryRunMouse())
    monkeypatch.setattr(gui, "Bot", lambda s, mouse: type(
        "B", (), {"run": lambda self: None, "stop": lambda self, why="": None, "stop_reason": ""})())
    seen = []
    monkeypatch.setattr(gui, "activate", lambda h: seen.append(h) or True)
    _click(app, 600, 300)
    app.dry_var.set(dry)
    app.start()
    app.thread.join(2)
    assert seen == activated and not app.errors
