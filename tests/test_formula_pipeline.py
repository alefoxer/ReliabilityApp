import math

import app.core.dependability_backend as backend
from app.formulas.formula_pipeline import (
    FORMULA_MODE_ALGORITHMIC,
    FORMULA_MODE_NORMATIVE,
    FORMULA_MODE_STRUCTURAL,
    generate_formula_package,
)
from app.core.rbd_models import BlockModel, ConnectionModel, ReportData, SchemeModel
from app.reports.report_exporters import _report_model


def reserve_scheme() -> SchemeModel:
    return SchemeModel(
        name="Reserve",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R", "right", 100, 0, {"lambda": 0.001, "reserve_count": 1, "Tv": 5.0}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def series_scheme() -> SchemeModel:
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


def test_routing_to_normative_generator():
    results = backend.f11(t=100, lam_list=[0.001, 0.002])
    package = generate_formula_package(
        method_code="F1.1",
        inputs={"t": 100, "lam_list": [0.001, 0.002]},
        numeric_results=results,
    )
    assert package.formula_mode == FORMULA_MODE_NORMATIVE
    assert package.is_normative is True
    assert package.method_code == "F1.1"


def test_routing_to_structural_fallback():
    package = generate_formula_package(scheme=series_scheme(), time_horizon=100)
    assert package.formula_mode == FORMULA_MODE_STRUCTURAL
    assert package.is_normative is False
    assert "ненорматив" in package.limitations.lower()
    assert "fallback" in package.source_details.lower()


def test_routing_to_algorithmic_mode():
    package = generate_formula_package(
        formula_mode=FORMULA_MODE_ALGORITHMIC,
        algorithm_name="minimal_paths",
        inputs={"paths": 3},
        numeric_results={"P": 0.95},
    )
    assert package.formula_mode == FORMULA_MODE_ALGORITHMIC
    assert package.is_normative is False
    assert "algorithmic" in package.source_label.lower()


def test_formula_package_contains_required_fields():
    package = generate_formula_package(scheme=series_scheme(), time_horizon=100)
    assert package.title
    assert package.source_label
    assert isinstance(package.formulas, list)
    assert isinstance(package.parameter_lines, list)
    assert isinstance(package.export_payload, dict)
    assert package.plain_text
    assert package.html_text


def test_f22_cat123_package_preserves_normative_tv_kg_and_kog():
    params = {"cat3": 1, "t": 100, "n": 2, "m": 1, "t_v": 5, "lam": 0.001}
    result = backend.f22(**params)
    package = generate_formula_package(method_code="F2.2", inputs=params, numeric_results=result)
    assert package.formula_mode == FORMULA_MODE_NORMATIVE
    assert math.isclose(package.numeric_results["Tv"], params["t_v"] / (params["m"] + 1), rel_tol=1e-12)
    assert math.isclose(
        package.numeric_results["Kg"],
        package.numeric_results["T0"] / (package.numeric_results["T0"] + package.numeric_results["Tv"]),
        rel_tol=1e-12,
    )
    assert math.isclose(
        package.numeric_results["Kog"],
        package.numeric_results["Kg"] * package.numeric_results["P"],
        rel_tol=1e-12,
    )
    formulas = " ".join(item.symbolic_template for item in package.intermediate_formulas + package.result_formulas)
    assert "T_v = t_v / (m + 1)" in formulas
    assert "K_g = T_0 / (T_0 + T_v)" in formulas
    assert "K_og = K_g · P(t)" in formulas


def test_f63_package_exposes_limitation_without_fake_t0():
    result = backend.f63(t=100, r1=3, r2=2, r3=2, m=1, lam1=0.001, lam2=0.0015, lam3=0.002, t_upr=1000)
    package = generate_formula_package(
        method_code="F6.3",
        inputs={"t": 100, "r1": 3, "r2": 2, "r3": 2, "m": 1, "lam1": 0.001, "lam2": 0.0015, "lam3": 0.002, "t_upr": 1000},
        numeric_results={"P": result["P"]},
    )
    assert "T0" in package.limitations
    assert "T0" not in package.numeric_results


def test_export_uses_same_formula_package_instance():
    result = backend.f11(t=100, lam_list=[0.001, 0.002])
    package = generate_formula_package(
        method_code="F1.1",
        inputs={"t": 100, "lam_list": [0.001, 0.002]},
        numeric_results=result,
    )
    report = ReportData(
        title="Report",
        subtitle="Subtitle",
        created_at=__import__("datetime").datetime(2026, 4, 27, 12, 0),
        inputs={"t": 100},
        results=result,
        method_name="F1.1",
        methodology="Methodology",
        formula_package=package,
    )
    model = _report_model(report)
    assert package.plain_text in model["formula_text"]

