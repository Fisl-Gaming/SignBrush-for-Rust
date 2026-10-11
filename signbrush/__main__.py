"""Entry point.

    signbrush                      start the GUI
    signbrush dryrun IMAGE ...     plan + render without touching the mouse
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _dryrun(args: argparse.Namespace) -> int:
    from PIL import Image

    from .config import load_config, load_default
    from .dryrun import render_plan, save_gif
    from .pipeline import build_job
    from .planner import format_duration

    cfg = load_config(args.config) if args.config else load_default()
    if args.profile:
        cfg.active_profile = args.profile
    s = cfg.settings
    for name in ("sign_type", "detail", "fit", "brush_shape", "color_mode", "fill_size", "algorithm",
                 "shape_count"):
        v = getattr(args, name)
        if v is not None:
            setattr(s, name, v)
    if args.dither:
        s.dither = True
    if args.colors is not None:
        s.max_colors = args.colors
    last = [-1]

    def progress(stage, frac):
        if int(frac * 10) != last[0]:
            last[0] = int(frac * 10)
            print(f"  generating {stage}: {frac * 100:.0f}%")

    job = build_job(args.image, cfg, progress=progress)
    g = job.geometry
    print(f"sign {job.sign.key} {g.texture[0]}x{g.texture[1]}, algorithm {job.algorithm}, "
          f"cell {g.cell_tex} tex px -> grid {g.cols}x{g.rows}, "
          f"colours used {job.colors_used()}/{len(job.plan.palette)}")
    print("plan:", job.plan.summary())
    print("estimated time:", format_duration(job.estimate_s))
    out = Path(args.out or Path(args.image).with_suffix(".plan.png"))
    render_plan(job.plan, scale=args.scale, blank=job.sign.blank).save(out)
    k = max(1, round(args.scale))
    job.preview.resize((g.cols * k, g.rows * k), Image.Resampling.NEAREST).save(out.with_suffix(".target.png"))
    print("rendered:", out)
    if args.gif:
        print("gif:", save_gif(job.plan, args.gif, scale=args.scale, blank=job.sign.blank))
    return 0


def main(argv: list[str] | None = None) -> int:
    import os
    for name in ("stdout", "stderr"):   # windowed .exe has no console streams
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    ap = argparse.ArgumentParser(prog="signbrush", description="SignBrush for Rust - paints any picture on Rust signs")
    ap.add_argument("--config", help="path to config.json")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("dryrun", help="plan and render without mouse control")
    d.add_argument("image")
    d.add_argument("-o", "--out", help="output PNG (default: IMAGE.plan.png)")
    d.add_argument("--gif", help="also write an animated GIF of the drawing order")
    d.add_argument("--profile")
    d.add_argument("--sign", dest="sign_type", help="sign type key, e.g. sign.medium.wood")
    d.add_argument("--detail", type=int, help="texture px per cell (fine brush size)")
    d.add_argument("--fill-size", dest="fill_size", type=int, help="big brush, texture px (0 = off)")
    d.add_argument("--shape", dest="brush_shape", choices=["square", "circle"])
    d.add_argument("--mode", dest="color_mode", choices=["palette", "hex"])
    d.add_argument("--algorithm", choices=["hybrid", "pixels", "shapes"])
    d.add_argument("--shapes", dest="shape_count", type=int, help="number of strokes in shape mode")
    d.add_argument("--scale", type=float, default=2.0, help="render px per cell")
    d.add_argument("--dither", action="store_true")
    d.add_argument("--colors", type=int)
    d.add_argument("--fit", choices=["pad", "crop", "stretch"])
    args = ap.parse_args(argv)
    if args.cmd == "dryrun":
        return _dryrun(args)
    from .gui import run_gui
    return run_gui(args.config)


if __name__ == "__main__":
    sys.exit(main())
