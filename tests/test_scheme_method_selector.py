from math import isclose
import random

import pytest

from app.core.scheme_method_selector import (
    AUTO_COMPOSITION,
    AUTO_IDENTITY,
    AUTO_SINGLE,
    STATUS_CONDITIONAL,
    STATUS_OK,
    select_method_for_scheme,
)
from app.core.scheme_adapter import calculate_scheme_reliability
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel


def empty_scheme() -> SchemeModel:
    return SchemeModel(
        name="Empty",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("end", "End", "out", 100, 0, {}),
        ],
        connections=[ConnectionModel("c1", "start", "out", "end", "in")],
    )


def single_scheme() -> SchemeModel:
    return SchemeModel(
        name="Single",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "B1", "right", 100, 0, {"lambda": 0.001}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )


def series_scheme(count: int = 3) -> SchemeModel:
    blocks = [BlockModel("start", "Start", "in", 0, 0, {})]
    connections = []
    previous = "start"
    for index in range(1, count + 1):
        block_id = f"b{index}"
        blocks.append(BlockModel(block_id, f"B{index}", "right", 100 * index, 0, {"lambda": 0.001 * index}))
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
        blocks.append(BlockModel(block_id, f"P{index}", "right", 200, index * 50, {"lambda": 0.001 * index}))
        connections.append(ConnectionModel(f"c_split_{index}", "split", "right", block_id, "left"))
        connections.append(ConnectionModel(f"c_join_{index}", block_id, "right", "join", "left"))
    return SchemeModel("Parallel", blocks, connections)


def mixed_scheme() -> SchemeModel:
    scheme = parallel_scheme(2)
    scheme.blocks.insert(1, BlockModel("s1", "S1", "right", 50, 100, {"lambda": 0.001}))
    scheme.connections = [
        ConnectionModel("c1", "start", "out", "s1", "left"),
        ConnectionModel("c2", "s1", "right", "split", "left"),
        *[connection for connection in scheme.connections if connection.connection_id not in {"c_start"}],
    ]
    return scheme


def reserve_scheme() -> SchemeModel:
    return SchemeModel(
        name="Reserve",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R", "right", 100, 0, {"lambda": 0.001, "reserve_count": 1}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def scheme_with_unused_block() -> SchemeModel:
    scheme = series_scheme(2)
    scheme.blocks.append(BlockModel("unused", "B_UNUSED", "right", 100, 150, {"lambda": 0.01}))
    return scheme


def test_empty_scheme_uses_identity_method():
    selection = select_method_for_scheme(empty_scheme())
    assert selection.recommended_method.method_id == AUTO_IDENTITY
    assert selection.analysis.block_count == 0
    assert selection.formula_report.symbolic_formula_reliability == "1"


def test_single_block_is_classified_as_single_element():
    selection = select_method_for_scheme(single_scheme())
    assert selection.recommended_method.method_id == AUTO_SINGLE
    assert selection.analysis.block_count == 1
    assert selection.analysis.structure_type == "один расчетный элемент"


def test_series_scheme_recommends_f11():
    selection = select_method_for_scheme(series_scheme(5))
    assert selection.recommended_method.method_id == "F1.1"
    assert selection.recommended_method.status == STATUS_OK
    assert selection.analysis.has_series
    assert not selection.analysis.has_parallel


def test_parallel_scheme_prefers_composition_but_keeps_f12_as_candidate():
    selection = select_method_for_scheme(parallel_scheme(4))
    assert selection.recommended_method.method_id == AUTO_COMPOSITION
    assert selection.analysis.has_parallel
    f12 = next(item for item in selection.methods if item.method_id == "F1.2")
    assert f12.status == STATUS_CONDITIONAL


def test_mixed_scheme_recommends_composition():
    selection = select_method_for_scheme(mixed_scheme())
    assert selection.recommended_method.method_id == AUTO_COMPOSITION
    assert selection.analysis.has_series
    assert selection.analysis.has_parallel
    assert selection.formula_report.used_blocks == ["S1", "P1", "P2"]


def test_reserve_scheme_recommends_reserve_method():
    selection = select_method_for_scheme(reserve_scheme())
    assert selection.recommended_method.method_id == "F1.2"
    assert selection.analysis.has_reserve
    assert "резерв" in selection.recommended_method.reason.lower()


def test_unused_block_is_warning_not_method_input():
    selection = select_method_for_scheme(scheme_with_unused_block())
    assert "B_UNUSED" in selection.analysis.unused_blocks
    assert "B_UNUSED" not in selection.formula_report.used_blocks
    assert "B_UNUSED" not in selection.formula_report.symbolic_formula_reliability


def test_selection_result_is_consistent_with_formula_report_symbols():
    selection = select_method_for_scheme(mixed_scheme())
    symbols = selection.formula_report.formula_ast_reliability.collect_symbols()
    assert symbols == set(selection.formula_report.symbols)
    for symbol in symbols:
        assert symbol in selection.formula_report.symbolic_formula_reliability
    text = selection.to_plain_text()
    assert selection.recommended_method.title in text
    assert selection.analysis.structure_type in text
    assert "AUTO.COMPOSITION" not in text


def test_scheme_calculation_public_method_name_does_not_expose_auto_id():
    result = calculate_scheme_reliability(mixed_scheme(), time_horizon=100, simulations=100)
    assert "AUTO.COMPOSITION" not in result.method_name
    assert result.formula is not None
    assert "P" in result.formula.text


def test_scheme_calculation_uses_structural_t0_for_parallel_scheme():
    result = calculate_scheme_reliability(parallel_scheme(2), time_horizon=100, simulations=100)
    expected_t0 = 1 / 0.001 + 1 / 0.002 - 1 / (0.001 + 0.002)
    assert isclose(result.indicators["T0"], expected_t0, rel_tol=1e-9)
    assert result.details["indicator_sources"]["T0"] == "structural_formula_integral"


def test_scheme_calculation_rejects_non_positive_simulation_count():
    with pytest.raises(ValueError, match="simulations must be a positive integer"):
        calculate_scheme_reliability(single_scheme(), time_horizon=100, simulations=0)


def test_scheme_monte_carlo_mode_changes_probability_source_and_curve():
    random.seed(12345)
    analytic = calculate_scheme_reliability(parallel_scheme(2), time_horizon=100, simulations=2000)
    random.seed(12345)
    monte = calculate_scheme_reliability(
        parallel_scheme(2),
        time_horizon=100,
        simulations=2000,
        method="Метод Монте-Карло",
    )

    assert monte.details["indicator_sources"]["P"] == "monte_carlo"
    assert monte.indicators["P"] == monte.details["monte_carlo_probability"]
    assert analytic.indicators["P"] != monte.indicators["P"]
    assert monte.graph_points is not None
    assert monte.graph_points["P"][-1] != analytic.graph_points["P"][-1]


def test_scheme_monte_carlo_for_parallel_scheme_is_not_lost_on_junctions():
    random.seed(7)
    result = calculate_scheme_reliability(
        parallel_scheme(3),
        time_horizon=100,
        simulations=3000,
        method="Метод Монте-Карло",
    )

    assert 0.0 < result.details["monte_carlo_probability"] <= 1.0
