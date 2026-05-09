from math import exp, isclose

from app.formulas.graph_formula_builder import build_formula_for_scheme, build_formula_report, evaluate_formula_for_scheme
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel, formula_short_text


def series_scheme() -> SchemeModel:
    return SchemeModel(
        name="Series",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "B1", "right", 100, 0, {"lambda": 0.001, "Tv": 10.0, "t": 100}),
            BlockModel("b2", "B2", "right", 200, 0, {"lambda": 0.002, "Tv": 10.0, "t": 100}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "b2", "left"),
            ConnectionModel("c3", "b2", "right", "end", "in"),
        ],
    )


def parallel_scheme() -> SchemeModel:
    return SchemeModel(
        name="Parallel",
        blocks=[
            BlockModel("start", "Start", "in", 0, 100, {}),
            BlockModel("split", "Split", "junction", 100, 100, {}),
            BlockModel("b1", "B1", "right", 200, 50, {"lambda": 0.001, "Tv": 10.0, "t": 100}),
            BlockModel("b2", "B2", "right", 200, 150, {"lambda": 0.002, "Tv": 10.0, "t": 100}),
            BlockModel("join", "Join", "junction", 300, 100, {}),
            BlockModel("end", "End", "out", 400, 100, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "split", "left"),
            ConnectionModel("c2", "split", "right", "b1", "left"),
            ConnectionModel("c3", "split", "down", "b2", "left"),
            ConnectionModel("c4", "b1", "right", "join", "left"),
            ConnectionModel("c5", "b2", "right", "join", "left"),
            ConnectionModel("c6", "join", "right", "end", "in"),
        ],
    )


def series_then_parallel_scheme() -> SchemeModel:
    return SchemeModel(
        name="SeriesThenParallel",
        blocks=[
            BlockModel("start", "Start", "in", 0, 100, {}),
            BlockModel("b3", "B3", "right", 100, 100, {"lambda": 0.003}),
            BlockModel("split", "Split", "junction", 200, 100, {}),
            BlockModel("b2", "B2", "right", 300, 30, {"lambda": 0.002}),
            BlockModel("b5", "B5", "right", 300, 100, {"lambda": 0.005}),
            BlockModel("b6", "B6", "right", 300, 170, {"lambda": 0.006}),
            BlockModel("join", "Join", "junction", 420, 100, {}),
            BlockModel("end", "End", "out", 520, 100, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b3", "left"),
            ConnectionModel("c2", "b3", "right", "split", "left"),
            ConnectionModel("c3", "split", "right", "b2", "left"),
            ConnectionModel("c4", "split", "right", "b5", "left"),
            ConnectionModel("c5", "split", "right", "b6", "left"),
            ConnectionModel("c6", "b2", "right", "join", "left"),
            ConnectionModel("c7", "b5", "right", "join", "left"),
            ConnectionModel("c8", "b6", "right", "join", "left"),
            ConnectionModel("c9", "join", "right", "end", "in"),
        ],
    )


def parallel_of_subchains_scheme() -> SchemeModel:
    return SchemeModel(
        name="ParallelOfSubchains",
        blocks=[
            BlockModel("start", "Start", "in", 0, 100, {}),
            BlockModel("split", "Split", "junction", 100, 100, {}),
            BlockModel("b1", "B1", "right", 200, 50, {"lambda": 0.001}),
            BlockModel("b2", "B2", "right", 300, 50, {"lambda": 0.002}),
            BlockModel("b3", "B3", "right", 200, 150, {"lambda": 0.003}),
            BlockModel("b4", "B4", "right", 300, 150, {"lambda": 0.004}),
            BlockModel("join", "Join", "junction", 420, 100, {}),
            BlockModel("end", "End", "out", 520, 100, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "split", "left"),
            ConnectionModel("c2", "split", "right", "b1", "left"),
            ConnectionModel("c3", "b1", "right", "b2", "left"),
            ConnectionModel("c4", "b2", "right", "join", "left"),
            ConnectionModel("c5", "split", "right", "b3", "left"),
            ConnectionModel("c6", "b3", "right", "b4", "left"),
            ConnectionModel("c7", "b4", "right", "join", "left"),
            ConnectionModel("c8", "join", "right", "end", "in"),
        ],
    )


def single_block_scheme() -> SchemeModel:
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


def scheme_with_uuid_ids_and_formula_symbols() -> SchemeModel:
    first_id = "54666a95-6493-4a0d-a000-000000000001"
    second_id = "284fb4c3-b08b-4b95-a000-000000000002"
    return SchemeModel(
        name="UuidIds",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel(first_id, "Блок 1", "right", 100, 0, {"lambda": 0.001, "formula_symbol": "B1"}),
            BlockModel(second_id, "Блок 2", "right", 200, 0, {"lambda": 0.002, "formula_symbol": "B2"}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", first_id, "left"),
            ConnectionModel("c2", first_id, "right", second_id, "left"),
            ConnectionModel("c3", second_id, "right", "end", "in"),
        ],
    )


def empty_scheme() -> SchemeModel:
    return SchemeModel(
        name="Empty",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("end", "End", "out", 100, 0, {}),
        ],
        connections=[ConnectionModel("c1", "start", "out", "end", "in")],
    )


