"""Click points in the settings: storage, validation, and files saved by the old releases."""
import json

import pytest

from r2clicker.config import MAX_MANUAL_POINTS, SETTINGS_VERSION, Settings, point_reason

PTS = [(600, 300), (1000, 250), (500, 550)]


def test_default_has_no_points_and_cannot_run():
    s = Settings()
    assert s.manual_points == []
    assert any("no click points" in e for e in s.validate())
    assert s.validate(include_manual=False) == []  # the form can still be applied and saved


def test_roundtrip_keeps_order(tmp_path):
    p = tmp_path / "settings.json"
    Settings(manual_points=list(PTS)).save(p)
    assert json.loads(p.read_text(encoding="utf-8"))["manual_points"] == [list(x) for x in PTS]
    s = Settings.load(p)
    assert s.manual_points == PTS and all(isinstance(x, tuple) for x in s.manual_points)
    assert not s.load_warnings


@pytest.mark.parametrize("bad", ["600,300", [[1, 2, 3]], [5], 7, [["a", "b"]]])
def test_malformed_points_keep_default_with_warning(tmp_path, bad):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"manual_points": bad, "wait_interval": 2.0}), encoding="utf-8")
    s = Settings.load(p)
    assert s.manual_points == [] and s.wait_interval == 2.0
    assert any("manual_points" in w for w in s.load_warnings)


@pytest.mark.parametrize("pt, ok", [
    ((0, 0), True),
    ((800, 440), True),        # on the player: allowed now, the user decides
    ((100, 850), True),        # on the HUD: allowed now
    ((1599, 899), True),
    ((1600, 400), False),      # off the client
    ((-1, 10), False),
])
def test_only_points_off_the_client_are_refused(pt, ok):
    assert (point_reason(pt, Settings()) is None) is ok


def test_bad_points_fail_validation_with_their_number():
    errs = Settings(manual_points=[(600, 300), (1700, 300)]).validate()
    assert any("click point 2" in e and "outside" in e for e in errs)


def test_too_many_points_refused():
    s = Settings(manual_points=[(600, 300)] * (MAX_MANUAL_POINTS + 1))
    assert any("at most" in e for e in s.validate())


def test_old_release_file_keeps_points_and_wait_and_drops_nameplate_settings(tmp_path):
    """A settings.json written by 0.1.x (as on the customer's PC) loads into the auto clicker."""
    old = {"window_title": "R2", "wait_interval": 3.0, "manual_points": [list(p) for p in PTS],
           "roi": [350, 130, 1250, 670], "marker_min_green": 60, "max_attempts": 30, "verify_mode": "diff",
           "right_click_delay": 0.1, "park_point": [1480, 300], "settings_version": 2, "dry_run": False}
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    s = Settings.load(p)
    assert s.manual_points == PTS and s.wait_interval == 3.0 and s.dry_run is False
    assert s.right_click_delay == 0  # old meaning (pause after the check) is not carried over
    assert not s.load_warnings and any("ignored" in n for n in s.load_notes)
    assert s.validate() == []
    s.save(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "roi" not in d and "marker_min_green" not in d and d["settings_version"] == SETTINGS_VERSION


def test_right_click_delay_of_a_current_file_is_kept(tmp_path):
    p = tmp_path / "settings.json"
    Settings(right_click_delay=0.25, manual_points=list(PTS)).save(p)
    assert Settings.load(p).right_click_delay == 0.25
