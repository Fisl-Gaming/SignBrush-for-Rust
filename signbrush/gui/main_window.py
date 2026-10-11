"""Main window (layout from the «Sign Painter — интерфейс» design)."""

from __future__ import annotations

import base64
import io
import tempfile
import threading
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtCore import QBuffer, QIODevice, QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QColorDialog, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget, QTabBar,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..calibration import apply_results
from ..config import Config, app_dir
from ..dryrun import PlanRenderer
from ..executor import Controller, Executor, Progress, WinKeyboard, verify_and_fix
from ..imaging import parse_color, to_hex
from ..pipeline import Geometry, Job, build_job
from ..planner import format_duration
from ..shapes import Cancelled
from ..winput import HotkeyWatcher, WinMouse, cursor_pos
from . import dialogs, icons, theme
from .overlay import CalibrationOverlay
from .widgets import (Badge, CanvasView, Chip, Hud, InfoButton, Kbd, LogView, Section, Segmented, SourceView,
                      Toggle, button, field, hbox, icon_label, label, toggle_row, vbox)
from ..i18n import LANGUAGES, language, set_language, tr

PROGRESS_FILE = "progress.json"

ALGO_DESC = {
    "hybrid": "Рекомендуется. Крупные полупрозрачные мазки быстро закрывают холст, потом точная доводка там, "
              "где цвет отличается больше допуска.",
    "pixels": "Точная копия: каждая клетка сетки рисуется своим цветом. Самый точный и самый долгий режим.",
    "shapes": "Только полупрозрачные круги-мазки. Быстро, живописно, без мелких деталей.",
}
CALIB_NAMES = {"canvas": "холст", "palette": "избранные цвета", "size": "размер кисти", "hex_field": "HEX-поле",
               "focus": "пустая точка панели", "picker": "квадрат и полоса цвета", "opacity": "прозрачность"}


class Bridge(QObject):
    """Carries events from worker / hotkey threads into the GUI thread."""
    event = pyqtSignal(str, object)


def _encode_target(a: np.ndarray) -> dict:
    return {"shape": list(a.shape), "data": base64.b64encode(a.astype(np.int16).tobytes()).decode()}


def _decode_target(d: dict) -> np.ndarray:
    return np.frombuffer(base64.b64decode(d["data"]), dtype=np.int16).reshape(d["shape"]).astype(np.int32)


def _encode_rgb(a: np.ndarray) -> dict:
    return {"shape": list(a.shape), "data": base64.b64encode(np.clip(a, 0, 255).astype(np.uint8).tobytes()).decode()}


def _decode_rgb(d: dict) -> np.ndarray:
    return np.frombuffer(base64.b64decode(d["data"]), dtype=np.uint8).reshape(d["shape"]).astype(np.float64)


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ") if language() == "ru" else f"{n:,}"


def _frame(name: str) -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


def _vsep(h: int = 24) -> QFrame:
    f = _frame("VSep")
    f.setFixedHeight(h)
    return f


_WINDOWS: list = []   # windows rebuilt by the language switch (kept alive here)


