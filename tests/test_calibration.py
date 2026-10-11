import numpy as np
import pytest

from signbrush.calibration import STEPS, apply_results, detect_canvas
from signbrush.config import load_default


def fake_editor():
    """1280x720 'screenshot': dark background, a 512x256 canvas, a 4x16 palette."""
    img = np.full((720, 1280, 3), 35, dtype=np.uint8)
    img[100:356, 100:612] = (168, 147, 131)                    # canvas
    rng = np.random.default_rng(0)
    colors = rng.integers(0, 256, size=(64, 3), dtype=np.uint8)
    for i, c in enumerate(colors):
        r, col = divmod(i, 4)
        y, x = 200 + r * 20, 900 + col * 30
        img[y - 8:y + 9, x - 12:x + 13] = c
    return img, colors


def test_apply_results_samples_palette_and_sets_controls():
    img, colors = fake_editor()
    prof = load_default().profile
    res = {
        "canvas": ((100, 100), (611, 355)),
        "palette": ((900, 200), (990, 500)),
        "size_slider": ((700, 50), (860, 50)),
        "opacity_textbox": ((880, 80),),
        "save": ((1000, 600),),
        "focus": ((300, 200),),                   # on the canvas -> rejected
    }
    warns = apply_results(prof, res, img, origin=(1920, 0), screen_size=(1280, 720), grid=(4, 16))
    assert prof.canvas == (2020, 100, 2531, 355)
    assert prof.palette_grid.first == (2820, 200)
    assert [c.rgb for c in prof.palette] == [tuple(int(v) for v in c) for c in colors]
    assert prof.swatch_positions()[5] == (2850, 220)
    assert prof.controls["size"].slider_min == (2620, 50)
    assert prof.controls["opacity"].textbox == (2800, 80)
    assert prof.buttons["save"] == (2920, 600)
    assert prof.buttons["focus"] is None and any("focus" in w for w in warns)
    # focus was rejected (on the canvas) but typed values need it to be applied without Enter
    assert prof.missing_calibration("palette") == ["focus"]
    assert prof.missing_calibration("hex") == ["hex_field", "focus"]


def test_too_small_canvas_rejected():
    img, _ = fake_editor()
    with pytest.raises(ValueError):
        apply_results(load_default().profile, {"canvas": ((10, 10), (15, 15))}, img)


def test_detect_canvas_finds_rectangle_with_aspect():
    img, _ = fake_editor()
    rect = detect_canvas(img, aspect=2.0)
    assert rect is not None
    x0, y0, x1, y1 = rect
    assert abs(x0 - 100) <= 3 and abs(y0 - 100) <= 3 and abs(x1 - 611) <= 3 and abs(y1 - 355) <= 3


def test_steps_are_unique_and_required_first():
    keys = [s.key for s in STEPS]
    assert len(keys) == len(set(keys))
    assert [s.key for s in STEPS if not s.optional] == ["canvas"]


def hue_bar_screenshot():
    """Picker like the 2025 editor: SV square + vertical hue bar (red top, hue decreasing downwards)."""
    import colorsys
    img = np.full((400, 600, 3), 30, dtype=np.uint8)
    for y in range(300):
        r, g, b = colorsys.hsv_to_rgb(1 - y / 299 if y else 0.0, 1, 1)
        img[50 + y, 400:440] = (int(r * 255), int(g * 255), int(b * 255))
    return img


def test_picker_calibration_and_click_points():
    import colorsys
    from signbrush.executor import Executor, RecordingKeyboard
    from signbrush.planner import Plan
    from signbrush.winput import RecordingMouse

    img = hue_bar_screenshot()
    cfg = load_default()
    prof = cfg.profile
    apply_results(prof, {"canvas": ((10, 10), (300, 300)), "picker_sv": ((50, 50), (349, 349)),
                         "picker_hue": ((420, 50), (420, 349))}, img)
    assert prof.picker_sv == (50, 50, 349, 349) and len(prof.picker_hue_lut) > 60
    assert "picker" not in prof.missing_calibration("picker")
    ex = Executor(Plan(1, 1, [(0, 0, 0)], {"fine": 1.0}), None, prof, cfg.settings, RecordingMouse(),
                  RecordingKeyboard(), color_mode="picker", check_window=lambda: "Rust")
    for rgb in ((255, 0, 0), (0, 200, 40), (30, 60, 220), (185, 14, 32)):
        hue_pt, (sx, sy) = ex.picker_points(rgb)
        h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        bar = img[hue_pt[1], 420]                      # the bar colour where we would click
        bh = colorsys.rgb_to_hsv(*(c / 255 for c in bar))[0]
        assert min(abs(bh - h), 1 - abs(bh - h)) < 0.02
        assert abs((sx - 50) / 299 - sat) < 0.01 and abs(1 - (sy - 50) / 299 - val) < 0.01
    hue_pt, sv = ex.picker_points((128, 128, 128))     # grey: no hue click needed
    assert hue_pt is None and sv[0] == 50
