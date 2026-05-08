from pathlib import Path

import app.core.dependability_backend as backend
from app.formulas.formula_rendering import result_metric_latex_for
from app.formulas.formula_package import generate_formula_package
from app.core.rbd_models import BlockModel, ConnectionModel, FormulaPackage, SchemeModel


def _series_scheme() -> SchemeModel:
    return SchemeModel(
        name="Series",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "B1", "right", 100, 0, {"lambda": 0.001}),
            BlockModel("b2", "B2", "right", 200, 0, {"lambda": 0.002}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "b2", "left"),
            ConnectionModel("c3", "b2", "right", "end", "in"),
        ],
    )


def test_formula_package_routing_normative_structural_and_algorithmic():
    normative = generate_formula_package(method_code="F1.1", inputs={"t": 100}, numeric_results={"P": 0.7, "T0": 10})
    assert isinstance(normative, FormulaPackage)
    assert normative.formula_mode == "normative"
    assert normative.is_normative is True
    assert normative.method_code == "F1.1"

    structural = generate_formula_package(scheme=_series_scheme())
    assert structural.formula_mode == "structural_fallback"
    assert structural.is_normative is False
    assert structural.method_code is None
    assert "structural" in structural.source_label.lower()
    assert "not normative" in structural.plain_text.lower()

    algorithmic = generate_formula_package(formula_mode="algorithmic", algorithm_name="minimal_paths")
    assert algorithmic.formula_mode == "algorithmic"
    assert algorithmic.is_normative is False


def test_f22_package_preserves_correct_tv_kg_kog_for_cat1_to_3():
    for cat3 in (1, 2, 3):
        inputs = {"cat3_f22": cat3, "t": 100, "n": 2, "m": 1, "t_v": 6.0, "lam": 0.001, "lam_p": 0.0005, "lam_s": 0.0}
        result = backend.f22(cat3=cat3, t=inputs["t"], n=inputs["n"], m=inputs["m"], t_v=inputs["t_v"], lam=inputs["lam"], lam_p=inputs["lam_p"], lam_s=inputs["lam_s"])
        package = generate_formula_package(method_code="F2.2", inputs=inputs, numeric_results=result)
        combined = "\n".join(
            [package.plain_text]
            + [item.symbolic_template for item in package.intermediate_formulas]
            + [item.instantiated_formula for item in package.intermediate_formulas]
        )

        assert package.formula_mode == "normative"
        assert result["Tv"] == inputs["t_v"] / (inputs["m"] + 1)
        assert result["Kg"] == result["T0"] / (result["T0"] + result["Tv"])
        assert result["Kog"] == result["Kg"] * result["P"]
        assert "Tv = t_v / (m + 1)" in combined
        assert "Kg = T0 / (T0 + Tv)" in combined
        assert "Kog = Kg * P" in combined


def test_f63_package_exposes_p_limitation_without_full_t0_formula():
    result = backend.f63(t=100, r1=3, r2=2, r3=2, m=2, lam1=0.001, lam2=0.002, lam3=0.003, t_upr=1000)
    package = generate_formula_package(
        method_code="F6.3",
        inputs={"t": 100, "r1": 3, "r2": 2, "r3": 2, "m": 2, "lam1": 0.001, "lam2": 0.002, "lam3": 0.003, "t_upr": 1000},
        numeric_results={"P": result["P"]},
    )

    assert package.formula_mode == "normative"
    assert package.numeric_results == {"P": result["P"]}
    assert "T0" in package.limitations
    assert all(item.label != "T0" for item in package.result_formulas)
    assert any("T0" in warning for warning in package.warnings)


def test_ui_and_export_are_wired_to_formula_package():
    root = Path(__file__).resolve().parents[1]
    gui_source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")
    export_source = (root / 'app' / 'reports' / 'report_exporters.py').read_text(encoding="utf-8")

    assert "generate_formula_package" in gui_source
    assert "self.last_formula_package.html_text" in gui_source
    assert "formula_package.plain_text" in gui_source
    assert 'getattr(report, "formula_package", None)' in export_source


