import threading

import numpy as np
from PIL import Image

from signbrush.config import load_default
from signbrush.executor import Controller, Executor, Progress, RecordingKeyboard, verify_and_fix
from signbrush.pipeline import build_job
from signbrush.winput import RecordingMouse

CANVAS = (1000, 200, 1127, 263)        # 128 x 64 screen px for a 64 x 32 grid


def make_cfg(mode="palette"):  # noqa: D103
    cfg = load_default()
    s = cfg.settings
    s.algorithm = "pixels"
    s.sign_type, s.custom_size, s.detail, s.fill_size = "custom", "64x32", 1, 8
    s.color_mode, s.max_colors = mode, 6
    for k in ("action_delay_ms", "move_delay_ms", "draw_step_delay_ms", "click_hold_ms",
              "color_switch_ms", "brush_switch_ms"):
        setattr(s, k, 0)
    s.save_every, s.save_method = 20, "ctrl+s"
    s.game_fps = 0
    p = cfg.profile
    p.canvas = CANVAS
    from signbrush.config import PaletteColor
    favs = [(0, 0, 0), (255, 255, 255), (255, 51, 52), (52, 51, 255), (115, 116, 115), (255, 215, 52)]
    p.palette = [PaletteColor(f"F{i}", c) for i, c in enumerate(favs)]
    p.palette_grid.cols, p.palette_grid.rows = 1, len(favs)
    p.palette_grid.first, p.palette_grid.last = (1600, 300), (1600, 750)
    p.controls["size"].slider_min, p.controls["size"].slider_max = (1600, 150), (1760, 150)
    p.controls["opacity"].textbox = (1800, 180)
    p.buttons["hex_field"] = (1700, 800)
    p.buttons["brush_square"] = (1610, 100)
    p.buttons["focus"] = (1750, 1000)
    return cfg


def picture():
    img = Image.new("RGB", (64, 32), (255, 255, 255))
    img.paste((255, 51, 52), (8, 4, 40, 20))
    img.paste((52, 51, 255), (30, 12, 60, 30))
    img.putpixel((3, 28), (0, 0, 0))
    return img


def make_executor(cfg, job, mouse=None, kb=None, ctl=None, **kw):
    return Executor(job.plan, job.geometry, cfg.profile, cfg.settings, mouse or RecordingMouse(),
                    kb or RecordingKeyboard(), ctl or Controller(), hex_mode=cfg.settings.color_mode == "hex",
                    check_window=lambda: "Rust", **kw)


def inside(p, rect):
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def test_full_run_clicks_only_canvas_and_controls():
    cfg = make_cfg()
    job = build_job(picture(), cfg)
    mouse, kb = RecordingMouse(), RecordingKeyboard()
    res = make_executor(cfg, job, mouse, kb).run()
    assert res.status == "done" and res.next_index == len(job.plan.strokes)
    downs = [e for e in mouse.events if e[0] == "down"]
    ups = [e for e in mouse.events if e[0] == "up"]
    assert len(downs) == len(ups) and not mouse.pressed
    controls = set(p for p in cfg.profile.swatch_positions() if p)
    controls |= {(1610, 100), (1800, 180), (1750, 1000), (1700, 800)}
    for _, x, y in downs:
        on_slider = y == 150 and 1600 <= x <= 1760
        assert inside((x, y), CANVAS) or (x, y) in controls or on_slider, (x, y)
    assert ("kdown", "s") in kb.events                     # ctrl+s save at the end
    assert ("kdown", "enter") not in kb.events             # Enter opens the chat in Rust
    assert "1" in kb.typed()                               # opacity typed into its text box


def test_stop_releases_mouse_and_resume_finishes(tmp_path):
    cfg = make_cfg()
    job = build_job(picture(), cfg)
    ctl = Controller()

    class StopAfter(RecordingMouse):
        def down(self):
            super().down()
            if sum(1 for e in self.events if e[0] == "down") == 12:
                ctl.stop()

    mouse = StopAfter()
    prog = tmp_path / "progress.json"
    res = make_executor(cfg, job, mouse, ctl=ctl, progress_path=prog).run()
    assert res.status == "stopped" and 0 < res.next_index < len(job.plan.strokes)
    assert not mouse.pressed and mouse.events[-1][0] == "up"
    saved = Progress.load(prog)
    assert saved.next_index == res.next_index and saved.plan.strokes == job.plan.strokes
    res2 = make_executor(cfg, job).run(start=saved.next_index)
    assert res2.status == "done"


