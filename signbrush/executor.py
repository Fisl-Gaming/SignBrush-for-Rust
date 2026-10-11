"""Executor: replays a stroke plan in the game's sign editor with mouse/keyboard input.

Safety
------
* Every input action goes through ``_checkpoint()``: the stop key aborts at
  once (the mouse button is released first), pause releases the button and
  waits, the current stroke is redone after resuming.
* If the cursor is not where we put it (the user grabbed the mouse) or the
  foreground window is not the game, painting pauses by itself.
* Waits are ``Event.wait`` slices, so the stop key never waits for a sleep.
* Only clicks inside the calibrated canvas and on calibrated controls.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np

from .config import Profile, Settings
from .pipeline import Geometry
from .planner import BrushSpec, Plan, Stroke, plan_fixes
from .winput import MouseBackend, foreground_title
from .i18n import tr


class Stopped(Exception):
    """The user pressed the stop key."""


class _Interrupted(Exception):
    """Pause requested in the middle of a stroke: redo it after resuming."""


# ---------------------------------------------------------------- keyboard backends

class KeyboardBackend(Protocol):
    def down(self, key: str) -> None: ...
    def up(self, key: str) -> None: ...


class WinKeyboard:
    """Scan-code key events through pydirectinput (what Unity input fields expect)."""

    def __init__(self) -> None:
        import pydirectinput
        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        self._pdi = pydirectinput

    def down(self, key: str) -> None:
        self._pdi.keyDown(key)

    def up(self, key: str) -> None:
        self._pdi.keyUp(key)


class RecordingKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def down(self, key: str) -> None:
        self.events.append(("kdown", key))

    def up(self, key: str) -> None:
        self.events.append(("kup", key))

    def typed(self) -> str:
        return "".join(k for e, k in self.events if e == "kdown" and len(k) == 1)


# ---------------------------------------------------------------- control flags

class Controller:
    """Thread-safe stop / pause flags shared with hotkeys and the GUI."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self.pause_reason = ""

    def stop(self) -> None:
        self.stop_event.set()
        self._resume.set()

    def pause(self, reason: str = "user") -> None:
        self.pause_reason = reason
        self._resume.clear()

    def resume(self) -> None:
        self.pause_reason = ""
        self._resume.set()

    def toggle_pause(self) -> None:
        if self.paused:
            self.resume()
        else:
            self.pause("user")

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def wait_resumed(self) -> None:
        while not self._resume.wait(0.05):
            pass
        if self.stopped:
            raise Stopped()


# ---------------------------------------------------------------- progress file

@dataclass
class Progress:
    plan: Plan
    next_index: int = 0
    canvas: tuple[int, int, int, int] | None = None
    meta: dict = field(default_factory=dict)   # geometry, target, mode... for resuming

    def save(self, path: Path) -> None:
        data = {"fingerprint": self.plan.fingerprint(), "next_index": self.next_index,
                "canvas": list(self.canvas) if self.canvas else None, "meta": self.meta,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "plan": self.plan.to_dict()}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Progress":
        d = json.loads(path.read_text(encoding="utf-8"))
        plan = Plan.from_dict(d["plan"])
        if plan.fingerprint() != d.get("fingerprint"):
            raise ValueError("progress file is corrupted")
        cv = d.get("canvas")
        return cls(plan, int(d.get("next_index", 0)), tuple(cv) if cv else None, d.get("meta", {}))


# ---------------------------------------------------------------- executor

Event = Callable[[str, dict], None]


@dataclass
class RunResult:
    status: str               # done | stopped
    next_index: int
    total: int