def test_shared_latex_renderer_is_used_in_gui_and_report_html():
    root = Path(__file__).resolve().parents[1]
    gui_source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")
    export_source = (root / 'app' / 'reports' / 'report_exporters.py').read_text(encoding="utf-8")
    rendering_source = (root / 'app' / 'formulas' / 'formula_rendering.py').read_text(encoding="utf-8")

    assert "render_latex_to_png_bytes" in rendering_source
    assert "latex_image_html" in rendering_source
    assert "formula_dict_to_html(formulas)" in gui_source
    assert '_method_details_renderer = QtFormulaHtmlRenderer(' in gui_source
    assert "self._method_details_renderer.reset()" in gui_source
    assert "self._set_method_details_html(self._format_method_details(spec, config))" in gui_source
    assert "self._method_formula_dict_to_qt_html(spec.formulas)" in gui_source
    assert "result_metric_latex_for(spec.result_fields)" in gui_source
    assert "formula_package.html_text" in export_source
    assert "formula_html" in export_source


def test_calculator_moves_method_formulas_to_details_tab():
    root = Path(__file__).resolve().parents[1]
    gui_source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")

    assert 'self.graph_formula_toggle = QToolButton()' in gui_source
    assert 'self.graph_formula_group = QFrame()' in gui_source
    assert 'self.details_scroll = QScrollArea()' in gui_source
    assert 'self.details_content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)' in gui_source
    assert 'self.details_content_layout.addWidget(self.graph_formula_toggle, 0, Qt.AlignmentFlag.AlignTop)' in gui_source
    assert 'graph_formula_layout.addWidget(self.vis.formula_view)' in gui_source
    assert 'self.details_content_layout.addWidget(self.graph_formula_group, 0, Qt.AlignmentFlag.AlignTop)' in gui_source
    assert 'self.details_content_layout.addWidget(self.out, 0, Qt.AlignmentFlag.AlignTop)' in gui_source
    assert 'numeric_layout.addWidget(self.graph_formula_toggle)' not in gui_source
    assert 'numeric_layout.addWidget(self.graph_formula_group)' not in gui_source
    assert 'numeric_layout.addSpacing(10)' not in gui_source
    assert 'self.result_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)' in gui_source
    assert 'self.results_table.setMinimumHeight(110)' in gui_source
    assert 'self.results_table.setMaximumHeight(360)' in gui_source
    assert 'self.results_table.setWordWrap(False)' in gui_source
    assert 'numeric_layout.addWidget(self.results_table, stretch=0)' in gui_source
    assert 'def _fit_results_table_height' in gui_source
    assert 'self.results_tabs.addTab(analysis_tab, "Анализ вкладов")' in gui_source
    assert 'self.scheme_structure_view = SchemeStructureWidget()' in gui_source
    assert 'self.graph_formula_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)' in gui_source
    assert 'self.graph_formula_group.setMaximumHeight(960)' in gui_source
    assert 'self.out.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)' in gui_source
    assert 'details_layout.addWidget(self.graph_formula_group, 1)' not in gui_source
    assert "Формула методики под графиком" not in gui_source


def test_normative_formula_labels_are_user_facing_and_russian():
    package = generate_formula_package(
        method_code="F2.1",
        inputs={"cat3_f2": 1, "t": 1000, "n": 2, "lam_list": [0.001, 0.001], "tv_list": [10.0, 10.0], "t_0_list": [1000.0, 1000.0]},
        numeric_results={"T0": 500.0, "Tv": 10.05, "Kg": 0.9802960494069208, "Kog": 0.1326686435022181, "P": 0.1353352832366127},
    )

    labels = [item.label for item in package.formulas + package.intermediate_formulas]
    assert "cat3=1" not in labels
    assert "Kog consistency" not in labels
    assert "Основная формула метода F2.1" in labels
    assert "Проверка Kог" in labels


def test_vector_methods_pass_tv_list_to_backend_kwargs():
    root = Path(__file__).resolve().parents[1]
    gui_source = (root / 'app' / 'gui' / 'gui_calculator.py').read_text(encoding="utf-8")

    assert 'kwargs["tv_list"] = tv_list' in gui_source


def test_result_metric_latex_is_compact_for_method_description_panels():
    formulas = result_metric_latex_for(["P", "T0", "Tv", "Kg", "Kog"])

    assert formulas["P"] == r"P(t)"
    assert formulas["T0"] == r"T_0"
    assert formulas["Tv"] == r"T_{\text{в}}"
    assert formulas["Kg"] == r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}"
    assert r"\text{вероятность" not in "".join(formulas.values())
