"""Graphical reliability block diagram editor.

This module contains the QGraphicsScene/QGraphicsView based editor, visual
block and connection items, scheme import/export actions, formula generation
actions and calculation-by-scheme workflow. It is intentionally the UI layer:
core data is passed through ``SchemeModel`` and delegated to validators,
formula builder, method selector and calculation adapter.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
import uuid

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QLineF, QPointF, QRectF, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (
    QApplication, QAbstractSpinBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGraphicsItem,
    QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSlider, QSizePolicy, QSpinBox, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.import_export.file_service import SaveFormat, choose_save_path, notify_save_result
from app.demo.demo_scenarios import comparison_lines_for_display, load_sne_emrtu_demo
from app.import_export.external_reliability_import import imported_project_to_scheme, load_imported_project
from app.formulas.formula_rendering import (
    FORMULA_FONT_SIZE,
    formula_item_html,
    formula_section_html,
    is_renderable_latex_formula,
    normalize_latex_for_mathtext,
    readable_formula_html,
    render_latex_to_png_bytes,
    split_latex_formula_for_display,
)
from app.formulas.graph_formula_builder import block_formula_symbol, build_formula_for_scheme
from app.gui.gui_dialogs import BlockPropsDialog
from app.demo.library_templates import built_in_templates
from app.core.reliability_contribution_analysis import (
    CONTRIBUTION_METRIC_LABELS,
    CONTRIBUTION_METRICS,
    analyze_scheme_contributions,
)
from app.core.rbd_models import BlockModel, CalculationResult, ConnectionModel, SchemeModel, formula_short_text
from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer
from app.import_export.scene_exporters import export_scene_to_png, export_scene_to_svg
from app.core.scheme_adapter import calculate_scheme_reliability
from app.core.scheme_method_selector import format_method_selection_html, format_method_selection_text, select_method_for_scheme
from app.import_export.scheme_storage import load_scheme, save_scheme
from app.gui.screen_utils import fit_widget_to_screen
from app.core.validators import validate_scheme, validate_scheme_file


GRID_STEP = 20
DEFAULT_ZOOM = 100
FORMULA_UI_QUALITY_SCALE = 2


def _block_role(props: dict | None, is_subscheme: bool = False) -> str:
    params = dict(props or {})
    if is_subscheme or str(params.get("block_role", "")).lower() == "subscheme":
        return "subscheme"
    role = str(params.get("block_role", "")).lower().strip()
    if role in {"ordinary", "reserve", "k_of_n", "subscheme", "passive"}:
        return role
    if "k_required" in params or "n_total" in params or str(params.get("reserve_type", "")).lower() == "sliding":
        return "k_of_n"
    try:
        if int(float(params.get("reserve_count", 0) or 0)) > 0:
            return "reserve"
    except (TypeError, ValueError):
        pass
    return "ordinary"


def _default_block_params() -> dict[str, object]:
    return {"lambda": 0.001, "Tv": 10.0, "t": 1000, "block_role": "ordinary"}


def _short_axis_label(value: str, *, limit: int = 16) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _format_contribution_value(value: float) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(numeric) >= 1000 or (0 < abs(numeric) < 0.001):
        return f"{numeric:.4g}"
    return f"{numeric:.6g}"


def _is_uuid_like(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _display_badge_id(value: object) -> str:
    text = str(value or "").strip()
    if not text or _is_uuid_like(text):
        return ""
    return text if len(text) <= 18 else ""


def _render_latex_to_png_bytes(line: str) -> bytes:
    """Render a LaTeX-like formula to PNG bytes via matplotlib mathtext."""
    return render_latex_to_png_bytes(line)


def _normalize_latex_for_mathtext(line: str) -> str:
    return normalize_latex_for_mathtext(line)


class StepSpinWidget(QWidget):
    def __init__(self, minimum: int, maximum: int, value: int, *, step: int = 1):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setMinimumWidth(110)
        self.btn_minus = QPushButton("−")
        self.btn_minus.setProperty("role", "tool")
        self.btn_minus.setFixedWidth(28)
        self.btn_minus.clicked.connect(self.spin.stepDown)
        self.btn_plus = QPushButton("+")
        self.btn_plus.setProperty("role", "tool")
        self.btn_plus.setFixedWidth(28)
        self.btn_plus.clicked.connect(self.spin.stepUp)
        layout.addWidget(self.spin, 1)
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.btn_plus)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, value: int) -> None:  # noqa: N802
        self.spin.setValue(value)


class ConnectionLine(QGraphicsPathItem):
    def __init__(self, start_block: "RBDBlock", start_port_id: str, end_block: "RBDBlock", end_port_id: str, *, connection_id: str | None = None):
        super().__init__()
        self.connection_id = connection_id or str(uuid.uuid4())
        self.start_block = start_block
        self.start_port_id = start_port_id
        self.end_block = end_block
        self.end_port_id = end_port_id
        self.arrow_polygon = QPolygonF()
        self._bounding_rect = QRectF()
        self._default_pen = QPen(QColor("#4f6d8f"), 2.2)
        self._selected_pen = QPen(QColor("#1f6fb2"), 3.0)
        self._highlight_pen = QPen(QColor("#f59e0b"), 3.0)
        self.setZValue(-2)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.label_item = QGraphicsSimpleTextItem(self)
        self.label_item.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        self.label_item.setBrush(QColor("#475569"))
        self.label_item.setOpacity(0.0)
        self.label_item.setZValue(3)
        self.refresh_style()
        self.update_path()

    def _label_text(self) -> str:
        value = self.end_block.props.get("lambda", self.start_block.props.get("lambda"))
        try:
            return f"λ≈{float(value):.4f}" if value is not None else ""
        except (TypeError, ValueError):
            return ""

    def _update_label(self) -> None:
        text = self._label_text()
        self.label_item.setText(text)
        self.label_item.setVisible(bool(text))
        if not text:
            return
        label_percent = 0.46
        if self.start_port_id in {"up", "up_spec", "down", "down_spec"} or self.end_port_id in {"up", "up_spec", "down", "down_spec"}:
            label_percent = 0.54
        point = self.path().pointAtPercent(label_percent)
        before = self.path().pointAtPercent(max(0.0, label_percent - 0.04))
        after = self.path().pointAtPercent(min(1.0, label_percent + 0.04))
        dx = after.x() - before.x()
        dy = after.y() - before.y()
        if abs(dx) >= abs(dy):
            offset = QPointF(0.0, -24.0 if point.y() <= (self.start_block.scenePos().y() + self.end_block.scenePos().y()) / 2 else 24.0)
        else:
            offset = QPointF(18.0 if dx >= 0 else -18.0, 0.0)
        rect = self.label_item.boundingRect()
        self.label_item.setPos(point.x() - rect.width() / 2 + offset.x(), point.y() - rect.height() / 2 + offset.y())

    def _rebuild_arrow(self) -> None:
        point_at_end = self.path().pointAtPercent(1.0)
        point_before_end = self.path().pointAtPercent(0.96)
        direction = QLineF(point_before_end, point_at_end)
        if direction.length() == 0:
            self.arrow_polygon = QPolygonF()
            return
        angle = direction.angle()
        left = QLineF.fromPolar(10.0, angle + 155)
        right = QLineF.fromPolar(10.0, angle - 155)
        left.translate(point_at_end)
        right.translate(point_at_end)
        self.arrow_polygon = QPolygonF([point_at_end, left.p2(), right.p2()])

    def _update_bounds(self) -> None:
        rect = super().boundingRect()
        if not self.arrow_polygon.isEmpty():
            rect = rect.united(self.arrow_polygon.boundingRect())
        if self.label_item.isVisible():
            rect = rect.united(self.label_item.mapRectToParent(self.label_item.boundingRect()))
        self._bounding_rect = rect.adjusted(-8, -8, 8, 8)

    def update_path(self) -> None:
        self.prepareGeometryChange()
        start = self.start_block.get_port_scene_pos(self.start_port_id)
        end = self.end_block.get_port_scene_pos(self.end_port_id)
        start_handle = start + self.start_block.port_tangent(self.start_port_id, 105.0)
        end_handle = end + self.end_block.port_tangent(self.end_port_id, 105.0)
        if QLineF(start, end).length() < 120:
            offset = QPointF(62.0, 0.0)
            start_handle = start + offset
            end_handle = end - offset
        path = QPainterPath(start)
        path.cubicTo(start_handle, end_handle, end)
        self.setPath(path)
        self._rebuild_arrow()
        self._update_label()
        self._update_bounds()
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._bounding_rect if not self._bounding_rect.isNull() else super().boundingRect().adjusted(-8, -8, 8, 8)

    def refresh_style(self, highlighted: bool = False) -> None:
        if highlighted:
            self.setPen(self._highlight_pen)
            self.label_item.setBrush(QColor("#b45309"))
        elif self.isSelected():
            self.setPen(self._selected_pen)
            self.label_item.setBrush(QColor("#1f6fb2"))
        else:
            self.setPen(self._default_pen)
            self.label_item.setBrush(QColor("#475569"))

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.refresh_style(self.start_block.isSelected() or self.end_block.isSelected())
        return super().itemChange(change, value)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        super().paint(painter, option, widget)
        if not self.arrow_polygon.isEmpty():
            painter.setBrush(self.pen().color())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(self.arrow_polygon)
        text = self.label_item.text()
        if text:
            rect = self.label_item.mapRectToParent(self.label_item.boundingRect()).adjusted(-5, -3, 5, 3)
            painter.setPen(QPen(QColor("#d7e3f1"), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255, 232)))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setFont(self.label_item.font())
            painter.setPen(QPen(self.label_item.brush().color()))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu()
        delete_action = menu.addAction("Удалить связь")
        if menu.exec(event.screenPos()) == delete_action:
            editor = self.scene().property("editor") if self.scene() else None
            if editor:
                editor.remove_connection(self)

    def to_model(self) -> ConnectionModel:
        return ConnectionModel(connection_id=self.connection_id, source_id=self.start_block.block_id, source_port=self.start_port_id, target_id=self.end_block.block_id, target_port=self.end_port_id)


class RBDBlock(QGraphicsObject):
    port_clicked = pyqtSignal(object, str)
    block_changed = pyqtSignal()

    def __init__(self, name: str, direction: str, x: float, y: float, *, block_id: str | None = None, props: dict[str, object] | None = None, is_subscheme: bool = False, nested_scheme: SchemeModel | None = None):
        super().__init__()
        self.block_id = block_id or str(uuid.uuid4())
        self.name = name
        self.direction = direction
        self.props = dict(props or _default_block_params())
        self.is_subscheme = is_subscheme
        self.nested_scheme = nested_scheme
        if self.direction not in {"in", "out", "junction"} and not str(self.props.get("formula_symbol", "") or "").strip():
            self.props["formula_symbol"] = block_formula_symbol(self._temporary_model())
        self.attached_lines: list[ConnectionLine] = []
        self.is_connecting = False
        self.validation_state = ""
        self.validation_message = ""
        self._refresh_tooltip()
        self.setPos(self._snap_value(x), self._snap_value(y))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)

    @staticmethod
    def _snap_value(value: float) -> float:
        return round(value / GRID_STEP) * GRID_STEP

    def attach_connection(self, connection: ConnectionLine) -> None:
        if connection not in self.attached_lines:
            self.attached_lines.append(connection)

    def detach_connection(self, connection: ConnectionLine) -> None:
        if connection in self.attached_lines:
            self.attached_lines.remove(connection)

    def _base_rect(self) -> QRectF:
        if self.direction in {"in", "out"}:
            return QRectF(-42, -28, 118, 56)
        if self.direction in {"right", "left"}:
            return QRectF(-92, -38, 184, 78)
        if self.direction in {"up", "down"}:
            return QRectF(-92, -72, 184, 144)
        if self.direction == "up_right":
            return QRectF(-92, -38, 184, 132)
        if self.direction == "down_right":
            return QRectF(-92, -112, 184, 132)
        return QRectF(-92, -38, 184, 78)

    @staticmethod
    def _body_rect() -> QRectF:
        return QRectF(-76, -30, 152, 60)

    def _info_text(self) -> str:
        parts = []
        if "lambda" in self.props:
            try:
                parts.append(f"λ={float(self.props['lambda']):.4f}")
            except (TypeError, ValueError):
                parts.append(f"λ={self.props['lambda']}")
        role = _block_role(self.props, self.is_subscheme)
        if role == "reserve":
            try:
                reserve_count = int(float(self.props.get("reserve_count", 0) or 0))
                if reserve_count > 0:
                    parts.append(f"резерв: 1+{reserve_count}")
            except (TypeError, ValueError):
                parts.append("резерв")
        elif role == "k_of_n":
            parts.append(f"k={self.props.get('k_required', '?')} из {self.props.get('n_total', '?')}")
        elif role == "passive":
            parts.append("служебный")
        if self.is_subscheme or role == "subscheme":
            parts.append("подсхема")
        return " ".join(parts)

    def _formula_badge_text(self) -> str:
        if self.direction in {"in", "out", "junction"}:
            return ""
        if self.is_subscheme and self.nested_scheme is not None:
            nested_ids = [
                _display_badge_id(block_formula_symbol(block))
                for block in self.nested_scheme.blocks
                if block.kind not in {"in", "out", "junction"}
            ]
            nested_ids = [item for item in nested_ids if item]
            if len(nested_ids) >= 2:
                return f"{nested_ids[0]}…{nested_ids[-1]}"
            if nested_ids:
                return nested_ids[0]
        return _display_badge_id(block_formula_symbol(self._temporary_model()))

    def _temporary_model(self) -> BlockModel:
        return BlockModel(
            block_id=self.block_id,
            name=self.name,
            kind=self.direction,
            x=self.pos().x(),
            y=self.pos().y(),
            params=self.props.copy(),
            is_subscheme=self.is_subscheme,
            nested_scheme=self.nested_scheme,
        )

    def _refresh_tooltip(self) -> None:
        badge = self._formula_badge_text()
        if badge:
            self.setToolTip(f"Обозначение в формуле: {badge}\nНазвание блока: {self.name}")
        else:
            self.setToolTip(self.name)

    def boundingRect(self) -> QRectF:  # noqa: N802
        rect = self._base_rect()
        if self._info_text():
            rect = rect.united(QRectF(rect.left() - 4, rect.bottom() + 2, rect.width() + 8, 22))
        return rect.adjusted(-6, -6, 6, 6)

    def set_connecting(self, state: bool) -> None:
        self.is_connecting = state
        self.update()

    def set_validation_state(self, state: str = "", message: str = "") -> None:
        """Mark the block after scheme validation: '', 'warning' or 'error'."""
        self.validation_state = state
        self.validation_message = message
        badge = self._formula_badge_text()
        tooltip = f"Обозначение в формуле: {badge}\nНазвание блока: {self.name}" if badge else self.name
        self.setToolTip(f"{tooltip}\n{message}" if message else tooltip)
        self.update()

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(self._snap_value(value.x()), self._snap_value(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemScenePositionHasChanged:
            for line in self.attached_lines:
                line.update_path()
                line.refresh_style(self.isSelected() or line.start_block.isSelected() or line.end_block.isSelected())
            self.block_changed.emit()
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            for line in self.attached_lines:
                line.refresh_style(self.isSelected() or line.start_block.isSelected() or line.end_block.isSelected())
        return super().itemChange(change, value)

    def get_ports(self) -> dict[str, QPointF]:
        if self.direction == "in":
            return {"out": QPointF(58, 0)}
        if self.direction == "out":
            return {"in": QPointF(0, 0)}
        if self.direction in {"right", "left"}:
            return {"left": QPointF(-86, 0), "right": QPointF(86, 0)}
        if self.direction in {"up", "down"}:
            return {"up": QPointF(0, -66), "down": QPointF(0, 66)}
        if self.direction == "up_right":
            return {"left": QPointF(-86, 0), "right": QPointF(86, 0), "down_spec": QPointF(-56, 86)}
        if self.direction == "down_right":
            return {"left": QPointF(-86, 0), "right": QPointF(86, 0), "up_spec": QPointF(-56, -86)}
        return {}

    @staticmethod
    def _fit_text_lines(text: str, metrics: QFontMetrics, width: int, max_lines: int = 2) -> list[str]:
        words = str(text or "").split()
        if not words:
            return [""]
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and metrics.horizontalAdvance(candidate) > width:
                lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    break
            else:
                current = candidate
        if len(lines) < max_lines and current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        if len(lines) == max_lines and " ".join(lines) != " ".join(words):
            lines[-1] = metrics.elidedText(lines[-1], Qt.TextElideMode.ElideRight, width)
        return lines or [metrics.elidedText(str(text), Qt.TextElideMode.ElideRight, width)]

    def port_tangent(self, port_id: str, distance: float = 60.0) -> QPointF:
        mapping = {"left": QPointF(-distance, 0), "in": QPointF(-distance, 0), "right": QPointF(distance, 0), "out": QPointF(distance, 0), "up": QPointF(0, -distance), "up_spec": QPointF(0, -distance), "down": QPointF(0, distance), "down_spec": QPointF(0, distance)}
        return mapping.get(port_id, QPointF(distance, 0))

    def get_port_local_pos(self, port_id: str) -> QPointF:
        return self.get_ports().get(port_id, QPointF(0, 0))

    def get_port_scene_pos(self, port_id: str) -> QPointF:
        return self.mapToScene(self.get_port_local_pos(port_id))

    def _port_stub_start(self, body: QRectF, port_name: str, port_pos: QPointF) -> QPointF:
        """Start inner port stubs at the body edge so the title area stays clear."""
        if port_name == "left":
            return QPointF(body.left(), port_pos.y())
        if port_name == "right":
            return QPointF(body.right(), port_pos.y())
        if port_name in {"up", "up_spec"}:
            return QPointF(port_pos.x(), body.top())
        if port_name in {"down", "down_spec"}:
            return QPointF(port_pos.x(), body.bottom())
        return QPointF(0, 0)

    def _port_stub_segments(self, body: QRectF) -> list[tuple[QPointF, QPointF, str]]:
        return [
            (self._port_stub_start(body, port_name, pos), pos, port_name)
            for port_name, pos in self.get_ports().items()
        ]

    def paint(self, painter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._base_rect()
        role = _block_role(self.props, self.is_subscheme)
        has_subscheme_marker = self.is_subscheme or role == "subscheme"
        pen = QPen(QColor("#8aa2ba"), 1.2)
        brush = QBrush(QColor("#f9fbfd"))
        if self.is_connecting:
            pen = QPen(QColor("#2e8b57"), 3)
        elif self.validation_state == "error":
            pen = QPen(QColor("#dc2626"), 3)
            brush = QBrush(QColor("#fff1f2"))
        elif self.validation_state == "warning":
            pen = QPen(QColor("#f59e0b"), 2.5)
            brush = QBrush(QColor("#fffbeb"))
        elif self.isSelected():
            pen = QPen(QColor("#1f6fb2"), 2.5)
        elif has_subscheme_marker:
            pen = QPen(QColor("#2563eb"), 2.8)
        painter.setPen(pen)
        painter.setBrush(brush)
        if self.direction == "in":
            painter.drawEllipse(QRectF(-10, -10, 20, 20))
            painter.drawLine(10, 0, 58, 0)
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(-30, -12, 18, 24), Qt.AlignmentFlag.AlignCenter, "I")
        elif self.direction == "out":
            painter.drawLine(0, 0, 40, 0)
            painter.drawEllipse(QRectF(40, -10, 20, 20))
            painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            painter.drawText(QRectF(-30, -12, 18, 24), Qt.AlignmentFlag.AlignCenter, "O")
        else:
            body = self._body_rect()
            painter.drawRoundedRect(body, 8, 8)
            if has_subscheme_marker:
                self._draw_subscheme_marker(painter, body)
            badge = self._formula_badge_text()
            if badge:
                painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
                metrics = painter.fontMetrics()
                badge_width = min(max(metrics.horizontalAdvance(badge) + 12, 34), int(body.width()) - 16)
                badge_rect = QRectF(body.left() + 8, body.top() + 4, badge_width, 16)
                painter.setPen(QPen(QColor("#1d4ed8"), 1))
                painter.setBrush(QBrush(QColor("#eaf2ff")))
                painter.drawRoundedRect(badge_rect, 5, 5)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, metrics.elidedText(badge, Qt.TextElideMode.ElideRight, int(badge_rect.width()) - 6))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            painter.setPen(QPen(QColor("#1f2937")))
            title_rect = body.adjusted(10, 22 if badge else 6, -10, -6)
            metrics = painter.fontMetrics()
            lines = self._fit_text_lines(self.name, metrics, int(title_rect.width()), max_lines=2)
            line_height = metrics.height()
            total_height = line_height * len(lines)
            y = title_rect.center().y() - total_height / 2
            for line in lines:
                painter.drawText(
                    QRectF(title_rect.left(), y, title_rect.width(), line_height),
                    Qt.AlignmentFlag.AlignCenter,
                    line,
                )
                y += line_height
            for start, end, port_name in self._port_stub_segments(body):
                painter.drawLine(start, end)
                pos = end
                self.draw_port(painter, pos.x(), pos.y(), port_name)
        if self.direction in {"in", "out"}:
            for port_name, pos in self.get_ports().items():
                self.draw_port(painter, pos.x(), pos.y(), port_name)
        info_text = self._info_text()
        if info_text:
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QPen(QColor("#5b6572")))
            painter.drawText(QRectF(rect.left() - 4, rect.bottom() + 2, rect.width() + 8, 22), Qt.AlignmentFlag.AlignCenter, info_text)

    def _draw_subscheme_marker(self, painter: QPainter, body: QRectF) -> None:
        """Draw a double outline and corner marker without covering the block title."""
        previous_pen = painter.pen()
        previous_brush = painter.brush()
        marker_pen = QPen(QColor("#1d4ed8"), 1.6)
        marker_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        marker_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(marker_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        inner = body.adjusted(3, 3, -3, -3)
        painter.drawRoundedRect(inner, 5, 5)

        corner_size = 9.0
        x = body.right() - corner_size - 2
        y = body.top() + 2
        painter.drawLine(QPointF(x, y), QPointF(x + corner_size, y))
        painter.drawLine(QPointF(x + corner_size, y), QPointF(x + corner_size, y + corner_size))

        painter.setPen(previous_pen)
        painter.setBrush(previous_brush)

    def draw_port(self, painter: QPainter, x: float, y: float, port_name: str) -> None:
        painter.setBrush(QColor("#e11d48") if port_name in {"left", "in", "up", "up_spec"} else QColor("#2563eb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(x - 4, y - 4, 8, 8))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.pos()
        for port_id, local_pos in self.get_ports().items():
            if (pos.x() - local_pos.x()) ** 2 + (pos.y() - local_pos.y()) ** 2 < 100:
                self.port_clicked.emit(self, port_id)
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu()
        rename_action = menu.addAction("Переименовать")
        props_action = menu.addAction("Свойства")
        subscheme_action = menu.addAction("Редактировать подсхему")
        menu.addSeparator()
        delete_action = menu.addAction("Удалить")
        selected = menu.exec(event.screenPos())
        editor = self.scene().property("editor") if self.scene() else None
        if selected == rename_action:
            new_name, ok = QInputDialog.getText(None, "Переименование блока", "Имя блока:", text=self.name)
            if ok and new_name.strip():
                self.prepareGeometryChange()
                self.name = new_name.strip()
                for line in self.attached_lines:
                    line.update_path()
                self._refresh_tooltip()
                self.block_changed.emit()
                self.update()
        elif selected == props_action:
            self.mouseDoubleClickEvent(None)
        elif selected == subscheme_action and editor:
            editor.edit_subscheme(self)
        elif selected == delete_action and editor:
            editor.remove_block(self)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.direction in {"in", "out"}:
            return
        editor = self.scene().property("editor") if self.scene() else None
        dialog = BlockPropsDialog(self.name, self.props, self.is_subscheme)
        if dialog.exec():
            self.prepareGeometryChange()
            self.name = dialog.get_name()
            self.props = dialog.get_props()
            self.is_subscheme = dialog.is_subscheme()
            if self.is_subscheme and self.nested_scheme is None and editor:
                self.nested_scheme = editor._default_subscheme_for_block(self)
            if not self.is_subscheme:
                self.nested_scheme = None
            for line in self.attached_lines:
                line.update_path()
            self._refresh_tooltip()
            self.block_changed.emit()
            self.update()

    def to_model(self) -> BlockModel:
        return BlockModel(block_id=self.block_id, name=self.name, kind=self.direction, x=self.pos().x(), y=self.pos().y(), params=self.props.copy(), is_subscheme=self.is_subscheme, nested_scheme=self.nested_scheme)


class GraphicsView(QGraphicsView):
    zoom_changed = pyqtSignal(int)

    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#f8fafc")))
        self._panning = False
        self._pan_start = QPointF()
        self.zoom_percent = DEFAULT_ZOOM

    def set_zoom_percent(self, value: int):
        self.zoom_percent = max(25, min(300, value))
        scale = self.zoom_percent / 100.0
        self.resetTransform()
        self.scale(scale, scale)
        self.zoom_changed.emit(self.zoom_percent)

    def fit_to_content(self) -> None:
        rect = self.scene().itemsBoundingRect().adjusted(-160, -120, 160, 120)
        if rect.isValid() and not rect.isEmpty():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.zoom_percent = max(25, min(300, int(round(self.transform().m11() * 100))))
            self.zoom_changed.emit(self.zoom_percent)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom_percent(self.zoom_percent + (10 if event.angleDelta().y() > 0 else -10))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawBackground(painter, rect)
        left = int(rect.left()) - (int(rect.left()) % GRID_STEP)
        top = int(rect.top()) - (int(rect.top()) % GRID_STEP)
        minor_pen = QPen(QColor("#e9eef5"), 1)
        major_pen = QPen(QColor("#d8e3ef"), 1)
        lines_minor = []
        lines_major = []
        for x in range(left, int(rect.right()), GRID_STEP):
            target = lines_major if x % (GRID_STEP * 5) == 0 else lines_minor
            target.append(QLineF(x, rect.top(), x, rect.bottom()))
        for y in range(top, int(rect.bottom()), GRID_STEP):
            target = lines_major if y % (GRID_STEP * 5) == 0 else lines_minor
            target.append(QLineF(rect.left(), y, rect.right(), y))
        painter.setPen(minor_pen)
        painter.drawLines(lines_minor)
        painter.setPen(major_pen)
        painter.drawLines(lines_major)


class WrappedFormulaWidget(QFrame):
    """Content-sized formula card that wraps raw LaTeX by measured rendered width."""

    def __init__(self, *, renderer: QtFormulaHtmlRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._raw_latex = ""
        self._display_lines: list[str] = []
        self._last_width = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("role", "formulaCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    @property
    def display_lines(self) -> list[str]:
        return list(self._display_lines)

    def set_formula(self, raw_latex: str) -> None:
        self._raw_latex = str(raw_latex or "").strip()
        self.rebuild_for_width(self._available_formula_width())

    def clear(self) -> None:
        self._raw_latex = ""
        self._display_lines = []
        self._clear_layout()
        self._set_content_height(56)

    def setPlainText(self, text: str) -> None:  # noqa: N802
        self._raw_latex = ""
        self._display_lines = []
        self._clear_layout()
        label = QLabel(str(text or ""))
        self._prepare_formula_line_label(label)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._layout.addWidget(label)
        self._set_content_height(max(56, label.sizeHint().height() + 18))

    def setHtml(self, html: str) -> None:  # noqa: N802
        self.setPlainText(re.sub(r"<[^>]+>", " ", str(html or "")).strip())

    def rebuild_for_width(self, width: int) -> None:
        if not self._raw_latex:
            self.clear()
            return
        available_width = max(120, int(width))
        self._last_width = available_width
        self._display_lines = self.build_display_lines(self._raw_latex, max_width=available_width)
        self._render_display_lines(available_width)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        width = self._available_formula_width()
        if self._raw_latex and abs(width - self._last_width) > 8:
            QTimer.singleShot(0, lambda: self.rebuild_for_width(self._available_formula_width()))

    def _available_formula_width(self) -> int:
        margins = self._layout.contentsMargins()
        return max(120, self.width() - margins.left() - margins.right() - 2)

    def _render_display_lines(self, available_width: int) -> None:
        self._clear_layout()
        total_height = self._layout.contentsMargins().top() + self._layout.contentsMargins().bottom()
        for line in self._display_lines:
            image, display_width, display_height = self._renderer._fit_formula_image(
                line,
                font_size=FORMULA_FONT_SIZE,
                max_display_width=None,
            )
            if image.isNull():
                label = QLabel(readable_formula_html(line))
                self._prepare_formula_line_label(label)
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
            else:
                label = QLabel()
                self._prepare_formula_line_label(label)
                pixmap = QPixmap.fromImage(image).scaled(
                    display_width,
                    display_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                label.setPixmap(pixmap)
                label.setFixedSize(display_width, display_height)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self._layout.addWidget(label)
            total_height += label.sizeHint().height() + self._layout.spacing()
        self._set_content_height(total_height + 2)

    @staticmethod
    def _prepare_formula_line_label(label: QLabel) -> None:
        label.setFrameShape(QFrame.Shape.NoFrame)
        label.setProperty("role", "formulaLine")
        label.setStyleSheet(
            "QLabel[role='formulaLine'] { "
            "border: none; background: transparent; border-radius: 0; padding: 0; margin: 0; "
            "}"
        )

    def _set_content_height(self, height: int) -> None:
        resolved = max(56, min(300, int(height)))
        self.setMinimumHeight(resolved)
        self.setMaximumHeight(resolved)
        self.updateGeometry()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def build_display_lines(self, raw_latex: str, *, max_width: int) -> list[str]:
        tokens = self._top_level_operator_terms(raw_latex)
        if len(tokens) <= 1:
            return [raw_latex] if raw_latex else []
        lines: list[str] = []
        current = tokens[0][1]
        current_terms = 1
        for operator, term in tokens[1:]:
            piece = f"{operator} {term}".strip()
            candidate = f"{current} {piece}".strip()
            if (
                current_terms >= 3
                or self._measure_formula_width(candidate) > max_width
                or self._is_continuation_group_line(current)
            ):
                lines.append(current)
                current = piece
                current_terms = 1
            else:
                current = candidate
                current_terms += 1
        if current:
            lines.append(current)
        return self._ensure_lines_fit(lines, max_width=max_width)

    def _ensure_lines_fit(self, lines: list[str], *, max_width: int) -> list[str]:
        result: list[str] = []
        for line in lines:
            if self._measure_formula_width(line) <= max_width:
                result.append(line)
                continue
            tokens = self._top_level_operator_terms(line)
            if len(tokens) <= 1:
                result.extend(self._split_wide_atom_line(line) or [line])
                continue
            result.extend(self._pack_terms_to_width(tokens, max_width=max_width))
        return result

    @classmethod
    def _split_wide_atom_line(cls, line: str) -> list[str]:
        text = str(line or "").strip()
        prefix = ""
        body = text
        for operator in (r"\cdot", "+", "-"):
            if body.startswith(operator):
                prefix = operator
                body = body[len(operator) :].strip()
                break
        factors = cls._top_level_parenthesized_chunks(body)
        if len(factors) < 2:
            return []
        first, *rest = factors
        return [f"{prefix} {first}".strip() if prefix else first] + rest

    @staticmethod
    def _top_level_parenthesized_chunks(text: str) -> list[str]:
        chunks: list[str] = []
        index = 0
        length = len(text)
        while index < length:
            while index < length and text[index].isspace():
                index += 1
            if index >= length:
                break
            if text[index] != "(":
                return []
            start = index
            depth = 0
            while index < length:
                char = text[index]
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            chunks.append(text[start:index].strip())
        return chunks

    def _pack_terms_to_width(self, tokens: list[tuple[str, str]], *, max_width: int) -> list[str]:
        lines: list[str] = []
        current = tokens[0][1]
        for operator, term in tokens[1:]:
            piece = f"{operator} {term}".strip()
            candidate = f"{current} {piece}".strip()
            if self._measure_formula_width(candidate) > max_width:
                lines.append(current)
                current = piece
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    def _measure_formula_width(self, line: str) -> int:
        image, display_width, _display_height = self._renderer._fit_formula_image(
            line,
            font_size=FORMULA_FONT_SIZE,
            max_display_width=None,
        )
        if image.isNull():
            return max(1, len(line) * 8)
        return display_width

    @classmethod
    def _top_level_operator_terms(cls, formula: str) -> list[tuple[str, str]]:
        lhs, separator, rhs = formula.partition("=")
        prefix = f"{lhs.strip()} =" if separator else ""
        source = rhs.strip() if separator else formula.strip()
        atoms = cls._top_level_terms(source)
        if not atoms:
            return [("", formula.strip())] if formula.strip() else []
        first_operator, first_term = atoms[0]
        first = f"{prefix} {first_operator} {first_term}".strip() if prefix and first_operator else f"{prefix} {first_term}".strip()
        return [("", first)] + atoms[1:]

    @staticmethod
    def _top_level_terms(text: str) -> list[tuple[str, str]]:
        terms: list[tuple[str, str]] = []
        depth = 0
        start = 0
        pending_operator = ""
        index = 0
        while index < len(text):
            command = ""
            if text[index] == "\\":
                command_start = index
                index += 1
                while index < len(text) and text[index].isalpha():
                    index += 1
                command = text[command_start:index]
                if command == r"\left":
                    while index < len(text) and text[index].isspace():
                        index += 1
                    if index < len(text) and text[index] in "([{":
                        depth += 1
                        index += 1
                    continue
                if command == r"\right":
                    while index < len(text) and text[index].isspace():
                        index += 1
                    if index < len(text) and text[index] in ")]}":
                        depth = max(0, depth - 1)
                        index += 1
                    continue
                if command == r"\cdot" and depth == 0:
                    term = text[start:command_start].strip()
                    if term:
                        terms.append((pending_operator, term))
                    pending_operator = r"\cdot"
                    start = index
                    continue
                continue
            char = text[index]
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth = max(0, depth - 1)
            elif depth == 0 and char in "+-" and WrappedFormulaWidget._is_binary_operator(text, index):
                term = text[start:index].strip()
                if term:
                    terms.append((pending_operator, term))
                pending_operator = char
                start = index + 1
            index += 1
        tail = text[start:].strip()
        if tail:
            terms.append((pending_operator, tail))
        return terms

    @staticmethod
    def _is_binary_operator(text: str, index: int) -> bool:
        before = text[:index].rstrip()
        after = text[index + 1 :].lstrip()
        return bool(before and after and before[-1] not in "({[=_^+-")

    @staticmethod
    def _is_grouped_formula_factor(text: str) -> bool:
        value = str(text or "").strip()
        return value.startswith("(") or value.startswith(r"\left")

    @classmethod
    def _is_continuation_group_line(cls, text: str) -> bool:
        value = str(text or "").strip()
        if value.startswith(r"\cdot"):
            value = value[len(r"\cdot") :].strip()
        return cls._is_grouped_formula_factor(value)


class ModuleVisualRBD(QWidget):
    scheme_calculated = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.settings = QSettings("reliability-app", "desktop")
        self.cnt = 1
        self.temp_start: tuple[RBDBlock, str] | None = None
        self.current_scheme_name = "Новая схема"
        self.current_result: CalculationResult | None = None
        self.block_items: dict[str, RBDBlock] = {}
        self.connection_items: dict[str, ConnectionLine] = {}
        self._formula_renderer = QtFormulaHtmlRenderer(
            resource_prefix="formula://latex",
            quality_scale=FORMULA_UI_QUALITY_SCALE,
            fallback_svg=True,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setMinimumWidth(300)
        self.left_scroll.setMaximumWidth(390)
        left_panel = QWidget()
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(10, 10, 10, 10)
        left.setSpacing(10)
        self.left_scroll.setWidget(left_panel)

        self.scene = QGraphicsScene(0, 0, 4000, 3000)
        self.scene.setProperty("editor", self)
        self.view = GraphicsView(self.scene)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.view.setMinimumWidth(720)
        splitter.addWidget(self.view)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(320)
        right_scroll.setMaximumWidth(430)
        panel = QWidget()
        right = QVBoxLayout(panel)
        right.setContentsMargins(8, 8, 8, 8)
        right.setSpacing(7)
        right_scroll.setWidget(panel)

        g_blocks = QGroupBox("Добавление блоков")
        g_blocks_layout = QGridLayout(g_blocks)
        g_blocks_layout.setContentsMargins(8, 8, 8, 8)
        g_blocks_layout.setHorizontalSpacing(6)
        g_blocks_layout.setVerticalSpacing(6)
        for index, (title, direction) in enumerate([("Вход", "in"), ("Выход", "out"), ("Горизонтальный блок", "right"), ("Вертикальный блок", "up"), ("Разветвление вверх", "up_right"), ("Разветвление вниз", "down_right")]):
            btn = QPushButton(title)
            btn.setProperty("role", "compact")
            btn.clicked.connect(lambda _, direction=direction: self.add_block(direction))
            g_blocks_layout.addWidget(btn, index // 2, index % 2)
        right.addWidget(g_blocks)

        g_files = QGroupBox("Шаблоны и файлы")
        g_files_layout = QVBoxLayout(g_files)
        self.template_combo = QComboBox()
        self.template_combo.addItems([template.name for template in built_in_templates()])
        g_files_layout.addWidget(self.template_combo)
        for title, callback in [("Применить шаблон", self.apply_selected_template), ("Проверить схему", self.validate_current_scheme), ("Сохранить схему", self.save_to_file), ("Загрузить схему", self.load_from_file), ("Экспорт SVG", self.export_svg), ("Экспорт PNG", self.export_png)]:
            btn = QPushButton(title)
            btn.clicked.connect(callback)
            g_files_layout.addWidget(btn)
        btn_import_project = QPushButton("Импорт расчета JSON/YAML")
        btn_import_project.clicked.connect(self.import_reliability_project)
        g_files_layout.addWidget(btn_import_project)
        btn_clear = QPushButton("Очистить")
        btn_clear.setProperty("role", "danger")
        btn_clear.clicked.connect(self.clear_scene)
        g_files_layout.addWidget(btn_clear)
        left.addWidget(g_files)

        g_calc = QGroupBox("Параметры расчёта схемы")
        g_calc_layout = QFormLayout(g_calc)
        g_calc_layout.setContentsMargins(8, 8, 8, 8)
        g_calc_layout.setSpacing(6)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Аналитический расчёт", "Метод Монте-Карло", "Приближённый аналитический расчёт"])
        self.time_spin = StepSpinWidget(1, 1_000_000, 1000, step=100)
        self.sim_spin = StepSpinWidget(1000, 500_000, 10000, step=1000)
        g_calc_layout.addRow("Способ расчёта:", self.method_combo)
        g_calc_layout.addRow("Горизонт t:", self.time_spin)
        g_calc_layout.addRow("Число симуляций:", self.sim_spin)
        btn_calc = QPushButton("Рассчитать схему")
        btn_calc.setProperty("role", "primary")
        btn_calc.clicked.connect(lambda: self.calc_graph())
        g_calc_layout.addRow(btn_calc)
        right.addWidget(g_calc)

        g_contribution = QGroupBox("Анализ вклада элементов")
        g_contribution_layout = QVBoxLayout(g_contribution)
        g_contribution_layout.setContentsMargins(8, 8, 8, 8)
        g_contribution_layout.setSpacing(6)
        contribution_hint = QLabel("Гистограмма показывает нормированный вклад элементов текущей схемы.")
        contribution_hint.setWordWrap(True)
        contribution_hint.setProperty("role", "muted")
        self.contribution_metric_combo = QComboBox()
        for metric in CONTRIBUTION_METRICS:
            self.contribution_metric_combo.addItem(CONTRIBUTION_METRIC_LABELS[metric], metric)
        self.contribution_metric_combo.currentIndexChanged.connect(lambda _: self.refresh_contribution_analysis())
        self.contribution_fig = Figure(figsize=(3.5, 2.4), dpi=100, constrained_layout=True)
        self.contribution_canvas = FigureCanvas(self.contribution_fig)
        self.contribution_canvas.setMinimumHeight(220)
        self.contribution_canvas.setMaximumHeight(300)
        self.contribution_ax = self.contribution_fig.add_subplot(111)
        self.contribution_status = QLabel("Постройте или загрузите схему для анализа.")
        self.contribution_status.setWordWrap(True)
        self.contribution_status.setProperty("role", "muted")
        self._contribution_annotation = None
        self._contribution_bars = []
        self._contribution_items = []
        self.contribution_canvas.mpl_connect("motion_notify_event", self._on_contribution_hover)
        g_contribution_layout.addWidget(contribution_hint)
        g_contribution_layout.addWidget(self.contribution_metric_combo)
        g_contribution_layout.addWidget(self.contribution_canvas)
        g_contribution_layout.addWidget(self.contribution_status)
        self.contribution_group = g_contribution

        g_zoom = QGroupBox("Масштаб рабочей области")
        g_formula = QGroupBox("Генератор общей формулы")
        g_formula_layout = QVBoxLayout(g_formula)
        g_formula_layout.setContentsMargins(8, 8, 8, 8)
        g_formula_layout.setSpacing(6)
        self.formula_mode = QComboBox()
        self.formula_mode.addItems(["Краткий вид", "Развернутый вид"])
        self.formula_mode.currentIndexChanged.connect(lambda _: self.refresh_summary())
        btn_formula = QPushButton("Сгенерировать формулу")
        btn_formula.setProperty("role", "primary")
        btn_formula.clicked.connect(self.show_formula_dialog)
        btn_copy_formula = QPushButton("Копировать формулу")
        btn_copy_formula.clicked.connect(self.copy_formula_to_clipboard)
        btn_self_check = QPushButton("Проверить систему")
        btn_self_check.clicked.connect(self.run_self_check)
        self.btn_demo = QPushButton("Демо-схема")
        self.btn_demo.setProperty("role", "primary")
        self.btn_demo.clicked.connect(self.run_demo_scenario)
        self.demo_status = QLabel("")
        self.demo_status.setWordWrap(True)
        self.demo_status.setProperty("role", "muted")
        formula_hint = QLabel("Сценарий: схема → общая формула → расчет.")
        formula_hint.setWordWrap(True)
        g_formula_layout.addWidget(formula_hint)
        g_formula_layout.addWidget(self.formula_mode)
        formula_buttons = QHBoxLayout()
        formula_buttons.setSpacing(6)
        formula_buttons.addWidget(btn_formula)
        formula_buttons.addWidget(btn_copy_formula)
        g_formula_layout.addLayout(formula_buttons)
        g_formula_layout.addWidget(self.btn_demo)
        g_formula_layout.addWidget(self.demo_status)
        g_formula_layout.addWidget(btn_self_check)
        right.addWidget(g_formula)

        g_zoom_layout = QVBoxLayout(g_zoom)
        g_zoom_layout.setContentsMargins(8, 8, 8, 8)
        g_zoom_layout.setSpacing(6)
        zoom_buttons = QHBoxLayout()
        for title, callback, role in [("−", lambda: self.set_zoom(self.view.zoom_percent - 10), "tool"), ("100%", lambda: self.set_zoom(100), None), ("+", lambda: self.set_zoom(self.view.zoom_percent + 10), "tool")]:
            btn = QPushButton(title)
            if role:
                btn.setProperty("role", role)
            btn.clicked.connect(callback)
            zoom_buttons.addWidget(btn)
        btn_fit = QPushButton("По схеме")
        btn_fit.setProperty("role", "compact")
        btn_fit.clicked.connect(self.fit_scheme_to_view)
        zoom_buttons.addWidget(btn_fit)
        self.zoom_label = QLabel("100%")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 300)
        self.zoom_slider.valueChanged.connect(self.set_zoom)
        g_zoom_layout.addLayout(zoom_buttons)
        zoom_value_row = QHBoxLayout()
        zoom_value_row.setSpacing(6)
        zoom_value_row.addWidget(self.zoom_label)
        zoom_value_row.addWidget(self.zoom_slider, 1)
        g_zoom_layout.addLayout(zoom_value_row)
        zoom_hint = QLabel("Ctrl + колесо мыши: масштаб. Средняя кнопка мыши: панорамирование.")
        zoom_hint.setWordWrap(True)
        g_zoom_layout.addWidget(zoom_hint)
        right.addWidget(g_zoom)

        self.summary = WrappedFormulaWidget(renderer=self._formula_renderer)
        summary_group = QGroupBox("Общая формула системы")
        summary_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(6, 6, 6, 6)
        summary_layout.setSpacing(4)
        summary_layout.addWidget(self.summary)
        left.addWidget(summary_group)
        left.addStretch()
        right.addStretch()

        splitter.addWidget(right_scroll)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([980, 400])

        saved_zoom = int(self.settings.value("editor_zoom", DEFAULT_ZOOM))
        self.zoom_slider.setValue(saved_zoom)
        self.set_zoom(saved_zoom)

    def _on_zoom_changed(self, value: int):
        self.zoom_label.setText(f"{value}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_slider.blockSignals(False)
        self.settings.setValue("editor_zoom", value)

    def set_zoom(self, value: int):
        self.view.set_zoom_percent(value)

    def fit_scheme_to_view(self) -> None:
        self.view.fit_to_content()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete:
            for item in self.scene.selectedItems():
                if isinstance(item, RBDBlock):
                    self.remove_block(item)
                elif isinstance(item, ConnectionLine):
                    self.remove_connection(item)
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in {Qt.Key.Key_Equal, Qt.Key.Key_Plus}:
            self.set_zoom(self.view.zoom_percent + 10)
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Minus:
            self.set_zoom(self.view.zoom_percent - 10)
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_0:
            self.set_zoom(100)
            return
        super().keyPressEvent(event)

    def add_block(self, direction: str, *, block: BlockModel | None = None) -> RBDBlock:
        idx = self.cnt
        name = "Start" if direction == "in" else "End" if direction == "out" else f"B{idx}"
        x = 80 + ((idx - 1) % 6) * 180
        y = 100 + ((idx - 1) // 6) * 120
        item = RBDBlock(block.name if block else name, block.kind if block else direction, block.x if block else x, block.y if block else y, block_id=block.block_id if block else None, props=block.params if block else None, is_subscheme=block.is_subscheme if block else False, nested_scheme=block.nested_scheme if block else None)
        item.port_clicked.connect(self.handle_port_click_signal)
        item.block_changed.connect(self.refresh_summary)
        self.scene.addItem(item)
        self.block_items[item.block_id] = item
        self.cnt += 1
        self.view.centerOn(item)
        self.refresh_summary()
        return item

    def add_connection(self, start_block: RBDBlock, start_port: str, end_block: RBDBlock, end_port: str, *, connection_id: str | None = None) -> ConnectionLine:
        line = ConnectionLine(start_block, start_port, end_block, end_port, connection_id=connection_id)
        self.scene.addItem(line)
        self.connection_items[line.connection_id] = line
        start_block.attach_connection(line)
        end_block.attach_connection(line)
        return line

    def handle_port_click_signal(self, block: RBDBlock, port_id: str) -> None:
        if self.temp_start is None:
            self.temp_start = (block, port_id)
            block.set_connecting(True)
            return
        start_block, start_port = self.temp_start
        start_block.set_connecting(False)
        self.temp_start = None
        if start_block == block:
            QMessageBox.warning(self, "Некорректная связь", "Нельзя соединять блок с самим собой.")
            return
        if not self._is_connection_allowed(start_block, start_port, block, port_id):
            return
        self.add_connection(start_block, start_port, block, port_id)
        self.refresh_summary()

    def _is_connection_allowed(self, start_block: RBDBlock, start_port: str, end_block: RBDBlock, end_port: str) -> bool:
        if start_block.direction == "out":
            QMessageBox.warning(self, "Некорректная связь", "У блока «Выход» не может быть исходящих связей.")
            return False
        if end_block.direction == "in":
            QMessageBox.warning(self, "Некорректная связь", "У блока «Вход» не может быть входящих связей.")
            return False
        if any(line.start_block == start_block and line.start_port_id == start_port and line.end_block == end_block and line.end_port_id == end_port for line in self.connection_items.values()):
            QMessageBox.information(self, "Связь уже существует", "Такая связь уже добавлена.")
            return False
        return True

    def remove_block(self, block: RBDBlock) -> None:
        for line in list(block.attached_lines):
            self.remove_connection(line)
        self.block_items.pop(block.block_id, None)
        self.scene.removeItem(block)
        self.refresh_summary()

    def remove_connection(self, line: ConnectionLine) -> None:
        line.start_block.detach_connection(line)
        line.end_block.detach_connection(line)
        self.connection_items.pop(line.connection_id, None)
        self.scene.removeItem(line)
        self.refresh_summary()

    def clear_scene(self) -> None:
        self.scene.clear()
        self.scene.setProperty("editor", self)
        self.scene.setSceneRect(0, 0, 4000, 3000)
        self.block_items.clear()
        self.connection_items.clear()
        self.cnt = 1
        self.temp_start = None
        self.current_result = None
        self.summary.clear()
        self.refresh_contribution_analysis()

    def to_scheme_model(self) -> SchemeModel:
        blocks = [item.to_model() for item in self.block_items.values()]
        blocks.sort(key=lambda item: item.name)
        connections = [item.to_model() for item in self.connection_items.values()]
        return SchemeModel(name=self.current_scheme_name, blocks=blocks, connections=connections)

    def load_scheme_model(self, scheme: SchemeModel) -> None:
        self.clear_scene()
        self.current_scheme_name = scheme.name
        for block in scheme.blocks:
            self.add_block(block.kind, block=block)
        for connection in scheme.connections:
            start_block = self.block_items.get(connection.source_id)
            end_block = self.block_items.get(connection.target_id)
            if start_block and end_block:
                self.add_connection(start_block, connection.source_port, end_block, connection.target_port, connection_id=connection.connection_id or None)
        self._relax_loaded_layout_spacing()
        self._normalize_loaded_layout_if_needed()
        self._refresh_scene_viewport(fit=True)
        self.refresh_summary()

    def _relax_loaded_layout_spacing(self) -> None:
        """Give loaded schemes enough visual air without changing topology or math."""
        items = list(self.block_items.values())
        if len(items) < 2:
            return
        regular = [item for item in items if item.direction not in {"in", "out"}]
        if not regular:
            return

        min_row_gap = 220.0
        min_column_gap = 175.0
        needs_horizontal_air = any(
            0 < abs(a.pos().x() - b.pos().x()) < min_row_gap and abs(a.pos().y() - b.pos().y()) < 80
            for index, a in enumerate(items)
            for b in items[index + 1 :]
        )
        needs_vertical_air = any(
            0 < abs(a.pos().y() - b.pos().y()) < min_column_gap and abs(a.pos().x() - b.pos().x()) < 110
            for index, a in enumerate(regular)
            for b in regular[index + 1 :]
        )
        if not needs_horizontal_air and not needs_vertical_air:
            return

        rect = self.scene.itemsBoundingRect()
        if not rect.isValid() or rect.isEmpty():
            return
        origin = rect.topLeft()
        x_scale = 1.42 if needs_horizontal_air else 1.0
        y_scale = 1.28 if needs_vertical_air else 1.0
        for item in items:
            pos = item.pos()
            item.setPos(QPointF(origin.x() + (pos.x() - origin.x()) * x_scale, origin.y() + (pos.y() - origin.y()) * y_scale))
        for line in self.connection_items.values():
            line.update_path()

    def _normalize_loaded_layout_if_needed(self) -> None:
        """Wrap very long imported single-row diagrams so labels stay readable after fit."""
        items = list(self.block_items.values())
        if len(items) < 6:
            return
        rect = self.scene.itemsBoundingRect()
        if not rect.isValid() or rect.width() < 1100 or rect.height() > 260:
            return

        ordered = sorted(items, key=lambda item: (item.pos().x(), item.pos().y()))
        regular = [item for item in ordered if item.direction not in {"in", "out"}]
        if len(regular) < 4:
            return

        columns = 4
        x0, y0 = 80.0, 110.0
        dx, dy = 280.0, 190.0
        sequence = [item for item in ordered if item.direction == "in"] + regular + [item for item in ordered if item.direction == "out"]
        for index, item in enumerate(sequence):
            row, col = divmod(index, columns)
            item.setPos(QPointF(x0 + col * dx, y0 + row * dy))
        for line in self.connection_items.values():
            line.update_path()

    def _refresh_scene_viewport(self, *, fit: bool = False) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isValid() and not rect.isEmpty():
            padded = rect.adjusted(-120, -90, 120, 90)
            self.scene.setSceneRect(padded)
            if fit:
                self.view.fitInView(padded, Qt.AspectRatioMode.KeepAspectRatio)
                self.view.zoom_percent = max(25, min(300, int(round(self.view.transform().m11() * 100))))
                self.view.zoom_changed.emit(self.view.zoom_percent)
            else:
                self.view.centerOn(padded.center())
            return
        self.scene.setSceneRect(0, 0, 4000, 3000)

    def clear_validation_highlights(self) -> None:
        for block in self.block_items.values():
            block.set_validation_state()
        for line in self.connection_items.values():
            line.refresh_style(False)

    def _validation_problem_blocks(self, scheme: SchemeModel) -> tuple[set[str], set[str], list[str]]:
        """Return error/warning block ids and topology notes for visual diagnostics."""
        error_ids: set[str] = set()
        warning_ids: set[str] = set()
        notes: list[str] = []
        ids = {block.block_id for block in scheme.blocks}
        by_id = {block.block_id: block for block in scheme.blocks}
        incoming = {block.block_id: 0 for block in scheme.blocks}
        outgoing = {block.block_id: 0 for block in scheme.blocks}
        adjacency: dict[str, list[str]] = {block.block_id: [] for block in scheme.blocks}
        reverse: dict[str, list[str]] = {block.block_id: [] for block in scheme.blocks}

        names: dict[str, list[str]] = {}
        for block in scheme.blocks:
            names.setdefault(block.name, []).append(block.block_id)
        for block_ids in names.values():
            if len(block_ids) > 1:
                error_ids.update(block_ids)

        starts = [block.block_id for block in scheme.blocks if block.kind == "in"]
        ends = [block.block_id for block in scheme.blocks if block.kind == "out"]
        if len(starts) != 1:
            error_ids.update(starts)
        if len(ends) != 1:
            error_ids.update(ends)

        for connection in scheme.connections:
            if connection.source_id not in ids or connection.target_id not in ids:
                error_ids.update({connection.source_id, connection.target_id} & ids)
                continue
            if connection.source_id == connection.target_id:
                error_ids.add(connection.source_id)
                continue
            outgoing[connection.source_id] += 1
            incoming[connection.target_id] += 1
            adjacency[connection.source_id].append(connection.target_id)
            reverse[connection.target_id].append(connection.source_id)

        for block in scheme.blocks:
            if block.kind == "in" and incoming[block.block_id] > 0:
                error_ids.add(block.block_id)
            if block.kind == "out" and outgoing[block.block_id] > 0:
                error_ids.add(block.block_id)
            if block.kind not in {"in", "out"} and incoming[block.block_id] == 0:
                warning_ids.add(block.block_id)
            if block.kind not in {"in", "out"} and outgoing[block.block_id] == 0:
                warning_ids.add(block.block_id)

        if len(starts) == 1 and len(ends) == 1:
            reachable: set[str] = set()
            stack = [starts[0]]
            while stack:
                current = stack.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                stack.extend(adjacency.get(current, []))
            can_reach_end: set[str] = set()
            stack = [ends[0]]
            while stack:
                current = stack.pop()
                if current in can_reach_end:
                    continue
                can_reach_end.add(current)
                stack.extend(reverse.get(current, []))
            used_path = reachable & can_reach_end
            unused_ids = [
                block_id
                for block_id in ids - used_path
                if by_id[block_id].kind not in {"in", "out"}
            ]
            warning_ids.update(unused_ids)
            if unused_ids:
                notes.append(
                    "Не входят в путь от входа к выходу: "
                    + ", ".join(sorted(by_id[block_id].name for block_id in unused_ids))
                )

        warning_ids.difference_update(error_ids)
        return error_ids, warning_ids, notes

    def apply_validation_highlights(self, result=None) -> list[str]:
        scheme = self.to_scheme_model()
        error_ids, warning_ids, notes = self._validation_problem_blocks(scheme)
        for block_id, block in self.block_items.items():
            if block_id in error_ids:
                block.set_validation_state(
                    "error",
                    "Ошибка схемы. Проверьте связи, вход/выход и уникальность имени блока.",
                )
            elif block_id in warning_ids:
                block.set_validation_state(
                    "warning",
                    "Предупреждение: блок может быть не включен в расчетный путь.",
                )
            else:
                block.set_validation_state()
        return notes

    def validate_current_scheme(self) -> None:
        result = validate_scheme(self.to_scheme_model())
        extra_notes = self.apply_validation_highlights(result)
        self.refresh_summary()
        if result.ok:
            text = "Схема прошла проверку."
            if result.warnings:
                text += "\n\nПредупреждения:\n- " + "\n- ".join(result.warnings)
            QMessageBox.information(self, "Проверка схемы", text)
        else:
            QMessageBox.warning(self, "Проверка схемы", "\n".join(result.errors))

    def _obsolete_refresh_summary(self) -> None:
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        formula = build_formula_for_scheme(scheme)
        parts = [
            f"<b>Схема:</b> {scheme.name}",
            f"<b>Блоков:</b> {len(scheme.blocks)} | <b>Связей:</b> {len(scheme.connections)}",
            f"<b>Проверка:</b> {'успешно' if validation.ok else 'есть ошибки'}",
        ]
        if validation.errors:
            parts.append("<b>Ошибки:</b><br>" + "<br>".join(f"• {text}" for text in validation.errors))
        if validation.warnings:
            parts.append("<b>Предупреждения:</b><br>" + "<br>".join(f"• {text}" for text in validation.warnings))
        parts.append(f"<b>Формула:</b><br>{formula.text}")
        if formula.note:
            parts.append(f"<b>Комментарий:</b> {formula.note}")
        if self.current_result:
            lines = "<br>".join(f"• {name}: {value:.6f}" if isinstance(value, float) else f"• {name}: {value}" for name, value in self.current_result.indicators.items())
            parts.append(f"<b>Последний расчёт:</b><br>{lines}")
        self.summary.setHtml("<br><br>".join(parts))

    def _obsolete_run_self_check_with_expected_logic(self) -> None:
        """Run demonstrational checks with expected formula logic."""
        expected_logic = [
            "ожидание: последовательное произведение B1 · B2",
            "ожидание: параллельный блок 1 - (1 - B2)(1 - B3)",
            "ожидание: последовательность с вложенным параллельным участком",
            "ожидание: резерв 1+1 как 1 - (1 - P)^2",
        ]
        lines: list[str] = []
        ok_count = 0
        for index, template in enumerate(built_in_templates()):
            try:
                formula = build_formula_for_scheme(template)
                result = calculate_scheme_reliability(template, time_horizon=1000, simulations=1000, method="Самопроверка")
                value = float(result.indicators.get("P", 0.0))
                ok = formula.is_exact and 0.0 <= value <= 1.0 and "(B1 - 1)" not in formula.text and "+ 1" not in formula.text
                ok_count += 1 if ok else 0
                marker = "OK" if ok else "Ошибка"
                expected = expected_logic[index] if index < len(expected_logic) else "ожидание: корректная формула"
                generated = formula.text.splitlines()[0] if formula.text else "формула не построена"
                lines.append(f"{marker}: {template.name} | P={value:.6f}\n  {expected}\n  получено: {generated}")
            except Exception as exc:
                lines.append(f"Ошибка: {template.name} | {exc}")
        report = "\n".join(lines)
        self.summary.setPlainText("Самопроверка генератора формул\n\n" + report)
        QMessageBox.information(
            self,
            "Самопроверка генератора формул",
            f"Проверено примеров: {len(lines)}\nУспешно: {ok_count}\n\n{report}",
        )

    def _obsolete_show_formula_dialog_message_box(self) -> None:
        """Build and show the current structural formula explicitly."""
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        formula = build_formula_for_scheme(scheme)
        expanded = not hasattr(self, "formula_mode") or self.formula_mode.currentIndex() == 1
        self.refresh_summary()
        message = formula.text
        if formula.note:
            message += f"\n\nКомментарий: {formula.note}"
        if validation.errors:
            message += "\n\nОшибки схемы:\n" + "\n".join(f"- {text}" for text in validation.errors)
            QMessageBox.warning(self, "Формула по схеме", message)
        else:
            QMessageBox.information(self, "Формула по схеме", message)

    def _formula_html(self, formula, *, expanded: bool) -> str:
        if not expanded:
            return self._formula_latex_brief_html(formula)
        parts = [
            "<div style='border:1px solid #cbd5e1; border-radius:8px; padding:10px; background:#f8fafc;'>",
            "<b>Формулы надежности в LaTeX</b>",
        ]
        package = getattr(formula, "package", None)
        if package is not None:
            parts.append(self._formula_package_sections_html(package))
            if getattr(package, "warnings", None):
                warnings = "".join(f"<li>{escape(text)}</li>" for text in package.warnings)
                parts.append(f"<b>Предупреждения</b><ul>{warnings}</ul>")
            if getattr(package, "limitations", ""):
                parts.append(f"<p><b>Ограничения:</b> {escape(str(package.limitations))}</p>")
        else:
            latex = str(getattr(formula, "latex", "") or "").strip()
            fallback = latex or formula.text or formula_short_text(formula)
            parts.append(self._latex_block_html(fallback))
        parts.append("</div>")
        return "".join(parts)

    def _formula_latex_brief_html(self, formula) -> str:
        formulas = self._formula_latex_brief_lines(formula) or [formula_short_text(formula)]
        brief_lines: list[str] = []
        for line in formulas:
            brief_lines.extend(self._display_formula_lines_for_ui(line, max_line_length=72))
        body = self._latex_lines_html(
            brief_lines or formulas,
            font_size=FORMULA_FONT_SIZE,
            prefer_svg=False,
            separate_lines=True,
            max_display_width=660,
        )
        return (
            "<div style='border:1px solid #cbd5e1; border-radius:8px; padding:10px; background:#f8fafc;'>"
            "<b>Формула надежности в LaTeX</b>"
            f"{body}"
            "</div>"
        )

    def _summary_formula_html(self, formula) -> str:
        formulas = self._formula_latex_brief_lines(formula) or [formula_short_text(formula)]
        summary_lines: list[str] = []
        for line in formulas[:1]:
            summary_lines.extend(self._display_formula_lines_for_ui(line, max_line_length=72))
        body = self._latex_lines_html(
            summary_lines,
            compact=True,
            align="left",
            font_size=FORMULA_FONT_SIZE,
            prefer_svg=False,
            separate_lines=True,
            max_display_width=None,
        )
        return "<div style='margin:0; padding:0; width:100%; text-align:left;'>" + body + "</div>"

    def _summary_formula_latex(self, formula) -> str:
        formulas = self._formula_latex_brief_lines(formula) or [formula_short_text(formula)]
        return str(formulas[0] if formulas else "").strip()

    @classmethod
    def _display_formula_lines_for_ui(cls, line: str, *, max_line_length: int = 72) -> list[str]:
        """Format a copy of LaTeX for UI display without changing copied/calculated formulas."""
        text = str(line or "").strip()
        if not text:
            return []
        multiplier_lines = cls._display_product_formula_lines(text, max_line_length=max_line_length)
        if multiplier_lines:
            return multiplier_lines
        lines = split_latex_formula_for_display(text, max_line_length=max_line_length)
        if len(lines) > 1:
            return lines
        return cls._split_latex_for_summary(text, max_line_length=max_line_length)

    @classmethod
    def _display_product_formula_lines(cls, text: str, *, max_line_length: int = 72) -> list[str]:
        """Split UI-only formula by top-level products and keep bracketed groups intact."""
        if len(text) <= max_line_length:
            return []
        lhs, separator, rhs = text.partition("=")
        if not separator:
            return []
        lhs = f"{lhs.strip()} ="
        factors = cls._top_level_latex_product_factors(rhs.strip())
        if len(factors) < 2:
            return []
        lines: list[str] = []
        current = f"{lhs} {factors[0]}".strip()
        current_factor_count = 1
        for factor in factors[1:]:
            candidate = rf"{current} \cdot {factor}".strip()
            should_break_before = (
                cls._display_formula_weight(candidate) > 34
                or current_factor_count >= 3
                or cls._is_grouped_formula_factor(factor) and current.startswith(lhs) and len(factors) <= 3
                or cls._is_continuation_group_line(current)
            )
            if should_break_before:
                lines.append(current)
                current = rf"\cdot {factor}".strip()
                current_factor_count = 1
            else:
                current = candidate
                current_factor_count += 1
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _is_grouped_formula_factor(text: str) -> bool:
        value = str(text or "").strip()
        return value.startswith("(") or value.startswith(r"\left")

    @classmethod
    def _is_continuation_group_line(cls, text: str) -> bool:
        value = str(text or "").strip()
        if value.startswith(r"\cdot"):
            value = value[len(r"\cdot") :].strip()
        return cls._is_grouped_formula_factor(value)

    @staticmethod
    def _display_formula_weight(text: str) -> int:
        value = str(text or "")
        value = re.sub(r"\\(?:mathrm|text)\{([^{}]*)\}", r"\1", value)
        value = value.replace(r"\cdot", "·")
        value = value.replace(r"\left", "").replace(r"\right", "")
        value = re.sub(r"[\\{}]", "", value)
        return len(value)

    @staticmethod
    def _top_level_latex_product_factors(text: str) -> list[str]:
        factors: list[str] = []
        depth = 0
        start = 0
        index = 0
        while index < len(text):
            if text.startswith(r"\cdot", index) and depth == 0:
                factor = text[start:index].strip()
                if factor:
                    factors.append(factor)
                index += len(r"\cdot")
                start = index
                continue
            char = text[index]
            if char == "\\":
                command_start = index
                index += 1
                while index < len(text) and text[index].isalpha():
                    index += 1
                command = text[command_start:index]
                if command == r"\left":
                    while index < len(text) and text[index].isspace():
                        index += 1
                    if index < len(text) and text[index] in "([{":
                        depth += 1
                        index += 1
                elif command == r"\right":
                    while index < len(text) and text[index].isspace():
                        index += 1
                    if index < len(text) and text[index] in ")]}":
                        depth = max(0, depth - 1)
                        index += 1
                continue
            if char in "({[":
                depth += 1
            elif char in ")}]":
                depth = max(0, depth - 1)
            index += 1
        tail = text[start:].strip()
        if tail:
            factors.append(tail)
        return factors

    @classmethod
    def _split_latex_for_summary(cls, line: str, *, max_line_length: int = 52) -> list[str]:
        text = str(line or "").strip()
        if not text or len(text) <= max_line_length:
            return [text] if text else []

        left, separator, right = text.partition("=")
        lhs = f"{left.strip()} =" if separator else ""
        rhs = right.strip() if separator else text
        terms = cls._top_level_split(rhs, r" \cdot ")
        if len(terms) > 1:
            lines: list[str] = []
            current = f"{lhs} {terms[0]}".strip() if lhs else terms[0]
            for term in terms[1:]:
                candidate = f"{current} \\cdot {term}"
                if len(candidate) > max_line_length and current:
                    lines.append(current)
                    current = rf"\cdot {term}"
                else:
                    current = candidate
            if current:
                lines.append(current)
            return lines or [text]

        if rhs.startswith("1 - "):
            complement_lines = cls._split_complement_rhs(lhs, rhs, max_line_length=max_line_length)
            if complement_lines:
                return complement_lines

        return [text]

    @classmethod
    def _split_complement_rhs(cls, lhs: str, rhs: str, *, max_line_length: int) -> list[str]:
        remainder = rhs[4:].strip()
        if not remainder:
            return [f"{lhs} 1 -".strip()] if lhs else [rhs]

        factors = cls._top_level_parenthesized_factors(remainder)
        if not factors:
            if len(rhs) > max_line_length and lhs:
                return [f"{lhs} {rhs}".strip()]
            return [rhs] if not lhs else [f"{lhs} {rhs}".strip()]

        first_factor, *other_factors = factors
        first_line = f"{lhs} 1 - {first_factor}".strip() if lhs else f"1 - {first_factor}"
        lines = [first_line]
        current = ""
        for factor in other_factors:
            candidate = f"{current}{factor}" if current else factor
            if current and len(candidate) > max_line_length:
                lines.append(current)
                current = factor
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _top_level_parenthesized_factors(text: str) -> list[str]:
        result: list[str] = []
        index = 0
        length = len(text)
        while index < length:
            while index < length and text[index].isspace():
                index += 1
            if index >= length:
                break
            if text[index] != "(":
                return []

            depth = 0
            start = index
            while index < length:
                char = text[index]
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            factor = text[start:index]
            while index < length and text[index].isspace():
                index += 1
            if index < length and text[index] == "^":
                exp_start = index
                index += 1
                if index < length and text[index] == "{":
                    brace_depth = 1
                    index += 1
                    while index < length and brace_depth > 0:
                        if text[index] == "{":
                            brace_depth += 1
                        elif text[index] == "}":
                            brace_depth -= 1
                        index += 1
                factor += text[exp_start:index]
            result.append(factor.strip())
        return result

    @staticmethod
    def _top_level_split(text: str, separator: str) -> list[str]:
        parts: list[str] = []
        depth = 0
        start = 0
        index = 0
        while index < len(text):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif depth == 0 and text.startswith(separator, index):
                parts.append(text[start:index].strip())
                index += len(separator)
                start = index
                continue
            index += 1
        parts.append(text[start:].strip())
        return [part for part in parts if part]

    @staticmethod
    def _formula_latex_brief_lines(formula) -> list[str]:
        package = getattr(formula, "package", None)
        if package is not None:
            lines = [
                item.instantiated_latex or item.display_latex or item.general_latex
                for item in getattr(package, "formulas", [])
                if item.instantiated_latex or item.display_latex or item.general_latex
            ]
            return lines[:1]
        latex = str(getattr(formula, "latex", "") or "").strip()
        return [latex] if latex else []

    def _formula_plain_text(self, formula, *, expanded: bool) -> str:
        if not expanded:
            brief = self._formula_latex_brief_lines(formula) or [formula_short_text(formula)]
            return "\n".join(["Общая формула системы (LaTeX)"] + brief)
        package = getattr(formula, "package", None)
        if package is not None:
            lines = ["Общая формула системы (LaTeX)"]
            lines.extend(self._formula_package_sections_plain(package))
            if getattr(package, "warnings", None):
                lines.extend(["", "Предупреждения:"])
                lines.extend(f"- {warning}" for warning in package.warnings)
            if getattr(package, "limitations", ""):
                lines.extend(["", "Ограничения:", str(package.limitations)])
            return "\n".join(lines)
        return "\n".join(["Общая формула системы (LaTeX)", str(getattr(formula, "latex", "") or formula.text)])

    def _reset_formula_resources(self) -> None:
        self._formula_renderer.reset()

    def _set_html_with_formula_resources(self, viewer: QTextEdit, html: str) -> None:
        self._formula_renderer.set_html(viewer, html)

    def _qt_formula_image_html(
        self,
        line: str,
        *,
        font_size: int,
        align: str = "center",
        margin: str = "4px 0",
        max_display_width: int | None = None,
    ) -> str:
        return self._formula_renderer.formula_image_html(
            line,
            font_size=font_size,
            align=align,
            margin=margin,
            max_display_width=max_display_width,
        )

    def _qt_formula_lines_html(
        self,
        lines: list[str],
        *,
        font_size: int,
        align: str,
        margin: str,
        line_margin: str,
        max_display_width: int | None,
    ) -> str:
        return self._formula_renderer.formula_line_images_html(
            lines,
            font_size=font_size,
            align=align,
            margin=margin,
            line_margin=line_margin,
            max_display_width=max_display_width,
        )

    def _latex_block_html(
        self,
        line: str,
        *,
        compact: bool = False,
        align: str = "left",
        font_size: int | None = None,
        prefer_svg: bool = True,
        max_display_width: int | None = None,
    ) -> str:
        rendered = self._formula_renderer.formula_value_html(
            line,
            compact=compact,
            align=align,
            font_size=font_size,
            prefer_svg=prefer_svg,
            max_display_width=max_display_width,
        )
        if rendered:
            if compact:
                return (
                    f"<div style='margin:2px 0; padding:0; width:100%; text-align:{align};'>"
                    + rendered.replace("margin:6px 0;", "margin:0;")
                    + "</div>"
                )
            return rendered
        font_size = "11pt" if compact else "12pt"
        margin = "2px 0" if compact else "6px 0"
        return (
            "<pre style='white-space:pre-wrap; word-break:break-word; "
            f"font-family:Consolas,monospace; font-size:{font_size}; margin:{margin}; width:100%; text-align:{align};'>"
            f"{escape(line)}</pre>"
        )

    def _latex_lines_html(
        self,
        lines: list[str],
        *,
        compact: bool = False,
        align: str = "left",
        font_size: int | None = None,
        prefer_svg: bool = True,
        separate_lines: bool = False,
        max_display_width: int | None = None,
    ) -> str:
        return self._formula_renderer.formula_lines_html(
            lines,
            compact=compact,
            align=align,
            font_size=font_size,
            prefer_svg=prefer_svg,
            separate_lines=separate_lines,
            max_display_width=max_display_width,
        )

    @staticmethod
    def _latex_to_image_html(line: str) -> str:
        return QtFormulaHtmlRenderer(fallback_svg=True).formula_value_html(line)

    def _formula_package_sections_html(self, package) -> str:
        parts: list[str] = []
        for title, items in (
            ("Основные формулы", getattr(package, "formulas", [])),
            ("Промежуточные формулы", getattr(package, "intermediate_formulas", [])),
            ("Формулы результатов", getattr(package, "result_formulas", [])),
        ):
            section = self._formula_items_html(title, items)
            if section:
                parts.append(section)
        symbols = self._formula_parameters_html(getattr(package, "parameter_lines", []))
        if symbols:
            parts.append(symbols)
        return "".join(parts)

    @staticmethod
    def _formula_parameters_html(items) -> str:
        rows: list[str] = []
        for item in items:
            name = getattr(item, "name", "")
            value = getattr(item, "value", "")
            comment = getattr(item, "comment", "")
            if not str(name).strip() and not str(value).strip():
                continue
            rows.append(
                "<div style='margin:2px 0; color:#536274; font-size:11px; line-height:1.3; word-break:break-word;'>"
                f"<b>{escape(str(name))}</b> - {escape(str(value))}"
                f"{'; ' + escape(str(comment)) if comment else ''}"
                "</div>"
            )
        return formula_section_html("Обозначения", "".join(rows)) if rows else ""

    def _formula_items_html(self, title: str, items) -> str:
        rows: list[str] = []
        for item in items:
            latex = getattr(item, "instantiated_latex", "") or getattr(item, "display_latex", "") or getattr(item, "general_latex", "")
            if not str(latex).strip():
                continue
            value = getattr(item, "numeric_value", None)
            display_lines = split_latex_formula_for_display(str(latex), max_line_length=90)
            formula_html = (
                self._latex_lines_html(display_lines, font_size=FORMULA_FONT_SIZE, prefer_svg=False, separate_lines=True, max_display_width=660)
                if any(is_renderable_latex_formula(line) for line in display_lines)
                else "".join(readable_formula_html(line, align="left") for line in display_lines)
            )
            rows.append(formula_item_html(getattr(item, "label", ""), formula_html, numeric_value=value, comment=getattr(item, "comment", "")))
        if not rows:
            return ""
        return formula_section_html(title, "".join(rows))

    def _formula_package_sections_plain(self, package) -> list[str]:
        lines: list[str] = []
        for title, items in (
            ("Основные формулы", getattr(package, "formulas", [])),
            ("Промежуточные формулы", getattr(package, "intermediate_formulas", [])),
            ("Формулы результатов", getattr(package, "result_formulas", [])),
        ):
            section_lines = self._formula_items_plain(title, items)
            if section_lines:
                if lines:
                    lines.append("")
                lines.extend(section_lines)
        return lines

    @staticmethod
    def _formula_items_plain(title: str, items) -> list[str]:
        lines: list[str] = []
        for item in items:
            latex = getattr(item, "instantiated_latex", "") or getattr(item, "display_latex", "") or getattr(item, "general_latex", "")
            if not str(latex).strip():
                continue
            if not lines:
                lines.append(title + ":")
            lines.append(f"- {item.label}: {latex}")
            value = getattr(item, "numeric_value", None)
            if value not in (None, ""):
                lines.append(f"  Значение: {value}")
        return lines

    def _method_selection_html(self, scheme: SchemeModel) -> str:
        try:
            return format_method_selection_html(select_method_for_scheme(scheme))
        except Exception as exc:
            return f"<p><b>Анализ схемы и выбор методики:</b> не выполнен: {escape(str(exc))}</p>"

    def _method_selection_plain_text(self, scheme: SchemeModel) -> str:
        try:
            return format_method_selection_text(select_method_for_scheme(scheme))
        except Exception as exc:
            return f"Анализ схемы и выбор методики не выполнен: {exc}"

    def refresh_summary(self) -> None:
        formula = build_formula_for_scheme(self.to_scheme_model())
        self._reset_formula_resources()
        self.summary.set_formula(self._summary_formula_latex(formula))
        self.refresh_contribution_analysis()

    def _selected_contribution_metric(self) -> str:
        if not hasattr(self, "contribution_metric_combo"):
            return "P"
        metric = self.contribution_metric_combo.currentData()
        return str(metric or "P")

    def refresh_contribution_analysis(self) -> None:
        if not hasattr(self, "contribution_ax"):
            return
        metric = self._selected_contribution_metric()
        self.contribution_ax.clear()
        self._contribution_bars = []
        self._contribution_items = []
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        if not validation.ok:
            self.contribution_status.setText("Анализ появится после корректного построения схемы.")
            self.contribution_ax.text(0.5, 0.5, "Нет корректной схемы", ha="center", va="center", color="#667085")
            self.contribution_ax.set_axis_off()
            self.contribution_canvas.draw_idle()
            return
        try:
            analysis = analyze_scheme_contributions(
                scheme,
                time_horizon=self.time_spin.value(),
                metric=metric,
            )
        except Exception as exc:
            self.contribution_status.setText(f"Анализ вклада недоступен: {exc}")
            self.contribution_ax.text(0.5, 0.5, "Анализ недоступен", ha="center", va="center", color="#8a4b18")
            self.contribution_ax.set_axis_off()
            self.contribution_canvas.draw_idle()
            return
        if not analysis.elements:
            self.contribution_status.setText("В схеме нет расчетных элементов.")
            self.contribution_ax.text(0.5, 0.5, "Нет элементов", ha="center", va="center", color="#667085")
            self.contribution_ax.set_axis_off()
            self.contribution_canvas.draw_idle()
            return

        values = [item.contribution_percent[analysis.metric] for item in analysis.elements]
        labels = [_short_axis_label(item.name) for item in analysis.elements]
        bars = self.contribution_ax.bar(range(len(values)), values, color="#2f80ed", alpha=0.86)
        self._contribution_bars = list(bars)
        self._contribution_items = analysis.elements
        self.contribution_ax.set_ylabel("Вклад, %")
        self.contribution_ax.set_xlabel("Элементы схемы")
        self.contribution_ax.set_title(f"Вклад в {analysis.metric_label}", fontsize=10, pad=6)
        self.contribution_ax.set_xticks(range(len(labels)))
        self.contribution_ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        self.contribution_ax.tick_params(axis="y", labelsize=8)
        self.contribution_ax.grid(True, axis="y", linestyle="--", alpha=0.28)
        self.contribution_ax.set_ylim(0.0, max(100.0, max(values) * 1.18 if values else 100.0))
        self._ensure_contribution_annotation()
        if self._contribution_annotation is not None:
            self._contribution_annotation.set_visible(False)
        total = analysis.total_values.get(analysis.metric, 0.0)
        self.contribution_status.setText(
            f"Показатель: {analysis.metric_label}. Итоговое значение схемы: {_format_contribution_value(total)}."
        )
        self.contribution_canvas.draw_idle()

    def _ensure_contribution_annotation(self) -> None:
        if self._contribution_annotation is not None and self._contribution_annotation.axes is self.contribution_ax:
            return
        self._contribution_annotation = self.contribution_ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 16),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.35", "fc": "#ffffff", "ec": "#9db5d1", "alpha": 0.96},
            arrowprops={"arrowstyle": "->", "color": "#7b93ad"},
            fontsize=8,
        )
        self._contribution_annotation.set_visible(False)

    def _on_contribution_hover(self, event) -> None:
        if not self._contribution_bars or self._contribution_annotation is None:
            return
        if event.inaxes is not self.contribution_ax:
            if self._contribution_annotation.get_visible():
                self._contribution_annotation.set_visible(False)
                self.contribution_canvas.draw_idle()
            return
        metric = self._selected_contribution_metric()
        label = CONTRIBUTION_METRIC_LABELS.get(metric, metric)
        for index, bar in enumerate(self._contribution_bars):
            contains, _ = bar.contains(event)
            if not contains:
                continue
            item = self._contribution_items[index]
            contribution = item.contribution_percent.get(metric, 0.0)
            value = item.values.get(metric, 0.0)
            self._contribution_annotation.xy = (bar.get_x() + bar.get_width() / 2, bar.get_height())
            self._contribution_annotation.set_text(
                "Элемент схемы: "
                f"{item.name}\n"
                f"Показатель: {label}\n"
                f"Значение элемента: {_format_contribution_value(value)}\n"
                f"Вклад в общий показатель: {contribution:.2f} %"
            )
            self._contribution_annotation.set_visible(True)
            self.contribution_canvas.draw_idle()
            return
        if self._contribution_annotation.get_visible():
            self._contribution_annotation.set_visible(False)
            self.contribution_canvas.draw_idle()

    def _obsolete_show_formula_dialog_plain_text(self) -> None:
        """Build and show the current structural formula explicitly."""
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        formula = build_formula_for_scheme(scheme)
        self.refresh_summary()
        message = self._formula_plain_text(formula, expanded=True)
        if formula.note:
            message += f"\n\nКомментарий: {formula.note}"
        if validation.errors:
            message += "\n\nОшибки схемы:\n" + "\n".join(f"- {text}" for text in validation.errors)
            QMessageBox.warning(self, "Формула по схеме", message)
        else:
            QMessageBox.information(self, "Формула по схеме", message)

    def copy_formula_to_clipboard(self) -> None:
        scheme = self.to_scheme_model()
        formula = build_formula_for_scheme(scheme)
        expanded = not hasattr(self, "formula_mode") or self.formula_mode.currentIndex() == 1
        clipboard_text = self._formula_plain_text(formula, expanded=expanded)
        if expanded:
            clipboard_text = self._method_selection_plain_text(scheme) + "\n\n" + clipboard_text
        QApplication.clipboard().setText(clipboard_text)
        QMessageBox.information(self, "Формула", "Формула и пояснения скопированы в буфер обмена.")

    def _obsolete_run_self_check_compact(self) -> None:
        lines: list[str] = []
        ok_count = 0
        for template in built_in_templates():
            try:
                formula = build_formula_for_scheme(template)
                selection = select_method_for_scheme(template)
                result = calculate_scheme_reliability(template, time_horizon=1000, simulations=1000, method="Самопроверка")
                value = float(result.indicators.get("P", 0.0))
                ok = formula.is_exact and 0.0 <= value <= 1.0
                ok_count += 1 if ok else 0
                marker = "OK" if ok else "Ошибка"
                lines.append(f"{marker}: {template.name} | P={value:.6f}")
            except Exception as exc:
                lines.append(f"Ошибка: {template.name} | {exc}")
        report = "\n".join(lines)
        self.summary.setPlainText("Самопроверка генератора формул\n\n" + report)
        QMessageBox.information(
            self,
            "Самопроверка",
            f"Проверено примеров: {len(lines)}\nУспешно: {ok_count}\n\n{report}",
        )

    def show_formula_dialog(self) -> None:
        """Show formula as a structured engineering document, not a raw string."""
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        formula = build_formula_for_scheme(scheme)
        expanded = not hasattr(self, "formula_mode") or self.formula_mode.currentIndex() == 1
        self.refresh_summary()
        content = [
            "<h2>Общая формула системы</h2>",
            self._formula_html(formula, expanded=expanded),
        ]
        if expanded:
            content.append("<h3>Подбор сценария и метода</h3>")
            content.append(self._method_selection_html(scheme))
        if validation.errors:
            content.append("<h3>Ошибки схемы</h3>")
            content.append("<br>".join(f"• {escape(text)}" for text in validation.errors))

        dialog = QDialog(self)
        dialog.setWindowTitle("Формула по схеме")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        viewer = QTextEdit()
        viewer.setReadOnly(True)
        viewer.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        viewer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._set_html_with_formula_resources(viewer, "".join(content))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText("Закрыть")
        copy_button = QPushButton("Копировать полностью")
        buttons.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(
                (
                    self._method_selection_plain_text(scheme) + "\n\n"
                    if expanded
                    else ""
                )
                + self._formula_plain_text(formula, expanded=expanded)
            )
        )
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(viewer)
        layout.addWidget(buttons)
        dialog.exec()

    def run_self_check(self) -> None:
        """Show formula consistency diagnostics built from the same FormulaInfo object."""
        lines: list[str] = []
        ok_count = 0
        for template in built_in_templates():
            try:
                formula = build_formula_for_scheme(template)
                result = calculate_scheme_reliability(template, time_horizon=1000, simulations=1000, method="Самопроверка")
                value = float(result.indicators.get("P", 0.0))
                selection = select_method_for_scheme(template)
                symbols_in_formula = set(formula.symbols)
                all_symbols_visible = all(
                    symbol in (formula.text + formula.computational + formula.structural)
                    for symbol in symbols_in_formula
                )
                ok = formula.is_exact and all_symbols_visible and 0.0 <= value <= 1.0
                ok_count += 1 if ok else 0
                marker = "OK" if ok else "Ошибка"
                used = ", ".join(formula.used_blocks) or "нет расчетных блоков"
                unused = ", ".join(formula.unused_blocks) or "нет"
                generated = formula.text.splitlines()[0] if formula.text else "формула не построена"
                lines.append(
                    f"{marker}: {template.name} | P={value:.6f}\n"
                    f"  включены: {used}\n"
                    f"  исключены: {unused}\n"
                    f"  метод: {selection.recommended_method.title}\n"
                    f"  формула: {generated}"
                )
            except Exception as exc:
                lines.append(f"Ошибка: {template.name} | {exc}")
        report = "\n".join(lines)
        self.summary.setPlainText("Самопроверка генератора формул\n\n" + report)
        QMessageBox.information(
            self,
            "Самопроверка генератора формул",
            f"Проверено примеров: {len(lines)}\nУспешно: {ok_count}\n\n{report}",
        )

    def _set_demo_status(self, text: str, *, loading: bool) -> None:
        if hasattr(self, "btn_demo"):
            self.btn_demo.setEnabled(not loading)
            self.btn_demo.setText("Демо-схема..." if loading else "Демо-схема")
        if hasattr(self, "demo_status"):
            self.demo_status.setText(text)
        QApplication.processEvents()

    def _finish_demo_status(self, text: str) -> None:
        self._set_demo_status(text, loading=False)
        if hasattr(self, "demo_status"):
            QTimer.singleShot(3500, lambda: self.demo_status.setText(""))

    def run_sne_demo_scenario(self) -> None:
        """Load the normalized SNE EMRTU reference example and calculate it."""
        self._set_demo_status("Загружаем пример...", loading=True)
        try:
            demo = load_sne_emrtu_demo(
                time_horizon=158,
                simulations=10000,
                method=self.method_combo.currentText(),
            )
        except Exception as exc:
            self._finish_demo_status("Ошибка демо.")
            QMessageBox.critical(self, "Демо СНЭ", f"Не удалось загрузить демонстрационный пример:\n{exc}")
            return

        self._set_demo_status("Строим граф...", loading=True)
        self.time_spin.setValue(demo.time_horizon)
        self.sim_spin.setValue(demo.simulations)
        self.load_scheme_model(demo.scheme)
        validation = validate_scheme(self.to_scheme_model())
        self.apply_validation_highlights(validation)
        self._set_demo_status("Выполняется расчет...", loading=True)
        self.current_result = demo.calculation
        self.refresh_summary()
        self.scheme_calculated.emit(demo.calculation)
        self._finish_demo_status("Готово.")

        comparison_text = "\n".join(comparison_lines_for_display(demo.comparisons))
        message = (
            "Загружен эталонный пример СНЭ ЭМРТУ из структурированного JSON.\n"
            "Схема построена в редакторе, формула сгенерирована, расчет выполнен и передан в калькулятор.\n\n"
            "Резерв 175 из 204 показан одним агрегированным блоком, чтобы схема оставалась читаемой.\n\n"
            f"Источник: {demo.source_path}\n"
            f"Горизонт расчета: {demo.time_horizon} ч\n\n"
            f"Формула:\n{demo.formula_preview}\n\n"
            f"Сравнение с эталоном:\n{comparison_text}"
        )
        QMessageBox.information(self, "Демо СНЭ", message)

    def run_demo_scenario(self) -> None:
        """Load a ready example, validate it, generate formula and calculate results."""
        self._set_demo_status("Загружаем пример...", loading=True)
        templates = built_in_templates()
        if not templates:
            self._finish_demo_status("Ошибка демо.")
            QMessageBox.warning(self, "Демо", "Встроенные демонстрационные схемы не найдены.")
            return
        template = templates[0]
        self.load_scheme_model(template)
        self.time_spin.setValue(1000)
        self.sim_spin.setValue(10000)
        self._set_demo_status("Проверяем схему...", loading=True)
        validation = validate_scheme(self.to_scheme_model())
        self.apply_validation_highlights(validation)
        if not validation.ok:
            self._finish_demo_status("Ошибка демо.")
            QMessageBox.warning(self, "Демо", "Демонстрационная схема содержит ошибки:\n" + "\n".join(validation.errors))
            return
        self._set_demo_status("Генерируем формулы...", loading=True)
        formula = build_formula_for_scheme(self.to_scheme_model())
        self.refresh_summary()
        self._set_demo_status("Выполняется расчет...", loading=True)
        self.calc_graph(show_message=False)
        self._set_demo_status("Строим граф...", loading=True)
        self._finish_demo_status("Готово.")
        QMessageBox.information(
            self,
            "Демо-схема",
            "Демо-схема создана. Нажмите «Рассчитать схему», затем «Сгенерировать формулу».\n\n"
            f"Формула: {formula.text.splitlines()[0] if formula.text else 'не построена'}\n\n"
            "Расчёт выполнен, результаты и график доступны в калькуляторе.",
        )

    def calc_graph(self, *, show_message: bool = True) -> None:
        scheme = self.to_scheme_model()
        validation = validate_scheme(scheme)
        self.apply_validation_highlights(validation)
        if not validation.ok:
            self.current_result = None
            self.refresh_summary()
            QMessageBox.warning(self, "Проверка схемы", "Расчет остановлен: сначала исправьте ошибки схемы.\n\n" + "\n".join(validation.errors))
            return
        try:
            result = calculate_scheme_reliability(scheme, time_horizon=self.time_spin.value(), simulations=self.sim_spin.value(), method=self.method_combo.currentText())
        except ValueError as exc:
            self.current_result = None
            self.refresh_summary()
            QMessageBox.warning(self, "Ошибка расчёта", str(exc))
            return
        self.current_result = result
        self.refresh_summary()
        self.scheme_calculated.emit(result)
        if show_message:
            QMessageBox.information(
                self,
                "Результат расчёта",
                "\n".join(
                    [f"Способ расчёта: {self.method_combo.currentText()}", f"Методика: {result.method_name}"]
                    + [f"{k}: {v:.6f}" if isinstance(v, float) else f"{k}: {v}" for k, v in result.indicators.items()]
                ),
            )

    def save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранение схемы", "schema_nadezhnosti.json", "Файлы схем (*.json)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        try:
            save_scheme(target, self.to_scheme_model())
        except Exception as exc:
            QMessageBox.critical(self, "Сохранение схемы", str(exc))
            return
        QMessageBox.information(self, "Сохранение схемы", f"Схема успешно сохранена:\n{target}")

    def load_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Загрузка схемы", "", "Файлы схем (*.json)")
        if not path:
            return
        validation = validate_scheme_file(path)
        if not validation.ok:
            QMessageBox.warning(self, "Загрузка схемы", "\n".join(validation.errors))
            return
        try:
            self.load_scheme_model(load_scheme(path))
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось загрузить схему:\n{exc}")

    def import_reliability_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт расчета надежности",
            "",
            "Reliability import (*.json *.yaml *.yml)",
        )
        if not path:
            return
        try:
            project = load_imported_project(path)
            scheme_names = [
                f"{scheme_id}: {scheme.get('name', scheme_id)}"
                for scheme_id, scheme in project.schemes.items()
            ]
            selected, ok = QInputDialog.getItem(
                self,
                "Импорт расчета надежности",
                "Схема:",
                scheme_names,
                0,
                False,
            )
            if not ok or not selected:
                return
            scheme_id = selected.split(":", 1)[0]
            scheme = imported_project_to_scheme(project, scheme_id, time_horizon=self.time_spin.value())
            self.load_scheme_model(scheme)
            warnings = scheme.metadata.get("import_warnings", []) + scheme.metadata.get("manual_review_required", [])
        except Exception as exc:
            QMessageBox.critical(self, "Импорт расчета надежности", f"Не удалось импортировать проект:\n{exc}")
            return
        message = f"Импортирована схема: {scheme.name}"
        if warnings:
            message += "\n\nПредупреждения и ручная проверка:\n" + "\n".join(f"- {item}" for item in warnings[:8])
        QMessageBox.information(self, "Импорт расчета надежности", message)

    def export_svg(self) -> None:
        path, _ = choose_save_path(self, "Экспорт схемы в SVG", [SaveFormat("SVG", ".svg", "schema_nadezhnosti.svg")])
        if path is None:
            return
        try:
            export_scene_to_svg(self.scene, path)
        except Exception as exc:
            notify_save_result(self, path, success=False, title="Экспорт SVG", error=str(exc))
            return
        notify_save_result(self, path, success=True, title="Экспорт SVG")

    def export_png(self) -> None:
        path, _ = choose_save_path(self, "Экспорт схемы в PNG", [SaveFormat("PNG", ".png", "schema_nadezhnosti.png")])
        if path is None:
            return
        try:
            export_scene_to_png(self.scene, path)
        except Exception as exc:
            notify_save_result(self, path, success=False, title="Экспорт PNG", error=str(exc))
            return
        notify_save_result(self, path, success=True, title="Экспорт PNG")

    def export_current_scene_png(self, path: str | Path) -> str:
        return str(export_scene_to_png(self.scene, path))

    def apply_selected_template(self) -> None:
        template = next((item for item in built_in_templates() if item.name == self.template_combo.currentText()), None)
        if template is not None:
            self.load_scheme_model(template)

    def edit_subscheme(self, block: RBDBlock) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Подсхема блока {block.name}")
        fit_widget_to_screen(dialog, width_ratio=0.92, height_ratio=0.88)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        editor = ModuleVisualRBD()
        editor.load_scheme_model(block.nested_scheme or self._default_subscheme_for_block(block))
        editor._refresh_scene_viewport(fit=True)
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button is not None:
            save_button.setText("Сохранить подсхему")
        if cancel_button is not None:
            cancel_button.setText("Назад без сохранения")

        def accept_if_valid() -> None:
            nested_scheme = editor.to_scheme_model()
            validation = validate_scheme(nested_scheme)
            if not validation.ok:
                QMessageBox.warning(
                    dialog,
                    "Проверка подсхемы",
                    "Подсхему нельзя сохранить, пока в ней есть ошибки:\n\n" + "\n".join(validation.errors),
                )
                return
            dialog.accept()

        buttons.accepted.connect(accept_if_valid)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            block.prepareGeometryChange()
            block.is_subscheme = True
            block.props["block_role"] = "subscheme"
            block.nested_scheme = editor.to_scheme_model()
            for line in block.attached_lines:
                line.update_path()
            block.update()
            self.scene.update()
            self.refresh_summary()

    @staticmethod
    def _default_subscheme_for_block(block: RBDBlock) -> SchemeModel:
        """Create a minimal editable pass-through subscheme for a newly opened block."""
        return SchemeModel(
            name=f"Подсхема {block.name}",
            blocks=[
                BlockModel("nested_start", "Start", "in", 120, 140, {}),
                BlockModel("nested_end", "End", "out", 360, 140, {}),
            ],
            connections=[ConnectionModel("nested_c1", "nested_start", "out", "nested_end", "in")],
            metadata={"parent_block_id": block.block_id, "parent_block_name": block.name},
        )
