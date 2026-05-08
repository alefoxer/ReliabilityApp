from __future__ import annotations

from PyQt6.QtWidgets import QApplication

from app.gui.ui_styles import build_app_style


def apply_theme(app: QApplication, scale: float = 1.0) -> None:
    app.setStyleSheet(build_app_style(scale))
