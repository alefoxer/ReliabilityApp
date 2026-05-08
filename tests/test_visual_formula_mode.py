from pathlib import Path
import ast


def test_visual_formula_dialog_uses_selected_mode():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")
    show_dialog = source[source.index("    def show_formula_dialog"):source.index("    def run_self_check")]

    assert 'expanded = not hasattr(self, "formula_mode") or self.formula_mode.currentIndex() == 1' in show_dialog
    assert "self._formula_html(formula, expanded=expanded)" in show_dialog
    assert "self._formula_plain_text(formula, expanded=expanded)" in show_dialog
    assert 'if expanded:' in show_dialog
    assert 'content.append(self._method_selection_html(scheme))' in show_dialog


def test_expanded_formula_view_uses_package_latex_sections():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "_formula_package_sections_html" in source
    assert "_formula_package_sections_plain" in source
    assert "_latex_to_image_html" in source
    assert "_render_latex_to_png_bytes" in source
    assert "Основные формулы" in source
    assert "Промежуточные формулы" in source
    assert "Формулы результатов" in source


def test_formula_renderer_user_labels_are_russian():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'formulas' / 'formula_package.py').read_text(encoding="utf-8")

    assert "_formula_mode_label" in source
    assert "Предупреждения" in source
    assert "Формулы результатов" in source
    assert "Warnings:" not in source
    assert "Formulas are not available" not in source


def test_summary_panel_shows_only_compact_latex_formula():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")
    refresh_summary = source[source.index("    def refresh_summary"):source.index("    def _obsolete_show_formula_dialog_plain_text")]

    assert "self._reset_formula_resources()" in refresh_summary
    assert "self.summary.set_formula(self._summary_formula_latex(formula))" in refresh_summary
    assert "Схема:" not in refresh_summary
    assert "Проверка:" not in refresh_summary
    assert "Последний расчет:" not in refresh_summary


def test_summary_panel_supports_multiline_latex_wrapping():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _split_latex_for_summary" in source
    assert 'cls._top_level_split(rhs, r" \\cdot ")' in source
    assert "def _display_formula_lines_for_ui" in source
    assert "summary_lines.extend(self._display_formula_lines_for_ui(line, max_line_length=72))" in source
    assert "summary_lines," in source
    assert "compact=True" in source
    assert 'align="left"' in source
    assert "font_size=FORMULA_FONT_SIZE" in source
    assert "prefer_svg=False" in source
    assert "separate_lines=True" in source
    assert "def _latex_lines_html" in source
    assert "def _split_complement_rhs" in source
    assert "def _top_level_parenthesized_factors" in source


def test_summary_formula_html_uses_left_aligned_full_width_container():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "width:100%; text-align:left;" in source
    assert "def _latex_block_html(" in source
    assert "font_size: int | None = None" in source
    assert "prefer_svg: bool = True" in source


