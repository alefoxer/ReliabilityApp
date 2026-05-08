from __future__ import annotations

import math
from html import escape as _html_escape
from pathlib import Path
from typing import Any


MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_SCHEME_BLOCKS = 1000
MAX_SCHEME_CONNECTIONS = 3000
MAX_NESTED_SCHEME_DEPTH = 8
MAX_STRING_LENGTH = 10_000
MAX_MAPPING_ITEMS = 5000
MAX_METADATA_ITEMS = 200
MAX_PARAMS_ITEMS = 100
ALLOWED_BLOCK_KINDS = {"in", "out", "junction", "right", "up", "up_right", "down_right"}
XLSX_FORMULA_PREFIXES = ("=", "+", "-", "@")


def ensure_import_file_size(path: str | Path, *, max_bytes: int = MAX_IMPORT_BYTES) -> None:
    size = Path(path).stat().st_size
    if size > max_bytes:
        raise ValueError(f"Input file is too large: {size} bytes. Limit is {max_bytes} bytes.")


def ensure_text_size(text: str, *, max_bytes: int = MAX_IMPORT_BYTES) -> None:
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"Input text is too large: {size} bytes. Limit is {max_bytes} bytes.")


def ensure_string(value: Any, field_name: str, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise ValueError(f"Missing required field: {field_name}.")
        return ""
    text = str(value)
    if required and not text:
        raise ValueError(f"Field {field_name} must not be empty.")
    if len(text) > MAX_STRING_LENGTH:
        raise ValueError(f"Field {field_name} is too long.")
    return text


def ensure_mapping(value: Any, field_name: str, *, max_items: int = MAX_MAPPING_ITEMS) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Field {field_name} must be an object.")
    if len(value) > max_items:
        raise ValueError(f"Field {field_name} contains too many items.")
    result: dict[str, Any] = {}
    for key, item in value.items():
        key_text = ensure_string(key, f"{field_name} key")
        result[key_text] = _sanitize_scalar_tree(item, field_name)
    return result


def ensure_sequence(value: Any, field_name: str, *, max_items: int) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Field {field_name} must be a list.")
    if len(value) > max_items:
        raise ValueError(f"Field {field_name} contains too many items.")
    return value


def ensure_finite_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field {field_name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"Field {field_name} must be a finite number.")
    return number


def validate_probability_value(value: Any, field_name: str) -> float:
    number = ensure_finite_float(value, field_name)
    if not 0 <= number <= 1:
        raise ValueError(f"Field {field_name} must be in range 0..1.")
    return number


def validate_non_negative_value(value: Any, field_name: str) -> float:
    number = ensure_finite_float(value, field_name)
    if number < 0:
        raise ValueError(f"Field {field_name} must be non-negative.")
    return number


def validate_integer_value(value: Any, field_name: str, *, minimum: int = 0) -> int:
    number = ensure_finite_float(value, field_name)
    integer = int(number)
    if number != integer:
        raise ValueError(f"Field {field_name} must be an integer.")
    if integer < minimum:
        raise ValueError(f"Field {field_name} must be at least {minimum}.")
    return integer


def safe_html(value: Any) -> str:
    return _html_escape(str(value), quote=True)


def safe_xlsx_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(XLSX_FORMULA_PREFIXES):
        return "'" + value
    return value


def _sanitize_scalar_tree(value: Any, field_name: str, *, depth: int = 0) -> Any:
    if depth > MAX_NESTED_SCHEME_DEPTH + 4:
        raise ValueError(f"Field {field_name} is too deeply nested.")
    if isinstance(value, str):
        return ensure_string(value, field_name, required=False)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"Field {field_name} must be finite.")
        return value
    if isinstance(value, (bool, type(None))):
        return value
    if isinstance(value, dict):
        if len(value) > MAX_MAPPING_ITEMS:
            raise ValueError(f"Field {field_name} contains too many items.")
        return {
            ensure_string(key, f"{field_name} key"): _sanitize_scalar_tree(item, field_name, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        if len(value) > MAX_MAPPING_ITEMS:
            raise ValueError(f"Field {field_name} contains too many items.")
        return [_sanitize_scalar_tree(item, field_name, depth=depth + 1) for item in value]
    return ensure_string(value, field_name, required=False)
