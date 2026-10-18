"""Headless GUI smoke test: import, build the window hidden, exercise form -> Settings, close.
Never starts a run and never captures the screen."""
import pytest

tk = pytest.importorskip("tkinter")

from r2clicker.geometry import Mapping  # noqa: E402


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


def test_check_on_sample_image_finds_nothing(app):
    app.test_verify()
    assert app.verify_box is not None  # the best (rejected) box is drawn for inspection


def test_roi_drag_updates_field(app):
    class E:
        def __init__(self, x, y):
            self.x, self.y = x, y

    app.drag_mode.set("roi")
    app._on_press(E(200, 100))
    app._on_drag(E(500, 300))
    app._on_release(E(500, 300))
    assert app.settings.roi == (400, 200, 1000, 600)  # the canvas is half of 1600x900


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
    app.vars["grid_step"][0].set("1")  # invalid
    app.capture_preview()
    assert calls == [] and app.errors
    assert app.settings is before and app.settings.window_title != "NewTitle"


def test_load_image_applies_typed_roi_first(app, monkeypatch):
    from r2clicker import gui
    from r2clicker.paths import sample_image

    opened = []
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: opened.append(1) or str(sample_image()))
    app.vars["roi"][0].set("400, 150, 1200, 650")
    app.load_image()
    assert opened and app.settings.roi == (400, 150, 1200, 650)


def test_load_image_not_opened_when_form_invalid(app, monkeypatch):
    from r2clicker import gui

    opened = []
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: opened.append(1) or "")
    app.vars["roi"][0].set("1, 2, 3")
    app.load_image()
    assert not opened and app.errors


def test_check_on_image_uses_typed_thresholds_and_keeps_mode(app):
    app.vars["plate_min_white"][0].set("77")
    app.test_verify()
    assert app.settings.plate_min_white == 77
    assert app.settings.verify_mode == "diff"  # the single-image check must not change the saved mode


def test_start_uses_typed_wait_interval(app, monkeypatch):
    from r2clicker import gui

    started = []

    class FakeBot:
        def __init__(self, s, grab, mouse):
            started.append((s, mouse))
            self.stop_reason = ""

        def run(self):
            pass

        def stop(self, why=""):
            pass

    monkeypatch.setattr(gui, "Bot", FakeBot)
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
