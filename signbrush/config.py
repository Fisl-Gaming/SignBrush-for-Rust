"""config.json: sign types, calibration profiles (one per screen setup) and settings.

Everything game-specific lives here, not in code: the palette, sign texture
sizes, positions of the editor controls. Defaults ship in
``default_config.json`` next to this module and are copied on first start.

Geometry model
--------------
Every sign has a fixed texture size (e.g. 512x256). The editor shows that
texture scaled into the on-screen ``canvas`` rectangle. Brush sizes are in
texture pixels, so the drawing grid is ``texture / detail`` and is independent
of the screen resolution.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any

from .imaging import parse_color, to_hex, RGB, ImageOptions
from .planner import PlanOptions, Timing
from .i18n import tr

DEFAULT_CONFIG_FILE = Path(__file__).with_name("default_config.json")
XY = tuple[int, int]
Rect = tuple[int, int, int, int]


def app_dir() -> Path:
    """Folder next to the .exe (portable) or the current folder when run from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_config_path() -> Path:
    p = app_dir() / "config.json"
    if p.exists() or os.access(p.parent, os.W_OK):
        return p
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "SignBrush" / "config.json"


def _xy(v) -> XY | None:
    return None if v is None else (int(round(v[0])), int(round(v[1])))


def _xy_list(v: XY | None):
    return list(v) if v else None


# ---------------------------------------------------------------- pieces

@dataclass
class SignType:
    key: str
    label: str
    size: tuple[int, int]          # texture width, height
    blank: RGB = (168, 147, 131)   # colour of an unpainted sign

    @classmethod
    def from_dict(cls, key: str, d: dict) -> "SignType":
        return cls(key, d.get("label", key), (int(d["size"][0]), int(d["size"][1])),
                   parse_color(d.get("blank", "#A89383")))

    def to_dict(self) -> dict:
        return {"label": self.label, "size": list(self.size), "blank": to_hex(self.blank)}


@dataclass
class PaletteColor:
    name: str
    rgb: RGB                         # colour as it looks on screen (sampled in calibration)
    pos: XY | None = None            # explicit swatch position (otherwise from the grid)

    @classmethod
    def from_dict(cls, d: dict) -> "PaletteColor":
        return cls(str(d.get("name", "")), parse_color(d["rgb"]), _xy(d.get("pos")))

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"name": self.name, "rgb": to_hex(self.rgb)}
        if self.pos:
            d["pos"] = list(self.pos)
        return d


@dataclass
class PaletteGrid:
    """Swatch grid: centres of the first (top-left) and last (bottom-right) swatch."""
    first: XY | None = None
    last: XY | None = None
    cols: int = 4
    rows: int = 16

    def positions(self) -> list[XY]:
        """Row-major centres of all swatches."""
        if not (self.first and self.last):
            return []
        (x0, y0), (x1, y1) = self.first, self.last
        dx = (x1 - x0) / max(1, self.cols - 1)
        dy = (y1 - y0) / max(1, self.rows - 1)
        return [(round(x0 + c * dx), round(y0 + r * dy)) for r in range(self.rows) for c in range(self.cols)]

    @classmethod
    def from_dict(cls, d: dict | None) -> "PaletteGrid":
        d = d or {}
        return cls(_xy(d.get("first")), _xy(d.get("last")), int(d.get("cols", 4)), int(d.get("rows", 16)))

    def to_dict(self) -> dict:
        return {"first": _xy_list(self.first), "last": _xy_list(self.last), "cols": self.cols, "rows": self.rows}


@dataclass
class Control:
    """A value control of the editor: slider (two end points) and/or a text box."""
    slider_min: XY | None = None
    slider_max: XY | None = None
    range: tuple[float, float] = (0.0, 1.0)
    textbox: XY | None = None

    @property
    def usable(self) -> bool:
        return bool(self.textbox or (self.slider_min and self.slider_max))

    def slider_point(self, value: float) -> XY:
        assert self.slider_min and self.slider_max
        lo, hi = self.range
        f = 0.0 if hi == lo else min(1.0, max(0.0, (value - lo) / (hi - lo)))
        (x0, y0), (x1, y1) = self.slider_min, self.slider_max
        return round(x0 + (x1 - x0) * f), round(y0 + (y1 - y0) * f)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Control":
        d = d or {}
        rng = d.get("range", [0, 1])
        return cls(_xy(d.get("slider_min")), _xy(d.get("slider_max")),
                   (float(rng[0]), float(rng[1])), _xy(d.get("textbox")))

    def to_dict(self) -> dict:
        return {"slider_min": _xy_list(self.slider_min), "slider_max": _xy_list(self.slider_max),
                "range": list(self.range), "textbox": _xy_list(self.textbox)}


BUTTONS = ("brush_square", "brush_circle", "save", "focus", "hex_field")
CONTROLS = ("size", "opacity", "spacing")


