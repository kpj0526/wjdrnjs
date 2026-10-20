import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from r2clicker.geometry import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()  # as the app does: window, cursor and capture coordinates in physical pixels

FIXTURE = Path(__file__).resolve().parent.parent / "assets" / "sample_1600x900.png"


@pytest.fixture(scope="session")
def base_img() -> Image.Image:
    return Image.open(FIXTURE).convert("RGB")


@pytest.fixture(scope="session")
def base(base_img) -> np.ndarray:
    return np.asarray(base_img)


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tcl interpreter for the whole run, like the real app: creating many Tk()
    instances in one process intermittently fails on Windows with "Can't find a usable tk.tcl"."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    root.withdraw()
    yield root
    root.destroy()
