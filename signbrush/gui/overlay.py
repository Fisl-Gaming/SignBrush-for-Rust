"""Full-screen calibration overlay drawn over a frozen screenshot.

Nothing here sends input to the game: the user marks the canvas, palette and
controls on a still picture inside our own window.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from ..calibration import STEPS, Step, detect_canvas
from . import theme
from ..i18n import language, tr

ImgPt = tuple[int, int]

SHORT = {"canvas": "Холст", "hex_field": "HEX-поле", "picker_sv": "Квадрат цвета", "picker_hue": "Полоса тонов",
         "size_textbox": "Размер", "size_slider": "Ползунок размера", "opacity_textbox": "Прозрачность",
         "opacity_slider": "Ползунок прозрачности", "spacing_textbox": "Интервал", "brush_square": "Квадратная кисть",
         "brush_circle": "Круглая кисть", "palette": "Избранное", "save": "Сохранить", "focus": "Фокус"}


class CalibrationOverlay(QWidget):
    """Emits ``finished(results)`` (screenshot coordinates) or ``cancelled()``."""

    finished = pyqtSignal(dict)
    cancelled = pyqtSignal()

    def __init__(self, shot: np.ndarray, prefill: dict[str, tuple], grid: tuple[int, int],
                 aspect: float | None = None, steps: list[Step] | None = None, caption: str = ""):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.shot = np.ascontiguousarray(shot)
        h, w = self.shot.shape[:2]
        self._qimg = QImage(self.shot.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._pix = QPixmap.fromImage(self._qimg)
        self.steps = steps or STEPS
        self.caption = caption
        self.grid = grid
        self.aspect = aspect
        self.idx = 0
        self.results: dict[str, tuple] = {k: v for k, v in prefill.items() if v}
        self._drag_start: ImgPt | None = None
        self._drag_now: ImgPt | None = None
        self._mouse: ImgPt = (w // 2, h // 2)

    # -- coordinates --------------------------------------------------------------
    def _scale(self) -> tuple[float, float]:
        h, w = self.shot.shape[:2]
        return w / max(1, self.width()), h / max(1, self.height())

    def to_img(self, p: QPointF | QPoint) -> ImgPt:
        sx, sy = self._scale()
        h, w = self.shot.shape[:2]
        return min(w - 1, max(0, int(p.x() * sx))), min(h - 1, max(0, int(p.y() * sy)))

    def to_widget(self, p: ImgPt) -> QPointF:
        sx, sy = self._scale()
        return QPointF((p[0] + 0.5) / sx, (p[1] + 0.5) / sy)

    @property
    def step(self) -> Step:
        return self.steps[self.idx]

    # -- input ------------------------------------------------------------------------
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            p = self.to_img(e.position())
            if self.step.kind == "point":
                self.results[self.step.key] = (p,)
            else:
                self._drag_start = self._drag_now = p
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            self._back()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self._mouse = self.to_img(e.position())
        if self._drag_start:
            self._drag_now = self._mouse
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._drag_start:
            a, b = self._drag_start, self.to_img(e.position())
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 4:
                self.results[self.step.key] = (a, b)
            self._drag_start = self._drag_now = None
            self.update()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.step.key in self.results or self.step.optional:
                self._next()
        elif k in (Qt.Key.Key_S, Qt.Key.Key_Space) and self.step.optional:
            self.results.pop(self.step.key, None)
            self._next()
        elif k == Qt.Key.Key_Backspace:
            if self.step.key in self.results:
                self.results.pop(self.step.key)
                self.update()
            else:
                self._back()
        elif k == Qt.Key.Key_A and self.step.key == "canvas":
            rect = detect_canvas(self.shot, self.aspect)
            if rect:
                self.results["canvas"] = ((rect[0], rect[1]), (rect[2], rect[3]))
            self.update()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._nudge(k, 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)

    def _nudge(self, key, d: int) -> None:
        """Arrow keys move the last point of the current mark by 1 px (Shift: 10 px)."""
        v = self.results.get(self.step.key)
        if not v:
            return
        dx = {Qt.Key.Key_Left: -d, Qt.Key.Key_Right: d}.get(key, 0)
        dy = {Qt.Key.Key_Up: -d, Qt.Key.Key_Down: d}.get(key, 0)
        *rest, last = v
        self.results[self.step.key] = (*rest, (last[0] + dx, last[1] + dy))
        self.update()

    def _next(self) -> None:
        if self.idx + 1 >= len(self.steps):
            self.finished.emit(dict(self.results))
            self.close()
        else:
            self.idx += 1
            self.update()

    def _back(self) -> None:
        if self.idx > 0:
            self.idx -= 1
            self.update()

    # -- drawing ------------------------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), self._pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 40))
        for key, val in self.results.items():
            self._draw_mark(p, key, val, active=(key == self.step.key))
        if self._drag_start and self._drag_now:
            self._draw_mark(p, self.step.key, (self._drag_start, self._drag_now), active=True)
        self._draw_banner(p)
        self._draw_loupe(p)
        p.end()

    def _draw_mark(self, p: QPainter, key: str, val: tuple, active: bool) -> None:
        color = QColor(theme.CALIB_ACTIVE) if active else QColor(theme.ACCENT)
        dark = QPen(QColor(10, 15, 12, 220), 5)
        kind = next((s.kind for s in self.steps if s.key == key), "point")

        def stroke(draw):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(dark)                       # dark outline first: readable on any background
            draw()
            p.setPen(QPen(color, 2))
            draw()

        if kind == "rect" and len(val) == 2:
            a, b = self.to_widget(val[0]), self.to_widget(val[1])
            rect = QRectF(a, b).normalized()
            stroke(lambda: p.drawRect(rect))
            if active:
                p.fillRect(rect, QColor(255, 212, 59, 22))
        elif kind == "line" and len(val) == 2:
            a, b = self.to_widget(val[0]), self.to_widget(val[1])
            if key == "palette":
                cols, rows = self.grid
                for r in range(rows):
                    for c in range(cols):
                        fx = c / max(1, cols - 1)
                        fy = r / max(1, rows - 1)
                        q = QPointF(a.x() + (b.x() - a.x()) * fx, a.y() + (b.y() - a.y()) * fy)
                        stroke(lambda q=q: p.drawEllipse(q, 5, 5))
            else:
                stroke(lambda: p.drawLine(a, b))
                stroke(lambda: p.drawEllipse(a, 5, 5))
                stroke(lambda: p.drawRect(QRectF(b.x() - 5, b.y() - 5, 10, 10)))
        else:
            q = self.to_widget(val[0])
            stroke(lambda: (p.drawLine(QPointF(q.x() - 10, q.y()), QPointF(q.x() + 10, q.y())),
                            p.drawLine(QPointF(q.x(), q.y() - 10), QPointF(q.x(), q.y() + 10))))
        # name tag
        f = QFont(theme.FONT)
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        name = tr(SHORT.get(key, key))
        anchor = self.to_widget(val[0]) + QPointF(8, -10)
        tw = p.fontMetrics().horizontalAdvance(name) + 12
        tag = QRectF(anchor.x(), anchor.y() - 14, tw, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(10, 15, 12, 220))
        p.drawRoundedRect(tag, 4, 4)
        p.setPen(color)
        p.drawText(tag, Qt.AlignmentFlag.AlignCenter, name)

    def _draw_banner(self, p: QPainter) -> None:
        s = self.step
        w = min(760, self.width() - 40)
        box = QRectF((self.width() - w) / 2, 20, w, 112)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(box.adjusted(-2, 6, 2, 10), 16, 16)
        p.setBrush(QColor(17, 24, 19, 245))
        p.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
        p.drawRoundedRect(box, 14, 14)
        # step pill
        f = QFont(theme.FONT)
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        pill_t = tr('Шаг {0}/{1}').format(self.idx + 1, len(self.steps)) + (tr(' · необязательно') if s.optional else "")
        pw = p.fontMetrics().horizontalAdvance(pill_t) + 20
        pill = QRectF(box.x() + 18, box.y() + 16, pw, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(134, 192, 74, 36))
        p.drawRoundedRect(pill, 12, 12)
        p.setPen(QColor(theme.ACCENT_TEXT))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, pill_t)
        # progress dots
        dx = pill.right() + 14
        for i in range(len(self.steps)):
            col = theme.ACCENT if i < self.idx else (theme.CALIB_ACTIVE if i == self.idx else theme.BORDER_STRONG)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(dx + i * 12, pill.center().y()), 3.5, 3.5)
        # title
        f.setPixelSize(17)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(box.x() + 18, box.y() + 46, box.width() - 36, 26),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, s.ru if language() == "ru" else s.en)
        # key hints
        keys = [("Enter", tr('дальше')), ("Backspace", tr('стереть')), (tr('ПКМ'), tr('назад')), ("S", tr('пропустить')),
                ("←↑→↓", tr('сдвиг 1 px')), ("Esc", tr('отмена'))]
        if s.key == "canvas":
            keys.insert(0, ("A", tr('найти холст')))
        x = box.x() + 18
        y = box.y() + 80
        fk = QFont(theme.MONO)
        fk.setPixelSize(11)
        ft = QFont(theme.FONT)
        ft.setPixelSize(12)
        for k, what in keys:
            p.setFont(fk)
            kw = p.fontMetrics().horizontalAdvance(k) + 12
            kr = QRectF(x, y, kw, 20)
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
            p.setBrush(QColor("#172019"))
            p.drawRoundedRect(kr, 4, 4)
            p.setPen(QColor(theme.TEXT))
            p.drawText(kr, Qt.AlignmentFlag.AlignCenter, k)
            p.setFont(ft)
            p.setPen(QColor(theme.TEXT2))
            tw = p.fontMetrics().horizontalAdvance(what)
            p.drawText(QPointF(x + kw + 6, y + 14), what)
            x += kw + tw + 20
        # caption bottom-left
        if self.caption:
            f.setPixelSize(12)
            f.setWeight(QFont.Weight.Medium)
            p.setFont(f)
            cw = p.fontMetrics().horizontalAdvance(self.caption) + 24
            cr = QRectF(20, self.height() - 48, cw, 28)
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
            p.setBrush(QColor(10, 15, 12, 225))
            p.drawRoundedRect(cr, 14, 14)
            p.setPen(QColor(theme.TEXT2))
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, self.caption)

    def _draw_loupe(self, p: QPainter) -> None:
        """8x magnifier next to the cursor - for hitting swatch centres exactly."""
        r, zoom = 12, 8
        mx, my = self._mouse
        h, w = self.shot.shape[:2]
        x0, y0 = max(0, mx - r), max(0, my - r)
        x1, y1 = min(w, mx + r + 1), min(h, my + r + 1)
        crop = self._qimg.copy(x0, y0, x1 - x0, y1 - y0)
        size = (2 * r + 1) * zoom
        c = self.to_widget(self._mouse)
        dx = 30 if c.x() + 30 + size < self.width() else -30 - size
        dy = 30 if c.y() + 30 + size < self.height() else -30 - size
        target = QRectF(c.x() + dx, c.y() + dy, (x1 - x0) * zoom, (y1 - y0) * zoom)
        p.drawImage(target, crop)
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawRect(target)
        cx = target.x() + (mx - x0 + 0.5) * zoom
        cy = target.y() + (my - y0 + 0.5) * zoom
        p.setPen(QPen(QColor(255, 0, 80), 1))
        p.drawLine(QPointF(cx - zoom, cy), QPointF(cx + zoom, cy))
        p.drawLine(QPointF(cx, cy - zoom), QPointF(cx, cy + zoom))
        rgb = self.shot[my, mx]
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(target.x(), target.bottom() + 14),
                   f"{mx},{my}  #{int(rgb[0]):02X}{int(rgb[1]):02X}{int(rgb[2]):02X}")