@dataclass
class Profile:
    name: str
    description: str = ""
    screen: XY | None = None
    canvas: Rect | None = None                 # x0, y0, x1, y1 on screen
    palette_grid: PaletteGrid = field(default_factory=PaletteGrid)
    palette: list[PaletteColor] = field(default_factory=list)
    controls: dict[str, Control] = field(default_factory=dict)
    buttons: dict[str, XY | None] = field(default_factory=dict)
    picker_sv: Rect | None = None              # saturation/value square of the colour picker
    picker_hue: tuple[XY, XY] | None = None    # hue bar: first and last point
    picker_hue_lut: list[tuple[float, float]] = field(default_factory=list)   # (position 0..1, hue deg)
    size_scale: float = 1.0      # brush diameter in texture px per unit of the size control
    size_measured: bool = False  # size_scale comes from "Measure brush" (not the default guess)
    opacity: float = 1.0         # value set before painting
    spacing: float | None = None  # brush spacing value set before painting (None = leave)

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "Profile":
        cv = d.get("canvas")
        return cls(
            name=name,
            description=d.get("description", ""),
            screen=_xy(d.get("screen")),
            canvas=tuple(int(v) for v in cv) if cv else None,  # type: ignore[arg-type]
            palette_grid=PaletteGrid.from_dict(d.get("palette_grid")),
            palette=[PaletteColor.from_dict(c) for c in d.get("palette", [])],
            controls={k: Control.from_dict(d.get("controls", {}).get(k)) for k in CONTROLS},
            buttons={k: _xy(d.get("buttons", {}).get(k)) for k in BUTTONS},
            picker_sv=tuple(int(v) for v in d["picker_sv"]) if d.get("picker_sv") else None,  # type: ignore[arg-type]
            picker_hue=(_xy(d["picker_hue"][0]), _xy(d["picker_hue"][1])) if d.get("picker_hue") else None,  # type: ignore[arg-type]
            picker_hue_lut=[(float(a), float(b)) for a, b in d.get("picker_hue_lut", [])],
            size_scale=float(d.get("size_scale", 1.0)),
            size_measured=bool(d.get("size_measured", False)),
            opacity=float(d.get("opacity", 1.0)),
            spacing=None if d.get("spacing") is None else float(d["spacing"]),
        )

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "screen": _xy_list(self.screen),
            "canvas": list(self.canvas) if self.canvas else None,
            "palette_grid": self.palette_grid.to_dict(),
            "palette": [c.to_dict() for c in self.palette],
            "controls": {k: c.to_dict() for k, c in self.controls.items()},
            "buttons": {k: _xy_list(v) for k, v in self.buttons.items()},
            "picker_sv": list(self.picker_sv) if self.picker_sv else None,
            "picker_hue": [list(self.picker_hue[0]), list(self.picker_hue[1])] if self.picker_hue else None,
            "picker_hue_lut": [list(p) for p in self.picker_hue_lut],
            "size_scale": self.size_scale,
            "size_measured": self.size_measured,
            "opacity": self.opacity,
            "spacing": self.spacing,
        }

    # -- derived -------------------------------------------------------------
    @property
    def canvas_size(self) -> tuple[int, int] | None:
        if not self.canvas:
            return None
        x0, y0, x1, y1 = self.canvas
        return x1 - x0 + 1, y1 - y0 + 1

    def palette_rgb(self) -> list[RGB]:
        return [c.rgb for c in self.palette]

    def swatch_positions(self) -> list[XY | None]:
        grid = self.palette_grid.positions()
        out: list[XY | None] = []
        for i, c in enumerate(self.palette):
            out.append(c.pos or (grid[i] if i < len(grid) else None))
        return out

    def size_value(self, diameter_tex: float) -> float:
        """Value for the size control that gives a brush of ``diameter_tex`` texture px."""
        return diameter_tex / max(self.size_scale, 1e-6)

    def missing_calibration(self, color_mode: str = "palette", algorithm: str = "pixels") -> list[str]:
        miss = []
        if algorithm in ("shapes", "hybrid") and not self.controls.get("opacity", Control()).usable:
            miss.append("opacity")
        if not self.canvas:
            miss.append("canvas")
        if color_mode == "hex":
            if not self.buttons.get("hex_field"):
                miss.append("hex_field")
        elif color_mode == "picker":
            if not (self.picker_sv and self.picker_hue):
                miss.append("picker")
        elif not self.palette or any(p is None for p in self.swatch_positions()):
            miss.append("palette")
        if not self.controls.get("size", Control()).usable:
            miss.append("size")
        typing = color_mode == "hex" or any(c.textbox for c in self.controls.values())
        if typing and not self.buttons.get("focus"):
            miss.append("focus")
        return miss


