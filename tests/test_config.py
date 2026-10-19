import json

import pytest

from r2clicker.config import Settings


PTS = [(600, 300)]


def test_defaults_are_valid_once_there_are_points():
    assert Settings(manual_points=PTS).validate() == []


@pytest.mark.parametrize(
    "kw, needle",
    [
        (dict(wait_interval=-1.0), "wait_interval"),
        (dict(wait_interval=float("nan")), "wait_interval"),
        (dict(right_click_delay=-0.1), "right_click_delay"),
        (dict(point_delay=100), "point_delay"),
        (dict(right_click_hold=0), "right_click_hold"),
        (dict(right_click_hover=5), "right_click_hover"),
        (dict(max_cycles=-1), "max_cycles"),
        (dict(capture_backend="gdi"), "capture_backend"),
        (dict(emergency_hotkey="F13"), "emergency_hotkey"),
        (dict(dry_run=False, emergency_hotkey="", corner_failsafe=False), "emergency"),
        (dict(manual_points=[]), "no click points"),
    ],
)
def test_invalid_settings_reported(kw, needle):
    errs = Settings(**{"manual_points": PTS, **kw}).validate()
    assert any(needle in e for e in errs), errs


def test_live_mode_with_one_safety_is_fine():
    assert Settings(dry_run=False, emergency_hotkey="", corner_failsafe=True, manual_points=PTS).validate() == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "settings.json"
    s = Settings(wait_interval=7.25, point_delay=0.3, manual_points=[(1, 2), (3, 4)], dry_run=False)
    s.save(p)
    t = Settings.load(p)
    assert (t.wait_interval, t.point_delay, t.manual_points, t.dry_run) == (7.25, 0.3, [(1, 2), (3, 4)], False)
    assert t.load_warnings == []
    assert "load_warnings" not in json.loads(p.read_text(encoding="utf-8"))
    assert not list(p.parent.glob("*.tmp"))


def test_missing_file_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", "", "\x00\x01"])
def test_corrupt_file_gives_defaults_with_warning(tmp_path, content):
    p = tmp_path / "settings.json"
    p.write_text(content, encoding="utf-8")
    s = Settings.load(p)
    assert s.manual_points == [] and s.dry_run is True
    assert s.load_warnings


def test_wrong_types_keep_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "wait_interval": "fast", "max_cycles": 2.5, "manual_points": [1, 2, 3], "dry_run": "no",
        "point_delay": 0.4, "unknown_key": 1, "window_title": 5, "settings_version": 3,
    }), encoding="utf-8")
    s = Settings.load(p)
    d = Settings()
    assert (s.wait_interval, s.max_cycles, s.manual_points, s.dry_run, s.window_title) == (
        d.wait_interval, d.max_cycles, d.manual_points, True, d.window_title)
    assert s.point_delay == 0.4 and s.extra == {"unknown_key": 1}
    assert len(s.load_warnings) == 5


def test_int_json_value_for_float_setting(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"wait_interval": 3}), encoding="utf-8")
    s = Settings.load(p)
    assert s.wait_interval == 3.0 and isinstance(s.wait_interval, float)


def test_utf8_bom_accepted(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes("\ufeff".encode() + json.dumps({"window_title": "알투"}).encode("utf-8"))
    assert Settings.load(p).window_title == "알투"


def test_hide_helper_defaults_off_and_is_saved_with_version(tmp_path):
    from r2clicker.config import SETTINGS_VERSION

    assert Settings().hide_helper_from_capture is False
    p = tmp_path / "s.json"
    Settings(hide_helper_from_capture=True).save(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["settings_version"] == SETTINGS_VERSION and d["hide_helper_from_capture"] is True
    assert Settings.load(p).hide_helper_from_capture is True  # an explicit v2 choice is kept


@pytest.mark.parametrize("data, notes", [
    ({"hide_helper_from_capture": True}, 1),                          # previous release's default
    ({"hide_helper_from_capture": True, "settings_version": 1}, 1),
    ({"hide_helper_from_capture": False}, 0),
    ({}, 0),
])
def test_legacy_files_never_hide_the_window(tmp_path, data, notes):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    s = Settings.load(p)
    assert s.hide_helper_from_capture is False and len(s.load_notes) == notes and not s.load_warnings
