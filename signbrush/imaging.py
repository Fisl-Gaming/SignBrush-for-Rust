"""Image preparation: fitting to the canvas grid, palette quantization, dithering.

Everything here is pure (no screen / input access) so it can be unit-tested.
A prepared image is a 2-D array of palette indices, one per canvas cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

RGB = tuple[int, int, int]

FIT_MODES = ("pad", "crop", "stretch")

# LUT resolution per channel (64 -> 4-unit steps, 262 144 entries).
_LUT_LEVELS = 64
_LUT_SHIFT = 2


# ---------------------------------------------------------------- colour math

def parse_color(value: str | Sequence[int]) -> RGB:
    """Accept '#rrggbb', 'rrggbb' or an (r, g, b) sequence."""
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) != 6:
            raise ValueError(f"bad colour: {value!r}")
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    r, g, b = (int(v) for v in value)
    return r, g, b


def to_hex(rgb: Sequence[int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(int(v) for v in rgb[:3]))


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert sRGB values in 0..255 (any shape (..., 3)) to CIELAB (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    lab = np.empty_like(f)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def nearest_palette(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Index of the perceptually nearest palette colour for each pixel."""
    lab = srgb_to_lab(rgb.reshape(-1, 3))
    pal = srgb_to_lab(np.asarray(palette, dtype=np.float64))
    d = ((lab[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
    return d.argmin(axis=1).reshape(rgb.shape[:-1])


def build_lut(palette: np.ndarray) -> np.ndarray:
    """Nearest-palette lookup table indexed by (r>>2, g>>2, b>>2)."""
    step = 256 // _LUT_LEVELS
    axis = np.arange(_LUT_LEVELS) * step + step // 2
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
    out = np.empty(grid.shape[:-1], dtype=np.int32)
    flat = grid.reshape(-1, 3)
    pal_lab = srgb_to_lab(np.asarray(palette, dtype=np.float64))
    res = out.reshape(-1)
    chunk = 32768
    for i in range(0, len(flat), chunk):
        lab = srgb_to_lab(flat[i:i + chunk])
        d = ((lab[:, None, :] - pal_lab[None, :, :]) ** 2).sum(axis=2)
        res[i:i + chunk] = d.argmin(axis=1)
    return out


# ---------------------------------------------------------------- geometry

def grid_size(canvas_px: tuple[float, float], cell_px: float, max_cells: int = 0) -> tuple[int, int]:
    """Number of (cols, rows) cells that fit the on-screen canvas."""
    w, h = canvas_px
    if cell_px <= 0:
        raise ValueError("cell size must be positive")
    cols = max(1, int(round(w / cell_px)))
    rows = max(1, int(round(h / cell_px)))
    if max_cells and cols * rows > max_cells:
        k = (max_cells / (cols * rows)) ** 0.5
        cols, rows = max(1, int(cols * k)), max(1, int(rows * k))
    return cols, rows


def flatten_alpha(img: Image.Image, background: RGB, alpha_threshold: int = 0) -> Image.Image:
    """Composite transparent areas onto the background colour.

    With ``alpha_threshold`` > 0 alpha is first binarised, which avoids
    halo fringes on pixel art / logos.
    """
    rgba = img.convert("RGBA")
    if alpha_threshold > 0:
        a = np.asarray(rgba.getchannel("A"))
        rgba.putalpha(Image.fromarray(np.where(a >= alpha_threshold, 255, 0).astype(np.uint8)))
    bg = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


def fit_image(img: Image.Image, size: tuple[int, int], mode: str = "pad",
              background: RGB = (255, 255, 255), alpha_threshold: int = 0,
              resample: Image.Resampling = Image.Resampling.LANCZOS) -> Image.Image:
    """Scale ``img`` to exactly ``size`` (cols, rows) keeping the aspect ratio.

    pad     - letterbox: the whole picture is visible, margins get the background
    crop    - fill the canvas, cutting the overflow centred
    stretch - ignore the aspect ratio
    """
    if mode not in FIT_MODES:
        raise ValueError(f"fit mode must be one of {FIT_MODES}")
    tw, th = size
    src = flatten_alpha(img, background, alpha_threshold)
    sw, sh = src.size
    if mode == "stretch":
        return src.resize((tw, th), resample)
    if mode == "crop":
        scale = max(tw / sw, th / sh)
        cw, ch = min(sw, tw / scale), min(sh, th / scale)
        left, top = (sw - cw) / 2, (sh - ch) / 2
        return src.resize((tw, th), resample, box=(left, top, left + cw, top + ch))
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    inner = src.resize((nw, nh), resample)
    out = Image.new("RGB", (tw, th), background)
    out.paste(inner, ((tw - nw) // 2, (th - nh) // 2))
    return out


def fit_mask(img: Image.Image, size: tuple[int, int], mode: str = "pad",
             alpha_threshold: int = 0) -> np.ndarray:
    """(rows, cols) bool mask of cells that should be painted: opaque parts of the
    picture. Transparent pixels and the letterbox margins are False."""
    tw, th = size
    a = img.convert("RGBA").getchannel("A")
    sw, sh = a.size
    res = Image.Resampling.BILINEAR
    if mode == "stretch":
        out = a.resize((tw, th), res)
    elif mode == "crop":
        scale = max(tw / sw, th / sh)
        cw, ch = min(sw, tw / scale), min(sh, th / scale)
        left, top = (sw - cw) / 2, (sh - ch) / 2
        out = a.resize((tw, th), res, box=(left, top, left + cw, top + ch))
    else:
        scale = min(tw / sw, th / sh)
        nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
        out = Image.new("L", (tw, th), 0)
        out.paste(a.resize((nw, nh), res), ((tw - nw) // 2, (th - nh) // 2))
    return np.asarray(out) >= (alpha_threshold or 128)


# ---------------------------------------------------------------- quantization

def quantize(rgb: np.ndarray, palette: np.ndarray, dither: bool = False,
             lut: np.ndarray | None = None) -> np.ndarray:
    """Map an (H, W, 3) image to palette indices, optionally with Floyd–Steinberg."""
    palette = np.asarray(palette, dtype=np.float64)
    if lut is None:
        lut = build_lut(palette)
    arr = np.asarray(rgb, dtype=np.float64)
    if not dither:
        q = np.clip(arr, 0, 255).astype(np.int32) >> _LUT_SHIFT
        return lut[q[..., 0], q[..., 1], q[..., 2]]
    return _floyd_steinberg(arr, palette, lut)


def _floyd_steinberg(arr: np.ndarray, palette: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Serpentine Floyd–Steinberg error diffusion (pure Python lists for speed)."""
    h, w = arr.shape[:2]
    buf = arr.tolist()
    pal = palette.tolist()
    lut_l = lut  # numpy indexing of scalars is the hot spot; keep the array
    out = np.empty((h, w), dtype=np.int32)
    for y in range(h):
        row = buf[y]
        nxt = buf[y + 1] if y + 1 < h else None
        if y % 2 == 0:
            xs, d = range(w), 1
        else:
            xs, d = range(w - 1, -1, -1), -1
        orow = out[y]
        for x in xs:
            px = row[x]
            r = 0 if px[0] < 0 else 255 if px[0] > 255 else px[0]
            g = 0 if px[1] < 0 else 255 if px[1] > 255 else px[1]
            b = 0 if px[2] < 0 else 255 if px[2] > 255 else px[2]
            k = int(lut_l[int(r) >> _LUT_SHIFT, int(g) >> _LUT_SHIFT, int(b) >> _LUT_SHIFT])
            orow[x] = k
            pc = pal[k]
            er, eg, eb = r - pc[0], g - pc[1], b - pc[2]
            xn = x + d
            if 0 <= xn < w:
                p = row[xn]
                p[0] += er * 0.4375; p[1] += eg * 0.4375; p[2] += eb * 0.4375
            if nxt is not None:
                xb = x - d
                if 0 <= xb < w:
                    p = nxt[xb]
                    p[0] += er * 0.1875; p[1] += eg * 0.1875; p[2] += eb * 0.1875
                p = nxt[x]
                p[0] += er * 0.3125; p[1] += eg * 0.3125; p[2] += eb * 0.3125
                if 0 <= xn < w:
                    p = nxt[xn]
                    p[0] += er * 0.0625; p[1] += eg * 0.0625; p[2] += eb * 0.0625
    return out


def choose_colors(rgb: np.ndarray, palette: np.ndarray, n: int,
                  required: Iterable[int] = ()) -> list[int]:
    """Greedily pick ``n`` palette indices that minimise the total Lab error.

    ``required`` indices (e.g. the background) are always kept.
    """
    k = len(palette)
    chosen = [i for i in dict.fromkeys(required) if 0 <= i < k]
    if n <= 0 or n >= k:
        return list(range(k))
    px = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    if len(px) > 40000:  # a uniform subsample is plenty for colour statistics
        px = px[np.linspace(0, len(px) - 1, 40000).astype(np.int64)]
    lab = srgb_to_lab(px)
    pal = srgb_to_lab(np.asarray(palette, dtype=np.float64))
    dist = np.sqrt(((lab[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2))  # (N, K)
    best = dist[:, chosen].min(axis=1) if chosen else np.full(len(px), np.inf)
    while len(chosen) < n:
        cand = [i for i in range(k) if i not in chosen]
        costs = [np.minimum(best, dist[:, i]).sum() for i in cand]
        pick = cand[int(np.argmin(costs))]
        chosen.append(pick)
        best = np.minimum(best, dist[:, pick])
    return sorted(chosen)


def adaptive_palette(img: Image.Image, n: int, extra: Sequence[Sequence[int]] = ()) -> list[RGB]:
    """Median-cut palette of ``n`` colours for free-colour (hex input) mode.

    ``extra`` colours (e.g. the background) are always included.
    """
    n = max(1, int(n))
    q = img.convert("RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw = q.getpalette()[: 3 * n]
    used = sorted(set(np.asarray(q).ravel().tolist()))
    out: list[RGB] = [tuple(int(v) for v in extra_c[:3]) for extra_c in extra]  # type: ignore[misc]
    for i in used:
        c = (raw[3 * i], raw[3 * i + 1], raw[3 * i + 2])
        if c not in out:
            out.append(c)
    return out


def kmeans_palette(img: Image.Image | np.ndarray, n: int, extra: Sequence[Sequence[int]] = (),
                   iters: int = 12, sample: int = 60000, seed: int = 0) -> list[RGB]:
    """Palette of up to ``n`` colours fitted to the picture with k-means in Lab.

    Gives visibly closer results than median cut for photos. ``extra``
    colours (e.g. the background) are always included.
    """
    rgb = np.asarray(img.convert("RGB") if isinstance(img, Image.Image) else img, dtype=np.float64)
    px = rgb.reshape(-1, 3)
    rng = np.random.default_rng(seed)
    if len(px) > sample:
        px = px[rng.choice(len(px), sample, replace=False)]
    lab = srgb_to_lab(px)
    n = max(1, min(int(n), len(np.unique(px, axis=0))))
    # k-means++ seeding
    cent = np.empty((n, 3))
    cent[0] = lab[rng.integers(len(lab))]
    d = ((lab - cent[0]) ** 2).sum(axis=1)
    for j in range(1, n):
        cent[j] = lab[rng.choice(len(lab), p=d / d.sum())] if d.sum() > 0 else lab[rng.integers(len(lab))]
        d = np.minimum(d, ((lab - cent[j]) ** 2).sum(axis=1))
    assign = np.zeros(len(lab), dtype=np.int64)
    for _ in range(iters):
        assign = ((lab[:, None, :] - cent[None]) ** 2).sum(axis=2).argmin(axis=1)
        sums = np.zeros_like(cent)
        np.add.at(sums, assign, lab)
        cnt = np.bincount(assign, minlength=n)[:, None]
        cent = np.where(cnt > 0, sums / np.maximum(cnt, 1), cent)
    out: list[RGB] = [tuple(int(v) for v in c[:3]) for c in extra]  # type: ignore[misc]
    for j in range(n):
        m = assign == j
        if m.any():
            c = tuple(int(round(v)) for v in px[m].mean(axis=0))
            if c not in out:
                out.append(c)  # type: ignore[arg-type]
    return out


def despeckle(indices: np.ndarray, passes: int = 1) -> np.ndarray:
    """Replace isolated cells by the dominant colour of their 3x3 neighbourhood.

    Removes single-pixel noise that would cost a separate mouse press each,
    with almost no visible change.
    """
    idx = np.asarray(indices, dtype=np.int32)
    if passes <= 0 or idx.size == 0:
        return idx
    k = int(idx.max()) + 1
    h, w = idx.shape
    for _ in range(passes):
        onehot = np.zeros((k, h, w), dtype=np.int8)
        np.put_along_axis(onehot, idx[None], 1, axis=0)
        pad = np.pad(onehot, ((0, 0), (1, 1), (1, 1)))
        cnt = sum(pad[:, 1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        own = np.take_along_axis(cnt, idx[None], axis=0)[0]
        best = cnt.argmax(axis=0)
        change = (own <= 2) & (cnt.max(axis=0) >= 5)
        if not change.any():
            break
        idx = np.where(change, best, idx).astype(np.int32)
    return idx


# ---------------------------------------------------------------- pipeline

@dataclass
class ImageOptions:
    fit: str = "pad"
    background: RGB = (255, 255, 255)
    alpha_threshold: int = 0
    dither: bool = False
    max_colors: int = 0          # 0 = whole palette
    resample: str = "lanczos"    # lanczos | box | nearest
    despeckle: int = 0           # passes of isolated-pixel cleanup (0 = off)


_RESAMPLE = {
    "lanczos": Image.Resampling.LANCZOS,
    "box": Image.Resampling.BOX,
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
}


@dataclass
class PreparedImage:
    indices: np.ndarray                 # (rows, cols) palette indices
    palette: list[RGB]                  # full palette, indices refer to it
    used: list[int]                     # palette indices allowed by the colour limit
    fitted: Image.Image                 # RGB image before quantization (cols x rows)

    @property
    def cols(self) -> int:
        return int(self.indices.shape[1])

    @property
    def rows(self) -> int:
        return int(self.indices.shape[0])

    def to_image(self) -> Image.Image:
        return indices_to_image(self.indices, self.palette)

    def preview(self, cell_px: int = 4) -> Image.Image:
        img = self.to_image()
        return img.resize((self.cols * cell_px, self.rows * cell_px), Image.Resampling.NEAREST)


def indices_to_image(indices: np.ndarray, palette: Sequence[Sequence[int]],
                     unknown: RGB = (0, 0, 0)) -> Image.Image:
    pal = np.array(list(palette) + [unknown], dtype=np.uint8)
    idx = np.where(indices < 0, len(pal) - 1, indices)
    return Image.fromarray(pal[idx], "RGB")


def background_index(palette: Sequence[Sequence[int]], background: RGB) -> int:
    return int(nearest_palette(np.array([[background]], dtype=np.float64),
                               np.asarray(palette, dtype=np.float64))[0, 0])


def prepare_image(img: Image.Image | str | Path, grid: tuple[int, int],
                  palette: Sequence[Sequence[int]], opts: ImageOptions | None = None) -> PreparedImage:
    """Full pipeline: load -> fit to (cols, rows) -> limit colours -> quantize."""
    opts = opts or ImageOptions()
    if not isinstance(img, Image.Image):
        img = Image.open(img)
        img.load()
    pal = np.asarray(palette, dtype=np.float64)
    if pal.ndim != 2 or pal.shape[1] != 3 or len(pal) == 0:
        raise ValueError("palette must be a non-empty list of RGB triples")
    fitted = fit_image(img, grid, opts.fit, opts.background, opts.alpha_threshold,
                       _RESAMPLE.get(opts.resample, Image.Resampling.LANCZOS))
    rgb = np.asarray(fitted, dtype=np.float64)
    bg = background_index(pal, opts.background)
    used = choose_colors(rgb, pal, opts.max_colors, required=[bg])
    sub = pal[used]
    idx_sub = quantize(rgb, sub, dither=opts.dither)
    if opts.despeckle:
        idx_sub = despeckle(idx_sub, opts.despeckle)
    indices = np.asarray(used, dtype=np.int32)[idx_sub]
    return PreparedImage(indices=indices, palette=[tuple(int(v) for v in c) for c in pal],
                         used=used, fitted=fitted)