@dataclass
class Settings:
    algorithm: str = "hybrid"    # hybrid (strokes base + pixel touch-up) | pixels (cell-exact) | shapes
    sign_type: str = "auto"
    custom_size: str = "512x256"
    detail: int = 2              # texture px per drawing cell (fine brush size)
    fill_size: int = 16          # big brush for background / large areas, texture px (0 = off)
    brush_shape: str = "square"  # square | circle
    color_mode: str = "hex"      # hex (type the code) | picker (2 clicks: hue bar + SV square) | palette (swatches)
    fit: str = "pad"
    background: str = "#FFFFFF"
    transparent: str = "fill"    # fill: transparent areas / margins get the background colour; skip: not painted
    alpha_threshold: int = 0
    dither: bool = False
    max_colors: int = 0
    resample: str = "lanczos"
    despeckle: int = 1           # isolated-pixel cleanup passes (fewer presses, ~no visible change)
    base_fill: bool = True
    coarse: bool = True
    max_bridge: int = 12
    line_mode: str = "jump"      # jump (one move per vertex) | drag (interpolated moves) | shift (shift-line)
    field_commit: str = "click"  # how typed values are applied: click (focus point) | enter | tab
                                 # (Enter opens the chat in Rust, so it is not the default)
    verify_passes: int = 2
    verify_tolerance: float = 0.002   # share of wrong cells that is accepted
    verify_de: float = 10.0           # a cell is wrong when its colour differs from the expected by more (dE)
    game_fps: float = 60         # timing in game frames (0 = use the *_ms delays below)
    frames_per_action: float = 2.0  # waits per mouse action, in frames (FPS drops while painting)
    min_frames: float = 1.0         # lower bound for the wait, in frames ("Speed test" may lower it)
    gap_frames: float = 3.0         # min frames between releasing the button and the next press, any speed:
                                    # if the game misses the release (a slow frame), it draws a "tail" line
    action_delay_ms: float = 20
    move_delay_ms: float = 15
    draw_step_px: float = 6
    draw_step_delay_ms: float = 4
    click_hold_ms: float = 20
    color_switch_ms: float = 15     # extra settle time after a colour change
    brush_switch_ms: float = 30     # extra settle time after a size / opacity change
    speed: float = 1.0           # global multiplier: 2.0 = twice as fast (delays halved)
    save_every: int = 0          # strokes between saves (0 = only at the end)
    save_method: str = "off"     # off | ctrl+s | button  ("Save changes" may close the editor!)
    mouse_guard_px: int = 12     # user moved the mouse -> pause (0 = off)
    window_title: str = "Rust"   # pause when the foreground window title lacks this ("" = off)
    max_cells: int = 600000
    brush_cover: float = 1.2     # opaque (square) brushes are this much bigger than a cell: no hairline gaps
    countdown_s: int = 3
    confirm_start: bool = True   # show the "Начать рисование?" dialog
    language: str = ""           # ru | en; "" = system language
    shape_count: int = 6000
    shape_sizes: str = "3,6,12,25,50,100"          # circle diameters, texture px
    shape_alphas: str = "0.09,0.19,0.39,0.75,0.9,1.0"
    shape_work_size: int = 256                     # generator resolution (longest side)
    hybrid_shapes: int = 1000    # translucent strokes laid down before the pixel touch-up
    fix_tolerance: float = 8.0   # touch-up repaints cells whose colour error (CIELAB dE) is above this

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        casts = {"int": int, "float": float, "str": str, "bool": bool}
        known = {f.name: casts[str(f.type)] for f in fields(cls)}
        s = cls()
        for k, v in (d or {}).items():
            if k in known:
                setattr(s, k, known[k](v))
        return s

    def image_options(self) -> ImageOptions:
        return ImageOptions(fit=self.fit, background=parse_color(self.background),
                            alpha_threshold=self.alpha_threshold, dither=self.dither,
                            max_colors=self.max_colors, resample=self.resample,
                            despeckle=0 if self.dither else self.despeckle)

    def plan_options(self) -> PlanOptions:
        return PlanOptions(base_fill=self.base_fill, coarse=self.coarse, max_bridge=self.max_bridge)

    def timing(self) -> Timing:
        """Delays. With ``game_fps`` every mouse action waits a whole number of game
        frames: the game samples the mouse once per frame, waiting longer is wasted."""
        k = 1.0 / max(self.speed, 0.05)
        ms = 0.001 * k
        common = dict(draw_step_px=self.draw_step_px, color_switch=self.color_switch_ms * ms,
                      brush_switch=self.brush_switch_ms * ms, line_mode=self.line_mode)
        if self.game_fps > 0:
            # never shorter than min_frames (1 frame unless the speed test proved less is fine):
            # shorter waits make the game miss mouse moves
            frame = max(self.frames_per_action * k, self.min_frames) / self.game_fps
            return Timing(action_delay=frame, move_delay=frame, draw_step_delay=frame,
                          click_hold=frame, release_gap=max(0.0, self.gap_frames) / self.game_fps, **common)
        return Timing(action_delay=self.action_delay_ms * ms, move_delay=self.move_delay_ms * ms,
                      draw_step_delay=self.draw_step_delay_ms * ms, click_hold=self.click_hold_ms * ms,
                      release_gap=0.0, **common)

    def shape_sizes_list(self) -> list[float]:
        return sorted(float(v) for v in self.shape_sizes.replace(";", ",").split(",") if v.strip())

    def shape_alphas_list(self) -> list[float]:
        return sorted(min(1.0, max(0.01, float(v)))
                      for v in self.shape_alphas.replace(";", ",").split(",") if v.strip())


