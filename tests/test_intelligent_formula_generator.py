from math import exp

from app.formulas.formula_library import FORMULA_LIBRARY
from app.formulas.graph_formula_builder import build_formula_for_scheme
from app.formulas.intelligent_formula_generator import generate_intelligent_formula
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel


def series_scheme(count: int = 3) -> SchemeModel:
    blocks = [BlockModel("start", "Start", "in", 0, 0, {})]
    connections = []
    previous = "start"
    for index in range(1, count + 1):
        block_id = f"b{index}"
        blocks.append(BlockModel(block_id, f"B{index}", "right", index * 100, 0, {"lambda": 0.001 * index}))
        connections.append(ConnectionModel(f"c{index}", previous, "right", block_id, "left"))
        previous = block_id
    blocks.append(BlockModel("end", "End", "out", 100 * (count + 1), 0, {}))
    connections.append(ConnectionModel("c_end", previous, "right", "end", "in"))
    return SchemeModel("Series", blocks, connections)


def parallel_scheme(width: int = 3) -> SchemeModel:
    blocks = [
        BlockModel("start", "Start", "in", 0, 100, {}),
        BlockModel("split", "Split", "junction", 100, 100, {}),
        BlockModel("join", "Join", "junction", 300, 100, {}),
        BlockModel("end", "End", "out", 400, 100, {}),
    ]
    connections = [
        ConnectionModel("c_start", "start", "out", "split", "left"),
        ConnectionModel("c_end", "join", "right", "end", "in"),
    ]
    for index in range(1, width + 1):
        block_id = f"p{index}"
        blocks.append(BlockModel(block_id, f"P{index}", "right", 200, index * 60, {"lambda": 0.001 * index}))
        connections.append(ConnectionModel(f"c_split_{index}", "split", "right", block_id, "left"))
        connections.append(ConnectionModel(f"c_join_{index}", block_id, "right", "join", "left"))
    return SchemeModel("Parallel", blocks, connections)


def nested_scheme() -> SchemeModel:
    inner = parallel_scheme(2)
    return SchemeModel(
        name="Nested",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "Sub", "right", 100, 0, {}, is_subscheme=True, nested_scheme=inner),
            BlockModel("b3", "B3", "right", 200, 0, {"lambda": 0.003}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "sub", "left"),
            ConnectionModel("c2", "sub", "right", "b3", "left"),
            ConnectionModel("c3", "b3", "right", "end", "in"),
        ],
    )


def reserve_scheme() -> SchemeModel:
    return SchemeModel(
        name="Reserve",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R", "right", 100, 0, {"lambda": 0.001, "reserve_count": 2}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def test_series_fragment_selects_series_formula_and_substitutes_n():
    result = generate_intelligent_formula(series_scheme(4), time_horizon=100)
    selected_ids = {item.selected_formula.formula_id for item in result.fragment_selections if item.selected_formula}
    assert "STRUCT.SERIES.P" in selected_ids
    series = next(item for item in result.fragment_selections if item.selected_formula and item.selected_formula.formula_id == "STRUCT.SERIES.P")
    assert series.parameters["N"] == 4
    assert "B1 · B2 · B3 · B4" in series.instantiated_formula


def test_parallel_fragment_selects_parallel_formula_and_numeric_value_matches_manual():
    result = generate_intelligent_formula(parallel_scheme(3), time_horizon=100)
    selected_ids = {item.selected_formula.formula_id for item in result.fragment_selections if item.selected_formula}
    assert "STRUCT.PARALLEL.P" in selected_ids
    expected = 1.0
    for index in range(1, 4):
        expected *= 1 - exp(-0.001 * index * 100)
    expected = 1 - expected
    assert abs(result.numeric_results["P"] - expected) < 1e-12


def test_reserve_fragment_selects_reserve_formula_and_expands_count():
    result = generate_intelligent_formula(reserve_scheme(), time_horizon=100)
    reserve = next(item for item in result.fragment_selections if item.selected_formula and item.selected_formula.formula_id == "STRUCT.RESERVE.P")
    assert reserve.parameters["m"] == 2
    assert reserve.parameters["всего элементов"] == 3
    assert "1 - (1 - R)^3" in reserve.instantiated_formula


def test_nested_scheme_uses_recursive_formula_selection():
    result = generate_intelligent_formula(nested_scheme(), time_horizon=100)
    selected_ids = {item.selected_formula.formula_id for item in result.fragment_selections if item.selected_formula}
    assert "STRUCT.SERIES.P" in selected_ids
    assert "STRUCT.PARALLEL.P" in selected_ids
    assert any("Подставленные параметры" in step for step in result.explanation_steps)


def test_ui_formula_info_contains_intelligent_selection_sections():
    formula = build_formula_for_scheme(series_scheme(2))
    assert "Выбранные формулы по фрагментам" in formula.structural
    assert any("выбрана формула" in step for step in formula.steps)
    assert any("λ_B1" in step for step in formula.steps)


def test_generator_exposes_t0_formula_when_lambdas_are_available():
    formula = build_formula_for_scheme(series_scheme(2))
    assert "T0 = 1 / (λ_B1 + λ_B2)" in formula.text
    assert "STRUCT.EQUIVALENT.T0" in formula.structural
    result = generate_intelligent_formula(series_scheme(2), time_horizon=100)
    assert "T0" in result.numeric_results
    assert result.numeric_results["T0"] > 0
    assert any("показателя T0" in step for step in result.explanation_steps)


def test_formula_library_contains_project_t0_definition():
    definition = FORMULA_LIBRARY["STRUCT.EQUIVALENT.T0"]
    assert definition.metric == "T0"
    assert "Σ" in definition.general_formula
    assert "lambda_i" in definition.parameters


def test_nested_scheme_contributes_inner_lambdas_to_t0_substitution():
    result = generate_intelligent_formula(nested_scheme(), time_horizon=100)
    assert "T0" in result.numeric_results
    assert abs(result.numeric_results["T0"] - (1.0 / (0.001 + 0.002 + 0.003))) < 1e-12
    assert any("λ_P1" in step and "λ_P2" in step and "λ_B3" in step for step in result.explanation_steps)
