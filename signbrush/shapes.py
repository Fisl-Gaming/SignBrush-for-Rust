"""Shape mode: the picture is built from semi-transparent circles, one click each.

The same idea as "primitive"-style generators (and Bob-Rust): repeatedly add
the circle that reduces the error to the target the most. Opacity blending of
the 64 game colours gives smooth shading with relatively few clicks.

Implementation notes (all numpy, no per-pixel Python):

* For a circle with opacity ``a`` and colour ``c`` the change of squared error
  over its pixels is

      dE = 2a*Sum((T-C).C) + a^2*Sum|C|^2 - 2a*c.(Sum(T-C) + a*Sum C) + n*a^2*|c|^2

  so only a few region sums are needed. They come from per-row prefix sums:
  O(circle height) per candidate, evaluated for hundreds of candidates and all
  (opacity x colour) pairs at once.
* Candidate centres are sampled where the error is large, then refined by a
  small vectorised hill climb.
* Afterwards shapes are reordered to group equal (size, opacity, colour)
  while keeping the order of overlapping shapes that do not commute.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


class Cancelled(Exception):
    pass


@dataclass
class ShapeOptions:
    count: int = 6000
    sizes: Sequence[float] = (3, 6, 12, 25, 50, 100)        # diameters in texture px
    alphas: Sequence[float] = (0.09, 0.19, 0.39, 0.75, 0.9, 1.0)
    work_size: int = 256          # generator resolution (longest side)
    candidates: int = 128         # random centres per size per shape
    climb_rounds: int = 4
    mutations: int = 48
    seed: int = 0


@dataclass
class Shape:
    x: int          # centre, work px
    y: int
    size: int       # index into sizes
    alpha: int      # index into alphas
    color: int      # palette index


@dataclass
class _Disc:
    dy: np.ndarray      # row offsets
    hx: np.ndarray      # half width per row
    mask: np.ndarray    # (2r+1, 2r+1) bool
    r: int


def make_disc(diameter: float) -> _Disc:
    rad = max(0.5, diameter / 2)
    r = int(math.floor(rad))
    dy = np.arange(-r, r + 1)
    hx = np.floor(np.sqrt(np.maximum(rad * rad - dy * dy, 0))).astype(np.int64)
    xs = np.arange(-r, r + 1)
    mask = np.abs(xs[None, :]) <= hx[:, None]
    return _Disc(dy, hx, mask, r)


class ShapeGenerator:
    def __init__(self, target: np.ndarray, palette: np.ndarray, blank: Sequence[float],
                 sizes_work: Sequence[float], alphas: Sequence[float], opts: ShapeOptions | None = None):
        self.opts = opts or ShapeOptions()
        self.T = np.asarray(target, dtype=np.float64)
        self.H, self.W = self.T.shape[:2]
        self.C = np.empty_like(self.T)
        self.C[:] = np.asarray(blank, dtype=np.float64)
        self.pal = np.asarray(palette, dtype=np.float64)
        self.pal2 = (self.pal ** 2).sum(axis=1)
        self.alphas = np.asarray(alphas, dtype=np.float64)
        self.discs = [make_disc(d) for d in sizes_work]
        self.rng = np.random.default_rng(self.opts.seed)
        self.shapes: list[Shape] = []
        self.P = np.zeros((9, self.H, self.W + 1))
        self.err = np.zeros((self.H, self.W))
        self._update_rows(0, self.H)

    # -- bookkeeping ------------------------------------------------------------------
    def _update_rows(self, y0: int, y1: int) -> None:
        T, C = self.T[y0:y1], self.C[y0:y1]
        D = T - C
        ch = np.empty((9, y1 - y0, self.W))
        ch[0] = (D * D).sum(axis=2)
        ch[1] = (D * C).sum(axis=2)
        ch[2] = (C * C).sum(axis=2)
        ch[3:6] = np.moveaxis(D, 2, 0)
        ch[6:9] = np.moveaxis(C, 2, 0)
        np.cumsum(ch, axis=2, out=self.P[:, y0:y1, 1:])
        self.err[y0:y1] = ch[0]

    @property
    def total_error(self) -> float:
        return float(self.err.sum())

    # -- evaluation ---------------------------------------------------------------------
    def evaluate(self, si: int, cx: np.ndarray, cy: np.ndarray):
        """Best (delta, alpha index, colour index) for circles of size ``si`` at (cx, cy)."""
        d = self.discs[si]
        Y = cy[:, None] + d.dy[None, :]
        valid = (Y >= 0) & (Y < self.H)
        Yc = np.clip(Y, 0, self.H - 1)
        xl = np.clip(cx[:, None] - d.hx[None, :], 0, self.W - 1)
        xh = np.clip(cx[:, None] + d.hx[None, :], 0, self.W - 1)
        S = ((self.P[:, Yc, xh + 1] - self.P[:, Yc, xl]) * valid).sum(axis=2)     # (9, B)
        n = ((xh - xl + 1) * valid).sum(axis=1).astype(np.float64)                 # (B,)
        G, Q = S[1], S[2]
        U, V = S[3:6].T, S[6:9].T
        colU = U @ self.pal.T                                                      # (B, K)
        colV = V @ self.pal.T
        a = self.alphas[None, :, None]
        delta = (2 * a * G[:, None, None] + a * a * Q[:, None, None]
                 - 2 * a * (colU[:, None, :] + a * colV[:, None, :])
                 + n[:, None, None] * a * a * self.pal2[None, None, :])           # (B, A, K)
        flat = delta.reshape(len(cx), -1)
        best = flat.argmin(axis=1)
        val = flat[np.arange(len(cx)), best]
        k = self.pal.shape[0]
        return val, best // k, best % k

    def _sample_centres(self, m: int) -> tuple[np.ndarray, np.ndarray]:
        half = m // 2
        cdf = np.cumsum(self.err.ravel())
        if cdf[-1] > 0:
            pick = np.searchsorted(cdf, self.rng.random(half) * cdf[-1])
            pick = np.minimum(pick, self.H * self.W - 1)
        else:
            pick = self.rng.integers(0, self.H * self.W, half)
        uni = self.rng.integers(0, self.H * self.W, m - half)
        idx = np.concatenate([pick, uni])
        return idx % self.W, idx // self.W

    def _best_of(self, sis: np.ndarray, cx: np.ndarray, cy: np.ndarray):
        best = (np.inf, 0, 0, 0, 0, 0)
        for si in np.unique(sis):
            m = sis == si
            val, ai, ki = self.evaluate(int(si), cx[m], cy[m])
            j = int(val.argmin())
            if val[j] < best[0]:
                best = (float(val[j]), int(si), int(cx[m][j]), int(cy[m][j]), int(ai[j]), int(ki[j]))
        return best

    def step(self) -> Shape | None:
        o = self.opts
        nsz = len(self.discs)
        cx, cy = self._sample_centres(o.candidates * nsz)
        sis = np.repeat(np.arange(nsz), o.candidates)
        best = self._best_of(sis, cx, cy)
        for _ in range(o.climb_rounds):   # vectorised hill climb around the winner
            _, si, x, y, _, _ = best
            sigma = max(1.0, self.discs[si].r / 2)
            mx = np.clip(np.round(x + self.rng.normal(0, sigma, o.mutations)), 0, self.W - 1).astype(np.int64)
            my = np.clip(np.round(y + self.rng.normal(0, sigma, o.mutations)), 0, self.H - 1).astype(np.int64)
            ms = np.clip(si + self.rng.choice([-1, 0, 0, 1], o.mutations), 0, nsz - 1)
            cand = self._best_of(ms, mx, my)
            if cand[0] < best[0]:
                best = cand
        delta, si, x, y, ai, ki = best
        if not delta < 0:
            return None
        shape = Shape(x, y, si, ai, ki)
        self.apply(shape)
        return shape

    def apply(self, s: Shape) -> None:
        d = self.discs[s.size]
        a = self.alphas[s.alpha]
        col = self.pal[s.color]
        y0, y1 = max(0, s.y - d.r), min(self.H, s.y + d.r + 1)
        x0, x1 = max(0, s.x - d.r), min(self.W, s.x + d.r + 1)
        m = d.mask[y0 - (s.y - d.r):y1 - (s.y - d.r), x0 - (s.x - d.r):x1 - (s.x - d.r)]
        region = self.C[y0:y1, x0:x1]
        region[m] = (1 - a) * region[m] + a * col
        self.shapes.append(s)
        self._update_rows(y0, y1)

    def run(self, count: int, progress: Callable[[int, int], None] | None = None,
            cancel: Callable[[], bool] | None = None) -> list[Shape]:
        misses = 0
        while len(self.shapes) < count:
            if cancel and len(self.shapes) % 32 == 0 and cancel():
                raise Cancelled()
            if self.step() is None:
                misses += 1
                if misses > 20:
                    break
            else:
                misses = 0
            if progress and len(self.shapes) % 100 == 0:
                progress(len(self.shapes), count)
        return self.shapes


# ---------------------------------------------------------------- ordering

def _switch_cost(a: tuple, b: tuple | None) -> int:
    if b is None:
        return 7
    size, alpha, color = a
    return (3 if size != b[0] else 0) + (3 if alpha != b[1] else 0) + (1 if color != b[2] else 0)


def sort_shapes(shapes: list[Shape], radii: Sequence[float], chunk: int = 800) -> list[Shape]:
    """Reorder to minimise brush/opacity/colour switches without changing the result.

    Two shapes commute unless they overlap and differ in (colour, opacity) -
    blending with the same colour and opacity is order independent. Within each
    chunk a greedy topological sort prefers shapes with the current settings.
    """
    out: list[Shape] = []
    state: tuple | None = None
    rad = np.asarray(radii, dtype=np.float64)
    for c0 in range(0, len(shapes), chunk):
        part = shapes[c0:c0 + chunk]
        n = len(part)
        xs = np.array([s.x for s in part], dtype=np.float64)
        ys = np.array([s.y for s in part], dtype=np.float64)
        rs = rad[[s.size for s in part]]
        ca = np.array([s.color * 1000 + s.alpha for s in part])
        dist2 = (xs[:, None] - xs[None]) ** 2 + (ys[:, None] - ys[None]) ** 2
        overlap = dist2 <= (rs[:, None] + rs[None] + 1) ** 2
        dep = np.triu(overlap & (ca[:, None] != ca[None]), 1)
        indeg = dep.sum(axis=0)
        succ = [np.nonzero(dep[i])[0] for i in range(n)]
        keys = [(s.size, s.alpha, s.color) for s in part]
        buckets: dict[tuple, list[int]] = {}
        for i in range(n):
            if indeg[i] == 0:
                buckets.setdefault(keys[i], []).append(i)
        done = 0
        while done < n:
            if state in buckets and buckets[state]:
                key = state
            else:
                key = min((k for k, v in buckets.items() if v),
                          key=lambda k: (_switch_cost(k, state), -len(buckets[k])))
            i = buckets[key].pop()
            if not buckets[key]:
                del buckets[key]
            out.append(part[i])
            state = key
            done += 1
            for j in succ[i]:
                indeg[j] -= 1
                if indeg[j] == 0:
                    buckets.setdefault(keys[j], []).append(int(j))
    return out


# ---------------------------------------------------------------- rendering

def render(shapes: Sequence[Shape], size: tuple[int, int], palette: np.ndarray, blank: Sequence[float],
           sizes: Sequence[float], alphas: Sequence[float], scale: float = 1.0) -> np.ndarray:
    """Exact alpha-blended result; ``scale`` maps work px to output px."""
    w, h = size
    C = np.empty((h, w, 3))
    C[:] = np.asarray(blank, dtype=np.float64)
    discs = [make_disc(d * scale) for d in sizes]
    pal = np.asarray(palette, dtype=np.float64)
    for s in shapes:
        d = discs[s.size]
        x, y = int(round((s.x + 0.5) * scale - 0.5)), int(round((s.y + 0.5) * scale - 0.5))
        y0, y1 = max(0, y - d.r), min(h, y + d.r + 1)
        x0, x1 = max(0, x - d.r), min(w, x + d.r + 1)
        if y0 >= y1 or x0 >= x1:
            continue
        m = d.mask[y0 - (y - d.r):y1 - (y - d.r), x0 - (x - d.r):x1 - (x - d.r)]
        a = alphas[s.alpha]
        region = C[y0:y1, x0:x1]
        region[m] = (1 - a) * region[m] + a * pal[s.color]
    return np.clip(C, 0, 255).astype(np.uint8)
