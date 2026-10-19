import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_selftest_passes_from_source(tmp_path):
    # A fresh process, like the packaged exe: the self-test creates its own Tk interpreter, and a
    # second interpreter inside the pytest process (after the GUI tests) is unreliable on Windows.
    out = tmp_path / "selftest.json"
    env = dict(os.environ, R2_HELPER_HOME=str(tmp_path / "home"))
    if os.environ.get("R2_SKIP_DESKTOP_TESTS") == "1":
        env["R2_SELFTEST_NO_WINDOW"] = "1"  # the PrintWindow step maps a small window on screen
    p = subprocess.run([sys.executable, "-m", "r2clicker", "--selftest", str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    r = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and r["passed"], r
    assert set(r["checks"]) == {"sample", "tk_and_window_capture", "candidates", "detect", "dry_cycle",
                                "manual_cycle", "preflight", "dpi_awareness", "settings_io", "settings_untouched"}
    assert not list((tmp_path / "home").glob("settings*.json"))


def test_selftest_keeps_existing_user_settings(tmp_path):
    from r2clicker.config import Settings

    home = tmp_path / "home"
    home.mkdir()
    Settings(wait_interval=7.5, manual_points=[(600, 300)]).save(home / "settings.json")
    before = (home / "settings.json").read_bytes()
    env = dict(os.environ, R2_HELPER_HOME=str(home), R2_SELFTEST_NO_WINDOW="1")
    out = tmp_path / "selftest.json"
    p = subprocess.run([sys.executable, "-m", "r2clicker", "--selftest", str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    r = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and r["checks"]["settings_untouched"] == "ok", r
    assert (home / "settings.json").read_bytes() == before
