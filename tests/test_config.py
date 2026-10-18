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
    p.write_bytes("﻿".encode() + json.dumps({"window_title": "알투"}).encode("utf-8"))
    assert Settings.load(p).window_title == "알투"
