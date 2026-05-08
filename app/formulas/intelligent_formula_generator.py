"""Intelligent formula selection layer for reliability schemes.

This module builds on the existing graph AST. It recognizes AST fragments,
selects formulas from ``formula_library``, substitutes concrete N/parameters,
evaluates numeric values and prepares an explanation that can be shown in UI
or exported. It does not invent external standards; all current formulas are
marked as project method formulas until exact normative references are added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from typing import Any

from app.formulas.formula_library import FORMULA_LIBRARY, FormulaDefinition, formula_for_fragment
from app.formulas.graph_formula_builder import FormulaExpr, FormulaGenerationResult, build_formula_report, evaluate_formula_for_scheme
from app.core.rbd_models import BlockModel, FormulaInfo, SchemeModel


@dataclass(frozen=True, slots=True)
class FormulaCandidate:
    formula_id: str
    title: str
    status: str
    reason: str
    priority: int


@dataclass(frozen=True, slots=True)
class FragmentFormulaSelection:
    fragment_id: str
    fragment_kind: str
    metric: str
    selected_formula: FormulaDefinition | None
    candidates: tuple[FormulaCandidate, ...]
    elements: tuple[str, ...]
    parameters: dict[str, Any]
    general_formula: str
    instantiated_formula: str
    computable_formula: str
    numeric_value: float | None
    explanation: str


@dataclass(frozen=True, slots=True)
class IntelligentFormulaGenerationResult:
    base_report: FormulaGenerationResult
    fragment_selections: tuple[FragmentFormulaSelection, ...]
    recommended_formulas: tuple[FormulaDefinition, ...]
    instantiated_formula_reliability: str
    instantiated_formula_availability: str
    instantiated_formula_mttf: str
    numeric_results: dict[str, float]
    parameter_values: dict[str, Any]
    explanation_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_formula_info(self) -> FormulaInfo:
        text_lines = [
            f"Pсист(t) = {self.instantiated_formula_reliability}",
            f"Kг_сист = {self.instantiated_formula_availability.replace(' · ', ' * ')}",
        ]
        if self.instantiated_formula_mttf:
            text_lines.append(f"T0 = {self.instantiated_formula_mttf}")
        text = "\n".join(text_lines)
        structural = _selection_table_text(self.fragment_selections)
        if self.instantiated_formula_mttf:
            structural += (
                "\n\nФормулы дополнительных показателей:\n"
                f"- T0: STRUCT.EQUIVALENT.T0; {self.instantiated_formula_mttf}"
            )
        computational = "\n".join(
            [
                f"P = {self.base_report.computable_formula_reliability}",
                f"Kг = {self.base_report.computable_formula_availability}",
            ]
        )
        symbols = dict(self.base_report.symbols)
        note = (
            "Формула построена через интеллектуальный слой: схема распознана как набор "
            "фрагментов, для каждого фрагмента выбрана формула из библиотеки проекта, "
            "после чего выполнена подстановка конкретных N и параметров."
        )
        return FormulaInfo(
            text=text,
            is_exact=True,
            note=note,
            structural=structural,
            computational=computational,
            steps=self.explanation_steps,
            symbols=symbols,
            used_blocks=self.base_report.used_blocks,
            unused_blocks=self.base_report.unused_blocks,
            warnings=self.warnings,
        )


def generate_intelligent_formula(
    scheme: SchemeModel,
    *,
    time_horizon: int = 1000,
    base_report: FormulaGenerationResult | None = None,
) -> IntelligentFormulaGenerationResult:
    """Analyze a scheme, select formulas and instantiate them for this scheme."""
    report = base_report or build_formula_report(scheme)
    p_values, k_values, parameter_values = _symbol_values_with_parameters(report, time_horizon)
    selections: list[FragmentFormulaSelection] = []
    _collect_fragment_selections(report.formula_ast_reliability, "P", p_values, selections, path="P")
    _collect_fragment_selections(report.formula_ast_availability, "Kг", k_values, selections, path="K")
    numeric_results = evaluate_formula_for_scheme(scheme, time_horizon=time_horizon)
    t0_formula, t0_value = _equivalent_t0_formula(parameter_values)
    if t0_value is not None:
        numeric_results = {**numeric_results, "T0": t0_value}
    recommended = tuple(
        selection.selected_formula
        for selection in selections
        if selection.selected_formula is not None
    )
    steps = _build_intelligent_steps(report, selections, parameter_values, numeric_results)
    warnings = list(report.warnings)
    if any(selection.selected_formula is None and selection.fragment_kind != "symbol" for selection in selections):
        warnings.append("Для части фрагментов не найдена специализированная формула; используется базовое AST-представление.")
    return IntelligentFormulaGenerationResult(
        base_report=report,
        fragment_selections=tuple(selections),
        recommended_formulas=recommended,
        instantiated_formula_reliability=report.symbolic_formula_reliability,
        instantiated_formula_availability=report.symbolic_formula_availability,
        instantiated_formula_mttf=t0_formula,
        numeric_results=numeric_results,
        parameter_values=parameter_values,
        explanation_steps=steps,
        warnings=warnings,
    )


def enhance_formula_info(
    scheme: SchemeModel,
    formula: FormulaInfo,
    *,
    base_report: FormulaGenerationResult | None = None,
    time_horizon: int = 1000,
) -> FormulaInfo:
    """Return FormulaInfo enriched with library selection and substitutions."""
    try:
        intelligent = generate_intelligent_formula(scheme, time_horizon=time_horizon, base_report=base_report)
    except Exception as exc:
        formula.warnings.append(f"Интеллектуальный подбор формул недоступен: {exc}")
        return formula
    enriched = intelligent.to_formula_info()
    enriched.latex = formula.latex
    if formula.structural:
        enriched.structural = formula.structural + "\n\n" + enriched.structural
    enriched.steps = formula.steps + [step for step in enriched.steps if step not in formula.steps]
    enriched.warnings = list(dict.fromkeys(formula.warnings + enriched.warnings))
    return enriched


def _collect_fragment_selections(
    expr: FormulaExpr,
    metric: str,
    values: dict[str, float],
    selections: list[FragmentFormulaSelection],
    *,
    path: str,
) -> float:
    child_values = [
        _collect_fragment_selections(child, metric, values, selections, path=f"{path}.{index}")
        for index, child in enumerate(expr.children, start=1)
    ]
    definition = formula_for_fragment(expr.kind, metric)
    candidates = _candidates_for(expr.kind, metric, definition)
    elements = tuple(_ordered_symbols(expr))
    numeric = expr.evaluate(values)
    parameters = _fragment_parameters(expr, child_values)
    instantiated = expr.render_pretty()
    computable = expr.render_computable()
    explanation = _fragment_explanation(expr, metric, definition, parameters, instantiated)
    selections.append(
        FragmentFormulaSelection(
            fragment_id=path,
            fragment_kind=expr.kind,
            metric=metric,
            selected_formula=definition,
            candidates=candidates,
            elements=elements,
            parameters=parameters,
            general_formula=definition.general_formula if definition else instantiated,
            instantiated_formula=instantiated,
            computable_formula=computable,
            numeric_value=numeric,
            explanation=explanation,
        )
    )
    return numeric


def _candidates_for(kind: str, metric: str, selected: FormulaDefinition | None) -> tuple[FormulaCandidate, ...]:
    if selected is None:
        return (
            FormulaCandidate(
                formula_id="AST.FALLBACK",
                title="Композиционное AST-выражение",
                status="условно подходит",
                reason="Специализированная формула фрагмента не найдена; используется прямое выражение AST.",
                priority=1,
            ),
        )
    return (
        FormulaCandidate(
            formula_id=selected.formula_id,
            title=selected.title,
            status="подходит",
            reason=f"Фрагмент типа «{kind}» соответствует области применения формулы: {selected.applies_to}",
            priority=selected.priority,
        ),
    )


def _fragment_parameters(expr: FormulaExpr, child_values: list[float]) -> dict[str, Any]:
    if expr.kind in {"series", "parallel"}:
        return {
            "N": len(expr.children),
            "значения подфрагментов": [round(value, 8) for value in child_values],
        }
    if expr.kind == "reserve":
        return {"m": expr.reserve_count, "всего элементов": expr.reserve_count + 1, "символ": expr.symbol}
    if expr.kind == "symbol":
        return {"символ": expr.symbol}
    return {}


def _fragment_explanation(
    expr: FormulaExpr,
    metric: str,
    definition: FormulaDefinition | None,
    parameters: dict[str, Any],
    instantiated: str,
) -> str:
    if definition is None:
        return f"Фрагмент {expr.kind}: специализированная формула не найдена, используется {instantiated}."
    params = ", ".join(f"{key}={value}" for key, value in parameters.items()) or "без параметров"
    return (
        f"Фрагмент {expr.kind}, показатель {metric}: выбрана формула «{definition.title}» "
        f"({definition.formula_id}); подстановка: {params}; конкретная формула: {instantiated}."
    )


def _symbol_values_with_parameters(
    report: FormulaGenerationResult,
    time_horizon: int,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    p_values: dict[str, float] = {}
    k_values: dict[str, float] = {}
    parameters: dict[str, Any] = {"t": time_horizon}
    parameters["_lambda_values"] = {}
    for block_id in report.normalized_scheme.active_ids:
        block = report.normalized_scheme.blocks[block_id]
        if block.kind in {"in", "out", "junction"}:
            continue
        _collect_block_values(block, time_horizon, p_values, k_values, parameters)
    return p_values, k_values, parameters


def _collect_block_values(
    block: BlockModel,
    time_horizon: int,
    p_values: dict[str, float],
    k_values: dict[str, float],
    parameters: dict[str, Any],
) -> None:
    if block.is_subscheme and block.nested_scheme is not None:
        nested = build_formula_report(block.nested_scheme)
        nested_p, nested_k, nested_params = _symbol_values_with_parameters(nested, time_horizon)
        p_values.update(nested_p)
        k_values.update(nested_k)
        parameters.setdefault("_lambda_values", {}).update(nested_params.get("_lambda_values", {}))
        parameters.update(
            {
                f"{block.name}/{key}": value
                for key, value in nested_params.items()
                if not str(key).startswith("_")
            }
        )
        return
    symbol = _safe_symbol(block.name)
    lam = float(block.params.get("lambda", 0.0) or 0.0)
    tv = float(block.params.get("Tv", 0.0) or 0.0)
    kg = block.params.get("Kg", block.params.get("K"))
    explicit_p = block.params.get("P")
    if explicit_p is not None:
        p_values[symbol] = max(0.0, min(1.0, float(explicit_p)))
    else:
        p_values[symbol] = max(0.0, min(1.0, exp(-lam * time_horizon))) if lam > 0 else 1.0
    if kg is not None:
        k_values[f"K_{symbol}"] = max(0.0, min(1.0, float(kg)))
    elif lam > 0 and tv > 0:
        k_values[f"K_{symbol}"] = max(0.0, min(1.0, 1.0 / (1.0 + lam * tv)))
    else:
        k_values[f"K_{symbol}"] = p_values[symbol]
    parameters[f"λ_{symbol}"] = lam
    parameters.setdefault("_lambda_values", {})[symbol] = lam
    if tv:
        parameters[f"Tв_{symbol}"] = tv
    if "reserve_count" in block.params:
        parameters[f"m_{symbol}"] = int(block.params.get("reserve_count", 0) or 0)


def _build_intelligent_steps(
    report: FormulaGenerationResult,
    selections: list[FragmentFormulaSelection],
    parameter_values: dict[str, Any],
    numeric_results: dict[str, float],
) -> list[str]:
    steps = [
        f"Анализ схемы: расчетных блоков включено в формулу: {len(report.used_blocks)}; неиспользованных: {len(report.unused_blocks)}.",
    ]
    if report.symbols:
        steps.append(
            "Обозначения в формуле: "
            + "; ".join(f"{symbol}: {description}" for symbol, description in report.symbols.items())
            + "."
        )
    for selection in selections:
        if selection.fragment_kind == "symbol":
            continue
        steps.append(selection.explanation)
    visible_parameters = {key: value for key, value in parameter_values.items() if not str(key).startswith("_")}
    if visible_parameters:
        params = ", ".join(f"{key}={value}" for key, value in visible_parameters.items())
        steps.append(f"Подставленные параметры: {params}.")
    if numeric_results:
        values = ", ".join(f"{key}={value:.8g}" for key, value in numeric_results.items())
        steps.append(f"Численный результат по этой же формуле: {values}.")
    if "T0" in numeric_results:
        definition = FORMULA_LIBRARY.get("STRUCT.EQUIVALENT.T0")
        if definition is not None:
            t0_formula, _ = _equivalent_t0_formula(parameter_values)
            steps.append(
                f"Для показателя T0 применена формула «{definition.title}»: "
                f"{definition.display_formula}. Конкретизация: {t0_formula}. "
                f"Ограничение: {definition.limitations}"
            )
    return steps


def _selection_table_text(selections: tuple[FragmentFormulaSelection, ...]) -> str:
    lines = ["Выбранные формулы по фрагментам:"]
    for selection in selections:
        if selection.fragment_kind == "symbol":
            continue
        formula_id = selection.selected_formula.formula_id if selection.selected_formula else "AST.FALLBACK"
        status = selection.selected_formula.verification_status if selection.selected_formula else "fallback"
        lines.append(
            f"- {selection.fragment_id}: {selection.fragment_kind}, {selection.metric}, {formula_id}; "
            f"status={status}; "
            f"N={selection.parameters.get('N', selection.parameters.get('всего элементов', '-'))}; "
            f"{selection.instantiated_formula}"
        )
    return "\n".join(lines)


def _equivalent_t0_formula(parameter_values: dict[str, Any]) -> tuple[str, float | None]:
    """Return the T0 formula used by the scheme adapter for active block lambdas."""
    lambdas = {
        str(symbol): float(value)
        for symbol, value in dict(parameter_values.get("_lambda_values", {})).items()
        if float(value or 0.0) > 0
    }
    if not lambdas:
        return "", None
    ordered_symbols = sorted(lambdas, key=_natural_key)
    denominator = " + ".join(f"λ_{symbol}" for symbol in ordered_symbols)
    value = 1.0 / sum(lambdas.values())
    return f"1 / ({denominator}) = {value:.8g}", value


def _ordered_symbols(expr: FormulaExpr) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def visit(node: FormulaExpr) -> None:
        if node.kind in {"symbol", "reserve"}:
            if node.symbol not in seen:
                result.append(node.symbol)
                seen.add(node.symbol)
            return
        for child in node.children:
            visit(child)

    visit(expr)
    return result


def _safe_symbol(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in str(value).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "E"


def _natural_key(value: str) -> tuple:
    parts: list[int | str] = []
    chunk = ""
    for char in str(value):
        if char.isdigit():
            chunk += char
            continue
        if chunk:
            parts.append(int(chunk))
            chunk = ""
        parts.append(char)
    if chunk:
        parts.append(int(chunk))
    return tuple(parts)
