from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel
from app.core.validators import validate_scheme


def test_validate_scheme_requires_start_and_end():
    scheme = SchemeModel(
        name="Invalid",
        blocks=[BlockModel("b1", "A", "right", 0, 0, {"lambda": 0.001})],
        connections=[],
    )
    result = validate_scheme(scheme)
    assert not result.ok
    assert any("Вход" in error or "Выход" in error for error in result.errors)


def test_validate_scheme_accepts_simple_valid_structure():
    scheme = SchemeModel(
        name="Valid",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"lambda": 0.001}),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )
    result = validate_scheme(scheme)
    assert result.ok


def test_validate_scheme_reports_nested_subscheme_errors():
    nested = SchemeModel(
        name="BrokenNested",
        blocks=[BlockModel("b", "NestedBlock", "right", 0, 0, {"lambda": 0.001})],
        connections=[],
    )
    scheme = SchemeModel(
        name="Parent",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "Sub", "right", 10, 0, {}, is_subscheme=True, nested_scheme=nested),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "sub", "left"),
            ConnectionModel("c2", "sub", "right", "end", "in"),
        ],
    )
    result = validate_scheme(scheme)
    assert not result.ok
    assert any("Parent / Sub" in error for error in result.errors)


def test_validate_scheme_warns_about_unused_blocks():
    scheme = SchemeModel(
        name="Unused",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"lambda": 0.001}),
            BlockModel("unused", "UnusedBlock", "right", 10, 50, {"lambda": 0.002}),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )
    result = validate_scheme(scheme)
    assert result.ok
    assert any("UnusedBlock" in warning and "не будет включен" in warning for warning in result.warnings)


def test_validate_scheme_rejects_cycles():
    scheme = SchemeModel(
        name="Cycle",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"lambda": 0.001}),
            BlockModel("b2", "B", "right", 20, 0, {"lambda": 0.002}),
            BlockModel("end", "End", "out", 30, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "b2", "left"),
            ConnectionModel("c3", "b2", "right", "b1", "left"),
            ConnectionModel("c4", "b2", "right", "end", "in"),
        ],
    )
    result = validate_scheme(scheme)
    assert not result.ok
    assert any("цикл" in error.lower() for error in result.errors)
