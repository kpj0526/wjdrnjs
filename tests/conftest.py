import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE = Path(__file__).resolve().parent.parent / "assets" / "sample_1600x900.png"


@pytest.fixture(scope="session")
def base_img() -> Image.Image:
    return Image.open(FIXTURE).convert("RGB")


@pytest.fixture(scope="session")
def base(base_img) -> np.ndarray:
    return np.asarray(base_img)
