"""Design tokens and the Qt style sheet (from the «Sign Painter — интерфейс» design)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from . import icons

# ---------------------------------------------------------------- tokens
BG = "#0A0F0C"            # bg/window
CHROME = "#0D1310"        # header, action bar
SURFACE1 = "#111813"      # cards, panels
SURFACE2 = "#141C17"      # settings sections
SURFACE3 = "#1D2820"      # fields, buttons
HOVER = "#243028"
BORDER = "#253128"
BORDER_STRONG = "#34433A"
TEXT = "#E7EEE8"
TEXT2 = "#A3B2A7"
HINT = "#7D8C82"
DISABLED = "#56645B"
ACCENT = "#86C04A"
ACCENT_HOVER = "#98D25B"
ACCENT_PRESSED = "#6FA537"
ACCENT_TEXT = "#A6D873"
ON_ACCENT = "#0E1A07"
WARNING = "#F2A541"
WARNING_TEXT = "#F5B963"
DANGER = "#E5534B"
DANGER_ALARM = "#5A1814"
INFO = "#7DB7E8"
CALIB_ACTIVE = "#FFD43B"

FONT = "Onest"
MONO = "JetBrains Mono"


def _font_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    for p in (base / "signbrush" / "gui" / "fonts", Path(__file__).with_name("fonts")):
        if p.exists():
            return p
    return Path(__file__).with_name("fonts")


def load_fonts() -> None:
    global FONT, MONO
    ok: set[str] = set()
    for f in _font_dir().glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            ok.update(QFontDatabase.applicationFontFamilies(fid))
    if "Onest" not in ok:
        FONT = "Segoe UI Variable Text"
    if "JetBrains Mono" not in ok:
        MONO = "Consolas"


def _assets() -> dict[str, str]:
    d = Path(tempfile.gettempdir()) / "signbrush_theme2"
    d.mkdir(exist_ok=True)
    out: dict[str, str] = {}

    def save(name: str, pm: QPixmap) -> None:
        path = d / f"{name}.png"
        pm.save(str(path))
        out[name] = path.as_posix()

    for nm, col in (("down", TEXT2), ("down_dis", DISABLED), ("up", TEXT2), ("up_dis", DISABLED)):
        ic = "chevron-down" if nm.startswith("down") else "chevron-up"
        pm = icons.pixmap(ic, col, 14, 1.0, 2.0)
        save(nm, pm)

    def toggle(on: bool, enabled: bool) -> QPixmap:
        k = 2
        pm = QPixmap(38 * k, 22 * k)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(k, k)
        if not enabled:
            p.setPen(QPen(QColor("#2A362E"), 1))
            p.setBrush(QColor(SURFACE3))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT if on else BORDER_STRONG))
        p.drawRoundedRect(QRectF(0.5, 0.5, 37, 21), 10.5, 10.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3A463F" if not enabled else (ON_ACCENT if on else TEXT2)))
        p.drawEllipse(QRectF(19 if on else 3, 3, 16, 16))
        p.end()
        return pm

    save("tog_on", toggle(True, True))
    save("tog_off", toggle(False, True))
    save("tog_on_dis", toggle(True, False))
    save("tog_off_dis", toggle(False, False))
    return out


def stylesheet() -> str:
    a = _assets()
    return f"""
* {{ font-family: "{FONT}", "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 13px; color: {TEXT}; outline: none; }}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QDialog {{ background: transparent; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: #151D18; color: {TEXT}; border: 1px solid #3A4B40; padding: 8px 10px; font-size: 12px; }}

/* chrome */
QFrame#Header {{ background: {CHROME}; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#Footer {{ background: {CHROME}; border: none; border-top: 1px solid {BORDER}; }}
QLabel#AppTitle {{ font-size: 16px; font-weight: 700; }}
QLabel#Muted {{ color: {TEXT2}; font-size: 12px; }}
QLabel#Hint {{ color: {HINT}; font-size: 11px; }}
QLabel#Caps {{ color: {HINT}; font-size: 11px; font-weight: 600; }}
QLabel#Kbd {{ font-family: "{MONO}"; font-size: 11px; color: {TEXT}; background: #172019; border: 1px solid {BORDER_STRONG};
              border-bottom: 2px solid {BORDER_STRONG}; border-radius: 4px; padding: 0 6px; min-height: 16px; }}
QFrame#VSep {{ background: {BORDER}; max-width: 1px; min-width: 1px; }}