def test_expanded_formula_view_splits_large_latex_without_forced_shrink():
    root = Path(__file__).resolve().parents[1]
    gui_source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")
    rendering_source = (root / 'app' / 'formulas' / 'formula_rendering.py').read_text(encoding="utf-8")
    qt_rendering_source = (root / 'app' / 'formulas' / 'qt_formula_renderer.py').read_text(encoding="utf-8")

    assert "display_lines = split_latex_formula_for_display(str(latex), max_line_length=90)" in gui_source
    assert "self._latex_lines_html(display_lines, font_size=FORMULA_FONT_SIZE, prefer_svg=False, separate_lines=True, max_display_width=660)" in gui_source
    assert "font_size=24" not in gui_source
    assert "font_size=FORMULA_FONT_SIZE" in gui_source
    assert "max_display_width=660" in gui_source
    assert "max_display_width=None" in gui_source
    assert "FORMULA_UI_QUALITY_SCALE = 2" in gui_source
    assert "quality_scale=FORMULA_UI_QUALITY_SCALE" in gui_source
    assert "font_size=font_size * self.quality_scale" in qt_rendering_source
    assert "image.width() / self.quality_scale" in qt_rendering_source
    assert "image.height() / self.quality_scale" in qt_rendering_source
    assert "display_width = max(1, int(image.width() / self.quality_scale))" in qt_rendering_source
    assert "display_height = max(1, int(image.height() / self.quality_scale))" in qt_rendering_source
    assert "scale = max_display_width / display_width" in qt_rendering_source
    assert "def _qt_formula_lines_html" in gui_source
    assert "common_scale = 1.0" in qt_rendering_source
    assert "widest = max(image.width() / self.quality_scale for _, image in rendered_images)" in qt_rendering_source
    assert "common_scale = max_display_width / widest" in qt_rendering_source
    assert "display_width = max(1, int(image.width() / self.quality_scale * common_scale))" in qt_rendering_source
    assert "display_height = max(1, int(image.height() / self.quality_scale * common_scale))" in qt_rendering_source
    assert "self.summary = WrappedFormulaWidget(renderer=self._formula_renderer)" in gui_source
    assert "QTextEdit.LineWrapMode.WidgetWidth" in gui_source
    assert "prefer_svg: bool = True" in gui_source
    assert "prefer_svg=prefer_svg" in gui_source
    assert "document.addResource(QTextDocument.ResourceType.ImageResource, url, image)" in qt_rendering_source
    assert 'resource_prefix="formula://latex"' in gui_source
    assert "readable-formula-block" not in gui_source
    assert "size_attrs = _image_size_attrs(mime_type, payload)" in rendering_source
    assert "formula-latex-lines" in rendering_source
    assert "separate_lines: bool = False" in rendering_source
    assert "overflow-x:auto" in rendering_source
    assert 'align: str = "left"' in qt_rendering_source
    assert 'align: str = "center"' not in qt_rendering_source
    assert "max-width:none; height:auto; vertical-align:middle;" in rendering_source
    assert "max-width:100%; height:auto; vertical-align:middle;" not in rendering_source


def test_expanded_formula_view_keeps_composition_rules_as_readable_text():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")
    qt_rendering_source = (root / 'app' / 'formulas' / 'qt_formula_renderer.py').read_text(encoding="utf-8")

    assert "is_renderable_latex_formula" in source
    assert "readable_formula_html" in source
    assert "not any(is_renderable_latex_formula(line) for line in rendered_lines)" in qt_rendering_source
    assert "formula_html = (" in source


def test_calculator_graph_formula_uses_qt_resources_not_data_uri_only():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")
    qt_rendering_source = (root / 'app' / 'formulas' / 'qt_formula_renderer.py').read_text(encoding="utf-8")

    assert "formula_dict_to_qt_html" in source
    assert 'resource_prefix="formula://calculator"' in source
    assert "document.addResource(QTextDocument.ResourceType.ImageResource, url, image)" in qt_rendering_source
    assert "formula_dict_to_html(formulas)" not in source[source.index("def _graph_formula_update_view_v2"):source.index("PlotAndFormulaWidget.update_view = _graph_formula_update_view_v2")]


def test_calculator_results_tabs_have_dedicated_styling_hooks():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")
    styles = (root / 'app' / 'gui' / 'ui_styles.py').read_text(encoding="utf-8")

    assert 'self.results_tabs.setObjectName("resultsTabs")' in source
    assert 'numeric_tab.setProperty("role", "resultsPage")' in source
    assert 'details_tab.setProperty("role", "resultsPage")' in source
    assert 'QTabWidget#resultsTabs::pane' in styles
    assert 'QTabWidget#resultsTabs QTabBar::tab:selected' in styles


def test_summary_wrap_keeps_multiplication_operator_on_continuation_line():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _display_product_formula_lines" in source
    assert "current_factor_count >= 3" in source
    assert "def _display_formula_weight" in source
    assert "def _top_level_latex_product_factors" in source
    assert "def _is_continuation_group_line" in source


