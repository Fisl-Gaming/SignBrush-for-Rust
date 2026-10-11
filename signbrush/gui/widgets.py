"""Widgets of the new interface (design «Sign Painter — интерфейс»)."""

from __future__ import annotations

import html
import time
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap,
                         QTextCursor)
from PyQt6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QTextEdit, QToolTip, QVBoxLayout, QWidget)

from . import icons, theme
from .help_texts import HELP
from .help_texts_en import HELP_EN
from ..i18n import language, tr

IMAGE_FILTER = "Картинки (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def pil_to_qimage(img: Image.Image) -> QImage:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, 4 * rgba.width, QImage.Format.Format_RGBA8888).copy()


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def icon_label(name: str, color: str, size: int = 16) -> QLabel:
    lb = QLabel()
    lb.setPixmap(icons.pixmap(name, color, size))
    lb.setFixedSize(size, size)
    return lb


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def button(text: str = "", kind: str | None = None, icon: str | None = None, icon_color: str | None = None,
           tip: str | None = None, size: int = 16) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon:
        col = icon_color or {"Primary": theme.ON_ACCENT, "PrimarySm": theme.ON_ACCENT, "Danger": "#1A0605",
                             "Ghost": theme.TEXT2, "Link": theme.ACCENT_TEXT, "Warn": "#1F1405",
                             "Round": theme.ON_ACCENT}.get(kind or "", theme.TEXT)
        b.setIcon(icons.icon(icon, col, size))
        b.setIconSize(QSize(size, size))
    if tip:
        b.setToolTip(tip)
        b.setAccessibleName(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Kbd(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("Kbd")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class Chip(QFrame):
    """Rounded status pill: icon + text (+ value)."""

    def __init__(self, icon: str | None = None, text: str = "", value: str = ""):
        super().__init__()
        self.setObjectName("Chip")
        self._icon_name = icon
        self._icon = QLabel()
        self._text = QLabel(text)
        self._value = QLabel(value)
        self._value.setObjectName("ChipValue")
        lay = hbox(self._icon, self._text, self._value, spacing=7, margins=(12, 0, 12, 0))
        self.setLayout(lay)
        self.set(text, value, "neutral", icon)

    def set(self, text: str, value: str = "", state: str = "neutral", icon: str | None = None) -> None:
        self._text.setText(text)
        self._value.setText(value)
        self._value.setVisible(bool(value))
        col = {"ok": theme.ACCENT_TEXT, "warn": theme.WARNING_TEXT, "busy": theme.ON_ACCENT}.get(state, theme.TEXT2)
        name = icon or self._icon_name
        if name:
            self._icon.setPixmap(icons.pixmap(name, col, 15))
        self._icon.setVisible(bool(name))
        theme.set_state(self, state)


def _help() -> dict:
    return HELP if language() == "ru" else HELP_EN


def help_html(key: str) -> str:
    d = _help().get(key)
    if not d:
        return ""
    e = lambda s: html.escape(s or "")
    impact_col = {"warn": theme.WARNING_TEXT, "ok": theme.ACCENT_TEXT}.get(d.get("impactKind", ""), theme.TEXT2)
    rows = [f"<div style='font-size:11px;color:{theme.HINT}'>{e(d.get('group'))}</div>",
            f"<div style='font-size:14px;font-weight:700;color:{theme.TEXT};margin:2px 0 6px 0'>{e(d.get('title'))}</div>",
            f"<div style='color:#C9D6CC;line-height:140%'>{e(d.get('text'))}</div>"]
    if d.get("tip"):
        rows.append(f"<div style='color:{theme.ACCENT_TEXT};margin-top:8px'>💡 {e(d['tip'])}</div>")
    meta = []
    if d.get("def"):
        meta.append(tr("<span style='color:{0}'>По умолчанию:</span> {1}").format(theme.HINT, e(d['def'])))
    if d.get("impact"):
        meta.append(f"<span style='color:{impact_col}'>{e(d['impact'])}</span>")
    if meta:
        rows.append(f"<div style='margin-top:8px;font-size:12px'>{' &nbsp;·&nbsp; '.join(meta)}</div>")
    return f"<div style='width:300px'>{''.join(rows)}</div>"


class InfoButton(QPushButton):
    """ⓘ next to a setting: hover shows the hint after 400 ms, click shows it at once."""

    def __init__(self, key: str):
        super().__init__()
        self.setObjectName("Info")
        self.key = key
        self.setIcon(icons.icon("info", theme.HINT, 14))
        self.setIconSize(QSize(14, 14))
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.setAccessibleName(tr('Подсказка: ') + _help().get(key, {}).get("title", key))
        self._t = QTimer(self, singleShot=True, interval=400, timeout=self._show)
        self.clicked.connect(self._show)

    def _show(self) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 4)), help_html(self.key), self)

    def enterEvent(self, e) -> None:
        self._t.start()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._t.stop()
        super().leaveEvent(e)


