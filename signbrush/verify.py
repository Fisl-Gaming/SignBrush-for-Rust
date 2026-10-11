"""Result verification: screenshot of the canvas -> palette index grid -> diff."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .imaging import srgb_to_lab


@dataclass
class Comparison:
    observed: np.ndarray        # (rows, cols) palette indices seen on screen
    mismatch: np.ndarray        # bool mask
    distance: np.ndarray        # Lab distance of each cell to its nearest palette colour

    @property
    def wrong(self) -> int:
        return int(self.mismatch.sum())

    @property
    def accuracy(self) -> float:
        return 1.0 - self.mismatch.mean()


def cell_colors(img: np.ndarray, cols: int, rows: int, inner: float = 0.4) -> np.ndarray:
    """Median colour of the central part of every cell -> (rows, cols, 3).

    Only the inner ``inner`` fraction of a cell is sampled so brush edges and
    anti-aliasing of the neighbours do not leak in.
    """
    h, w = img.shape[:2]
    cw, ch = w / cols, h / rows
    xs = (np.arange(cols) + 0.5) * cw
    ys = (np.arange(rows) + 0.5) * ch
    rx = max(0, int(cw * inner / 2))
    ry = max(0, int(ch * inner / 2))
    ox = np.arange(-rx, rx + 1)
    oy = np.arange(-ry, ry + 1)
    px = np.clip(np.round(xs[:, None] + ox[None, :]).astype(int), 0, w - 1)   # (cols, kx)
    py = np.clip(np.round(ys[:, None] + oy[None, :]).astype(int), 0, h - 1)   # (rows, ky)
    patch = img[py[:, None, :, None], px[None, :, None, :]]                    # (rows, cols, ky, kx, 3)
    return np.median(patch.reshape(rows, cols, -1, 3), axis=2)


def classify(colors: np.ndarray, palette: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lab = srgb_to_lab(colors.reshape(-1, 3))
    pal = srgb_to_lab(np.asarray(palette, dtype=np.float64))
    d = np.sqrt(((lab[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2))
    idx = d.argmin(axis=1)
    return idx.reshape(colors.shape[:2]).astype(np.int32), d.min(axis=1).reshape(colors.shape[:2])


def fit_screen_colors(colors: np.ndarray, expected: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Predict how ``expected`` colours look on screen.

    The editor shows the sign slightly darker / tinted than the typed colours (about
    -14 per channel was measured), so an affine colour map is fitted on the cells
    (robustly: the worst 30 % are refitted out). Falls back to identity when the map
    looks implausible.
    """
    e = np.asarray(expected, dtype=np.float64).reshape(-1, 3)
    o = np.asarray(colors, dtype=np.float64).reshape(-1, 3)
    use = np.ones(len(e), bool) if mask is None else np.asarray(mask, bool).reshape(-1)
    if use.sum() < 30:
        return np.asarray(expected, dtype=np.float64)
    X = np.c_[e, np.ones(len(e))]
    A = None
    for _ in range(2):
        A, *_ = np.linalg.lstsq(X[use], o[use], rcond=None)
        res = np.abs(X @ A - o).sum(axis=1)
        cut = np.quantile(res[use], 0.7)
        use = use & (res <= cut)
        if use.sum() < 30:
            break
    lin = A[:3]
    if not (0.6 < float(np.cbrt(np.linalg.det(lin))) < 1.4) or np.abs(A[3]).max() > 60:
        return np.asarray(expected, dtype=np.float64)
    return np.clip(X @ A, 0, 255).reshape(np.shape(expected))


def compare_expected(img: np.ndarray, expected_rgb: np.ndarray, max_de: float = 10.0,
                     fit_colors: bool = True, skip_mask: np.ndarray | None = None) -> Comparison:
    """Cells whose on-screen colour is farther than ``max_de`` (CIELAB) from the
    colour they should have. Works for any mode, including blended strokes."""
    rows, cols = expected_rgb.shape[:2]
    colors = cell_colors(img, cols, rows)
    expected = np.asarray(expected_rgb, dtype=np.float64)
    if fit_colors:
        expected = fit_screen_colors(colors, expected, None if skip_mask is None else ~skip_mask)
    de = np.sqrt(((srgb_to_lab(colors) - srgb_to_lab(expected)) ** 2).sum(axis=2))
    mismatch = de > max_de
    return Comparison(observed=np.where(mismatch, -1, 0).astype(np.int32), mismatch=mismatch, distance=de)


def compare(img: np.ndarray, target: np.ndarray, screen_palette: np.ndarray,
            max_distance: float = 0.0) -> Comparison:
    """Compare a canvas screenshot with the target index grid.

    ``screen_palette`` should hold the palette colours *as they look on
    screen* (sampled during calibration) - in-game rendering may differ from
    the nominal colours. Cells farther than ``max_distance`` (Lab, 0 = off)
    from every palette colour count as wrong as well (e.g. unpainted wood).
    """
    rows, cols = target.shape
    colors = cell_colors(img, cols, rows)
    observed, dist = classify(colors, screen_palette)
    mismatch = observed != target
    if max_distance > 0:
        unsure = dist > max_distance
        mismatch |= unsure
        observed = np.where(unsure, -1, observed)
    return Comparison(observed=observed, mismatch=mismatch, distance=dist)