def test_summary_display_formula_wraps_mixed_scheme_by_top_level_terms():
    from app.gui.gui_visual_editor import ModuleVisualRBD

    formula = (
        r"P_{\text{сист}}(t) = P_{\mathrm{a}} \cdot "
        r"(1 - (1 - P_{\mathrm{b}})(1 - P_{\mathrm{c}})) \cdot P_{\mathrm{d}}"
    )
    lines = ModuleVisualRBD._display_formula_lines_for_ui(formula, max_line_length=72)

    assert lines == [
        r"P_{\text{сист}}(t) = P_{\mathrm{a}}",
        r"\cdot (1 - (1 - P_{\mathrm{b}})(1 - P_{\mathrm{c}}))",
        r"\cdot P_{\mathrm{d}}",
    ]
    assert lines[1].startswith(r"\cdot (") and r"(1 - P_{\mathrm{c}})" in lines[1]
    assert lines[2] == r"\cdot P_{\mathrm{d}}"


def test_summary_display_formula_keeps_left_right_group_intact():
    from app.gui.gui_visual_editor import ModuleVisualRBD

    formula = (
        r"P_{\text{sys}}(t) = P_a \cdot "
        r"\left(1 - (1 - P_b)(1 - P_c)\right) \cdot P_d"
    )
    lines = ModuleVisualRBD._display_formula_lines_for_ui(formula, max_line_length=58)

    assert lines == [
        r"P_{\text{sys}}(t) = P_a",
        r"\cdot \left(1 - (1 - P_b)(1 - P_c)\right)",
        r"\cdot P_d",
    ]
    assert all("(1 - P_c)" in line or "P_c" not in line for line in lines)
    assert lines[2] == r"\cdot P_d"


def test_summary_display_formula_groups_nine_serial_factors_compactly():
    from app.gui.gui_visual_editor import ModuleVisualRBD

    formula = (
        r"P_{\text{sys}}(t) = P_{B1} \cdot P_{B2A} \cdot P_{B2B} \cdot "
        r"P_{B2C} \cdot P_{B2D} \cdot P_{B3} \cdot P_{B4} \cdot P_{B5} \cdot P_{B6}"
    )
    lines = ModuleVisualRBD._display_formula_lines_for_ui(formula, max_line_length=72)

    assert 3 <= len(lines) <= 4
    assert len(lines) < 9
    assert lines[0].count(r"\cdot") == 2
    assert all(not line.endswith(r"\cdot") for line in lines)
    assert all(line.startswith(r"\cdot") for line in lines[1:])
    assert all(line.count("P_") >= 2 for line in lines[:-1])


def test_formula_line_images_disable_widget_auto_wrapping():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'formulas' / 'qt_formula_renderer.py').read_text(encoding="utf-8")

    assert "white-space:nowrap" in source
    assert "formula-latex-lines" in source


def test_wrapped_formula_widget_measures_lines_against_width():
    from PyQt6.QtWidgets import QApplication

    from app.gui.gui_visual_editor import WrappedFormulaWidget
    from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer

    app = QApplication.instance() or QApplication([])
    widget = WrappedFormulaWidget(renderer=QtFormulaHtmlRenderer())
    formula = (
        r"P_{\text{sys}}(t) = P_{B1} \cdot P_{B2A} \cdot P_{B2B} \cdot "
        r"P_{B2C} \cdot P_{B2D} \cdot P_{B3} \cdot P_{B4} \cdot P_{B5} \cdot P_{B6}"
    )

    narrow = widget.build_display_lines(formula, max_width=220)
    wide = widget.build_display_lines(formula, max_width=500)

    assert app is not None
    assert len(narrow) > len(wide)
    assert 2 <= len(wide) <= 4
    assert all(line.startswith(r"\cdot") for line in narrow[1:])
    assert all(not line.endswith(r"\cdot") for line in narrow)
    assert all(widget._measure_formula_width(line) <= 220 for line in narrow)
    widget.deleteLater()