def field(title: str, control: QWidget | None, help_key: str | None = None, value: QLabel | None = None) -> QWidget:
    """Label row (title + ⓘ [+ value on the right]) above a control."""
    w = QWidget()
    lab = label(title, "FieldLabel")
    row = [lab]
    if help_key:
        row.append(InfoButton(help_key))
    row.append(None)
    if value is not None:
        row.append(value)
    lay = vbox(hbox(*row, spacing=4), spacing=5)
    if control is not None:
        lay.addWidget(control)
    w.setLayout(lay)
    w.label = lab  # type: ignore[attr-defined]
    return w


class Toggle(QCheckBox):
    """Switch (38x22). Use :func:`toggle_row` for a «text ... switch» row."""

    def __init__(self, accessible: str = ""):
        super().__init__()
        self.setObjectName("Toggle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(accessible)


def toggle_row(text: str, toggle: "Toggle", help_key: str | None = None) -> QWidget:
    w = QWidget()
    lab = QLabel(text)
    lab.setBuddy(toggle)
    items = [lab]
    if help_key:
        items.append(InfoButton(help_key))
    items += [None, toggle]
    w.setLayout(hbox(*items, spacing=4))
    w.label = lab  # type: ignore[attr-defined]
    toggle.toggled.connect(lambda _=False: None)
    return w


class Segmented(QFrame):
    """Exclusive segmented control. ``changed(value)``."""

    changed = pyqtSignal(str)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("Seg")
        self._buttons: dict[str, QPushButton] = {}
        lay = hbox(spacing=2, margins=(3, 3, 3, 3))
        for value, text in items:
            b = QPushButton(text)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self.set_value(v, emit=True))
            lay.addWidget(b, 1)
            self._buttons[value] = b
        self.setLayout(lay)
        self.setFixedHeight(34)
        self._value = items[0][0]
        self.set_value(self._value)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str, emit: bool = False) -> None:
        if value not in self._buttons:
            return
        self._value = value
        for v, b in self._buttons.items():
            b.setChecked(v == value)
        if emit:
            self.changed.emit(value)

    def setEnabled(self, on: bool) -> None:  # noqa: N802
        for b in self._buttons.values():
            b.setEnabled(on)


class Section(QFrame):
    """Collapsible settings section."""

    def __init__(self, title: str, open_: bool = True):
        super().__init__()
        self.setObjectName("Section")
        self.head = QPushButton(title)
        self.head.setObjectName("SectionHead")
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.head.setIconSize(QSize(14, 14))
        self.head.clicked.connect(lambda: self.set_open(not self._open))
        self.body = QWidget()
        self.body_layout = vbox(spacing=12, margins=(12, 2, 12, 14))
        self.body.setLayout(self.body_layout)
        self.setLayout(vbox(self.head, self.body, spacing=0))
        self._open = True
        self.set_open(open_)

    def add(self, *widgets) -> None:
        for w in widgets:
            if isinstance(w, QWidget):
                self.body_layout.addWidget(w)
            else:
                self.body_layout.addLayout(w)

    def set_open(self, on: bool) -> None:
        self._open = on
        self.body.setVisible(on)
        self.head.setIcon(icons.icon("chevron-up" if on else "chevron-down", theme.TEXT2, 14))