def _dec(text: str) -> str:
    """Decimal comma in Russian, point in English."""
    return text.replace(".", ",") if language() == "ru" else text


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.image: Image.Image | None = None
        self.image_path: str | None = None
        self.job: Job | None = None
        self._gen = 0
        self._planning = False
        self.ctl: Controller | None = None
        self.awaiting_capture = False
        self._renderer: PlanRenderer | None = None
        self._paint_started = 0.0
        self._paint_start_index = 0
        self._paint_total = 0
        self._loading = False
        self.progress_path = (cfg.path.parent if cfg.path else app_dir()) / PROGRESS_FILE

        self.bridge = Bridge()
        self.bridge.event.connect(self._on_event)
        hk = cfg.hotkeys
        self.hotkeys = HotkeyWatcher({
            hk["stop"]: lambda: self.bridge.event.emit("hk_stop", None),
            hk["pause"]: lambda: self.bridge.event.emit("hk_pause", None),
            hk["capture"]: lambda: self.bridge.event.emit("hk_capture", None),
        }).start()

        self.hud = Hud()
        self._hud_hide = QTimer(self, singleShot=True, interval=5000, timeout=self.hud.hide)
        self._refresh_timer = QTimer(self, singleShot=True, interval=350, timeout=self.rebuild_preview)
        self._anim = QTimer(self, interval=30, timeout=self._anim_tick)

        self.setWindowTitle(f"SignBrush for Rust {__version__}")
        self.resize(1320, 860)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self.paste_image)
        self._load_settings_into_ui()
        self._refresh_all()
        self.log(tr('SignBrush for Rust запущен · профиль «{0}»').format(cfg.active_profile))
        self.log(tr('Стоп — {0}, пауза — {1}, снимок для калибровки — {2}').format(hk['stop'].upper(), hk['pause'].upper(), hk['capture'].upper()))

    # ================================================================ layout
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        body = hbox(spacing=16, margins=(16, 16, 16, 16))
        left = vbox(self._preview_card(), self._log_card(), spacing=12)
        body.addLayout(left, 1)
        body.addWidget(self._aside())
        root.setLayout(vbox(self._header(), body, self._footer(), spacing=0))
        self.setCentralWidget(root)

    # ---------------------------------------------------------------- header
    def _header(self) -> QFrame:
        h = _frame("Header")
        h.setFixedHeight(60)
        logo = QLabel()
        logo.setPixmap(icons.logo(34))
        hk = self.cfg.hotkeys
        title = label("SignBrush <span style='color:#7D8C82; font-weight:500'>for Rust</span>", "AppTitle")
        sub = hbox(Kbd(hk["stop"].upper()), label(tr('стоп в любой момент'), "Muted"), label("·", "Hint"),
                   Kbd(hk["pause"].upper()), label(tr('пауза'), "Muted"), None, spacing=6)
        self.chip_profile = Chip("profile", tr('Профиль'))
        self.chip_fps = Chip("speed", "")
        self.chip_calib = Chip("check", "")
        help_btn = button("", "Flat", "help", theme.TEXT2, tr('Как пользоваться'), 18)
        help_btn.setFixedSize(34, 34)
        help_btn.clicked.connect(self.show_help)
        self.lang_seg = Segmented(list(LANGUAGES.items()))
        self.lang_seg.setObjectName("SegPlain")
        self.lang_seg.setFixedWidth(92)
        self.lang_seg.set_value(language())
        self.lang_seg.setToolTip("Язык интерфейса · Interface language")
        self.lang_seg.changed.connect(self._switch_language)
        h.setLayout(hbox(logo, 12, vbox(title, sub, spacing=3), None, self.chip_profile, self.chip_fps,
                         self.chip_calib, 4, _vsep(), 4, self.lang_seg, help_btn, spacing=8, margins=(20, 0, 20, 0)))
        return h

    # ---------------------------------------------------------------- preview
    def _preview_card(self) -> QFrame:
        card = _frame("Card")
        head = _frame("CardHead")
        head.setFixedHeight(46)
        self.tabbar = QTabBar()
        self.tabbar.setDrawBase(False)
        self.tabbar.setExpanding(False)
        for t in (tr('Исходник'), tr('Результат'), "Dry-run"):
            self.tabbar.addTab(t)
        self.tabbar.currentChanged.connect(self._on_tab)
        self.view_info = label("", "Hint")
        self.view_info.setStyleSheet(f"font-size: 12px; color: {theme.HINT};")
        zoom = _frame("Seg")
        self.zoom_out = button("", "Flat", "minus", theme.TEXT2, tr('Уменьшить'), 14)
        self.zoom_lbl = label("—")
        self.zoom_lbl.setMinimumWidth(42)
        self.zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_lbl.setStyleSheet("font-size: 12px;")
        self.zoom_in = button("", "Flat", "plus", theme.TEXT2, tr('Увеличить'), 14)
        self.zoom_fit = button("", "Flat", "fit", theme.TEXT2, tr('Вписать в окно'), 14)
        zoom.setLayout(hbox(self.zoom_out, self.zoom_lbl, self.zoom_in, _vsep(16), self.zoom_fit, spacing=0,
                            margins=(1, 1, 1, 1)))
        self.zoom_out.clicked.connect(lambda: self._view().zoom_by(1 / 1.25))
        self.zoom_in.clicked.connect(lambda: self._view().zoom_by(1.25))
        self.zoom_fit.clicked.connect(lambda: self._view().zoom_fit())
        zoom.setFixedHeight(32)
        self.zoom_box = zoom
        head.setLayout(hbox(self.tabbar, None, self.view_info, 10, zoom, spacing=0, margins=(6, 0, 8, 0)))

        self.src_view = SourceView()
        self.src_view.fileDropped.connect(self.load_image)
        self.res_view = CanvasView(smooth=False, mat=True,
                                   placeholder=(tr('Здесь появится результат'),
                                                tr('Сначала добавьте картинку на вкладке «Исходник»')))
        self.dry_view = CanvasView(smooth=False, mat=True,
                                   placeholder=(tr('Dry-run: порядок рисования'),
                                                tr('Нажмите ▶ — программа покажет, как будет рисовать, мышь не двигается')))
        self.stack = QStackedWidget()
        for v in (self.src_view, self.res_view, self.dry_view):
            v.zoomChanged.connect(self._on_zoom_text)
            self.stack.addWidget(v)
        self.badge = Badge(self.stack)

        # dry-run player
        self.dry_bar = _frame("CardHead")
        self.dry_bar.setStyleSheet(f"QFrame#CardHead {{ border-bottom: none; border-top: 1px solid {theme.BORDER}; }}")
        self.dry_bar.setFixedHeight(54)
        self.dry_btn = button("", "Round", "play", theme.ON_ACCENT, tr('Запустить анимацию'), 14)
        self.dry_btn.clicked.connect(self.toggle_dryrun)
        self.dry_counter = label("0 / 0")
        self.dry_counter.setStyleSheet(f"font-family: '{theme.MONO}'; font-size: 13px;")
        self.dry_counter.setMinimumWidth(110)
        self.dry_prog = QProgressBar()
        self.dry_prog.setProperty("state", "info")
        self.dry_prog.setTextVisible(False)
        self.dry_prog.setFixedHeight(4)
        self.dry_speed = QSlider(Qt.Orientation.Horizontal, minimum=1, maximum=10, value=6)
        self.dry_speed.setFixedWidth(110)
        self.dry_speed.setAccessibleName(tr('Скорость анимации'))
        self.dry_bar.setLayout(hbox(self.dry_btn, self.dry_counter, self.dry_prog, 8,
                                    label(tr('Скорость анимации'), "Muted"), self.dry_speed, 8,
                                    label(tr('мышь не двигается'), "Hint"), spacing=14, margins=(14, 0, 14, 0)))
        card.setLayout(vbox(head, self.stack, self.dry_bar, spacing=0))
        self.dry_bar.hide()
        return card

    def _view(self) -> CanvasView:
        return self.stack.currentWidget()  # type: ignore[return-value]

    def _on_tab(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.dry_bar.setVisible(i == 2 and self.job is not None)
        self._update_view_info()
        self._on_zoom_text(self._view().zoom_text())

    def _on_zoom_text(self, _t: str) -> None:
        v = self._view()
        self.zoom_lbl.setText(v.zoom_text())
        self.zoom_box.setVisible(v.has_image())

    def _update_view_info(self) -> None:
        i = self.tabbar.currentIndex()
        if i == 0 and self.image is not None:
            name = Path(self.image_path).name if self.image_path else tr('картинка')
            self.view_info.setText(f"{name} · {self.image.width}×{self.image.height}")
        elif i > 0 and self.job is not None:
            self.view_info.setText(tr('Без сглаживания · как на табличке'))
        else:
            self.view_info.setText("")

    # ---------------------------------------------------------------- log
    def _log_card(self) -> QFrame:
        card = _frame("Card")
        self.log_card = card
        head = _frame("LogHead")
        head.setFixedHeight(36)
        self.log_toggle = button("", "Flat", "chevron-down", theme.TEXT2, tr('Свернуть журнал'), 14)
        self.log_toggle.clicked.connect(self._toggle_log)
        self.log_count = label("", "Hint")
        copy_btn = button(tr('Копировать'), "Ghost")
        clear_btn = button(tr('Очистить'), "Ghost")
        for b in (copy_btn, clear_btn):
            b.setStyleSheet("min-height: 24px; font-size: 12px; padding: 0 10px;")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText("\n".join(self.logbox.lines)))
        clear_btn.clicked.connect(lambda: (self.logbox.clear_all(), self.log_count.setText("")))
        head.setLayout(hbox(self.log_toggle, label(tr('Журнал'), "CardTitle"), self.log_count, None, copy_btn, clear_btn,
                            spacing=8, margins=(8, 0, 8, 0)))
        self.logbox = LogView()
        card.setLayout(vbox(head, self.logbox, spacing=0))
        card.setFixedHeight(150)
        return card

    def _toggle_log(self) -> None:
        open_ = not self.logbox.isVisible()
        self.logbox.setVisible(open_)
        self.log_card.setFixedHeight(150 if open_ else 38)
        self.log_toggle.setIcon(icons.icon("chevron-down" if open_ else "chevron-right", theme.TEXT2, 14))

    # ---------------------------------------------------------------- settings panel
    def _aside(self) -> QFrame:
        aside = _frame("Card")
        aside.setFixedWidth(420)
        head = _frame("CardHead")
        head.setFixedHeight(52)
        self.mode_seg = Segmented([("simple", tr('Простой')), ("adv", tr('Продвинутый'))])
        self.mode_seg.changed.connect(self._on_mode)
        head.setLayout(hbox(label(tr('Настройки'), "PanelTitle"), None, self.mode_seg, margins=(16, 0, 12, 0)))

        self.lock_box = _frame("LockBox")
        lk = label(tr("<b style='color:#E7EEE8'>Настройки заблокированы</b>, пока рисунок не закончен. Нажмите «Стоп», чтобы изменить их — прогресс сохранится."), "Desc", wrap=True)
        self.lock_box.setLayout(hbox(icon_label("lock", theme.TEXT, 16), lk, spacing=10, margins=(12, 10, 12, 10)))
        self.lock_box.hide()

        self.panels = QStackedWidget()
        self.panels.addWidget(self._scroll(self._simple_panel()))
        self.panels.addWidget(self._scroll(self._advanced_panel()))
        aside.setLayout(vbox(head, vbox(self.lock_box, margins=(12, 12, 12, 0)), self.panels, spacing=0))
        return aside

    def _scroll(self, w: QWidget) -> QScrollArea:
        sc = QScrollArea()
        sc.setWidget(w)
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for cb in w.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        return sc

    def _on_mode(self, mode: str) -> None:
        self.panels.setCurrentIndex(0 if mode == "simple" else 1)

    # simple wizard ------------------------------------------------------------
    def _step(self, n: int, title: str, content: QWidget | None, last: bool = False, extra: QWidget | None = None):
        badge = label(str(n), "Step")
        self._steps.append(badge)
        line = _frame("StepLine")
        col = vbox(badge, line if not last else None, spacing=4)
        right = vbox(hbox(label(title, "StepTitle"), None, extra, spacing=6) if extra else
                     hbox(label(title, "StepTitle"), None), spacing=8, margins=(0, 0, 0, 0 if last else 16))
        if content is not None:
            right.addWidget(content)
        w = QWidget()
        w.setLayout(hbox(col, right, spacing=12))
        return w

    def _simple_panel(self) -> QWidget:
        self._steps: list[QLabel] = []
        w = QWidget()
        lay = vbox(spacing=0, margins=(16, 16, 16, 12))

        # 1. picture
        self.s_pic = label(tr('Перетащите файл в окно слева или кликните по нему'), "Desc", wrap=True)
        replace = button(tr('Заменить…'), "Link")
        replace.clicked.connect(self.src_view.browse)
        self.s_replace = replace
        lay.addWidget(self._step(1, tr('Картинка'), self.s_pic, extra=replace))

        # 2. sign + calibration
        box2 = QWidget()
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.setContentsMargins(0, 0, 0, 0)
        self.s_profile_cb = QComboBox()
        self.s_profile_cb.currentTextChanged.connect(self._on_profile)
        s_add = button("", "Icon", "plus", theme.TEXT, tr('Новый профиль (копия текущего)'), 14)
        s_add.clicked.connect(self._new_profile)
        pw = QWidget()
        pw.setLayout(hbox(self.s_profile_cb, s_add, spacing=6))
        self.s_sign_cb = QComboBox()
        self._fill_sign_combo(self.s_sign_cb)
        self.s_sign_cb.currentIndexChanged.connect(lambda: self._on_sign(self.s_sign_cb))
        g.addWidget(field(tr('Профиль'), pw, "profile"), 0, 0)
        g.addWidget(field(tr('Тип таблички'), self.s_sign_cb, "signType"), 0, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        self.s_calib_ok = _frame("OkBox")
        self.s_calib_ok_text = label("", "OkText", wrap=True)
        s_cal_btn = button(tr('Калибровка…'))
        s_cal_btn.setStyleSheet("min-height: 28px; font-size: 12px;")
        s_cal_btn.clicked.connect(self.start_calibration)
        self.s_calib_ok.setLayout(hbox(icon_label("check", theme.ACCENT_TEXT, 16), self.s_calib_ok_text, s_cal_btn,
                                       spacing=10, margins=(12, 6, 6, 6)))
        self.s_calib_warn = _frame("WarnBox")
        self.s_warn_title = label("", "WarnTitle", wrap=True)
        self.s_warn_text = label("", "Body", wrap=True)
        self.s_warn_btn = button(tr('Калибровка…'), "Warn", "calibrate", "#1F1405")
        self.s_warn_btn.clicked.connect(self._simple_fix)
        self.s_calib_warn.setLayout(vbox(hbox(icon_label("warning", theme.WARNING_TEXT, 16),
                                              vbox(self.s_warn_title, self.s_warn_text, spacing=3), spacing=10),
                                         self.s_warn_btn, spacing=10, margins=(12, 12, 12, 12)))
        tools = hbox(None, spacing=4)
        for text, slot in ((tr('Измерить кисть'), self.start_measure), (tr('Тест скорости'), self.start_speed_test)):
            b = button(text, "Link")
            b.clicked.connect(slot)
            tools.insertWidget(tools.count() - 1, b)
        box2.setLayout(vbox(g, self.s_calib_ok, self.s_calib_warn, tools, spacing=10))
        lay.addWidget(self._step(2, tr('Табличка и калибровка'), box2))

        # 3. quality & speed
        box3 = QWidget()
        self.s_algo_cb = QComboBox()
        for v, t in (("hybrid", tr('Гибрид: мазки + точная доводка ★')), ("pixels", tr('Попиксельно (точная копия)')),
                     ("shapes", tr('Только мазки (прозрачные круги)'))):
            self.s_algo_cb.addItem(t, v)
        self.s_algo_cb.currentIndexChanged.connect(lambda: self._set_algorithm(self.s_algo_cb.currentData()))
        self.s_detail = QSlider(Qt.Orientation.Horizontal, minimum=1, maximum=8)
        self.s_detail_val = label("", "Value")
        self.s_detail.valueChanged.connect(self._on_s_detail)
        self.s_speed = QSlider(Qt.Orientation.Horizontal, minimum=5, maximum=30)
        self.s_speed_val = label("", "Value")
        self.s_speed.valueChanged.connect(self._on_s_speed)

        def captions(a: str, b: str):
            return hbox(label(a, "Hint"), None, label(b, "Hint"))

        box3.setLayout(vbox(field(tr('Алгоритм'), self.s_algo_cb, "algo"),
                            field(tr('Детализация — размер «пикселя»'), self.s_detail, "detail", self.s_detail_val),
                            captions(tr('Точнее, но дольше'), tr('Грубее, но быстрее')),
                            field(tr('Скорость рисования'), self.s_speed, "speed", self.s_speed_val),
                            captions(tr('Надёжнее'), tr('Быстрее, больше промахов')), spacing=8))
        lay.addWidget(self._step(3, tr('Качество и скорость'), box3))

        # 4. draw
        t4 = label(tr('Откройте табличку в игре и нажмите «Нарисовать» внизу. Окно свернётся — не трогайте мышь до конца.'), "Desc", wrap=True)
        all_btn = button(tr('Все настройки'), "Link", "chevron-right", theme.ACCENT_TEXT, size=13)
        all_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        all_btn.clicked.connect(lambda: self.mode_seg.set_value("adv", emit=True))
        c4 = QWidget()
        c4.setLayout(vbox(t4, hbox(all_btn, None), spacing=6))
        lay.addWidget(self._step(4, tr('Рисовать'), c4, last=True))
        lay.addStretch(1)
        w.setLayout(lay)
        return w

    def _simple_fix(self) -> None:
        if self.s_warn_btn.property("action") == "measure":
            self.start_measure()
        else:
            self.start_calibration()

    # advanced sections ----------------------------------------------------------
    def _fill_sign_combo(self, cb: QComboBox) -> None:
        cb.addItem(tr('По холсту на экране (авто)'), "auto")
        for key, st in self.cfg.sign_types.items():
            cb.addItem(f"{st.label}  ({st.size[0]}×{st.size[1]})", key)

    def _advanced_panel(self) -> QWidget:
        w = QWidget()
        lay = vbox(spacing=10, margins=(12, 12, 12, 12))

        # sign & calibration
        sec = Section(tr('Табличка и калибровка'), open_=False)
        self.profile_cb = QComboBox()
        self.profile_cb.currentTextChanged.connect(self._on_profile)
        add = button("", "Icon", "plus", theme.TEXT, tr('Новый профиль (копия текущего)'), 14)
        add.clicked.connect(self._new_profile)
        pw = QWidget()
        pw.setLayout(hbox(self.profile_cb, add, spacing=6))
        self.sign_cb = QComboBox()
        self._fill_sign_combo(self.sign_cb)
        self.sign_cb.currentIndexChanged.connect(lambda: self._on_sign(self.sign_cb))
        self.custom_size = QLineEdit()
        self.custom_size.setPlaceholderText("512x256")
        self.custom_size.editingFinished.connect(lambda: self._set("custom_size", self.custom_size.text().strip()))
        self.grid_cols = QSpinBox(minimum=1, maximum=32)
        self.grid_rows = QSpinBox(minimum=1, maximum=64)
        gw = QWidget()
        gw.setLayout(hbox(self.grid_cols, label("×", "Hint"), self.grid_rows, spacing=6))
        tools = QGridLayout()
        tools.setSpacing(8)
        self.calib_btn = button(tr('Калибровка…'), icon="calibrate")
        self.calib_delay_btn = button(tr('Снимок через 5 с'), icon="snapshot")
        self.measure_btn = button(tr('Измерить кисть'), icon="measure")
        self.speedtest_btn = button(tr('Тест скорости'), icon="speed")
        for i, (b, slot, key) in enumerate(((self.calib_btn, self.start_calibration, "calib"),
                                            (self.calib_delay_btn, self.start_calibration_delayed, "snapshot"),
                                            (self.measure_btn, self.start_measure, "measure"),
                                            (self.speedtest_btn, self.start_speed_test, "speedtest"))):
            b.clicked.connect(slot)
            cell = QWidget()
            cell.setLayout(hbox(b, InfoButton(key), spacing=4))
            tools.addWidget(cell, i // 2, i % 2)
        self.calib_status = label("", "Desc", wrap=True)
        self.calib_status_box = _frame("OkBox")
        self.calib_status_box.setLayout(vbox(self.calib_status, margins=(12, 8, 12, 8)))
        sec.add(self._grid2(field(tr('Профиль'), pw, "profile"), field(tr('Тип таблички'), self.sign_cb, "signType"),
                            field(tr('Свой размер'), self.custom_size, "customSize"),
                            field(tr('Избранное (кол × стр)'), gw, "paletteGrid")),
                tools, self.calib_status_box)
        lay.addWidget(sec)

        # image
        sec = Section(tr('Изображение'))
        self.algo_seg = Segmented([("hybrid", tr('Гибрид ★')), ("pixels", tr('Попиксельно')), ("shapes", tr('Только мазки'))])
        self.algo_seg.changed.connect(self._set_algorithm)
        self.algo_desc = label("", "Desc", wrap=True)
        self.shapes_sb = QSpinBox(minimum=100, maximum=100000, singleStep=500)
        self.shapes_sb.valueChanged.connect(
            lambda v: self._set("hybrid_shapes" if self.cfg.settings.algorithm == "hybrid" else "shape_count", v))
        self.tol_sb = QDoubleSpinBox(minimum=1.0, maximum=40.0, singleStep=1.0, decimals=1, suffix=" ΔE")
        self.tol_sb.valueChanged.connect(lambda v: self._set("fix_tolerance", v))
        self.fit_cb = QComboBox()
        for k, t in (("pad", tr('Вписать (поля)')), ("crop", tr('Заполнить (обрезка)')), ("stretch", tr('Растянуть'))):
            self.fit_cb.addItem(t, k)
        self.fit_cb.currentIndexChanged.connect(lambda: self._set("fit", self.fit_cb.currentData()))
        self.transp_cb = QComboBox()
        self.transp_cb.addItem(tr('Заливать цветом фона'), "fill")
        self.transp_cb.addItem(tr('Не рисовать'), "skip")
        self.transp_cb.currentIndexChanged.connect(self._on_transparent)
        self.bg_btn = QPushButton()
        self.bg_btn.setObjectName("Swatch")
        self.bg_btn.clicked.connect(self._pick_background)
        self.mode_cb = QComboBox()
        self.mode_cb.addItem(tr('HEX-ввод (любой цвет, точно)'), "hex")
        self.mode_cb.addItem(tr('Пипетка: 2 клика'), "picker")
        self.mode_cb.addItem(tr('Избранные цвета'), "palette")
        self.mode_cb.currentIndexChanged.connect(self._on_color_mode)
        self.colors_sb = QSpinBox(minimum=0, maximum=256)
        self.colors_sb.setSpecialValueText(tr('авто'))
        self.colors_sb.valueChanged.connect(lambda v: self._set("max_colors", v))
        self.dither_cb = Toggle(tr('Дизеринг Флойда–Стейнберга'))
        self.dither_row = toggle_row(tr('Дизеринг Флойда–Стейнберга'), self.dither_cb, "dither")
        self.dither_cb.toggled.connect(lambda v: self._set("dither", v))
        self.despeckle_sb = QSpinBox(minimum=0, maximum=5)
        self.despeckle_sb.setSpecialValueText(tr('выкл'))
        self.despeckle_sb.valueChanged.connect(lambda v: self._set("despeckle", v))
        self.f_shapes = field(tr('Число мазков'), self.shapes_sb, "strokes")
        self.f_tol = field(tr('Допуск доводки'), self.tol_sb, "tolerance")
        self.f_clean = field(tr('Чистка одиночных пикселей'), self.despeckle_sb, "cleanup")
        sec.add(field(tr('Алгоритм'), self.algo_seg, "algo"), self.algo_desc,
                self._grid2(self.f_shapes, self.f_tol, field(tr('Масштаб'), self.fit_cb, "scale"),
                            field(tr('Прозрачное и поля'), self.transp_cb, "transparent"),
                            field(tr('Цвет фона'), self.bg_btn, "bgColor"), field(tr('Цвета'), self.mode_cb, "colorInput"),
                            field(tr('Число цветов'), self.colors_sb, "colors"), self.f_clean),
                self.dither_row)
        lay.addWidget(sec)

        # brush
        sec = Section(tr('Кисть'))
        self.detail_sb = QSpinBox(minimum=1, maximum=32, suffix=" px")
        self.detail_sb.valueChanged.connect(lambda v: self._set("detail", v))
        self.fill_sb = QSpinBox(minimum=0, maximum=128, suffix=" px")
        self.fill_sb.setSpecialValueText(tr('выкл'))
        self.fill_sb.valueChanged.connect(lambda v: self._set("fill_size", v))
        self.shape_seg = Segmented([("square", tr('Квадратная')), ("circle", tr('Круглая'))])
        self.shape_seg.changed.connect(lambda v: self._set("brush_shape", v))
        self.line_cb = QComboBox()
        self.line_cb.addItem(tr('Бросок к вершине (быстро)'), "jump")
        self.line_cb.addItem(tr('Протяжка мелкими шагами'), "drag")
        self.line_cb.addItem(tr('Shift + линия'), "shift")
        self.line_cb.currentIndexChanged.connect(lambda: self._set("line_mode", self.line_cb.currentData(), False))
        self.basefill_cb = Toggle(tr('Сначала залить фон основным цветом'))
        self.basefill_cb.toggled.connect(lambda v: self._set("base_fill", v))
        bf = toggle_row(tr('Сначала залить фон основным цветом'), self.basefill_cb, "fillFirst")
        self.basefill_row = bf
        self.f_fill = field(tr('Кисть заливки'), self.fill_sb, "fillBrush")
        self.f_shape = field(tr('Форма кисти'), self.shape_seg, "brushShape")
        sec.add(self._grid2(field(tr('Детализация'), self.detail_sb, "detail"), self.f_fill),
                self.f_shape, field(tr('Линии'), self.line_cb, "lines"), bf)
        lay.addWidget(sec)

        # speed
        sec = Section(tr('Скорость и надёжность'), open_=False)
        self.speed_sb = QDoubleSpinBox(minimum=0.1, maximum=5.0, singleStep=0.1, decimals=2, suffix="×")
        self.speed_sb.valueChanged.connect(lambda v: self._set("speed", v, False))
        self.fps_sb = QSpinBox(minimum=0, maximum=500, suffix=" FPS")
        self.fps_sb.setSpecialValueText(tr('не учитывать'))
        self.fps_sb.valueChanged.connect(lambda v: self._set("game_fps", float(v), False))
        self.delay_sb = QSpinBox(minimum=0, maximum=500, suffix=tr(' мс'))
        self.delay_sb.valueChanged.connect(lambda v: self._set("action_delay_ms", float(v), False))
        self.colordelay_sb = QSpinBox(minimum=0, maximum=2000, suffix=tr(' мс'))
        self.colordelay_sb.valueChanged.connect(lambda v: self._set("color_switch_ms", float(v), False))
        self.save_sb = QSpinBox(minimum=0, maximum=100000, suffix=tr(' штрихов'))
        self.save_sb.setSpecialValueText(tr('только в конце'))
        self.save_sb.valueChanged.connect(lambda v: self._set("save_every", v, False))
        self.verify_sb = QSpinBox(minimum=0, maximum=10)
        self.verify_sb.setSpecialValueText(tr('не проверять'))
        self.verify_sb.valueChanged.connect(lambda v: self._set("verify_passes", v, False))
        self.countdown_sb = QSpinBox(minimum=0, maximum=30, suffix=tr(' с'))
        self.countdown_sb.valueChanged.connect(lambda v: self._set("countdown_s", v, False))
        sec.add(self._grid2(field(tr('Скорость'), self.speed_sb, "speed"), field(tr('FPS игры'), self.fps_sb, "fps"),
                            field(tr('Задержка действия'), self.delay_sb, "delay"),
                            field(tr('Пауза смены цвета'), self.colordelay_sb, "colorPause"),
                            field(tr('Сохранять каждые'), self.save_sb, "saveEvery"),
                            field(tr('Проходов проверки'), self.verify_sb, "verify"),
                            field(tr('Отсчёт перед стартом'), self.countdown_sb, "countdown")))
        lay.addWidget(sec)
        lay.addStretch(1)
        w.setLayout(lay)
        return w

    @staticmethod
    def _grid2(*fields_: QWidget) -> QGridLayout:
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(12)
        for i, f in enumerate(fields_):
            g.addWidget(f, i // 2, i % 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        return g

    # ---------------------------------------------------------------- footer
    def _footer(self) -> QFrame:
        f = _frame("Footer")
        f.setFixedHeight(96)
        self.time_caps = label(tr('ОЦЕНКА ВРЕМЕНИ'), "Caps")
        self.eta = label("—:——", "Eta")
        tb = QWidget()
        tb.setFixedWidth(150)
        tb.setLayout(vbox(self.time_caps, self.eta, spacing=2))
        self.line1 = label("", "Line1")
        self.line1b = label("", "Hint")
        self.line1b.setStyleSheet(f"font-size: 12px; color: {theme.HINT};")
        self.warn_line = QWidget()
        self.warn_text = label("", "WarnLine")
        self.warn_line.setLayout(hbox(icon_label("warning", theme.WARNING_TEXT, 14), self.warn_text, None, spacing=6))
        self.line2 = label("", "Muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        info = vbox(hbox(self.line1, self.line1b, None, spacing=10), self.warn_line, self.line2, self.progress, spacing=7)
        hk = self.cfg.hotkeys
        self.preview_btn = button(tr('Предпросмотр'), icon="preview")
        self.preview_btn.clicked.connect(lambda: self.rebuild_preview(show=True))
        self.resume_btn = button(tr('Продолжить'), icon="resume")
        self.resume_btn.clicked.connect(self._on_resume)
        self.pause_btn = button(tr('Пауза  {0}').format(hk['pause'].upper()), "Ghost", "pause", theme.TEXT2, size=15)
        self.pause_btn.clicked.connect(lambda: self.ctl and self.ctl.toggle_pause())
        self.stop_btn = button(tr('Стоп  {0}').format(hk['stop'].upper()), "Danger", "stop", size=14)
        self.stop_btn.clicked.connect(self.stop_all)
        self.paint_btn = button(tr('Нарисовать'), "Primary", "draw", size=20)
        self.paint_btn.clicked.connect(lambda: self.start_paint(resume=False))
        lay = hbox(tb, _vsep(52), 4, info, 12, self.preview_btn, self.resume_btn, self.pause_btn,
                   self.stop_btn, self.paint_btn, spacing=8, margins=(20, 0, 20, 0))
        lay.setStretchFactor(info, 1)
        f.setLayout(lay)
        return f

    def _footer_set(self, caps: str, eta: str, eta_state: str, line1: str, line1b: str = "", line2: str = "",
                    warn: str = "", progress: float | None = None, pstate: str = "") -> None:
        self.time_caps.setText(caps)
        self.eta.setText(eta)
        theme.set_state(self.eta, eta_state)
        self.line1.setText(line1)
        self.line1b.setText(line1b)
        self.line2.setText(line2)
        self.line2.setVisible(bool(line2))
        self.warn_text.setText(warn)
        self.warn_line.setVisible(bool(warn))
        self.progress.setMaximum(1000)
        self.progress.setValue(int((progress or 0) * 1000))
        theme.set_state(self.progress, pstate)

    # ================================================================ settings <-> UI
    def _load_settings_into_ui(self) -> None:
        s = self.cfg.settings
        was = self._loading
        self._loading = True
        names = list(self.cfg.profiles)
        for cb in (self.profile_cb, self.s_profile_cb):
            cb.clear()
            cb.addItems(names)
            cb.setCurrentText(self.cfg.active_profile)
        for cb in (self.sign_cb, self.s_sign_cb):
            cb.setCurrentIndex(max(0, cb.findData(s.sign_type)))
        self.custom_size.setText(s.custom_size)
        self.custom_size.setEnabled(s.sign_type == "custom")
        self.algo_seg.set_value(s.algorithm)
        self.s_algo_cb.setCurrentIndex(max(0, self.s_algo_cb.findData(s.algorithm)))
        self.algo_desc.setText(tr(ALGO_DESC.get(s.algorithm, "")))
        self.shapes_sb.setValue(s.hybrid_shapes if s.algorithm == "hybrid" else s.shape_count)
        self.tol_sb.setValue(s.fix_tolerance)
        self.despeckle_sb.setValue(s.despeckle)
        self.fps_sb.setValue(int(s.game_fps))
        self.fit_cb.setCurrentIndex(max(0, self.fit_cb.findData(s.fit)))
        self.transp_cb.setCurrentIndex(max(0, self.transp_cb.findData(s.transparent)))
        self.bg_btn.setEnabled(s.transparent != "skip")
        self._show_bg()
        self.mode_cb.setCurrentIndex(max(0, self.mode_cb.findData(s.color_mode)))
        self.colors_sb.setValue(s.max_colors)
        self.dither_cb.setChecked(s.dither)
        self.detail_sb.setValue(s.detail)
        self.s_detail.setValue(min(8, max(1, s.detail)))
        self.s_detail_val.setText(f"{s.detail} px")
        self.fill_sb.setValue(s.fill_size)
        self.shape_seg.set_value(s.brush_shape)
        self.line_cb.setCurrentIndex(max(0, self.line_cb.findData(s.line_mode)))
        self.basefill_cb.setChecked(s.base_fill)
        self.speed_sb.setValue(s.speed)
        self.s_speed.setValue(int(round(min(3.0, max(0.5, s.speed)) * 10)))
        self.s_speed_val.setText(_dec(f"{s.speed:.2f}×"))
        self.delay_sb.setValue(int(s.action_delay_ms))
        self.colordelay_sb.setValue(int(s.color_switch_ms))
        self.save_sb.setValue(s.save_every)
        self.verify_sb.setValue(s.verify_passes)
        self.countdown_sb.setValue(s.countdown_s)
        pg = self.cfg.profile.palette_grid
        self.grid_cols.setValue(pg.cols)
        self.grid_rows.setValue(pg.rows)
        self._sync_algorithm_widgets()
        self._loading = was

    def _set(self, name: str, value, replan: bool = True) -> None:
        if self._loading:
            return
        setattr(self.cfg.settings, name, value)
        self._save_cfg()
        self._load_settings_into_ui()        # keep the simple and the advanced panel in sync
        self._refresh_all()
        if replan:
            self._refresh_timer.start()
        else:
            self._update_stats()

    def _save_cfg(self) -> None:
        try:
            self.cfg.save()
        except OSError as e:
            self.log(tr('⚠ Не удалось сохранить config.json: {0}').format(e))

    def _set_algorithm(self, algo: str) -> None:
        if self._loading or not algo:
            return
        self._set("algorithm", algo)

    def _on_s_detail(self, v: int) -> None:
        self.s_detail_val.setText(f"{v} px")
        self._set("detail", v)

    def _on_s_speed(self, v: int) -> None:
        self.s_speed_val.setText(_dec(f"{v / 10:.2f}×"))
        self._set("speed", v / 10, False)

    def _on_transparent(self) -> None:
        self._set("transparent", self.transp_cb.currentData())

    def _on_color_mode(self) -> None:
        self._set("color_mode", self.mode_cb.currentData())

    def _sync_algorithm_widgets(self) -> None:
        algo = self.cfg.settings.algorithm
        self.shapes_sb.setEnabled(algo in ("shapes", "hybrid"))
        self.tol_sb.setEnabled(algo == "hybrid")
        for w in (self.detail_sb, self.line_cb):
            w.setEnabled(algo in ("pixels", "hybrid"))
        for w in (self.dither_cb, self.despeckle_sb, self.fill_sb, self.basefill_cb):
            w.setEnabled(algo == "pixels")
        self.shape_seg.setEnabled(algo == "pixels")
        self.verify_sb.setEnabled(algo in ("pixels", "hybrid"))
        for f, on in ((self.f_shapes, algo in ("shapes", "hybrid")), (self.f_tol, algo == "hybrid"),
                      (self.f_clean, algo == "pixels"), (self.f_fill, algo == "pixels"),
                      (self.f_shape, algo == "pixels"), (self.dither_row, algo == "pixels"),
                      (self.basefill_row, algo == "pixels")):
            f.label.setEnabled(on)

    def _on_sign(self, cb: QComboBox) -> None:
        if self._loading:
            return
        self._set("sign_type", cb.currentData())

    def _on_profile(self, name: str) -> None:
        if self._loading or not name or name == self.cfg.active_profile:
            return
        self.cfg.active_profile = name
        self._save_cfg()
        self._load_settings_into_ui()
        self._refresh_all()
        self._refresh_timer.start()

    def _new_profile(self) -> None:
        scr = QGuiApplication.primaryScreen().size()
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        default = f"{int(scr.width() * dpr)}x{int(scr.height() * dpr)}"
        name, ok = QInputDialog.getText(self, tr('Новый профиль'), tr('Имя профиля (копия текущего):'), text=default)
        if ok and name.strip():
            try:
                self.cfg.add_profile(name.strip())
            except ValueError as e:
                dialogs.info(self, tr('Профиль'), str(e), kind="warn", icon="warning")
                return
            self.cfg.active_profile = name.strip()
            self._save_cfg()
            self.log(tr('Создан профиль «{0}»').format(name.strip()))
            self._load_settings_into_ui()
            self._refresh_all()

    def _pick_background(self) -> None:
        c = QColorDialog.getColor(QColor(self.cfg.settings.background), self, tr('Цвет фона'))
        if c.isValid():
            self._set("background", to_hex((c.red(), c.green(), c.blue())))

    def _show_bg(self) -> None:
        bg = self.cfg.settings.background
        r, g, b = parse_color(bg)
        fg = "#000" if r + g + b > 380 else "#fff"
        self.bg_btn.setText(bg.upper())
        self.bg_btn.setStyleSheet(f"QPushButton#Swatch {{ background: {bg}; color: {fg}; }}")

    # ================================================================ state refresh
    def _refresh_all(self) -> None:
        self._update_chips()
        self._update_calibration_status()
        self._update_steps()
        self._update_buttons()
        self._update_footer()

    def _calib_missing(self) -> list[str]:
        s = self.cfg.settings
        return self.cfg.profile.missing_calibration(s.color_mode, s.algorithm)

    def _update_chips(self) -> None:
        s = self.cfg.settings
        self.chip_profile.set(tr('Профиль'), self.cfg.active_profile)
        if s.game_fps:
            self.chip_fps.set(f"{s.game_fps:.0f} FPS", state="neutral")
        else:
            self.chip_fps.set(tr('FPS не задан'), state="warn")
        if self.ctl is not None:
            if self.ctl.paused:
                pct = f" · {round(self._paint_fraction() * 100)}%" if self._paint_total else ""
                self.chip_calib.set(tr('Пауза') + pct, state="warn", icon="pause")
            else:
                self.chip_calib.set(tr('● Рисую'), state="busy", icon="draw")
        elif self._calib_missing():
            self.chip_calib.set(tr('Нужна калибровка'), state="warn", icon="warning")
        else:
            self.chip_calib.set(tr('Откалибровано'), state="ok", icon="check")

    def _update_calibration_status(self) -> None:
        p = self.cfg.profile
        miss = self._calib_missing()
        if miss:
            text = tr('Не откалибровано: ') + ", ".join(tr(CALIB_NAMES.get(m, m)) for m in miss)
            self.calib_status.setText("⚠ " + text)
            self.calib_status_box.setObjectName("WarnBox")
            self.s_calib_ok.hide()
            self.s_calib_warn.show()
            self.s_warn_title.setText(text)
            self.s_warn_text.setText(tr('Откройте в игре редактор таблички и нажмите «Калибровка». Займёт около минуты.'))
            self.s_warn_btn.setText(tr('Калибровка…'))
            self.s_warn_btn.setProperty("action", "calib")
        else:
            x0, y0, x1, y1 = p.canvas  # type: ignore[misc]
            text = tr('Холст {0}×{1} px · кисть {2}').format(x1 - x0 + 1, y1 - y0 + 1, 'измерена' if p.size_measured else 'не измерена')
            self.calib_status.setText("✓ " + text)
            self.calib_status_box.setObjectName("OkBox")
            if p.size_measured:
                self.s_calib_warn.hide()
                self.s_calib_ok.show()
                self.s_calib_ok_text.setText(tr('Холст {0}×{1} px, кисть измерена').format(x1 - x0 + 1, y1 - y0 + 1))
            else:
                self.s_calib_ok.hide()
                self.s_calib_warn.show()
                self.s_warn_title.setText(tr('Кисть не измерена'))
                self.s_warn_text.setText(tr('Без измерения размер «пикселя» может не совпасть с кистью в игре — появятся щели. Измерение ставит 2 точки и стирает их.'))
                self.s_warn_btn.setText(tr('Измерить кисть'))
                self.s_warn_btn.setProperty("action", "measure")
        self.calib_status_box.style().unpolish(self.calib_status_box)
        self.calib_status_box.style().polish(self.calib_status_box)

    def _update_steps(self) -> None:
        if not self._steps:
            return
        has = self.image is not None
        calib_ok = not self._calib_missing() and self.cfg.profile.size_measured
        states = ["done" if has else "active", "done" if calib_ok else "warn",
                  "done" if has else "todo", "active" if has and calib_ok else "todo"]
        for i, (b, st) in enumerate(zip(self._steps, states)):
            b.setText("✓" if st == "done" else str(i + 1))
            theme.set_state(b, st)
        if has:
            name = Path(self.image_path).name if self.image_path else tr('картинка')
            self.s_pic.setText(f"{name} · {self.image.width}×{self.image.height}")
        else:
            self.s_pic.setText(tr('Перетащите файл в окно слева или кликните по нему'))
        self.s_replace.setVisible(has)

    def _update_buttons(self) -> None:
        painting = self.ctl is not None
        paused = painting and self.ctl.paused
        has_job = self.job is not None and not self._planning
        self.paint_btn.setEnabled(not painting and has_job and not self._calib_missing())
        self.preview_btn.setEnabled(not painting and self.image is not None and not self._planning)
        self.resume_btn.setEnabled(paused or (not painting and self.progress_path.exists()))
        self.resume_btn.setObjectName("PrimarySm" if paused else "")
        self.resume_btn.style().unpolish(self.resume_btn)
        self.resume_btn.style().polish(self.resume_btn)
        self.pause_btn.setEnabled(painting and not paused)
        self.stop_btn.setEnabled(painting)
        self.panels.setEnabled(not painting)
        self.lock_box.setVisible(painting)
        self.mode_seg.setEnabled(not painting)
        self.lang_seg.setEnabled(not painting)

    def _paint_fraction(self) -> float:
        return self.progress.value() / 1000 if self._paint_total else 0.0

    def _update_footer(self) -> None:
        if self.ctl is not None:
            return                       # painting updates the footer itself
        if self.image is None:
            self._footer_set(tr('ОЦЕНКА ВРЕМЕНИ'), "—:——", "dim", tr('Нет картинки'),
                             line2=tr('Добавьте картинку — здесь появятся оценка времени и статистика'))
            return
        if self._planning or self.job is None:
            return
        self._update_stats()

    # ================================================================ image & preview
    def load_image(self, path: str) -> None:
        try:
            img = Image.open(path)
            img.load()
        except Exception as e:
            dialogs.error(self, tr('Не удалось открыть картинку'), str(e))
            return
        self._set_image(img, path)

    def paste_image(self) -> None:
        cb = QGuiApplication.clipboard()
        md = cb.mimeData()
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.load_image(u.toLocalFile())
                    return
        qimg = cb.image()
        if qimg.isNull():
            self.log(tr('В буфере обмена нет картинки'))
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        qimg.save(buf, "PNG")
        img = Image.open(io.BytesIO(bytes(buf.data())))
        img.load()
        path = Path(tempfile.gettempdir()) / "signbrush_clipboard.png"
        img.save(path)
        self._set_image(img, str(path))

    def _set_image(self, img: Image.Image, path: str) -> None:
        self.image, self.image_path = img, path
        self.src_view.set_image(img)
        self.log(tr('Загружено: {0} ({1}×{2})').format(Path(path).name, img.width, img.height))
        self._update_view_info()
        self.rebuild_preview(show=True)

    def rebuild_preview(self, show: bool = False) -> None:
        if self.image is None:
            return
        self._gen += 1
        gen = self._gen
        self._planning = True
        self._footer_set(tr('ОЦЕНКА ВРЕМЕНИ'), "…", "dim", tr('Считаю план…'), progress=0)
        self.badge.show_text(tr('Считаю план…'), tr('Можно менять настройки — пересчитаю'), "speed")
        self._update_buttons()
        img, cfg = self.image.copy(), self.cfg

        def progress(stage: str, frac: float) -> None:
            self.bridge.event.emit("job_progress", (gen, frac))

        def work():
            try:
                job = build_job(img, cfg, progress=progress, cancel=lambda: gen != self._gen)
                self.bridge.event.emit("job", (gen, job, show))
            except Cancelled:
                pass
            except Exception as e:
                self.bridge.event.emit("job", (gen, e, show))

        threading.Thread(target=work, daemon=True).start()

    def _on_job(self, gen: int, job, show: bool) -> None:
        if gen != self._gen:
            return
        self._planning = False
        self.badge.hide()
        if isinstance(job, Exception):
            self._footer_set(tr('ОЦЕНКА ВРЕМЕНИ'), "—", "dim", tr('Ошибка расчёта'), line2=str(job))
            self.log(tr('Ошибка расчёта плана: {0}').format(job), )
            self._update_buttons()
            return
        self.job = job
        self._renderer = None
        self._anim.stop()
        self._set_play_icon(False)
        g = job.geometry
        self.res_view.set_image(job.preview)
        self.dry_view.set_image(None)
        self.dry_counter.setText(f"0 / {_num(len(job.plan.strokes))}")
        self.dry_prog.setValue(0)
        sm = job.plan.summary()
        self.log(tr('План готов: {0} штрихов, {1} смен цвета').format(_num(sm['strokes']), sm['color_switches']))
        if show:
            self.tabbar.setCurrentIndex(1)
        self._on_tab(self.tabbar.currentIndex())
        self._refresh_all()

    def _update_stats(self) -> None:
        job = self.job
        if not job or self.ctl is not None:
            return
        from ..planner import estimate_seconds
        est = estimate_seconds(job.plan, self.cfg.settings.timing(), job.screen_cell_px)
        g, sm = job.geometry, job.plan.summary()
        used = job.colors_used()
        if job.algorithm == "shapes":
            line1b = tr('текстура {0}×{1} · мазки').format(g.texture[0], g.texture[1])
            line2 = tr('Цветов {0} · мазков {1} · смен цвета {2}').format(used, _num(sm['strokes']), sm['color_switches'])
        elif job.algorithm == "hybrid":
            ph = sm["phases"]
            line1b = tr('сетка {0}×{1} · гибрид').format(g.cols, g.rows)
            line2 = (tr('Цветов {0} · мазков {1} · доводка {2} · смен цвета {3}').format(used, _num(ph.get('shape', 0)), _num(ph.get('fix', 0)), sm['color_switches']))
        else:
            line1b = tr('сетка {0}×{1} · клетка {2} px').format(g.cols, g.rows, g.cell_tex)
            line2 = tr('Цветов {0} · штрихов {1} · смен цвета {2}').format(used, _num(sm['strokes']), sm['color_switches'])
        fps = self.cfg.settings.game_fps
        if fps:
            line2 += tr(' · при {0:.0f} FPS').format(fps)
        miss = self._calib_missing()
        warn = tr('Рисовать нельзя: не хватает калибровки — шаг 2 справа') if miss else ""
        self._footer_set(tr('ОЦЕНКА ВРЕМЕНИ'), "≈ " + format_duration(est), "", job.sign.label, line1b,
                         "" if warn else line2, warn, 0)

    # ================================================================ dry-run
    def _set_play_icon(self, playing: bool) -> None:
        self.dry_btn.setIcon(icons.icon("pause" if playing else "play", theme.ON_ACCENT, 14))
        self.dry_btn.setToolTip(tr('Пауза анимации') if playing else tr('Запустить анимацию'))

    def toggle_dryrun(self) -> None:
        if not self.job:
            self.rebuild_preview(show=False)
            return
        if self._anim.isActive():
            self._anim.stop()
            self._set_play_icon(False)
            return
        if self._renderer is None or self._renderer.finished():
            g = self.job.geometry
            self._renderer = PlanRenderer(self.job.plan, scale=max(1, 900 // max(g.cols, g.rows)),
                                          blank=self.job.sign.blank)
        self.tabbar.setCurrentIndex(2)
        self._set_play_icon(True)
        self._anim.start()

    def _anim_tick(self) -> None:
        r = self._renderer
        if not r:
            return
        total = len(r.plan.strokes)
        per = max(1, int(total * (self.dry_speed.value() / 10) ** 2 / 60) + 1)
        r.step(per)
        self.dry_view.set_image(r.image)
        self.dry_counter.setText(f"{_num(r.done)} / {_num(total)}")
        self.dry_prog.setMaximum(max(1, total))
        self.dry_prog.setValue(r.done)
        if r.finished():
            self._anim.stop()
            self._set_play_icon(False)

    # ================================================================ calibration
    def show_help(self) -> None:
        hk = self.cfg.hotkeys
        dialogs.Dialog(
            self, tr('Как пользоваться'),
            tr('1. Перетащите картинку в окно слева.\n2. Откройте в игре редактор таблички и нажмите «Калибровка» — один раз на разрешение экрана. Потом «Измерить кисть» и «Тест скорости».\n3. Выберите алгоритм и детализацию, посмотрите «Результат» и «Dry-run».\n4. Нажмите «Нарисовать» и переключитесь в игру за время отсчёта.'),
            icon="help", keys=[(hk["stop"].upper(), tr('стоп в любой момент')), (hk["pause"].upper(), tr('пауза / продолжить')),
                               (hk["capture"].upper(), tr('снимок экрана для калибровки'))],
            buttons=[(tr('Понятно'), "ok", "PrimarySm")], width=560).exec()

    def start_calibration(self) -> None:
        self.awaiting_capture = True
        key = self.cfg.hotkeys["capture"].upper()
        self.log(tr('Калибровка: откройте в Rust редактор таблички и нажмите {0}').format(key))
        role = dialogs.Dialog(
            self, tr('Калибровка'),
            tr('Откройте в игре редактор нужной таблички (режим окна: «Без рамки»). Нажмите клавишу ниже — программа сделает снимок экрана, и вы разметите на нём холст и элементы управления. В игру ничего не кликается.'),
            icon="calibrate", keys=[(key, tr('снимок экрана из игры'))],
            note=("", tr('Займёт около минуты. Повторять нужно только после смены разрешения или масштаба интерфейса.')),
            buttons=[(tr('Снимок через 5 с'), "<delay", "Ghost"), (tr('Понятно, жду клавишу'), "ok", "PrimarySm")]).exec_role()
        if role == "delay":
            self.start_calibration_delayed()

    def start_calibration_delayed(self) -> None:
        self.awaiting_capture = True
        self.log(tr('Снимок через 5 секунд — переключитесь в игру…'))
        QTimer.singleShot(5000, self.capture_for_calibration)

    def capture_for_calibration(self) -> None:
        if not self.awaiting_capture:
            return
        self.awaiting_capture = False
        from ..screen import grab_monitor_at
        try:
            shot, origin, size = grab_monitor_at(cursor_pos())
        except Exception as e:
            self.log(tr('⚠ Снимок экрана не удался: {0}').format(e))
            return
        prof = self.cfg.profile
        ox, oy = origin
        rel = lambda p: (p[0] - ox, p[1] - oy) if p else None
        prefill: dict[str, tuple] = {}
        if prof.canvas:
            x0, y0, x1, y1 = prof.canvas
            prefill["canvas"] = (rel((x0, y0)), rel((x1, y1)))
        pg = prof.palette_grid
        if pg.first and pg.last:
            prefill["palette"] = (rel(pg.first), rel(pg.last))
        for name, ctl in prof.controls.items():
            if ctl.slider_min and ctl.slider_max:
                prefill[f"{name}_slider"] = (rel(ctl.slider_min), rel(ctl.slider_max))
            if ctl.textbox:
                prefill[f"{name}_textbox"] = (rel(ctl.textbox),)
        for b, pos in prof.buttons.items():
            if pos:
                prefill[b] = (rel(pos),)
        if prof.picker_sv:
            x0, y0, x1, y1 = prof.picker_sv
            prefill["picker_sv"] = (rel((x0, y0)), rel((x1, y1)))
        if prof.picker_hue:
            prefill["picker_hue"] = (rel(prof.picker_hue[0]), rel(prof.picker_hue[1]))
        sign = self.cfg.sign()
        grid = (self.grid_cols.value(), self.grid_rows.value())
        ov = CalibrationOverlay(shot, prefill, grid, aspect=sign.size[0] / sign.size[1],
                                caption=tr('Снимок заморожен · {0}×{1} · профиль «{2}»').format(size[0], size[1], self.cfg.active_profile))
        ov.finished.connect(lambda res: self._calibration_done(res, shot, origin, size, grid))
        ov.cancelled.connect(lambda: self.log(tr('Калибровка отменена')))
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        ov.setGeometry(scr.geometry())
        ov.showFullScreen()
        ov.raise_()
        ov.activateWindow()
        self._overlay = ov

    def _calibration_done(self, results: dict, shot, origin, size, grid) -> None:
        try:
            warns = apply_results(self.cfg.profile, results, shot, origin, size, grid)
        except ValueError as e:
            dialogs.info(self, tr('Калибровка'), str(e), kind="warn", icon="warning")
            return
        self._save_cfg()
        for w in warns:
            self.log("⚠ " + w)
        self.log(tr('✓ Калибровка сохранена в профиль «{0}»').format(self.cfg.active_profile))
        self._load_settings_into_ui()
        self._refresh_all()
        self.rebuild_preview()

    # ================================================================ painting
    def _on_resume(self) -> None:
        if self.ctl is not None and self.ctl.paused:
            self.ctl.resume()
            self._refresh_all()
        else:
            self.start_paint(resume=True)

    def start_paint(self, resume: bool) -> None:
        s, prof = self.cfg.settings, self.cfg.profile
        color_mode = s.color_mode
        if resume:
            try:
                prog = Progress.load(self.progress_path)
            except Exception as e:
                dialogs.info(self, tr('Продолжить'), tr('Нет сохранённого прогресса: {0}').format(e), kind="warn", icon="warning")
                return
            meta = prog.meta
            plan, start = prog.plan, prog.next_index
            geo = Geometry(tuple(meta["texture"]), int(meta["cell_tex"]), plan.cols, plan.rows)
            target = _decode_target(meta["target"]) if meta.get("target") else None
            expected = _decode_rgb(meta["expected"]) if meta.get("expected") else None
            skip = _decode_target(meta["skip"]).astype(bool) if meta.get("skip") else None
            color_mode = meta.get("color_mode") or ("hex" if meta.get("hex_mode") else color_mode)
            if prog.canvas and prof.canvas and tuple(prog.canvas) != tuple(prof.canvas):
                if not dialogs.ask(self, tr('Калибровка изменилась'),
                                   tr('Холст откалиброван иначе, чем при прошлом рисовании. Всё равно продолжить?'),
                                   ok=tr('Продолжить'), kind="warn", icon="warning"):
                    return
        else:
            if not self.job:
                dialogs.info(self, tr('Нарисовать'), tr('Сначала загрузите картинку.'), icon="image")
                return
            plan, geo, start = self.job.plan, self.job.geometry, 0
            target, expected, skip = self.job.fix_indices, self.job.expected_rgb, self.job.skip_mask
            meta = {"texture": list(geo.texture), "cell_tex": geo.cell_tex, "color_mode": color_mode,
                    "sign": self.job.sign.key, "image": self.image_path, "algorithm": self.job.algorithm,
                    "target": _encode_target(target) if target is not None else None,
                    "expected": _encode_rgb(expected) if expected is not None else None,
                    "skip": _encode_target(skip.astype(np.int32)) if skip is not None else None}
        algo = "shapes" if any(st.alpha < 0.999 for st in plan.strokes) else "pixels"  # needs opacity?
        miss = prof.missing_calibration(color_mode, algo)
        if miss:
            dialogs.info(self, tr('Не хватает калибровки'), ", ".join(tr(CALIB_NAMES.get(m, m)) for m in miss).capitalize()
                         + tr('. Нажмите «Калибровка…» в настройках.'), kind="warn", icon="warning")
            return
        if not prof.size_measured:
            role = dialogs.Dialog(
                self, tr('Кисть не измерена'),
                tr('Без измерения размер «пикселя» может не совпасть с кистью в игре — появятся щели или наложения. Измерение ставит 2 точки в углу холста и стирает их.'), kind="warn", icon="warning",
                buttons=[(tr('Рисовать без измерения'), "<anyway", "Ghost"), (tr('Отмена'), "cancel", "Outline"),
                         (tr('Измерить кисть'), "measure", "PrimarySm")]).exec_role()
            if role == "measure":
                self.start_measure()
                return
            if role != "anyway":
                return
        from ..planner import Plan, estimate_seconds
        rest = Plan(plan.cols, plan.rows, plan.palette, plan.brushes, plan.strokes[start:], plan.shape, plan.tips)
        est = estimate_seconds(rest, s.timing(), (prof.canvas[2] - prof.canvas[0] + 1) / plan.cols)
        hk = self.cfg.hotkeys
        changes = sum(1 for a, b in zip(rest.strokes, rest.strokes[1:]) if a.color != b.color) + 1
        if s.confirm_start:
            d = dialogs.Dialog(
                self, tr('Продолжить рисование?') if start else tr('Начать рисование?'),
                tr('Откройте в игре редактор таблички. После отсчёта программа будет сама водить мышью.'),
                stats=[(tr('Время'), "≈ " + format_duration(est)), (tr('Штрихов'), _num(len(rest.strokes))),
                       (tr('Смен цвета'), _num(changes))],
                keys=[(hk["stop"].upper(), tr('стоп в любой момент')), (hk["pause"].upper(), tr('пауза / продолжить')),
                      ("icon:mouse", tr('Не трогайте мышь — сдвиг поставит паузу'))],
                risk=tr('Программа эмулирует ввод мыши. Используйте на свой риск: правила серверов и античит могут запрещать автоматизацию.'),
                checkbox=tr('Больше не спрашивать'),
                buttons=[(tr('Отмена'), "cancel", "Outline"), (tr('Старт через {0} с').format(s.countdown_s), "ok", "PrimarySm")])
            if d.exec_role() != "ok":
                return
            if d.checked():
                s.confirm_start = False
                self._save_cfg()
        self.ctl = Controller()
        self._paint_started = time.monotonic()
        self._paint_start_index = start
        self._paint_total = len(plan.strokes)
        self._footer_set(tr('ОСТАЛОСЬ'), "~" + format_duration(est), "", tr('Подготовка…'), f"{start} / {self._paint_total}",
                         progress=start / max(1, self._paint_total))
        self._refresh_all()
        self.hud.place()
        self.hud.show_state("countdown", tr('Старт через… переключитесь в игру'),
                            tr('Откройте редактор таблички · {0} — отмена').format(hk['stop'].upper()), fraction=0,
                            number=s.countdown_s)
        self.hud.show()
        self.showMinimized()
        args = (plan, geo, target, expected, skip, start, color_mode, meta, self.ctl)
        threading.Thread(target=self._paint_thread, args=args, daemon=True).start()

    def _begin_tool(self, title: str) -> Controller:
        self.ctl = Controller()
        self._paint_total = 0
        self._refresh_all()
        self.hud.place()
        self.hud.show_state("info", title, tr('{0} — стоп').format(self.cfg.hotkeys['stop'].upper()))
        self.hud.show()
        self.showMinimized()
        return self.ctl

    def start_measure(self) -> None:
        prof, s = self.cfg.profile, self.cfg.settings
        if not prof.canvas or not prof.controls["size"].usable:
            dialogs.info(self, tr('Измерить кисть'), tr('Сначала откалибруйте холст и размер кисти.'), kind="warn",
                         icon="warning")
            return
        color_mode = s.color_mode
        if {"hex_field", "picker", "palette"} & set(prof.missing_calibration(color_mode)):
            dialogs.info(self, tr('Измерить кисть'), tr('Сначала откалибруйте выбор цвета (HEX-поле, пипетку или палитру).'),
                         kind="warn", icon="warning")
            return
        sign = self.cfg.sign()
        if not dialogs.ask(self, tr('Измерить кисть'),
                           tr('Откройте в игре табличку того же типа, что выбран здесь: «{0}». В правом нижнем углу холста появятся 2 пробные точки — по скриншоту программа узнает размер кисти и сотрёт их (Ctrl+Z).').format(sign.label), ok=tr('Измерить через {0} с').format(s.countdown_s), icon="measure"):
            return
        ctl = self._begin_tool(tr('Измерение кисти…'))
        threading.Thread(target=self._measure_thread, args=(ctl, sign, color_mode), daemon=True).start()

    def _measure_thread(self, ctl: Controller, sign, color_mode: str) -> None:
        from ..executor import MeasureError, Stopped, measure_size_scale
        from ..planner import Plan
        from ..screen import grab
        emit = lambda k, d: self.bridge.event.emit(k, d)
        s, prof = self.cfg.settings, self.cfg.profile
        try:
            for i in range(s.countdown_s, 0, -1):
                emit("countdown", i)
                if ctl.stop_event.wait(1.0):
                    emit("finished", "stopped")
                    return
            plan = Plan(1, 1, prof.palette_rgb(), {"fine": 1.0})
            ex = Executor(plan, None, prof, s, WinMouse(), WinKeyboard(), ctl, on_event=emit,  # type: ignore[arg-type]
                          color_mode=color_mode)
            debug_dir = (self.cfg.path.parent if self.cfg.path else app_dir()) / "debug"
            scale = measure_size_scale(ex, grab, sign.size[0], on_event=emit, debug_dir=debug_dir)
            emit("measured", scale)
            emit("finished", "measured")
        except Stopped:
            emit("finished", "stopped")
        except MeasureError as e:
            emit("fail", str(e))
        except Exception:
            emit("error", traceback.format_exc())

    SPEED_FRAMES = (2.0, 1.5, 1.0, 0.5, 0.0)

    def start_speed_test(self) -> None:
        prof, s = self.cfg.profile, self.cfg.settings
        miss = prof.missing_calibration(s.color_mode)
        if miss:
            dialogs.info(self, tr('Тест скорости'), tr('Сначала откалибруйте: ') + ", ".join(tr(CALIB_NAMES.get(m, m)) for m in miss),
                         kind="warn", icon="warning")
            return
        if s.game_fps <= 0:
            dialogs.info(self, tr('Тест скорости'), tr('Укажите FPS игры в настройках скорости.'), kind="warn", icon="warning")
            return
        if not dialogs.ask(self, tr('Тест скорости'),
                           tr('Нарисую {0} зигзагов с точками в верхней части холста и проверю снимком, успевает ли игра. Займёт ~20 секунд, потом подберу паузу автоматически и сотру тест (Ctrl+Z).').format(len(self.SPEED_FRAMES)), ok=tr('Запустить тест'), icon="speed",
                           note=("", tr('Держите в игре тот же FPS, что и при рисовании ({0:.0f}). Холст должен быть открыт.').format(s.game_fps))):
            return
        ctl = self._begin_tool(tr('Тест скорости…'))
        threading.Thread(target=self._speed_thread, args=(ctl,), daemon=True).start()

    def _speed_thread(self, ctl: Controller) -> None:
        from ..executor import Stopped, line_test, recommend_frames, speed_test
        from ..planner import Plan
        from ..screen import grab
        emit = lambda k, d: self.bridge.event.emit(k, d)
        s, prof = self.cfg.settings, self.cfg.profile
        try:
            for i in range(s.countdown_s, 0, -1):
                emit("countdown", i)
                if ctl.stop_event.wait(1.0):
                    emit("finished", "stopped")
                    return
            sign = self.cfg.sign()
            cell = max(1, int(s.detail))
            x0, _, x1, _ = prof.canvas
            brush_px = cell * (x1 - x0 + 1) / sign.size[0]
            palette = prof.palette_rgb() if s.color_mode == "palette" else [(0, 0, 0), (255, 255, 255), (255, 0, 255)]
            plan = Plan(1, 1, palette, {"fine": 1.0})
            ex = Executor(plan, None, prof, s, WinMouse(), WinKeyboard(), ctl, on_event=emit,  # type: ignore[arg-type]
                          color_mode=s.color_mode)
            results = speed_test(ex, grab, self.SPEED_FRAMES, s.game_fps, prof.size_value(cell), brush_px,
                                 on_event=emit)
            cov = line_test(ex, grab, prof.size_value(cell * 2), 2.0 / s.game_fps, on_event=emit)
            emit("speed_done", recommend_frames(results))
            emit("line_done", cov)
            emit("finished", "speedtest")
        except Stopped:
            emit("finished", "stopped")
        except Exception:
            emit("error", traceback.format_exc())

    def _paint_thread(self, plan, geo, target, expected, skip, start, color_mode, meta,
                      ctl: Controller) -> None:
        emit = lambda k, d: self.bridge.event.emit(k, d)
        s, prof = self.cfg.settings, self.cfg.profile
        try:
            for i in range(s.countdown_s, 0, -1):
                emit("countdown", i)
                if ctl.stop_event.wait(1.0):
                    emit("finished", "stopped")
                    return
            mouse, kb = WinMouse(), WinKeyboard()
            ex = Executor(plan, geo, prof, s, mouse, kb, ctl, on_event=emit,
                          progress_path=self.progress_path, progress_meta=meta, color_mode=color_mode)
            res = ex.run(start)
            status = res.status
            if status == "done" and s.verify_passes > 0 and target is not None:
                from ..screen import grab
                emit("status", tr('Проверка результата…'))

                def make(p):
                    return Executor(p, geo, prof, s, mouse, kb, ctl, on_event=emit, color_mode=color_mode)

                out = verify_and_fix(make, target, plan, grab, s.verify_passes, s.verify_tolerance, emit,
                                     max_de=s.verify_de, expected_rgb=expected, skip_mask=skip)
                status = {"ok": "done", "stopped": "stopped"}.get(out, "incomplete")
            if status == "done":
                try:
                    self.progress_path.unlink()
                except OSError:
                    pass
            emit("finished", status)
        except Exception:
            emit("error", traceback.format_exc())

    def stop_all(self) -> None:
        if self.ctl:
            self.ctl.stop()
        self.awaiting_capture = False
        if self._anim.isActive():
            self._anim.stop()
            self._set_play_icon(False)

    # ================================================================ events
    def _on_event(self, kind: str, data) -> None:
        hk = self.cfg.hotkeys
        stop_k, pause_k = hk["stop"].upper(), hk["pause"].upper()
        if kind == "job":
            self._on_job(*data)
        elif kind == "job_progress":
            gen, frac = data
            if gen == self._gen:
                self._footer_set(tr('ОЦЕНКА ВРЕМЕНИ'), "…", "dim", tr('Генерирую мазки… {0:.0f}%').format(frac * 100),
                                 tr('палитра ✓ · мазки, потом доводка'), progress=frac)
                self.badge.show_text(tr('Считаю план · {0:.0f}%').format(frac * 100), tr('Можно менять настройки — пересчитаю'))
        elif kind == "hk_stop":
            if self.ctl:
                self.log(tr('■ Аварийная остановка'))
            self.stop_all()
        elif kind == "hk_pause":
            if self.ctl:
                self.ctl.toggle_pause()
                if not self.ctl.paused:
                    self.hud.show_state("paint", tr('Продолжаю…'))
                self._refresh_all()
        elif kind == "hk_capture":
            if self.awaiting_capture:
                self.capture_for_calibration()
        elif kind == "countdown":
            self.hud.show_state("countdown", tr('Старт через {0}… переключитесь в игру').format(data),
                                tr('Откройте редактор таблички · {0} — отмена').format(stop_k), number=data)
        elif kind == "progress":
            done, total = data["done"], data["total"]
            el = time.monotonic() - self._paint_started
            painted = max(1, done - self._paint_start_index)
            left = el / painted * (total - done)
            frac = done / max(1, total)
            self.hud.show_state("paint", tr('Рисую: {0} / {1} · осталось ~{2}').format(_num(done), _num(total), format_duration(left)),
                                tr('· {0} — стоп · {1} — пауза').format(stop_k, pause_k), fraction=frac)
            self._footer_set(tr('ОСТАЛОСЬ'), "~" + format_duration(left), "",
                             tr('Рисую — {0} из {1}').format(_num(done), _num(total)), f"{round(frac * 100)}%",
                             self.line2.text(), progress=frac)
        elif kind == "color":
            hexc = to_hex(data["rgb"])
            self.hud.show_state(self.hud.kind if self.hud.kind != "countdown" else "paint", self.hud.title,
                                color_hex=hexc)
            self.line2.setText(tr('Текущий цвет {0} · прогресс сохраняется').format(hexc))
            self.line2.show()
        elif kind == "paused":
            reason = {"user": tr('по команде'), "mouse moved": tr('мышь сдвинута')}.get(data["reason"], data["reason"])
            self.hud.show_state("alarm", tr('Пауза ({0})').format(reason), tr('{0} — продолжить · {1} — стоп · прогресс сохранён').format(pause_k, stop_k))
            self.log(tr('Пауза: {0} (штрих {1})').format(reason, _num(data['index'] + 1)), )
            frac = self._paint_fraction()
            self._footer_set(tr('ОСТАЛОСЬ'), self.eta.text(), "warn", tr('Пауза — нарисовано {0}%').format(round(frac * 100)),
                             "", self.line2.text(), progress=frac, pstate="warn")
            self._refresh_all()
        elif kind == "resumed":
            self.log(tr('Продолжаю'))
            theme.set_state(self.progress, "")
            theme.set_state(self.eta, "")
            self._refresh_all()
        elif kind == "saved":
            self.log(tr('✓ Табличка сохранена в игре'))
        elif kind == "status":
            self.hud.show_state("info", data, tr('{0} — стоп').format(stop_k))
            self.log(data)
        elif kind == "measure":
            self.log(tr('Пробная {0}: размер {1:g} → {2:.1f} px на экране = {3:.1f} px текстуры').format(data.get('how', 'точка'), data['value'], data['screen_px'], data['texture_px']))
        elif kind == "speed":
            mark = "✓" if data["passed"] else "✗"
            self.log(tr('{0} Тест скорости: пауза {1:g} кадра ({2:.1f} мс) — углы {3}, точки {4}').format(mark, data['frames'], data['ms'], data['corners'], data['dots'])
                     + (tr(', хвосты между точками: {0}').format(data['tails']) if data.get("tails") else ""),
                     "ok" if data["passed"] else "warn")
        elif kind == "speed_done":
            s = self.cfg.settings
            if data is None:
                self.log(tr('⚠ Даже самая длинная пауза теряет движения — проверьте FPS и калибровку.'))
            else:
                s.frames_per_action, s.min_frames = data
                s.speed = 1.0
                self._save_cfg()
                self._load_settings_into_ui()
                self.log(tr('✓ Скорость выставлена: {0:g} кадра на действие ({1:.1f} мс при {2:.0f} FPS), запас 50%').format(s.frames_per_action, s.frames_per_action / s.game_fps * 1000, s.game_fps))
        elif kind == "line":
            self.log(tr('Длинная линия одним броском мыши: закрашено {0:.0f}% длины').format(data['coverage'] * 100))
        elif kind == "line_done":
            s = self.cfg.settings
            if data < 0.97:
                s.line_mode = "drag"
                s.draw_step_px = 4.0
                self._save_cfg()
                self._load_settings_into_ui()
                self.log(tr('⚠ Игра не соединяет быстрые броски мыши в сплошную линию — включена «Протяжка мелкими шагами» (медленнее, но без пунктира).'))
            else:
                self.log(tr('✓ Длинные линии рисуются сплошными — «Бросок к вершине» подходит.'))
        elif kind == "measure_step":
            self.log(tr('Измерение: ') + data["text"], "info")
        elif kind == "measured":
            self.cfg.profile.size_scale = round(float(data), 3)
            self.cfg.profile.size_measured = True
            self._save_cfg()
            self.log(tr('✓ Измерение кисти: {0:.3f} px текстуры на единицу размера — сохранено в профиль').format(data))
            self._refresh_timer.start()
        elif kind == "verify_stuck":
            self.log(tr('Проверка остановлена: дорисовка почти ничего не меняет (осталось {0} клеток) — дальше было бы тратой времени.').format(_num(data['wrong'])), "warn")
        elif kind == "verify":
            self.log(tr('Проверка #{0}: неверных клеток {1} (точность {2:.2f}%)').format(data['pass'], _num(data['wrong']), data['accuracy'] * 100), "info")
        elif kind == "stopped":
            self.log(tr('Остановлено на штрихе {0}. Прогресс сохранён — можно «Продолжить».').format(_num(data['index'] + 1)),
                     "warn")
        elif kind in ("finished", "error", "fail"):
            total = self._paint_total
            elapsed = time.monotonic() - self._paint_started
            self.ctl = None
            if kind == "fail":
                self.log("⚠ " + str(data).split("\n")[0])
            elif kind == "error":
                self.log(tr('Ошибка: ') + str(data).strip().splitlines()[-1], "err")
            else:
                self.log({"done": tr('✓ Готово!'), "stopped": tr('Остановлено.'), "measured": tr('✓ Кисть измерена.'),
                          "speedtest": tr('✓ Тест скорости завершён.'),
                          "incomplete": tr('⚠ Готово, но проверка нашла неисправленные клетки.')}.get(data, data))
            if kind == "finished" and data in ("done", "incomplete") and total:
                self.hud.show_state("done", tr('Готово: {0} штрихов за {1}').format(_num(total), format_duration(elapsed)),
                                    tr('Не забудьте сохранить табличку в игре'))
                self._hud_hide.start()
            else:
                self.hud.hide()
            self._paint_total = 0
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self._refresh_all()
            theme.set_state(self.progress, "")
            if kind == "fail":
                dialogs.info(self, tr('Не получилось'), str(data), kind="warn", icon="warning")
            elif kind == "error":
                dialogs.error(self, tr('Ошибка'), str(data).strip().splitlines()[-1], details=str(data)[-3000:])

    def log(self, text: str, level: str | None = None) -> None:
        self.logbox.add(text, level)
        self.log_count.setText(tr('{0} сообщ.').format(self.logbox.count))

    def _switch_language(self, code: str) -> None:
        """Rebuild the window in the other language, keeping the picture, mode and geometry."""
        if code == language():
            return
        if self.ctl is not None:
            self.lang_seg.set_value(language())
            return
        self.cfg.settings.language = code
        self._save_cfg()
        set_language(code)
        self._gen += 1                   # drop a plan that is still being computed for this window
        w = MainWindow(self.cfg)
        w.setGeometry(self.geometry())
        w.mode_seg.set_value(self.mode_seg.value(), emit=True)
        if self.image is not None:
            w._set_image(self.image, self.image_path or "image.png")
        w.showMaximized() if self.isMaximized() else w.show()
        _WINDOWS.append(w)
        self.close()

    def closeEvent(self, e) -> None:
        if self.ctl:
            self.ctl.stop()
        self.hotkeys.stop()
        self.hud.close()
        super().closeEvent(e)
