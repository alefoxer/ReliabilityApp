from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QSize
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtSvg import QSvgGenerator
from PyQt6.QtWidgets import QGraphicsScene


EXPORT_PADDING = 40.0
MAX_EXPORT_DIMENSION = 8192


def scene_content_rect(scene: QGraphicsScene, padding: float = EXPORT_PADDING) -> QRectF:
    rect = scene.itemsBoundingRect()
    if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        rect = scene.sceneRect()
    if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        rect = QRectF(0, 0, 800, 600)
    return rect.adjusted(-padding, -padding, padding, padding)


def _scaled_size(source_rect: QRectF, scale_factor: float) -> QSize:
    width = max(1, int(round(source_rect.width() * scale_factor)))
    height = max(1, int(round(source_rect.height() * scale_factor)))
    biggest = max(width, height)
    if biggest > MAX_EXPORT_DIMENSION:
        ratio = MAX_EXPORT_DIMENSION / biggest
        width = max(1, int(round(width * ratio)))
        height = max(1, int(round(height * ratio)))
    return QSize(width, height)


def export_scene_to_png(
    scene: QGraphicsScene,
    path: str | Path,
    *,
    scale_factor: float = 2.0,
    background: QColor | None = None,
) -> Path:
    target = Path(path)
    source_rect = scene_content_rect(scene)
    image_size = _scaled_size(source_rect, scale_factor)
    image = QImage(image_size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill((background or QColor("#ffffff")).rgba())

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    scene.render(painter, QRectF(0, 0, image.width(), image.height()), source_rect)
    painter.end()

    if not image.save(str(target)):
        raise OSError("Qt не смог сохранить PNG-файл.")
    return target


def export_scene_to_svg(scene: QGraphicsScene, path: str | Path) -> Path:
    target = Path(path)
    source_rect = scene_content_rect(scene)
    generator = QSvgGenerator()
    generator.setFileName(str(target))
    generator.setSize(source_rect.size().toSize())
    generator.setViewBox(source_rect)
    generator.setTitle("Схема надежности")
    generator.setDescription("Экспорт структурной схемы надежности")
    painter = QPainter(generator)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scene.render(painter, QRectF(), source_rect)
    painter.end()
    return target
