"""Headless smoke test of the GUI (Qt offscreen platform, no real input)."""

import os
import time

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from signbrush.config import load_config  # noqa: E402
from signbrush.gui import main_window  # noqa: E402
from signbrush.gui.overlay import CalibrationOverlay  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(main_window.HotkeyWatcher, "start", lambda self: self)
    cfg = load_config(tmp_path / "config.json")
    cfg.settings.sign_type = "sign.small.wood"
    cfg.settings.detail = 4
    cfg.settings.algorithm = "pixels"
    w = main_window.MainWindow(cfg)
    yield w
    w.close()


def wait_for(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_load_preview_and_dryrun(app, window, tmp_path):
    img = Image.new("RGB", (200, 100), "white")
    img.paste((255, 51, 52), (40, 20, 160, 80))
    p = tmp_path / "pic.png"
    img.save(p)
    window.load_image(str(p))
    assert wait_for(app, lambda: window.job is not None)
    assert "сетка 64×32" in window.line1b.text()
    assert window.eta.text().startswith("≈")
    window.toggle_dryrun()
    window.dry_speed.setValue(10)
    assert wait_for(app, lambda: window._renderer is not None and window._renderer.finished())
    assert window.preview_btn.isEnabled()
    assert not window.paint_btn.isEnabled()          # not calibrated yet
    assert window.chip_calib._text.text() == "Нужна калибровка"
    # settings change in the advanced panel triggers a new plan and syncs the simple panel
    window.detail_sb.setValue(8)
    assert wait_for(app, lambda: window.job.geometry.cols == 32)
    assert window.cfg.settings.detail == 8
    assert window.s_detail.value() == 8
    window.mode_seg.set_value("adv", emit=True)
    assert window.panels.currentIndex() == 1


def press(widget, key, mod=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, mod))


def drag(widget, a, b):
    for t, p in ((QMouseEvent.Type.MouseButtonPress, a), (QMouseEvent.Type.MouseMove, b),
                 (QMouseEvent.Type.MouseButtonRelease, b)):
        ev = QMouseEvent(t, QPointF(*p), QPointF(*p), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        {QMouseEvent.Type.MouseButtonPress: widget.mousePressEvent,
         QMouseEvent.Type.MouseMove: widget.mouseMoveEvent,
         QMouseEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[t](ev)


def test_overlay_marks_canvas_and_palette(app):
    shot = np.full((400, 800, 3), 40, dtype=np.uint8)
    shot[50:250, 50:450] = (168, 147, 131)
    ov = CalibrationOverlay(shot, {}, grid=(4, 16), aspect=2.0)
    ov.resize(800, 400)                      # 1:1 with the screenshot
    got = {}
    ov.finished.connect(got.update)
    press(ov, Qt.Key.Key_A)                  # auto-detect the canvas
    assert "canvas" in ov.results
    press(ov, Qt.Key.Key_Return)
    assert ov.step.key == "hex_field"
    drag(ov, (700, 300), (700, 300))         # a click = point step
    press(ov, Qt.Key.Key_Return)
    drag(ov, (500, 60), (590, 150))          # SV square
    press(ov, Qt.Key.Key_Return)
    drag(ov, (600, 60), (600, 360))          # hue bar line
    press(ov, Qt.Key.Key_Down)               # nudge last point by 1 px
    press(ov, Qt.Key.Key_Return)
    while ov.idx < len(ov.steps) - 1:
        press(ov, Qt.Key.Key_S)              # skip optional steps
    press(ov, Qt.Key.Key_S)
    assert got["hex_field"] == ((700, 300),)
    assert got["picker_sv"] == ((500, 60), (590, 150))
    assert got["picker_hue"] == ((600, 60), (600, 361))
    (x0, y0), (x1, y1) = got["canvas"]
    assert abs(x0 - 50) <= 3 and abs(x1 - 449) <= 3
    ov.grab()                                # paintEvent runs without errors