def scheme_with_unused_block() -> SchemeModel:
    scheme = series_scheme()
    scheme.blocks.append(BlockModel("unused", "B_UNUSED", "right", 100, 150, {"lambda": 0.01}))
    return scheme


def long_series_scheme(count: int = 25) -> SchemeModel:
    blocks = [BlockModel("start", "Start", "in", 0, 0, {})]
    connections = []
    previous = "start"
    for index in range(1, count + 1):
        block_id = f"b{index}"
        blocks.append(BlockModel(block_id, f"B{index}", "right", index * 80, 0, {"lambda": 0.0001 * index}))
        connections.append(ConnectionModel(f"c{index}", previous, "right", block_id, "left"))
        previous = block_id
    blocks.append(BlockModel("end", "End", "out", (count + 1) * 80, 0, {}))
    connections.append(ConnectionModel("c_end", previous, "right", "end", "in"))
    return SchemeModel("LongSeries", blocks, connections)


def wide_parallel_scheme(width: int = 12) -> SchemeModel:
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
        blocks.append(BlockModel(block_id, f"P{index}", "right", 200, index * 40, {"lambda": 0.0001 * index}))
        connections.append(ConnectionModel(f"c_split_{index}", "split", "right", block_id, "left"))
        connections.append(ConnectionModel(f"c_join_{index}", block_id, "right", "join", "left"))
    return SchemeModel("WideParallel", blocks, connections)


def large_combined_scheme(stages: int = 6, width: int = 4) -> SchemeModel:
    blocks = [BlockModel("start", "Start", "in", 0, 100, {})]
    connections = []
    previous = "start"
    connection_index = 1
    for stage in range(1, stages + 1):
        serial_id = f"s{stage}"
        split_id = f"split{stage}"
        join_id = f"join{stage}"
        blocks.extend(
            [
                BlockModel(serial_id, f"S{stage}", "right", stage * 300, 100, {"lambda": 0.0002 * stage}),
                BlockModel(split_id, f"Split{stage}", "junction", stage * 300 + 80, 100, {}),
                BlockModel(join_id, f"Join{stage}", "junction", stage * 300 + 220, 100, {}),
            ]
        )
        connections.append(ConnectionModel(f"c{connection_index}", previous, "right", serial_id, "left"))
        connection_index += 1
        connections.append(ConnectionModel(f"c{connection_index}", serial_id, "right", split_id, "left"))
        connection_index += 1
        for branch in range(1, width + 1):
            block_id = f"x{stage}_{branch}"
            blocks.append(
                BlockModel(block_id, f"X{stage}_{branch}", "right", stage * 300 + 150, branch * 45, {"lambda": 0.0001 * (stage + branch)})
            )
            connections.append(ConnectionModel(f"c{connection_index}", split_id, "right", block_id, "left"))
            connection_index += 1
            connections.append(ConnectionModel(f"c{connection_index}", block_id, "right", join_id, "left"))
            connection_index += 1
        previous = join_id
    blocks.append(BlockModel("end", "End", "out", (stages + 1) * 300, 100, {}))
    connections.append(ConnectionModel(f"c{connection_index}", previous, "right", "end", "in"))
    return SchemeModel("LargeCombined", blocks, connections)


def assert_formula_pipeline_is_consistent(scheme: SchemeModel) -> None:
    report = build_formula_report(scheme)
    formula = build_formula_for_scheme(scheme)
    ast_symbols = report.formula_ast_reliability.collect_symbols() | report.formula_ast_availability.collect_symbols()
    assert set(report.symbols) == ast_symbols
    assert set(formula.symbols) == ast_symbols
    combined_formula = "\n".join([formula.text, formula.computational, formula.structural])
    explanation = "\n".join(formula.steps)
    for symbol in ast_symbols:
        assert symbol in combined_formula
        assert symbol in explanation
    for symbol in set(formula.symbols) - ast_symbols:
        raise AssertionError(f"Symbol {symbol} is in descriptions but not in AST")


def test_formula_builder_for_series_scheme():
    assert_formula_pipeline_is_consistent(series_scheme())
    formula = build_formula_for_scheme(series_scheme())
    assert formula.is_exact
    assert "Pсист(t) = B1 · B2" in formula.text
    assert "B1 * B2" in formula.computational


