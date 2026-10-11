"""Regenerate the README images in docs/ from a procedural sample picture.

    python scripts/make_docs.py

Everything is drawn here, so the images carry no third-party artwork.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signbrush.config import load_default  # noqa: E402
from signbrush.dryrun import render_plan, save_gif  # noqa: E402
from signbrush.pipeline import build_job  # noqa: E402

DOCS = ROOT / "docs"
FONT = ROOT / "signbrush" / "gui" / "fonts" / "Onest.ttf"


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sample(w: int = 800, h: int = 400) -> Image.Image:
    """Sunset over mountains and a lake, with a few pines."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    horizon = int(h * 0.62)
    top, mid, low = (38, 52, 120), (233, 120, 92), (252, 205, 120)
    for y in range(horizon):
        t = y / horizon
        c = _lerp(top, mid, t / 0.7) if t < 0.7 else _lerp(mid, low, (t - 0.7) / 0.3)
        for x in range(w):
            px[x, y] = c
    d = ImageDraw.Draw(img)
    sx, sy, r = int(w * 0.66), int(horizon * 0.72), int(h * 0.16)
    d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 226, 140))
    rng = np.random.default_rng(7)

    def ridge(base, amp, color, seed):
        g = np.random.default_rng(seed)
        xs = np.linspace(0, w, 9)
        ys = base - g.uniform(0.3, 1.0, len(xs)) * amp
        pts = [(0, horizon)] + [(float(x), float(y)) for x, y in zip(xs, ys)] + [(w, horizon)]
        d.polygon(pts, fill=color)

    ridge(horizon - 20, h * 0.30, (122, 88, 120), 3)
    ridge(horizon, h * 0.22, (72, 58, 92), 5)
    # lake with a soft reflection of the sky
    for y in range(horizon, h):
        t = (y - horizon) / (h - horizon)
        c = _lerp((206, 116, 104), (34, 44, 88), t)
        for x in range(w):
            px[x, y] = c
    d.ellipse((sx - r * 0.9, 2 * horizon - sy - r * 0.25, sx + r * 0.9, 2 * horizon - sy + r * 0.25),
              fill=(250, 196, 128))
    for _ in range(5):
        y = int(rng.uniform(horizon + 8, h - 10))
        x = int(rng.uniform(0, w - 160))
        d.line((x, y, x + int(rng.uniform(60, 160)), y), fill=(240, 170, 130), width=2)
    # pines on the left shore
    for i, x in enumerate(range(20, 230, 34)):
        th = int(h * (0.20 + 0.08 * ((i * 37) % 5) / 4))
        base = horizon + 6
        d.polygon([(x, base - th), (x - th * 0.22, base), (x + th * 0.22, base)], fill=(22, 34, 36))
    return img.filter(ImageFilter.SMOOTH)


def label(img: Image.Image, text: str) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + 34), (13, 19, 16))
    out.paste(img, (0, 34))
    font = ImageFont.truetype(str(FONT), 18) if FONT.exists() else ImageFont.load_default()
    ImageDraw.Draw(out).text((10, 7), text, fill=(231, 238, 232), font=font)
    return out


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    src = sample()
    src.save(DOCS / "sample.png")
    cfg = load_default()
    s = cfg.settings
    s.sign_type = "sign.large.wood"
    s.color_mode = "hex"
    renders = {}
    for algo in ("pixels", "hybrid", "shapes"):
        s.algorithm = algo
        job = build_job(src, cfg)
        renders[algo] = render_plan(job.plan, scale=2.0, blank=job.sign.blank)
        print(algo, job.plan.summary())
        if algo == "hybrid":
            renders[algo].save(DOCS / "preview_hex.png")
            save_gif(job.plan, DOCS / "demo.gif", scale=2.0, blank=job.sign.blank)
    w, h = renders["hybrid"].size
    renders = {k: v.resize((w, h), Image.Resampling.LANCZOS) for k, v in renders.items()}
    tiles = [label(src.resize((w, h), Image.Resampling.LANCZOS), "Source"),
             label(renders["hybrid"], "Hybrid (default)"),
             label(renders["pixels"], "Pixels"),
             label(renders["shapes"], "Strokes only")]
    gap = 12
    th = tiles[0].height
    sheet = Image.new("RGB", (2 * w + 3 * gap, 2 * th + 3 * gap), (10, 15, 12))
    for i, t in enumerate(tiles):
        sheet.paste(t, (gap + (i % 2) * (w + gap), gap + (i // 2) * (th + gap)))
    sheet.save(DOCS / "compare.png")
    print("written to", DOCS)


if __name__ == "__main__":
    main()
