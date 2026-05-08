from __future__ import annotations

import pytest

from app.import_export.external_reliability_import import (
    compare_imported_scheme_with_expected,
    imported_project_from_dict,
    imported_project_to_scheme,
    load_imported_project,
)
from app.formulas.formula_library import FORMULA_LIBRARY, formula_for_fragment
from app.formulas.graph_formula_builder import build_formula_for_scheme, evaluate_formula_for_scheme
from app.formulas.intelligent_formula_generator import generate_intelligent_formula
from app.utils.paths import examples_path


EXAMPLE = examples_path("imported", "sne_emrtu_project.json")


def test_load_imported_project_json_and_convert_top_scheme() -> None:
    project = load_imported_project(EXAMPLE)

    scheme = imported_project_to_scheme(project, "sne_top", time_horizon=158)
    values = evaluate_formula_for_scheme(scheme, time_horizon=158)

    assert project.project_name
    assert scheme.metadata["imported_scheme_id"] == "sne_top"
    assert values["P"] == pytest.approx(0.998900209, rel=1e-8)
    assert values["Kg"] == pytest.approx(0.999999801, rel=1e-8)


def test_compare_imported_scheme_with_expected_for_two_time_values() -> None:
    project = load_imported_project(EXAMPLE)

    comparison_158 = compare_imported_scheme_with_expected(project, "sne_document_demo", time_horizon=158)
    comparison_125 = compare_imported_scheme_with_expected(project, "sne_document_demo", time_horizon=125)

    assert {item.metric: item.status for item in comparison_158}["P_158"] == "match"
    assert {item.metric: item.status for item in comparison_125}["P_125"] == "match"


def test_import_format_is_not_tied_to_document_name() -> None:
    project = imported_project_from_dict(
        {
            "schema_version": "1.0",
            "project_name": "Any external reliability project",
            "source": {"document": "any_name.docx"},
            "components": [
                {"id": "A", "name": "A", "parameters": {"probability_by_time": {"10": 0.9}}},
                {"id": "B", "name": "B", "parameters": {"probability_by_time": {"10": 0.8}}},
            ],
            "schemes": [
                {
                    "id": "main",
                    "name": "Main scheme",
                    "root": {"type": "series", "children": ["A", "B"]},
                }
            ],
            "expected_results": {"main": {"P_10": 0.72}},
        }
    )

    comparison = compare_imported_scheme_with_expected(project, "main", time_horizon=10)

    assert comparison[0].status == "match"
    assert comparison[0].actual == pytest.approx(0.72)


def test_repeated_series_chain_instantiates_n_154() -> None:
    project = load_imported_project(EXAMPLE)
    scheme = imported_project_to_scheme(project, "energy_block_chain_154", time_horizon=100)
    formula = build_formula_for_scheme(scheme)
    intelligent = generate_intelligent_formula(scheme, time_horizon=100, base_report=None)

    series_selections = [
        item
        for item in intelligent.fragment_selections
        if item.fragment_kind == "series" and item.metric == "P"
    ]

    assert len([block for block in scheme.blocks if block.kind not in {"in", "out", "junction"}]) == 154
    assert any(selection.parameters.get("N") == 154 for selection in series_selections)
    assert "Energy_block_identical_element_1" in formula.text
    assert any("Energy block identical element" in text for text in formula.symbols.values())


def test_k_of_n_reserve_is_marked_manual_review_not_simple_reserve() -> None:
    project = load_imported_project(EXAMPLE)
    scheme = imported_project_to_scheme(project, "sne_reserve_group_175_of_204", time_horizon=158)
    reserve = next(block for block in scheme.blocks if block.kind not in {"in", "out", "junction"})

    assert scheme.metadata["manual_review_required"]
    assert reserve.params["block_role"] == "k_of_n"
    assert reserve.params["reserve_type"] == "sliding_loaded"
    assert reserve.params["k_required"] == 175
    assert reserve.params["n_total"] == 204
    assert "reserve_count" not in reserve.params
    assert FORMULA_LIBRARY["DOC.SLIDING_LOADED_RESERVE_K_OF_N.P"].verification_status == "needs_review"
    assert formula_for_fragment("reserve_sliding_k_of_n", "P").manual_review_required is True
    assert formula_for_fragment("reserve", "P").verification_status == "project_method"


def test_document_demo_k_of_n_uses_table_values_not_simple_reserve_count() -> None:
    project = load_imported_project(EXAMPLE)
    scheme = imported_project_to_scheme(project, "sne_document_demo", time_horizon=158)
    values = evaluate_formula_for_scheme(scheme, time_horizon=158)
    formula = build_formula_for_scheme(scheme)
    reserve = scheme.block_by_id("B1")

    assert reserve is not None
    assert reserve.params["block_role"] == "k_of_n"
    assert reserve.params["k_required"] == 175
    assert reserve.params["n_total"] == 204
    assert reserve.params["P"] == pytest.approx(0.999988706)
    assert reserve.params["probability_by_time"]["158.0"] == pytest.approx(0.999988706)
    assert reserve.params["probability_by_time"]["125.0"] == pytest.approx(0.999999941)
    assert "reserve_count" not in reserve.params
    assert values["P"] == pytest.approx(0.998900209, rel=1e-8)
    assert any("175 of 204" in warning for warning in formula.warnings)


def test_invalid_imported_json_reports_clear_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken_project.json"
    broken.write_text('{"schema_version": "1.0", "schemes": [}', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON imported project"):
        load_imported_project(broken)


def test_yaml_import_matches_json_pipeline(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    yaml_file = tmp_path / "generic_project.yaml"
    yaml_file.write_text(
        """
schema_version: "1.0"
project_name: YAML reliability import
components:
  - id: A
    name: A
    parameters:
      probability_by_time:
        "10": 0.95
  - id: B
    name: B
    parameters:
      probability_by_time:
        "10": 0.9
schemes:
  - id: main
    name: Main YAML scheme
    root:
      type: series
      children: [A, B]
expected_results:
  main:
    P_10: 0.855
""",
        encoding="utf-8",
    )

    project = load_imported_project(yaml_file)
    comparison = compare_imported_scheme_with_expected(project, "main", time_horizon=10)

    assert comparison[0].status == "match"
    assert comparison[0].actual == pytest.approx(0.855)
