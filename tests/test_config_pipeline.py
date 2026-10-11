import json

import numpy as np
import pytest
from PIL import Image

from signbrush.config import Config, Control, PaletteGrid, load_config, load_default
from signbrush.pipeline import FILL, FINE, Geometry, build_job
from signbrush.planner import simulate


def test_default_config_matches_current_editor():
    cfg = load_default()
    assert cfg.settings.color_mode == "hex" and cfg.settings.save_method == "off"
    assert cfg.profile.palette_grid.cols * cfg.profile.palette_grid.rows == len(cfg.profile.palette)
    assert cfg.sign("auto").size == (512, 512)              # no canvas yet
    cfg.profile.canvas = (821, 506, 1164, 934)
    assert cfg.sign("auto").size == (411, 512)              # canvas aspect, long side 512
    cfg.profile.canvas = (0, 0, 687, 857)                   # same frame zoomed in: same resolution
    assert cfg.sign("auto").size == (411, 512)
    # a sign type whose table aspect does not match the canvas keeps its resolution (long side)
    # but takes the aspect of the canvas - no stretched cells
    assert cfg.sign("sign.medium.wood").size == (411, 512)
    assert cfg.sign("sign.pictureframe.xxl").size == (821, 1024)
    cfg.profile.canvas = (0, 0, 1023, 511)                  # 2:1 canvas: the table aspect is kept
    assert cfg.sign("sign.medium.wood").size == (512, 256)
    assert cfg.sign("sign.pictureframe.xxl").size == (1024, 512)


def test_config_roundtrip_and_v1_migration(tmp_path):
    p = tmp_path / "config.json"
    cfg = load_config(p)                    # created from defaults
    cfg.profile.canvas = (10, 20, 521, 275)
    cfg.profile.picker_sv = (2050, 762, 2360, 1073)
    cfg.profile.picker_hue = ((2390, 762), (2390, 1073))
    cfg.profile.picker_hue_lut = [(0.0, 0.0), (0.5, 180.0)]
    cfg.settings.detail = 3
    cfg.save()
    again = load_config(p)
    assert again.profile.canvas == (10, 20, 521, 275)
    assert again.profile.picker_hue == ((2390, 762), (2390, 1073))
    assert again.profile.picker_hue_lut == [(0.0, 0.0), (0.5, 180.0)]
    assert again.settings.detail == 3
    assert again.to_dict() == cfg.to_dict()
    p.write_text(json.dumps({"version": 1, "profiles": {"x": {}}}), encoding="utf-8")
    migrated = load_config(p)
    assert migrated.settings.color_mode == "hex"
    assert (tmp_path / "config.v1.json").exists()


def test_custom_sign_size():
    cfg = load_default()
    cfg.settings.sign_type = "custom"
    cfg.settings.custom_size = "300x100"
    assert cfg.sign().size == (300, 100)


def test_palette_grid_positions_row_major():
    g = PaletteGrid(first=(100, 200), last=(130, 350), cols=4, rows=16)
    pos = g.positions()
    assert len(pos) == 64
    assert pos[0] == (100, 200) and pos[3] == (130, 200)
    assert pos[4] == (100, 210) and pos[-1] == (130, 350)


def test_control_slider_point():
    c = Control(slider_min=(100, 50), slider_max=(300, 50), range=(1, 32))
    assert c.slider_point(1) == (100, 50)
    assert c.slider_point(32) == (300, 50)
    assert c.slider_point(100) == (300, 50)
    assert c.usable and not Control().usable


def test_geometry_and_screen_mapping():
    cfg = load_default()
    geo = Geometry.for_sign(cfg.sign("sign.medium.wood"), detail=2)
    assert (geo.cols, geo.rows) == (256, 128)
    specs = geo.brushes(16)
    assert specs[0].name == FINE and specs[1].name == FILL and specs[1].diameter == 8
    canvas = (1000, 100, 1511, 355)          # 512x256 on screen -> 2 screen px per cell
    assert geo.to_screen(canvas, 0.5, 0.5) == (1001, 101)
    assert geo.to_screen(canvas, 255.5, 127.5) == (1511, 355)
    small = Geometry.for_sign(cfg.sign("sign.pictureframe.xxl"), detail=1, max_cells=50000)
    assert small.cols * small.rows <= 50000


@pytest.mark.parametrize("mode", ["palette", "hex"])
def test_build_job_end_to_end(mode):
    cfg = load_default()
    cfg.settings.sign_type = "sign.small.wood"
    cfg.settings.detail = 4
    cfg.settings.color_mode = mode
    cfg.settings.algorithm = "pixels"
    cfg.settings.max_colors = 8
    img = Image.new("RGB", (120, 60), (250, 250, 250))
    img.paste((200, 30, 30), (20, 10, 70, 50))
    job = build_job(img, cfg)
    assert (job.plan.cols, job.plan.rows) == (64, 32)
    assert (simulate(job.plan) == job.prepared.indices).all()
    assert job.estimate_s > 0
    if mode == "hex":
        assert len(job.prepared.palette) <= 9


@pytest.mark.parametrize("algo", ["pixels", "hybrid"])
def test_transparent_areas_can_be_skipped(algo):
    cfg = load_default()
    s = cfg.settings
    s.algorithm, s.sign_type, s.detail, s.transparent, s.hybrid_shapes = algo, "sign.small.wood", 4, "skip", 80
    img = Image.new("RGBA", (128, 64), (0, 0, 0, 0))            # transparent everywhere ...
    img.paste((200, 30, 30, 255), (40, 16, 88, 48))              # ... except a red block
    job = build_job(img, cfg)
    assert job.skip_mask is not None and job.skip_mask[0, 0] and not job.skip_mask[16, 32]
    canvas = simulate(job.plan) if algo == "pixels" else None
    if canvas is not None:
        assert (canvas[job.skip_mask] == -1).all()
    fixes = [st for st in job.plan.strokes if st.phase in ("fine", "fix")]
    for st in fixes:
        for x, y in st.points:
            assert not job.skip_mask[int(y), int(x)]
