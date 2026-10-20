from r2clicker.geometry import Mapping


def test_identity_mapping():
    m = Mapping(0, 0, 1600, 900)
    assert m.to_screen(350, 130) == (350, 130)
    assert m.rect_to_client((350, 130, 1250, 670)) == (350, 130, 1250, 670)


def test_window_offset_and_scaling():
    # game client 1920x1080 whose top-left is at screen (100, 40)
    m = Mapping(100, 40, 1920, 1080)
    assert m.to_screen(0, 0) == (100, 40)
    assert m.to_screen(1600, 900) == (2020, 1120)
    assert m.to_screen(800, 450) == (1060, 580)
    assert m.rect_to_client((350, 130, 1250, 670)) == (420, 156, 1500, 804)
    x, y = m.to_ref(*m.to_screen(1250, 670))
    assert abs(x - 1250) < 1 and abs(y - 670) < 1


def test_non_uniform_scaling_and_negative_monitor():
    m = Mapping(-1280, 0, 1280, 800)  # left secondary monitor, 16:10
    assert m.to_screen(1600, 900) == (0, 800)
    assert m.to_screen(800, 450) == (-640, 400)
    assert m.scale_len(100) == 84  # (0.8 + 0.889)/2 * 100
