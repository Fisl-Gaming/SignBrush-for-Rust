"""Speed test against a fake game that samples the mouse once per frame."""

import time

import numpy as np

from signbrush.config import load_default
from signbrush.executor import Executor, RecordingKeyboard, SpeedResult, recommend_frames, speed_test
from signbrush.planner import Plan
from signbrush.winput import RecordingMouse

CANVAS = (100, 100, 699, 499)
FRAME = 0.02                                 # the fake game runs at 50 FPS


class FrameSampledGame(RecordingMouse):
    """Records timestamped input; ``render`` replays it the way a game loop sees it:
    once per frame it reads the cursor position and the button state, and while the
    button is held it draws a line from the previous frame's position."""

    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.log = [(time.perf_counter(), 0, 0, False)]
        self.rendered_until = self.log[0][0]
        self.prev = None

    def move(self, x, y):
        super().move(x, y)
        self.log.append((time.perf_counter(), self.pos[0], self.pos[1], self.pressed))

    def down(self):
        super().down()
        self.log.append((time.perf_counter(), self.pos[0], self.pos[1], True))

    def up(self):
        super().up()
        self.log.append((time.perf_counter(), self.pos[0], self.pos[1], False))

    def _line(self, a, b):
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
        for t in np.linspace(0, 1, n):
            x, y = int(round(a[0] + (b[0] - a[0]) * t)), int(round(a[1] + (b[1] - a[1]) * t))
            self.screen[y - 1:y + 2, x - 1:x + 2] = 0

    def render(self):
        now = time.perf_counter()
        t = self.rendered_until + FRAME
        i = 0
        while t <= now:
            while i + 1 < len(self.log) and self.log[i + 1][0] <= t:
                i += 1
            _, x, y, pressed = self.log[i]
            if pressed:
                self._line(self.prev or (x, y), (x, y))
                self.prev = (x, y)
            else:
                self.prev = None
            self.rendered_until = t
            t += FRAME


def test_speed_test_finds_the_frame_limit():
    cfg = load_default()
    prof = cfg.profile
    prof.canvas = CANVAS
    prof.buttons["focus"] = (900, 50)
    prof.buttons["hex_field"] = (900, 100)
    prof.controls["size"].textbox = (900, 150)
    cfg.settings.game_fps = 1 / FRAME
    screen = np.full((600, 1000, 3), 255, dtype=np.uint8)
    game = FrameSampledGame(screen)

    def grab(rect):
        game.render()
        x0, y0, x1, y1 = rect
        return screen[y0:y1 + 1, x0:x1 + 1].copy()

    plan = Plan(1, 1, [(0, 0, 0), (255, 255, 255)], {"fine": 1.0})
    ex = Executor(plan, None, prof, cfg.settings, game, RecordingKeyboard(),
                  color_mode="hex", check_window=lambda: "Rust")
    results = speed_test(ex, grab, frames=[3.0, 2.0, 0.25, 0.0], fps=1 / FRAME,
                         brush_value=2, brush_px=3)
    by = {r.frames: r for r in results}
    assert by[3.0].passed and by[2.0].passed           # waits longer than a frame: nothing lost
    assert not by[0.0].passed                          # no waits: corners cut / clicks lost
    assert not by[0.25].passed
    frames, minimum = recommend_frames(results)
    assert frames >= 2.0 and minimum <= 1.0


def test_recommend_frames_needs_all_slower_waits_to_pass():
    r = lambda f, ok: SpeedResult(f, f / 60, 5 if ok else 3, 5, 5, 5)
    assert recommend_frames([r(2, True), r(1, True), r(0.5, False), r(0, False)]) == (1.5, 1.0)
    assert recommend_frames([r(2, True), r(1, False), r(0.5, True)]) == (3.0, 1.0)   # 0.5 alone is a fluke
    assert recommend_frames([r(1, False), r(0.5, False)]) is None
    assert recommend_frames([r(1, True), r(0.25, True)]) == (0.38, 0.38)


def _speed_setup(gap_frames):
    cfg = load_default()
    prof = cfg.profile
    prof.canvas = CANVAS
    prof.buttons["focus"] = (900, 50)
    prof.buttons["hex_field"] = (900, 100)
    prof.controls["size"].textbox = (900, 150)
    cfg.settings.game_fps = 1 / FRAME
    cfg.settings.gap_frames = gap_frames
    screen = np.full((600, 1000, 3), 255, dtype=np.uint8)
    game = FrameSampledGame(screen)

    def grab(rect):
        game.render()
        x0, y0, x1, y1 = rect
        return screen[y0:y1 + 1, x0:x1 + 1].copy()

    plan = Plan(1, 1, [(0, 0, 0), (255, 255, 255)], {"fine": 1.0})
    ex = Executor(plan, None, prof, cfg.settings, game, RecordingKeyboard(),
                  color_mode="hex", check_window=lambda: "Rust")
    return ex, grab


def test_release_gap_prevents_tails_between_clicks():
    from signbrush.planner import Timing

    def tails_with(gap):
        ex, grab = _speed_setup(gap_frames=0)
        # clicks long enough to be seen, but almost no time between release and the next press
        ex.timing = Timing(action_delay=0.001, move_delay=0.001, click_hold=3 * FRAME, release_gap=gap)
        before = grab((100, 100, 699, 499)).copy()
        pts = [(150 + 60 * i, 300) for i in range(6)]
        for p in pts:
            ex.click(p)
        time.sleep(3 * FRAME)
        after = grab((100, 100, 699, 499))
        mask = np.abs(after.astype(int) - before.astype(int)).sum(axis=2) > 60
        return sum(bool(mask[300 - 100, (a[0] + b[0]) // 2 - 100]) for a, b in zip(pts, pts[1:]))

    assert tails_with(0.0) > 0                 # the game misses the release: dots get joined
    assert tails_with(3 * FRAME) == 0          # enforced gap: every release is seen