@dataclass
class Config:
    profiles: dict[str, Profile]
    active_profile: str
    settings: Settings
    hotkeys: dict[str, str]
    sign_types: dict[str, SignType]
    path: Path | None = None

    @property
    def profile(self) -> Profile:
        if self.active_profile not in self.profiles:
            self.active_profile = next(iter(self.profiles))
        return self.profiles[self.active_profile]

    def sign(self, key: str | None = None) -> SignType:
        key = key or self.settings.sign_type
        if key == "auto":
            # unknown texture: keep the canvas aspect ratio, long side = 512 "texture px",
            # so the drawing resolution does not depend on how big the canvas looks on screen
            w, h = self.profile.canvas_size or (512, 512)
            k = 512 / max(w, h)
            return SignType("auto", tr('По холсту на экране'), (max(1, round(w * k)), max(1, round(h * k))),
                            (179, 171, 160))
        st = self.sign_types.get(key) or next(iter(self.sign_types.values()))
        if st.key == "custom":
            try:
                w, h = (int(v) for v in self.settings.custom_size.lower().split("x"))
                st = SignType(st.key, st.label, (w, h), st.blank)
            except ValueError:
                pass
        cs = self.profile.canvas_size
        if cs:
            # the editor shows the whole texture in the canvas, so the canvas aspect is the
            # texture aspect. Texture tables go stale between game updates: trust the screen and
            # keep only the resolution (long side) from the sign type.
            tw, th = st.size
            if abs((cs[0] / cs[1]) / (tw / th) - 1) > 0.03:
                long = max(tw, th)
                k = long / max(cs)
                st = SignType(st.key, st.label + tr(' (по холсту)'),
                              (max(1, round(cs[0] * k)), max(1, round(cs[1] * k))), st.blank)
        return st

    def add_profile(self, name: str, copy_from: str | None = None) -> Profile:
        if name in self.profiles:
            raise ValueError(f"profile {name!r} already exists")
        src = self.profiles.get(copy_from or self.active_profile)
        p = Profile.from_dict(name, copy.deepcopy(src.to_dict())) if src else Profile(name)
        self.profiles[name] = p
        return p

    @classmethod
    def from_dict(cls, d: dict, path: Path | None = None) -> "Config":
        defaults = json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
        profiles = {n: Profile.from_dict(n, p) for n, p in d.get("profiles", {}).items()}
        if not profiles:
            raise ValueError("config has no profiles")
        hotkeys = dict(defaults["hotkeys"])
        hotkeys.update({k: str(v).lower() for k, v in d.get("hotkeys", {}).items()})
        signs_raw = d.get("sign_types") or defaults["sign_types"]
        signs = {k: SignType.from_dict(k, v) for k, v in signs_raw.items()}
        return cls(profiles=profiles, active_profile=d.get("active_profile") or next(iter(profiles)),
                   settings=Settings.from_dict(d.get("settings", {})), hotkeys=hotkeys,
                   sign_types=signs, path=path)

    def to_dict(self) -> dict:
        return {
            "version": 2,
            "active_profile": self.active_profile,
            "hotkeys": dict(self.hotkeys),
            "sign_types": {k: s.to_dict() for k, s in self.sign_types.items()},
            "settings": asdict(self.settings),
            "profiles": {n: p.to_dict() for n, p in self.profiles.items()},
        }

    def save(self, path: Path | str | None = None) -> Path:
        p = Path(path or self.path or default_config_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        self.path = p
        return p


def load_default() -> Config:
    return Config.from_dict(json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")))


def load_config(path: Path | str | None = None) -> Config:
    """Load ``path`` (default: next to the app); create it from defaults if missing."""
    p = Path(path) if path else default_config_path()
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        if int(data.get("version", 1)) < 2:      # old layout: keep settings, reset profiles
            old = p.with_suffix(".v1.json")
            p.replace(old)
            cfg = load_default()
            cfg.save(p)
            return cfg
        cfg = Config.from_dict(data, path=p)
    else:
        cfg = load_default()
        cfg.save(p)
    return cfg
