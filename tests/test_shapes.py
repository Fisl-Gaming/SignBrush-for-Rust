import numpy as np
from PIL import Image

from signbrush.config import load_default
from signbrush.imaging import despeckle, kmeans_palette
from signbrush.pipeline import build_job
from signbrush.shapes import Shape, ShapeGenerator, ShapeOptions, make_disc, render, sort_shapes

PAL = np.array([(0, 0, 0), (255, 255, 255), (255, 51, 52), (52, 51, 255), (115, 116, 115)], float)
SIZES = [1.5, 3, 6, 12]
ALPHAS = [0.2, 0.5, 1.0]


def target_img():
    t = np.zeros((48, 64, 3))
    t[:, :32] = (200, 40, 40)
    t[10:30, 40:60] = (240, 240, 240)
    yy, xx = np.mgrid[:48, :64]
    t[..., 2] += xx * 2          # a gradient that needs blending
    return np.clip(t, 0, 255)


def test_disc_shapes():
    assert make_disc(1).mask.sum() == 1
    assert make_disc(3).mask.sum() == 9
    d = make_disc(12)
    assert d.mask.shape == (13, 13) and d.mask[6, 6] and not d.mask[0, 0]


def test_evaluate_matches_brute_force():
    g = ShapeGenerator(target_img(), PAL, (168, 147, 131), SIZES, ALPHAS)
    cx, cy = np.array([5, 40, 63]), np.array([5, 20, 47])
    for si in range(len(SIZES)):
        val, ai, ki = g.evaluate(si, cx, cy)
        for j in range(3):
            # brute force: apply the chosen circle on a copy and measure the error change
            before = ((g.T - g.C) ** 2).sum()
            g2 = ShapeGenerator(g.T, PAL, (168, 147, 131), SIZES, ALPHAS)
            g2.apply(Shape(int(cx[j]), int(cy[j]), si, int(ai[j]), int(ki[j])))
            after = ((g2.T - g2.C) ** 2).sum()
            assert np.isclose(after - before, val[j], rtol=1e-6, atol=1e-3)


def test_generator_reduces_error_and_stays_inside():
    g = ShapeGenerator(target_img(), PAL, (168, 147, 131), SIZES, ALPHAS, ShapeOptions(candidates=32))
    e0 = g.total_error
    shapes = g.run(150)
    assert len(shapes) > 50
    assert g.total_error < 0.4 * e0
    assert all(0 <= s.x < 64 and 0 <= s.y < 48 for s in shapes)
    # the incremental canvas equals a fresh render of the shape list
    img = render(shapes, (64, 48), PAL, (168, 147, 131), SIZES, ALPHAS)
    assert np.abs(img.astype(int) - np.clip(g.C, 0, 255).astype(np.uint8).astype(int)).max() <= 1


def test_sort_keeps_result_and_reduces_switches():
    g = ShapeGenerator(target_img(), PAL, (168, 147, 131), SIZES, ALPHAS, ShapeOptions(candidates=32))
    shapes = g.run(300)
    srt = sort_shapes(shapes, [d / 2 for d in SIZES], chunk=120)
    assert sorted(id(s) for s in srt) == sorted(id(s) for s in shapes)
    a = render(shapes, (64, 48), PAL, (168, 147, 131), SIZES, ALPHAS)
    b = render(srt, (64, 48), PAL, (168, 147, 131), SIZES, ALPHAS)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 1

    def switches(lst):
        return sum(1 for p, q in zip(lst, lst[1:]) if (p.size, p.alpha, p.color) != (q.size, q.alpha, q.color))
    assert switches(srt) < switches(shapes)


def test_shapes_job_end_to_end():
    cfg = load_default()
    s = cfg.settings
    s.algorithm, s.sign_type, s.shape_count, s.shape_work_size = "shapes", "sign.small.wood", 200, 64
    img = Image.fromarray(target_img().astype(np.uint8))
    seen = []
    job = build_job(img, cfg, progress=lambda st, f: seen.append(f))
    assert job.algorithm == "shapes" and job.target is None
    assert 0 < len(job.plan.strokes) <= 200 and seen
    assert job.preview.size == (256, 128)
    for st in job.plan.strokes:
        (x, y), = st.points
        assert 0 <= x <= 256 and 0 <= y <= 128
        assert st.brush in job.plan.brushes and 0 < st.alpha <= 1
    assert job.plan.brushes["s0"] == 3.0          # texture px


def test_kmeans_palette_finds_clusters():
    img = np.zeros((40, 40, 3), np.uint8)
    img[:20] = (250, 10, 10)
    img[20:, :20] = (10, 250, 10)
    img[20:, 20:] = (10, 10, 250)
    pal = kmeans_palette(img, 3)
    assert sorted(pal) == sorted([(250, 10, 10), (10, 250, 10), (10, 10, 250)])
    assert kmeans_palette(img, 3, extra=[(0, 0, 0)])[0] == (0, 0, 0)


def test_despeckle_removes_isolated_pixels_only():
    idx = np.zeros((10, 10), np.int32)
    idx[5, 5] = 1                    # isolated -> removed
    idx[0:3, 7:10] = 2               # a 3x3 block -> kept
    out = despeckle(idx, 1)
    assert out[5, 5] == 0
    assert (out[0:3, 7:10] == 2).all()


def test_hybrid_job_lays_strokes_then_fixes():
    from signbrush.planner import simulate
    cfg = load_default()
    s = cfg.settings
    s.algorithm, s.sign_type, s.detail, s.hybrid_shapes, s.fix_tolerance = "hybrid", "sign.small.wood", 4, 150, 6.0
    img = Image.fromarray(target_img().astype(np.uint8))
    job = build_job(img, cfg)
    assert job.algorithm == "hybrid" and (job.plan.cols, job.plan.rows) == (64, 32)
    phases = [st.phase for st in job.plan.strokes]
    assert phases[0] == "shape" and "fix" in phases
    assert phases.index("fix") > max(i for i, p in enumerate(phases) if p == "shape")   # coarse before fine
    assert job.plan.tip("s0") == "circle" and job.plan.tip("fine") == "square"
    assert all(st.alpha == 1.0 for st in job.plan.strokes if st.phase == "fix")
