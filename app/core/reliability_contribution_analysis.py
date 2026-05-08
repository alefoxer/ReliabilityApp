from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.formulas.graph_formula_builder import (
    PASS_THROUGH_KINDS,
    _block_availability,
    _block_probability,
    _metric_symbol,
    build_formula_report,
    evaluate_formula_for_scheme,
)
from app.core.rbd_models import BlockModel, SchemeModel
from app.core.scheme_adapter import _derive_t0_from_availability, _representative_recovery_time, _structural_t0_from_formula


CONTRIBUTION_METRICS = ("P", "T0", "Kg", "Kog")
CONTRIBUTION_METRIC_LABELS = {
    "P": "P(t)",
    "T0": "T0",
    "Kg": "Kг",
    "Kog": "Kог",
}


@dataclass(frozen=True)
class ElementContribution:
    block_id: str
    name: str
    values: dict[str, float]
    raw_impact: dict[str, float]
    contribution_percent: dict[str, float]


@dataclass(frozen=True)
class ContributionAnalysis:
    metric: str
    metric_label: str
    total_values: dict[str, float]
    elements: list[ElementContribution]


def analyze_scheme_contributions(
    scheme: SchemeModel,
    *,
    time_horizon: int | float = 1000,
    metric: str = "P",
) -> ContributionAnalysis:
    """Estimate per-element contribution to the selected scheme indicator.

    The analysis is intentionally read-only: it reuses the structural formula
    AST and block parameter rules from the existing scheme calculation path.
    Percent values are normalized sensitivities, so the bars sum to 100%.
    """
    selected_metric = _normalize_metric(metric)
    horizon = int(float(time_horizon or 0))
    report = build_formula_report(scheme)
    elements = _active_leaf_blocks(report.normalized_scheme)

    p_values = {
        str(_metric_symbol(block, "P")): _block_probability(block, horizon)
        for block in elements
    }
    k_values = {
        str(_metric_symbol(block, "K")): _block_availability(block)
        for block in elements
    }
    formula_values = evaluate_formula_for_scheme(scheme, horizon)
    tv_value = _representative_recovery_time(elements)
    kg_total = float(formula_values.get("Kg", 0.0) or 0.0)
    p_total = float(formula_values.get("P", 0.0) or 0.0)
    t0_total = _scheme_total_t0(scheme, kg_total, tv_value) if selected_metric == "T0" else 0.0
    total_values = {
        "P": p_total,
        "Kg": kg_total,
        "Kog": p_total * kg_total,
        "T0": float(t0_total or 0.0),
    }

    items: list[ElementContribution] = []
    raw_by_metric: dict[str, list[float]] = {key: [] for key in CONTRIBUTION_METRICS}
    pending: list[tuple[BlockModel, dict[str, float], dict[str, float]]] = []
    for block in elements:
        p_symbol = str(_metric_symbol(block, "P"))
        k_symbol = str(_metric_symbol(block, "K"))
        p_value = float(p_values.get(p_symbol, 0.0))
        k_value = float(k_values.get(k_symbol, 0.0))
        values = {
            "P": p_value,
            "Kg": k_value,
            "Kog": p_value * k_value,
            "T0": _block_t0(block),
        }
        p_if_perfect = dict(p_values)
        p_if_perfect[p_symbol] = 1.0
        k_if_perfect = dict(k_values)
        k_if_perfect[k_symbol] = 1.0
        improved_p = float(report.formula_ast_reliability.evaluate(p_if_perfect))
        improved_kg = float(report.formula_ast_availability.evaluate(k_if_perfect))
        raw = {
            "P": max(0.0, improved_p - total_values["P"]),
            "Kg": max(0.0, improved_kg - total_values["Kg"]),
            "Kog": max(0.0, improved_p * improved_kg - total_values["Kog"]),
            "T0": _block_failure_rate(block),
        }
        for key, value in raw.items():
            raw_by_metric[key].append(value)
        pending.append((block, values, raw))

    totals = {
        key: sum(value for value in values if isfinite(value) and value > 0.0)
        for key, values in raw_by_metric.items()
    }
    for block, values, raw in pending:
        contribution = {
            key: (raw[key] / totals[key] * 100.0 if totals[key] > 0.0 else 0.0)
            for key in CONTRIBUTION_METRICS
        }
        items.append(
            ElementContribution(
                block_id=str(block.block_id),
                name=str(block.name or block.block_id),
                values=values,
                raw_impact=raw,
                contribution_percent=contribution,
            )
        )

    return ContributionAnalysis(
        metric=selected_metric,
        metric_label=CONTRIBUTION_METRIC_LABELS[selected_metric],
        total_values=total_values,
        elements=items,
    )


def _normalize_metric(metric: str) -> str:
    value = str(metric or "P").strip()
    aliases = {
        "P(t)": "P",
        "P": "P",
        "T0": "T0",
        "Kг": "Kg",
        "Kg": "Kg",
        "Kог": "Kog",
        "Kog": "Kog",
    }
    return aliases.get(value, "P")


def _active_leaf_blocks(normalized_scheme) -> list[BlockModel]:
    blocks: list[BlockModel] = []
    ordered_ids = sorted(
        normalized_scheme.active_ids,
        key=lambda block_id: (
            normalized_scheme.blocks[block_id].x,
            normalized_scheme.blocks[block_id].y,
            normalized_scheme.blocks[block_id].name,
        ),
    )
    for block_id in ordered_ids:
        block = normalized_scheme.blocks[block_id]
        if block.kind in PASS_THROUGH_KINDS:
            continue
        if block.is_subscheme and block.nested_scheme is not None:
            blocks.extend(_active_leaf_blocks(build_formula_report(block.nested_scheme).normalized_scheme))
            continue
        blocks.append(block)
    return blocks


def _scheme_total_t0(scheme: SchemeModel, kg_total: float, tv_value: float | None) -> float:
    structural_t0 = _structural_t0_from_formula(scheme)
    derived_t0 = structural_t0 if structural_t0 is not None else _derive_t0_from_availability(kg_total, tv_value)
    return float(derived_t0 or 0.0)


def _block_t0(block: BlockModel) -> float:
    for key in ("T0", "t0"):
        if key in block.params:
            try:
                value = float(block.params.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0.0:
                return value
    failure_rate = _block_failure_rate(block)
    return 1.0 / failure_rate if failure_rate > 0.0 else 0.0


def _block_failure_rate(block: BlockModel) -> float:
    try:
        value = float(block.params.get("lambda", 0.0) or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if value > 0.0:
        return value
    t0 = _block_t0_from_params_only(block)
    return 1.0 / t0 if t0 > 0.0 else 0.0


def _block_t0_from_params_only(block: BlockModel) -> float:
    try:
        value = float(block.params.get("T0", 0.0) or block.params.get("t0", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0.0 else 0.0
