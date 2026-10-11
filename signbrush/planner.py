"""Stroke planner.

Turns a grid of palette indices into an ordered list of brush strokes.

Coordinates are in *grid units*: cell (row r, col c) spans x in [c, c+1],
y in [r, r+1]; its centre is (c + 0.5, r + 0.5). The executor maps grid units
to screen pixels, so the plan itself is resolution independent.

Pipeline (every step is simulated on a virtual canvas, so later steps only
paint what is still wrong):

1. base fill   - the dominant colour, whole canvas, biggest brush
2. coarse pass - b x b blocks of a uniform colour, biggest brush
3. fine pass   - per colour: run-length segments (row- or column-wise,
                 whichever gives fewer strokes) that may bridge over cells of
                 colours painted *later*; adjacent segments are chained into
                 snake-like polylines so one mouse press covers a whole blob.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

import numpy as np

UNKNOWN = -1
Point = tuple[float, float]


@dataclass(frozen=True)
class BrushSpec:
    name: str
    diameter: float            # in grid cells (the fine brush is ~1.0)

    @property
    def radius(self) -> float:
        return self.diameter / 2


@dataclass(frozen=True)
class Stroke:
    color: int
    brush: str
    points: tuple[Point, ...]   # polyline; a single point means one click
    phase: str = "fine"        # base | coarse | fine | fix | shape
    alpha: float = 1.0         # brush opacity

    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


@dataclass
class Plan:
    cols: int
    rows: int
    palette: list[tuple[int, int, int]]
    brushes: dict[str, float]           # name -> diameter (circle) / side (square) in cells
    strokes: list[Stroke] = field(default_factory=list)
    shape: str = "square"               # default brush tip: square | circle
    tips: dict[str, str] = field(default_factory=dict)   # per-brush tip overriding ``shape``

    def tip(self, brush: str) -> str:
        return self.tips.get(brush, self.shape)

    # -- stats -----------------------------------------------------------
    def color_switches(self) -> int:
        return _count_changes(s.color for s in self.strokes)

    def brush_switches(self) -> int:
        return _count_changes(s.brush for s in self.strokes)

    def summary(self) -> dict:
        phases: dict[str, int] = {}
        for s in self.strokes:
            phases[s.phase] = phases.get(s.phase, 0) + 1
        return {
            "strokes": len(self.strokes),
            "clicks": sum(1 for s in self.strokes if len(s.points) == 1),
            "color_switches": self.color_switches(),
            "brush_switches": self.brush_switches(),
            "phases": phases,
            "length_cells": round(sum(s.length() for s in self.strokes), 1),
        }

    # -- (de)serialisation for progress files ------------------------------
    def to_dict(self) -> dict:
        return {
            "cols": self.cols, "rows": self.rows,
            "palette": [list(c) for c in self.palette],
            "brushes": dict(self.brushes),
            "shape": self.shape,
            "tips": dict(self.tips),
            "strokes": [[s.color, s.brush, s.phase, [list(p) for p in s.points]] + ([s.alpha] if s.alpha != 1.0 else [])
                        for s in self.strokes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Plan":
        return cls(
            cols=int(d["cols"]), rows=int(d["rows"]),
            palette=[tuple(c) for c in d["palette"]],
            brushes={k: float(v) for k, v in d["brushes"].items()},
            strokes=[Stroke(int(st[0]), st[1], tuple(tuple(p) for p in st[3]), st[2],
                            float(st[4]) if len(st) > 4 else 1.0)
                     for st in d["strokes"]],
            shape=d.get("shape", "square"),
            tips=dict(d.get("tips", {})),
        )

    def fingerprint(self) -> str:
        import hashlib
        return hashlib.sha1(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


def _count_changes(seq: Iterable) -> int:
    n, prev = 0, object()
    for v in seq:
        if v != prev:
            n += 1
            prev = v
    return n


# ---------------------------------------------------------------- simulation

def rasterize(canvas: np.ndarray, stroke: Stroke, radius: float, shape: str = "circle") -> None:
    """Paint ``stroke`` onto ``canvas`` in place.

    A cell gets the stroke colour when its centre is covered by the brush
    swept along the polyline: Euclidean distance <= radius for a round tip,
    Chebyshev distance <= radius (half side) for a square tip.
    """
    rows, cols = canvas.shape
    pts = stroke.points if len(stroke.points) > 1 else stroke.points * 2
    eps = 1e-9
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if shape == "square":
            _rasterize_square_segment(canvas, stroke.color, x0, y0, x1, y1, radius)
            continue
        c0 = max(0, int(math.floor(min(x0, x1) - radius)))
        c1 = min(cols - 1, int(math.ceil(max(x0, x1) + radius)))
        r0 = max(0, int(math.floor(min(y0, y1) - radius)))
        r1 = min(rows - 1, int(math.ceil(max(y0, y1) + radius)))
        if c0 > c1 or r0 > r1:
            continue
        cx = np.arange(c0, c1 + 1) + 0.5
        cy = np.arange(r0, r1 + 1) + 0.5
        px, py = np.meshgrid(cx, cy)
        dx, dy = x1 - x0, y1 - y0
        ll = dx * dx + dy * dy
        if ll == 0:
            t = np.zeros_like(px)
        else:
            t = np.clip(((px - x0) * dx + (py - y0) * dy) / ll, 0.0, 1.0)
        d2 = (px - (x0 + t * dx)) ** 2 + (py - (y0 + t * dy)) ** 2
        mask = d2 <= radius * radius + eps
        canvas[r0:r1 + 1, c0:c1 + 1][mask] = stroke.color


def _rasterize_square_segment(canvas, color, x0, y0, x1, y1, r) -> None:
    eps = 1e-9
    if x0 != x1 and y0 != y1:   # diagonal: union of stamps along the segment
        n = int(math.ceil(max(abs(x1 - x0), abs(y1 - y0)) / 0.25))
        for k in range(n + 1):
            t = k / n
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            _rasterize_square_segment(canvas, color, x, y, x, y, r)
        return
    rows, cols = canvas.shape
    # cells whose centre c+0.5 lies in [lo - r, hi + r]
    c0 = max(0, int(math.ceil(min(x0, x1) - r - 0.5 - eps)))
    c1 = min(cols - 1, int(math.floor(max(x0, x1) + r - 0.5 + eps)))
    r0 = max(0, int(math.ceil(min(y0, y1) - r - 0.5 - eps)))
    r1 = min(rows - 1, int(math.floor(max(y0, y1) + r - 0.5 + eps)))
    if c0 <= c1 and r0 <= r1:
        canvas[r0:r1 + 1, c0:c1 + 1] = color


def simulate(plan: Plan, upto: int | None = None, canvas: np.ndarray | None = None) -> np.ndarray:
    """Grid-level result of executing the first ``upto`` strokes."""
    if canvas is None:
        canvas = np.full((plan.rows, plan.cols), UNKNOWN, dtype=np.int32)
    else:
        canvas = canvas.copy()
    for s in plan.strokes[:upto]:
        rasterize(canvas, s, plan.brushes[s.brush] / 2, plan.tip(s.brush))
    return canvas


# ---------------------------------------------------------------- options

@dataclass
class PlanOptions:
    base_fill: bool = True
    coarse: bool = True
    coarse_purity: float = 1.0  # share of a block that must have the block's colour (1 = uniform only)
    max_bridge: int = 12        # max run of already-correct cells a fine stroke may cross
    chain: bool = True          # join segments of neighbouring rows into polylines
    skip_colors: tuple[int, ...] = ()   # colours never painted (e.g. "leave sign blank")


# ---------------------------------------------------------------- planning

def plan_strokes(target: np.ndarray, palette: Sequence[Sequence[int]],
                 brushes: Sequence[BrushSpec], opts: PlanOptions | None = None,
                 canvas: np.ndarray | None = None, phase_fine: str = "fine",
                 shape: str = "square", skip_mask: np.ndarray | None = None) -> Plan:
    """Build a stroke plan that turns ``canvas`` (default: unknown) into ``target``.

    ``brushes[0]`` is treated as the fine (1-cell) brush; the largest other
    brush with diameter >= 2 cells is used for base fill and the coarse pass.
    """
    opts = opts or PlanOptions()
    target = np.asarray(target, dtype=np.int32)
    rows, cols = target.shape
    if not brushes:
        raise ValueError("at least one brush is required")
    fine = brushes[0]
    bigs = sorted((b for b in brushes[1:] if b.diameter >= 2), key=lambda b: -b.diameter)
    big = bigs[0] if bigs else None
    plan = Plan(cols=cols, rows=rows, palette=[tuple(int(v) for v in c) for c in palette],
                brushes={b.name: float(b.diameter) for b in brushes}, shape=shape)
    cv = (np.full(target.shape, UNKNOWN, dtype=np.int32) if canvas is None
          else np.asarray(canvas, dtype=np.int32).copy())
    skip = set(opts.skip_colors)
    # cells of skipped colours count as done whatever is on the canvas
    done_mask = np.isin(target, list(skip)) if skip else np.zeros(target.shape, bool)
    if skip_mask is not None:            # cells that must stay untouched (transparent areas)
        done_mask = done_mask | np.asarray(skip_mask, dtype=bool)

    def emit(strokes: list[Stroke], radius: float) -> None:
        for s in strokes:
            rasterize(cv, s, radius, shape)
        plan.strokes.extend(strokes)

    if opts.base_fill and canvas is None and not done_mask.any():   # a full fill would paint skipped cells
        vals, counts = np.unique(target[~done_mask], return_counts=True)
        if len(vals):
            dom = int(vals[np.argmax(counts)])
            brush = big or fine
            emit(_base_fill(dom, brush, cols, rows), brush.radius)

    if opts.coarse:   # brush ladder: biggest blocks first, each size only fixes what is still wrong
        for b in bigs:
            emit(_coarse_pass(target, cv, done_mask, b, opts.coarse_purity), b.radius)

    emit(_fine_pass(target, cv, done_mask, fine, opts, phase_fine, shape), fine.radius)
    return plan


def plan_fixes(target: np.ndarray, observed: np.ndarray, palette, brushes: Sequence[BrushSpec],
               opts: PlanOptions | None = None, shape: str = "square",
               skip_mask: np.ndarray | None = None) -> Plan:
    """Plan strokes that repaint only the cells where ``observed`` != ``target``."""
    o = PlanOptions(**{**asdict(opts or PlanOptions()), "base_fill": False, "coarse": False})
    o.skip_colors = tuple(o.skip_colors)
    return plan_strokes(target, palette, brushes, o, canvas=observed, phase_fine="fix", shape=shape,
                        skip_mask=skip_mask)


def _base_fill(color: int, brush: BrushSpec, cols: int, rows: int) -> list[Stroke]:
    """Horizontal serpentine bands that cover the whole canvas."""
    r = brush.radius
    step = max(1.0, math.floor(brush.diameter))
    ys: list[float] = []
    y = min(r, rows / 2)
    while True:
        ys.append(min(y, rows - min(r, rows / 2)))
        if ys[-1] + r >= rows - 1e-9:
            break
        y += step
    xl, xr = 0.5, cols - 0.5
    out = []
    for i, y in enumerate(dict.fromkeys(ys)):
        # separate straight bands (alternating direction): if the game misses a frame,
        # a straight line is still straight, while a corner of a zig-zag becomes a diagonal
        a, b = (xl, xr) if i % 2 == 0 else (xr, xl)
        out.append(Stroke(color, brush.name, ((a, y), (b, y)), "base"))
    return out


def _coarse_pass(target: np.ndarray, cv: np.ndarray, done: np.ndarray, brush: BrushSpec,
                 purity: float = 1.0) -> list[Stroke]:
    rows, cols = target.shape
    b = int(math.floor(brush.diameter))
    r = brush.radius
    if b < 2 or rows < b or cols < b:
        return []
    br, bc = rows // b, cols // b
    blocks = target[:br * b, :bc * b].reshape(br, b, bc, b).transpose(0, 2, 1, 3).reshape(br, bc, b * b)
    if purity >= 1.0:
        first = blocks[..., 0]
        uniform = (blocks == first[..., None]).all(axis=2)
    else:   # dominant colour per block; the minority cells are repainted by later passes
        k = int(target.max()) + 1
        counts = (blocks[..., None] == np.arange(k, dtype=blocks.dtype)).sum(axis=2)
        first = counts.argmax(axis=2).astype(target.dtype)
        uniform = counts.max(axis=2) >= purity * b * b - 1e-9
    cvb = cv[:br * b, :bc * b].reshape(br, b, bc, b).transpose(0, 2, 1, 3).reshape(br, bc, b * b)
    dn = done[:br * b, :bc * b].reshape(br, b, bc, b).transpose(0, 2, 1, 3).reshape(br, bc, b * b)
    own = blocks == first[..., None]
    uniform = uniform & ~dn.any(axis=2)          # never stamp a big brush over cells that must stay untouched
    needy = uniform & (own & (cvb != first[..., None]) & ~dn).any(axis=2)

    by_color: dict[int, dict[int, list[list[Point]]]] = {}   # colour -> block row -> segments
    for i in range(br):
        y = i * b + b / 2
        j = 0
        while j < bc:
            if not uniform[i, j] or dn[i, j].all():
                j += 1
                continue
            c = int(first[i, j])
            k = j
            while k + 1 < bc and uniform[i, k + 1] and first[i, k + 1] == c:
                k += 1
            # trim blocks that are already correct at both ends
            s, e = j, k
            while s <= e and not needy[i, s]:
                s += 1
            while e >= s and not needy[i, e]:
                e -= 1
            if s <= e:
                xs, xe = s * b + r, (e + 1) * b - r
                pts = [((xs + xe) / 2, y)] if xe <= xs else [(xs, y), (xe, y)]
                by_color.setdefault(c, {}).setdefault(i, []).append(pts)
            j = k + 1
    result: list[Stroke] = []
    for c in sorted(by_color, key=lambda c: -sum(len(v) for v in by_color[c].values())):
        rows_map = by_color[c]
        for n, i in enumerate(sorted(rows_map)):   # serpentine order inside a colour
            segs = rows_map[i]
            if n % 2:
                segs = [list(reversed(p)) for p in reversed(segs)]
            result += [Stroke(c, brush.name, tuple(p), "coarse") for p in segs]
    return result


def _runs_1d(allowed: np.ndarray, needy: np.ndarray, max_bridge: int) -> list[tuple[int, int]]:
    """Segments [a, b] inside ``allowed`` that cover every ``needy`` cell.

    A segment never starts or ends on a non-needy cell and never crosses more
    than ``max_bridge`` consecutive non-needy cells.
    """
    out: list[tuple[int, int]] = []
    n = len(allowed)
    i = 0
    while i < n:
        if not needy[i]:
            i += 1
            continue
        a = b = i
        j = i + 1
        gap = 0
        while j < n and allowed[j]:
            if needy[j]:
                b, gap = j, 0
            else:
                gap += 1
                if gap > max_bridge:
                    break
            j += 1
        out.append((a, b))
        i = b + 1
    return out


def _segments(allowed: np.ndarray, needy: np.ndarray, max_bridge: int) -> list[tuple[int, int, int]]:
    """(line, a, b) runs for every line (row) of 2-D masks."""
    segs = []
    for line in np.nonzero(needy.any(axis=1))[0]:
        for a, b in _runs_1d(allowed[line], needy[line], max_bridge):
            segs.append((int(line), a, b))
    return segs


def _chain(segs: list[tuple[int, int, int]], chain: bool) -> list[list[tuple[int, int]]]:
    """Order segments serpentine-style and join vertically adjacent ones.

    Returns polylines as lists of (line, pos) integer cell coordinates.
    A segment on line L+1 is appended to the current polyline when the
    polyline's end position lies inside it, so the link is a straight
    one-cell step that only touches cells belonging to both segments.
    """
    by_line: dict[int, list[tuple[int, int]]] = {}
    for line, a, b in segs:
        by_line.setdefault(line, []).append((a, b))
    used: dict[int, list[bool]] = {ln: [False] * len(v) for ln, v in by_line.items()}
    lines = sorted(by_line)
    polys: list[list[tuple[int, int]]] = []
    forward = True
    for ln in lines:
        order = range(len(by_line[ln])) if forward else range(len(by_line[ln]) - 1, -1, -1)
        for idx in order:
            if used[ln][idx]:
                continue
            used[ln][idx] = True
            a, b = by_line[ln][idx]
            s, e = (a, b) if forward else (b, a)
            poly = [(ln, s), (ln, e)]
            cur_line, cur = ln, e
            while chain:
                nxt = cur_line + 1
                cand = by_line.get(nxt)
                if not cand:
                    break
                hit = next((k for k, (ca, cb) in enumerate(cand)
                            if not used[nxt][k] and ca <= cur <= cb), None)
                if hit is None:
                    break
                used[nxt][hit] = True
                ca, cb = cand[hit]
                poly.append((nxt, cur))
                # visit the nearer end first, finish at the far one
                if cur - ca <= cb - cur:
                    path = [ca, cb]
                else:
                    path = [cb, ca]
                for p in path:
                    if poly[-1] != (nxt, p):
                        poly.append((nxt, p))
                cur_line, cur = nxt, poly[-1][1]
            polys.append(_dedupe(poly))
        forward = not forward
    return polys


def _dedupe(poly: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = [poly[0]]
    for p in poly[1:]:
        if p != out[-1]:
            out.append(p)
    # drop collinear middle points
    res = [out[0]]
    for k in range(1, len(out) - 1):
        a, b, c = res[-1], out[k], out[k + 1]
        if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]) and \
                (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0:
            continue
        res.append(b)
    if len(out) > 1:
        res.append(out[-1])
    return res


def _fine_pass(target: np.ndarray, cv: np.ndarray, done: np.ndarray, brush: BrushSpec,
               opts: PlanOptions, phase: str, shape: str) -> list[Stroke]:
    skip = set(opts.skip_colors)
    needed = (target != cv) & ~done
    colors = [int(c) for c in np.unique(target[needed]) if int(c) not in skip]
    # big areas first, details on top
    colors.sort(key=lambda c: -int(np.count_nonzero(needed & (target == c))))
    rank = {c: k for k, c in enumerate(colors)}
    max_c = int(max(target.max(), max(colors, default=0))) + 1
    strokes: list[Stroke] = []
    for k, c in enumerate(colors):
        later_lut = np.zeros(max_c + 1, dtype=bool)
        for c2, k2 in rank.items():
            if k2 > k:
                later_lut[c2] = True
        later = later_lut[target]
        needy = (target == c) & (cv != c) & ~done
        if not needy.any():
            continue
        allowed = ((target == c) | (later & (cv != target))) & ~done
        variants = []
        for transpose in (False, True):
            al, nd = (allowed.T, needy.T) if transpose else (allowed, needy)
            polys = _chain(_segments(al, nd, opts.max_bridge), opts.chain)
            variants.append((len(polys), transpose, polys))
        _, transpose, polys = min(variants, key=lambda v: (v[0], v[1]))
        for poly in polys:
            if transpose:   # (line, pos) = (col, row)
                pts = tuple((ln + 0.5, p + 0.5) for ln, p in poly)
            else:           # (line, pos) = (row, col)
                pts = tuple((p + 0.5, ln + 0.5) for ln, p in poly)
            s = Stroke(c, brush.name, pts, phase)
            rasterize(cv, s, brush.radius, shape)
            strokes.append(s)
    return strokes


# ---------------------------------------------------------------- timing

@dataclass
class Timing:
    action_delay: float = 0.02      # s after every mouse/key action
    move_delay: float = 0.02        # s after positioning the cursor
    draw_step_px: float = 6.0       # interpolation step while dragging (line_mode "drag")
    draw_step_delay: float = 0.004  # s per interpolation step / per polyline vertex
    click_hold: float = 0.02        # s mouse held down for a dot
    color_switch: float = 0.12      # s per colour change (incl. UI settle)
    brush_switch: float = 0.15      # s per size / opacity change
    line_mode: str = "jump"         # jump (one move per vertex) | drag | shift
    release_gap: float = 0.0        # min time between a release and the next press


def estimate_seconds(plan: Plan, timing: Timing, cell_px: float) -> float:
    """Mirrors what the executor does (see ``Executor.click`` / ``draw_stroke``)."""
    tm = timing
    gap_extra = max(0.0, tm.release_gap - tm.action_delay - tm.move_delay)   # enforced before every press
    click = tm.move_delay + tm.click_hold + tm.action_delay + gap_extra
    control = click + 7 * tm.action_delay + tm.brush_switch     # click field, Ctrl+A, type, Enter
    t = 0.0
    color = brush = alpha = None
    for s in plan.strokes:
        if s.brush != brush:
            t += control
            brush = s.brush
        if alpha is None or s.alpha != alpha:
            t += control
            alpha = s.alpha
        if s.color != color:
            t += click + tm.color_switch
            color = s.color
        if len(s.points) == 1:
            t += click
        elif tm.line_mode == "drag":
            steps = max(1.0, s.length() * cell_px / max(tm.draw_step_px, 0.5))
            t += tm.move_delay + 3 * tm.action_delay + steps * tm.draw_step_delay + gap_extra
        else:
            t += tm.move_delay + 2 * tm.action_delay + (len(s.points) - 1) * tm.draw_step_delay + gap_extra
    return t


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
