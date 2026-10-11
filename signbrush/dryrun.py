"""Dry-run: render a stroke plan to an image / animation without touching the mouse."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from PIL import Image, ImageDraw

from .planner import Plan, Stroke

BLANK = (214, 196, 160)   # stand-in for an unpainted wooden sign


class PlanRenderer:
    """Incrementally draws strokes as round-capped lines at ``scale`` px per cell."""

    def __init__(self, plan: Plan, scale: float = 4.0, blank=BLANK):
        self.plan = plan
        self.scale = float(scale)
        self.image = Image.new("RGB", (max(1, round(plan.cols * scale)), max(1, round(plan.rows * scale))),
                               tuple(blank))
        self._draw = ImageDraw.Draw(self.image)
        self.done = 0

    def _draw_translucent_dot(self, s: Stroke, col) -> None:
        """Semi-transparent round stamp (shape mode): composite a small patch."""
        k = self.scale
        d = max(1.0, self.plan.brushes[s.brush] * k)
        x, y = s.points[0][0] * k, s.points[0][1] * k
        x0, y0 = int(x - d / 2), int(y - d / 2)
        size = int(d) + 2
        patch = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(patch).ellipse((x - d / 2 - x0, y - d / 2 - y0, x + d / 2 - x0, y + d / 2 - y0),
                                      fill=(*col, int(round(s.alpha * 255))))
        base = self.image.crop((x0, y0, x0 + size, y0 + size)).convert("RGBA")
        base.alpha_composite(patch)
        self.image.paste(base.convert("RGB"), (x0, y0))

    def draw_stroke(self, s: Stroke, color=None) -> None:
        k = self.scale
        col = tuple(color or self.plan.palette[s.color])
        if s.alpha < 0.999 and len(s.points) == 1:
            self._draw_translucent_dot(s, col)
            return
        w = self.plan.brushes[s.brush] * k
        r = w / 2
        pts = [(x * k, y * k) for x, y in s.points]
        if self.plan.tip(s.brush) == "square":
            seg = pts if len(pts) > 1 else pts * 2
            for (xa, ya), (xb, yb) in zip(seg, seg[1:]):
                if xa != xb and ya != yb:   # diagonal: stamp along it
                    n = max(1, int(max(abs(xb - xa), abs(yb - ya)) / max(1.0, r)))
                    for i in range(n + 1):
                        x, y = xa + (xb - xa) * i / n, ya + (yb - ya) * i / n
                        self._draw.rectangle((x - r, y - r, x + r - 1, y + r - 1), fill=col)
                else:
                    self._draw.rectangle((min(xa, xb) - r, min(ya, yb) - r,
                                          max(xa, xb) + r - 1, max(ya, yb) + r - 1), fill=col)
            return
        if len(pts) > 1:
            self._draw.line(pts, fill=col, width=max(1, round(w)), joint="curve")
        for x, y in pts:   # round caps / dots
            self._draw.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def step(self, n: int = 1) -> int:
        """Draw the next ``n`` strokes; returns how many were drawn."""
        end = min(len(self.plan.strokes), self.done + n)
        for s in self.plan.strokes[self.done:end]:
            self.draw_stroke(s)
        drawn = end - self.done
        self.done = end
        return drawn

    def finished(self) -> bool:
        return self.done >= len(self.plan.strokes)


def render_plan(plan: Plan, scale: float = 4.0, upto: int | None = None, blank=BLANK) -> Image.Image:
    r = PlanRenderer(plan, scale, blank)
    r.step(len(plan.strokes) if upto is None else upto)
    return r.image


def iter_frames(plan: Plan, frames: int = 60, scale: float = 4.0, blank=BLANK) -> Iterator[Image.Image]:
    r = PlanRenderer(plan, scale, blank)
    total = len(plan.strokes)
    per = max(1, -(-total // max(1, frames)))
    yield r.image.copy()
    while not r.finished():
        r.step(per)
        yield r.image.copy()


def save_gif(plan: Plan, path: str | Path, frames: int = 60, scale: float = 4.0,
             frame_ms: int = 80, hold_ms: int = 1500, blank=BLANK) -> Path:
    imgs = [im.convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
            for im in iter_frames(plan, frames, scale, blank)]
    durations = [frame_ms] * (len(imgs) - 1) + [hold_ms]
    p = Path(path)
    imgs[0].save(p, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
    return p
