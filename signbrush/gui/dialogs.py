"""Custom dialogs in the app's style (start confirmation, warnings, errors)."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                             QPushButton, QVBoxLayout, QWidget)

from . import icons, theme
from .widgets import Kbd, button, hbox, label, vbox
from ..i18n import tr


class Dialog(QDialog):
    """A card dialog. ``buttons`` = [(text, role, kind)] left to right; kind in Primary/Outline/Ghost/Danger.
    A role starting with "<" is put on the left side. ``exec_role()`` returns the clicked role (or "cancel")."""

    def __init__(self, parent: QWidget | None, title: str, text: str = "", kind: str = "info",
                 icon: str | None = None, stats: list[tuple[str, str]] | None = None,
                 keys: list[tuple[str, str]] | None = None, note: tuple[str, str] | None = None,
                 risk: str | None = None, details: str | None = None, checkbox: str | None = None,
                 buttons: list[tuple[str, str, str]] | None = None, width: int = 520):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.role = "cancel"
        self._drag = None
        card = QFrame()
        card.setObjectName("DlgCard")
        if kind == "error":
            card.setProperty("kind", "error")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 14)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        card.setFixedWidth(width)

        head = QHBoxLayout()
        head.setSpacing(14)
        if icon:
            tile = QFrame()
            tile.setObjectName("IconTile")
            tile.setProperty("kind", {"warn": "warn", "error": "error"}.get(kind, "ok"))
            col = {"warn": theme.WARNING_TEXT, "error": "#F07C75"}.get(kind, theme.ACCENT)
            il = QLabel()
            il.setPixmap(icons.pixmap(icon, col, 20))
            tile.setLayout(vbox(hbox(None, il, None), margins=(0, 0, 0, 0)))
            head.addWidget(tile, 0, Qt.AlignmentFlag.AlignTop)
        tl = label(title, "DlgTitle", wrap=True)
        txt = label(text, "Desc", wrap=True)
        txt.setStyleSheet(f"color: {theme.TEXT2}; font-size: 13px;")
        head.addLayout(vbox(tl, txt if text else None, spacing=6), 1)

        body = vbox(head, spacing=16, margins=(24, 22, 24, 0))
        if stats:
            row = QHBoxLayout()
            row.setSpacing(8)
            for cap, val in stats:
                t = QFrame()
                t.setObjectName("StatTile")
                t.setLayout(vbox(label(cap, "Hint"), label(val, "StatValue"), spacing=2, margins=(14, 10, 14, 10)))
                row.addWidget(t, 1)
            body.addLayout(row)
        if keys:
            kl = QVBoxLayout()
            kl.setSpacing(8)
            for k, what in keys:
                if k.startswith("icon:"):
                    il = QLabel()
                    il.setPixmap(icons.pixmap(k[5:], theme.WARNING_TEXT, 18))
                    kl.addLayout(hbox(il, label(what), None, spacing=10))
                else:
                    kl.addLayout(hbox(Kbd(k), label(what), None, spacing=10))
            body.addLayout(kl)
        if note:
            box = QFrame()
            box.setObjectName("InfoBox")
            nl = label(note[1], "Desc", wrap=True)
            box.setLayout(vbox(nl, margins=(12, 10, 12, 10)))
            body.addWidget(box)
        if risk:
            box = QFrame()
            box.setObjectName("RiskBox")
            box.setLayout(vbox(label(risk, "RiskText", wrap=True), margins=(12, 10, 12, 10)))
            body.addWidget(box)
        if details:
            d = label(details, "Details", wrap=True)
            d.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(d)
            self._details = details
        self.check: QCheckBox | None = None
        if checkbox:
            self.check = QCheckBox(checkbox)
            self.check.setStyleSheet(f"color: {theme.TEXT2}; font-size: 12px;")
            body.addWidget(self.check)

        foot = QFrame()
        foot.setObjectName("DlgFoot")
        fl = hbox(spacing=8, margins=(24, 14, 24, 14))
        left = [b for b in (buttons or []) if b[1].startswith("<")]
        right = [b for b in (buttons or [("OK", "ok", "PrimarySm")]) if not b[1].startswith("<")]
        for text_, role, k in left:
            fl.addWidget(self._btn(text_, role.lstrip("<"), k))
        fl.addStretch(1)
        for text_, role, k in right:
            fl.addWidget(self._btn(text_, role, k))
        foot.setLayout(fl)

        card.setLayout(vbox(body, 20, foot, spacing=0))
        outer = vbox(card, margins=(24, 18, 24, 34))
        self.setLayout(outer)

    def _btn(self, text: str, role: str, kind: str) -> QPushButton:
        if role == "copy":
            b = button(text, "Ghost", "copy")
            b.clicked.connect(lambda: QGuiApplication.clipboard().setText(getattr(self, "_details", "")))
            return b
        b = button(text, kind)
        b.setMinimumHeight(40)
        if kind in ("Primary", "PrimarySm"):
            b.setObjectName("PrimarySm")
            b.setDefault(True)

        def done(_=False, r=role):
            self.role = r
            self.accept() if r not in ("cancel",) else self.reject()

        b.clicked.connect(done)
        return b

    def exec_role(self) -> str:
        self.exec()
        return self.role

    def checked(self) -> bool:
        return bool(self.check and self.check.isChecked())

    # move by dragging the card
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None


def ask(parent, title: str, text: str, ok: str = "OK", cancel: str = tr('Отмена'), kind: str = "info",
        icon: str | None = "info", **kw) -> bool:
    d = Dialog(parent, title, text, kind=kind, icon=icon,
               buttons=[(cancel, "cancel", "Outline"), (ok, "ok", "PrimarySm")], **kw)
    return d.exec_role() == "ok"


def info(parent, title: str, text: str, kind: str = "info", icon: str | None = "info", **kw) -> None:
    Dialog(parent, title, text, kind=kind, icon=icon, buttons=[(tr('Понятно'), "ok", "PrimarySm")], **kw).exec()


def error(parent, title: str, text: str, details: str | None = None) -> None:
    Dialog(parent, title, text, kind="error", icon="error", details=details,
           buttons=([(tr('Скопировать детали'), "<copy", "Ghost")] if details else []) + [(tr('Закрыть'), "ok", "Outline")]
           ).exec()