def test_mouse_moved_by_user_pauses_and_redoes_stroke():
    cfg = make_cfg()
    job = build_job(picture(), cfg)
    ctl = Controller()
    paused = threading.Event()

    class Grabbed(RecordingMouse):
        moves = 0

        def position(self):
            Grabbed.moves += 1
            if Grabbed.moves == 30:
                return self.pos[0] + 100, self.pos[1]
            return self.pos

    events = []

    def on_event(kind, data):
        events.append(kind)
        if kind == "paused":
            paused.set()

    ex = make_executor(cfg, job, Grabbed(), ctl=ctl, on_event=on_event)
    t = threading.Thread(target=lambda: events.append(ex.run().status))
    t.start()
    assert paused.wait(5)
    assert ctl.pause_reason == "mouse moved"
    ctl.resume()
    t.join(10)
    assert "resumed" in events and events[-1] == "done"


def test_hex_mode_types_colours():
    cfg = make_cfg("hex")
    job = build_job(picture(), cfg)
    kb = RecordingKeyboard()
    make_executor(cfg, job, kb=kb).run()
    typed = kb.typed()
    used = {int(c) for c in np.unique(job.prepared.indices)}
    for idx in used:
        r, g, b = job.plan.palette[idx]
        assert f"{r:02x}{g:02x}{b:02x}" in typed


def test_verify_repaints_wrong_cells():
    cfg = make_cfg()
    job = build_job(picture(), cfg)
    target = job.prepared.indices
    pal = np.asarray(job.plan.palette, dtype=np.uint8)
    state = {"canvas": target.copy()}
    state["canvas"][5, 5] = (target[5, 5] + 1) % len(pal)       # one wrong cell on "screen"
    fixes = []

    def grab(rect):
        img = Image.fromarray(pal[state["canvas"]])
        return np.asarray(img.resize((128, 64), Image.Resampling.NEAREST))

    def make(plan):
        if plan is not job.plan:
            fixes.append(plan)
            state["canvas"] = target.copy()                      # the fix "lands"
        return make_executor(cfg, job) if plan is job.plan else Executor(
            plan, job.geometry, cfg.profile, cfg.settings, RecordingMouse(), RecordingKeyboard(),
            check_window=lambda: "Rust")

    out = verify_and_fix(make, target, job.plan, grab, passes=3, tolerance=0, max_de=5)
    assert out == "ok"
    assert len(fixes) == 1 and len(fixes[0].strokes) == 1
    assert fixes[0].strokes[0].points == ((5.5, 5.5),)


def test_shape_mode_switches_opacity_and_clicks_once_per_shape():
    cfg = make_cfg()
    s = cfg.settings
    s.algorithm, s.shape_count, s.shape_work_size = "shapes", 120, 32
    s.shape_sizes, s.shape_alphas = "2,4,8", "0.25,0.5,1.0"
    job = build_job(picture(), cfg)
    mouse, kb = RecordingMouse(), RecordingKeyboard()
    res = make_executor(cfg, job, mouse, kb).run()
    assert res.status == "done"
    canvas_downs = [e for e in mouse.events if e[0] == "down" and inside(e[1:], CANVAS)]
    assert len(canvas_downs) == len(job.plan.strokes)
    typed = kb.typed()
    used_alphas = {st.alpha for st in job.plan.strokes}
    for a in used_alphas:
        txt = f"{a:.0f}" if abs(a - round(a)) < 1e-6 else f"{a:.2f}"
        assert txt in typed


def test_frame_timing():
    cfg = make_cfg()
    s = cfg.settings
    s.game_fps, s.frames_per_action, s.speed = 120, 1, 1.0
    t = s.timing()
    assert abs(t.action_delay - 1 / 120) < 1e-9 and t.click_hold == t.move_delay == t.action_delay
    s.speed, s.frames_per_action = 3.0, 2.0          # 2/3 frame would be too short: clamped to 1 frame
    assert abs(s.timing().action_delay - 1 / 120) < 1e-9
    s.speed = 1.0
    s.game_fps = 0
    s.action_delay_ms = 25
    assert abs(s.timing().action_delay - 0.025) < 1e-9


def test_measure_size_scale_on_fake_screen():
    from signbrush.executor import measure_size_scale
    from signbrush.planner import Plan
    from signbrush.shapes import make_disc

    cfg = make_cfg()
    prof = cfg.profile
    prof.controls["size"].slider_min = prof.controls["size"].slider_max = None
    prof.controls["size"].textbox = (1700, 150)
    prof.controls["size"].range = (1, 32)
    screen = np.full((400, 2000, 3), 168, dtype=np.uint8)
    true_scale = 1.5                                  # texture px per size unit
    tex_w = 64                                        # CANVAS is 128 px wide -> 2 screen px per texture px
    state = {"size": 1.0, "color": (0, 0, 0)}

    class FakeGame(RecordingMouse):
        def down(self):
            super().down()
            x, y = self.pos
            if inside((x, y), CANVAS):
                d = make_disc(state["size"] * true_scale * 2)
                screen[y - d.r:y + d.r + 1, x - d.r:x + d.r + 1][d.mask] = state["color"]

    plan = Plan(1, 1, prof.palette_rgb(), {"fine": 1.0})
    ex = Executor(plan, None, prof, cfg.settings, FakeGame(), RecordingKeyboard(),
                  check_window=lambda: "Rust")
    orig_set, orig_col = ex.set_control, ex.select_color

    def set_control(name, value):
        if name == "size":
            state["size"] = value
        return orig_set(name, value)

    def select_color(idx):
        state["color"] = plan.palette[idx]
        return orig_col(idx)

    ex.set_control, ex.select_color = set_control, select_color

    def grab(rect):
        x0, y0, x1, y1 = rect
        return screen[y0:y1 + 1, x0:x1 + 1].copy()

    scale = measure_size_scale(ex, grab, tex_w)
    assert abs(scale - true_scale) / true_scale < 0.15


