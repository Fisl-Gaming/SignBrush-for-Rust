import numpy as np
import pytest

from signbrush.dryrun import render_plan
from signbrush.planner import (
    UNKNOWN, BrushSpec, Plan, PlanOptions, Stroke, Timing, _runs_1d, estimate_seconds,
    plan_fixes, plan_strokes, rasterize, simulate,
)

PAL = [(0, 0, 0), (255, 255, 255), (200, 30, 30), (30, 60, 200), (40, 160, 40)]
FINE = BrushSpec("fine", 1.0)


def blobby(rows, cols, ncolors, seed):
    """Random image made of rectangles (realistic: areas + details)."""
    rng = np.random.default_rng(seed)
    img = np.full((rows, cols), rng.integers(ncolors), dtype=np.int32)
    for _ in range(12):
        r0, c0 = rng.integers(rows), rng.integers(cols)
        h, w = rng.integers(1, rows // 2 + 2), rng.integers(1, cols // 2 + 2)
        img[r0:r0 + h, c0:c0 + w] = rng.integers(ncolors)
    noise = rng.random((rows, cols)) < 0.05
    img[noise] = rng.integers(ncolors, size=noise.sum())
    return img


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("brushes", [
    [FINE],
    [FINE, BrushSpec("big", 4.0)],
    [FINE, BrushSpec("big", 5.5)],
])
@pytest.mark.parametrize("base_fill", [True, False])
@pytest.mark.parametrize("shape", ["square", "circle"])
def test_plan_reproduces_target_exactly(seed, brushes, base_fill, shape):
    target = blobby(23, 37, len(PAL), seed)
    plan = plan_strokes(target, PAL, brushes, PlanOptions(base_fill=base_fill), shape=shape)
    assert plan.shape == shape
    assert (simulate(plan) == target).all()


def test_noise_image_reproduced():
    rng = np.random.default_rng(42)
    target = rng.integers(0, len(PAL), size=(16, 20)).astype(np.int32)
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 3)])
    assert (simulate(plan) == target).all()


def test_points_stay_inside_canvas():
    target = blobby(20, 30, 5, 3)
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 6.0)])
    for s in plan.strokes:
        for x, y in s.points:
            assert 0 < x < plan.cols and 0 < y < plan.rows


def test_fine_strokes_are_axis_aligned():
    target = blobby(20, 30, 5, 4)
    plan = plan_strokes(target, PAL, [FINE], PlanOptions(base_fill=False))
    for s in plan.strokes:
        for (x0, y0), (x1, y1) in zip(s.points, s.points[1:]):
            assert x0 == x1 or y0 == y1


def test_uniform_image_is_base_fill_only_with_straight_bands():
    target = np.full((10, 40), 3, dtype=np.int32)
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 4)])
    assert plan.strokes and all(s.phase == "base" and s.brush == "big" for s in plan.strokes)
    for s in plan.strokes:                     # no corners: a missed frame cannot cut a diagonal
        assert len(s.points) == 2 and s.points[0][1] == s.points[1][1]
    assert (simulate(plan) == 3).all()


def test_solid_rectangle_becomes_single_snake_stroke():
    target = np.zeros((12, 12), dtype=np.int32)
    target[2:9, 3:10] = 2
    plan = plan_strokes(target, PAL, [FINE], PlanOptions(base_fill=True))
    reds = [s for s in plan.strokes if s.color == 2]
    assert len(reds) == 1
    assert (simulate(plan) == target).all()


def test_order_overpaints_details_instead_of_splitting_runs():
    # a white row crossed by a single black dot: one white stroke + one black dot,
    # not two white strokes, because black is painted later
    target = np.full((1, 21), 1, dtype=np.int32)
    target[0, 10] = 0
    plan = plan_strokes(target, PAL, [FINE], PlanOptions(base_fill=False))
    assert [s.color for s in plan.strokes] == [1, 0]
    assert len(plan.strokes[1].points) == 1
    assert (simulate(plan) == target).all()


def test_coarse_pass_used_for_big_blocks():
    target = np.full((16, 32), 1, dtype=np.int32)
    target[4:12, 4:28] = 3
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 4)], PlanOptions(base_fill=True))
    phases = plan.summary()["phases"]
    assert phases.get("coarse", 0) >= 1
    assert (simulate(plan) == target).all()


