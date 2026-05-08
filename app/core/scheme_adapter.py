from __future__ import annotations

from dataclasses import asdict
import math
from statistics import median

from app.core.dependability_graph import Graph
from app.formulas.graph_formula_builder import (
    PASS_THROUGH_KINDS,
    build_formula_for_scheme,
    build_formula_report,
    evaluate_formula_for_scheme,
)
from app.core.rbd_models import CalculationResult, SchemeModel
from app.core.scheme_method_selector import select_method_for_scheme
from app.core.validators import validate_scheme

import sympy as sp


def scheme_to_graph(scheme: SchemeModel) -> Graph:
    graph = Graph()
    for block in scheme.blocks:
        graph.add_node(block.name, block.params)
    for connection in scheme.connections:
        source = scheme.block_by_id(connection.source_id)
        target = scheme.block_by_id(connection.target_id)
        if source and target:
            graph.add_edge(source.name, target.name)
    return graph


def calculate_scheme_reliability(
    scheme: SchemeModel,
    *,
    time_horizon: int = 1000,
    simulations: int = 10000,
    method: str = "Аналитический расчёт",
) -> CalculationResult:
    """Calculate scheme indicators using the same rules as the formula generator."""
    validation = validate_scheme(scheme)
    if not validation.ok:
        raise ValueError("\n".join(validation.errors))

    graph = scheme_to_graph(scheme)
    start_block = next((block for block in scheme.blocks if block.kind == "in"), None)
    end_block = next((block for block in scheme.blocks if block.kind == "out"), None)
    start_name = start_block.name if start_block is not None else "Start"
    end_name = end_block.name if end_block is not None else "End"
    graph.find_all_paths(start_name, end_name)
    formula = build_formula_for_scheme(scheme)
    formula_package = formula.package if formula is not None else None
    method_selection = select_method_for_scheme(scheme)
    formula_values = evaluate_formula_for_scheme(scheme, time_horizon)
    monte_carlo_probability = graph.calculate_reliability_monte_carlo(time_horizon, simulations, start_name, end_name)
    graph_t_values = _graph_time_values(scheme, time_horizon)
    probability_mode = _scheme_probability_mode(method)
    graph_p_values = _scheme_probability_graph(
        scheme,
        graph,
        graph_t_values,
        simulations=simulations,
        start_name=start_name,
        end_name=end_name,
        probability_mode=probability_mode,
    )
    selected_probability = _scheme_probability_value(
        graph,
        time_horizon,
        simulations=simulations,
        start_name=start_name,
        end_name=end_name,
        formula_values=formula_values,
        probability_mode=probability_mode,
        monte_carlo_probability=monte_carlo_probability,
    )

    blocks = [block for block in scheme.iter_blocks_recursive(include_pass_through=False)]
    structural_t0 = _structural_t0_from_formula(scheme)
    tv_value = _representative_recovery_time(blocks)
    kg_value = float(formula_values["Kg"])
    t0_value = structural_t0 if structural_t0 is not None else _derive_t0_from_availability(kg_value, tv_value)

    indicators = {
        "P": selected_probability,
        "Kg": kg_value,
        "Kog": kg_value * float(selected_probability),
        "Количество блоков": len(blocks),
        "Количество связей": len(scheme.connections),
    }
    if t0_value is not None and t0_value > 0.0:
        indicators["T0"] = t0_value
    if tv_value is not None:
        indicators["Tv"] = tv_value
    details = {
        "scheme": asdict(scheme),
        "calculation_method": method,
        "simulations": simulations,
        "monte_carlo_probability": monte_carlo_probability,
        "validation_warnings": validation.warnings,
        "formula_structural": formula.structural,
        "formula_computational": formula.computational,
        "formula_steps": formula.steps,
        "formula_symbols": formula.symbols,
        "formula_used_blocks": formula.used_blocks,
        "formula_unused_blocks": formula.unused_blocks,
        "formula_warnings": formula.warnings,
        "formula_package": formula_package.export_payload if formula_package else {},
        "formula_mode": formula_package.formula_mode if formula_package else "structural_fallback",
        "formula_values": formula_values,
        "indicator_sources": {
            "P": probability_mode,
            "Kg": "formula",
            "Kog": f"Kg * P({probability_mode})",
            "T0": "structural_formula_integral" if structural_t0 is not None else "derived_from_Kg_Tv" if t0_value is not None else "unavailable",
            "Tv": "component_recovery_time" if tv_value is not None else "unavailable",
        },
        "scheme_structure_type": method_selection.analysis.structure_type,
        "recommended_method_id": method_selection.recommended_method.method_id,
        "recommended_method_title": method_selection.recommended_method.title,
        "recommended_formula_mode": method_selection.formula_mode,
        "method_selection_explanation": method_selection.explanation,
        "method_candidates": [
            {
                "method_id": candidate.method_id,
                "title": candidate.title,
                "status": candidate.status,
                "reason": candidate.reason,
                "formula_mode": candidate.formula_mode,
            }
            for candidate in method_selection.methods
        ],
    }
    recommended_id = method_selection.recommended_method.method_id
    if recommended_id.startswith("AUTO."):
        display_method_name = "Формула по структуре схемы"
    else:
        display_method_name = method_selection.recommended_method.title
    return CalculationResult(
        method_name=display_method_name,
        indicators=indicators,
        source="scheme",
        formula=formula,
        formula_package=formula_package,
        graph_points={"t": graph_t_values, "P": graph_p_values},
        details=details,
    )