class LogView(QTextEdit):
    COLORS = {"m": theme.TEXT2, "ok": theme.ACCENT_TEXT, "warn": theme.WARNING_TEXT,
              "info": "#9CC7EC", "err": "#F07C75"}

    def __init__(self):
        super().__init__()
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.count = 0
        self.lines: list[str] = []

    def add(self, text: str, level: str | None = None) -> None:
        if level is None:
            t = text.lstrip()
            level = ("warn" if t.startswith(("⚠", tr('Пауза'))) else "ok" if t.startswith(("✓", tr('Готово')))
                     else "err" if t.startswith((tr('Ошибка'), "■", "✗")) else "m")
        ts = time.strftime("[%H:%M]")
        self.lines.append(f"{ts} {text}")
        first, *rest = text.split("\n")
        body = html.escape(first) + "".join("<br>" + html.escape(r) for r in rest)
        self.append(f"<span style='color:#5F6E64'>{ts}</span>&nbsp;&nbsp;"
                    f"<span style='color:{self.COLORS.get(level, theme.TEXT2)}'>{body}</span>")
        self.count += 1
        self.moveCursor(QTextCursor.MoveOperation.End)

    def clear_all(self) -> None:
        self.clear()
        self.lines.clear()
        self.count = 0


# ---------------------------------------------------------------- picture views

class CanvasView(QWidget):
    """Dotted backdrop with a centred picture; zoom (fit / %), crisp or smooth scaling."""

    zoomChanged = pyqtSignal(str)

    def __init__(self, smooth: bool = False, mat: bool = False, placeholder: tuple[str, str] = ("", "")):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 220)
        self._img: QImage | None = None
        self._smooth = smooth
        self._mat = mat
        self._zoom: float | None = None          # None = fit
        self.placeholder = placeholder

    def set_image(self, img: Image.Image | QImage | None) -> None:
        if img is None:
            self._img = None
        else:
            self._img = img if isinstance(img, QImage) else pil_to_qimage(img)
        self.update()
        self.zoomChanged.emit(self.zoom_text())

    def has_image(self) -> bool:
        return self._img is not None

    def _fit_scale(self) -> float:
        if not self._img:
            return 1.0
        pad = 48 if self._mat else 32
        return max(0.01, min((self.width() - pad) / self._img.width(), (self.height() - pad) / self._img.height()))

    def scale(self) -> float:
        return self._zoom if self._zoom is not None else self._fit_scale()

    def zoom_text(self) -> str:
        return f"{round(self.scale() * 100)}%" if self._img else "—"

    def zoom_by(self, k: float) -> None:
        self._zoom = max(0.1, min(16.0, self.scale() * k))
        self.update()
        self.zoomChanged.emit(self.zoom_text())

    def zoom_fit(self) -> None:
        self._zoom = None
        self.update()
        self.zoomChanged.emit(self.zoom_text())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.zoomChanged.emit(self.zoom_text())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor("#0C120E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1A241D"))
        for y in range(8, r.height(), 16):           # radial-dot backdrop
            for x in range(8, r.width(), 16):
                p.drawEllipse(QPointF(x, y), 1, 1)
        if self._img is None:
            t, sub = self.placeholder
            if t:
                f = QFont(theme.FONT)
                f.setPixelSize(15)
                f.setWeight(QFont.Weight.Medium)
                p.setFont(f)
                p.setPen(QColor(theme.TEXT2))
                p.drawText(r.adjusted(0, -12, 0, -12), Qt.AlignmentFlag.AlignCenter, t)
                f.setPixelSize(13)
                f.setWeight(QFont.Weight.Normal)
                p.setFont(f)
                p.setPen(QColor(theme.HINT))
                p.drawText(r.adjusted(0, 26, 0, 26), Qt.AlignmentFlag.AlignCenter, sub)
            p.end()
            return
        s = self.scale()
        w, h = self._img.width() * s, self._img.height() * s
        x, y = (r.width() - w) / 2, (r.height() - h) / 2
        target = QRectF(x, y, w, h)
        # soft shadow + optional mat
        for i, a in ((10, 18), (6, 26), (3, 34)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(target.adjusted(-i, -i + 8, i, i + 8), 6, 6)
        if self._mat:
            p.setBrush(QColor("#2A3229"))
            p.drawRoundedRect(target.adjusted(-10, -10, 10, 10), 6, 6)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth and s < 4)
        p.drawImage(target, self._img)
        p.end()


class ClickFrame(QFrame):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()


