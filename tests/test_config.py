import json

import pytest

from r2clicker.config import Settings


def test_defaults_are_valid():
    assert Settings().validate() == []


@pytest.mark.parametrize(
    "kw, needle",
    [
        (dict(roi=(1250, 130, 350, 670)), "ROI"),
        (dict(roi=(350, 130, 1700, 670)), "ROI"),
        (dict(roi=(350, 130, 360, 670)), "grid step"),
        (dict(wait_interval=-1.0), "wait_interval"),
        (dict(wait_interval=float("nan")), "wait_interval"),
        (dict(max_attempts=0), "max_attempts"),
        (dict(grid_step=2), "grid_step"),
        (dict(verify_delay=1.0, verify_timeout=0.5), "verify_timeout"),
        (dict(order="zigzag"), "order"),
        (dict(verify_mode="fuzzy"), "verify_mode"),
        (dict(right_click_target="mob"), "right_click_target"),
        (dict(park_point=(800, 400)), "outside the ROI"),
        (dict(park_point=(1700, 300)), "park_point"),
        (dict(player_center=(-5, 10)), "player_center"),
        (dict(ui_rects=[(10, 10, 5, 50)]), "ui_rects"),
        (dict(emergency_hotkey="F13"), "emergency_hotkey"),
        (dict(dry_run=False, emergency_hotkey="", corner_failsafe=False), "emergency"),
        (dict(template_path="does/not/exist.png"), "template"),
        (dict(white_min=300), "white_min"),
        (dict(template_min_score=1.5), "template_min_score"),
    ],
)
def test_invalid_settings_reported(kw, needle):
    errs = Settings(**kw).validate()
    assert any(needle in e for e in errs), errs


def test_live_mode_with_one_safety_is_fine():
    assert Settings(dry_run=False, emergency_hotkey="", corner_failsafe=True).validate() == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "settings.json"
    s = Settings(wait_interval=7.25, roi=(400, 150, 1200, 650), ui_rects=[(0, 0, 10, 10)], dry_run=False)
    s.save(p)
    t = Settings.load(p)
    assert (t.wait_interval, t.roi, t.ui_rects, t.dry_run) == (7.25, (400, 150, 1200, 650), [(0, 0, 10, 10)], False)
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
    assert s.roi == Settings().roi and s.dry_run is True
    assert s.load_warnings


def test_wrong_types_keep_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "wait_interval": "fast", "max_attempts": 2.5, "roi": [1, 2, 3], "dry_run": "no",
        "grid_step": 40, "unknown_key": 1, "order": 5,
    }), encoding="utf-8")
    s = Settings.load(p)
    d = Settings()
    assert (s.wait_interval, s.max_attempts, s.roi, s.dry_run, s.order) == (
        d.wait_interval, d.max_attempts, d.roi, True, d.order)
    assert s.grid_step == 40
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


@pytest.mark.parametrize("data", [
    {"right_click_delay": 0.1, "right_click_hover": 0.1, "right_click_hold": 0.15, "settings_version": 2},  # 0.1.x
    {"right_click_delay": 0.0, "right_click_hover": 0.03, "point_delay": 0.1, "settings_version": 4},       # 0.2.x
])
def test_older_right_click_timing_is_replaced_by_the_new_defaults(tmp_path, data):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({**data, "wait_interval": 3.0, "manual_points": [[600, 300]]}), encoding="utf-8")
    s = Settings.load(p)
    d = Settings()
    assert (s.right_click_delay, s.right_click_hover) == (d.right_click_delay, d.right_click_hover)
    assert s.wait_interval == 3.0 and s.manual_points == [(600, 300)] and not s.load_warnings
    s.save(p)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert "right_click_hold" not in saved and "point_delay" not in saved


def test_current_right_click_timing_is_kept(tmp_path):
    p = tmp_path / "s.json"
    Settings(right_click_delay=0.2, right_click_hover=0.05).save(p)
    s = Settings.load(p)
    assert (s.right_click_delay, s.right_click_hover) == (0.2, 0.05)