def test_hybrid_switches_brush_tip_buttons():
    cfg = make_cfg()
    s = cfg.settings
    s.algorithm, s.hybrid_shapes, s.shape_sizes, s.shape_alphas = "hybrid", 60, "2,4,8", "0.25,0.5,1.0"
    cfg.profile.buttons["brush_circle"] = (1640, 100)
    job = build_job(picture(), cfg)
    mouse = RecordingMouse()
    assert make_executor(cfg, job, mouse).run().status == "done"
    downs = [(x, y) for e, x, y in mouse.events if e == "down"]
    i_circle = downs.index((1640, 100))
    i_square = downs.index((1610, 100))
    assert i_circle < i_square                 # strokes (round) first, square touch-up after


def test_compare_expected_flags_blank_gaps():
    from signbrush.verify import compare_expected
    expected = np.full((4, 6, 3), 255.0)                  # should be white everywhere
    shot = np.full((40, 60, 3), 255, dtype=np.uint8)
    shot[10:20, 20:30] = (217, 217, 217)                  # unpainted light-grey canvas shows through
    cmp = compare_expected(shot, expected, max_de=10)
    assert cmp.wrong == 1 and cmp.mismatch[1, 2]


def test_measure_falls_back_to_a_line_when_clicks_are_ignored():
    from signbrush.executor import measure_size_scale
    from signbrush.planner import Plan

    cfg = make_cfg()
    prof = cfg.profile
    prof.controls["size"].slider_min = prof.controls["size"].slider_max = None
    prof.controls["size"].textbox = (1700, 150)
    prof.controls["size"].range = (1, 100)
    screen = np.full((400, 2000, 3), 168, dtype=np.uint8)
    true_scale, state = 1.5, {"size": 1.0, "color": (0, 0, 0)}

    class MovesOnly(RecordingMouse):            # paints only while dragging, never on a bare click
        def move(self, x, y):
            if self.pressed and inside((x, y), CANVAS) and inside(self.pos, CANVAS):
                r = int(round(state["size"] * true_scale * 2 / 2))
                (ax, ay), (bx, by) = self.pos, (x, y)
                for t in np.linspace(0, 1, max(abs(bx - ax), abs(by - ay)) + 1):
                    px, py = int(round(ax + (bx - ax) * t)), int(round(ay + (by - ay) * t))
                    screen[py - r:py + r, px - r:px + r] = state["color"]
            super().move(x, y)

    plan = Plan(1, 1, prof.palette_rgb(), {"fine": 1.0})
    ex = Executor(plan, None, prof, cfg.settings, MovesOnly(), RecordingKeyboard(), check_window=lambda: "Rust")
    orig_set, orig_col = ex.set_control, ex.select_color
    ex.set_control = lambda n, v: (state.__setitem__("size", v) if n == "size" else None) or orig_set(n, v)
    ex.select_color = lambda i: state.__setitem__("color", plan.palette[i]) or orig_col(i)
    grab = lambda r: screen[r[1]:r[3] + 1, r[0]:r[2] + 1].copy()
    steps = []
    scale = measure_size_scale(ex, grab, 64, on_event=lambda k, d: steps.append((k, d)))
    assert abs(scale - true_scale) / true_scale < 0.2
    assert any(k == "measure" and d["how"] == "линия" for k, d in steps)


def test_verify_tolerates_a_uniform_screen_tint():
    from signbrush.verify import compare_expected
    rng = np.random.default_rng(3)
    expected = rng.integers(30, 230, size=(20, 30, 3)).astype(float)
    shot_cells = np.clip(expected - 14, 0, 255)            # the editor shows everything ~14 darker
    shot_cells[4, 7] = (255, 0, 255)                       # one genuinely wrong cell
    shot = np.repeat(np.repeat(shot_cells, 6, axis=0), 6, axis=1).astype(np.uint8)
    raw = compare_expected(shot, expected, max_de=5, fit_colors=False)
    fitted = compare_expected(shot, expected, max_de=5)
    assert raw.wrong > 300                                   # without the fit almost everything "fails"
    assert fitted.wrong == 1 and fitted.mismatch[4, 7]