class SourceView(CanvasView):
    """Source picture tab: a big drop zone until a picture is loaded."""

    fileDropped = pyqtSignal(str)

    def __init__(self):
        super().__init__(smooth=True)
        self.setAcceptDrops(True)
        self.zone = ClickFrame()
        self.zone.setObjectName("DropZone")
        self.zone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zone.setFixedSize(540, 320)
        self.zone.setStyleSheet(
            f"QFrame#DropZone {{ background: {theme.SURFACE1}; border: 2px dashed #3A4B40; border-radius: 16px; }}"
            f"QFrame#DropZone:hover {{ border-color: {theme.ACCENT_PRESSED}; }}"
            "QFrame#DropZone QLabel { border: none; }")
        tile = QLabel()
        tile.setFixedSize(60, 60)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setPixmap(icons.pixmap("image", theme.ACCENT, 28, width=1.7))
        tile.setStyleSheet("QLabel { background: rgba(134,192,74,0.12); border: 1px solid rgba(134,192,74,0.35); border-radius: 16px; }")
        t = label(tr('Перетащите картинку сюда или кликните'))
        t.setStyleSheet("font-size: 19px; font-weight: 600;")
        sub = label(tr('Можно вставить из буфера обмена — Ctrl+V'), "Desc")
        sub.setStyleSheet(f"font-size: 13px; color: {theme.TEXT2};")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch(1)
        for ext in ("PNG", "JPG", "WEBP", "GIF", "BMP"):
            c = QLabel(ext)
            c.setStyleSheet(f"background:#172019;border:1px solid {theme.BORDER};border-radius:6px;padding:3px 8px;"
                            f"font-family:'{theme.MONO}';font-size:11px;color:{theme.TEXT2};")
            chips.addWidget(c)
        chips.addStretch(1)
        for w in (tile, t, sub):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner = vbox(None, hbox(None, tile, None), 4, hbox(None, t, None), hbox(None, sub, None), 6, chips, None,
                     spacing=10)
        self.zone.setLayout(inner)
        self.zone.clicked.connect(self.browse)
        lay = vbox(None, hbox(None, self.zone, None), None)
        self.setLayout(lay)

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr('Выберите картинку'), "", tr(IMAGE_FILTER))
        if path:
            self.fileDropped.emit(path)

    def set_image(self, img) -> None:
        super().set_image(img)
        self.zone.setVisible(img is None)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in IMAGE_EXT
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in IMAGE_EXT:
                self.fileDropped.emit(p)
                return


