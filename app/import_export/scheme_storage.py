from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.import_export.import_safety import (
    ALLOWED_BLOCK_KINDS,
    MAX_METADATA_ITEMS,
    MAX_NESTED_SCHEME_DEPTH,
    MAX_PARAMS_ITEMS,
    MAX_SCHEME_BLOCKS,
    MAX_SCHEME_CONNECTIONS,
    ensure_finite_float,
    ensure_import_file_size,
    ensure_mapping,
    ensure_sequence,
    ensure_string,
)
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel


SCHEME_VERSION = 2


def _scheme_to_dict(scheme: SchemeModel) -> dict[str, Any]:
    data = asdict(scheme)
    data["version"] = SCHEME_VERSION
    return data


def _block_from_dict(data: dict[str, Any], *, depth: int) -> BlockModel:
    if not isinstance(data, dict):
        raise ValueError("Scheme block must be an object.")
    for field_name in ("block_id", "name", "kind"):
        if field_name not in data:
            raise ValueError(f"Scheme block is missing required field: {field_name}.")
    kind = ensure_string(data["kind"], "block.kind")
    if kind not in ALLOWED_BLOCK_KINDS:
        raise ValueError(f"Unsupported block kind: {kind}.")
    nested = data.get("nested_scheme")
    nested_scheme = scheme_from_dict(nested, _depth=depth + 1) if nested else None
    params = {
        ensure_string(k, "params key"): _coerce_param_value(v)
        for k, v in ensure_mapping(data.get("params", {}), "params", max_items=MAX_PARAMS_ITEMS).items()
    }
    return BlockModel(
        block_id=ensure_string(data["block_id"], "block.block_id"),
        name=ensure_string(data["name"], "block.name"),
        kind=kind,
        x=ensure_finite_float(data.get("x", 0.0), "block.x"),
        y=ensure_finite_float(data.get("y", 0.0), "block.y"),
        params=params,
        is_subscheme=bool(data.get("is_subscheme", False)),
        nested_scheme=nested_scheme,
    )


def _connection_from_dict(data: dict[str, Any]) -> ConnectionModel:
    if not isinstance(data, dict):
        raise ValueError("Scheme connection must be an object.")
    for field_name in ("source_id", "target_id"):
        if field_name not in data:
            raise ValueError(f"Scheme connection is missing required field: {field_name}.")
    return ConnectionModel(
        connection_id=ensure_string(data.get("connection_id", ""), "connection.connection_id", required=False),
        source_id=ensure_string(data["source_id"], "connection.source_id"),
        source_port=ensure_string(data.get("source_port", ""), "connection.source_port", required=False),
        target_id=ensure_string(data["target_id"], "connection.target_id"),
        target_port=ensure_string(data.get("target_port", ""), "connection.target_port", required=False),
    )


def _coerce_param_value(value: Any) -> Any:
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _validate_loaded_scheme_shape(scheme: SchemeModel) -> None:
    ids: set[str] = set()
    for block in scheme.blocks:
        if block.block_id in ids:
            raise ValueError(f"Duplicate block_id in scheme: {block.block_id}.")
        ids.add(block.block_id)
    for connection in scheme.connections:
        if connection.source_id not in ids or connection.target_id not in ids:
            raise ValueError("Scheme connection references a missing block.")


def scheme_from_dict(data: dict[str, Any], *, _depth: int = 0) -> SchemeModel:
    if _depth > MAX_NESTED_SCHEME_DEPTH:
        raise ValueError("Scheme nesting is too deep.")
    if not isinstance(data, dict):
        raise ValueError("Scheme data must be an object.")
    blocks_data = ensure_sequence(data.get("blocks", []), "blocks", max_items=MAX_SCHEME_BLOCKS)
    connections_data = ensure_sequence(data.get("connections", []), "connections", max_items=MAX_SCHEME_CONNECTIONS)
    scheme = SchemeModel(
        name=ensure_string(data.get("name", "РќРѕРІР°СЏ СЃС…РµРјР°"), "scheme.name", required=False) or "РќРѕРІР°СЏ СЃС…РµРјР°",
        blocks=[_block_from_dict(item, depth=_depth) for item in blocks_data],
        connections=[_connection_from_dict(item) for item in connections_data],
        metadata=ensure_mapping(data.get("metadata", {}), "metadata", max_items=MAX_METADATA_ITEMS),
    )
    _validate_loaded_scheme_shape(scheme)
    return scheme


def save_scheme(path: str | Path, scheme: SchemeModel) -> None:
    target = Path(path)
    target.write_text(
        json.dumps(_scheme_to_dict(scheme), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_scheme(path: str | Path) -> SchemeModel:
    target = Path(path)
    ensure_import_file_size(target)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid scheme JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc
    if not isinstance(raw, dict):
        raise ValueError("Scheme file has invalid format.")
    scheme = scheme_from_dict(raw)
    from app.core.validators import validate_scheme

    validation = validate_scheme(scheme)
    if not validation.ok:
        raise ValueError("Scheme is invalid: " + "; ".join(validation.errors))
    return scheme