def test_wrapped_formula_widget_keeps_branch_and_parallel_inside_width():
    from PyQt6.QtWidgets import QApplication

    from app.gui.gui_visual_editor import WrappedFormulaWidget
    from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer

    app = QApplication.instance() or QApplication([])
    widget = WrappedFormulaWidget(renderer=QtFormulaHtmlRenderer())
    branch = r"P_{\text{sys}}(t) = P_a \cdot \left(1 - (1 - P_b)(1 - P_c)\right) \cdot P_d"
    parallel = r"P_{\text{sys}}(t) = 1 - (1 - P_{top})(1 - P_{bottom})"

    branch_lines = widget.build_display_lines(branch, max_width=320)
    parallel_lines = widget.build_display_lines(parallel, max_width=320)

    assert app is not None
    assert branch_lines == [
        r"P_{\text{sys}}(t) = P_a",
        r"\cdot \left(1 - (1 - P_b)(1 - P_c)\right)",
        r"\cdot P_d",
    ]
    assert all("(1 - P_c)" in line or "P_c" not in line for line in branch_lines)
    assert parallel_lines == [
        r"P_{\text{sys}}(t) = 1",
        r"- (1 - P_{top})",
        r"(1 - P_{bottom})",
    ]
    assert all(widget._measure_formula_width(line) <= 320 for line in branch_lines + parallel_lines)
    widget.deleteLater()


def test_wrapped_formula_widget_rewraps_on_resize():
    from PyQt6.QtWidgets import QApplication

    from app.gui.gui_visual_editor import WrappedFormulaWidget
    from app.formulas.qt_formula_renderer import QtFormulaHtmlRenderer

    app = QApplication.instance() or QApplication([])
    widget = WrappedFormulaWidget(renderer=QtFormulaHtmlRenderer())
    widget.resize(340, 100)
    widget.show()
    app.processEvents()
    widget.set_formula(r"P_{\text{sys}}(t) = P_a \cdot \left(1 - (1 - P_b)(1 - P_c)\right) \cdot P_d")
    app.processEvents()
    narrow = widget.display_lines

    widget.resize(520, 100)
    app.processEvents()
    wide = widget.display_lines

    assert len(narrow) > len(wide)
    assert all(widget._measure_formula_width(line) <= widget._available_formula_width() for line in wide)
    widget.deleteLater()


def test_wrapped_formula_line_labels_are_visual_only_not_cards():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _prepare_formula_line_label" in source
    assert "label.setProperty(\"role\", \"formulaLine\")" in source
    assert "border: none; background: transparent; border-radius: 0; padding: 0; margin: 0;" in source


def test_summary_formula_card_is_not_stretched_or_horizontally_scrollable():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "summary_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)" in source
    assert "left.addWidget(summary_group)" in source
    assert "left.addWidget(summary_group, stretch=1)" not in source
    assert "self.summary = WrappedFormulaWidget(renderer=self._formula_renderer)" in source
    assert "self.summary.set_formula(self._summary_formula_latex(formula))" in source
    assert "self._set_html_with_formula_resources(self.summary" not in source
    assert "self.left_scroll.setMaximumWidth(390)" in source
    assert "class WrappedFormulaWidget" in source


def test_scheme_labels_have_background_and_loaded_layout_gets_air():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "self.label_item.setOpacity(0.0)" in source
    assert "painter.drawRoundedRect(rect, 4, 4)" in source
    assert "self.start_block.port_tangent(self.start_port_id, 105.0)" in source
    assert "def _relax_loaded_layout_spacing" in source
    assert "min_row_gap = 220.0" in source
    assert "min_column_gap = 175.0" in source


def test_summary_wrap_keeps_complement_lines_in_single_formula_flow():
    module = ast.parse((Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8"))
    target = None
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == "_split_complement_rhs":
            target = ast.get_source_segment((Path(__file__).resolve().parents[1] / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8"), node)
            break

    assert target is not None
    assert 'first_line = f"{lhs} 1 - {first_factor}".strip() if lhs else f"1 - {first_factor}"' in target

