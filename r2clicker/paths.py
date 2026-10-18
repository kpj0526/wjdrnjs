"""Where settings, logs and bundled resources live, from source and from a PyInstaller build.

Data folder:
- Source checkout: the repository root (next to README.md).
- Packaged exe: the folder of the exe if it is writable ("portable" zip use), otherwise
  %LOCALAPPDATA%\\R2TargetHelper (e.g. when unpacked under Program Files).
- R2_HELPER_HOME overrides both (used by tests and the packaging self-test).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "R2TargetHelper"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(rel: str) -> Path:
    """A file shipped with the app (inside the PyInstaller bundle, or in the source tree)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".write-test-", delete=True):
            pass
        return True
    except OSError:
        return False


def data_dir() -> Path:
    env = os.environ.get("R2_HELPER_HOME")
    if env:
        d = Path(env)
        d.mkdir(parents=True, exist_ok=True)
        return d
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        if _writable(exe_dir):
            return exe_dir
        d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent.parent


def settings_path() -> Path:
    return data_dir() / "settings.json"


def resolve_in_data_dir(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else data_dir() / q


SAMPLE_REL = "assets/sample_1600x900.png"


def sample_image() -> Path | None:
    p = resource_path(SAMPLE_REL)
    return p if p.is_file() else None
