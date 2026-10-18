import numpy as np
import pytest
from PIL import Image

from r2clicker.config import Settings
from r2clicker.fixtures import frame_with_nameplate, jitter, save_nameplate_template
from r2clicker.geometry import Mapping
from r2clicker.vision import load_template, verify

M = Mapping(0, 0, 1600, 900)
SPOTS = [(700, 250), (1000, 420), (560, 560), (640, 330), (800, 330), (1150, 600), (450, 180)]


def test_real_screenshot_has_no_nameplate(base):
    # the busy cluster (skill flashes, green orbs, HP bar) must not look like a selection
    assert not verify(base, Settings(verify_mode="absolute"), M).ok


@pytest.mark.parametrize("shift", [(1, 0), (2, 1), (4, 3), (8, -5), (15, 10), (30, 20)])
def test_animation_motion_is_not_a_selection(base, shift):
    after = np.roll(base, (shift[1], shift[0]), (0, 1))
    assert not verify(after, Settings(), M, before=base).ok


@pytest.mark.parametrize("spot", SPOTS)
def test_nameplate_detected_diff(base_img, base, spot):
    after = jitter(frame_with_nameplate(base_img, spot), 1)
    r = verify(after, Settings(), M, before=jitter(base, 2))
    assert r.ok, r.summary()
    bx1, by1, bx2, by2 = r.box
    assert bx1 - 10 <= spot[0] <= bx2 + 10 and by1 - 10 <= spot[1] <= by2 + 10


@pytest.mark.parametrize("spot", SPOTS)
def test_nameplate_detected_absolute(base_img, spot):
    r = verify(frame_with_nameplate(base_img, spot), Settings(verify_mode="absolute"), M)
    assert r.ok, r.summary()


def test_white_text_without_green_markers_rejected(base_img, base):
    # e.g. a hover label or a chat bubble: white text but no selection markers
    after = frame_with_nameplate(base_img, (700, 250), markers=False)
    r = verify(after, Settings(), M, before=base)
    assert not r.ok and "green" in r.reason


def test_nameplate_already_present_in_baseline_is_not_new(base_img):
    a = frame_with_nameplate(base_img, (700, 250))
    assert not verify(a, Settings(), M, before=a).ok


def test_nameplate_outside_roi_margin_ignored(base_img, base):
    s = Settings(roi=(350, 130, 700, 400), verify_margin=20)
    after = frame_with_nameplate(base_img, (1100, 600))
    assert not verify(after, s, M, before=base).ok


def test_scaled_client(base_img):
    big = base_img.resize((1920, 1080), Image.BILINEAR)
    m = Mapping(0, 0, 1920, 1080)
    after = frame_with_nameplate(big, (840, 300), size=14)  # 700,250 in reference coordinates
    r = verify(after, Settings(), m, before=np.asarray(big))
    assert r.ok, r.summary()
    assert abs((r.box[0] + r.box[2]) / 2 - 700) < 30


def test_template_mode(tmp_path, base_img, base):
    p = tmp_path / "plate.png"
    save_nameplate_template(p)
    s = Settings(template_path=str(p))
    tmpl = load_template(str(p), s)
    assert tmpl is not None
    hit = verify(frame_with_nameplate(base_img, (640, 330)), s, M, before=base, template=tmpl)
    assert hit.ok and hit.template_score > 0.8, hit.summary()
    miss = verify(base, Settings(verify_mode="absolute", template_path=str(p)), M, template=tmpl)
    assert not miss.ok, miss.summary()


def test_verify_is_fast(base_img, base):
    after = frame_with_nameplate(base_img, (700, 250))
    r = verify(after, Settings(), M, before=base)
    assert r.ms < 400  # generous for slow machines; ~80 ms on a desktop
