"""Screen capture through mss (read-only screenshots, nothing else)."""

from __future__ import annotations

import numpy as np

Rect = tuple[int, int, int, int]   # x0, y0, x1, y1 inclusive


def grab(rect: Rect | None = None) -> np.ndarray:
    """RGB uint8 array of ``rect`` (absolute desktop coords) or the whole virtual screen."""
    import mss
    with mss.mss() as sct:
        if rect is None:
            mon = sct.monitors[0]
            box = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        else:
            x0, y0, x1, y1 = normalize(rect)
            box = {"left": x0, "top": y0, "width": x1 - x0 + 1, "height": y1 - y0 + 1}
        shot = sct.grab(box)
        arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return arr[..., 2::-1].copy()   # BGRA -> RGB


def grab_monitor_at(pt: tuple[int, int]) -> tuple[np.ndarray, tuple[int, int], tuple[int, int]]:
    """Screenshot of the monitor containing desktop point ``pt``.

    Returns (RGB image, (left, top) of the monitor, (width, height)).
    """
    import mss
    with mss.mss() as sct:
        mons = sct.monitors[1:] or sct.monitors[:1]
        mon = next((m for m in mons if m["left"] <= pt[0] < m["left"] + m["width"]
                    and m["top"] <= pt[1] < m["top"] + m["height"]), mons[0])
    rect = (mon["left"], mon["top"], mon["left"] + mon["width"] - 1, mon["top"] + mon["height"] - 1)
    return grab(rect), (mon["left"], mon["top"]), (mon["width"], mon["height"])


def virtual_origin() -> tuple[int, int]:
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[0]
        return mon["left"], mon["top"]


def normalize(rect: Rect) -> Rect:
    x0, y0, x1, y1 = rect
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def sample(img: np.ndarray, x: int, y: int, radius: int = 2) -> tuple[int, int, int]:
    """Median colour of a small square around (x, y) in image coordinates."""
    h, w = img.shape[:2]
    patch = img[max(0, y - radius):min(h, y + radius + 1), max(0, x - radius):min(w, x + radius + 1)]
    m = np.median(patch.reshape(-1, 3), axis=0)
    return int(m[0]), int(m[1]), int(m[2])
