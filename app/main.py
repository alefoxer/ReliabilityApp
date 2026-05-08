"""Application entry point."""

from __future__ import annotations

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.gui.gui_main import APP_DISPLAY_NAME, MainWindow, _set_windows_app_identity
from app.gui.theme_manager import apply_theme
from app.utils.paths import resource_path


def main() -> int:
    _set_windows_app_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app_icon = resource_path("app_icon.ico")
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
