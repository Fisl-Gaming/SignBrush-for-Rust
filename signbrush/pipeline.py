"""Glue: image + sign type + profile + settings -> stroke plan.

Two algorithms:

* ``pixels`` - the sign texture is split into cells of ``detail`` texture px,
  every cell gets exactly one palette colour (cell-exact copy).
* ``shapes`` - semi-transparent circles, one click each (see :mod:`shapes`).
* ``hybrid`` - coarse-to-fine: a few thousand translucent strokes lay down
  smooth colour, then a pixel pass repaints only the cells whose colour error
  is still above ``fix_tolerance``.

Screen coordinates are only needed by the executor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .config import Config, Profile, Settings, SignType
from .imaging import (PreparedImage, fit_image, fit_mask, indices_to_image, kmeans_palette, prepare_image,
                      quantize, srgb_to_lab)
from .planner import BrushSpec, Plan, PlanOptions, Stroke, estimate_seconds, plan_strokes
from .shapes import ShapeGenerator, ShapeOptions, render, sort_shapes

FINE, FILL = "fine", "fill"
Progress = Callable[[str, float], None]


@dataclass
class Geometry:
    texture: tuple[int, int]     # sign texture size, px
    cell_tex: int                # texture px per cell
    cols: int
    rows: int

    @classmethod
    def for_sign(cls, sign: SignType, detail: int, max_cells: int = 0) -> "Geometry":
        tw, th = sign.size
        cell = max(1, int(detail))
        while max_cells and (tw // cell) * (th // cell) > max_cells:
            cell += 1
        return cls((tw, th), cell, max(1, tw // cell), max(1, th // cell))

    def brushes(self, fill_size_tex: int) -> list[BrushSpec]:
        out = [BrushSpec(FINE, 1.0)]
        if fill_size_tex and fill_size_tex >= 2 * self.cell_tex:
            out.append(BrushSpec(FILL, fill_size_tex / self.cell_tex))
        return out

    def brush_tex(self, spec: BrushSpec) -> float:
        """Brush size in texture px."""
        return spec.diameter * self.cell_tex

    def to_screen(self, canvas: tuple[int, int, int, int], x: float, y: float) -> tuple[int, int]:
        """Grid units -> absolute screen pixel."""
        x0, y0, x1, y1 = canvas
        w, h = x1 - x0 + 1, y1 - y0 + 1
        tx, ty = x * self.cell_tex, y * self.cell_tex
        sx = x0 + tx / self.texture[0] * w
        sy = y0 + ty / self.texture[1] * h
        return min(x1, max(x0, int(math.floor(sx)))), min(y1, max(y0, int(math.floor(sy))))


@dataclass
class Job:
    plan: Plan
    geometry: Geometry
    sign: SignType
    estimate_s: float
    screen_cell_px: float           # on-screen size of one grid unit (for time estimates)
    preview: Image.Image            # expected result, one px per grid unit
    algorithm: str = "pixels"
    prepared: PreparedImage | None = None   # pixel mode only
    fix_indices: np.ndarray | None = None   # palette index to repaint a wrong cell with (verification)
    expected_rgb: np.ndarray | None = None  # what every cell should look like (verification)
    skip_mask: np.ndarray | None = None     # cells left unpainted (transparent areas), grid resolution

    @property
    def target(self) -> np.ndarray | None:
        return self.fix_indices

    def colors_used(self) -> int:
        return len({s.color for s in self.plan.strokes})


def _screen_cell(prof: Profile, cols: int) -> float:
    if prof.canvas:
        x0, _, x1, _ = prof.canvas
        return (x1 - x0 + 1) / cols
    return 1000 / cols           # rough guess for an uncalibrated preview


def build_job(image: Image.Image | str | Path, cfg: Config, sign: SignType | None = None,
              profile: Profile | None = None, settings: Settings | None = None,
              progress: Progress | None = None, cancel: Callable[[], bool] | None = None) -> Job:
    s = settings or cfg.settings
    prof = profile or cfg.profile
    sign = sign or cfg.sign()
    img = image if isinstance(image, Image.Image) else Image.open(image)
    img.load()
    if s.algorithm == "shapes":
        return _build_shapes(img, s, prof, sign, progress, cancel)
    if s.algorithm == "hybrid":
        return _build_hybrid(img, s, prof, sign, progress, cancel)
    return _build_pixels(img, s, prof, sign)


def _build_pixels(img: Image.Image, s: Settings, prof: Profile, sign: SignType) -> Job:
    geo = Geometry.for_sign(sign, s.detail, s.max_cells)
    specs = geo.brushes(s.fill_size if s.coarse or s.base_fill else 0)
    opts = s.image_options()
    skip = ~fit_mask(img, (geo.cols, geo.rows), opts.fit, opts.alpha_threshold) if s.transparent == "skip" else None
    if skip is not None and not skip.any():
        skip = None
    if s.color_mode in ("hex", "picker"):
        # any colour can be entered: fit a palette to this picture
        fitted = fit_image(img, (geo.cols, geo.rows), opts.fit, opts.background, opts.alpha_threshold)
        visible = np.asarray(fitted)[~skip] if skip is not None else np.asarray(fitted)
        palette = kmeans_palette(visible.reshape(-1, 1, 3), s.max_colors or 48,
                                 extra=[] if skip is not None else [opts.background])
        opts.max_colors = 0
    else:
        palette = prof.palette_rgb()
    prepared = prepare_image(img, (geo.cols, geo.rows), palette, opts)
    plan = plan_strokes(prepared.indices, prepared.palette, specs, s.plan_options(), shape=s.brush_shape,
                        skip_mask=skip)
    cell_px = _screen_cell(prof, geo.cols)
    est = estimate_seconds(plan, s.timing(), cell_px)
    preview = np.asarray(prepared.to_image()).copy()
    if skip is not None:
        preview[skip] = sign.blank
    return Job(plan, geo, sign, est, cell_px, Image.fromarray(preview), "pixels", prepared,
               prepared.indices, np.asarray(prepared.palette, dtype=np.float64)[prepared.indices], skip)


def _build_shapes(img: Image.Image, s: Settings, prof: Profile, sign: SignType,
                  progress: Progress | None, cancel: Callable[[], bool] | None) -> Job:
    tw, th = sign.size
    f = max(1.0, max(tw, th) / max(16, s.shape_work_size))
    ww, wh = max(1, round(tw / f)), max(1, round(th / f))
    opts = s.image_options()
    fitted = fit_image(img, (ww, wh), opts.fit, opts.background, opts.alpha_threshold)
    target = np.asarray(fitted, dtype=np.float64).copy()
    if s.transparent == "skip":
        # leave transparent areas as they are: the "target" there is the bare sign,
        # so any stroke reaching into them only adds error and is avoided
        hidden = ~fit_mask(img, (ww, wh), opts.fit, opts.alpha_threshold)
        target[hidden] = sign.blank
    if s.color_mode in ("hex", "picker"):
        palette = kmeans_palette(target.astype(np.uint8), s.max_colors or 32)
    else:
        palette = prof.palette_rgb()
    pal = np.asarray(palette, dtype=np.float64)
    sizes_tex = s.shape_sizes_list()
    alphas = s.shape_alphas_list()
    sizes_w = [d / f for d in sizes_tex]
    gen = ShapeGenerator(target, pal, sign.blank, sizes_w, alphas, ShapeOptions())
    report = (lambda n, total: progress("shapes", n / max(1, total))) if progress else None
    shapes = gen.run(s.shape_count, report, cancel)
    shapes = sort_shapes(shapes, [d / 2 for d in sizes_w])
    fx, fy = tw / ww, th / wh
    plan = Plan(cols=tw, rows=th, palette=[tuple(int(v) for v in c) for c in palette],
                brushes={f"s{i}": float(d) for i, d in enumerate(sizes_tex)}, shape="circle")
    plan.strokes = [Stroke(sh.color, f"s{sh.size}", (((sh.x + 0.5) * fx, (sh.y + 0.5) * fy),), "shape",
                           alphas[sh.alpha]) for sh in shapes]
    preview = Image.fromarray(render(shapes, (tw, th), pal, sign.blank, sizes_w, alphas, scale=fx))
    geo = Geometry((tw, th), 1, tw, th)
    cell_px = _screen_cell(prof, tw)
    est = estimate_seconds(plan, s.timing(), cell_px)
    return Job(plan, geo, sign, est, cell_px, preview, "shapes")


def _build_hybrid(img: Image.Image, s: Settings, prof: Profile, sign: SignType,
                  progress: Progress | None, cancel: Callable[[], bool] | None) -> Job:
    geo = Geometry.for_sign(sign, s.detail, s.max_cells)
    opts = s.image_options()
    fitted = fit_image(img, (geo.cols, geo.rows), opts.fit, opts.background, opts.alpha_threshold)
    rgb = np.asarray(fitted, dtype=np.float64).copy()
    skip = ~fit_mask(img, (geo.cols, geo.rows), opts.fit, opts.alpha_threshold) if s.transparent == "skip" else None
    if skip is not None and not skip.any():
        skip = None
    if skip is not None:
        rgb[skip] = sign.blank            # strokes into transparent areas only add error -> avoided
    if s.color_mode in ("hex", "picker"):
        visible = rgb[~skip] if skip is not None else rgb.reshape(-1, 3)
        palette = kmeans_palette(visible.reshape(-1, 1, 3).astype(np.uint8), s.max_colors or 48)
    else:
        palette = prof.palette_rgb()
    pal = np.asarray(palette, dtype=np.float64)

    # 1. coarse: translucent strokes on the drawing grid itself
    sizes_tex = s.shape_sizes_list()
    alphas = s.shape_alphas_list()
    sizes_cells = [d / geo.cell_tex for d in sizes_tex]
    gen = ShapeGenerator(rgb, pal, sign.blank, sizes_cells, alphas, ShapeOptions())
    report = (lambda n, total: progress("shapes", n / max(1, total))) if progress else None
    shapes = sort_shapes(gen.run(s.hybrid_shapes, report, cancel), [d / 2 for d in sizes_cells])

    # 2. fine: repaint only the cells that are still too far from the target
    base = np.clip(gen.C, 0, 255)
    T, P = srgb_to_lab(rgb), srgb_to_lab(pal)
    k = quantize(rgb, pal).astype(np.int32)
    de_cur = np.sqrt(((srgb_to_lab(base) - T) ** 2).sum(axis=2))
    de_new = np.sqrt(((P[k] - T) ** 2).sum(axis=2))
    need = (de_cur > s.fix_tolerance) & (de_new < de_cur - 1.0)
    if skip is not None:
        need &= ~skip
    fix = plan_strokes(k, palette, [BrushSpec(FINE, 1.0)],
                       PlanOptions(base_fill=False, coarse=False, max_bridge=s.max_bridge),
                       canvas=np.where(need, -1, k), phase_fine="fix", shape="square", skip_mask=skip)

    names = {i: f"s{i}" for i in range(len(sizes_cells))}
    plan = Plan(cols=geo.cols, rows=geo.rows, palette=[tuple(int(v) for v in c) for c in palette],
                brushes={**{names[i]: float(d) for i, d in enumerate(sizes_cells)}, FINE: 1.0},
                shape="square", tips={n: "circle" for n in names.values()})
    plan.strokes = [Stroke(sh.color, names[sh.size], ((sh.x + 0.5, sh.y + 0.5),), "shape", alphas[sh.alpha])
                    for sh in shapes] + fix.strokes
    final = np.where(need[..., None], pal[k], base)
    preview = Image.fromarray(np.clip(final, 0, 255).astype(np.uint8))
    cell_px = _screen_cell(prof, geo.cols)
    est = estimate_seconds(plan, s.timing(), cell_px)
    return Job(plan, geo, sign, est, cell_px, preview, "hybrid", None, k, np.clip(final, 0, 255), skip)


__all__ = ["Geometry", "Job", "build_job", "FINE", "FILL", "indices_to_image"]
