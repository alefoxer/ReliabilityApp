from pathlib import Path
import re

from PyQt6.QtWidgets import QApplication

from app.gui.gui_calculator import ModuleUniversalCalc
from app.formulas.graph_formula_builder import build_formula_for_scheme
from app.demo.library_templates import built_in_templates
from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer


def test_graph_metric_priority_prefers_p_then_engineering_order():
    assert ModuleUniversalCalc._select_default_graph_metric(["Kg", "T0"]) == "Kg"
    assert ModuleUniversalCalc._select_default_graph_metric(["Tpr", "Tv"]) == "Tv"
    assert ModuleUniversalCalc._select_default_graph_metric(["P", "Kg", "T0"]) == "P"


def test_available_graph_metrics_are_limited_to_supported_engineering_set():
    metrics = ModuleUniversalCalc._available_graph_metrics(["P", "Kg", "Kog", "T0", "Tv", "Tpr", "lambda", "custom"])

    assert metrics == ["P", "Kg", "Kog", "T0", "Tv", "Tpr"]


def test_graph_rows_use_selected_metric_in_header():
    rows = ModuleUniversalCalc._make_graph_rows([0, 10], [0.9, 0.8], "Kg")

    assert rows[0] == ("t", "Kg")
    assert rows[1] == (0.0, 0.9)
    assert rows[2] == (10.0, 0.8)


def test_threshold_defaults_and_comparison_direction_follow_metric_semantics():
    assert ModuleUniversalCalc._threshold_default_for_metric("P") == "0.90"
    assert ModuleUniversalCalc._threshold_default_for_metric("T0") == "1000"
    assert ModuleUniversalCalc._threshold_passes("Kg", 0.95, 0.90) is True
    assert ModuleUniversalCalc._threshold_passes("T0", 800, 1000) is False
    assert ModuleUniversalCalc._threshold_passes("Tv", 8, 10) is True
    assert ModuleUniversalCalc._threshold_passes("Tpr", 30, 24) is False


def test_gui_source_contains_graph_metric_selector_and_metric_aware_rendering():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")

    assert 'graph_metric_row.addWidget(QLabel("Показатель графика:"))' in source
    assert "self.graph_metric_combo = QComboBox()" in source
    assert "def _build_graph_series" in source
    assert 'self._make_graph_rows(x_values, y_values, metric)' in source
    assert 'graph_metric=metric' in source
    assert 'graph_title=self._graph_title(metric)' in source


def test_gui_source_contains_collapsible_threshold_metric_panel():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")

    assert 'self.threshold_toggle = QToolButton()' in source
    assert 'self.threshold_group = QFrame()' in source
    assert 'self.threshold_metric_combo = QComboBox()' in source
    assert 'self.threshold_toggle.toggled.connect(self._set_threshold_panel_visible)' in source
    assert "def _refresh_threshold_options" in source
    assert "def _on_threshold_metric_changed" in source
    assert 'threshold_metric=threshold_metric' in source


def test_method_description_panel_is_content_height_not_expanding():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")

    assert "self.method_details.setMinimumHeight(72)" in source
    assert "self.method_details.setMaximumHeight(220)" in source
    assert "self.method_details.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)" in source
    assert "_fit_text_edit_to_document(self.method_details, min_height=72, max_height=220)" in source
    assert "_fit_parent_frame_to_child(self.method_details, max_height=244)" in source
    assert "self.method_details.setMinimumHeight(220)" not in source


def test_f21_normalization_removes_legacy_tv_list_argument():
    app = QApplication.instance() or QApplication([])
    calc = ModuleUniversalCalc()

    kwargs = calc._prepare_call_kwargs("F2.1: Восстанавливаемая система")
    normalized = calc._normalize_call_kwargs("F2.1: Восстанавливаемая система", kwargs.copy())

    assert app is not None
    assert "t_v_list" in normalized
    assert "tv_list" not in normalized
    calc.deleteLater()


def test_qt_formula_renderer_refits_large_formula_before_display_scaling():
    renderer = QtFormulaHtmlRenderer(resource_prefix="formula://test-width", quality_scale=2)

    html = renderer.formula_image_html(
        r"P(t)=e^{-t\sum_i \lambda_i}",
        font_size=18,
        max_display_width=240,
    )

    match = re.search(r"width='(\d+)' height='(\d+)'", html)
    assert match is not None
    assert int(match.group(1)) <= 240
    assert len(renderer._resources) == 1
    _, image = renderer._resources[0]
    assert image.width() / renderer.quality_scale <= 280


def test_qt_formula_renderer_keeps_wrapped_formula_lines_on_common_scale():
    renderer = QtFormulaHtmlRenderer(resource_prefix="formula://test-lines", quality_scale=2)
    lines = [
        r"P(t)=1-\prod_{i=1}^{n}(1-P_i(t))",
        r"\cdot \prod_{j=1}^{m}(1-Q_j(t))",
    ]

    html = renderer.formula_line_images_html(
        lines,
        font_size=18,
        align="center",
        margin="6px 0",
        line_margin="4px 0",
        max_display_width=240,
    )

    assert "formula://test-lines/1" in html
    assert "formula://test-lines/2" in html
    assert len(renderer._resources) == 2
    first_height = renderer._resources[0][1].height()
    second_height = renderer._resources[1][1].height()
    assert abs(first_height - second_height) <= 40


def test_qt_formula_renderer_keeps_fraction_readable_not_microscopic():
    renderer = QtFormulaHtmlRenderer(resource_prefix="formula://test-fraction", quality_scale=2)

    html = renderer.formula_value_html(r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}", max_display_width=660)

    assert "formula://test-fraction/1" in html
    assert r"\frac" not in html
    assert len(renderer._resources) == 1
    display_height = renderer._resources[0][1].height() / renderer.quality_scale
    assert 36 <= display_height <= 90


def test_structural_formula_fallback_latex_uses_text_wrapped_symbols():
    formula = build_formula_for_scheme(built_in_templates()[0])

    assert r"P_{\text{сист}}(t)" in formula.latex
    assert r"K_{\text{г,сист}}" in formula.latex
    assert r"P_{\mathrm{b1}}" in formula.latex
    assert "Блок 1" not in formula.latex
