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
    p = subprocess.run([sys.executable, "-m", "r2clicker", "--selftest", str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    r = json.loads(out.read_text(encoding="utf-8"))
    assert p.returncode == 0 and r["passed"], r
    assert set(r["checks"]) == {"sample", "tk", "candidates", "detect", "dry_cycle", "settings_io"}
    assert not list((tmp_path / "home").glob("settings*.json"))