def test_formula_builder_for_parallel_scheme():
    assert_formula_pipeline_is_consistent(parallel_scheme())
    formula = build_formula_for_scheme(parallel_scheme())
    assert formula.is_exact
    assert "Pсист(t) = 1 - (1 - B1)(1 - B2)" in formula.text
    assert "(B1 - 1)" not in formula.text
    assert "+ 1" not in formula.text
    assert "Параллельно" in formula.structural


def test_formula_builder_for_series_before_parallel_keeps_one_inside_parallel_block():
    assert_formula_pipeline_is_consistent(series_then_parallel_scheme())
    formula = build_formula_for_scheme(series_then_parallel_scheme())
    assert formula.is_exact
    assert "Pсист(t) = B3 · (1 - (1 - B2)(1 - B5)(1 - B6))" in formula.text
    assert not formula.text.startswith("Pсист(t) = 1 - B3")
    assert "(B3 - 1)" not in formula.text
    assert "B3 * (1 - ((1 - B2) * (1 - B5) * (1 - B6)))" in formula.computational


def test_formula_builder_for_parallel_of_subchains():
    assert_formula_pipeline_is_consistent(parallel_of_subchains_scheme())
    formula = build_formula_for_scheme(parallel_of_subchains_scheme())
    assert formula.is_exact
    assert "1 - (1 - B1 · B2)(1 - B3 · B4)" in formula.text
    assert "B1 * B2" in formula.computational
    assert "B3 * B4" in formula.computational


def test_formula_builder_for_nested_scheme():
    nested = parallel_scheme()
    scheme = SchemeModel(
        name="Nested",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "Sub", "right", 100, 0, {}, is_subscheme=True, nested_scheme=nested),
            BlockModel("b3", "B3", "right", 200, 0, {"lambda": 0.003}),
            BlockModel("end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "sub", "left"),
            ConnectionModel("c2", "sub", "right", "b3", "left"),
            ConnectionModel("c3", "b3", "right", "end", "in"),
        ],
    )
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    assert "1 - (1 - B1)(1 - B2)" in formula.text
    assert "B3" in formula.text
    assert any("Вложенная схема" in step for step in formula.steps)


def test_formula_builder_for_two_level_nested_scheme():
    inner = SchemeModel(
        name="Inner",
        blocks=[
            BlockModel("inner_start", "Start", "in", 0, 0, {}),
            BlockModel("inner_b1", "I1", "right", 100, 0, {"lambda": 0.001}),
            BlockModel("inner_end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("ic1", "inner_start", "out", "inner_b1", "left"),
            ConnectionModel("ic2", "inner_b1", "right", "inner_end", "in"),
        ],
    )
    middle = SchemeModel(
        name="Middle",
        blocks=[
            BlockModel("middle_start", "Start", "in", 0, 0, {}),
            BlockModel("middle_sub", "MiddleSub", "right", 100, 0, {}, is_subscheme=True, nested_scheme=inner),
            BlockModel("middle_b2", "M2", "right", 200, 0, {"lambda": 0.002}),
            BlockModel("middle_end", "End", "out", 300, 0, {}),
        ],
        connections=[
            ConnectionModel("mc1", "middle_start", "out", "middle_sub", "left"),
            ConnectionModel("mc2", "middle_sub", "right", "middle_b2", "left"),
            ConnectionModel("mc3", "middle_b2", "right", "middle_end", "in"),
        ],
    )
    scheme = SchemeModel(
        name="Parent2",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "Sub", "right", 100, 0, {}, is_subscheme=True, nested_scheme=middle),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "sub", "left"),
            ConnectionModel("c2", "sub", "right", "end", "in"),
        ],
    )
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    assert "I1" in formula.text
    assert "M2" in formula.text
    values = evaluate_formula_for_scheme(scheme, time_horizon=100)
    assert isclose(values["P"], exp(-(0.001 + 0.002) * 100), rel_tol=1e-9)


def test_formula_builder_for_nested_reserve_scheme():
    nested = SchemeModel(
        name="NestedReserve",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("r", "R_nested", "right", 100, 0, {"lambda": 0.001, "reserve_count": 1}),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "r", "left"),
            ConnectionModel("c2", "r", "right", "end", "in"),
        ],
    )
    scheme = SchemeModel(
        name="ParentReserve",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "SubReserve", "right", 100, 0, {}, is_subscheme=True, nested_scheme=nested),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("pc1", "start", "out", "sub", "left"),
            ConnectionModel("pc2", "sub", "right", "end", "in"),
        ],
    )
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    assert "1 - (1 - R_nested)^2" in formula.text