@dataclass
class Executor:
    plan: Plan
    geometry: Geometry
    profile: Profile
    settings: Settings
    mouse: MouseBackend
    keyboard: KeyboardBackend
    ctl: Controller = field(default_factory=Controller)
    on_event: Event = lambda kind, data: None
    progress_path: Path | None = None
    progress_meta: dict = field(default_factory=dict)
    hex_mode: bool = False          # legacy flag, same as color_mode="hex"
    color_mode: str = ""            # hex | picker | palette
    check_window: Callable[[], str] = foreground_title

    def __post_init__(self) -> None:
        if not self.profile.canvas:
            raise ValueError("canvas is not calibrated")
        self.canvas = self.profile.canvas
        self.timing = self.settings.timing()
        self._expected: tuple[int, int] | None = None
        self._pressed = False
        self._keys_down: list[str] = []
        self._color: int | None = None
        self._brush: str | None = None
        self._alpha: float | None = None
        self._tip: str | None = None
        self._last_up: float | None = None
        self._since_save = 0
        self._last_progress_write = 0.0
        self._swatches = self.profile.swatch_positions()
        if not self.color_mode:
            self.color_mode = "hex" if self.hex_mode else "palette"
        self._hue_pos: tuple[int, int] | None = None
        if not self.color_mode:
            self.color_mode = "hex" if self.hex_mode else "palette"
        self._hue_pos: tuple[int, int] | None = None

    # -- low level ---------------------------------------------------------
    def _release_all(self) -> None:
        for k in reversed(self._keys_down):
            try:
                self.keyboard.up(k)
            except Exception:
                pass
        self._keys_down.clear()
        if self._pressed:
            try:
                self.mouse.up()
            finally:
                self._pressed = False

    def _checkpoint(self) -> None:
        if self.ctl.stopped:
            self._release_all()
            raise Stopped()
        guard = self.settings.mouse_guard_px
        if guard and self._expected is not None:
            x, y = self.mouse.position()
            if math.dist((x, y), self._expected) > guard:
                self.ctl.pause("mouse moved")
        title = self.settings.window_title
        if title and title.lower() not in (self.check_window() or "").lower():
            self.ctl.pause(f"window '{title}' is not active")
        if self.ctl.paused:
            self._release_all()
            raise _Interrupted()

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if seconds < 0.05:
            # Event.wait is rounded to the ~15.6 ms Windows timer tick; time.sleep uses a
            # high-resolution timer (Python 3.11+), so frame-sized waits stay frame-sized
            time.sleep(seconds)
            if self.ctl.stopped:
                self._release_all()
                raise Stopped()
        elif self.ctl.stop_event.wait(seconds):
            self._release_all()
            raise Stopped()

    def _move(self, x: int, y: int) -> None:
        self._checkpoint()
        self.mouse.move(x, y)
        self._expected = (int(x), int(y))

    def _down(self) -> None:
        self._checkpoint()
        gap = getattr(self.timing, "release_gap", 0.0)
        if gap and self._last_up is not None:
            # the game must see the button released for a few frames, otherwise it joins
            # the previous stroke to this one with a straight "tail" line
            rest = gap - (time.perf_counter() - self._last_up)
            if rest > 0:
                self._sleep(rest)
                self._checkpoint()
        self.mouse.down()
        self._pressed = True

    def _up(self) -> None:
        self.mouse.up()
        self._pressed = False
        self._last_up = time.perf_counter()

    def _key_down(self, key: str) -> None:
        self._checkpoint()
        self.keyboard.down(key)
        self._keys_down.append(key)

    def _key_up(self, key: str) -> None:
        self.keyboard.up(key)
        if key in self._keys_down:
            self._keys_down.remove(key)

    def _press(self, *keys: str) -> None:
        """Key chord, e.g. _press('ctrl', 'a')."""
        for k in keys:
            self._key_down(k)
            self._sleep(0.01)
        for k in reversed(keys):
            self._key_up(k)
        self._sleep(self.timing.action_delay)

    def _type(self, text: str) -> None:
        for ch in text:
            self._press(ch)

    def click(self, pos: tuple[int, int], hold: float | None = None) -> None:
        self._move(*pos)
        self._sleep(self.timing.move_delay)
        self._down()
        self._sleep(self.timing.click_hold if hold is None else hold)
        self._up()
        self._sleep(self.timing.action_delay)

    # -- editor controls -------------------------------------------------------
    def _commit_field(self) -> None:
        """Apply a typed value. Enter would open the chat in Rust, so by default the
        input field is deselected by clicking a neutral spot of the panel."""
        mode = self.settings.field_commit
        focus = self.profile.buttons.get("focus")
        if mode == "enter":
            self._press("enter")
        elif mode == "tab":
            self._press("tab")
        elif focus:
            self.click(focus)
        else:
            raise ValueError("focus point is not calibrated (needed to apply typed values)")

    def set_control(self, name: str, value: float) -> bool:
        ctl = self.profile.controls.get(name)
        if not ctl or not ctl.usable:
            return False
        if ctl.textbox:
            self.click(ctl.textbox)
            self._press("ctrl", "a")
            txt = f"{value:.0f}" if abs(value - round(value)) < 1e-6 else f"{value:.2f}"
            self._type(txt)
            self._commit_field()
        else:
            x, y = ctl.slider_point(value)
            self._move(x, y)
            self._sleep(self.timing.move_delay)
            self._down()                         # press + tiny wiggle makes Unity sliders jump here
            self._sleep(self.timing.action_delay)
            self._move(x + 1, y)
            self._move(x, y)
            self._sleep(self.timing.action_delay)
            self._up()
        self._sleep(self.timing.brush_switch)
        return True

    def select_color(self, idx: int) -> None:
        if self.color_mode == "picker":
            self._pick(self.plan.palette[idx])
        elif self.color_mode == "hex":
            field_pos = self.profile.buttons.get("hex_field")
            if not field_pos:
                raise ValueError("hex field is not calibrated")
            r, g, b = self.plan.palette[idx]
            self.click(field_pos)
            self._press("ctrl", "a")
            self._type(f"{r:02x}{g:02x}{b:02x}")
            self._commit_field()
        else:
            pos = self._swatches[idx] if idx < len(self._swatches) else None
            if pos is None:
                raise ValueError(f"palette colour {idx} has no calibrated position")
            self.click(pos)
        self._sleep(self.timing.color_switch)
        self._color = idx
        self.on_event("color", {"index": idx, "rgb": self.plan.palette[idx]})

    def select_tip(self, tip: str) -> None:
        btn = self.profile.buttons.get(f"brush_{tip}")
        if btn and tip != self._tip:
            self.click(btn)
        self._tip = tip

    def picker_points(self, rgb) -> tuple[tuple[int, int] | None, tuple[int, int]]:
        """Screen points for (hue bar, SV square) that produce ``rgb`` in the colour picker."""
        import colorsys

        if not (self.profile.picker_sv and self.profile.picker_hue):
            raise ValueError("colour picker is not calibrated")
        h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        x0, y0, x1, y1 = self.profile.picker_sv
        sv = (round(x0 + sat * (x1 - x0)), round(y0 + (1 - val) * (y1 - y0)))
        if sat < 0.02 or val < 0.02:
            return None, sv                      # grey / black: hue does not matter
        hue = h * 360
        lut = self.profile.picker_hue_lut
        if lut:
            t = min(lut, key=lambda e: min(abs(e[1] - hue), 360 - abs(e[1] - hue)))[0]
        else:                                    # red at the top, hue decreasing downwards
            t = 1 - h
        (ax, ay), (bx, by) = self.profile.picker_hue
        return (round(ax + (bx - ax) * t), round(ay + (by - ay) * t)), sv

    def _pick(self, rgb) -> None:
        hue_pt, sv_pt = self.picker_points(rgb)
        if hue_pt is not None and hue_pt != self._hue_pos:
            self.click(hue_pt)
            self._hue_pos = hue_pt
        self.click(sv_pt)

    def picker_points(self, rgb) -> tuple[tuple[int, int] | None, tuple[int, int]]:
        """Screen points for (hue bar, SV square) that produce ``rgb`` in the colour picker."""
        import colorsys

        if not (self.profile.picker_sv and self.profile.picker_hue):
            raise ValueError("colour picker is not calibrated")
        h, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        x0, y0, x1, y1 = self.profile.picker_sv
        sv = (round(x0 + sat * (x1 - x0)), round(y0 + (1 - val) * (y1 - y0)))
        if sat < 0.02 or val < 0.02:
            return None, sv                      # grey / black: hue does not matter
        hue = h * 360
        lut = self.profile.picker_hue_lut
        if lut:
            t = min(lut, key=lambda e: min(abs(e[1] - hue), 360 - abs(e[1] - hue)))[0]
        else:                                    # red at the top, hue decreasing downwards
            t = 1 - h
        (ax, ay), (bx, by) = self.profile.picker_hue
        return (round(ax + (bx - ax) * t), round(ay + (by - ay) * t)), sv

    def _pick(self, rgb) -> None:
        hue_pt, sv_pt = self.picker_points(rgb)
        if hue_pt is not None and hue_pt != self._hue_pos:
            self.click(hue_pt)
            self._hue_pos = hue_pt
        self.click(sv_pt)

    def select_brush(self, name: str) -> None:
        tip = self.plan.tip(name)
        self.select_tip(tip)
        spec = BrushSpec(name, self.plan.brushes[name])
        tex = self.geometry.brush_tex(spec)
        if tip == "square":     # opaque cell strokes: a bit bigger than the cell so no gaps remain
            tex *= max(1.0, self.settings.brush_cover)
        size = self.profile.size_value(tex)
        self.set_control("size", size)
        self._brush = name

    def select_alpha(self, alpha: float) -> None:
        """Opacity as a 0..1 fraction, mapped onto the calibrated control range."""
        ctl = self.profile.controls.get("opacity")
        if ctl and ctl.usable:
            lo, hi = ctl.range
            self.set_control("opacity", lo + alpha * (hi - lo))
        elif alpha < 0.999:
            raise ValueError("opacity control is not calibrated (needed for shape mode)")
        self._alpha = alpha

    def save(self) -> None:
        method = self.settings.save_method
        if method == "off":
            return
        btn = self.profile.buttons.get("save")
        if method == "button" and btn:
            self.click(btn)
        else:
            self._press("ctrl", "s")
        self._since_save = 0
        self.on_event("saved", {})

    def prepare(self) -> None:
        """Focus the game and set the brush up before the first stroke."""
        focus = self.profile.buttons.get("focus")
        if focus:
            self.click(focus)
        self._tip = None
        if self.profile.spacing is not None:
            self.set_control("spacing", self.profile.spacing)
        self._color = self._brush = self._alpha = None   # the run loop sets them per stroke

    # -- strokes ---------------------------------------------------------------
    def screen_points(self, s: Stroke) -> list[tuple[int, int]]:
        return [self.geometry.to_screen(self.canvas, x, y) for x, y in s.points]

    def draw_stroke(self, s: Stroke) -> None:
        pts = self.screen_points(s)
        if len(pts) == 1:
            self.click(pts[0])
            return
        t = self.timing
        self._move(*pts[0])
        self._sleep(t.move_delay)
        self._down()
        self._sleep(t.action_delay)
        if self.settings.line_mode == "jump":
            # the game samples the cursor once per frame and draws the segment in between
            for p in pts[1:]:
                self._move(*p)
                self._sleep(t.draw_step_delay)
        elif self.settings.line_mode == "shift":
            for p in pts[1:]:
                self._key_down("shift")
                self._sleep(0.01)
                self._move(*p)
                self._sleep(t.draw_step_delay * 4)
                self._key_up("shift")
        else:
            for a, b in zip(pts, pts[1:]):
                n = max(1, int(math.ceil(math.dist(a, b) / max(t.draw_step_px, 1.0))))
                for k in range(1, n + 1):
                    self._move(round(a[0] + (b[0] - a[0]) * k / n), round(a[1] + (b[1] - a[1]) * k / n))
                    self._sleep(t.draw_step_delay)
        if self.settings.line_mode != "jump":     # in jump mode the last vertex already waited a frame
            self._sleep(t.action_delay)
        self._up()
        self._sleep(t.action_delay)

    def _write_progress(self, i: int, force: bool = False) -> None:
        if not self.progress_path:
            return
        now = time.monotonic()
        if force or now - self._last_progress_write > 2.0:
            Progress(self.plan, i, self.canvas, self.progress_meta).save(self.progress_path)
            self._last_progress_write = now

    def run(self, start: int = 0, prepare: bool = True) -> RunResult:
        strokes = self.plan.strokes
        total = len(strokes)
        i = start
        need_prepare = prepare
        try:
            while i < total:
                try:
                    if need_prepare:
                        self.prepare()
                        need_prepare = False
                    s = strokes[i]
                    if s.brush != self._brush:
                        self.select_brush(s.brush)
                    if self._alpha is None or abs(s.alpha - self._alpha) > 1e-6:
                        self.select_alpha(s.alpha)
                    if s.color != self._color:
                        self.select_color(s.color)
                    self.draw_stroke(s)
                except _Interrupted:
                    self.on_event("paused", {"reason": self.ctl.pause_reason, "index": i})
                    self._write_progress(i, force=True)
                    self.ctl.wait_resumed()
                    self._expected = None          # the user moved the mouse on purpose
                    self._color = self._brush = self._alpha = self._tip = self._hue_pos = None
                    need_prepare = True
                    self.on_event("resumed", {"index": i})
                    continue
                i += 1
                self._since_save += 1
                self.on_event("progress", {"done": i, "total": total})
                self._write_progress(i)
                if self.settings.save_every and self._since_save >= self.settings.save_every:
                    self.save()
            self.save()
            self._write_progress(i, force=True)
            return RunResult("done", i, total)
        except Stopped:
            self._release_all()
            self._write_progress(i, force=True)
            self.on_event("stopped", {"index": i})
            return RunResult("stopped", i, total)
        finally:
            self._release_all()

    # -- verification ------------------------------------------------------------
    def park_mouse(self) -> None:
        """Move the cursor off the canvas so it does not hide pixels in the screenshot."""
        x0, y0, x1, y1 = self.canvas
        self._move(x1 + 40, y0)
        self._sleep(0.3)


