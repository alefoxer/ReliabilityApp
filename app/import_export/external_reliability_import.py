"""Import normalized external reliability projects.

The application stores editable diagrams as ``SchemeModel`` JSON. External
engineering documents are intentionally handled one level above that: text,
tables and manually reviewed data are normalized into ``ImportedReliabilityProject``
JSON/YAML and only then converted into the internal scheme model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.formulas.graph_formula_builder import evaluate_formula_for_scheme
from app.import_export.import_safety import (
    MAX_MAPPING_ITEMS,
    MAX_SCHEME_BLOCKS,
    ensure_import_file_size,
    ensure_mapping,
    ensure_string,
    ensure_text_size,
)
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel
from app.core.validators import validate_scheme


SUPPORTED_STRUCTURED_SUFFIXES = {".json", ".yaml", ".yml"}


@dataclass(frozen=True, slots=True)
class ImportComparison:
    metric: str
    expected: float | None
    actual: float | None
    abs_delta: float | None
    rel_delta: float | None
    status: str


@dataclass(slots=True)
class ImportedReliabilityProject:
    schema_version: str
    project_name: str
    source: dict[str, Any] = field(default_factory=dict)
    requirements: dict[str, Any] = field(default_factory=dict)
    calculation_conditions: dict[str, Any] = field(default_factory=dict)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    schemes: dict[str, dict[str, Any]] = field(default_factory=dict)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    expected_results: dict[str, dict[str, float]] = field(default_factory=dict)
    conclusions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_review_required: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def first_scheme_id(self) -> str:
        if not self.schemes:
            raise ValueError("Imported project does not contain schemes.")
        return next(iter(self.schemes))


def load_imported_project(path: str | Path) -> ImportedReliabilityProject:
    """Load a normalized external reliability project from JSON or YAML."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_STRUCTURED_SUFFIXES:
        raise ValueError(f"Unsupported import format: {suffix}. Use JSON or YAML.")
    ensure_import_file_size(source)
    text = source.read_text(encoding="utf-8")
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON imported project: {exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc
    else:
        data = _load_yaml(text)
    return imported_project_from_dict(data)


def imported_project_from_dict(data: dict[str, Any]) -> ImportedReliabilityProject:
    """Validate and normalize an imported project dictionary."""
    if not isinstance(data, dict):
        raise ValueError("Imported project must be a mapping/object.")
    if len(data) > MAX_MAPPING_ITEMS:
        raise ValueError("Imported project contains too many top-level fields.")
    schema_version = ensure_string(data.get("schema_version") or "", "schema_version")
    if not schema_version:
        raise ValueError("Imported project must define schema_version.")
    project_name = ensure_string(data.get("project_name") or "Imported reliability project", "project_name")
    schemes = _normalize_keyed_items(data.get("schemes", {}), "id")
    if not schemes:
        raise ValueError("Imported project must contain at least one scheme.")
    return ImportedReliabilityProject(
        schema_version=schema_version,
        project_name=project_name,
        source=ensure_mapping(data.get("source", {}) or {}, "source"),
        requirements=ensure_mapping(data.get("requirements", {}) or {}, "requirements"),
        calculation_conditions=ensure_mapping(data.get("calculation_conditions", {}) or {}, "calculation_conditions"),
        components=_normalize_keyed_items(data.get("components", {}), "id"),
        schemes=schemes,
        formulas=list(data.get("formulas", []) or []),
        expected_results={
            str(key): {str(metric): float(value) for metric, value in dict(values).items()}
            for key, values in dict(data.get("expected_results", {}) or {}).items()
        },
        conclusions=[str(item) for item in data.get("conclusions", []) or []],
        warnings=[str(item) for item in data.get("warnings", []) or []],
        manual_review_required=[str(item) for item in data.get("manual_review_required", []) or []],
        raw=data,
    )


def imported_project_to_scheme(
    project: ImportedReliabilityProject,
    scheme_id: str | None = None,
    *,
    time_horizon: int | None = None,
    _seen: set[str] | None = None,
) -> SchemeModel:
    """Convert a normalized imported scheme to the internal graph model."""
    selected_id = scheme_id or project.first_scheme_id
    seen = set(_seen or set())
    if selected_id in seen:
        raise ValueError(f"Nested imported schemes contain a cycle at {selected_id!r}.")
    seen.add(selected_id)
    scheme_data = project.schemes.get(selected_id)
    if scheme_data is None:
        raise ValueError(f"Scheme {selected_id!r} is not present in imported project.")
    builder = _SchemeBuilder(project, selected_id, time_horizon, seen)
    scheme = builder.build(scheme_data)
    warnings = list(project.warnings) + builder.warnings
    scheme.metadata.update(
        {
            "imported_project": project.project_name,
            "imported_scheme_id": selected_id,
            "import_source": project.source,
            "import_warnings": warnings,
            "manual_review_required": list(project.manual_review_required) + builder.manual_review_required,
            "calculation_conditions": project.calculation_conditions,
            "requirements": project.requirements,
        }
    )
    validation = validate_scheme(scheme)
    if not validation.ok:
        raise ValueError("Imported scheme is invalid: " + "; ".join(validation.errors))
    return scheme


def compare_imported_scheme_with_expected(
    project: ImportedReliabilityProject,
    scheme_id: str | None = None,
    *,
    time_horizon: int,
    tolerance: float = 1e-6,
) -> list[ImportComparison]:
    """Calculate an imported scheme and compare it with expected source values."""
    selected_id = scheme_id or project.first_scheme_id
    scheme = imported_project_to_scheme(project, selected_id, time_horizon=time_horizon)
    actual_values = evaluate_formula_for_scheme(scheme, time_horizon=time_horizon)
    expected_values = dict(project.expected_results.get(selected_id, {}))
    results: list[ImportComparison] = []
    for metric in sorted(expected_values):
        if metric not in {f"P_{time_horizon}", "P", "Kg", "K", "T0"}:
            continue
        actual_metric = "P" if metric in {f"P_{time_horizon}", "P"} else "Kg" if metric in {"Kg", "K"} else metric
        expected = expected_values.get(metric)
        actual = actual_values.get(actual_metric)
        if expected is None or actual is None:
            results.append(ImportComparison(metric, expected, actual, None, None, "cannot_check"))
            continue
        abs_delta = abs(actual - expected)
        rel_delta = abs_delta / abs(expected) if expected else abs_delta
        status = "match" if abs_delta <= tolerance or rel_delta <= tolerance else "different"
        results.append(ImportComparison(metric, expected, actual, abs_delta, rel_delta, status))
    if not results:
        results.append(ImportComparison("expected_results", None, None, None, None, "cannot_check"))
    return results


def _load_yaml(text: str) -> dict[str, Any]:
    ensure_text_size(text)
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional dependency
        raise ValueError("YAML import requires PyYAML. Use JSON or install PyYAML.") from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("YAML imported project must be a mapping/object.")
    return data


def _normalize_keyed_items(value: Any, key_name: str) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        if len(value) > MAX_SCHEME_BLOCKS:
            raise ValueError("Imported project contains too many keyed items.")
        return {ensure_string(key, f"{key_name} key"): ensure_mapping(item or {}, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > MAX_SCHEME_BLOCKS:
            raise ValueError("Imported project contains too many list items.")
        result: dict[str, dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Imported project lists must contain objects.")
            item_id = str(item.get(key_name) or "")
            if not item_id:
                raise ValueError(f"Imported item must define {key_name}.")
            result[item_id] = ensure_mapping(item, item_id)
        return result
    return {}


class _SchemeBuilder:
    def __init__(self, project: ImportedReliabilityProject, scheme_id: str, time_horizon: int | None, seen: set[str]) -> None:
        self.project = project
        self.scheme_id = scheme_id
        self.time_horizon = time_horizon
        self._seen = seen
        self.blocks: list[BlockModel] = []
        self.connections: list[ConnectionModel] = []
        self._ids: set[str] = set()
        self._names: set[str] = set()
        self._connection_index = 1
        self.warnings: list[str] = []
        self.manual_review_required: list[str] = []

    def build(self, scheme_data: dict[str, Any]) -> SchemeModel:
        self.blocks.append(BlockModel("start", "Start", "in", 60, 180))
        self.blocks.append(BlockModel("end", "End", "out", 420, 180))
        self._ids.update({"start", "end"})
        self._names.update({"Start", "End"})
        root = scheme_data.get("root") or {"type": scheme_data.get("type", "series"), "children": scheme_data.get("children", [])}
        entry, exit_ = self._emit_node(root, depth=0, index=1)
        self._connect("start", entry)
        self._connect(exit_, "end")
        return SchemeModel(
            name=str(scheme_data.get("name") or self.project.project_name),
            blocks=self.blocks,
            connections=self.connections,
            metadata={
                "source_reference": scheme_data.get("source_reference"),
                "confidence": scheme_data.get("confidence", "medium"),
                "scheme_type": scheme_data.get("type", "unknown"),
                "notes": list(scheme_data.get("notes", []) or []),
            },
        )

    def _emit_node(self, node: Any, *, depth: int, index: int) -> tuple[str, str]:
        if isinstance(node, str):
            return self._emit_element(self._component_to_node(node), depth=depth, index=index)
        if not isinstance(node, dict):
            raise ValueError(f"Unsupported scheme node: {node!r}")
        node_type = str(node.get("type") or node.get("node_type") or "element")
        if node_type == "series":
            return self._emit_series(node, depth=depth, index=index)
        if node_type == "parallel":
            return self._emit_parallel(node, depth=depth, index=index)
        if node_type == "reserve_group":
            return self._emit_reserve_group(node, depth=depth, index=index)
        if node_type == "nested_scheme":
            nested_id = str(node.get("scheme_id") or node.get("id") or "")
            if nested_id in self.project.schemes:
                nested = imported_project_to_scheme(self.project, nested_id, time_horizon=self.time_horizon, _seen=self._seen)
                return self._emit_element({**node, "nested_scheme": nested}, depth=depth, index=index)
        return self._emit_element(node, depth=depth, index=index)

    def _emit_series(self, node: dict[str, Any], *, depth: int, index: int) -> tuple[str, str]:
        repeated = self._expanded_children(node)
        if not repeated:
            return self._emit_passthrough("series_empty", depth, index)
        first_entry = ""
        previous_exit = ""
        for child_index, child in enumerate(repeated, start=1):
            entry, exit_ = self._emit_node(child, depth=depth + 1, index=child_index)
            if not first_entry:
                first_entry = entry
            if previous_exit:
                self._connect(previous_exit, entry)
            previous_exit = exit_
        return first_entry, previous_exit

    def _emit_parallel(self, node: dict[str, Any], *, depth: int, index: int) -> tuple[str, str]:
        children = self._expanded_children(node)
        split = self._add_block(f"junction_parallel_{depth}_{index}_split", "Parallel split", "junction", depth, index)
        merge = self._add_block(f"junction_parallel_{depth}_{index}_merge", "Parallel merge", "junction", depth, index + 1)
        for child_index, child in enumerate(children, start=1):
            entry, exit_ = self._emit_node(child, depth=depth + 1, index=child_index)
            self._connect(split, entry)
            self._connect(exit_, merge)
        return split, merge

    def _emit_reserve_group(self, node: dict[str, Any], *, depth: int, index: int) -> tuple[str, str]:
        k_required = int(node.get("k_required", 0) or 0)
        n_total = int(node.get("n_total", 0) or 0)
        if k_required == 1 and n_total > 1:
            reserve = dict(node)
            reserve.setdefault("name", f"Reserve group {k_required} of {n_total}")
            reserve.setdefault("parameters", {})
            reserve["parameters"] = {**dict(reserve.get("parameters", {}) or {}), "reserve_count": n_total - 1}
            return self._emit_element(reserve, depth=depth, index=index)
        self.manual_review_required.append(
            f"Reserve group {node.get('id', '')}: k-of-N reserve ({k_required} of {n_total}) requires verified method."
        )
        placeholder = dict(node)
        placeholder.setdefault("name", f"Reserve group {k_required} of {n_total} - manual method required")
        placeholder.setdefault("parameters", {})
        placeholder["parameters"] = {
            **dict(placeholder.get("parameters", {}) or {}),
            "block_role": "k_of_n",
            "k_required": k_required,
            "n_total": n_total,
            "reserve_type": str(node.get("reserve_type") or "sliding_loaded"),
        }
        return self._emit_element(placeholder, depth=depth, index=index)

    def _emit_element(self, node: dict[str, Any], *, depth: int, index: int) -> tuple[str, str]:
        quantity = int(node.get("quantity", 1) or 1)
        if quantity > 1 and node.get("connection", node.get("connection_type")) == "series":
            series_node = {"type": "series", "repeat": quantity, "child": {**node, "quantity": 1}}
            return self._emit_series(series_node, depth=depth, index=index)
        block_id = self._unique_id(str(node.get("id") or node.get("designation") or f"node_{depth}_{index}"))
        params = self._numeric_params(node)
        kind = str(node.get("kind") or "right")
        block = BlockModel(
            block_id=block_id,
            name=self._unique_name(str(node.get("name") or block_id)),
            kind=kind,
            x=160 + index * 150,
            y=130 + depth * 110,
            params=params,
            is_subscheme="nested_scheme" in node,
            nested_scheme=node.get("nested_scheme"),
        )
        self.blocks.append(block)
        return block_id, block_id

    def _emit_passthrough(self, prefix: str, depth: int, index: int) -> tuple[str, str]:
        block_id = self._add_block(f"{prefix}_{depth}_{index}", prefix, "junction", depth, index)
        return block_id, block_id

    def _expanded_children(self, node: dict[str, Any]) -> list[Any]:
        if "repeat" in node and "child" in node:
            count = int(node.get("repeat", 0) or 0)
            if count < 1:
                raise ValueError("repeat must be positive.")
            return [dict(node["child"], id=f"{node['child'].get('id', 'item')}_{i}") for i in range(1, count + 1)]
        return list(node.get("children", []) or [])

    def _component_to_node(self, component_id: str) -> dict[str, Any]:
        component = self.project.components.get(component_id)
        if component is None:
            raise ValueError(f"Component {component_id!r} is not present in imported project.")
        return {**component, "id": component_id}

    def _numeric_params(self, node: dict[str, Any]) -> dict[str, Any]:
        source = {**dict(node.get("parameters", {}) or {})}
        for source_key, target_key in (
            ("lambda_work", "lambda"),
            ("recovery_time", "Tv"),
            ("availability", "Kg"),
            ("reserve_count", "reserve_count"),
            ("k_required", "k_required"),
            ("n_total", "n_total"),
        ):
            if source_key in source:
                source[target_key] = source[source_key]
        probabilities = source.get("probability_by_time")
        if self.time_horizon is not None and isinstance(probabilities, dict):
            value = probabilities.get(str(self.time_horizon), probabilities.get(self.time_horizon))
            if value is not None:
                source["P"] = value
        result: dict[str, Any] = {}
        for key in ("block_role", "reserve_type", "calculation_note"):
            if key in source:
                result[str(key)] = str(source[key])
        if isinstance(probabilities, dict):
            table: dict[str, float] = {}
            for key, value in probabilities.items():
                try:
                    table[str(float(key))] = float(value)
                except (TypeError, ValueError):
                    continue
            if table:
                result["probability_by_time"] = table
        for key, value in source.items():
            if key in {"probability_by_time", "block_role", "reserve_type", "calculation_note"}:
                continue
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return result

    def _add_block(self, seed: str, name: str, kind: str, depth: int, index: int) -> str:
        block_id = self._unique_id(seed)
        self.blocks.append(BlockModel(block_id, self._unique_name(name), kind, 140 + index * 120, 120 + depth * 100))
        return block_id

    def _unique_id(self, seed: str) -> str:
        cleaned = "".join(char if char.isalnum() or char == "_" else "_" for char in seed).strip("_") or "node"
        candidate = cleaned
        suffix = 2
        while candidate in self._ids:
            candidate = f"{cleaned}_{suffix}"
            suffix += 1
        self._ids.add(candidate)
        return candidate

    def _unique_name(self, seed: str) -> str:
        cleaned = seed.strip() or "Block"
        candidate = cleaned
        suffix = 2
        while candidate in self._names:
            candidate = f"{cleaned} {suffix}"
            suffix += 1
        self._names.add(candidate)
        return candidate

    def _connect(self, source_id: str, target_id: str) -> None:
        self.connections.append(
            ConnectionModel(
                connection_id=f"c{self._connection_index}",
                source_id=source_id,
                source_port="out",
                target_id=target_id,
                target_port="in",
            )
        )
        self._connection_index += 1
