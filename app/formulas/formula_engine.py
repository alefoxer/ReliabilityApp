"""Method-library based formula generation for structural reliability schemes.

The engine is intentionally separated into small stages:
SchemeAnalyzer -> FormulaLibrary -> FormulaSelector -> FormulaInstantiator ->
FormulaEvaluator -> FormulaGenerationResult.

It still reuses the existing graph AST for structural fallback calculations, but
the user-facing explanation is built from explicit formula definitions selected
from ``formula_library``. Unknown or unverified cases are marked honestly and
are never presented as normative formulas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from typing import Any

from app.formulas.formula_library import FORMULA_LIBRARY, FormulaDefinition
from app.formulas.formula_rendering import latex_formula_text
from app.formulas.graph_formula_builder import FormulaExpr, FormulaGenerationResult as GraphFormulaReport
from app.formulas.graph_formula_builder import build_formula_report, evaluate_formula_for_scheme
from app.core.rbd_models import BlockModel, SchemeModel


@dataclass(frozen=True, slots=True)
class FragmentAnalysis:
    fragment_id: str
    node_type: str
    fragment_kind: str
    metric: str
    elements: tuple[str, ...]
    parameters: dict[str, Any]
    reason: str
    expression: FormulaExpr | None = None


@dataclass(frozen=True, slots=True)
class FormulaSelection:
    fragment_id: str
    definition: FormulaDefinition | None
    candidates: tuple[FormulaDefinition, ...]
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class InstantiatedFormula:
    fragment_id: str
    formula_id: str
    title: str
    metric: str
    node_type: str
    verification_status: str
    source: str
    general_formula: str
    instantiated_formula: str
    general_latex: str
    instantiated_latex: str
    display_latex: str
    parameter_substitution: dict[str, Any]
    computable_formula: str
    numeric_value: float | None
    explanation: str
    manual_review_required: bool = False
    limitations: str = ""


@dataclass(frozen=True, slots=True)
class FormulaGenerationResult:
    scheme_name: str
    base_report: GraphFormulaReport
    analysis: tuple[FragmentAnalysis, ...]
    selections: tuple[FormulaSelection, ...]
    instantiated_formulas: tuple[InstantiatedFormula, ...]
    numeric_results: dict[str, float]
    symbols: dict[str, str]
    parameter_values: dict[str, Any]
    explanation_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class FormulaLibrary:
    """Central access point for formula definitions."""

    def __init__(self, definitions: dict[str, FormulaDefinition] | None = None) -> None:
        self._definitions = definitions or FORMULA_LIBRARY

    def candidates_for(self, node_type: str, metric: str = "P") -> tuple[FormulaDefinition, ...]:
        fragment_kind = _library_fragment_kind(node_type)
        return self.candidates_for_fragment_kind(fragment_kind, metric)

    def candidates_for_fragment_kind(self, fragment_kind: str, metric: str = "P") -> tuple[FormulaDefinition, ...]:
        metric_key = "K" if metric in {"K", "Kg", "KРі"} else metric
        candidates = [
            definition
            for definition in self._definitions.values()
            if definition.fragment_kind == fragment_kind
            and (definition.metric == metric_key or definition.metric in {metric, "KРі"})
        ]
        return tuple(sorted(candidates, key=lambda item: item.priority, reverse=True))

    def get(self, formula_id: str) -> FormulaDefinition | None:
        return self._definitions.get(formula_id)


class SchemeAnalyzer:
    """Build a normalized report and classify scheme fragments."""

    def analyze(self, scheme: SchemeModel) -> tuple[GraphFormulaReport, tuple[FragmentAnalysis, ...]]:
        report = build_formula_report(scheme)
        fragments: list[FragmentAnalysis] = []
        self._collect_expression(report.formula_ast_reliability, "P", fragments, "P")
        self._collect_expression(report.formula_ast_availability, "KРі", fragments, "K")
        self._collect_special_reserve_blocks(scheme, fragments)
        return report, tuple(fragments)

    def _collect_expression(
        self,
        expression: FormulaExpr,
        metric: str,
        fragments: list[FragmentAnalysis],
        path: str,
    ) -> None:
        for index, child in enumerate(expression.children, start=1):
            self._collect_expression(child, metric, fragments, f"{path}.{index}")

        node_type = _node_type_for_expr(expression)
        parameters = _parameters_for_expr(expression)
        elements = tuple(_ordered_symbols(expression))
        fragments.append(
            FragmentAnalysis(
                fragment_id=path,
                node_type=node_type,
                fragment_kind=expression.kind,
                metric=metric,
                elements=elements,
                parameters=parameters,
                reason=_classification_reason(node_type, expression, parameters),
                expression=expression,
            )
        )

    def _collect_special_reserve_blocks(self, scheme: SchemeModel, fragments: list[FragmentAnalysis]) -> None:
        for block in scheme.iter_blocks_recursive(include_pass_through=False):
            params = block.params or {}
            reserve_type = str(params.get("reserve_type", params.get("reserve_kind", ""))).lower()
            block_role = _block_role(params, block.is_subscheme)
            has_k_of_n = block_role == "k_of_n" or ("k_required" in params and "n_total" in params)
            if _truthy(params.get("suppress_manual_review_warning")):
                continue
            if "sliding" not in reserve_type and not has_k_of_n:
                continue
            k_required = _safe_int(params.get("k_required"), default=0)
            n_total = _safe_int(params.get("n_total"), default=0)
            fragments.append(
                FragmentAnalysis(
                    fragment_id=f"P.reserve.{block.block_id}",
                    node_type="sliding_reserve",
                    fragment_kind="reserve_sliding_k_of_n",
                    metric="P",
                    elements=(_safe_symbol(block.name),),
                    parameters={
                        "k_required": k_required,
                        "n_total": n_total,
                        "reserve_type": reserve_type or "sliding",
                        "block_role": block_role,
                    },
                    reason=(
                        "У блока заданы k_required/n_total или признак скользящего резерва; "
                        "нужна проверка по специализированной формуле резерва из библиотеки."
                    ),
                    expression=None,
                )
            )


class FormulaSelector:
    """Select the best library formula and expose unsupported cases."""

    def __init__(self, library: FormulaLibrary | None = None) -> None:
        self.library = library or FormulaLibrary()

    def select(self, fragment: FragmentAnalysis) -> FormulaSelection:
        if fragment.node_type == "mixed_structure":
            candidates = self.library.candidates_for_fragment_kind(fragment.fragment_kind, fragment.metric)
        else:
            candidates = self.library.candidates_for(fragment.node_type, fragment.metric)
        if not candidates:
            return FormulaSelection(
                fragment_id=fragment.fragment_id,
                definition=None,
                candidates=(),
                status="manual_required",
                reason=f"В библиотеке не найдена формула для типа фрагмента {fragment.node_type}, показатель {fragment.metric}.",
            )
        selected = candidates[0]
        status = selected.verification_status
        if selected.manual_review_required:
            status = "manual_required"
        return FormulaSelection(
            fragment_id=fragment.fragment_id,
            definition=selected,
            candidates=candidates,
            status=status,
            reason=f"Выбрана формула {selected.formula_id} для типа фрагмента {fragment.node_type}: {selected.applies_to}",
        )


class FormulaInstantiator:
    """Instantiate general formulas with concrete scheme parameters."""

    def instantiate(
        self,
        fragment: FragmentAnalysis,
        selection: FormulaSelection,
        values: dict[str, float],
        lambda_values: dict[str, float],
        time_horizon: int,
    ) -> InstantiatedFormula:
        definition = selection.definition
        expression = fragment.expression
        if definition is None:
            fallback = expression.render_pretty() if expression is not None else "требуется ручная проверка"
            return InstantiatedFormula(
                fragment_id=fragment.fragment_id,
                formula_id="UNSUPPORTED",
                title="Неподдержанный фрагмент",
                metric=fragment.metric,
                node_type=fragment.node_type,
                verification_status="manual_required",
                source="В библиотеке формул нет подходящего определения.",
                general_formula=fallback,
                instantiated_formula=fallback,
                general_latex=latex_formula_text(fallback),
                instantiated_latex=latex_formula_text(fallback),
                display_latex=latex_formula_text(fallback),
                parameter_substitution=dict(fragment.parameters),
                computable_formula=expression.render_computable() if expression is not None else "",
                numeric_value=expression.evaluate(values) if expression is not None else None,
                explanation=selection.reason,
                manual_review_required=True,
                limitations="Автоматический расчет не обоснован без подходящей формулы в библиотеке.",
            )

        instantiated = expression.render_pretty() if expression is not None else definition.display_formula
        instantiated_latex = expression.render_latex() if expression is not None else definition.display_latex
        computable = expression.render_computable() if expression is not None else definition.computable_formula
        numeric_value = expression.evaluate(values) if expression is not None else None
        parameters = dict(fragment.parameters)
        parameters.update(_lambda_parameters(fragment.elements, lambda_values, time_horizon))
        concrete = _concrete_exponential_formula(fragment, instantiated, lambda_values)
        concrete_latex = _concrete_exponential_formula_latex(fragment, instantiated_latex, lambda_values)
        if concrete:
            parameters["element_substitution"] = concrete
        explanation = (
            f"{fragment.reason} Выбрана формула {definition.formula_id}; "
            f"общий вид: {definition.general_formula}; конкретизация: {instantiated}."
        )
        return InstantiatedFormula(
            fragment_id=fragment.fragment_id,
            formula_id=definition.formula_id,
            title=definition.title,
            metric=fragment.metric,
            node_type=fragment.node_type,
            verification_status=definition.verification_status,
            source=definition.source,
            general_formula=definition.general_formula,
            instantiated_formula=concrete or instantiated,
            general_latex=definition.general_latex,
            instantiated_latex=concrete_latex or instantiated_latex,
            display_latex=definition.display_latex,
            parameter_substitution=parameters,
            computable_formula=computable,
            numeric_value=numeric_value,
            explanation=explanation,
            manual_review_required=definition.manual_review_required,
            limitations=definition.limitations,
        )


class FormulaEvaluator:
    """Evaluate exactly the same structural AST used for displayed formulas."""

    def evaluate(self, scheme: SchemeModel, time_horizon: int) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
        report = build_formula_report(scheme)
        numeric_results = evaluate_formula_for_scheme(scheme, time_horizon=time_horizon)
        p_values, k_values, parameters = _symbol_values_with_parameters(report, time_horizon)
        parameters["_p_values"] = p_values
        parameters["_k_values"] = k_values
        return numeric_results, p_values, parameters


class FormulaGenerationService:
    """Public service for method-library based structural formula generation."""

    def __init__(
        self,
        *,
        analyzer: SchemeAnalyzer | None = None,
        selector: FormulaSelector | None = None,
        instantiator: FormulaInstantiator | None = None,
        evaluator: FormulaEvaluator | None = None,
    ) -> None:
        self.analyzer = analyzer or SchemeAnalyzer()
        self.selector = selector or FormulaSelector()
        self.instantiator = instantiator or FormulaInstantiator()
        self.evaluator = evaluator or FormulaEvaluator()

    def generate(self, scheme: SchemeModel, *, time_horizon: int = 1000) -> FormulaGenerationResult:
        report, analysis = self.analyzer.analyze(scheme)
        numeric_results, p_values, parameter_values = self.evaluator.evaluate(scheme, time_horizon)
        lambda_values = dict(parameter_values.get("_lambda_values", {}))
        selections = tuple(self.selector.select(fragment) for fragment in analysis)
        selection_by_id = {selection.fragment_id: selection for selection in selections}
        instantiated = tuple(
            self.instantiator.instantiate(
                fragment,
                selection_by_id[fragment.fragment_id],
                p_values if fragment.metric == "P" else dict(parameter_values.get("_k_values", {})),
                lambda_values,
                time_horizon,
            )
            for fragment in analysis
        )
        warnings = _warnings_for(report, instantiated, selections)
        steps = _explanation_steps(report, analysis, instantiated, numeric_results)
        return FormulaGenerationResult(
            scheme_name=scheme.name,
            base_report=report,
            analysis=analysis,
            selections=selections,
            instantiated_formulas=instantiated,
            numeric_results=numeric_results,
            symbols=dict(report.symbols),
            parameter_values=parameter_values,
            explanation_steps=steps,
            warnings=warnings,
        )


def _node_type_for_expr(expression: FormulaExpr) -> str:
    if expression.kind == "one":
        return "identity"
    if expression.kind == "symbol":
        return "single_element"
    if expression.kind == "series":
        child_kinds = {child.kind for child in expression.children}
        return "mixed_structure" if child_kinds - {"symbol", "reserve"} else "series_chain"
    if expression.kind == "parallel":
        child_kinds = {child.kind for child in expression.children}
        return "mixed_structure" if child_kinds - {"symbol", "reserve"} else "parallel_group"
    if expression.kind == "reserve":
        return "reserve_group"
    return "unsupported"


def _library_fragment_kind(node_type: str) -> str:
    return {
        "identity": "one",
        "single_element": "symbol",
        "series_chain": "series",
        "parallel_group": "parallel",
        "mixed_structure": "series",
        "reserve_group": "reserve",
        "loaded_reserve": "reserve_loaded_1_of_2",
        "sliding_reserve": "reserve_sliding_k_of_n",
    }.get(node_type, node_type)


def _classification_reason(node_type: str, expression: FormulaExpr, parameters: dict[str, Any]) -> str:
    if node_type == "single_element":
        return "Фрагмент является одиночным расчетным блоком."
    if node_type == "series_chain":
        return f"Фрагмент является последовательной цепочкой: N={parameters.get('N')}."
    if node_type == "parallel_group":
        return f"Фрагмент является параллельной группой: N={parameters.get('N')} ветвей."
    if node_type == "reserve_group":
        return f"Фрагмент является резервированной группой: m={parameters.get('m')} резервных копий."
    if node_type == "mixed_structure":
        return f"Фрагмент смешанный и разбирается рекурсивно; верхний тип AST: {expression.kind}."
    if node_type == "identity":
        return "Фрагмент не содержит активных расчетных блоков."
    return f"Тип фрагмента {expression.kind} не классифицирован."


def _parameters_for_expr(expression: FormulaExpr) -> dict[str, Any]:
    if expression.kind in {"series", "parallel"}:
        return {"N": len(expression.children), "elements": tuple(_ordered_symbols(expression))}
    if expression.kind == "reserve":
        return {"m": expression.reserve_count, "n_total": expression.reserve_count + 1, "symbol": expression.symbol}
    if expression.kind == "symbol":
        return {"symbol": expression.symbol}
    return {}


def _ordered_symbols(expression: FormulaExpr) -> list[str]:
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

    visit(expression)
    return result


def _symbol_values_with_parameters(
    report: GraphFormulaReport,
    time_horizon: int,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    p_values: dict[str, float] = {}
    k_values: dict[str, float] = {}
    parameters: dict[str, Any] = {"t": time_horizon, "_lambda_values": {}}
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
        return
    symbol = _safe_symbol(block.name)
    lam = float(block.params.get("lambda", 0.0) or 0.0)
    tv = float(block.params.get("Tv", 0.0) or 0.0)
    explicit_p = block.params.get("P")
    if explicit_p is not None:
        p_values[symbol] = max(0.0, min(1.0, float(explicit_p)))
    else:
        p_values[symbol] = max(0.0, min(1.0, exp(-lam * time_horizon))) if lam > 0 else 1.0
    explicit_k = block.params.get("Kg", block.params.get("K"))
    if explicit_k is not None:
        k_values[f"K_{symbol}"] = max(0.0, min(1.0, float(explicit_k)))
    elif lam > 0 and tv > 0:
        k_values[f"K_{symbol}"] = max(0.0, min(1.0, 1.0 / (1.0 + lam * tv)))
    else:
        k_values[f"K_{symbol}"] = p_values[symbol]
    parameters.setdefault("_lambda_values", {})[symbol] = lam
    parameters[f"lambda_{symbol}"] = lam
    if tv:
        parameters[f"Tv_{symbol}"] = tv


def _lambda_parameters(elements: tuple[str, ...], lambda_values: dict[str, float], time_horizon: int) -> dict[str, Any]:
    result: dict[str, Any] = {"t": time_horizon}
    for symbol in elements:
        if symbol in lambda_values:
            result[f"lambda_{symbol}"] = lambda_values[symbol]
    return result


def _concrete_exponential_formula(
    fragment: FragmentAnalysis,
    instantiated: str,
    lambda_values: dict[str, float],
) -> str:
    if fragment.metric != "P" or not fragment.elements:
        return ""
    if not all(symbol in lambda_values for symbol in fragment.elements):
        return ""
    substitutions = {symbol: f"exp(-lambda_{symbol} * t)" for symbol in fragment.elements}
    formula = instantiated
    for symbol, replacement in substitutions.items():
        formula = formula.replace(symbol, replacement)
    return formula


def _concrete_exponential_formula_latex(
    fragment: FragmentAnalysis,
    instantiated_latex: str,
    lambda_values: dict[str, float],
) -> str:
    if fragment.metric != "P" or not fragment.elements:
        return ""
    if not all(symbol in lambda_values for symbol in fragment.elements):
        return ""
    formula = instantiated_latex
    for symbol in fragment.elements:
        formula = formula.replace(f"P_{{\\text{{{symbol}}}}}", f"e^{{-\\lambda_{{{symbol}}} t}}")
    return formula


def _warnings_for(
    report: GraphFormulaReport,
    formulas: tuple[InstantiatedFormula, ...],
    selections: tuple[FormulaSelection, ...],
) -> list[str]:
    warnings = list(report.warnings)
    for item in formulas:
        if item.manual_review_required or item.verification_status in {"needs_review", "manual_required"}:
            warnings.append(
                f"{item.formula_id}: статус формулы {item.verification_status}; требуется ручная проверка."
            )
    for selection in selections:
        if selection.definition is None:
            warnings.append(selection.reason)
    return list(dict.fromkeys(warnings))


def _explanation_steps(
    report: GraphFormulaReport,
    analysis: tuple[FragmentAnalysis, ...],
    formulas: tuple[InstantiatedFormula, ...],
    numeric_results: dict[str, float],
) -> list[str]:
    steps = [
        f"Схема проанализирована: расчетных блоков={len(report.used_blocks)}, неиспользованных блоков={len(report.unused_blocks)}.",
    ]
    for fragment in analysis:
        if fragment.node_type == "single_element":
            continue
        steps.append(f"{fragment.fragment_id}: {fragment.reason}")
    for item in formulas:
        if item.node_type == "single_element":
            continue
        steps.append(item.explanation)
    if numeric_results:
        values = ", ".join(f"{key}={value:.8g}" for key, value in numeric_results.items())
        steps.append(f"Численный результат рассчитан по той же конкретизированной AST-формуле: {values}.")
    return steps


def _safe_symbol(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in str(value).strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "E"


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "да"}


def _block_role(params: dict[str, Any] | None, is_subscheme: bool = False) -> str:
    values = dict(params or {})
    if is_subscheme or str(values.get("block_role", "")).lower() == "subscheme":
        return "subscheme"
    role = str(values.get("block_role", "")).lower().strip()
    if role in {"ordinary", "reserve", "k_of_n", "subscheme", "passive"}:
        return role
    if "k_required" in values or "n_total" in values or str(values.get("reserve_type", "")).lower() == "sliding":
        return "k_of_n"
    try:
        if int(float(values.get("reserve_count", 0) or 0)) > 0:
            return "reserve"
    except (TypeError, ValueError):
        pass
    return "ordinary"
