"""Line icons (24x24, stroke 1.8) rendered from inline SVG in any colour."""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_STROKE = 'fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"'

# body of each icon; "F:" prefix = filled shape (fill="currentColor", no stroke)
ICONS: dict[str, str] = {
    "draw": '<path d="M18.5 3.5l2 2-8.5 8.5-3-3z"/><path d="M9 11c-2.6 0-4 1.6-4 4 0 1.6-.7 2.8-2 3.4 1.2.8 2.7 1.1 4 1.1 3 0 5-2 5-5"/>',
    "preview": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "resume": '<path d="M5 4.5v15"/><path d="M9 4.5v15l11-7.5z" fill="currentColor" stroke="none"/>',
    "pause": 'F:<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "play": 'F:<path d="M7 4.5v15l12-7.5z"/>',
    "stop": 'F:<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "calibrate": '<circle cx="12" cy="12" r="8"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="1.3"/>',
    "snapshot": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "measure": '<path d="M3 16.5L16.5 3 21 7.5 7.5 21z"/><path d="M7 12.5l2 2M10 9.5l2 2M13 6.5l2 2"/>',
    "speed": '<path d="M4.5 18a8.5 8.5 0 1 1 15 0"/><path d="M12 13l4-4"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "sign": '<rect x="3" y="5" width="18" height="11" rx="1.5"/><path d="M9 16v4M15 16v4"/>',
    "profile": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "warning": '<path d="M12 3.5L2.5 20h19z"/><path d="M12 10v4.5M12 17.3v.2"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.6v.2"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.8-2.5 2.2-2.5 3.8M12 17.2v.3"/>',
    "error": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.3v.2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M18 15l-6-6-6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "mouse": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v3"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}


def _svg(name: str, color: str, width: float = 1.8) -> bytes:
    body = ICONS[name]
    if body.startswith("F:"):
        attrs, body = 'fill="currentColor" stroke="none"', body[2:]
    else:
        attrs = _STROKE.format(w=width)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{body}</svg>'
    return svg.replace("currentColor", color).encode()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#E7EEE8", size: int = 16, dpr: float = 2.0, width: float = 1.8) -> QPixmap:
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color, width)))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#E7EEE8", size: int = 16, disabled: str | None = "#4E5B53") -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Active)
    if disabled:
        ic.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled)
    return ic


LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 34 34">'
    '<rect width="34" height="34" rx="8" fill="#16241A"/>'
    '<rect x="0.5" y="0.5" width="33" height="33" rx="7.5" fill="none" stroke="#86C04A" stroke-opacity="0.35"/>'
    '<rect x="6" y="7.5" width="22" height="14" rx="2.5" fill="none" stroke="#E7EEE8" stroke-width="2"/>'
    '<path d="M13 21.5v6M21 21.5v6" stroke="#E7EEE8" stroke-width="2" stroke-linecap="round"/>'
    '<path d="M9.6 17.6c2.8-.8 4-5.6 7.6-5.8 2.2-.1 2.5 2.3 4.4 2.1 1.2-.1 1.9-1.1 2.5-2.4" fill="none" '
    'stroke="#86C04A" stroke-width="2.8" stroke-linecap="round"/></svg>'
)


def logo(size: int = 34, dpr: float = 2.0) -> QPixmap:
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.encode())).render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 20, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo(sz, 1.0))
    return ic