/* chips */
QFrame#Chip {{ background: #172019; border: 1px solid {BORDER}; border-radius: 14px; min-height: 26px; max-height: 26px; }}
QFrame#Chip QLabel {{ font-size: 12px; font-weight: 500; color: {TEXT2}; }}
QFrame#Chip QLabel#ChipValue {{ color: {TEXT}; }}
QFrame#Chip[state="ok"] {{ background: rgba(134,192,74,0.12); border-color: rgba(134,192,74,0.38); }}
QFrame#Chip[state="ok"] QLabel {{ color: {ACCENT_TEXT}; font-weight: 600; }}
QFrame#Chip[state="warn"] {{ background: rgba(242,165,65,0.12); border-color: rgba(242,165,65,0.4); }}
QFrame#Chip[state="warn"] QLabel {{ color: {WARNING_TEXT}; font-weight: 600; }}
QFrame#Chip[state="busy"] {{ background: {ACCENT}; border-color: {ACCENT}; }}
QFrame#Chip[state="busy"] QLabel {{ color: {ON_ACCENT}; font-weight: 600; }}

/* cards */
QFrame#Card {{ background: {SURFACE1}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#CardHead {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}
QFrame#LogHead {{ background: transparent; border: none; border-bottom: 1px solid {SURFACE3}; }}
QLabel#CardTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#PanelTitle {{ font-size: 15px; font-weight: 600; }}
QFrame#Section {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton#SectionHead {{ background: transparent; border: none; text-align: left; font-size: 14px; font-weight: 600;
                           padding: 0 12px; min-height: 44px; color: {TEXT}; }}
QPushButton#SectionHead:hover {{ color: {ACCENT_TEXT}; }}
QFrame#OkBox {{ background: rgba(134,192,74,0.08); border: 1px solid rgba(134,192,74,0.25); border-radius: 8px; }}
QFrame#WarnBox {{ background: rgba(242,165,65,0.10); border: 1px solid rgba(242,165,65,0.45); border-radius: 8px; }}
QFrame#InfoBox {{ background: #172019; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#LockBox {{ background: #172019; border: 1px solid {BORDER_STRONG}; border-radius: 8px; }}
QLabel#OkText {{ color: #C9D6CC; font-size: 12px; }}
QLabel#WarnTitle {{ color: {WARNING_TEXT}; font-weight: 600; }}
QLabel#Body {{ color: #C9D6CC; font-size: 12px; }}
QLabel#Desc {{ color: {TEXT2}; font-size: 12px; }}
QLabel#FieldLabel {{ color: {TEXT2}; font-size: 12px; }}
QLabel#FieldLabel:disabled {{ color: {DISABLED}; }}
QLabel#Value {{ color: {TEXT}; font-weight: 600; font-size: 12px; }}
QLabel#StepTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#Step {{ min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; border-radius: 12px; font-size: 12px; font-weight: 700; qproperty-alignment: AlignCenter; }}
QLabel#Step[state="done"] {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QLabel#Step[state="active"] {{ background: rgba(134,192,74,0.12); border: 2px solid {ACCENT}; color: {ACCENT_TEXT}; }}
QLabel#Step[state="warn"] {{ background: {WARNING}; color: #1F1405; }}
QLabel#Step[state="todo"] {{ background: transparent; border: 2px solid {BORDER_STRONG}; color: {HINT}; }}
QFrame#StepLine {{ background: {BORDER}; min-width: 2px; max-width: 2px; border-radius: 1px; }}
QLabel#Badge {{ background: rgba(134,192,74,0.14); color: {ACCENT_TEXT}; font-size: 10px; font-weight: 600; border-radius: 4px; padding: 2px 6px; }}

/* buttons */
QPushButton {{ background: {SURFACE3}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 0 14px;
               min-height: 32px; font-weight: 500; color: {TEXT}; }}
