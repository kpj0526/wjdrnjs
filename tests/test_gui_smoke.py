"""Headless GUI smoke test: import, build the window hidden, exercise form -> Settings, close.
Never starts a run and never captures the screen."""
import pytest

tk = pytest.importorskip("tkinter")


def test_gui_module_imports():
    from r2clicker import gui

    assert callable(gui.main) and gui.FORM


@pytest.fixture(scope="module")
def tk_root():
    # One Tcl interpreter per module, like the real app: creating many Tk() instances in one
    # process intermittently fails on Windows with "Can't find a usable tk.tcl".
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    root.withdraw()
    yield root
    root.destroy()


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