def verify_and_fix(make_executor: Callable[[Plan], Executor], fix_indices: np.ndarray, base_plan: Plan,
                   grab: Callable[[tuple[int, int, int, int]], np.ndarray], passes: int,
                   tolerance: float, on_event: Event = lambda k, d: None,
                   max_de: float = 10.0, expected_rgb: np.ndarray | None = None,
                   skip_mask: np.ndarray | None = None) -> str:
    """Screenshot -> compare with the expected colours -> repaint wrong cells.

    ``fix_indices`` - palette index used to repaint each cell; ``expected_rgb`` -
    what the cell should look like (defaults to the palette colour of the index).
    Returns "ok", "stopped" or "incomplete".
    """
    from .verify import compare_expected

    pal = np.asarray(base_plan.palette, dtype=np.float64)
    expected = pal[fix_indices] if expected_rgb is None else np.asarray(expected_rgb, dtype=np.float64)
    brushes = [BrushSpec("fine", base_plan.brushes["fine"])]
    prev_wrong = None
    for n in range(1, passes + 1):
        ex = make_executor(base_plan)
        ex.park_mouse()
        shot = grab(ex.canvas)
        cmp = compare_expected(shot, expected, max_de, skip_mask=skip_mask)
        if skip_mask is not None:           # transparent areas are left alone on purpose
            cmp.mismatch &= ~skip_mask
        on_event("verify", {"pass": n, "wrong": cmp.wrong, "accuracy": cmp.accuracy})
        if 1 - cmp.accuracy <= tolerance:
            return "ok"
        if prev_wrong is not None and cmp.wrong > 0.85 * prev_wrong:
            # repainting did not help: the difference is not something the brush can fix
            on_event("verify_stuck", {"wrong": cmp.wrong})
            return "incomplete"
        prev_wrong = cmp.wrong
        observed = np.where(cmp.mismatch, -1, fix_indices).astype(np.int32)
        fix = plan_fixes(fix_indices, observed, base_plan.palette, brushes, shape="square",
                         skip_mask=skip_mask)
        if not fix.strokes:
            return "ok"
        res = make_executor(fix).run(prepare=False)
        if res.status == "stopped":
            return "stopped"
    return "incomplete"


