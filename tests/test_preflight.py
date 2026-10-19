"""Preflight checks (offline: the window lookup and Win32 probes are faked) and the
settings-file safety it relies on. Nothing here opens a window or clicks."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from r2clicker.config import Settings
from r2clicker.geometry import Mapping, WindowNotFound
from r2clicker.preflight import FAIL, OK, WARN, run_preflight

ROOT = Path(__file__).resolve().parent.parent
GAME = Mapping(200, 50, 1600, 900, hwnd=1234)


PTS = [(600, 300), (1000, 250)]


def pf(s=None, live=False, mapping=GAME, **kw):
    """run_preflight against a fake game window."""
    fakes = dict(resolve=lambda t, w, h: (mapping, f"fake '{t}'"), dpi_awareness=lambda: 2, dpi_of=lambda h: 96,
                 me_elevated=lambda: False, game_elevated=lambda h: False)
    fakes.update(kw)
    return run_preflight(s or Settings(manual_points=PTS), live, **fakes)


def status(r, name):
    return [i.status for i in r.items if i.name == name]


def test_all_good_passes_and_reports_every_item():
    r = pf()
    assert r.ok, r.text()
    assert [i.name for i in r.items] == ["mode", "settings", "game window", "DPI", "client size",
                                         "click points", "admin rights"]
    assert "DRY RUN" in r.items[0].message and r.text().startswith("PREFLIGHT PASSED")


def test_live_mode_is_flagged():
    r = pf(live=True)
    assert r.ok and status(r, "mode") == [WARN] and "LIVE" in r.items[0].message


def test_window_not_found_fails_with_guidance():
    def missing(t, w, h):
        raise WindowNotFound(f"no visible window title contains '{t}'")

    r = pf(resolve=missing)
    assert not r.ok and status(r, "game window") == [FAIL]
    assert "Start the game" in r.failures[0].message and "nothing is clicked" in r.text()


def test_invalid_settings_stop_before_touching_the_window():
    called = []
    r = pf(Settings(manual_points=[(1700, 440)]), resolve=lambda *a: called.append(1))
    assert not r.ok and status(r, "settings") == [FAIL] and not called
    assert "click point 1" in r.failures[0].message


def test_no_click_points_fails():
    r = pf(Settings())
    assert not r.ok and "no click points" in r.failures[0].message


def test_dpi_unaware_process_fails():
    r = pf(dpi_awareness=lambda: 0)
    assert not r.ok and status(r, "DPI") == [FAIL]


def test_system_aware_on_scaled_monitor_warns():
    r = pf(dpi_awareness=lambda: 1, dpi_of=lambda h: 144)
    assert r.ok and status(r, "DPI") == [WARN] and "150%" in [i for i in r.items if i.name == "DPI"][0].message


def test_tiny_client_fails_and_wrong_aspect_warns():
    r = pf(mapping=Mapping(0, 0, 400, 300, hwnd=1))
    assert status(r, "client size") == [FAIL]
    r = pf(mapping=Mapping(0, 0, 1200, 900, hwnd=1))
    assert r.ok and status(r, "client size") == [WARN]


def test_scaled_16_9_client_is_ok():
    r = pf(mapping=Mapping(0, 0, 1920, 1080, hwnd=1))
    assert r.ok and status(r, "client size") == [OK]


def test_click_points_are_reported():
    r = pf()
    assert r.ok and "2 points" in [i for i in r.items if i.name == "click points"][0].message


@pytest.mark.parametrize("me, game, live, expect", [
    (False, True, True, FAIL),    # game as admin, tool not: clicks would be dropped
    (False, True, False, WARN),   # same in dry run: nothing is clicked anyway
    (False, None, True, WARN),    # unknown (protected game)
    (True, True, True, OK),
    (False, False, True, OK),
])
def test_admin_rights(me, game, live, expect):
    r = pf(me_elevated=lambda: me, game_elevated=lambda h: game, live=live)
    assert status(r, "admin rights") == [expect]
    assert r.ok is (expect != FAIL)


def test_whole_screen_target_warns_and_skips_admin_check():
    r = pf(Settings(window_title="", manual_points=PTS), mapping=Mapping(0, 0, 1600, 900))
    assert r.ok and status(r, "game window") == [WARN] and status(r, "admin rights") == ["info"]


def test_real_probes_do_not_crash():
    from r2clicker.preflight import process_dpi_awareness, self_elevated, window_dpi, window_elevated

    assert process_dpi_awareness() in (None, 0, 1, 2)
    assert self_elevated() in (None, True, False)
    assert window_dpi(0) is None and window_elevated(0) is None


# --- command line: --preflight writes a report, never clicks, opens no window -----------------


def test_preflight_command_reports_missing_window(tmp_path):
    home = tmp_path / "home"
    Settings(window_title="NoSuchWindow-r2-preflight-test", manual_points=PTS).save(home / "settings.json")
    before = (home / "settings.json").read_bytes()
    out = tmp_path / "pf.json"
    env = dict(os.environ, R2_HELPER_HOME=str(home))
    p = subprocess.run([sys.executable, "-m", "r2clicker", "--preflight", str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    r = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 1 and r["ok"] is False
    assert any(i["name"] == "game window" and i["status"] == FAIL for i in r["items"])
    assert (home / "settings.json").read_bytes() == before


# --- settings file safety ---------------------------------------------------------------------


def test_unknown_keys_from_a_newer_release_survive_a_save(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"wait_interval": 4.0, "future_option": {"a": 1}}), encoding="utf-8")
    s = Settings.load(p)
    assert not s.load_warnings and s.extra == {"future_option": {"a": 1}}
    s.wait_interval = 6.0
    s.save(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["future_option"] == {"a": 1} and d["wait_interval"] == 6.0 and "extra" not in d


def test_unreadable_file_is_backed_up_once(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{broken", encoding="utf-8")
    for _ in range(3):  # the GUI loads again on close: still one copy
        s = Settings.load(p)
    assert any("unreadable" in w for w in s.load_warnings)
    copies = list(tmp_path.glob("settings.json.unreadable*"))
    assert [c.name for c in copies] == ["settings.json.unreadable"]
    assert copies[0].read_text(encoding="utf-8") == "{broken"
