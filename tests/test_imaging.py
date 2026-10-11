import numpy as np
import pytest
from PIL import Image

from signbrush.imaging import (
    ImageOptions, background_index, build_lut, choose_colors, fit_image, flatten_alpha,
    grid_size, nearest_palette, parse_color, prepare_image, quantize, srgb_to_lab, to_hex,
)

BW = np.array([[0, 0, 0], [255, 255, 255]], dtype=float)
RGBK = np.array([[0, 0, 0], [255, 255, 255], [220, 30, 30], [30, 60, 200], [40, 160, 40]], dtype=float)


def test_parse_and_format_color():
    assert parse_color("#FF8000") == (255, 128, 0)
    assert parse_color("0f0") == (0, 255, 0)
    assert parse_color([1, 2, 3]) == (1, 2, 3)
    assert to_hex((255, 128, 0)) == "#FF8000"
    with pytest.raises(ValueError):
        parse_color("#12345")


def test_lab_reference_values():
    lab = srgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0]]))
    assert lab[0] == pytest.approx([100, 0, 0], abs=0.05)
    assert lab[1] == pytest.approx([0, 0, 0], abs=0.05)
    assert lab[2] == pytest.approx([53.24, 80.09, 67.20], abs=0.1)


def test_grid_size_and_limit():
    assert grid_size((600, 300), 6) == (100, 50)
    cols, rows = grid_size((600, 300), 1, max_cells=5000)
    assert cols * rows <= 5000
    assert cols / rows == pytest.approx(2, rel=0.05)


def test_flatten_alpha_fills_background():
    img = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    img.putpixel((1, 1), (255, 0, 0, 255))
    out = np.asarray(flatten_alpha(img, (0, 0, 255)))
    assert tuple(out[0, 0]) == (0, 0, 255)
    assert tuple(out[1, 1]) == (255, 0, 0)


def test_flatten_alpha_threshold_binarises():
    img = Image.new("RGBA", (2, 1), (255, 0, 0, 100))
    img.putpixel((1, 0), (255, 0, 0, 200))
    out = np.asarray(flatten_alpha(img, (0, 0, 0), alpha_threshold=128))
    assert tuple(out[0, 0]) == (0, 0, 0)
    assert tuple(out[0, 1]) == (255, 0, 0)


def test_fit_pad_letterboxes_wide_image():
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    out = np.asarray(fit_image(img, (20, 20), "pad", background=(0, 255, 0)))
    assert out.shape == (20, 20, 3)
    assert tuple(out[0, 10]) == (0, 255, 0)      # top margin
    assert tuple(out[10, 10]) == (255, 0, 0)     # picture in the middle
    assert tuple(out[19, 10]) == (0, 255, 0)     # bottom margin


def test_fit_crop_fills_canvas():
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    img.paste((0, 0, 255), (0, 0, 20, 100))        # left strip gets cropped away
    out = np.asarray(fit_image(img, (20, 20), "crop", background=(0, 255, 0)))
    assert out.shape == (20, 20, 3)
    assert (out == [255, 0, 0]).all()


def test_fit_stretch_and_bad_mode():
    img = Image.new("RGB", (10, 30), (1, 2, 3))
    assert fit_image(img, (40, 5), "stretch").size == (40, 5)
    with pytest.raises(ValueError):
        fit_image(img, (4, 4), "zoom")


def test_quantize_exact_palette_colours_map_to_themselves():
    rgb = RGBK[None, :, :].repeat(3, axis=0)
    for dither in (False, True):
        idx = quantize(rgb, RGBK, dither=dither)
        assert (idx == np.arange(len(RGBK))[None, :]).all()


def test_lut_matches_bruteforce():
    rng = np.random.default_rng(1)
    px = rng.integers(0, 64, size=(500, 3)) * 4 + 2     # LUT bin centres
    lut = build_lut(RGBK)
    via_lut = lut[px[:, 0] >> 2, px[:, 1] >> 2, px[:, 2] >> 2]
    assert (via_lut == nearest_palette(px.astype(float), RGBK)).all()


def test_dither_produces_mix_for_mid_gray():
    gray = np.full((32, 32, 3), 128.0)
    plain = quantize(gray, BW, dither=False)
    assert len(np.unique(plain)) == 1
    dith = quantize(gray, BW, dither=True)
    white_share = (dith == 1).mean()
    assert 0.4 < white_share < 0.6


def test_choose_colors_keeps_required_and_picks_present():
    img = np.zeros((10, 10, 3))
    img[:, :5] = RGBK[2]
    img[:, 5:] = RGBK[3]
    chosen = choose_colors(img, RGBK, 3, required=[1])
    assert chosen == [1, 2, 3]
    assert choose_colors(img, RGBK, 0) == list(range(len(RGBK)))


def test_background_index():
    assert background_index(RGBK, (250, 250, 250)) == 1


def test_prepare_image_pipeline():
    img = Image.new("RGBA", (60, 30), (0, 0, 0, 0))
    img.paste((220, 30, 30, 255), (10, 5, 50, 25))
    opts = ImageOptions(fit="pad", background=(255, 255, 255), max_colors=3)
    prep = prepare_image(img, (30, 15), RGBK, opts)
    assert prep.indices.shape == (15, 30)
    assert set(np.unique(prep.indices)) <= set(prep.used)
    assert len(prep.used) == 3 and 1 in prep.used
    assert prep.indices[0, 0] == 1      # transparent -> white background
    assert prep.indices[7, 15] == 2     # red block
    assert prep.preview(2).size == (60, 30)