QPushButton:hover {{ background: {HOVER}; border-color: #4A5A50; }}
QPushButton:pressed {{ background: #172019; color: #C9D6CC; }}
QPushButton:disabled {{ background: transparent; border-color: #1F2A23; color: #4E5B53; }}
QFrame#Footer QPushButton {{ min-height: 42px; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: {ON_ACCENT}; font-weight: 700;
                       font-size: 16px; border-radius: 10px; padding: 0 26px; }}
QFrame#Footer QPushButton#Primary {{ min-height: 50px; }}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton#Primary:disabled {{ background: #1A231D; border-color: {BORDER}; color: #4E5B53; }}
QPushButton#PrimarySm {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: {ON_ACCENT}; font-weight: 700; }}
QPushButton#PrimarySm:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Danger {{ background: {DANGER}; border: 1px solid {DANGER}; color: #1A0605; font-weight: 600; }}
QPushButton#Danger:hover {{ background: #F06A62; border-color: #F06A62; }}
QPushButton#Danger:pressed {{ background: #C4423B; }}
QPushButton#Danger:disabled {{ background: transparent; border-color: rgba(229,83,75,0.22); color: #6B4542; }}
QPushButton#Ghost {{ background: transparent; border-color: transparent; color: {TEXT2}; }}
QPushButton#Ghost:hover {{ background: #172019; color: {TEXT}; }}
QPushButton#Ghost:disabled {{ color: #4E5B53; }}
QPushButton#Outline {{ background: transparent; border: 1px solid {BORDER_STRONG}; }}
QPushButton#Outline:hover {{ background: #172019; }}
QPushButton#Link {{ background: transparent; border: none; color: {ACCENT_TEXT}; padding: 0 4px; min-height: 24px; font-size: 12px; }}
QPushButton#Link:hover {{ color: {ACCENT_HOVER}; }}
QPushButton#Warn {{ background: {WARNING}; border: none; color: #1F1405; font-weight: 600; min-height: 34px; }}
QPushButton#Warn:hover {{ background: #F5B963; }}
QPushButton#Icon {{ padding: 0; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; }}
QPushButton#Flat {{ background: transparent; border: none; padding: 0; min-width: 28px; min-height: 28px; color: {TEXT2}; }}
QPushButton#Flat:hover {{ background: #172019; color: {TEXT}; }}
QPushButton#Info {{ background: transparent; border: none; padding: 0; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; border-radius: 10px; }}
QPushButton#Info:hover {{ background: {HOVER}; }}
QPushButton#Round {{ background: {ACCENT}; border: none; border-radius: 18px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0; }}
QPushButton#Round:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Swatch {{ border: 1px solid {BORDER_STRONG}; border-radius: 8px; font-family: "{MONO}"; font-size: 12px; }}

/* segmented */
QFrame#Seg {{ background: #0C120E; border: 1px solid {BORDER}; border-radius: 9px; }}
QPushButton#SegBtn {{ background: transparent; border: 1px solid transparent; border-radius: 6px; min-height: 26px; padding: 0 12px;
                      color: {TEXT2}; font-size: 12px; font-weight: 500; }}
QPushButton#SegBtn:hover {{ color: {TEXT}; }}
QPushButton#SegBtn:checked {{ background: {SURFACE3}; color: {TEXT}; font-weight: 600; border-color: rgba(134,192,74,0.45); }}
QPushButton#SegBtn:disabled {{ color: {DISABLED}; }}
QFrame#SegPlain QPushButton#SegBtn:checked {{ border-color: transparent; }}

/* inputs */
QLineEdit, QComboBox, QAbstractSpinBox {{ background: {SURFACE3}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    padding: 0 10px; min-height: 32px; selection-background-color: {ACCENT_PRESSED}; selection-color: {ON_ACCENT}; }}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ border-color: #4A5A50; }}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{ background: {SURFACE2}; border: 1px dashed #2A362E; color: {DISABLED}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({a["down"]}); width: 14px; height: 14px; }}
QComboBox::down-arrow:disabled {{ image: url({a["down_dis"]}); }}
QComboBox QAbstractItemView {{ background: #151D18; border: 1px solid #3A4B40; border-radius: 10px; padding: 5px;
    selection-background-color: {HOVER}; selection-color: {TEXT}; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 8px; border-radius: 6px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 24px; border: none; background: transparent; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-arrow {{ image: url({a["up"]}); width: 12px; height: 12px; }}
QAbstractSpinBox::down-arrow {{ image: url({a["down"]}); width: 12px; height: 12px; }}
QAbstractSpinBox::up-arrow:disabled {{ image: url({a["up_dis"]}); }}
QAbstractSpinBox::down-arrow:disabled {{ image: url({a["down_dis"]}); }}

QCheckBox {{ spacing: 10px; }}
QCheckBox:disabled {{ color: {DISABLED}; }}
QCheckBox#Toggle::indicator {{ width: 38px; height: 22px; }}
QCheckBox#Toggle::indicator:unchecked {{ image: url({a["tog_off"]}); }}
QCheckBox#Toggle::indicator:checked {{ image: url({a["tog_on"]}); }}
QCheckBox#Toggle::indicator:unchecked:disabled {{ image: url({a["tog_off_dis"]}); }}
QCheckBox#Toggle::indicator:checked:disabled {{ image: url({a["tog_on_dis"]}); }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid #4A5A50; background: transparent; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider {{ min-height: 20px; }}
QSlider::groove:horizontal {{ height: 4px; background: {SURFACE3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; border: 3px solid {ACCENT}; width: 10px; height: 10px; margin: -6px 0; border-radius: 8px; }}
QSlider#Info::sub-page:horizontal {{ background: {INFO}; }}
QSlider#Info::handle:horizontal {{ border-color: {INFO}; }}

/* tabs */
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; border: none; border-bottom: 2px solid transparent; color: {TEXT2};
               min-height: 44px; padding: 0 14px; font-weight: 500; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; font-weight: 600; border-bottom: 2px solid {ACCENT}; }}

/* progress */
QProgressBar {{ background: {SURFACE3}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QProgressBar[state="warn"]::chunk {{ background: {WARNING}; }}
QProgressBar[state="danger"]::chunk {{ background: {DANGER}; }}
QProgressBar[state="info"]::chunk {{ background: {INFO}; }}
QLabel#Eta {{ font-size: 30px; font-weight: 700; }}
QLabel#Eta[state="dim"] {{ color: #4E5B53; }}
QLabel#Eta[state="warn"] {{ color: {WARNING_TEXT}; }}
QLabel#Line1 {{ font-weight: 600; }}
QLabel#WarnLine {{ color: {WARNING_TEXT}; font-size: 12px; }}

/* log */
QTextEdit#Log {{ background: transparent; border: none; font-family: "{MONO}"; font-size: 12px; color: {TEXT2}; padding: 4px 8px; }}

/* scrolling */
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4A5A50; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

/* dialogs */
QFrame#DlgCard {{ background: {SURFACE1}; border: 1px solid {BORDER_STRONG}; border-radius: 14px; }}
QFrame#DlgCard[kind="error"] {{ border-color: rgba(229,83,75,0.55); }}
QFrame#DlgFoot {{ background: {CHROME}; border: none; border-top: 1px solid {BORDER};
                  border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}
QLabel#DlgTitle {{ font-size: 18px; font-weight: 700; }}
QFrame#StatTile {{ background: #172019; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel#StatValue {{ font-size: 20px; font-weight: 700; }}
QFrame#RiskBox {{ background: rgba(242,165,65,0.10); border: 1px solid rgba(242,165,65,0.35); border-radius: 8px; }}
QLabel#RiskText {{ color: #F5D3A3; font-size: 12px; }}
QLabel#Details {{ background: #0C120E; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;
                  font-family: "{MONO}"; font-size: 11px; color: {TEXT2}; }}
QFrame#IconTile {{ border-radius: 10px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QFrame#IconTile[kind="ok"] {{ background: rgba(134,192,74,0.12); border: 1px solid rgba(134,192,74,0.35); }}
QFrame#IconTile[kind="warn"] {{ background: rgba(242,165,65,0.12); border: 1px solid rgba(242,165,65,0.4); }}
QFrame#IconTile[kind="error"] {{ background: rgba(229,83,75,0.14); border: 1px solid rgba(229,83,75,0.5); }}
"""


def palette() -> QPalette:
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, SURFACE3), (QPalette.ColorRole.AlternateBase, SURFACE1),
        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, SURFACE3),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT_PRESSED),
        (QPalette.ColorRole.HighlightedText, ON_ACCENT), (QPalette.ColorRole.ToolTipBase, "#151D18"),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, DISABLED),
        (QPalette.ColorRole.Link, ACCENT_TEXT),
    ):
        pal.setColor(role, QColor(color))
    return pal


def apply(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    app.setPalette(palette())
    f = QFont(FONT)
    f.setPixelSize(13)
    app.setFont(f)
    app.setStyleSheet(stylesheet())
    app.setWindowIcon(icons.app_icon())


def set_state(w: QWidget, state: str, prop: str = "state") -> None:
    """Switch a dynamic style property and re-polish the widget (and its children)."""
    if w.property(prop) == state:
        return
    w.setProperty(prop, state)
    for x in [w, *w.findChildren(QWidget)]:
        x.style().unpolish(x)
        x.style().polish(x)


# kept for the calibration overlay / HUD that paint by hand
def logo_pixmap(size: int = 46) -> QPixmap:
    return icons.logo(size)


def app_icon():
    return icons.app_icon()
