"""Universal calculator for the F1.1-F7.2 reliability methods.

The widget builds a dynamic parameter form from ``normative_methods``, calls
the calculation functions from ``dependability_backend``, visualizes graph
data with matplotlib and exports user-selected report/plot files. Method
descriptions are shown as a compact expandable passport rather than mixed
directly into the input form.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import app.utils.app_constants as const
from app.import_export.file_service import SaveFormat, choose_save_path, notify_save_result
from app.formulas.formula_package import generate_formula_package
from app.formulas.formula_rendering import (
    FORMULA_FONT_SIZE,
    formula_dict_to_html,
    formula_dict_to_plain,
    formula_item_html,
    formula_section_html,
    latex_block,
    latex_to_html,
    readable_formula_text,
    result_metric_formulas_for,
    result_metric_latex_for,
)
from app.gui.gui_dialogs import DialogLoadModule, DialogNomenclature, DialogReportSettings, DialogSaveModule, export_report_bundle
from app.core.normative_methods import get_method_spec, supported_method_names
from app.core.rbd_models import CalculationResult, ReportData, SchemeModel, formula_short_text
from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer
from app.core.reliability_contribution_analysis import (
    CONTRIBUTION_METRIC_LABELS,
    CONTRIBUTION_METRICS,
    analyze_scheme_contributions,
)
from app.import_export.scheme_storage import scheme_from_dict


CALC_FORMULA_UI_QUALITY_SCALE = 2


def _short_axis_label(value: str, *, limit: int = 18) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "..."


def _format_contribution_value(value: float) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(numeric) >= 1000 or (0 < abs(numeric) < 0.001):
        return f"{numeric:.4g}"
    return f"{numeric:.6g}"


class PlotAndFormulaWidget(QWidget):
    """График и область отображения нормативной формулы."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.fig = Figure(figsize=(6, 3.2), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(220)
        self.canvas.setMaximumHeight(360)
        layout.addWidget(self.canvas)
        self.ax_plot = self.fig.add_subplot(111)
        self.formula_view = QTextEdit()
        self.formula_view.setReadOnly(True)
        self.formula_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.formula_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.formula_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.formula_view.setMinimumHeight(96)
        self.formula_view.setMaximumHeight(520)
        self.formula_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.formula_view.setPlaceholderText("Формула, связанная с графиком, появится после расчета.")
        self._formula_renderer = QtFormulaHtmlRenderer(
            resource_prefix="formula://calculator",
            quality_scale=CALC_FORMULA_UI_QUALITY_SCALE,
        )

    def update_view(self, x_values, y_values, formulas: dict[str, str]):
        self.ax_plot.clear()
        if x_values is not None and y_values is not None:
            self.ax_plot.plot(x_values, y_values, color="#1f6fb2", linewidth=2.2)
            self.ax_plot.set_xlabel("Время t")
            self.ax_plot.set_ylabel("Значение")
            self.ax_plot.grid(True, linestyle="--", alpha=0.35)
        formula_lines = "\n".join(f"${value}$" for value in formulas.values()) if formulas else "Нормативная формула не задана."
        self.formula_view.setPlainText(_readable_formula_text(formula_lines.replace("$", "")))
        _fit_text_edit_to_document(self.formula_view, min_height=96, max_height=520)
        _fit_parent_frame_to_child(self.formula_view)
        self.canvas.draw()

    def export_plot(self, path: str | Path):
        self.fig.savefig(path, bbox_inches="tight")

    def set_formula_html(self, html: str) -> None:
        self._formula_renderer.set_html(self.formula_view, html)
        _fit_text_edit_to_document(self.formula_view, min_height=96, max_height=900)
        _fit_parent_frame_to_child(self.formula_view)

    def reset_formula_resources(self) -> None:
        self._formula_renderer.reset()

    def formula_dict_to_qt_html(self, formulas: dict[str, str]) -> str:
        return self._formula_renderer.formula_dict_html(formulas)

    def formula_value_to_qt_html(self, value: object) -> str:
        return self._formula_renderer.formula_value_html(value)

    def _qt_formula_image_html(self, line: str, *, font_size: int, max_display_width: int) -> str:
        return self._formula_renderer.formula_image_html(
            line,
            font_size=font_size,
            max_display_width=max_display_width,
        )


class ContributionAnalysisWidget(QWidget):
    """Central tab with the per-element reliability contribution histogram."""

    def __init__(self):
        super().__init__()
        self._result: CalculationResult | None = None
        self._scheme: SchemeModel | None = None
        self._contribution_annotation = None
        self._contribution_bars = []
        self._contribution_items = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Анализ вклада элементов")
        title_font = QFont(title.font())
        title_font.setBold(True)
        title_font.setPointSize(max(10, title_font.pointSize() + 1))
        title.setFont(title_font)
        layout.addWidget(title)

        hint = QLabel("Гистограмма показывает нормированный вклад элементов текущей схемы")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)

        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 0, 0, 0)
        metric_row.setSpacing(6)
        metric_row.addWidget(QLabel("Показатель:"))
        self.metric_combo = QComboBox()
        for metric in CONTRIBUTION_METRICS:
            self.metric_combo.addItem(CONTRIBUTION_METRIC_LABELS[metric], metric)
        self.metric_combo.currentIndexChanged.connect(lambda _: self.refresh())
        metric_row.addWidget(self.metric_combo, stretch=1)
        layout.addLayout(metric_row)

        self.fig = Figure(figsize=(7.2, 3.4), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(300)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.ax = self.fig.add_subplot(111)
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        layout.addWidget(self.canvas, stretch=1)

        self.status = QLabel("Анализ появится после расчета структурной схемы.")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status, stretch=0)
        self.clear()

    def clear(self) -> None:
        self._result = None
        self._scheme = None
        self.ax.clear()
        self.ax.text(0.5, 0.5, "Нет рассчитанной схемы", ha="center", va="center", color="#667085")
        self.ax.set_axis_off()
        self.status.setText("Анализ появится после расчета структурной схемы.")
        self._contribution_bars = []
        self._contribution_items = []
        self.canvas.draw_idle()

    def set_result(self, result: CalculationResult | None) -> None:
        self._result = result
        self._scheme = self._scheme_from_result(result)
        self.refresh()

    def _scheme_from_result(self, result: CalculationResult | None) -> SchemeModel | None:
        if result is None:
            return None
        scheme_data = (result.details or {}).get("scheme")
        if isinstance(scheme_data, SchemeModel):
            return scheme_data
        if isinstance(scheme_data, dict):
            try:
                return scheme_from_dict(scheme_data)
            except Exception:
                return None
        return None

    def _selected_metric(self) -> str:
        return str(self.metric_combo.currentData() or "P")

    def _time_horizon(self) -> int:
        points = (self._result.graph_points or {}).get("t") if self._result is not None else None
        if isinstance(points, (list, tuple)) and points:
            try:
                return max(1, int(max(float(item) for item in points)))
            except (TypeError, ValueError):
                pass
        return 1000

    def refresh(self) -> None:
        self.ax.clear()
        self._contribution_bars = []
        self._contribution_items = []
        if self._scheme is None:
            self.ax.text(0.5, 0.5, "Нет рассчитанной схемы", ha="center", va="center", color="#667085")
            self.ax.set_axis_off()
            self.status.setText("Анализ доступен после расчета схемы из редактора.")
            self.canvas.draw_idle()
            return
        metric = self._selected_metric()
        try:
            analysis = analyze_scheme_contributions(self._scheme, time_horizon=self._time_horizon(), metric=metric)
        except Exception as exc:
            self.ax.text(0.5, 0.5, "Анализ недоступен", ha="center", va="center", color="#8a4b18")
            self.ax.set_axis_off()
            self.status.setText(f"Анализ вклада недоступен: {exc}")
            self.canvas.draw_idle()
            return
        if not analysis.elements:
            self.ax.text(0.5, 0.5, "Нет расчетных элементов", ha="center", va="center", color="#667085")
            self.ax.set_axis_off()
            self.status.setText("В схеме нет расчетных элементов.")
            self.canvas.draw_idle()
            return

        values = [item.contribution_percent[analysis.metric] for item in analysis.elements]
        labels = [_short_axis_label(item.name) for item in analysis.elements]
        bars = self.ax.bar(range(len(values)), values, color="#2f80ed", alpha=0.86)
        self._contribution_bars = list(bars)
        self._contribution_items = analysis.elements
        self.ax.set_ylabel("Вклад, %")
        self.ax.set_xlabel("Элементы схемы")
        self.ax.set_title(f"Вклад в {analysis.metric_label}", fontsize=10, pad=6)
        self.ax.set_xticks(range(len(labels)))
        self.ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        self.ax.tick_params(axis="y", labelsize=8)
        self.ax.grid(True, axis="y", linestyle="--", alpha=0.28)
        self.ax.set_ylim(0.0, max(100.0, max(values) * 1.18 if values else 100.0))
        self._ensure_annotation()
        if self._contribution_annotation is not None:
            self._contribution_annotation.set_visible(False)
        total = analysis.total_values.get(analysis.metric, 0.0)
        self.status.setText(
            f"Показатель: {analysis.metric_label}. Итоговое значение схемы: {_format_contribution_value(total)}."
        )
        self.canvas.draw_idle()

    def _ensure_annotation(self) -> None:
        if self._contribution_annotation is not None and self._contribution_annotation.axes is self.ax:
            return
        self._contribution_annotation = self.ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 16),
            textcoords="offset points",
            bbox={"boxstyle": "round,pad=0.35", "fc": "#ffffff", "ec": "#9db5d1", "alpha": 0.96},
            arrowprops={"arrowstyle": "->", "color": "#7b93ad"},
            fontsize=8,
        )
        self._contribution_annotation.set_visible(False)

    def _on_hover(self, event) -> None:
        if not self._contribution_bars or self._contribution_annotation is None:
            return
        if event.inaxes is not self.ax:
            if self._contribution_annotation.get_visible():
                self._contribution_annotation.set_visible(False)
                self.canvas.draw_idle()
            return
        metric = self._selected_metric()
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
                f"Элемент схемы: {item.name}\n"
                f"Показатель: {label}\n"
                f"Значение элемента: {_format_contribution_value(value)}\n"
                f"Вклад в общий показатель: {contribution:.2f} %"
            )
            self._contribution_annotation.set_visible(True)
            self.canvas.draw_idle()
            return
        if self._contribution_annotation.get_visible():
            self._contribution_annotation.set_visible(False)
            self.canvas.draw_idle()