class MeasureError(RuntimeError):
    """A calibration measurement could not see its own test paint."""


def grab_until_changed(grab: Callable[[tuple[int, int, int, int]], np.ndarray], region, before: np.ndarray,
                       timeout: float = 2.5, poll: float = 0.15) -> tuple[np.ndarray, np.ndarray]:
    """Screenshots until the region differs from ``before`` (the game may update the sign
    texture with a delay), then once more after it settled. Returns (after, changed mask)."""
    t0 = time.monotonic()
    after = grab(region).astype(int)
    changed = np.abs(after - before).sum(axis=2) > 60
    while not changed.any() and time.monotonic() - t0 < timeout:
        time.sleep(poll)
        after = grab(region).astype(int)
        changed = np.abs(after - before).sum(axis=2) > 60
    if changed.any():
        time.sleep(0.25)
        after = grab(region).astype(int)
        changed = np.abs(after - before).sum(axis=2) > 60
    return after, changed


def _dump(debug_dir: Path | None, name: str, *imgs: np.ndarray) -> str:
    if not debug_dir:
        return ""
    from PIL import Image
    debug_dir.mkdir(parents=True, exist_ok=True)
    for i, im in enumerate(imgs):
        Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(debug_dir / f"{name}_{i}.png")
    return str(debug_dir)


