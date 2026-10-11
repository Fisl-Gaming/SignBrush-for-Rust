"""Calibration logic (GUI-independent).

The user opens a sign in the game, presses the capture hotkey, and Sign
Painter freezes a screenshot. All marking happens on that frozen picture in
our own window - no click ever reaches the game during calibration.

Steps are rectangles (drag), lines (drag from one end to the other) or
points (click). Results are applied to a :class:`~signbrush.config.Profile`;
palette colours are sampled from the same screenshot.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Control, PaletteColor, Profile
from .imaging import to_hex
from .screen import sample

XY = tuple[int, int]


@dataclass(frozen=True)
class Step:
    key: str
    kind: str            # rect | line | point
    optional: bool
    ru: str
    en: str


STEPS: list[Step] = [
    Step("canvas", "rect", False,
         "Обведите рамкой область рисования (только сам холст, без рамки таблички).",
         "Drag a rectangle around the drawing area (the canvas only, without the frame)."),
    Step("hex_field", "point", True,
         "Кликните в поле HEX-кода цвета (под образцом цвета, «#FFFFFF»).",
         "Click the HEX colour code field (under the colour preview, \"#FFFFFF\")."),
    Step("picker_sv", "rect", True,
         "Обведите квадрат выбора цвета (белый слева сверху, чёрный снизу) — для режима «пипетка».",
         "Drag around the saturation/value square (white top-left, black bottom) - for picker mode."),
    Step("picker_hue", "line", True,
         "Полоса оттенков: протяните от ВЕРХНЕГО до НИЖНЕГО края по её центру.",
         "Hue bar: drag from its TOP to its BOTTOM end along the middle."),
    Step("size_textbox", "point", True,
         "Кликните по числу размера кисти (справа от ползунка «РАЗМЕР»).",
         "Click the brush size number (right of the SIZE slider)."),
    Step("size_slider", "line", True,
         "Ползунок размера: от левого края до правого (если числовое поле не работает).",
         "Size slider: from its left end to its right end (if the number field does not work)."),
    Step("opacity_textbox", "point", True,
         "Кликните по числу прозрачности (справа от ползунка «ПРОЗРАЧНОСТЬ»). Нужно для мазков и гибрида.",
         "Click the opacity number (right of the OPACITY slider). Needed for strokes and hybrid."),
    Step("opacity_slider", "line", True,
         "Ползунок прозрачности: от левого края до правого.",
         "Opacity slider: from its left end to its right end."),
    Step("spacing_textbox", "point", True,
         "Кликните по числу интервала кисти (справа от ползунка «ИНТЕРВАЛ»).",
         "Click the brush spacing number (right of the SPACING slider)."),
    Step("brush_square", "point", True,
         "Кликните по квадратной кисти.",
         "Click the square brush."),
    Step("brush_circle", "point", True,
         "Кликните по жёсткой круглой кисти (белый круг с чёткими краями).",
         "Click the hard round brush (white circle with sharp edges)."),
    Step("palette", "line", True,
         "Избранные цвета (необязательно): от центра первого образца до центра последнего.",
         "Favourite colours (optional): from the centre of the first swatch to the centre of the last."),
    Step("save", "point", True,
         "Кнопка сохранения (необязательно; во время рисования по умолчанию не нажимается).",
         "Save button (optional; not pressed while painting by default)."),
    Step("focus", "point", True,
         "Кликните в пустое место панели справа — им программа забирает фокус. Не на холсте!",
         "Click an empty spot of the right panel used to focus the game. Not on the canvas!"),
]
STEP_BY_KEY = {s.key: s for s in STEPS}


def normalize_rect(a: XY, b: XY) -> tuple[int, int, int, int]:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def apply_results(profile: Profile, results: dict[str, tuple], screenshot: np.ndarray,
                  origin: XY = (0, 0), screen_size: XY | None = None,
                  grid: tuple[int, int] | None = None, sample_colors: bool = True) -> list[str]:
    """Write calibration ``results`` (screenshot coordinates) into ``profile``.

    ``origin`` is the desktop position of the screenshot's top-left pixel.
    Returns warnings for the user.
    """
    ox, oy = origin
    to_abs = lambda p: (int(p[0]) + ox, int(p[1]) + oy)
    warnings: list[str] = []

    if "canvas" in results:
        a, b = results["canvas"]
        x0, y0, x1, y1 = normalize_rect(a, b)
        if x1 - x0 < 20 or y1 - y0 < 20:
            raise ValueError("canvas rectangle is too small")
        profile.canvas = (x0 + ox, y0 + oy, x1 + ox, y1 + oy)

    if "palette" in results:
        first, last = results["palette"]
        pg = profile.palette_grid
        if grid:
            pg.cols, pg.rows = grid
        pg.first, pg.last = to_abs(first), to_abs(last)
        n = pg.cols * pg.rows
        if len(profile.palette) != n:
            profile.palette = [PaletteColor(f"C{i + 1:02d}", (0, 0, 0)) for i in range(n)]
        for c in profile.palette:
            c.pos = None
        if sample_colors:
            seen: dict[tuple, int] = {}
            for i, (x, y) in enumerate(pg.positions()):
                rgb = sample(screenshot, x - ox, y - oy, radius=2)
                profile.palette[i].rgb = rgb
                seen.setdefault(rgb, i)
            if len(seen) < n * 0.75:
                warnings.append(f"only {len(seen)} distinct colours of {n} sampled - check the palette grid")

    if "picker_sv" in results:
        a, b = results["picker_sv"]
        x0, y0, x1, y1 = normalize_rect(a, b)
        profile.picker_sv = (x0 + ox, y0 + oy, x1 + ox, y1 + oy)
    if "picker_hue" in results:
        a, b = results["picker_hue"]
        profile.picker_hue = (to_abs(a), to_abs(b))
        profile.picker_hue_lut = sample_hue_bar(screenshot, a, b)
        if len(profile.picker_hue_lut) < 8:
            warnings.append("hue bar looks grey - check the hue bar line")

    for name in ("size", "opacity", "spacing"):
        ctl = profile.controls.setdefault(name, Control())
        if f"{name}_slider" in results:
            a, b = results[f"{name}_slider"]
            ctl.slider_min, ctl.slider_max = to_abs(a), to_abs(b)
        if f"{name}_textbox" in results:
            ctl.textbox = to_abs(results[f"{name}_textbox"][0])

    for btn in ("brush_square", "brush_circle", "save", "hex_field", "focus"):
        if btn in results:
            profile.buttons[btn] = to_abs(results[btn][0])

    focus = profile.buttons.get("focus")
    if focus and profile.canvas:
        x0, y0, x1, y1 = profile.canvas
        if x0 <= focus[0] <= x1 and y0 <= focus[1] <= y1:
            profile.buttons["focus"] = None
            warnings.append("focus point was on the canvas and has been removed")
    if screen_size:
        profile.screen = screen_size
    if not profile.controls["size"].usable:
        warnings.append("brush size control is not calibrated: brushes cannot be switched")
    return warnings


def sample_hue_bar(img: np.ndarray, a: XY, b: XY, n: int = 96) -> list[tuple[float, float]]:
    """(position 0..1 along the bar, hue in degrees) for saturated samples of the hue bar."""
    import colorsys

    out: list[tuple[float, float]] = []
    for i in range(n):
        t = i / (n - 1)
        x = round(a[0] + (b[0] - a[0]) * t)
        y = round(a[1] + (b[1] - a[1]) * t)
        r, g, bl = sample(img, x, y, radius=1)
        h, sat, val = colorsys.rgb_to_hsv(r / 255, g / 255, bl / 255)
        if sat > 0.5 and val > 0.4:
            out.append((round(t, 4), round(h * 360, 2)))
    return out


def palette_preview(profile: Profile) -> list[tuple[XY | None, str]]:
    return [(p, to_hex(c.rgb)) for p, c in zip(profile.swatch_positions(), profile.palette)]


# ---------------------------------------------------------------- optional auto-detection

def detect_canvas(img: np.ndarray, aspect: float | None = None,
                  min_area: float = 0.03) -> tuple[int, int, int, int] | None:
    """Find the sign canvas on a screenshot: the largest axis-aligned rectangle
    (optionally with the given width/height ``aspect``). Returns x0, y0, x1, y1."""
    import cv2

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 30, 90)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best, best_score = None, 0.0
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < min_area * w * h or cw >= w - 2 or ch >= h - 2:
            continue
        fill = cv2.contourArea(cv2.convexHull(c)) / area
        if fill < 0.9:
            continue
        score = area * fill
        if aspect:
            err = abs((cw / ch) / aspect - 1)
            if err > 0.12:
                continue
            score *= 1 - err
        if score > best_score:
            best, best_score = (x, y, x + cw - 1, y + ch - 1), score
    if best is None:
        return None
    # the contour hugs the border line: shrink to the inside
    x0, y0, x1, y1 = best
    return x0 + 2, y0 + 2, x1 - 2, y1 - 2