class SchemeStructureWidget(QWidget):
    """Compact read-only scheme graph for the calculator result tabs."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setMinimumHeight(320)
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.view)
        self._empty_text: QGraphicsSimpleTextItem | None = None
        self.set_result(None)

    def set_result(self, result) -> None:
        self.scene.clear()
        self._empty_text = None
        scheme = None
        formula_symbols = {}
        if result is not None:
            details = getattr(result, "details", {}) or {}
            scheme = details.get("scheme")
            formula = getattr(result, "formula", None)
            formula_symbols = dict(getattr(formula, "symbols", {}) or details.get("formula_symbols", {}) or {})
        if not isinstance(scheme, dict) or not scheme.get("blocks"):
            self._show_empty("Схема появится здесь после расчета по структурной схеме.")
            return
        self._draw_scheme(scheme, formula_symbols)

    def _show_empty(self, text: str) -> None:
        item = self.scene.addSimpleText(text)
        item.setBrush(QBrush(QColor("#667085")))
        item.setPos(20, 20)
        self._empty_text = item
        self.scene.setSceneRect(0, 0, 620, 320)

    def _draw_scheme(self, scheme: dict, formula_symbols: dict[str, str]) -> None:
        blocks = [block for block in scheme.get("blocks", []) if isinstance(block, dict)]
        connections = [conn for conn in scheme.get("connections", []) if isinstance(conn, dict)]
        symbol_by_name = {str(name): str(symbol) for symbol, name in formula_symbols.items()}
        node_rects: dict[str, tuple[float, float, float, float]] = {}
        font = QFont()
        font.setPointSize(9)
        badge_font = QFont()
        badge_font.setPointSize(9)
        badge_font.setBold(True)
        visible_blocks = [
            block for block in blocks
            if str(block.get("kind") or "") not in {"in", "out", "junction"}
        ]
        ordered = sorted(visible_blocks, key=lambda block: (float(block.get("x", 0.0) or 0.0), float(block.get("y", 0.0) or 0.0), str(block.get("name", ""))))
        display_positions = self._display_positions(ordered)
        for index, block in enumerate(ordered):
            block_id = str(block.get("block_id") or block.get("id") or f"node_{index}")
            name = str(block.get("name") or block_id)
            x, y = display_positions.get(block_id, (80.0 + index * 220.0, 80.0))
            label = _ellipsize(name, 30)
            badge = _scheme_badge(block_id, name, symbol_by_name)
            width = 190.0
            height = 72.0
            rect = QGraphicsRectItem(x, y, width, height)
            rect.setBrush(QBrush(QColor("#f8fbff")))
            rect.setPen(QPen(QColor("#7ea6cf"), 1.4))
            rect.setToolTip(f"{badge}: {name}" if badge else name)
            self.scene.addItem(rect)
            rect.setZValue(1)
            badge_text = QGraphicsSimpleTextItem(badge, rect)
            badge_text.setBrush(QBrush(QColor("#153c61")))
            badge_text.setFont(badge_font)
            badge_text.setPos(10, 7)
            badge_text.setZValue(2)
            label_text = QGraphicsSimpleTextItem(label, rect)
            label_text.setBrush(QBrush(QColor("#26394d")))
            label_text.setFont(font)
            label_text.setPos(10, 34)
            label_text.setToolTip(name)
            label_text.setZValue(2)
            node_rects[block_id] = (x, y, width, height)

        for conn in connections:
            source_id = str(conn.get("source_id", ""))
            target_id = str(conn.get("target_id", ""))
            if source_id not in node_rects or target_id not in node_rects:
                continue
            sx, sy, sw, sh = node_rects[source_id]
            tx, ty, tw, th = node_rects[target_id]
            line = QGraphicsLineItem(sx + sw, sy + sh / 2.0, tx, ty + th / 2.0)
            line.setPen(QPen(QColor("#7b93ad"), 1.2))
            self.scene.addItem(line)
            line.setZValue(-1)

        if not node_rects:
            self._show_empty("В схеме нет расчетных узлов для отображения.")
            return
        rect = self.scene.itemsBoundingRect().adjusted(-42, -42, 42, 42)
        self.scene.setSceneRect(rect)
        self.fit_to_view()

    def _display_positions(self, blocks: list[dict]) -> dict[str, tuple[float, float]]:
        count = max(1, len(blocks))
        viewport_width = max(720, self.view.viewport().width())
        columns = max(1, min(count, max(3, int(viewport_width // 230))))
        if count <= 6:
            columns = count
        elif count <= 12:
            columns = min(5, count)
        positions: dict[str, tuple[float, float]] = {}
        for index, block in enumerate(blocks):
            block_id = str(block.get("block_id") or block.get("id") or f"node_{index}")
            col = index % columns
            row = index // columns
            positions[block_id] = (70.0 + col * 230.0, 70.0 + row * 125.0)
        return positions

    def fit_to_view(self) -> None:
        rect = self.scene.itemsBoundingRect().adjusted(-42, -42, 42, 42)
        if rect.isValid() and not rect.isEmpty():
            self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            scale = self.view.transform().m11()
            if scale < 0.72:
                self.view.resetTransform()
                self.view.scale(0.72, 0.72)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fit_to_view()


def _ellipsize(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _scheme_badge(block_id: str, name: str, symbol_by_name: dict[str, str]) -> str:
    if name in symbol_by_name:
        return symbol_by_name[name]
    compact_id = str(block_id or "").strip()
    if compact_id and compact_id.lower() not in {"start", "end"}:
        return compact_id
    return _ellipsize(str(name or compact_id), 8)


def _legacy_readable_formula_text(text: str) -> str:
    """Convert project LaTeX-like formula strings to compact readable math text."""
    result = str(text)
    fraction_pattern = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
    while True:
        updated = fraction_pattern.sub(r"(\1)/(\2)", result)
        if updated == result:
            break
        result = updated
    replacements = {
        r"\lambda": "λ",
        r"\gamma": "γ",
        r"\sum": "Σ",
        r"\prod": "Π",
        r"\left": "",
        r"\right": "",
        r"\quad": "  ",
        r"\cdot": "·",
        r"\Sigma": "Σ",
        r"\Pi": "Π",
        r"\lfloor": "⌊",
        r"\rfloor": "⌋",
        r"\ldots": "...",
        r"\text": "",
        "^": "^",
        "_": "_",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result.replace("{", "").replace("}", "")


def _readable_formula_text(text: str) -> str:
    """Use the shared renderer so formulas look identical in UI and exports."""
    return readable_formula_text(text)


def _short_value(value) -> str:
    """Return a compact text representation for values shown near the graph formula."""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        preview = ", ".join(_short_value(item) for item in list(value)[:3])
        suffix = "" if len(value) <= 3 else f", ... ({len(value)} знач.)"
        return f"[{preview}{suffix}]"
    return str(value)


def _fit_text_edit_to_document(
    widget: QTextEdit,
    *,
    min_height: int = 80,
    max_height: int = 520,
) -> None:
    """Keep read-only HTML blocks in the details tab close to their content height."""
    viewport_width = widget.viewport().width() or widget.width() or 760
    widget.document().setTextWidth(max(160, viewport_width - 14))
    document_height = int(math.ceil(widget.document().size().height()))
    frame_height = widget.frameWidth() * 2
    height = max(min_height, min(max_height, document_height + frame_height + 18))
    widget.setMinimumHeight(height)
    widget.setMaximumHeight(height)
    widget.updateGeometry()


def _fit_parent_frame_to_child(widget: QWidget, *, max_height: int = 960) -> None:
    """Let a details card wrap its only expanding child instead of compressing it."""
    parent = widget.parentWidget()
    if not isinstance(parent, QFrame):
        return
    layout = parent.layout()
    margins = layout.contentsMargins() if layout is not None else parent.contentsMargins()
    frame_height = parent.frameWidth() * 2
    desired_height = widget.maximumHeight() + margins.top() + margins.bottom() + frame_height
    height = min(max_height, desired_height)
    parent.setMinimumHeight(height)
    parent.setMaximumHeight(height)
    parent.updateGeometry()


def _formula_parameters_html(parameters: dict | None) -> str:
    """Build a small parameter line for the formula block under the graph."""
    if not parameters:
        return ""
    names = {
        "t": "t",
        "n": "n",
        "m": "m",
        "r1": "r1",
        "r2": "r2",
        "r3": "r3",
        "lam": "λ",
        "lam1": "λ1",
        "lam2": "λ2",
        "lam3": "λ3",
        "lam_p": "λp",
        "lam_s": "λs",
        "lambda_upr": "λупр",
        "t_v": "Tв",
        "t_v1": "Tв1",
        "t_v2": "Tв2",
        "t_p": "Tп",
        "t_upr": "Tупр",
        "t_obn": "Tобн",
        "t_vp": "Tвп",
        "t_dop": "tдоп",
        "Tv_": "Tв",
        "Tv_in": "Tвн",
        "gamma": "γ",
        "p_s": "Ps",
        "k_upr": "Kупр",
        "ko_upr": "Kо,упр",
        "k_1": "K1",
        "k_2": "K2",
        "ko_1": "Kо1",
        "ko_2": "Kо2",
        "lam_list": "λi",
        "tv_list": "Tвi",
    }
    ignored = {"module", "Источник"}
    items = []
    for key, value in parameters.items():
        if key in ignored:
            continue
        label = names.get(key, key)
        items.append(f"<span><b>{escape(str(label))}</b>={escape(_short_value(value))}</span>")
        if len(items) >= 10:
            break
    if not items:
        return ""
    return (
        "<div style='margin-top:6px; color:#536274;'>"
        "<b>Использованные значения:</b> "
        + "; ".join(items)
        + "</div>"
    )


def _method_parameter_docs_html(method_name: str) -> str:
    """Render compact parameter explanations for the formula block under the graph."""
    spec = get_method_spec(method_name)
    if spec is None or not spec.parameter_docs:
        return ""
    items = []
    for doc in spec.parameter_docs.values():
        items.append(
            f"<span><b>{escape(str(doc.symbol))}</b> - {escape(str(doc.name))}, "
            f"{escape(str(doc.unit))}</span>"
        )
        if len(items) >= 8:
            break
    return (
        "<div style='margin-top:6px; color:#536274;'>"
        "<b>Параметры формулы:</b> "
        + "; ".join(items)
        + "</div>"
    )


def _compact_plot_update_view(
    self,
    x_values,
    y_values,
    formulas: dict[str, str],
    method_name: str = "",
    parameters: dict | None = None,
    graph_note: str = "",
):
    """Render a compact graph and refresh the related formula details."""
    self.ax_plot.clear()
    if x_values is not None and y_values is not None:
        self.ax_plot.plot(x_values, y_values, color="#1f6fb2", linewidth=2.2)
        self.ax_plot.set_title("Зависимость показателя от времени", fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel("P(t)")
        self.ax_plot.grid(True, linestyle="--", alpha=0.35)
    else:
        self.ax_plot.set_title("График будет построен после расчета", fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel("P(t)")
        self.ax_plot.grid(True, linestyle="--", alpha=0.25)
    formula_lines = formula_dict_to_html(formulas) if formulas else "Формула для графика пока не задана."
    self.formula_view.setHtml(
        "<b>Формулы методики</b><br>"
        "<span style='color:#536274;'>Используется та же формула/методика, по которой построена кривая.</span><br><br>"
        f"{formula_lines}"
    )
    _fit_text_edit_to_document(self.formula_view, min_height=96, max_height=520)
    _fit_parent_frame_to_child(self.formula_view)
    self.canvas.draw()


PlotAndFormulaWidget.update_view = _compact_plot_update_view


def _graph_formula_update_view(
    self,
    x_values,
    y_values,
    formulas: dict[str, str],
    method_name: str = "",
    parameters: dict | None = None,
    graph_note: str = "",
):
    """Render the graph and the exact formula context used to build its curve."""
    self.ax_plot.clear()
    if x_values is not None and y_values is not None:
        self.ax_plot.plot(x_values, y_values, color="#1f6fb2", linewidth=2.2)
        self.ax_plot.set_title("Зависимость показателя от времени", fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel("P(t)")
        self.ax_plot.grid(True, linestyle="--", alpha=0.35)
    else:
        self.ax_plot.set_title("График будет построен после расчета", fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel("P(t)")
        self.ax_plot.grid(True, linestyle="--", alpha=0.25)

    method_html = f"<div><b>Методика:</b> {escape(method_name)}</div>" if method_name else ""
    formula_lines = formula_dict_to_html(formulas) if formulas else "<span style='color:#8a4b18;'>Формула для графика пока не задана.</span>"
    params_html = _formula_parameters_html(parameters)
    note_html = f"<div style='margin-top:6px; color:#536274;'>{escape(graph_note)}</div>" if graph_note else ""
    self.formula_view.setHtml(
        "<div style='font-size:12px;'>"
        "<b>Формулы методики</b>"
        "<div style='color:#536274; margin:3px 0 6px 0;'>"
        "Показана формула, по которой рассчитаны точки кривой."
        "</div>"
        f"{method_html}"
        f"{formula_lines}"
        f"{params_html}"
        f"{note_html}"
        "</div>"
    )
    _fit_text_edit_to_document(self.formula_view, min_height=96, max_height=520)
    _fit_parent_frame_to_child(self.formula_view)
    self.canvas.draw()


PlotAndFormulaWidget.update_view = _graph_formula_update_view


def _graph_formula_update_view_v2(
    self,
    x_values,
    y_values,
    formulas: dict[str, str],
    method_name: str = "",
    parameters: dict | None = None,
    graph_note: str = "",
    graph_metric: str = "P",
    graph_title: str = "",
):
    """Render graph and refresh the formula/details block."""
    self.ax_plot.clear()
    metric_label = "P(t)" if graph_metric == "P" else graph_metric
    title = graph_title or f"Зависимость показателя {metric_label} от времени"
    if x_values is not None and y_values is not None:
        self.ax_plot.plot(x_values, y_values, color="#1f6fb2", linewidth=2.2)
        self.ax_plot.set_title(title, fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel(metric_label)
        self.ax_plot.grid(True, linestyle="--", alpha=0.35)
    else:
        self.ax_plot.set_title("График будет построен после расчёта", fontsize=10, pad=6)
        self.ax_plot.set_xlabel("Время t")
        self.ax_plot.set_ylabel(metric_label)
        self.ax_plot.grid(True, linestyle="--", alpha=0.25)

    method_html = f"<div><b>Методика:</b> {escape(method_name)}</div>" if method_name else ""
    self.reset_formula_resources()
    formula_lines = self.formula_dict_to_qt_html(formulas)
    docs_html = _method_parameter_docs_html(method_name)
    params_html = _formula_parameters_html(parameters)
    note_html = f"<div style='margin-top:6px; color:#536274;'>{escape(graph_note)}</div>" if graph_note else ""
    self.set_formula_html(
        "<div style='font-size:12px;'>"
        "<div style='font-weight:700; color:#163f63; margin-bottom:6px;'>Формулы методики</div>"
        "<div style='color:#536274; margin:3px 0 6px 0;'>"
        f"Показаны формулы, по которым рассчитаны точки графика для показателя {escape(metric_label)}."
        "</div>"
        f"{method_html}"
        f"{formula_lines}"
        f"{docs_html}"
        f"{params_html}"
        f"{note_html}"
        "</div>"
    )
    self.canvas.draw()


PlotAndFormulaWidget.update_view = _graph_formula_update_view_v2


class ParamWidget(QWidget):
    """Параметр с явными кнопками уменьшения и увеличения."""

    def __init__(self, default_val, min_val, max_val, is_int: bool = False):
        super().__init__()
        self.is_int = is_int
        self.min_val = min_val
        self.max_val = max_val
        self.scale = 1 if is_int else 1000
        self.step = 1 if is_int else 0.001

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn_minus = QPushButton("−")
        self.btn_minus.setProperty("role", "tool")
        self.btn_minus.clicked.connect(self.decrease_value)

        self.line_edit = QLineEdit(str(default_val))
        self.line_edit.setFixedWidth(96)
        self.line_edit.editingFinished.connect(self.sync_slider_from_text)

        self.btn_plus = QPushButton("+")
        self.btn_plus.setProperty("role", "tool")
        self.btn_plus.clicked.connect(self.increase_value)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(min_val * self.scale), int(max_val * self.scale))
        self.slider.setValue(int(float(default_val) * self.scale))
        self.slider.valueChanged.connect(self.sync_text_from_slider)

        layout.addWidget(self.btn_minus)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.btn_plus)
        layout.addWidget(self.slider, stretch=1)
        self.sync_slider_from_text()

    def _set_value(self, value: float):
        value = min(max(value, self.min_val), self.max_val)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(value * self.scale)))
        self.slider.blockSignals(False)
        self.line_edit.setText(str(int(value)) if self.is_int else f"{value:.3f}")

    def sync_text_from_slider(self, value):
        self._set_value(value / self.scale)

    def sync_slider_from_text(self):
        try:
            value = float(self.line_edit.text().replace(",", ".").strip())
        except ValueError:
            value = self.min_val
        self._set_value(value)

    def increase_value(self):
        self._set_value(self.get_value() + self.step)

    def decrease_value(self):
        self._set_value(self.get_value() - self.step)

    def get_value(self):
        try:
            return float(self.line_edit.text().replace(",", "."))
        except ValueError:
            return 0.0


class ModuleUniversalCalc(QWidget):
    """Калькулятор только для нормативно подтверждённых методов."""

    GRAPH_METRICS = ("P", "Kg", "Kog", "T0", "Tv", "Tpr")
    GRAPH_METRIC_PRIORITY = ("P", "Kg", "Kog", "T0", "Tv", "Tpr")
    THRESHOLD_DEFAULTS = {
        "P": "0.90",
        "Kg": "0.90",
        "Kog": "0.90",
        "T0": "1000",
        "Tv": "10",
        "Tpr": "24",
    }
    THRESHOLD_GREATER_IS_BETTER = {"P", "Kg", "Kog", "T0"}

    VAR_DESC = {
        "t": "Время работы t",
        "lam": "Интенсивность отказов λ",
        "lam1": "Интенсивность отказов λ1",
        "lam2": "Интенсивность отказов λ2",
        "lam3": "Интенсивность отказов λ3",
        "lam_p": "Интенсивность отказов переключателя λп",
        "lam_s": "Интенсивность отказов ожидания λs",
        "lambda_upr": "Интенсивность отказов управления λупр",
        "t_v": "Среднее время восстановления Tv",
        "t_v1": "Время восстановления Tv1",
        "t_v2": "Время восстановления Tv2",
        "Tv_": "Среднее время восстановления Tv",
        "Tv_in": "Внутреннее время восстановления",
        "n": "Количество элементов n",
        "m": "Критерий отказа / резерв m",
        "r1": "Размер группы r1",
        "r2": "Размер группы r2",
        "r3": "Размер группы r3",
        "t_p": "Период контроля Tp",
        "t_obn": "Время обнаружения Tobn",
        "t_vp": "Время включения резерва Tvp",
        "t_dop": "Допустимое время простоя",
        "gamma": "Вероятность переключения γ",
        "p_s": "Вероятность отказа переключателя Ps",
        "t_upr": "Время восстановления управления Tupr",
        "k_upr": "Коэффициент покрытия управления Kupr",
        "ko_upr": "Коэффициент опасных отказов Koupr",
        "t_1": "Время восстановления T1",
        "k_1": "Коэффициент покрытия K1",
        "ko_1": "Коэффициент опасных отказов Ko1",
        "t_2": "Время восстановления T2",
        "k_2": "Коэффициент покрытия K2",
        "ko_2": "Коэффициент опасных отказов Ko2",
        "cat3": "Сценарий / категория",
        "cat3_f2": "Сценарий F2.1",
        "cat3_f22": "Сценарий F2.2",
        "cat3_f24": "Сценарий F2.4",
    }

    PARAM_LABELS = {
        "t": "t",
        "lam": "λ",
        "lam1": "λ1",
        "lam2": "λ2",
        "lam3": "λ3",
        "lam_p": "λп",
        "lam_s": "λs",
        "lambda_upr": "λупр",
        "t_v": "Tв",
        "t_v1": "Tв1",
        "t_v2": "Tв2",
        "Tv_": "Tв",
        "Tv_in": "Tвн",
        "n": "n",
        "m": "m",
        "r1": "r1",
        "r2": "r2",
        "r3": "r3",
        "t_p": "Tп",
        "t_obn": "Tобн",
        "t_vp": "Tвп",
        "t_dop": "Tдоп",
        "gamma": "γ",
        "p_s": "Ps",
        "t_upr": "Tупр",
        "k_upr": "Kупр",
        "ko_upr": "Koупр",
        "t_1": "T1",
        "k_1": "K1",
        "ko_1": "Ko1",
        "t_2": "T2",
        "k_2": "K2",
        "ko_2": "Ko2",
        "cat3": "cat3",
        "cat3_f2": "cat3",
        "cat3_f22": "cat3",
        "cat3_f24": "cat3",
    }

    PARAM_CONFIG = {
        "gamma": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.99},
        "p_s": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.01},
        "k_upr": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "ko_upr": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "k_1": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "ko_1": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "k_2": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "ko_2": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.9},
        "n": {"is_int": True, "min": 1, "max": 50, "def": 2},
        "m": {"is_int": True, "min": 1, "max": 50, "def": 1},
        "r1": {"is_int": True, "min": 1, "max": 20, "def": 2},
        "r2": {"is_int": True, "min": 1, "max": 20, "def": 2},
        "r3": {"is_int": True, "min": 1, "max": 20, "def": 2},
        "t": {"is_int": True, "min": 1, "max": 100000, "def": 1000},
        "lam": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.001},
        "lam1": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.001},
        "lam2": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.001},
        "lam3": {"is_int": False, "min": 0.0, "max": 1.0, "def": 0.001},
    }

    METHODS = {
        method_name: {
            "func": spec.func,
            "mode": spec.mode,
            "args": list(spec.args),
            "result_fields": list(spec.result_fields),
        }
        for method_name in supported_method_names()
        for spec in [get_method_spec(method_name)]
        if spec is not None
    }

    CATEGORY_OPTIONS = {
        "cat3": ["Сценарий 1", "Сценарий 2", "Сценарий 3", "Сценарий 4"],
        "cat3_f2": ["Независимое восстановление", "Одновременное восстановление"],
        "cat3_f22": ["Нагруженный резерв", "Облегчённый резерв", "Ненагруженный резерв", "Ненадёжный переключатель"],
        "cat3_f24": ["С ненадёжным переключателем", "С неполным контролем"],
    }

    SCENARIO_DESCRIPTIONS = {
        "cat3": [
            "Сценарий 1: нагруженный резерв. Основные и резервные элементы находятся под нагрузкой, поэтому отказ любого элемента учитывается с одинаковой интенсивностью.",
            "Сценарий 2: облегченный резерв. Резервные элементы работают в облегченном режиме; используется отношение интенсивностей отказов резервного и основного режимов.",
            "Сценарий 3: ненагруженный резерв. Резерв не стареет до включения; модель применяют для холодного резервирования.",
            "Сценарий 4: неоднородные элементы. Используется, когда элементы резервной группы имеют разные интенсивности отказов.",
        ],
        "cat3_f2": [
            "Независимое восстановление: каждый элемент восстанавливается отдельно, а готовность системы определяется по готовностям элементов.",
            "Одновременное восстановление: простой системы рассматривается как общий интервал восстановления после отказа.",
        ],
        "cat3_f22": [
            "Нагруженный резерв с восстановлением: резервные элементы находятся под нагрузкой и могут восстанавливаться после отказа.",
            "Облегченный резерв с восстановлением: резерв работает в менее напряженном режиме до включения.",
            "Ненагруженный резерв с восстановлением: резервный элемент не нагружен до момента включения.",
            "Ненадежный переключатель: дополнительно учитывается отказ устройства переключения резерва.",
        ],
        "cat3_f24": [
            "Вариант с ненадежным переключателем: отказ переключателя влияет на восстановление работоспособности системы.",
            "Вариант с неполным контролем: часть отказов может обнаруживаться с задержкой или не обнаруживаться сразу.",
        ],
    }

    def __init__(self):
        super().__init__()
        self.inputs: dict[str, QWidget] = {}
        self.last_results: dict = {}
        self.last_input_vals: dict = {}
        self.extra_info: dict = {}
        self.nomenclature_info: dict = {}
        self.last_method_name = ""
        self.last_calculation_method = "Аналитический расчёт"
        self.last_formula_dict: dict[str, str] = {}
        self.last_formula_package = None
        self.last_graph_rows: list[tuple[object, object]] = []
        self.last_graph_metric = "P"
        self.last_graph_x_values = None
        self.last_graph_y_values = None
        self.last_graph_note = ""
        self.scheme_result: CalculationResult | None = None

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setMinimumWidth(280)
        self.left_scroll.setMaximumWidth(360)
        input_panel = QFrame()
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(8, 8, 8, 8)
        input_layout.setSpacing(7)
        self.left_scroll.setWidget(input_panel)

        self.cb = QComboBox()
        self.cb.addItems(supported_method_names())
        self.cb.currentIndexChanged.connect(self.build_dynamic_form)
        input_layout.addWidget(QLabel("<b>Нормативная методика расчёта</b>"))
        input_layout.addWidget(self.cb)

        self.method_details_toggle = QToolButton()
        self.method_details_toggle.setText("▸ Описание методики")
        self.method_details_toggle.setCheckable(True)
        self.method_details_toggle.setChecked(False)
        self.method_details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.method_details_toggle.setProperty("role", "detailsToggle")
        self.method_details_toggle.toggled.connect(self._set_method_details_visible)
        input_layout.addWidget(self.method_details_toggle)

        self.method_details_group = QFrame()
        self.method_details_group.setProperty("role", "details")
        self.method_details_group.setVisible(False)
        details_layout = QVBoxLayout(self.method_details_group)
        details_layout.setContentsMargins(8, 8, 8, 8)
        self.method_details = QTextEdit()
        self.method_details.setReadOnly(True)
        self.method_details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.method_details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.method_details.setMinimumHeight(72)
        self.method_details.setMaximumHeight(220)
        self.method_details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.method_details_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._method_details_renderer = QtFormulaHtmlRenderer(
            resource_prefix="formula://method-details",
            quality_scale=CALC_FORMULA_UI_QUALITY_SCALE,
        )
        details_layout.addWidget(self.method_details)
        input_layout.addWidget(self.method_details_group)

        tools_row = QHBoxLayout()
        btn_nom = QPushButton("Справочник")
        btn_nom.clicked.connect(self.open_nomenclature)
        btn_report = QPushButton("Параметры отчёта")
        btn_report.clicked.connect(self.open_report)
        tools_row.addWidget(btn_nom)
        tools_row.addWidget(btn_report)
        input_layout.addLayout(tools_row)

        tools_row_2 = QHBoxLayout()
        btn_save_module = QPushButton("Сохранить шаблон")
        btn_save_module.clicked.connect(self.save_module)
        btn_load_module = QPushButton("Загрузить шаблон")
        btn_load_module.clicked.connect(self.load_module)
        tools_row_2.addWidget(btn_save_module)
        tools_row_2.addWidget(btn_load_module)
        input_layout.addLayout(tools_row_2)

        calc_input_panel = QWidget()
        calc_input_layout = QVBoxLayout(calc_input_panel)
        calc_input_layout.setContentsMargins(0, 0, 0, 0)
        calc_input_layout.setSpacing(7)

        params_panel = QGroupBox("Параметры расчета")
        params_layout = QVBoxLayout(params_panel)
        params_layout.setContentsMargins(8, 8, 8, 8)
        params_layout.setSpacing(7)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_widget = QWidget()
        self.form = QFormLayout(self.scroll_widget)
        self.form.setContentsMargins(6, 6, 6, 6)
        self.form.setSpacing(6)
        self.scroll.setWidget(self.scroll_widget)
        params_layout.addWidget(self.scroll, 1)

        self.tbl_group = QGroupBox("Элементы векторного метода")
        table_layout = QVBoxLayout(self.tbl_group)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Элемент", "λi", "Tвi"])
        self.tbl.setMaximumHeight(190)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self.tbl)
        table_buttons = QHBoxLayout()
        btn_add_row = QPushButton("+")
        btn_add_row.clicked.connect(self.add_row)
        btn_del_row = QPushButton("−")
        btn_del_row.clicked.connect(self.del_row)
        table_buttons.addWidget(btn_add_row)
        table_buttons.addWidget(btn_del_row)
        table_layout.addLayout(table_buttons)
        calc_input_layout.addWidget(self.tbl_group)
        calc_input_layout.addWidget(params_panel, 1)

        btn_calc = QPushButton("Рассчитать")
        self.threshold_toggle = QToolButton()
        self.threshold_toggle.setText("▸ Порог соответствия")
        self.threshold_toggle.setCheckable(True)
        self.threshold_toggle.setChecked(False)
        self.threshold_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.threshold_toggle.setProperty("role", "detailsToggle")
        self.threshold_toggle.toggled.connect(self._set_threshold_panel_visible)
        params_layout.addWidget(self.threshold_toggle)

        self.threshold_group = QFrame()
        self.threshold_group.setProperty("role", "details")
        self.threshold_group.setVisible(False)
        threshold_layout = QFormLayout(self.threshold_group)
        threshold_layout.setContentsMargins(8, 8, 8, 8)
        threshold_layout.setSpacing(6)
        self.threshold_metric_combo = QComboBox()
        self.threshold_metric_combo.currentIndexChanged.connect(self._on_threshold_metric_changed)
        self.threshold_input = QLineEdit(self.THRESHOLD_DEFAULTS["P"])
        self.threshold_input.setToolTip("Порог соответствия для итогового вывода и отчета. Можно выбирать показатель и задавать его порог отдельно.")
        threshold_layout.addRow("Показатель:", self.threshold_metric_combo)
        threshold_layout.addRow("Порог:", self.threshold_input)
        params_layout.addWidget(self.threshold_group)

        btn_calc.setProperty("role", "primary")
        btn_calc.clicked.connect(self.calc)
        params_layout.addWidget(btn_calc)

        btn_export_report = QPushButton("Экспорт отчёта")
        btn_export_report.clicked.connect(self.export_current_report)
        params_layout.addWidget(btn_export_report)

        btn_export_plot = QPushButton("Экспорт графика")
        btn_export_plot.clicked.connect(self.export_plot_image)
        params_layout.addWidget(btn_export_plot)

        input_layout.addStretch()

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(7)

        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("resultsTabs")

        numeric_tab = QWidget()
        numeric_tab.setProperty("role", "resultsPage")
        numeric_layout = QVBoxLayout(numeric_tab)
        numeric_layout.setContentsMargins(6, 6, 6, 6)
        numeric_layout.setSpacing(6)
        self.result_status = QLabel("Выполните расчёт, чтобы увидеть числовые результаты.")
        self.result_status.setWordWrap(True)
        self.result_status.setProperty("role", "hint")
        self.result_status.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.result_status.setMinimumHeight(58)
        self.result_status.setMaximumHeight(112)
        self.result_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        numeric_layout.addWidget(self.result_status, stretch=0)

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["Показатель", "Обозначение", "Значение", "Единицы", "Комментарий"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setWordWrap(False)
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.results_table.setMinimumHeight(110)
        self.results_table.setMaximumHeight(360)
        self.results_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        numeric_layout.addWidget(self.results_table, stretch=0)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.out.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.out.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.out.setMinimumHeight(96)
        self.out.setMaximumHeight(360)
        self.out.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.vis = PlotAndFormulaWidget()
        graph_metric_row = QHBoxLayout()
        graph_metric_row.setContentsMargins(0, 0, 0, 0)
        graph_metric_row.addWidget(QLabel("Показатель графика:"))
        self.graph_metric_combo = QComboBox()
        self.graph_metric_combo.currentIndexChanged.connect(self._on_graph_metric_changed)
        graph_metric_row.addWidget(self.graph_metric_combo, stretch=1)
        numeric_layout.addLayout(graph_metric_row)
        numeric_layout.addWidget(self.vis, stretch=1)

        self.scheme_structure_view = SchemeStructureWidget()
        self.scheme_structure_view.hide()
        analysis_tab = QWidget()
        analysis_tab.setProperty("role", "resultsPage")
        analysis_layout = QVBoxLayout(analysis_tab)
        analysis_layout.setContentsMargins(6, 6, 6, 6)
        analysis_layout.setSpacing(6)
        self.contribution_analysis = ContributionAnalysisWidget()
        analysis_layout.addWidget(self.contribution_analysis)

        details_tab = QWidget()
        details_tab.setProperty("role", "resultsPage")
        details_layout = QVBoxLayout(details_tab)
        details_layout.setContentsMargins(6, 6, 6, 6)
        details_layout.setSpacing(6)
        details_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.details_content = QWidget()
        self.details_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.details_content_layout = QVBoxLayout(self.details_content)
        self.details_content_layout.setContentsMargins(0, 0, 0, 0)
        self.details_content_layout.setSpacing(8)
        self.details_content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.details_scroll.setWidget(self.details_content)
        details_layout.addWidget(self.details_scroll)

        self.graph_formula_toggle = QToolButton()
        self.graph_formula_toggle.setText("▾ Формулы методики")
        self.graph_formula_toggle.setCheckable(True)
        self.graph_formula_toggle.setChecked(True)
        self.graph_formula_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.graph_formula_toggle.setProperty("role", "detailsToggle")
        self.graph_formula_toggle.toggled.connect(self._set_graph_formula_details_visible)
        self.details_content_layout.addWidget(self.graph_formula_toggle, 0, Qt.AlignmentFlag.AlignTop)

        self.graph_formula_group = QFrame()
        self.graph_formula_group.setProperty("role", "details")
        self.graph_formula_group.setVisible(True)
        self.graph_formula_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.graph_formula_group.setMaximumHeight(960)
        graph_formula_layout = QVBoxLayout(self.graph_formula_group)
        graph_formula_layout.setContentsMargins(8, 8, 8, 8)
        graph_formula_layout.setSpacing(6)
        graph_formula_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        graph_formula_layout.addWidget(self.vis.formula_view)
        self.details_content_layout.addWidget(self.graph_formula_group, 0, Qt.AlignmentFlag.AlignTop)
        self.details_content_layout.addWidget(self.out, 0, Qt.AlignmentFlag.AlignTop)

        self.results_tabs.addTab(numeric_tab, "Результаты")
        self.results_tabs.addTab(analysis_tab, "Анализ вкладов")
        self.results_tabs.addTab(details_tab, "Подробности")
        results_layout.addWidget(self.results_tabs)

        splitter.addWidget(calc_input_panel)
        splitter.addWidget(results_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([340, 920])

        self.build_dynamic_form()
        self.add_row()
        self.add_row()

    def current_spec(self):
        return get_method_spec(self.cb.currentText())

    def add_row(self):
        row = self.tbl.rowCount()
        self.tbl.insertRow(row)
        self.tbl.setItem(row, 0, QTableWidgetItem(f"E{row + 1}"))
        self.tbl.setItem(row, 1, QTableWidgetItem("0.001"))
        self.tbl.setItem(row, 2, QTableWidgetItem("10.0"))

    def del_row(self):
        row = self.tbl.currentRow()
        if row >= 0:
            self.tbl.removeRow(row)

    def get_val(self, name: str):
        widget = self.inputs.get(name)
        if widget is None:
            return 0
        if isinstance(widget, QComboBox):
            return widget.currentIndex() + 1
        if isinstance(widget, ParamWidget):
            return widget.get_value()
        if isinstance(widget, QLineEdit):
            try:
                return float(widget.text().replace(",", "."))
            except ValueError:
                return 0.0
        return 0

    def _formula_for_method(self, method_name: str) -> dict[str, str]:
        spec = get_method_spec(method_name)
        return spec.formulas if spec else {}

    def _formula_for_graph(self, method_name: str, kwargs: dict, graph_mode: str) -> dict[str, str]:
        """Select formulas that actually explain the curve currently plotted."""
        formulas = dict(self._formula_for_method(method_name))
        if not formulas:
            return {}

        scenario = None
        for key in ("cat3", "cat3_f2", "cat3_f22", "cat3_f24"):
            if key in kwargs:
                try:
                    scenario = int(kwargs[key])
                except (TypeError, ValueError):
                    scenario = None
                break

        if scenario is not None:
            scenario_key = f"cat3={scenario}"
            selected = {
                name: value
                for name, value in formulas.items()
                if scenario_key in name or "cat3" not in name
            }
            if selected:
                formulas = selected

        if graph_mode == "direct_p":
            p_formulas = {name: value for name, value in formulas.items() if "P" in name or "cat3" in name}
            return p_formulas or formulas

        if graph_mode == "t0_fallback":
            selected = {"P(t) по T0": r"P(t)=e^{-t/T_0}"}
            selected.update({name: value for name, value in formulas.items() if "T_0" in name or "T0" in name})
            return selected

        return formulas

    @classmethod
    def _metric_axis_label(cls, metric: str) -> str:
        return "P(t)" if metric == "P" else metric

    @classmethod
    def _select_default_graph_metric(cls, available_metrics: list[str]) -> str:
        for metric in cls.GRAPH_METRIC_PRIORITY:
            if metric in available_metrics:
                return metric
        return available_metrics[0] if available_metrics else "P"

    @classmethod
    def _available_graph_metrics(cls, result_fields) -> list[str]:
        field_set = {str(field) for field in result_fields}
        return [metric for metric in cls.GRAPH_METRICS if metric in field_set]

    def _refresh_graph_metric_options(self, method_name: str, results: dict | None = None) -> str:
        spec = get_method_spec(method_name)
        available = self._available_graph_metrics(results.keys() if results is not None else (spec.result_fields if spec else ()))
        if not available:
            available = ["P"]
        previous = self.graph_metric_combo.currentText().strip()
        selected = previous if previous in available else self._select_default_graph_metric(available)
        self.graph_metric_combo.blockSignals(True)
        self.graph_metric_combo.clear()
        self.graph_metric_combo.addItems(available)
        self.graph_metric_combo.setCurrentText(selected)
        self.graph_metric_combo.blockSignals(False)
        self.last_graph_metric = selected
        return selected

    def _graph_title(self, metric: str) -> str:
        return f"Зависимость показателя {self._metric_axis_label(metric)} от времени"

    @classmethod
    def _threshold_default_for_metric(cls, metric: str) -> str:
        return cls.THRESHOLD_DEFAULTS.get(metric, "0.90")

    @classmethod
    def _threshold_comparison_caption(cls, metric: str) -> str:
        return "больше или равно порогу" if metric in cls.THRESHOLD_GREATER_IS_BETTER else "меньше или равно порогу"

    @classmethod
    def _threshold_passes(cls, metric: str, metric_value: float, threshold_value: float) -> bool:
        if metric in cls.THRESHOLD_GREATER_IS_BETTER:
            return float(metric_value) >= float(threshold_value)
        return float(metric_value) <= float(threshold_value)

    def _refresh_threshold_options(self, method_name: str, results: dict | None = None) -> str:
        spec = get_method_spec(method_name)
        available = self._available_graph_metrics(results.keys() if results is not None else (spec.result_fields if spec else ()))
        if not available:
            available = ["P"]
        previous = self.threshold_metric_combo.currentText().strip()
        selected = previous if previous in available else self._select_default_graph_metric(available)
        self.threshold_metric_combo.blockSignals(True)
        self.threshold_metric_combo.clear()
        self.threshold_metric_combo.addItems(available)
        self.threshold_metric_combo.setCurrentText(selected)
        self.threshold_metric_combo.blockSignals(False)
        if previous != selected or not self.threshold_input.text().strip():
            self.threshold_input.setText(self._threshold_default_for_metric(selected))
        return selected

    def _graph_note_for_curve(self, metric: str) -> str:
        label = self._metric_axis_label(metric)
        return f"Точки графика для {label} рассчитаны повторным вызовом выбранной методики при разных значениях t."

    def _graph_note_for_constant(self, metric: str, value: float, reason: str = "") -> str:
        label = self._metric_axis_label(metric)
        value_text = f"{float(value):.6g}"
        note = f"Показатель {label} не меняется по времени для текущего расчёта; на графике показана постоянная линия {label}={value_text}."
        if reason:
            note += f" {reason}"
        return note

    def _build_graph_series(self, method_name: str, func, call_kwargs: dict, result: dict, metric: str, time_horizon: int):
        base_value = result.get(metric)
        x_values = np.linspace(0, time_horizon, 60)

        if metric == "P" and "P" in result and "t" in call_kwargs and not method_name.startswith("F7"):
            y_values = []
            for t_i in x_values:
                temp_kwargs = self._normalize_call_kwargs(method_name, call_kwargs.copy())
                temp_kwargs["t"] = int(t_i)
                curve_result = self._filter_results(method_name, func(**temp_kwargs))
                y_values.append(float(curve_result.get("P", 0.0)))
            return x_values, np.array(y_values, dtype=float), "direct_p", self._graph_note_for_curve("P")

        if metric == "P" and "T0" in result and isinstance(result["T0"], (int, float)) and result["T0"] > 0:
            y_values = np.array([math.exp(-t_i / result["T0"]) for t_i in x_values], dtype=float)
            note = "Методика не возвращает отдельную P(t) для графика; кривая построена по P(t)=e^{-t/T0} на основе рассчитанного T0."
            return x_values, y_values, "t0_fallback", note

        if isinstance(base_value, (int, float)):
            if "t" in call_kwargs and not method_name.startswith("F7"):
                sampled_values: list[float] = []
                for t_i in x_values:
                    temp_kwargs = self._normalize_call_kwargs(method_name, call_kwargs.copy())
                    temp_kwargs["t"] = int(t_i)
                    curve_result = self._filter_results(method_name, func(**temp_kwargs))
                    sampled = curve_result.get(metric)
                    if not isinstance(sampled, (int, float)):
                        sampled_values = []
                        break
                    sampled_values.append(float(sampled))
                if sampled_values:
                    y_values = np.array(sampled_values, dtype=float)
                    if np.allclose(y_values, y_values[0], rtol=1e-6, atol=1e-9):
                        return x_values, np.full_like(x_values, float(y_values[0]), dtype=float), "constant_metric", self._graph_note_for_constant(metric, float(y_values[0]))
                    return x_values, y_values, "metric_curve", self._graph_note_for_curve(metric)
            return x_values, np.full_like(x_values, float(base_value), dtype=float), "constant_metric", self._graph_note_for_constant(metric, float(base_value), "Для выбранной методики он вычисляется как итоговое постоянное значение.")

        return None, None, "", "График для выбранного показателя недоступен: значение отсутствует в результатах расчёта."

    def _redraw_last_graph(self) -> None:
        self.vis.update_view(
            self.last_graph_x_values,
            self.last_graph_y_values,
            self.last_formula_dict,
            method_name=self.last_method_name,
            parameters=self.last_input_vals,
            graph_note=self.last_graph_note,
            graph_metric=self.last_graph_metric,
            graph_title=self._graph_title(self.last_graph_metric),
        )
        self.vis.set_formula_html(
            self._formula_details_qt_html(
                self.last_formula_package,
                self.last_formula_dict,
                formula=self.scheme_result.formula if self.scheme_result is not None else None,
                graph_note=self.last_graph_note,
            )
        )

    def _on_graph_metric_changed(self) -> None:
        metric = self.graph_metric_combo.currentText().strip() or "P"
        self.last_graph_metric = metric
        if self.last_results and self.scheme_result is None:
            self.calc()
            return
        if self.last_graph_x_values is not None or self.last_graph_y_values is not None:
            self.last_graph_rows = self._make_graph_rows(self.last_graph_x_values, self.last_graph_y_values, metric)
            self._redraw_last_graph()

    def _on_threshold_metric_changed(self) -> None:
        metric = self.threshold_metric_combo.currentText().strip() or "P"
        self.threshold_input.setText(self._threshold_default_for_metric(metric))
        if self.last_results:
            self._update_numeric_results(self.last_method_name, self.last_results, self.last_calculation_method)

    def _compact_param_label(self, arg: str) -> str:
        return self.PARAM_LABELS.get(arg, arg)

    def open_nomenclature(self):
        dialog = DialogNomenclature(self, initial_data=self.nomenclature_info)
        if dialog.exec():
            self.nomenclature_info = dialog.get_data()
            QMessageBox.information(
                self,
                "Справочник",
                "Номенклатура сохранена.\n\n" + self.nomenclature_info.get("summary_text", ""),
            )

    def _nomenclature_report_block(self) -> tuple[str, str]:
        if not self.nomenclature_info:
            return "", ""
        summary = str(self.nomenclature_info.get("summary_text", "")).strip()
        metrics = str(self.nomenclature_info.get("recommended_metrics_text", "")).strip()
        methodology_block = "\n".join(
            part
            for part in [
                "Номенклатура показателей надёжности:",
                summary,
                metrics,
            ]
            if part
        ).strip()
        notes_block = "\n".join(
            part
            for part in [
                "Номенклатура:",
                summary,
            ]
            if part
        ).strip()
        return methodology_block, notes_block

    @staticmethod
    def _param_tooltip(doc) -> str:
        return (
            f"{doc.symbol} - {doc.name}\n"
            f"{doc.meaning}\n"
            f"Единицы: {doc.unit}\n"
            f"Роль в расчете: {doc.role}"
        )

    @staticmethod
    def _human_formula(text: str) -> str:
        result = text
        replacements = {
            r"\lambda": "λ",
            r"\gamma": "γ",
            r"\sum": "Σ",
            r"\prod": "Π",
            r"\frac": "",
            r"\left": "",
            r"\right": "",
            r"\quad": "  ",
            r"\cdot": "·",
            r"\Sigma": "Σ",
            r"\Pi": "Π",
            "{": "",
            "}": "",
        }
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result

    def _set_method_details_visible(self, checked: bool) -> None:
        """Show or hide the detailed method passport without occupying space when collapsed."""
        self.method_details_toggle.setText("▾ Описание методики" if checked else "▸ Описание методики")
        self.method_details_group.setVisible(checked)
        if checked:
            _fit_text_edit_to_document(self.method_details, min_height=72, max_height=220)
            _fit_parent_frame_to_child(self.method_details, max_height=244)

    def _set_method_details_html(self, html: str) -> None:
        self._method_details_renderer.set_html(self.method_details, html)
        _fit_text_edit_to_document(self.method_details, min_height=72, max_height=220)
        _fit_parent_frame_to_child(self.method_details, max_height=244)

    def _method_formula_dict_to_qt_html(self, formulas: dict[str, str]) -> str:
        return self._method_details_renderer.formula_dict_html(
            formulas,
            font_size=FORMULA_FONT_SIZE,
            max_display_width=660,
        )

    def _formula_item_to_qt_html(self, item) -> str:
        formula = (
            getattr(item, "instantiated_latex", "")
            or getattr(item, "display_latex", "")
            or getattr(item, "general_latex", "")
            or getattr(item, "instantiated_formula", "")
            or getattr(item, "symbolic_template", "")
        )
        formula_html = self.vis.formula_value_to_qt_html(str(formula))
        return formula_item_html(
            getattr(item, "label", ""),
            formula_html,
            numeric_value=getattr(item, "numeric_value", None),
            comment=getattr(item, "comment", ""),
        )

    def _formula_section_to_qt_html(self, title: str, items) -> str:
        rows = "".join(
            self._formula_item_to_qt_html(item)
            for item in sorted(items, key=lambda item: getattr(item, "order", 0))
            if str(
                getattr(item, "instantiated_latex", "")
                or getattr(item, "display_latex", "")
                or getattr(item, "general_latex", "")
                or getattr(item, "instantiated_formula", "")
                or getattr(item, "symbolic_template", "")
            ).strip()
        )
        return formula_section_html(title, rows) if rows else ""

    def _formula_package_to_qt_html(self, package) -> str:
        parts: list[str] = []
        for title, items in (
            ("Основные формулы", getattr(package, "formulas", [])),
            ("Промежуточные формулы", getattr(package, "intermediate_formulas", [])),
            ("Формулы результатов", getattr(package, "result_formulas", [])),
        ):
            section = self._formula_section_to_qt_html(title, items)
            if section:
                parts.append(section)
        parameters = getattr(package, "parameter_lines", [])
        if parameters:
            rows = []
            for item in parameters:
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
            if rows:
                parts.append(formula_section_html("Обозначения блоков", "".join(rows)))
        return "".join(parts)

    def _formula_details_qt_html(self, package, fallback_formulas: dict[str, str], *, formula=None, graph_note: str = "") -> str:
        self.vis.reset_formula_resources()
        parts = ["<div style='font-size:12px; line-height:1.3;'>"]
        if package is not None:
            package_html = self._formula_package_to_qt_html(package)
            if package_html:
                parts.append(package_html)
        elif fallback_formulas:
            parts.append(formula_section_html("Основные формулы", self.vis.formula_dict_to_qt_html(fallback_formulas)))
        else:
            parts.append("<span style='color:#8a4b18;'>Формулы пока не заданы.</span>")
        symbols = getattr(formula, "symbols", None)
        if symbols and "Обозначения блоков" not in "".join(parts):
            parts.append(_block_symbols_table_html(symbols))
        if graph_note:
            parts.append(f"<div style='margin-top:8px; color:#536274;'>{escape(str(graph_note))}</div>")
        parts.append("</div>")
        return "".join(parts)

    def _set_graph_formula_details_visible(self, checked: bool) -> None:
        """Show or hide the formula block in the details tab."""
        self.graph_formula_toggle.setText("▾ Формулы методики" if checked else "▸ Формулы методики")
        self.graph_formula_group.setVisible(checked)
        self.details_content.adjustSize()

    def _set_details_results_html(self, html: str) -> None:
        """Render the compact calculation result table as a normal details section."""
        self.out.setHtml(html)
        _fit_text_edit_to_document(self.out, min_height=96, max_height=520)
        self.details_content.adjustSize()

    def _set_details_results_text(self, text: str) -> None:
        """Render a short details message without expanding the whole tab."""
        self.out.setText(text)
        _fit_text_edit_to_document(self.out, min_height=72, max_height=220)
        self.details_content.adjustSize()

    def _set_threshold_panel_visible(self, checked: bool) -> None:
        """Show or hide the threshold configuration block."""
        self.threshold_toggle.setText("▾ Порог соответствия" if checked else "▸ Порог соответствия")
        self.threshold_group.setVisible(checked)

    def _scenario_details_html(self, config: dict) -> str:
        scenario_args = [arg for arg in config["args"] if arg in self.SCENARIO_DESCRIPTIONS]
        if not scenario_args:
            return "<p style='margin-left:16px;'>Для данной методики отдельный переключаемый сценарий не используется.</p>"
        rows: list[str] = []
        for arg in scenario_args:
            options = self.CATEGORY_OPTIONS.get(arg, [])
            descriptions = self.SCENARIO_DESCRIPTIONS.get(arg, [])
            for index, description in enumerate(descriptions):
                title = options[index] if index < len(options) else f"Сценарий {index + 1}"
                rows.append(f"<li><b>{escape(title)}</b>: {escape(description)}</li>")
        return "<ul>" + "".join(rows) + "</ul>"

    def _format_method_details(self, spec, config: dict) -> str:
        formulas = "".join(
            f"<div style='margin-left:16px;'><b>{escape(name)}:</b>{latex_to_html(latex_block(value))}</div>"
            for name, value in spec.formulas.items()
        )
        params = "".join(
            "<p style='margin-left:16px;'>"
            f"<b>{escape(doc.symbol)}</b> - {escape(doc.name)}. "
            f"{escape(doc.meaning)} "
            f"<i>Единицы:</i> {escape(doc.unit)}. "
            f"<i>Роль:</i> {escape(doc.role)}."
            "</p>"
            for arg, doc in spec.parameter_docs.items()
            if arg in config["args"]
        )
        if config["mode"] == "vector":
            params += (
                "<p style='margin-left:16px;'><b>λi</b> - интенсивность отказов i-го элемента в таблице элементов. "
                "<i>Единицы:</i> 1/ед. времени.</p>"
                "<p style='margin-left:16px;'><b>Tвi</b> - среднее время восстановления i-го элемента в таблице элементов. "
                "<i>Единицы:</i> единица времени.</p>"
            )
        limitations = f"<p><b>Ограничения:</b> {escape(spec.limitations)}</p>" if spec.limitations else ""
        return (
            f"<p><b>Название метода:</b> {escape(spec.display_name)}</p>"
            f"<p><b>Описание:</b> {escape(spec.description)}</p>"
            f"<p><b>Расшифровка параметров:</b></p>{params}"
            f"<p><b>Формулы:</b></p>{formulas}"
            f"<p><b>Пример применения:</b> {escape(spec.example)}</p>"
            f"{limitations}"
            "<p><b>Нормативная база:</b> утвержденный набор формул F1.1-F7.2, используемый в проекте.</p>"
        )

    def build_dynamic_form(self):
        method_name = self.cb.currentText()
        if method_name not in self.METHODS:
            self._set_details_results_text("Выбранный метод недоступен в нормативном режиме.")
            self.vis.update_view(None, None, {}, method_name=method_name)
            self.scheme_structure_view.set_result(None)
            self.contribution_analysis.clear()
            return
        spec = self.current_spec()
        config = self.METHODS[method_name]

        while self.form.count():
            item = self.form.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.inputs = {}

        self.tbl_group.setVisible(config["mode"] == "vector")
        if spec is not None:
            self._method_details_renderer.reset()
            self._set_method_details_html(self._format_method_details(spec, config))
        else:
            self.method_details.setPlainText("Нормативный паспорт метода не найден.")

        self.method_details_toggle.setChecked(False)

        formulas = self._formula_for_method(method_name)
        self.last_formula_dict = formulas
        metric = self._refresh_graph_metric_options(method_name)
        self._refresh_threshold_options(method_name)
        self.vis.update_view(None, None, formulas, method_name=method_name, graph_metric=metric, graph_title=self._graph_title(metric))

        for arg in config["args"]:
            label_text = self._compact_param_label(arg)
            tooltip = ""
            if spec is not None and arg in spec.parameter_docs:
                tooltip = self._param_tooltip(spec.parameter_docs[arg])
            if "cat" in arg:
                combo = QComboBox()
                combo.addItems(self.CATEGORY_OPTIONS.get(arg, ["Сценарий 1"]))
                combo.setToolTip(tooltip)
                self.form.addRow(label_text, combo)
                self.inputs[arg] = combo
                continue
            param_conf = self.PARAM_CONFIG.get(arg)
            if param_conf:
                widget = ParamWidget(param_conf["def"], param_conf["min"], param_conf["max"], param_conf["is_int"])
            else:
                widget = ParamWidget(0.001, 0.0, 1000.0)
            widget.setToolTip(tooltip)
            self.form.addRow(label_text, widget)
            self.inputs[arg] = widget

    def _prepare_call_kwargs(self, method_name: str):
        config = self.METHODS[method_name]
        kwargs = {}
        for arg in config["args"]:
            kwargs[arg] = self.get_val(arg)
        self.last_input_vals = kwargs.copy()
        self.last_input_vals["module"] = method_name

        for key in ("r1", "r2", "r3", "m", "n", "cat3", "cat3_f2", "cat3_f22", "cat3_f24"):
            if key in kwargs:
                kwargs[key] = int(kwargs[key])

        if config["mode"] == "vector":
            lam_list = []
            tv_list = []
            for row in range(self.tbl.rowCount()):
                try:
                    lam_list.append(float(self.tbl.item(row, 1).text().replace(",", ".")))
                    tv_list.append(float(self.tbl.item(row, 2).text().replace(",", ".")))
                except Exception:
                    continue
            kwargs["lam_list"] = lam_list
            kwargs["tv_list"] = tv_list
            if method_name.startswith("F2.1"):
                kwargs["t_v_list"] = tv_list
                kwargs["t_0_list"] = [1 / item if item else 0 for item in lam_list]
            if method_name.startswith("F1.1"):
                kwargs = {"t": kwargs.get("t", 1000), "lam_list": lam_list}
            self.last_input_vals["lam_list"] = lam_list
            self.last_input_vals["tv_list"] = tv_list
        return kwargs

    @staticmethod
    def _normalize_call_kwargs(method_name: str, call_kwargs: dict):
        if method_name.startswith("F7.1") or method_name.startswith("F7.2"):
            call_kwargs.pop("t", None)
        if method_name.startswith("F2.4") and "cat3_f24" in call_kwargs:
            call_kwargs["cat3"] = call_kwargs.pop("cat3_f24")
        if method_name.startswith("F2.1") and "cat3_f2" in call_kwargs:
            call_kwargs["cat3"] = call_kwargs.pop("cat3_f2")
        if method_name.startswith("F2.1") and "t_v_list" in call_kwargs:
            call_kwargs.pop("tv_list", None)
        if method_name.startswith("F2.2") and "cat3_f22" in call_kwargs:
            call_kwargs["cat3"] = call_kwargs.pop("cat3_f22")
        return call_kwargs

    def _filter_results(self, method_name: str, result: dict) -> dict:
        spec = get_method_spec(method_name)
        if spec is None:
            return result
        filtered = {key: value for key, value in result.items() if key in spec.result_fields}
        return filtered or result

    @staticmethod
    def _format_numeric_value(value) -> str:
        if isinstance(value, float):
            return f"{value:.6g}"
        if isinstance(value, int):
            return str(value)
        return str(value)

    @staticmethod
    def _result_metric_meta(key: str) -> tuple[str, str, str, str]:
        meta = {
            "P": ("Вероятность безотказной работы", "P(t)", "-", "Основной показатель надежности за заданное время"),
            "Kg": ("Коэффициент готовности", "Kг", "-", "Доля времени, когда система работоспособна"),
            "Kog": ("Коэффициент оперативной готовности", "Kог", "-", "Готовность с учетом безотказной работы в интервале"),
            "T0": ("Средняя наработка до отказа", "T0", "ч", "Оценка среднего времени до отказа"),
            "Tv": ("Среднее время восстановления", "Tв", "ч", "Оценка времени восстановления работоспособности"),
            "Tpr": ("Среднее время простоя", "Tпр", "ч", "Оценка времени простоя"),
            "lambda": ("Интенсивность отказов", "λ", "1/ч", "Частота отказов в расчете"),
        }
        return meta.get(key, (str(key), str(key), "-", "Расчетный показатель"))

    def _fit_results_table_height(self) -> None:
        """Keep the numeric result table compact when it has only a few rows."""
        self.results_table.resizeRowsToContents()
        header_height = self.results_table.horizontalHeader().height()
        rows_height = sum(self.results_table.rowHeight(row) for row in range(self.results_table.rowCount()))
        frame_height = self.results_table.frameWidth() * 2
        height = header_height + rows_height + frame_height + 8
        height = max(110, min(360, height))
        self.results_table.setMinimumHeight(height)
        self.results_table.setMaximumHeight(height)
        self.results_table.updateGeometry()

    def _threshold_summary(self, results: dict) -> tuple[str, float | None, bool | None, str]:
        metric = self.threshold_metric_combo.currentText().strip() or "P"
        try:
            threshold = float(self.threshold_input.text().replace(",", "."))
        except (AttributeError, ValueError):
            return metric, None, None, "Порог соответствия не задан."
        metric_value = results.get(metric)
        if isinstance(metric_value, (int, float)):
            passed = self._threshold_passes(metric, float(metric_value), threshold)
            if passed:
                return metric, threshold, True, f"Система соответствует заданному порогу по показателю {self._metric_axis_label(metric)}."
            return metric, threshold, False, f"Система не соответствует заданному порогу по показателю {self._metric_axis_label(metric)}."
        return metric, threshold, None, f"Порог задан, но показатель {self._metric_axis_label(metric)} отсутствует в результате."

    def _add_result_row(self, label: str, symbol: str, value, unit: str = "-", comment: str = "") -> None:
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        for column, cell_value in enumerate([label, symbol, self._format_numeric_value(value), unit, comment]):
            item = QTableWidgetItem(str(cell_value))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row, column, item)

    def _update_numeric_results(self, method_name: str, results: dict, calculation_method: str) -> None:
        """Refresh the compact user-facing numeric result table."""
        self.results_table.setRowCount(0)
        threshold_metric, threshold, _threshold_passed, conclusion = self._threshold_summary(results)
        self.result_status.setText(
            f"Методика / сценарий: {method_name or 'не задано'}\n"
            f"Способ расчёта: {calculation_method or 'Аналитический расчёт'}\n"
            f"Итог: {conclusion}"
        )
        self._add_result_row("Выбранная методика / сценарий", "Метод", method_name or "-", "-", "Выбрано пользователем или системой")
        self._add_result_row("Способ расчёта", "-", calculation_method or "Аналитический расчёт", "-", "Отображается отдельно от формул")
        for key, value in results.items():
            label, symbol, unit, comment = self._result_metric_meta(str(key))
            self._add_result_row(label, symbol, value, unit, comment)
        if threshold is not None:
            comparison = self._threshold_comparison_caption(threshold_metric)
            self._add_result_row(
                "Заданный порог",
                f"{self._metric_axis_label(threshold_metric)}пор",
                threshold,
                "-",
                f"Сравнение выполняется по {self._metric_axis_label(threshold_metric)}: {comparison}",
            )
        self._add_result_row("Итоговая оценка", "-", conclusion, "-", "Автоматический вывод по порогу")
        self._fit_results_table_height()
        self.results_tabs.setCurrentIndex(0)

    def calc(self):
        method_name = self.cb.currentText()
        if method_name not in self.METHODS:
            QMessageBox.warning(self, "Расчёт недоступен", "Выбранный режим не подтверждён нормативной базой проекта.")
            return

        config = self.METHODS[method_name]
        func = config["func"]
        kwargs = self._prepare_call_kwargs(method_name)
        try:
            call_kwargs = self._normalize_call_kwargs(method_name, kwargs.copy())
            time_horizon = int(call_kwargs.get("t", 1000))
            raw_result = func(**call_kwargs)
            result = self._filter_results(method_name, raw_result)
            formula_package = generate_formula_package(
                method_name=method_name,
                inputs=call_kwargs,
                numeric_results=result,
            )

            self.last_results = result
            self.last_method_name = method_name
            self.last_calculation_method = "Аналитический расчёт"
            self.last_formula_package = formula_package
            self.scheme_result = None
            self.scheme_structure_view.set_result(None)
            self.contribution_analysis.clear()
            self._refresh_threshold_options(method_name, result)
            self._update_numeric_results(method_name, result, self.last_calculation_method)
            self._set_details_results_html(self._results_to_html(method_name, kwargs, result))

            metric = self._refresh_graph_metric_options(method_name, result)
            x_values, y_values, graph_mode, graph_note = self._build_graph_series(
                method_name,
                func,
                call_kwargs,
                result,
                metric,
                time_horizon,
            )
            self.last_formula_dict = _formula_dict_from_package(formula_package) or self._formula_for_graph(method_name, kwargs, graph_mode)
            self.last_graph_metric = metric
            self.last_graph_x_values = x_values
            self.last_graph_y_values = y_values
            self.last_graph_note = graph_note
            self.last_graph_rows = self._make_graph_rows(x_values, y_values, metric)
            self.vis.update_view(
                x_values,
                y_values,
                self.last_formula_dict,
                method_name=method_name,
                parameters=self.last_input_vals,
                graph_note=graph_note,
                graph_metric=metric,
                graph_title=self._graph_title(metric),
            )
            self.vis.set_formula_html(
                self._formula_details_qt_html(
                    formula_package,
                    self.last_formula_dict,
                    graph_note=graph_note,
                )
            )
        except Exception as exc:
            self._set_details_results_text(f"Ошибка расчёта: {exc}")
            self.result_status.setText(f"Ошибка расчёта: {exc}")

    def _results_to_html(self, method_name: str, inputs: dict, results: dict):
        spec = get_method_spec(method_name)
        rows = "".join(
            f"<tr><td><b>{name}</b></td><td>{value:.6f}</td></tr>" if isinstance(value, (int, float))
            else f"<tr><td><b>{name}</b></td><td>{value}</td></tr>"
            for name, value in results.items()
        )
        inputs_html = "".join(f"<li><b>{key}</b>: {value}</li>" for key, value in inputs.items())
        formula_block = (
            self.last_formula_package.html_text
            if self.last_formula_package is not None
            else ("<br>".join(self._formula_for_method(method_name).values()) or "Нормативная формула отсутствует.")
        )
        limitation_block = ""
        if spec is not None:
            if spec.limitations:
                limitation_block = f"<p><b>Ограничения:</b> {spec.limitations}</p>"
        return (
            f"<h3>{method_name}</h3>"
            f"<p><b>Исходные данные</b></p><ul>{inputs_html}</ul>"
            f"<p><b>Результаты</b></p><table border='1' cellspacing='0' cellpadding='6'>{rows}</table>"
            f"<p><b>Формулы</b><br>{formula_block}</p>"
            f"{limitation_block}"
        )

    def open_nomenclature(self):
        dialog = DialogNomenclature(self)
        if dialog.exec():
            QMessageBox.information(self, "Справочник", "Параметры номенклатуры применены.")

    def open_report(self):
        if not self.last_results:
            QMessageBox.warning(self, "Внимание", "Сначала выполните расчёт.")
            return
        dialog = DialogReportSettings(self.last_results, self)
        if dialog.exec():
            self.extra_info, _ = dialog.get_data()

    @classmethod
    def _make_graph_rows(cls, x_values, y_values, metric: str = "P") -> list[tuple[object, object]]:
        rows: list[tuple[object, object]] = [("t", cls._metric_axis_label(metric))]
        if x_values is None or y_values is None:
            return rows
        for x_value, y_value in zip(x_values, y_values):
            rows.append((round(float(x_value), 6), round(float(y_value), 8)))
        return rows

    def _export_report_plot_snapshot(self) -> str:
        if not self.last_graph_rows:
            return ""
        path = Path(tempfile.gettempdir()) / "grafik_nadezhnosti_report.png"
        try:
            self.vis.export_plot(path)
        except Exception:
            return ""
        return str(path)

    def _build_report_data(self) -> ReportData:
        spec = get_method_spec(self.last_method_name) if self.last_method_name else None
        methodology = spec.methodology_text if spec is not None else self.extra_info.get("Z_3_0", const.ConstText.Z_3_0)
        nomenclature_methodology, nomenclature_notes = self._nomenclature_report_block()
        if nomenclature_methodology:
            methodology = "\n\n".join(part for part in [methodology, nomenclature_methodology] if part)
        note_parts = []
        if spec is not None and spec.limitations:
            note_parts.append(spec.limitations)
        if self.extra_info.get("notes"):
            note_parts.append(self.extra_info["notes"])
        if nomenclature_notes:
            note_parts.append(nomenclature_notes)
        report_inputs = dict(self.last_input_vals)
        report_inputs["Способ расчёта"] = self.last_calculation_method or "Аналитический расчёт"
        chart_path = self._export_report_plot_snapshot()
        threshold_metric, threshold_value, threshold_passed, threshold_conclusion = self._threshold_summary(self.last_results)
        metric_value = self.last_results.get(threshold_metric)
        if threshold_value is not None and isinstance(metric_value, (int, float)):
            status = "соответствует" if threshold_passed else "не соответствует"
            threshold_conclusion = (
                f"Система {status} заданному порогу: "
                f"{self._metric_axis_label(threshold_metric)}={float(metric_value):.6f}, "
                f"порог={threshold_value:.6f}."
            )
        note_parts.append(threshold_conclusion)
        final_conclusion = threshold_conclusion or "Расчет выполнен, итоговые показатели приведены в отчете."
        formula_package = self.last_formula_package
        report_formulas = dict(self.last_formula_dict)
        report_formulas.update(result_metric_formulas_for(self.last_results.keys()))
        return ReportData(
            title=self.last_method_name or "Расчёт надёжности",
            subtitle=self.extra_info.get("subtitle", "Инженерный отчёт по показателям надёжности"),
            created_at=datetime.now(),
            inputs=report_inputs,
            results=self.last_results,
            method_name=self.last_method_name or "Расчёт",
            methodology=methodology,
            calculation_method=self.last_calculation_method or "Аналитический расчёт",
            formula_text=formula_package.plain_text if formula_package is not None else (formula_dict_to_plain(report_formulas) if report_formulas else ""),
            formula_latex=formula_package.latex_text if formula_package is not None else "",
            formula_package=formula_package,
            scheme_name=self.scheme_result.details.get("scheme", {}).get("name", "") if self.scheme_result else "",
            scheme_image_path=self.scheme_result.details.get("scheme_image_path", "") if self.scheme_result else "",
            scheme_images=list(self.scheme_result.details.get("scheme_images", [])) if self.scheme_result else [],
            notes="\n".join(note_parts),
            charts=[chart_path] if chart_path else [],
            metadata={
                "source": "calculator",
                "method_code": spec.code if spec is not None else "",
                "formula_mode": formula_package.formula_mode if formula_package is not None else "",
                "nomenclature": dict(self.nomenclature_info),
            },
            warnings=list(formula_package.warnings) if formula_package is not None else [],
            limitations=[formula_package.limitations] if formula_package is not None and formula_package.limitations else ([spec.limitations] if spec is not None and spec.limitations else []),
            threshold_metric=threshold_metric,
            threshold_value=threshold_value,
            threshold_passed=threshold_passed,
            threshold_conclusion=threshold_conclusion,
            final_conclusion=final_conclusion,
            tables={"Данные графика": self.last_graph_rows} if self.last_graph_rows else {},
        )

    def export_current_report(self):
        if not self.last_results:
            QMessageBox.warning(self, "Внимание", "Нет результатов для экспорта.")
            return
        export_report_bundle(self._build_report_data(), self)

    def export_plot_image(self):
        path, _ = choose_save_path(self, "Экспорт графика", [SaveFormat("PNG", ".png", "grafik_nadezhnosti.png")])
        if path is None:
            return
        try:
            self.vis.export_plot(path)
        except Exception as exc:
            notify_save_result(self, path, success=False, title="Экспорт графика", error=str(exc))
            return
        notify_save_result(self, path, success=True, title="Экспорт графика")

    def save_module(self):
        if not self.last_results:
            QMessageBox.warning(self, "Внимание", "Сначала выполните расчёт.")
            return
        data = self.last_input_vals.copy()
        if "T0" in self.last_results and self.last_results["T0"] != 0:
            data["lambda"] = 1.0 / self.last_results["T0"]
        if "Tv" in self.last_results:
            data["Tv"] = self.last_results["Tv"]
        if "lambda" not in data and "lam" in data:
            data["lambda"] = data["lam"]
        DialogSaveModule(data, self).exec()

    def load_module(self):
        dialog = DialogLoadModule(self)
        if not dialog.exec():
            return
        data = dialog.get_selected_data()
        if not data:
            return
        for arg_name, value in [
            ("lam", data.get("lambda")),
            ("lam1", data.get("lambda")),
            ("t_v", data.get("Tv")),
            ("Tv", data.get("Tv")),
            ("t", data.get("t")),
        ]:
            widget = self.inputs.get(arg_name)
            if widget is None or value is None:
                continue
            if isinstance(widget, ParamWidget):
                widget.line_edit.setText(str(value))
                widget.sync_slider_from_text()
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))
        QMessageBox.information(self, "Загрузка", f"Шаблон '{data['name']}' загружен.")

    def apply_scheme_result(self, result: CalculationResult):
        self.scheme_result = result
        self.last_results = dict(result.indicators)
        self.last_input_vals = {"Источник": "Графический редактор"}
        self.last_method_name = result.method_name
        self._refresh_threshold_options(result.method_name, self.last_results)
        self.last_formula_dict = {"Итоговая формула": _scheme_formula_compact_text(result.formula)} if result.formula else {}
        self._set_details_results_html(
            "<h3>Результат расчёта по схеме</h3>"
            + "".join(
                f"<p><b>{key}</b>: {value:.6f}</p>" if isinstance(value, float) else f"<p><b>{key}</b>: {value}</p>"
                for key, value in result.indicators.items()
            )
            + (f"<p><b>Формула:</b> {result.formula.text}</p>" if result.formula else "")
        )
        probability = float(result.indicators.get("P", 0.0))
        x_values = np.linspace(0, 1000, 30)
        y_values = np.full_like(x_values, probability, dtype=float)
        self.last_graph_metric = "P"
        self.last_graph_x_values = x_values
        self.last_graph_y_values = y_values
        self.last_graph_note = "Для результата схемы показана постоянная линия вероятности безотказной работы."
        self.last_graph_rows = self._make_graph_rows(x_values, y_values, "P")
        self.vis.update_view(
            x_values,
            y_values,
            self.last_formula_dict,
            graph_metric="P",
            graph_title=self._graph_title("P"),
            graph_note=self.last_graph_note,
        )


def _scheme_formula_report_text(formula) -> str:
    if formula is None:
        return ""
    parts = [formula.text]
    if formula.structural:
        parts.extend(["", "Структурное представление:", formula.structural])
    if formula.computational:
        parts.extend(["", "Вычислительное представление:", formula.computational])
    if formula.symbols:
        parts.append("")
        parts.append("Обозначения:")
        parts.extend(f"- {symbol}: {description}" for symbol, description in formula.symbols.items())
    if formula.steps:
        parts.append("")
        parts.append("Построение формулы:")
        parts.extend(f"{index}. {step}" for index, step in enumerate(formula.steps, start=1))
    return "\n".join(parts)


def _scheme_formula_compact_text(formula) -> str:
    return formula_short_text(formula)


def _formula_dict_from_package(package) -> dict[str, str]:
    if package is None:
        return {}
    items = list(package.formulas) + list(package.intermediate_formulas) + list(package.result_formulas)
    return {
        str(item.label): str(item.instantiated_latex or item.display_latex or item.general_latex or item.instantiated_formula or item.symbolic_template)
        for item in items
        if str(item.instantiated_latex or item.display_latex or item.general_latex or item.instantiated_formula or item.symbolic_template).strip()
    }


def _block_symbols_table_html(symbols: dict | None) -> str:
    if not symbols:
        return ""
    rows = "".join(
        "<tr>"
        f"<td style='padding:4px 8px; border-bottom:1px solid #e3ebf5; font-weight:700;'>{escape(str(symbol))}</td>"
        f"<td style='padding:4px 8px; border-bottom:1px solid #e3ebf5;'>{escape(str(description))}</td>"
        "</tr>"
        for symbol, description in symbols.items()
    )
    return (
        "<div style='margin:12px 0 6px 0; color:#163f63; font-size:13px; font-weight:700;'>Обозначения блоков</div>"
        "<table cellspacing='0' cellpadding='0' style='width:100%; border-collapse:collapse; font-size:12px;'>"
        "<tr>"
        "<th align='left' style='padding:4px 8px; border-bottom:1px solid #cbd5e1;'>Обозначение</th>"
        "<th align='left' style='padding:4px 8px; border-bottom:1px solid #cbd5e1;'>Название блока</th>"
        "</tr>"
        f"{rows}"
        "</table>"
    )


def _formula_details_html(package, fallback_formulas: dict[str, str], *, formula=None, graph_note: str = "") -> str:
    parts = ["<div style='font-size:12px; line-height:1.3;'>"]
    if package is not None and str(getattr(package, "html_text", "")).strip():
        parts.append(package.html_text)
    elif fallback_formulas:
        parts.append("<div style='margin:12px 0 6px 0; color:#163f63; font-size:13px; font-weight:700;'>Основные формулы</div>")
        parts.append(formula_dict_to_html(fallback_formulas))
    else:
        parts.append("<span style='color:#8a4b18;'>Формулы пока не заданы.</span>")
    symbols = getattr(formula, "symbols", None)
    if symbols and "Обозначения блоков" not in "".join(parts):
        parts.append(_block_symbols_table_html(symbols))
    if graph_note:
        parts.append(f"<div style='margin-top:8px; color:#536274;'>{escape(str(graph_note))}</div>")
    parts.append("</div>")
    return "".join(parts)


def _calculation_method_label_from_details(details: dict | None) -> str:
    """Return a clear user-facing calculation method label for scheme results."""
    if not details:
        return "Аналитический расчёт"
    selected = str(details.get("calculation_method") or "").strip()
    if "Монте" in selected:
        return "Метод Монте-Карло: контрольная оценка с аналитической формулой по схеме"
    if "Приближ" in selected:
        return "Приближённый аналитический расчёт по структуре схемы"
    if "Аналит" in selected:
        return "Аналитический расчёт по структуре схемы"
    return selected or "Аналитический расчёт по структуре схемы"


def _apply_scheme_result_with_formula_details(self, result: CalculationResult):
    self.scheme_result = result
    self.last_results = dict(result.indicators)
    self.last_input_vals = {"Источник": "Графический редактор"}
    self.last_method_name = result.method_name
    self._refresh_threshold_options(result.method_name, self.last_results)
    formula_text = _scheme_formula_compact_text(result.formula)
    self.last_formula_dict = {"Итоговая формула": formula_text} if formula_text else {}
    formula_html = ""
    if result.formula:
        formula_html = escape(result.formula.text).replace("\n", "<br>")
    method_html = ""
    if result.details.get("recommended_method_id"):
        method_html = (
            f"<p><b>Рекомендуемый подход:</b> {escape(str(result.details.get('recommended_method_id')))} - "
            f"{escape(str(result.details.get('recommended_method_title')))}<br>"
            f"<b>Тип схемы:</b> {escape(str(result.details.get('scheme_structure_type', '')))}<br>"
            f"<b>Почему выбран:</b> {escape(str(result.details.get('method_selection_explanation', '')))}</p>"
        )
    self._set_details_results_html(
        "<h3>Результат расчёта по схеме</h3>"
        + method_html
        + "".join(
            f"<p><b>{key}</b>: {value:.6f}</p>" if isinstance(value, float) else f"<p><b>{key}</b>: {value}</p>"
            for key, value in result.indicators.items()
        )
        + (f"<p><b>Общая формула:</b><br>{formula_html}</p>" if formula_html else "")
    )
    if result.graph_points and result.graph_points.get("t") and result.graph_points.get("P"):
        x_values = np.array(result.graph_points["t"], dtype=float)
        y_values = np.array(result.graph_points["P"], dtype=float)
    else:
        probability = float(result.indicators.get("P", 0.0))
        x_values = np.linspace(0, 1000, 30)
        y_values = np.full_like(x_values, probability, dtype=float)
    self.last_graph_metric = "P"
    self.last_graph_x_values = x_values
    self.last_graph_y_values = y_values
    self.last_graph_note = "Кривая построена по общей формуле схемы, полученной генератором формул."
    self.last_graph_rows = self._make_graph_rows(x_values, y_values, "P")
    self.vis.update_view(
        x_values,
        y_values,
        self.last_formula_dict,
        method_name=result.method_name,
        parameters=dict(result.indicators),
        graph_note=self.last_graph_note,
        graph_metric="P",
        graph_title=self._graph_title("P"),
    )
    self.vis.set_formula_html(
        self._formula_details_qt_html(
            self.last_formula_package,
            self.last_formula_dict,
            formula=result.formula,
            graph_note=self.last_graph_note,
        )
    )
    self.vis.set_formula_html(
        self._formula_details_qt_html(
            self.last_formula_package,
            self.last_formula_dict,
            formula=result.formula,
            graph_note=self.last_graph_note,
        )
    )


def _professional_method_details(self, spec, config: dict) -> str:
    formulas = "".join(
        f"<div style='margin-left:16px;'><b>{escape(name)}:</b>{latex_to_html(latex_block(value))}</div>"
        for name, value in spec.formulas.items()
    )
    params = "".join(
        "<p style='margin-left:16px;'>"
        f"<b>{escape(doc.symbol)}</b> - {escape(doc.name)}. "
        f"{escape(doc.meaning)} "
        f"<i>Единицы:</i> {escape(doc.unit)}. "
        f"<i>Роль:</i> {escape(doc.role)}."
        "</p>"
        for arg, doc in spec.parameter_docs.items()
        if arg in config["args"]
    )
    if config["mode"] == "vector":
        params += (
            "<p style='margin-left:16px;'><b>λi</b> - интенсивность отказов i-го элемента в таблице элементов. "
            "<i>Единицы:</i> 1/ед. времени. <i>Роль:</i> формирует суммарную интенсивность отказов или готовность элемента.</p>"
            "<p style='margin-left:16px;'><b>Tвi</b> - среднее время восстановления i-го элемента в таблице элементов. "
            "<i>Единицы:</i> единица времени. <i>Роль:</i> используется для коэффициентов готовности восстанавливаемых систем.</p>"
        )
    limitations = (
        f"<p><b>Ограничения / примечания:</b> {escape(spec.limitations)}</p>"
        if spec.limitations
        else "<p><b>Ограничения / примечания:</b> специальных ограничений сверх корректности исходных параметров не задано.</p>"
    )
    return (
        "<div style='line-height:1.25;'>"
        f"<p><b>Название:</b> {escape(spec.display_name)}</p>"
        f"<p><b>Краткое описание:</b> {escape(spec.description)}</p>"
        f"<p><b>Где применяется:</b> {escape(spec.use_when)}</p>"
        f"<p><b>Что рассчитывает:</b> {escape(spec.calculates)}</p>"
        f"<p><b>Используемые сценарии:</b></p>{self._scenario_details_html(config)}"
        f"<p><b>Используемые параметры и расшифровка:</b></p>{params}"
        f"<p><b>Формулы:</b></p>{formulas}"
        f"<p><b>Пример применения:</b> {escape(spec.example)}</p>"
        f"{limitations}"
        "<p><b>Нормативная база:</b> утвержденный набор формул F1.1-F7.2, используемый в проекте.</p>"
        "</div>"
    )


ModuleUniversalCalc._format_method_details = _professional_method_details
ModuleUniversalCalc.apply_scheme_result = _apply_scheme_result_with_formula_details
ModuleUniversalCalc._human_formula = staticmethod(_readable_formula_text)


def _apply_scheme_result_compact(self, result: CalculationResult):
    """Display scheme results as compact summary + graph + formula below graph."""
    self.scheme_result = result
    self.last_results = dict(result.indicators)
    self.last_input_vals = {"Источник": "Графический редактор"}
    self.last_method_name = result.method_name
    self.last_calculation_method = _calculation_method_label_from_details(result.details)
    self.last_formula_package = result.formula_package or (result.formula.package if result.formula else None)
    formula_text = _scheme_formula_compact_text(result.formula)
    self.last_formula_dict = _formula_dict_from_package(self.last_formula_package) or ({"Итоговая формула": formula_text} if formula_text else {})
    self._refresh_threshold_options(result.method_name, self.last_results)
    self._update_numeric_results(result.method_name, self.last_results, self.last_calculation_method)
    self.scheme_structure_view.set_result(result)
    self.contribution_analysis.set_result(result)

    indicators_rows = "".join(
        f"<tr><td><b>{escape(str(key))}</b></td><td>{value:.6f}</td></tr>"
        if isinstance(value, float)
        else f"<tr><td><b>{escape(str(key))}</b></td><td>{escape(str(value))}</td></tr>"
        for key, value in result.indicators.items()
    )
    method_html = ""
    if result.details.get("recommended_method_id"):
        method_html = (
            "<div style='margin-top:6px; padding:8px; border:1px solid #d8e0ea; border-radius:8px; background:#f8fafc;'>"
            f"<b>Рекомендуемый подход:</b> {escape(str(result.details.get('recommended_method_title')))}<br>"
            f"<b>Тип схемы:</b> {escape(str(result.details.get('scheme_structure_type', '')))}"
            "</div>"
        )
    self._set_details_results_html(
        "<h3 style='margin:0 0 6px 0;'>Результаты расчета по схеме</h3>"
        f"<table border='1' cellspacing='0' cellpadding='5' style='border-collapse:collapse;'>{indicators_rows}</table>"
        f"{method_html}"
        "<p style='color:#536274; margin-top:8px;'>Формулы, структурное и вычислительное представления показаны во вкладке «Подробности».</p>"
    )

    if result.graph_points and result.graph_points.get("t") and result.graph_points.get("P"):
        x_values = np.array(result.graph_points["t"], dtype=float)
        y_values = np.array(result.graph_points["P"], dtype=float)
    else:
        probability = float(result.indicators.get("P", 0.0))
        x_values = np.linspace(0, 1000, 30)
        y_values = np.full_like(x_values, probability, dtype=float)
    self.last_graph_metric = "P"
    self.last_graph_x_values = x_values
    self.last_graph_y_values = y_values
    self.last_graph_note = "Кривая построена по общей формуле схемы, полученной генератором формул."
    self.last_graph_rows = self._make_graph_rows(x_values, y_values, "P")
    self.vis.update_view(
        x_values,
        y_values,
        self.last_formula_dict,
        method_name=result.method_name,
        parameters=dict(result.indicators),
        graph_note=self.last_graph_note,
        graph_metric="P",
        graph_title=self._graph_title("P"),
    )


ModuleUniversalCalc.apply_scheme_result = _apply_scheme_result_compact


def _compact_results_to_html(self, method_name: str, inputs: dict, results: dict):
    """Compact result summary; formulas are intentionally shown in details."""
    spec = get_method_spec(method_name)
    rows = "".join(
        f"<tr><td><b>{escape(str(name))}</b></td><td>{value:.6f}</td></tr>"
        if isinstance(value, (int, float))
        else f"<tr><td><b>{escape(str(name))}</b></td><td>{escape(str(value))}</td></tr>"
        for name, value in results.items()
    )
    inputs_html = "".join(f"<li><b>{escape(str(key))}</b>: {escape(str(value))}</li>" for key, value in inputs.items())
    limitation_block = ""
    if spec is not None and spec.limitations:
        limitation_block = f"<p><b>Ограничения:</b> {escape(spec.limitations)}</p>"
    return (
        "<h3 style='margin:0 0 6px 0;'>Результаты расчета</h3>"
        f"<p style='margin:4px 0; color:#536274;'><b>Методика:</b> {escape(method_name)}</p>"
        f"<p style='margin:4px 0;'><b>Исходные данные</b></p><ul style='margin-top:2px;'>{inputs_html}</ul>"
        f"<p style='margin:4px 0;'><b>Результаты</b></p>"
        f"<table border='1' cellspacing='0' cellpadding='5' style='border-collapse:collapse;'>{rows}</table>"
        "<p style='color:#536274; margin-top:8px;'>Формулы показаны во вкладке «Подробности» и используются для построения кривой.</p>"
        f"{limitation_block}"
    )


ModuleUniversalCalc._results_to_html = _compact_results_to_html


def _professional_method_details_v2(self, spec, config: dict) -> str:
    """Unified compact method passport: parameters first, formulas second."""
    params = "".join(
        "<p style='margin-left:14px; margin-top:4px; margin-bottom:4px;'>"
        f"<b>{escape(str(doc.symbol))}</b> - {escape(str(doc.name))}. "
        f"{escape(str(doc.meaning))} "
        f"<i>Единицы:</i> {escape(str(doc.unit))}. "
        f"<i>Роль:</i> {escape(str(doc.role))}."
        "</p>"
        for arg, doc in spec.parameter_docs.items()
        if arg in config["args"]
    )
    if config["mode"] == "vector":
        params += (
            "<p style='margin-left:14px; margin-top:4px; margin-bottom:4px;'>"
            "<b>λi</b> - интенсивность отказов i-го элемента в таблице элементов. "
            "<i>Единицы:</i> 1/ед. времени.</p>"
            "<p style='margin-left:14px; margin-top:4px; margin-bottom:4px;'>"
            "<b>Tвi</b> - среднее время восстановления i-го элемента в таблице элементов. "
            "<i>Единицы:</i> ед. времени.</p>"
        )
    method_formulas = self._method_formula_dict_to_qt_html(spec.formulas)
    result_formulas = self._method_formula_dict_to_qt_html(result_metric_latex_for(spec.result_fields))
    limitations = spec.limitations or "Специальных ограничений сверх корректности исходных параметров не задано."
    return (
        "<div style='line-height:1.25;'>"
        f"<p><b>Название:</b> {escape(spec.display_name)}</p>"
        f"<p><b>Краткое описание:</b> {escape(spec.description)}</p>"
        f"<p><b>Где применяется:</b> {escape(spec.use_when)}</p>"
        f"<p><b>Что рассчитывает:</b> {escape(spec.calculates)}</p>"
        f"<p><b>Используемые сценарии:</b></p>{self._scenario_details_html(config)}"
        f"<p><b>Расшифровка параметров:</b></p>{params or '<p>Параметры не заданы.</p>'}"
        f"<p><b>Формулы методики:</b></p>{method_formulas}"
        f"<p><b>Формулы выводимых показателей:</b></p>{result_formulas}"
        f"<p><b>Пример применения:</b> {escape(spec.example)}</p>"
        f"<p><b>Ограничения / примечания:</b> {escape(limitations)}</p>"
        "<p><b>Нормативная база:</b> утвержденный набор формул F1.1-F7.2, используемый в проекте.</p>"
        "</div>"
    )


ModuleUniversalCalc._format_method_details = _professional_method_details_v2