class Badge(QFrame):
    """Floating status pill over the picture (planning / paused)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame {{ background: {theme.SURFACE1}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 10px; }}"
                           "QLabel { border: none; }")
        self.icon = QLabel()
        self.title = label("", "CardTitle")
        self.sub = label("", "Desc")
        self.sub.setStyleSheet(f"font-size: 11px; color: {theme.TEXT2};")
        self.setLayout(hbox(self.icon, vbox(self.title, self.sub, spacing=2), spacing=10, margins=(10, 8, 14, 8)))
        self.move(16, 16)
        self.hide()

    def show_text(self, title: str, sub: str = "", icon: str = "speed", color: str = theme.ACCENT) -> None:
        self.icon.setPixmap(icons.pixmap(icon, color, 18))
        self.title.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.adjustSize()
        self.show()
        self.raise_()


# ---------------------------------------------------------------- HUD

class Hud(QWidget):
    """Always-on-top status strip while painting (460x64). Never takes focus, clicks pass through."""

    W, H = 460, 64

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(self.W + 16, self.H + 16)
        self.kind = "info"
        self.title = ""
        self.sub = ""
        self.fraction: float | None = None
        self.number: int | None = None
        self.color_hex: str | None = None

    def place(self) -> None:
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 16, scr.top() + 16)

    # state setters ------------------------------------------------------------
    def show_state(self, kind: str, title: str, sub: str | None = None, fraction: float | None = None,
                   number: int | None = None, color_hex: str | None = None) -> None:
        """kind: countdown | paint | alarm | done | info."""
        self.kind, self.title = kind, title
        if sub is not None:
            self.sub = sub
        if fraction is not None:
            self.fraction = max(0.0, min(1.0, fraction))
        self.number = number
        if color_hex is not None:
            self.color_hex = color_hex
        self.update()

    def set_status(self, text: str, sub: str | None = None, fraction: float | None = None, alert: bool = False) -> None:
        self.show_state("alarm" if alert else ("paint" if self.kind in ("paint", "alarm") else "info"),
                        text, sub, fraction)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(8, 8, self.W, self.H)
        for i, a in ((8, 20), (4, 30)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(box.adjusted(-i / 2, -i / 2 + 4, i / 2, i / 2 + 4), 12, 12)
        alarm = self.kind == "alarm"
        bg = QColor(theme.DANGER_ALARM) if alarm else QColor(10, 15, 12, 240)
        border = {"alarm": QColor(theme.DANGER), "done": QColor(134, 192, 74, 153)}.get(self.kind, QColor(theme.BORDER_STRONG))
        path = QPainterPath()
        path.addRoundedRect(box, 10, 10)
        p.fillPath(path, bg)
        p.setPen(QPen(border, 1))
        p.drawPath(path)
        # left circle
        c = QRectF(box.x() + 12, box.y() + 13, 38, 38)
        p.setPen(Qt.PenStyle.NoPen)
        if self.kind == "countdown":
            p.setBrush(QColor(theme.CALIB_ACTIVE))
            p.drawEllipse(c)
            f = QFont(theme.FONT)
            f.setPixelSize(20)
            f.setWeight(QFont.Weight.Bold)
            p.setFont(f)
            p.setPen(QColor("#1A1500"))
            p.drawText(c, Qt.AlignmentFlag.AlignCenter, str(self.number or ""))
        else:
            fill, ico, icol = {
                "alarm": (QColor(theme.DANGER), "pause", "#1A0605"),
                "done": (QColor(theme.ACCENT), "check", theme.ON_ACCENT),
            }.get(self.kind, (QColor(134, 192, 74, 36), "draw", theme.ACCENT))
            p.setBrush(fill)
            if self.kind not in ("alarm", "done"):
                p.setPen(QPen(QColor(134, 192, 74, 128), 1))
            p.drawEllipse(c)
            pm = icons.pixmap(ico, icol, 18, 2.0, 2.4 if self.kind == "done" else 2.0)
            p.drawPixmap(QRectF(c.center().x() - 9, c.center().y() - 9, 18, 18), pm, QRectF(pm.rect()))
        # texts
        tx = box.x() + 62
        right = box.right() - 16
        pct = f"{round(self.fraction * 100)}%" if self.fraction is not None and self.kind in ("paint", "alarm") else ""
        f = QFont(theme.FONT)
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.Bold if alarm else QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF" if alarm else theme.TEXT))
        p.drawText(QRectF(tx, box.y() + 12, right - tx - (44 if pct else 0), 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        sx = tx
        if self.kind == "paint" and self.color_hex:
            p.setPen(QPen(QColor(255, 255, 255, 77), 1))
            p.setBrush(QColor(self.color_hex))
            p.drawRoundedRect(QRectF(sx, box.y() + 38, 11, 11), 3, 3)
            sx += 17
            fm = QFont(theme.MONO)
            fm.setPixelSize(12)
            p.setFont(fm)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QPointF(sx, box.y() + 48), self.color_hex.upper())
            sx += 70
            p.setFont(f)
        p.setPen(QColor("#FFD9D6" if alarm else theme.TEXT2))
        p.drawText(QRectF(sx, box.y() + 34, right - sx, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.sub)
        if pct:
            fm = QFont(theme.MONO)
            fm.setPixelSize(13)
            p.setFont(fm)
            p.setPen(QColor("#FFD9D6" if alarm else theme.ACCENT_TEXT))
            p.drawText(QRectF(right - 44, box.y(), 44, box.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, pct)
        if self.fraction is not None and self.kind in ("paint", "alarm"):
            p.setPen(Qt.PenStyle.NoPen)
            clip = QPainterPath()
            clip.addRoundedRect(box, 10, 10)
            p.setClipPath(clip)
            bar = QRectF(box.x(), box.bottom() - 3, box.width(), 3)
            p.fillRect(bar, QColor(0, 0, 0, 90) if alarm else QColor(theme.SURFACE3))
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * self.fraction, 3),
                       QColor("#FFB3AD" if alarm else theme.ACCENT))
        p.end()
