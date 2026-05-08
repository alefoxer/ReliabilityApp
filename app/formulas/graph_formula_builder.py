"""Formula generation engine for reliability block diagrams.

The module converts a serializable ``SchemeModel`` into a normalized graph,
builds an AST for reliability/availability expressions, and renders the same
AST into user text, computable text, structural diagnostics and explanation
steps. UI code should consume ``FormulaInfo`` instead of rebuilding formula
sections independently.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from math import exp, log
from typing import Callable

import sympy as sp

from app.core.rbd_models import BlockModel, FormulaInfo, SchemeModel


PASS_THROUGH_KINDS = {"in", "out", "junction"}


@dataclass(frozen=True)
class FormulaExpr:
    """AST узел формулы. Все представления строятся только из этого дерева."""

    kind: str
    symbol: str = ""
    children: tuple["FormulaExpr", ...] = ()
    reserve_count: int = 0

    @staticmethod
    def one() -> "FormulaExpr":
        return FormulaExpr("one")

    @staticmethod
    def symbol_ref(symbol: str) -> "FormulaExpr":
        return FormulaExpr("symbol", symbol=symbol)

    @staticmethod
    def series(children: list["FormulaExpr"] | tuple["FormulaExpr", ...]) -> "FormulaExpr":
        flat: list[FormulaExpr] = []
        for child in children:
            if child.kind == "one":
                continue
            if child.kind == "series":
                flat.extend(child.children)
            else:
                flat.append(child)
        if not flat:
            return FormulaExpr.one()
        if len(flat) == 1:
            return flat[0]
        return FormulaExpr("series", children=tuple(flat))

    @staticmethod
    def parallel(children: list["FormulaExpr"] | tuple["FormulaExpr", ...]) -> "FormulaExpr":
        # Ветвь с выражением 1 означает безотказный обход; вся параллельная группа равна 1.
        if any(child.kind == "one" for child in children):
            return FormulaExpr.one()
        flat = list(children)
        if not flat:
            return FormulaExpr.one()
        if len(flat) == 1:
            return flat[0]
        return FormulaExpr("parallel", children=tuple(flat))

    @staticmethod
    def reserve(symbol: str, reserve_count: int) -> "FormulaExpr":
        return FormulaExpr("reserve", symbol=symbol, reserve_count=reserve_count)

    def collect_symbols(self) -> set[str]:
        if self.kind in {"symbol", "reserve"}:
            return {self.symbol}
        symbols: set[str] = set()
        for child in self.children:
            symbols.update(child.collect_symbols())
        return symbols

    def to_sympy(self) -> sp.Expr:
        if self.kind == "one":
            return sp.Integer(1)
        if self.kind == "symbol":
            return sp.Symbol(self.symbol)
        if self.kind == "reserve":
            symbol = sp.Symbol(self.symbol)
            return 1 - (1 - symbol) ** (self.reserve_count + 1)
        if self.kind == "series":
            value = sp.Integer(1)
            for child in self.children:
                value *= child.to_sympy()
            return value
        if self.kind == "parallel":
            failed_all = sp.Integer(1)
            for child in self.children:
                failed_all *= 1 - child.to_sympy()
            return 1 - failed_all
        raise ValueError(f"Неизвестный тип AST: {self.kind}")

    def evaluate(self, values: dict[str, float]) -> float:
        if self.kind == "one":
            return 1.0
        if self.kind == "symbol":
            return _clamp_probability(float(values.get(self.symbol, 0.0)))
        if self.kind == "reserve":
            value = _clamp_probability(float(values.get(self.symbol, 0.0)))
            return _clamp_probability(1.0 - (1.0 - value) ** (self.reserve_count + 1))
        if self.kind == "series":
            result = 1.0
            for child in self.children:
                result *= child.evaluate(values)
            return _clamp_probability(result)
        if self.kind == "parallel":
            failed_all = 1.0
            for child in self.children:
                failed_all *= 1.0 - child.evaluate(values)
            return _clamp_probability(1.0 - failed_all)
        raise ValueError(f"Неизвестный тип AST: {self.kind}")

    def render_pretty(self) -> str:
        if self.kind == "one":
            return "1"
        if self.kind == "symbol":
            return self.symbol
        if self.kind == "reserve":
            return f"1 - (1 - {self.symbol})^{self.reserve_count + 1}"
        if self.kind == "series":
            return " · ".join(_wrap_for_series(child) for child in self.children)
        if self.kind == "parallel":
            return "1 - " + "".join(f"(1 - {child.render_pretty()})" for child in self.children)
        raise ValueError(f"Неизвестный тип AST: {self.kind}")

    def render_computable(self) -> str:
        if self.kind == "one":
            return "1"
        if self.kind == "symbol":
            return self.symbol
        if self.kind == "reserve":
            return f"1 - (1 - {self.symbol})**{self.reserve_count + 1}"
        if self.kind == "series":
            return " * ".join(_wrap_for_computable_series(child) for child in self.children)
        if self.kind == "parallel":
            failed = " * ".join(f"(1 - {child.render_computable()})" for child in self.children)
            return f"1 - ({failed})"
        raise ValueError(f"Неизвестный тип AST: {self.kind}")

    def render_latex(self) -> str:
        if self.kind == "one":
            return "1"
        if self.kind == "symbol":
            return _latex_symbol(self.symbol)
        if self.kind == "reserve":
            return f"1 - (1 - {_latex_symbol(self.symbol)})^{{{self.reserve_count + 1}}}"
        if self.kind == "series":
            return r" \cdot ".join(_wrap_for_latex_series(child) for child in self.children)
        if self.kind == "parallel":
            return "1 - " + "".join(f"(1 - {child.render_latex()})" for child in self.children)
        raise ValueError(f"Unknown AST kind: {self.kind}")

    def render_structure(self) -> str:
        if self.kind == "one":
            return "1"
        if self.kind == "symbol":
            return self.symbol
        if self.kind == "reserve":
            return f"Резерв({self.symbol}, всего={self.reserve_count + 1})"
        title = "Последовательно" if self.kind == "series" else "Параллельно"
        return f"{title}(" + ", ".join(child.render_structure() for child in self.children) + ")"


@dataclass(frozen=True)
class NormalizedScheme:
    start_id: str
    end_id: str
    blocks: dict[str, BlockModel]
    forward: dict[str, list[str]]
    active_ids: set[str] = field(default_factory=set)
    unused_ids: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FormulaGenerationResult:
    """Единый источник истины для UI, отчетов, тестов и численного расчета."""

    normalized_scheme: NormalizedScheme
    formula_ast_reliability: FormulaExpr
    formula_ast_availability: FormulaExpr
    symbolic_formula_reliability: str
    symbolic_formula_availability: str
    computable_formula_reliability: str
    computable_formula_availability: str
    used_blocks: list[str]
    unused_blocks: list[str]
    symbols: dict[str, str]
    explanation_steps: list[str]
    warnings: list[str]


def build_formula_for_scheme(scheme: SchemeModel) -> FormulaInfo:
    """Public adapter returning the legacy FormulaInfo object from FormulaPackage."""
    try:
        from app.formulas.formula_package import formula_package_to_info, generate_formula_package

        package = generate_formula_package(scheme=scheme, formula_mode="structural_fallback")
        formula = formula_package_to_info(package)
        try:
            result = build_formula_report(scheme)
            from app.formulas.intelligent_formula_generator import enhance_formula_info

            formula = enhance_formula_info(scheme, formula, base_report=result)
            formula.package = package
        except Exception as exc:
            formula.warnings.append(f"Intelligent formula enrichment is unavailable: {exc}")
        return _hide_manual_review_text_if_requested(scheme, formula)
    except Exception:
        pass

    try:
        result = build_formula_report(scheme)
    except ValueError as exc:
        return _hide_manual_review_text_if_requested(scheme, FormulaInfo(
            text=f"Формула не построена: {exc}",
            is_exact=False,
            note="Проверьте наличие блоков Start/End, отсутствие циклов и корректность соединений.",
            warnings=[str(exc)],
        ))
    except Exception as exc:
        return _hide_manual_review_text_if_requested(scheme, FormulaInfo(
            text="Формула не построена для данной структуры.",
            is_exact=False,
            note=f"Для сложной схемы используйте численный расчет. Техническая причина: {exc}",
            warnings=[str(exc)],
        ))

    text = "\n".join(
        [
            f"Pсист(t) = {result.symbolic_formula_reliability}",
            f"Kг_сист = {result.symbolic_formula_availability.replace(' · ', ' * ')}",
        ]
    )
    computational = "\n".join(
        [
            f"P = {result.computable_formula_reliability}",
            f"Kг = {result.computable_formula_availability}",
        ]
    )
    structural = "\n".join(
        [
            f"P: {result.formula_ast_reliability.render_structure()}",
            f"Kг: {result.formula_ast_availability.render_structure()}",
        ]
    )
    latex = (
        rf"P_{{\text{{сист}}}}(t) = {result.formula_ast_reliability.render_latex()}; "
        rf"K_{{\text{{г,сист}}}} = {result.formula_ast_availability.render_latex()}"
    )
    warning_note = "\n".join(result.warnings)
    formula = FormulaInfo(
        text=text,
        latex=latex,
        is_exact=True,
        note=(
            "Формула построена из единого AST. Формула, вычислительное выражение, "
            "обозначения и пояснение используют один и тот же набор расчетных блоков."
            + (f"\n{warning_note}" if warning_note else "")
        ),
        structural=structural,
        computational=computational,
        steps=result.explanation_steps,
        symbols=result.symbols,
        used_blocks=result.used_blocks,
        unused_blocks=result.unused_blocks,
        warnings=result.warnings,
    )
    try:
        from app.formulas.intelligent_formula_generator import enhance_formula_info

        return _hide_manual_review_text_if_requested(scheme, enhance_formula_info(scheme, formula, base_report=result))
    except Exception as exc:
        formula.warnings.append(f"Интеллектуальный подбор формул недоступен: {exc}")
        return _hide_manual_review_text_if_requested(scheme, formula)


def build_formula_report(scheme: SchemeModel) -> FormulaGenerationResult:
    normalized = normalize_scheme(scheme)
    p_ast = _build_segment(normalized, normalized.start_id, normalized.end_id, "P", set())
    k_ast = _build_segment(normalized, normalized.start_id, normalized.end_id, "K", set())

    used_symbols = sorted(p_ast.collect_symbols() | k_ast.collect_symbols(), key=_natural_sort_key)
    symbol_descriptions = _symbol_descriptions_from_ast(normalized, used_symbols)
    used_blocks = _used_block_names_from_symbols(normalized, _ordered_symbols_from_ast(p_ast))
    explanation = _unique_steps(
        _nested_scheme_steps(normalized, used_symbols)
        + build_formula_explanation(p_ast, symbol_descriptions)
        + build_formula_explanation(k_ast, symbol_descriptions)
    )
    warnings = list(normalized.warnings)
    if not used_symbols:
        explanation = ["Схема содержит только вход и выход: расчетная структура пуста, поэтому Pсист = 1 и Kг_сист = 1."]

    return FormulaGenerationResult(
        normalized_scheme=normalized,
        formula_ast_reliability=p_ast,
        formula_ast_availability=k_ast,
        symbolic_formula_reliability=render_symbolic_formula(p_ast),
        symbolic_formula_availability=render_symbolic_formula(k_ast),
        computable_formula_reliability=render_computable_formula(p_ast),
        computable_formula_availability=render_computable_formula(k_ast),
        used_blocks=used_blocks,
        unused_blocks=_block_names(normalized, normalized.unused_ids),
        symbols=symbol_descriptions,
        explanation_steps=explanation,
        warnings=warnings,
    )


def evaluate_formula_for_scheme(scheme: SchemeModel, time_horizon: int = 1000) -> dict[str, float]:
    result = build_formula_report(scheme)
    p_values = _symbol_values(result.normalized_scheme, "P", lambda block: _block_probability(block, time_horizon), time_horizon)
    k_values = _symbol_values(result.normalized_scheme, "K", _block_availability, time_horizon)
    return {
        "P": result.formula_ast_reliability.evaluate(p_values),
        "Kg": result.formula_ast_availability.evaluate(k_values),
    }


def extract_reachable_subgraph(scheme: SchemeModel) -> NormalizedScheme:
    return normalize_scheme(scheme)


def normalize_scheme(scheme: SchemeModel) -> NormalizedScheme:
    start_blocks = [block for block in scheme.blocks if block.kind == "in"]
    end_blocks = [block for block in scheme.blocks if block.kind == "out"]
    if len(start_blocks) != 1 or len(end_blocks) != 1:
        raise ValueError("для построения формулы нужен ровно один вход и ровно один выход.")

    start = start_blocks[0]
    end = end_blocks[0]
    blocks = {block.block_id: block for block in scheme.blocks}
    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    for connection in scheme.connections:
        if connection.source_id not in blocks or connection.target_id not in blocks:
            continue
        forward[connection.source_id].append(connection.target_id)
        reverse[connection.target_id].append(connection.source_id)

    for targets in forward.values():
        targets.sort(key=lambda block_id: (blocks[block_id].x, blocks[block_id].y, blocks[block_id].name))

    reachable_from_start = _reachable(forward, start.block_id)
    reachable_to_end = _reachable(reverse, end.block_id)
    active_ids = reachable_from_start & reachable_to_end
    calculation_ids = {block.block_id for block in scheme.blocks if block.kind not in PASS_THROUGH_KINDS}
    unused_ids = calculation_ids - active_ids
    manual_review_warnings: list[str] = []
    for block_id in sorted(active_ids, key=lambda item: blocks[item].name):
        block = blocks[block_id]
        if block.kind in PASS_THROUGH_KINDS or _block_role(block) != "k_of_n":
            continue
        if _truthy(block.params.get("suppress_manual_review_warning")):
            continue
        k_required = int(float(block.params.get("k_required", 0) or 0))
        n_total = int(float(block.params.get("n_total", 0) or 0))
        manual_review_warnings.append(
            f"Block {block.name}: k-of-N reserve ({k_required} of {n_total}) uses tabular P/Kg here and requires manual formula verification."
        )
    warnings = [
        f"Блок «{blocks[block_id].name}» не входит в путь от входа к выходу и не включен в формулу."
        for block_id in sorted(unused_ids, key=lambda item: blocks[item].name)
    ] + manual_review_warnings

    if end.block_id not in reachable_from_start:
        raise ValueError("выход не достижим от входа.")

    return NormalizedScheme(
        start_id=start.block_id,
        end_id=end.block_id,
        blocks=blocks,
        forward=dict(forward),
        active_ids=active_ids,
        unused_ids=unused_ids,
        warnings=warnings,
    )


def detect_series_parallel_structure(scheme: SchemeModel, metric: str = "P") -> FormulaExpr:
    normalized = normalize_scheme(scheme)
    return _build_segment(normalized, normalized.start_id, normalized.end_id, metric, set())


def build_reliability_formula(scheme: SchemeModel) -> FormulaExpr:
    return detect_series_parallel_structure(scheme, "P")


def build_availability_formula(scheme: SchemeModel) -> FormulaExpr:
    return detect_series_parallel_structure(scheme, "K")


def render_symbolic_formula(expr: FormulaExpr) -> str:
    return expr.render_pretty()


def render_formula_pretty(expr: FormulaExpr) -> str:
    return render_symbolic_formula(expr)


def render_computable_formula(expr: FormulaExpr) -> str:
    return expr.render_computable()


def render_formula_computable(expr: FormulaExpr) -> str:
    return render_computable_formula(expr)


def collect_symbols_from_ast(expr: FormulaExpr) -> set[str]:
    return expr.collect_symbols()


def evaluate_formula(expr: FormulaExpr, values: dict[str, float]) -> float:
    return expr.evaluate(values)


def build_formula_explanation(expr: FormulaExpr, symbols: dict[str, str]) -> list[str]:
    steps: list[str] = []
    _explain_expr(expr, symbols, steps)
    return _unique_steps(steps)


def _build_segment(
    scheme: NormalizedScheme,
    current_id: str,
    stop_id: str,
    metric: str,
    active_stack: set[str],
) -> FormulaExpr:
    if current_id == stop_id:
        return FormulaExpr.one()
    if current_id in active_stack:
        raise ValueError("в схеме обнаружен цикл; циклические структуры формульным генератором не поддерживаются.")
    if current_id not in scheme.blocks:
        raise ValueError(f"не найден блок {current_id}.")

    active_stack = set(active_stack)
    active_stack.add(current_id)
    block = scheme.blocks[current_id]
    head = _block_metric_expr(block, metric)
    successors = [item for item in scheme.forward.get(current_id, []) if item in scheme.active_ids]
    if not successors:
        raise ValueError(f"у блока «{block.name}» нет расчетного пути к выходу.")

    if len(successors) == 1:
        tail = _build_segment(scheme, successors[0], stop_id, metric, active_stack)
        return FormulaExpr.series([head, tail])

    join_id = _find_parallel_join(scheme, current_id, successors, stop_id)
    branches = [_build_segment(scheme, successor_id, join_id, metric, active_stack) for successor_id in successors]
    tail = _build_segment(scheme, join_id, stop_id, metric, active_stack)
    return FormulaExpr.series([head, FormulaExpr.parallel(branches), tail])


def _block_metric_expr(block: BlockModel, metric: str) -> FormulaExpr:
    if block.kind in PASS_THROUGH_KINDS:
        return FormulaExpr.one()
    if block.is_subscheme and block.nested_scheme is not None:
        nested = build_formula_report(block.nested_scheme)
        return nested.formula_ast_reliability if metric == "P" else nested.formula_ast_availability

    symbol = str(_metric_symbol(block, metric))
    role = _block_role(block)
    reserve_count = int(block.params.get("reserve_count", 0) or 0)
    if role == "reserve" and reserve_count > 0:
        return FormulaExpr.reserve(symbol, reserve_count)
    if reserve_count > 0:
        return FormulaExpr.reserve(symbol, reserve_count)
    return FormulaExpr.symbol_ref(symbol)


def _find_parallel_join(scheme: NormalizedScheme, split_id: str, successors: list[str], stop_id: str) -> str:
    distance_maps = [_distances_to_reachable_nodes(scheme, successor_id, stop_id) for successor_id in successors]
    common = set(distance_maps[0])
    for distances in distance_maps[1:]:
        common &= set(distances)
    common.discard(split_id)
    if not common:
        raise ValueError(f"для разветвления после блока «{scheme.blocks[split_id].name}» не найдена точка слияния.")

    def score(node_id: str) -> tuple[int, int, float, float, str]:
        distances = [distance_map[node_id] for distance_map in distance_maps]
        block = scheme.blocks[node_id]
        return (max(distances), sum(distances), block.x, block.y, block.name)

    return min(common, key=score)


def _distances_to_reachable_nodes(scheme: NormalizedScheme, start_id: str, stop_id: str) -> dict[str, int]:
    distances = {start_id: 0}
    queue: deque[str] = deque([start_id])
    while queue:
        current = queue.popleft()
        if current == stop_id:
            continue
        for successor in scheme.forward.get(current, []):
            if successor not in scheme.active_ids:
                continue
            if successor not in distances:
                distances[successor] = distances[current] + 1
                queue.append(successor)
    return distances


def _reachable(graph: dict[str, list[str]], start_id: str) -> set[str]:
    visited: set[str] = set()
    queue: deque[str] = deque([start_id])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(graph.get(current, []))
    return visited


def _symbol_descriptions_from_ast(scheme: NormalizedScheme, used_symbols: list[str]) -> dict[str, str]:
    used = set(used_symbols)
    descriptions: dict[str, str] = {}
    for block in scheme.blocks.values():
        if block.kind in PASS_THROUGH_KINDS:
            continue
        if block.is_subscheme and block.nested_scheme is not None:
            nested = build_formula_report(block.nested_scheme)
            for symbol, description in nested.symbols.items():
                if symbol in used:
                    descriptions[symbol] = f"{description} (подсхема «{block.name}»)"
            continue
        p_symbol = str(_metric_symbol(block, "P"))
        k_symbol = str(_metric_symbol(block, "K"))
        if p_symbol in used:
            descriptions[p_symbol] = f"вероятность безотказной работы блока «{block.name}»"
        if k_symbol in used:
            descriptions[k_symbol] = f"коэффициент готовности блока «{block.name}»"
    for symbol in used_symbols:
        descriptions.setdefault(symbol, "расчетный символ структуры")
    return descriptions


def _nested_scheme_steps(scheme: NormalizedScheme, used_symbols: list[str]) -> list[str]:
    used = set(used_symbols)
    steps: list[str] = []
    for block in scheme.blocks.values():
        if block.block_id not in scheme.active_ids:
            continue
        if not block.is_subscheme or block.nested_scheme is None:
            continue
        nested = build_formula_report(block.nested_scheme)
        if not (set(nested.symbols) & used):
            continue
        steps.append(
            f"Вложенная схема «{block.name}»: сначала рассчитывается внутренняя структура, затем ее результат используется как показатель блока верхнего уровня."
        )
    return steps


def _used_block_names_from_symbols(scheme: NormalizedScheme, used_symbols: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    used = set(used_symbols)
    for block in scheme.blocks.values():
        if block.kind in PASS_THROUGH_KINDS:
            continue
        if block.is_subscheme and block.nested_scheme is not None:
            nested = build_formula_report(block.nested_scheme)
            if set(nested.symbols) & used:
                for name in nested.used_blocks:
                    full_name = f"{block.name}/{name}"
                    if full_name not in seen:
                        names.append(full_name)
                        seen.add(full_name)
            continue
        if str(_metric_symbol(block, "P")) in used or str(_metric_symbol(block, "K")) in used:
            if block.name not in seen:
                names.append(block.name)
                seen.add(block.name)
    return names


def _ordered_symbols_from_ast(expr: FormulaExpr) -> list[str]:
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


def _block_names(scheme: NormalizedScheme, block_ids: set[str]) -> list[str]:
    return [scheme.blocks[block_id].name for block_id in sorted(block_ids, key=lambda item: scheme.blocks[item].name)]


def _symbol_values(
    scheme: NormalizedScheme,
    metric: str,
    block_value: Callable[[BlockModel], float],
    time_horizon: int,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for block_id in scheme.active_ids:
        block = scheme.blocks[block_id]
        if block.kind in PASS_THROUGH_KINDS:
            continue
        if block.is_subscheme and block.nested_scheme is not None:
            nested = build_formula_report(block.nested_scheme)
            nested_scheme = nested.normalized_scheme
            values.update(_symbol_values(nested_scheme, metric, block_value, time_horizon))
            continue
        values[str(_metric_symbol(block, metric))] = block_value(block)
    return values


def _explain_expr(expr: FormulaExpr, symbols: dict[str, str], steps: list[str]) -> str:
    if expr.kind == "one":
        return "1"
    if expr.kind == "symbol":
        description = symbols.get(expr.symbol, expr.symbol)
        steps.append(f"Элемент {expr.symbol}: {description}.")
        return expr.symbol
    if expr.kind == "reserve":
        steps.append(
            f"Резервирование {expr.symbol}: используется правило 1 - (1 - {expr.symbol})^{expr.reserve_count + 1}."
        )
        return expr.render_pretty()
    child_labels = [_explain_expr(child, symbols, steps) for child in expr.children]
    rendered = expr.render_pretty()
    if expr.kind == "series":
        steps.append(f"Последовательное соединение {'; '.join(child_labels)}: показатели перемножаются → {rendered}.")
    elif expr.kind == "parallel":
        steps.append(f"Параллельное соединение {'; '.join(child_labels)}: 1 минус произведение отказов ветвей → {rendered}.")
    return rendered


def _block_probability(block: BlockModel, time_horizon: int) -> float:
    table_value = _probability_from_time_table(block.params.get("probability_by_time"), time_horizon)
    if table_value is not None:
        return table_value
    if "P" in block.params:
        return _clamp_probability(float(block.params.get("P", 0.0) or 0.0))
    lam = float(block.params.get("lambda", 0.0) or 0.0)
    return _clamp_probability(exp(-lam * time_horizon))


def _block_availability(block: BlockModel) -> float:
    for key in ("Kg", "K"):
        if key in block.params:
            return _clamp_probability(float(block.params.get(key, 0.0) or 0.0))
    lam = float(block.params.get("lambda", 0.0) or 0.0)
    tv = float(block.params.get("Tv", 0.0) or 0.0)
    if lam > 0 and tv > 0:
        return _clamp_probability(1.0 / (1.0 + lam * tv))
    time_horizon = int(block.params.get("t", 1000) or 1000)
    return _block_probability(block, time_horizon)


def _block_role(block: BlockModel) -> str:
    params = dict(block.params or {})
    if block.is_subscheme or str(params.get("block_role", "")).lower() == "subscheme":
        return "subscheme"
    role = str(params.get("block_role", "")).lower().strip()
    if role in {"ordinary", "reserve", "k_of_n", "subscheme", "passive"}:
        return role
    if "k_required" in params or "n_total" in params or str(params.get("reserve_type", "")).lower() == "sliding":
        return "k_of_n"
    try:
        if int(float(params.get("reserve_count", 0) or 0)) > 0:
            return "reserve"
    except (TypeError, ValueError):
        pass
    return "ordinary"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "да"}


def _hide_manual_review_text_if_requested(scheme: SchemeModel, formula: FormulaInfo) -> FormulaInfo:
    if not _truthy(scheme.metadata.get("suppress_manual_review_warnings")):
        return formula
    formula.warnings = [warning for warning in formula.warnings if not _is_manual_review_text(warning)]
    if formula.note:
        lines = [line for line in formula.note.splitlines() if not _is_manual_review_text(line)]
        formula.note = "\n".join(lines)
    _hide_manual_review_text_from_package(getattr(formula, "package", None))
    return formula


def _hide_manual_review_text_from_package(package: object | None) -> None:
    if package is None:
        return
    package.warnings = [warning for warning in package.warnings if not _is_manual_review_text(warning)]
    package.intermediate_formulas = [
        item
        for item in package.intermediate_formulas
        if not _is_manual_review_text(getattr(item, "label", ""))
        and not _is_manual_review_text(getattr(item, "instantiated_formula", ""))
        and not _is_manual_review_text(getattr(item, "display_latex", ""))
    ]


def _is_manual_review_text(text: object) -> bool:
    value = str(text).lower()
    markers = (
        "manual",
        "needs_review",
        "requires manual",
        "ручн",
        "требуется проверка",
        "требует проверки",
    )
    return any(marker in value for marker in markers)


def _metric_symbol(block: BlockModel, metric: str) -> sp.Symbol:
    base_name = _safe_symbol_name(str(block.block_id or block.name))
    if metric == "P":
        return sp.Symbol(base_name)
    return sp.Symbol(f"K_{base_name}")


def _safe_symbol_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "E"


def _wrap_for_series(expr: FormulaExpr) -> str:
    rendered = expr.render_pretty()
    if expr.kind in {"parallel", "series"}:
        return f"({rendered})"
    return rendered


def _wrap_for_computable_series(expr: FormulaExpr) -> str:
    rendered = expr.render_computable()
    if expr.kind in {"parallel", "series"}:
        return f"({rendered})"
    return rendered


def _wrap_for_latex_series(expr: FormulaExpr) -> str:
    rendered = expr.render_latex()
    if expr.kind in {"parallel", "series"}:
        return f"({rendered})"
    return rendered


def _latex_symbol(symbol: str) -> str:
    safe = str(symbol).replace("\\", "").replace("{", "").replace("}", "")
    prefix = "K" if safe.startswith("K_") else "P"
    if prefix == "K":
        safe = safe[2:]
    parts = [part for part in safe.split("_") if part]
    compact = "_".join(parts[:2]) if parts else "E"
    if len(compact) > 14:
        compact = compact[:12] + ".."
    return f"{prefix}_{{\\mathrm{{{compact}}}}}"


def _clamp_probability(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _probability_from_time_table(table: object, time_horizon: float) -> float | None:
    if not isinstance(table, dict):
        return None
    points: list[tuple[float, float]] = []
    for raw_time, raw_probability in table.items():
        try:
            t_value = float(raw_time)
            p_value = _clamp_probability(float(raw_probability))
        except (TypeError, ValueError):
            continue
        if t_value >= 0.0 and p_value > 0.0:
            points.append((t_value, p_value))
    if not points:
        return None
    points = sorted(dict(points).items())
    t = max(float(time_horizon), 0.0)
    for known_t, known_p in points:
        if abs(t - known_t) <= 1e-9:
            return known_p
    if t <= 0.0:
        return 1.0
    anchored = [(0.0, 1.0), *points]
    if t <= anchored[1][0]:
        return _log_linear_probability(anchored[0], anchored[1], t)
    for left, right in zip(anchored[1:], anchored[2:]):
        if left[0] <= t <= right[0]:
            return _log_linear_probability(left, right, t)
    left, right = anchored[-2], anchored[-1]
    return min(_log_linear_probability(left, right, t), right[1])


def _log_linear_probability(left: tuple[float, float], right: tuple[float, float], t: float) -> float:
    left_t, left_p = left
    right_t, right_p = right
    if abs(right_t - left_t) <= 1e-12:
        return _clamp_probability(right_p)
    alpha = (t - left_t) / (right_t - left_t)
    log_p = log(max(left_p, 1e-300)) + alpha * (log(max(right_p, 1e-300)) - log(max(left_p, 1e-300)))
    return _clamp_probability(exp(log_p))


def _unique_steps(steps: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for step in steps:
        if step not in seen:
            result.append(step)
            seen.add(step)
    return result


def _natural_sort_key(value: str) -> list[tuple[int, int | str]]:
    parts: list[tuple[int, int | str]] = []
    token = ""
    for char in value:
        if char.isdigit():
            token += char
        else:
            if token:
                parts.append((0, int(token)))
                token = ""
            parts.append((1, char))
    if token:
        parts.append((0, int(token)))
    return parts
