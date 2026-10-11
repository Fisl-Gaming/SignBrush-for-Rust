"""Render docs/ui-ru.png and docs/ui-en.png: the main window with the sample picture planned."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from signbrush.config import load_config  # noqa: E402
from signbrush.gui import theme  # noqa: E402
from signbrush.i18n import set_language  # noqa: E402


def shot(lang: str, out: Path) -> None:
    from signbrush.gui.main_window import MainWindow
    set_language(lang)
    cfg = load_config(Path(tempfile.mkdtemp()) / "config.json")
    cfg.settings.language = lang
    cfg.settings.sign_type = "sign.large.wood"
    w = MainWindow(cfg)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    w.resize(1440, 900)
    w.show()
    w.load_image(str(ROOT / "docs" / "sample.png"))
    t = time.time()
    while (w._planning or w.job is None) and time.time() - t < 120:
        QApplication.processEvents()
        time.sleep(0.02)
    w.tabbar.setCurrentIndex(1)
    for _ in range(20):
        QApplication.processEvents()
    w.grab().save(str(out))
    w.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme.apply(app)
    for lang in ("ru", "en"):
        shot(lang, ROOT / "docs" / f"ui-{lang}.png")