def test_fixes_only_touch_wrong_cells():
    target = blobby(15, 15, 4, 7)
    assert plan_fixes(target, target.copy(), PAL, [FINE]).strokes == []
    observed = target.copy()
    observed[5, 6] = (target[5, 6] + 1) % 4
    fix = plan_fixes(target, observed, PAL, [FINE, BrushSpec("big", 4)])
    assert len(fix.strokes) == 1 and fix.strokes[0].points == ((6.5, 5.5),)
    assert fix.strokes[0].phase == "fix"
    assert (simulate(fix, canvas=observed) == target).all()


def test_skip_colors_are_never_painted():
    target = blobby(15, 25, 4, 9)
    plan = plan_strokes(target, PAL, [FINE], PlanOptions(base_fill=False, skip_colors=(0,)))
    assert all(s.color != 0 for s in plan.strokes)
    res = simulate(plan)
    keep = target != 0
    assert (res[keep] == target[keep]).all()
    assert (res[~keep] == UNKNOWN).all()


def test_runs_bridge_limit():
    allowed = np.ones(10, bool)
    needy = np.zeros(10, bool)
    needy[[0, 4, 9]] = True
    assert _runs_1d(allowed, needy, max_bridge=4) == [(0, 9)]
    assert _runs_1d(allowed, needy, max_bridge=3) == [(0, 4), (9, 9)]
    allowed[2] = False
    assert _runs_1d(allowed, needy, max_bridge=10) == [(0, 0), (4, 9)]


def test_rasterize_square_brush_fills_corners():
    cv = np.full((9, 9), UNKNOWN, dtype=np.int32)
    rasterize(cv, Stroke(1, "b", ((4.5, 4.5),)), radius=2.0, shape="square")
    assert (cv[2:7, 2:7] == 1).all()
    assert (cv[1, :] == UNKNOWN).all() and (cv[:, 7] == UNKNOWN).all()
    cv[:] = UNKNOWN
    rasterize(cv, Stroke(2, "b", ((1.5, 3.5), (6.5, 3.5))), radius=0.5, shape="square")
    assert (cv[3, 1:7] == 2).all() and (cv == 2).sum() == 6


def test_square_coarse_blocks_need_no_fine_touch_up():
    target = np.full((16, 32), 1, dtype=np.int32)
    target[4:12, 8:24] = 3
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 4)], shape="square")
    assert plan.summary()["phases"].get("fine", 0) == 0
    assert (simulate(plan) == target).all()


def test_rasterize_round_brush():
    cv = np.full((9, 9), UNKNOWN, dtype=np.int32)
    rasterize(cv, Stroke(1, "b", ((4.5, 4.5),)), radius=2.0)
    assert cv[4, 4] == 1 and cv[4, 2] == 1 and cv[2, 4] == 1
    assert cv[2, 2] == UNKNOWN      # corner outside the circle


def test_plan_serialisation_roundtrip():
    target = blobby(10, 14, 4, 2)
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 3)])
    again = Plan.from_dict(plan.to_dict())
    assert again.strokes == plan.strokes
    assert again.fingerprint() == plan.fingerprint()


def test_estimate_scales_with_delays():
    plan = plan_strokes(blobby(20, 20, 4, 1), PAL, [FINE])
    fast = estimate_seconds(plan, Timing(action_delay=0.01), cell_px=5)
    slow = estimate_seconds(plan, Timing(action_delay=0.05), cell_px=5)
    assert 0 < fast < slow


def test_fewer_strokes_than_cells():
    target = blobby(40, 60, 5, 11)
    plan = plan_strokes(target, PAL, [FINE, BrushSpec("big", 5)])
    assert len(plan.strokes) < target.size / 5


def test_dryrun_render_matches_size():
    target = blobby(10, 20, 3, 5)
    plan = plan_strokes(target, PAL, [FINE])
    img = render_plan(plan, scale=3)
    assert img.size == (60, 30)
    # a pixel in the middle of a cell has the target colour
    assert img.getpixel((1 * 3 + 1, 1 * 3 + 1)) == PAL[target[1, 1]]


@pytest.mark.parametrize("brushes", [[FINE], [FINE, BrushSpec("big", 4)]])
def test_skip_mask_cells_are_never_painted(brushes):
    target = blobby(24, 36, 4, 8)
    skip = np.zeros_like(target, dtype=bool)
    skip[:, :10] = True                         # transparent left part
    skip[15:20, 20:30] = True                   # a hole in the middle
    plan = plan_strokes(target, PAL, brushes, PlanOptions(base_fill=True), skip_mask=skip)
    res = simulate(plan)
    assert (res[skip] == UNKNOWN).all()         # nothing touched the transparent cells
    assert (res[~skip] == target[~skip]).all()  # everything else is exact
    assert all(s.phase != "base" for s in plan.strokes)
