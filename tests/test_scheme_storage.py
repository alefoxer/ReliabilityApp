from pathlib import Path

import pytest

from app.import_export.import_safety import MAX_NESTED_SCHEME_DEPTH, MAX_SCHEME_BLOCKS
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel
from app.import_export.scheme_storage import load_scheme, save_scheme, scheme_from_dict


def test_scheme_roundtrip(tmp_path: Path):
    path = tmp_path / "scheme.json"
    scheme = SchemeModel(
        name="Test",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("end", "End", "out", 100, 0, {}),
        ],
        connections=[ConnectionModel("c1", "start", "out", "end", "in")],
    )
    save_scheme(path, scheme)
    restored = load_scheme(path)
    assert restored.name == scheme.name
    assert len(restored.blocks) == 2
    assert len(restored.connections) == 1


def test_nested_scheme_roundtrip(tmp_path: Path):
    path = tmp_path / "nested_scheme.json"
    nested = SchemeModel(
        name="Nested",
        blocks=[
            BlockModel("nested_start", "Start", "in", 0, 0, {}),
            BlockModel("nested_b1", "N1", "right", 100, 0, {"lambda": 0.001}),
            BlockModel("nested_end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("nc1", "nested_start", "out", "nested_b1", "left"),
            ConnectionModel("nc2", "nested_b1", "right", "nested_end", "in"),
        ],
    )
    scheme = SchemeModel(
        name="Parent",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("sub", "Sub", "right", 100, 0, {}, is_subscheme=True, nested_scheme=nested),
            BlockModel("end", "End", "out", 200, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "sub", "left"),
            ConnectionModel("c2", "sub", "right", "end", "in"),
        ],
    )
    save_scheme(path, scheme)
    restored = load_scheme(path)
    restored_sub = restored.block_by_id("sub")
    assert restored_sub is not None
    assert restored_sub.is_subscheme
    assert restored_sub.nested_scheme is not None
    assert restored_sub.nested_scheme.name == "Nested"
    assert restored_sub.nested_scheme.block_by_id("nested_b1").params["lambda"] == 0.001


def test_load_scheme_rejects_non_object_root(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="format"):
        load_scheme(path)


def test_scheme_from_dict_rejects_missing_required_block_field():
    with pytest.raises(ValueError, match="name"):
        scheme_from_dict({"blocks": [{"block_id": "start", "kind": "in"}], "connections": []})


def test_scheme_from_dict_rejects_duplicate_block_ids():
    data = {
        "name": "Duplicate",
        "blocks": [
            {"block_id": "start", "name": "Start", "kind": "in"},
            {"block_id": "start", "name": "End", "kind": "out"},
        ],
        "connections": [],
    }

    with pytest.raises(ValueError, match="Duplicate block_id"):
        scheme_from_dict(data)


def test_scheme_from_dict_rejects_missing_connection_target():
    data = {
        "name": "Broken connection",
        "blocks": [
            {"block_id": "start", "name": "Start", "kind": "in"},
            {"block_id": "end", "name": "End", "kind": "out"},
        ],
        "connections": [{"connection_id": "c1", "source_id": "start", "target_id": "ghost"}],
    }

    with pytest.raises(ValueError, match="missing block"):
        scheme_from_dict(data)


def test_scheme_from_dict_rejects_unknown_block_kind():
    with pytest.raises(ValueError, match="Unsupported block kind"):
        scheme_from_dict({"blocks": [{"block_id": "x", "name": "X", "kind": "alien"}], "connections": []})


def test_scheme_from_dict_rejects_too_many_blocks():
    blocks = [{"block_id": f"b{i}", "name": f"B{i}", "kind": "right"} for i in range(MAX_SCHEME_BLOCKS + 1)]

    with pytest.raises(ValueError, match="too many"):
        scheme_from_dict({"blocks": blocks, "connections": []})


def test_scheme_from_dict_rejects_deep_nested_scheme():
    nested = {"name": "Leaf", "blocks": [], "connections": []}
    for index in range(MAX_NESTED_SCHEME_DEPTH + 2):
        nested = {
            "name": f"Level {index}",
            "blocks": [
                {
                    "block_id": f"sub_{index}",
                    "name": f"Sub {index}",
                    "kind": "right",
                    "is_subscheme": True,
                    "nested_scheme": nested,
                }
            ],
            "connections": [],
        }

    with pytest.raises(ValueError, match="too deep"):
        scheme_from_dict(nested)
