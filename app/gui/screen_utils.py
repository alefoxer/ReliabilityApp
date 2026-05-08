from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QWidget


def fit_widget_to_screen(
    widget: QWidget,
    *,
    width_ratio: float = 0.9,
    height_ratio: float = 0.9,
    minimum_size: QSize | None = None,
) -> None:
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    width = max(minimum_size.width() if minimum_size else 800, int(available.width() * width_ratio))
    height = max(minimum_size.height() if minimum_size else 600, int(available.height() * height_ratio))
    widget.resize(min(width, available.width()), min(height, available.height()))
