from __future__ import annotations

from pathlib import Path

import pytest

from app.demo.demo_scenarios import SNE_DEMO_SCHEME_ID, comparison_lines_for_display, load_sne_emrtu_demo
from app.formulas.formula_rendering import safe_formula_html
from app.formulas.graph_formula_builder import build_formula_for_scheme
from app.demo.library_templates import built_in_templates
from app.core.scheme_adapter import calculate_scheme_reliability


def test_sne_demo_runs_import_formula_calculation_and_reference_compare() -> None:
    demo = load_sne_emrtu_demo(time_horizon=158, simulations=1000)

    assert SNE_DEMO_SCHEME_ID == "sne_document_demo"
    assert demo.scheme.metadata["imported_scheme_id"] == "sne_document_demo"
    assert demo.calculation.indicators["P"] == pytest.approx(0.998900209, rel=1e-8)
    assert demo.calculation.indicators["Kg"] == pytest.approx(0.999999801, rel=1e-8)
    assert demo.calculation.indicators["Kog"] == pytest.approx(
        demo.calculation.indicators["P"] * demo.calculation.indicators["Kg"],
        rel=1e-12,
    )
    assert demo.calculation.indicators["Tv"] == pytest.approx(5.0)
    assert demo.calculation.indicators["T0"] > 0.0
    assert all(item.status == "match" for item in demo.comparisons)
    assert "AUTO.COMPOSITION" not in demo.formula_preview
    assert "P" in demo.formula_preview
    assert "Energy_block" not in demo.formula_preview
    assert "Power_control" not in demo.formula_preview
    assert "Auxiliary" not in demo.formula_preview
    assert "B1" in demo.formula_preview
    assert "B2A" in demo.formula_preview
    assert demo.scheme.block_by_id("start").name == "Вход"
    assert demo.scheme.block_by_id("end").name == "Выход"
    reserve = demo.scheme.block_by_id("B1")
    assert reserve is not None
    assert reserve.params["block_role"] == "k_of_n"
    assert reserve.params["reserve_type"] == "sliding_loaded"
    assert reserve.params["k_required"] == 175
    assert reserve.params["n_total"] == 204
    assert "reserve_count" not in reserve.params
    aux = demo.scheme.block_by_id("B2")
    assert aux is not None
    assert aux.name == "Блок собственных нужд МКТН.563255.007"
    assert aux.is_subscheme is True
    assert aux.nested_scheme is not None
    assert len([block for block in aux.nested_scheme.blocks if block.kind not in {"in", "out", "junction"}]) == 4


def test_sne_demo_resource_is_available_and_packaged_for_exe() -> None:
    spec_source = Path("ReliabilityApp.spec").read_text(encoding="utf-8")
    from app.demo.demo_scenarios import SNE_DEMO_PATH

    assert SNE_DEMO_PATH.exists()
    assert '("examples/imported/sne_emrtu_project.json", "examples/imported")' in spec_source


def test_sne_demo_user_formula_is_russian_and_hides_manual_review_text() -> None:
    demo = load_sne_emrtu_demo(time_horizon=158, simulations=1000)
    lines = comparison_lines_for_display(demo.comparisons)
    formula = build_formula_for_scheme(demo.scheme)
    visible_text = "\n".join(
        [
            demo.formula_preview,
            formula.text,
            formula.latex,
            "\n".join(demo.warnings),
            "\n".join(formula.warnings),
            "\n".join(demo.calculation.details["formula_warnings"]),
        ]
    )
    recursive_names = {
        block.block_id: block.name
        for block in demo.scheme.iter_blocks_recursive()
        if block.kind not in {"in", "out", "junction"}
    }

    assert recursive_names["B2A"] == "Внутренний участок цепи собственных нужд 1"
    assert recursive_names["B2B"] == "Внутренний участок цепи собственных нужд 2"
    assert recursive_names["B2C"] == "Внутренний участок цепи собственных нужд 3"
    assert recursive_names["B2D"] == "Внутренний участок цепи собственных нужд 4"
    assert "B2A" in formula.text
    assert any("Внутренний участок цепи собственных нужд 1" in text for text in formula.symbols.values())
    for forbidden in ("Auxiliary", "internal chain", "manual", "needs_review", "requires manual", "требуется ручная проверка", "ручн"):
        assert forbidden.lower() not in visible_text.lower()
    assert any("совпадает" in line for line in lines)


def test_sne_demo_message_uses_neutral_notes_title() -> None:
    source = (Path("app") / "gui" / "gui_visual_editor.py").read_text(encoding="utf-8")
    start = source.index("def run_sne_demo_scenario")
    end = source.index("def run_demo_scenario", start)
    demo_ui_source = source[start:end]

    assert "Примечания к демо" not in demo_ui_source
    assert "Требует ручной проверки" not in demo_ui_source
    assert "demo.warnings" not in demo_ui_source


def test_sne_demo_graph_uses_reference_probability_table() -> None:
    demo = load_sne_emrtu_demo(time_horizon=158, simulations=1000)
    assert demo.calculation.graph_points is not None
    times = demo.calculation.graph_points["t"]
    probabilities = demo.calculation.graph_points["P"]
    by_time = {float(t): p for t, p in zip(times, probabilities)}

    assert len(set(round(value, 12) for value in probabilities)) > 1
    assert by_time[125.0] == pytest.approx(0.999994298, rel=1e-8)
    assert by_time[158.0] == pytest.approx(0.998900209, rel=1e-8)
    assert all(0.0 <= value <= 1.0 for value in probabilities)


def test_sne_demo_composition_rules_are_not_rendered_as_latex_image() -> None:
    demo = load_sne_emrtu_demo(time_horizon=158, simulations=1000)
    package = demo.calculation.formula_package
    assert package is not None
    rules = next(item for item in package.intermediate_formulas if item.label == "Правила композиции")
    main = package.formulas[0]

    rules_html = safe_formula_html(rules.instantiated_formula)
    main_html = safe_formula_html(main.instantiated_latex)

    assert "formula-readable-text" in rules_html
    assert "<img " not in rules_html
    assert "<img " in main_html


def test_sne_document_demo_matches_reference_for_125_hours() -> None:
    demo = load_sne_emrtu_demo(time_horizon=125, simulations=1000)

    assert demo.calculation.indicators["P"] == pytest.approx(0.999994298, rel=1e-8)
    assert demo.calculation.indicators["Kg"] == pytest.approx(0.999999801, rel=1e-8)
    assert demo.calculation.indicators["T0"] > 0.0
    assert demo.calculation.indicators["Tv"] == pytest.approx(5.0)
    assert {item.metric: item.status for item in demo.comparisons}["P_125"] == "match"


def test_built_in_demo_templates_are_simple_russian_and_calculable() -> None:
    templates = built_in_templates()
    assert [template.name for template in templates] == [
        "Последовательная схема",
        "Параллельная схема",
        "Смешанная схема",
        "Схема с резервированием",
    ]

    forbidden_labels = {"Start", "End", "Demo", "Example", "Test", "Block", "Input", "Output", "Auto", "Result", "Simulation"}
    for template in templates:
        assert len(template.blocks) <= 8
        visible_text = " ".join([template.name, *(block.name for block in template.blocks)])
        for label in forbidden_labels:
            assert label not in visible_text

        formula = build_formula_for_scheme(template)
        result = calculate_scheme_reliability(template, time_horizon=1000, simulations=1000)
        assert formula.text
        assert 0.0 <= float(result.indicators["P"]) <= 1.0
        assert result.graph_points and result.graph_points["t"] and result.graph_points["P"]