def _graph_time_values(scheme: SchemeModel, time_horizon: int | float) -> list[float]:
    horizon = max(float(time_horizon), 0.0)
    values = {round(horizon * index / 40, 6) for index in range(41)}
    values.add(0.0)
    values.add(round(horizon, 6))
    for block in scheme.iter_blocks_recursive(include_pass_through=False):
        table = block.params.get("probability_by_time")
        if not isinstance(table, dict):
            continue
        for raw_time in table:
            try:
                t_value = float(raw_time)
            except (TypeError, ValueError):
                continue
            if 0.0 <= t_value <= horizon:
                values.add(round(t_value, 6))
    return sorted(values)


def _scheme_probability_mode(method: str) -> str:
    normalized = str(method or "").lower()
    if "монте" in normalized:
        return "monte_carlo"
    if "приближ" in normalized:
        return "approximation"
    return "formula"


def _scheme_probability_value(
    graph: Graph,
    time_horizon: int | float,
    *,
    simulations: int,
    start_name: str,
    end_name: str,
    formula_values: dict[str, float],
    probability_mode: str,
    monte_carlo_probability: float,
) -> float:
    if probability_mode == "monte_carlo":
        return float(monte_carlo_probability)
    if probability_mode == "approximation":
        return float(graph.calculate_probability_approx(float(time_horizon)))
    return float(formula_values["P"])


def _scheme_probability_graph(
    scheme: SchemeModel,
    graph: Graph,
    graph_t_values: list[float],
    *,
    simulations: int,
    start_name: str,
    end_name: str,
    probability_mode: str,
) -> list[float]:
    if probability_mode == "monte_carlo":
        return [
            float(graph.calculate_reliability_monte_carlo(t_value, simulations, start_name, end_name))
            for t_value in graph_t_values
        ]
    if probability_mode == "approximation":
        return [float(graph.calculate_probability_approx(t_value)) for t_value in graph_t_values]
    return [
        float(evaluate_formula_for_scheme(scheme, t_value).get("P", 0.0))
        for t_value in graph_t_values
    ]


def _representative_recovery_time(blocks: list) -> float | None:
    values: list[float] = []
    for block in blocks:
        try:
            tv = float(block.params.get("Tv", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if tv > 0.0:
            values.append(tv)
    if not values:
        return None
    return float(median(values))


def _structural_t0_from_formula(scheme: SchemeModel) -> float | None:
    """Return MTTF as integral of the same structural P(t) formula used for P."""
    try:
        report = build_formula_report(scheme)
        expression = report.formula_ast_reliability.to_sympy()
        lambda_values = _lambda_values_for_normalized_scheme(report.normalized_scheme)
        if not lambda_values:
            return None

        time = sp.Symbol("__t", nonnegative=True)
        substitutions: dict[sp.Symbol, sp.Expr] = {}
        for symbol_name in expression.free_symbols:
            lam = lambda_values.get(str(symbol_name))
            if lam is None or lam <= 0.0:
                return None
            substitutions[symbol_name] = sp.exp(-float(lam) * time)

        if not substitutions:
            return None

        reliability_expr = sp.expand(expression.subs(substitutions))
        if reliability_expr.free_symbols - {time}:
            return None
        integral = sp.integrate(reliability_expr, (time, 0, sp.oo))
        value = float(integral.evalf())
    except Exception:
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return value


def _lambda_values_for_normalized_scheme(normalized_scheme) -> dict[str, float]:
    values: dict[str, float] = {}
    for block_id in normalized_scheme.active_ids:
        block = normalized_scheme.blocks[block_id]
        if block.kind in PASS_THROUGH_KINDS:
            continue
        if block.is_subscheme and block.nested_scheme is not None:
            nested = build_formula_report(block.nested_scheme)
            values.update(_lambda_values_for_normalized_scheme(nested.normalized_scheme))
            continue
        try:
            lam = float(block.params.get("lambda", 0.0) or 0.0)
        except (TypeError, ValueError):
            lam = 0.0
        values[_safe_symbol_name(block.name or block.block_id)] = lam
    return values


def _safe_symbol_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in str(value).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "E"


def _derive_t0_from_availability(kg_value: float, tv_value: float | None) -> float | None:
    if tv_value is None or tv_value <= 0.0:
        return None
    if kg_value <= 0.0 or kg_value >= 1.0:
        return None
    return kg_value * tv_value / (1.0 - kg_value)