def test_formula_builder_for_reserve_block():
    scheme = SchemeModel(
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
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    assert "Pсист(t) = 1 - (1 - R)^2" in formula.text
    assert "1 - (1 - R)**2" in formula.computational
    assert any("Резервирование" in step for step in formula.steps)


def test_formula_evaluator_matches_manual_series_value():
    values = evaluate_formula_for_scheme(series_scheme(), time_horizon=100)
    expected = exp(-(0.001 + 0.002) * 100)
    assert isclose(values["P"], expected, rel_tol=1e-9)


def test_formula_evaluator_matches_manual_parallel_value():
    values = evaluate_formula_for_scheme(parallel_scheme(), time_horizon=100)
    p_1 = exp(-0.001 * 100)
    p_2 = exp(-0.002 * 100)
    expected = 1 - (1 - p_1) * (1 - p_2)
    assert isclose(values["P"], expected, rel_tol=1e-9)


def test_formula_evaluator_matches_manual_series_then_parallel_value():
    values = evaluate_formula_for_scheme(series_then_parallel_scheme(), time_horizon=100)
    p3 = exp(-0.003 * 100)
    p2 = exp(-0.002 * 100)
    p5 = exp(-0.005 * 100)
    p6 = exp(-0.006 * 100)
    expected = p3 * (1 - (1 - p2) * (1 - p5) * (1 - p6))
    assert isclose(values["P"], expected, rel_tol=1e-9)


def test_formula_builder_for_single_block_scheme():
    assert_formula_pipeline_is_consistent(single_block_scheme())
    formula = build_formula_for_scheme(single_block_scheme())
    assert formula.is_exact
    assert "Pсист(t) = B1" in formula.text
    assert formula.structural.endswith("B1") or "B1" in formula.structural


def test_formula_builder_uses_formula_symbols_not_internal_uuid_ids():
    scheme = scheme_with_uuid_ids_and_formula_symbols()
    formula = build_formula_for_scheme(scheme)

    assert "B1" in formula.text
    assert "B2" in formula.text
    assert "54666a95" not in formula.text
    assert "284fb4c3" not in formula.text
    assert formula.symbols["B1"].endswith("«Блок 1»")
    assert formula.symbols["B2"].endswith("«Блок 2»")


def test_formula_builder_for_long_series_chain_is_not_hardcoded():
    count = 25
    scheme = long_series_scheme(count)
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    for index in range(1, count + 1):
        assert f"B{index}" in formula.text
    assert formula.text.count("·") == count - 1
    assert "1 - " not in formula.text.splitlines()[0]


def test_formula_builder_for_wide_parallel_group_is_not_width_limited():
    width = 12
    scheme = wide_parallel_scheme(width)
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    for index in range(1, width + 1):
        assert f"(1 - P{index})" in formula.text
    assert formula.text.splitlines()[0].startswith("Pсист(t) = 1 - ")
    assert "(P1 - 1)" not in formula.text


def test_formula_builder_for_large_combined_scheme_remains_structured():
    scheme = large_combined_scheme(stages=6, width=4)
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert formula.is_exact
    assert "S1" in formula.text and "S6" in formula.text
    assert "X1_1" in formula.text and "X6_4" in formula.text
    assert "Последовательно" in formula.structural
    assert "Параллельно" in formula.structural
    assert len(formula.steps) >= 6


def test_formula_evaluator_for_large_combined_scheme_returns_probability_range():
    values = evaluate_formula_for_scheme(large_combined_scheme(stages=8, width=5), time_horizon=100)
    assert 0.0 <= values["P"] <= 1.0
    assert 0.0 <= values["Kg"] <= 1.0


def test_empty_scheme_is_valid_identity_formula():
    assert_formula_pipeline_is_consistent(empty_scheme())
    formula = build_formula_for_scheme(empty_scheme())
    values = evaluate_formula_for_scheme(empty_scheme(), time_horizon=100)
    assert "Pсист(t) = 1" in formula.text
    assert "Kг_сист = 1" in formula.text
    assert formula.symbols == {}
    assert formula.used_blocks == []
    assert values == {"P": 1.0, "Kg": 1.0}


def test_unused_block_is_reported_but_not_leaked_into_formula_sections():
    scheme = scheme_with_unused_block()
    assert_formula_pipeline_is_consistent(scheme)
    formula = build_formula_for_scheme(scheme)
    assert "B_UNUSED" in formula.unused_blocks
    assert "B_UNUSED" not in formula.text
    assert "B_UNUSED" not in formula.computational
    assert "B_UNUSED" not in formula.structural
    assert "B_UNUSED" not in formula.symbols
    assert any("B_UNUSED" in warning for warning in formula.warnings)


def test_short_formula_text_contains_only_final_user_formulas():
    formula = build_formula_for_scheme(series_then_parallel_scheme())
    short = formula_short_text(formula)
    assert "P" in short
    assert "K" in short
    assert "AUTO.COMPOSITION" not in short
    assert "Структурное представление" not in short
    assert "Вычислительное представление" not in short