def measure_size_scale(ex: Executor, grab: Callable[[tuple[int, int, int, int]], np.ndarray],
                       texture_w: int, values: tuple[float, ...] | None = None,
                       on_event: Event = lambda k, d: None, undo: bool = True,
                       debug_dir: Path | None = None) -> float:
    """Paint test marks in the canvas corner and measure them on screen.

    Returns ``size_scale``: brush diameter in texture px per unit of the size
    control. A dot is tried first; if the game ignores single clicks, a short
    stroke is painted and its thickness measured instead. The marks are undone
    with Ctrl+Z afterwards.
    """
    ctl = ex.profile.controls["size"]
    lo, hi = ctl.range
    values = values or tuple(sorted({float(min(hi, max(lo, v))) for v in (4.0, 12.0)}))
    x0, y0, x1, y1 = ex.canvas
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    span = max(30, int(min(cw, ch) * 0.16))
    note = lambda text: on_event("measure_step", {"text": text})
    ex.prepare()
    ex.select_alpha(1.0)
    ex.select_tip("square")
    pal = np.asarray(ex.plan.palette, dtype=float)
    hold = max(ex.timing.click_hold, 0.06)
    ratios: list[float] = []
    marks = 0
    try:
        for i, v in enumerate(values):
            cx = max(x0 + span, x1 - span - i * 2 * span)
            cy = max(y0 + span, y1 - span)
            region = (max(x0, cx - span), max(y0, cy - span), min(x1, cx + span), min(y1, cy + span))
            ex.set_control("size", float(v))
            ex.park_mouse()
            ex._sleep(0.2)
            before = grab(region).astype(int)
            med = np.median(before.reshape(-1, 3), axis=0)
            k = int(((pal - med) ** 2).sum(axis=1).argmax())      # most contrasting colour
            ex.select_color(k)
            note(tr('размер {0:g}, цвет #{1}: ставлю точку').format(v, ''.join(f'{int(c):02X}' for c in pal[k])))
            ex._move(cx, cy)
            ex._sleep(0.05)
            ex._down()
            ex._sleep(hold)
            ex._up()
            ex._sleep(0.05)
            marks += 1
            ex.park_mouse()
            after, changed = grab_until_changed(grab, region, before)
            how = tr('точка')
            if not changed.any():
                note(tr('точка не появилась — пробую короткую линию (игра может не рисовать одиночные клики)'))
                half = span // 2
                ex._move(cx - half, cy)
                ex._sleep(0.05)
                ex._down()
                ex._sleep(0.05)
                for j in range(1, 9):
                    ex._move(cx - half + j * half // 4, cy)
                    ex._sleep(0.03)
                ex._sleep(0.05)
                ex._up()
                ex._sleep(0.05)
                marks += 1
                ex.park_mouse()
                after, changed = grab_until_changed(grab, region, before)
                how = tr('линия')
            if not changed.any():
                where = _dump(debug_dir, f"measure_{i}", before, after)
                raise MeasureError(
                    tr('Пробная отметка не появилась на холсте.\n\nПроверьте: открыт ли редактор таблички и активно ли окно Rust; совпадает ли рамка холста в калибровке с холстом на экране; применяется ли размер и цвет (поле размера и HEX-поле в калибровке). Если в журнале видно, что значения вводятся, а цвет не меняется — подтверждение ввода кликом может не срабатывать.')
                    + (tr('\n\nСнимки «до/после» сохранены в: {0}').format(where) if where else ""))
            ys, xs = np.nonzero(changed)
            if how == tr('точка'):
                d_screen = ((xs.max() - xs.min() + 1) + (ys.max() - ys.min() + 1)) / 2
            else:                                   # thickness of the line in its middle
                col = changed[:, min(changed.shape[1] - 1, max(0, cx - region[0]))]
                d_screen = float(col.sum()) if col.any() else float(ys.max() - ys.min() + 1)
            d_tex = d_screen * texture_w / cw
            ratios.append(d_tex / float(v))
            on_event("measure", {"value": v, "screen_px": d_screen, "texture_px": d_tex, "how": how})
    finally:
        if undo:   # remove the test marks again (Ctrl+Z in the editor)
            for _ in range(marks):
                ex._press("ctrl", "z")
                ex._sleep(0.15)
    if len(ratios) > 1 and max(ratios) / max(min(ratios), 1e-6) > 1.35:
        note(tr('⚠ размеры не пропорциональны ({0}) — возможно, у ползунка размера нелинейная шкала').format(', '.join(f'{r:.2f}' for r in ratios)))
    return float(np.mean(ratios))


# ---------------------------------------------------------------- speed test

@dataclass
class SpeedResult:
    frames: float            # wait per action, in game frames
    delay: float             # the same in seconds
    corners_ok: int
    corners: int
    dots_ok: int
    dots: int
    tails: int = 0           # lines between separate clicks: the game missed a release

    @property
    def passed(self) -> bool:
        return self.corners_ok == self.corners and self.dots_ok == self.dots and self.tails == 0


def _painted_near(mask: np.ndarray, x: int, y: int, r: int) -> bool:
    h, w = mask.shape
    return bool(mask[max(0, y - r):min(h, y + r + 1), max(0, x - r):min(w, x + r + 1)].any())


def speed_test(ex: Executor, grab: Callable[[tuple[int, int, int, int]], np.ndarray],
               frames: Sequence[float], fps: float, brush_value: float, brush_px: float,
               on_event: Event = lambda k, d: None, undo: bool = True) -> list[SpeedResult]:
    """Find how fast the game accepts mouse input.

    For every wait (in frames) a sharp zig-zag and a row of dots are painted in
    the upper part of the canvas. A wait that is too short makes the game skip
    a vertex (the corner is cut) or a whole click (a dot is missing), which is
    detected on a screenshot.
    """
    x0, y0, x1, y1 = ex.canvas
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    n = len(frames)
    bw = cw * 0.92 / n
    bh = min(ch * 0.3, bw * 1.4)
    m = max(4, int(bw * 0.12))
    r = max(3, int(round(brush_px * 1.2)) + 2)
    ex.prepare()
    ex.select_alpha(1.0)
    ex.select_tip("square")
    ex.set_control("size", float(brush_value))
    pal = np.asarray(ex.plan.palette, dtype=float)
    region = (x0, y0, x1, min(y1, int(y0 + ch * 0.06 + bh + 2 * m)))
    ex.park_mouse()
    before = grab(region).astype(int)
    med = np.median(before.reshape(-1, 3), axis=0)
    ex.select_color(int(((pal - med) ** 2).sum(axis=1).argmax()))
    plans: list[tuple[float, list[tuple[int, int]], list[tuple[int, int]]]] = []
    strokes = 0
    for i, f in enumerate(frames):
        d = max(0.0, f) / fps
        bx = x0 + cw * 0.04 + i * bw
        by = y0 + ch * 0.06
        top, bottom = int(by + m), int(by + bh * 0.62)
        xs = np.linspace(bx + m, bx + bw - m, 7)
        verts = [(int(x), top if k % 2 == 0 else bottom) for k, x in enumerate(xs)]
        dots = [(int(x), int(by + bh * 0.9)) for x in np.linspace(bx + m, bx + bw - m, 5)]
        # zig-zag: every vertex is a sharp corner
        ex._move(*verts[0])
        ex._sleep(d)
        ex._down()
        ex._sleep(d)
        for v in verts[1:]:
            ex._move(*v)
            ex._sleep(d)
        ex._up()
        ex._sleep(d)
        strokes += 1
        for p in dots:                      # single clicks
            ex._move(*p)
            ex._sleep(d)
            ex._down()
            ex._sleep(d)
            ex._up()
            ex._sleep(d)
            strokes += 1
        plans.append((f, verts, dots))
        ex._sleep(0.1)
    ex.park_mouse()
    ex._sleep(0.3)
    after, mask = grab_until_changed(grab, region, before)   # the sign texture may update late
    ox, oy = region[0], region[1]
    results = []
    for f, verts, dots in plans:
        c_ok = sum(_painted_near(mask, x - ox, y - oy, r) for x, y in verts[1:-1])
        d_ok = sum(_painted_near(mask, x - ox, y - oy, r) for x, y in dots)
        # dots are separate clicks: paint half-way between two of them is a tail
        tails = sum(_painted_near(mask, (a[0] + b[0]) // 2 - ox, a[1] - oy, max(1, r // 3))
                    for a, b in zip(dots, dots[1:]))
        res = SpeedResult(f, f / fps, c_ok, len(verts) - 2, d_ok, len(dots), tails)
        results.append(res)
        on_event("speed", {"frames": f, "ms": res.delay * 1000, "corners": f"{c_ok}/{res.corners}",
                           "dots": f"{d_ok}/{res.dots}", "tails": tails, "passed": res.passed})
    if undo:
        for _ in range(strokes):
            ex._press("ctrl", "z")
            ex._sleep(0.03)
    return results


def recommend_frames(results: Sequence[SpeedResult]) -> tuple[float, float] | None:
    """(frames_per_action, min_frames) with a safety margin, or None if nothing passed.

    The fastest wait that passed - and every slower one too - is taken, then
    lengthened by 50 % because the game's FPS drops while it repaints the sign.
    """
    ordered = sorted(results, key=lambda r: r.frames)
    best = None
    for k, r in enumerate(ordered):
        if r.passed and all(o.passed for o in ordered[k:]):
            best = r
            break
    if best is None:
        return None
    frames = max(0.25, best.frames * 1.5) if best.frames > 0 else 0.5
    return round(frames, 2), round(min(frames, 1.0), 2)


def line_test(ex: Executor, grab: Callable[[tuple[int, int, int, int]], np.ndarray],
              brush_value: float, wait: float, on_event: Event = lambda k, d: None,
              undo: bool = True) -> float:
    """Does the game connect a long mouse jump into a solid line?

    Paints one horizontal line across the lower part of the canvas with a single
    jump of the cursor and returns the painted share of its length (1.0 = solid).
    """
    x0, y0, x1, y1 = ex.canvas
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    y = int(y0 + ch * 0.82)
    xa, xb = int(x0 + cw * 0.08), int(x0 + cw * 0.92)
    region = (x0, max(y0, y - 12), x1, min(y1, y + 12))
    ex.select_alpha(1.0)
    ex.select_tip("square")
    ex.set_control("size", float(brush_value))
    pal = np.asarray(ex.plan.palette, dtype=float)
    ex.park_mouse()
    before = grab(region).astype(int)
    med = np.median(before.reshape(-1, 3), axis=0)
    ex.select_color(int(((pal - med) ** 2).sum(axis=1).argmax()))
    ex._move(xa, y)
    ex._sleep(wait)
    ex._down()
    ex._sleep(wait)
    ex._move(xb, y)          # one jump across the whole line
    ex._sleep(wait)
    ex._up()
    ex._sleep(wait)
    ex.park_mouse()
    ex._sleep(0.3)
    after, changed = grab_until_changed(grab, region, before)
    cols = changed.any(axis=0)[xa - region[0] + 3: xb - region[0] - 3]
    coverage = float(cols.mean()) if len(cols) else 0.0
    on_event("line", {"coverage": coverage})
    if undo:
        ex._press("ctrl", "z")
        ex._sleep(0.05)
    return coverage
