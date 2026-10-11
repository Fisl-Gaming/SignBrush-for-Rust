"""PyQt6 user interface."""

from __future__ import annotations

import sys


def run_gui(config_path: str | None = None) -> int:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from ..config import load_config
    from ..i18n import set_language, system_language, tr
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SignBrush for Rust")
    from . import theme
    theme.apply(app)
    set_language(system_language())
    try:
        cfg = load_config(config_path)
    except Exception as e:  # broken config: tell the user instead of crashing silently
        QMessageBox.critical(None, "SignBrush for Rust", tr("Не удалось прочитать config.json:\n{0}").format(e))
        return 1
    set_language(cfg.settings.language or system_language())
    win = MainWindow(cfg)
    win.show()
    return app.exec()
