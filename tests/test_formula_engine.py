from math import exp

from app.formulas.formula_engine import FormulaGenerationService, FormulaLibrary, FormulaSelector, FragmentAnalysis
from app.formulas.formula_package import generate_formula_package
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel


def _series_scheme(count: int = 3) -> SchemeModel:
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


def _parallel_scheme(width: int = 2) -> SchemeModel:
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


def _reserve_scheme() -> SchemeModel:
    return SchemeModel(
        "Reserve",
        [
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R", "right", 100, 0, {"lambda": 0.001, "reserve_count": 2}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        [
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def _sliding_reserve_scheme() -> SchemeModel:
    return SchemeModel(
        "Sliding",
        [
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(
                "r",
                "SlidingReserve",
                "right",
                100,
                0,
                {"lambda": 0.001, "reserve_type": "sliding", "k_required": 175, "n_total": 204},
            ),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        [
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )


def test_engine_classifies_series_selects_library_formula_and_substitutes_n():
    result = FormulaGenerationService().generate(_series_scheme(3), time_horizon=100)

    assert any(item.node_type == "series_chain" and item.parameters["N"] == 3 for item in result.analysis)
    assert any(item.definition and item.definition.formula_id == "STRUCT.SERIES.P" for item in result.selections)
    assert any(
        item.formula_id == "STRUCT.SERIES.P"
        and item.parameter_substitution["N"] == 3
        and "exp(-lambda_B1 * t)" in item.instantiated_formula
        for item in result.instantiated_formulas
    )
    assert abs(result.numeric_results["P"] - exp(-(0.001 + 0.002 + 0.003) * 100)) < 1e-12


def test_engine_classifies_parallel_and_uses_same_formula_for_numeric_result():
    result = FormulaGenerationService().generate(_parallel_scheme(2), time_horizon=100)
    selected_ids = {item.definition.formula_id for item in result.selections if item.definition}
    expected = 1 - (1 - exp(-0.001 * 100)) * (1 - exp(-0.002 * 100))

    assert "STRUCT.PARALLEL.P" in selected_ids
    assert any(item.node_type == "parallel_group" for item in result.analysis)
    assert abs(result.numeric_results["P"] - expected) < 1e-12


def test_engine_expands_reserve_m_and_n_total():
    result = FormulaGenerationService().generate(_reserve_scheme(), time_horizon=100)
    reserve = next(item for item in result.instantiated_formulas if item.formula_id == "STRUCT.RESERVE.P")

    assert reserve.parameter_substitution["m"] == 2
    assert reserve.parameter_substitution["n_total"] == 3
    assert "1 - (1 - exp(-lambda_R * t))^3" in reserve.instantiated_formula


def test_engine_marks_sliding_k_of_n_as_needs_review_not_simple_parallel():
    result = FormulaGenerationService().generate(_sliding_reserve_scheme(), time_horizon=158)

    selected = next(item for item in result.selections if item.fragment_id == "P.reserve.r")
    assert selected.definition is not None
    assert selected.definition.formula_id == "DOC.SLIDING_LOADED_RESERVE_K_OF_N.P"
    assert selected.status == "manual_required"
    assert any("ручная проверка" in warning for warning in result.warnings)


def test_selector_does_not_invent_formula_when_library_has_no_match():
    selector = FormulaSelector(FormulaLibrary({}))
    selection = selector.select(
        FragmentAnalysis(
            fragment_id="P.unknown",
            node_type="unknown_node",
            fragment_kind="unknown",
            metric="P",
            elements=(),
            parameters={},
            reason="test unsupported fragment",
        )
    )

    assert selection.definition is None
    assert selection.status == "manual_required"


def test_formula_package_exports_engine_selection_and_no_internal_auto_id():
    package = generate_formula_package(scheme=_series_scheme(2), time_horizon=100)

    assert "AUTO.COMPOSITION" not in package.plain_text
    assert any(item.formula_id == "STRUCT.SERIES.P" for item in package.intermediate_formulas)
    assert package.export_payload["metadata"]["formula_engine"] == "FormulaGenerationService"
    assert any(
        item["formula_id"] == "STRUCT.SERIES.P"
        for item in package.export_payload["intermediate_formulas"]
    )
