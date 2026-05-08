"""Scheme analysis and method selection layer.

The selector receives a scheme, reuses the formula builder as the single
source of structural truth, extracts topology features and produces scenarios,
method candidates and a recommended calculation approach for UI and reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from html import escape

from app.formulas.graph_formula_builder import FormulaExpr, FormulaGenerationResult, PASS_THROUGH_KINDS, build_formula_report
from app.core.normative_methods import SUPPORTED_METHODS_BY_CODE, NormativeMethodSpec
from app.core.rbd_models import BlockModel, SchemeModel


STATUS_OK = "подходит"
STATUS_CONDITIONAL = "условно подходит"
STATUS_NO = "не подходит"

MODE_IDENTITY = "тождественная формула"
MODE_TYPICAL = "типовая нормативная формула"
MODE_COMPOSITION = "построение по структуре схемы"
MODE_HYBRID = "типовая формула фрагмента + композиция схемы"

AUTO_IDENTITY = "AUTO.IDENTITY"
AUTO_SINGLE = "AUTO.SINGLE"
AUTO_COMPOSITION = "AUTO.COMPOSITION"


@dataclass(frozen=True)
class SchemeAnalysisResult:
    """Topology features used to classify a reliability block diagram."""

    block_count: int
    connection_count: int
    active_block_count: int
    unused_blocks: list[str]
    has_series: bool
    has_parallel: bool
    has_reserve: bool
    has_nested: bool
    has_repair_data: bool
    max_parallel_width: int
    ast_depth: int
    complexity_score: int
    structure_type: str
    features: tuple[str, ...]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioCandidate:
    id: str
    title: str
    status: str
    reason: str
    priority: int = 0


@dataclass(frozen=True)
class MethodCandidate:
    method_id: str
    title: str
    status: str
    reason: str
    formula_mode: str
    priority: int = 0
    source: str = ""
    limitations: str = ""


@dataclass(frozen=True)
class MethodSelectionResult:
    """Single result object for UI, reports and tests."""

    analysis: SchemeAnalysisResult
    scenarios: list[ScenarioCandidate]
    methods: list[MethodCandidate]
    recommended_method: MethodCandidate
    recommended_scenario: ScenarioCandidate | None
    formula_mode: str
    explanation: str
    formula_report: FormulaGenerationResult

    def suitable_methods(self) -> list[MethodCandidate]:
        return [item for item in self.methods if item.status in {STATUS_OK, STATUS_CONDITIONAL}]

    def to_plain_text(self) -> str:
        return format_method_selection_text(self)


def select_method_for_scheme(scheme: SchemeModel) -> MethodSelectionResult:
    """Analyze a scheme and select the most appropriate calculation approach."""
    formula_report = _selection_formula_report(build_formula_report(scheme))
    analysis = analyze_formula_report(formula_report, scheme)
    scenarios = build_scenario_candidates(analysis)
    methods = build_method_candidates(analysis)
    recommended_method = recommend_method(methods)
    recommended_scenario = scenarios[0] if scenarios else None
    explanation = build_recommendation_explanation(analysis, recommended_method)
    return MethodSelectionResult(
        analysis=analysis,
        scenarios=scenarios,
        methods=methods,
        recommended_method=recommended_method,
        recommended_scenario=recommended_scenario,
        formula_mode=recommended_method.formula_mode,
        explanation=explanation,
        formula_report=formula_report,
    )


def _selection_formula_report(report: FormulaGenerationResult) -> FormulaGenerationResult:
    """Keep method selection focused on the primary reliability expression.

    The full formula report intentionally contains both P(t) and Kг symbols for
    exports and the formula window. Method selection classifies the topology by
    the reliability AST, so its symbol list should mirror that primary formula.
    """
    reliability_symbols = _ordered_symbols(report.formula_ast_reliability)
    filtered_symbols = {
        symbol: report.symbols[symbol]
        for symbol in reliability_symbols
        if symbol in report.symbols
    }
    return replace(report, symbols=filtered_symbols)


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


def select_methods_for_scheme(scheme: SchemeModel) -> MethodSelectionResult:
    """Backward compatible alias for older UI code."""
    return select_method_for_scheme(scheme)


def analyze_scheme(scheme: SchemeModel) -> SchemeAnalysisResult:
    return analyze_formula_report(build_formula_report(scheme), scheme)


def analyze_formula_report(formula_report: FormulaGenerationResult, scheme: SchemeModel) -> SchemeAnalysisResult:
    expr = formula_report.formula_ast_reliability
    active_blocks = _active_blocks(formula_report)
    stats = _collect_ast_stats(expr)
    has_nested = any(block.is_subscheme for block in active_blocks)
    has_repair_data = any(_has_repair_params(block) for block in active_blocks)
    has_reserve = stats.has_reserve or any(_is_reserve_like(block) for block in active_blocks)
    features = _features(stats, active_blocks, has_reserve, has_nested, has_repair_data)
    block_count = len(formula_report.used_blocks)
    return SchemeAnalysisResult(
        block_count=block_count,
        connection_count=len(scheme.connections),
        active_block_count=len(active_blocks),
        unused_blocks=formula_report.unused_blocks,
        has_series=stats.has_series,
        has_parallel=stats.has_parallel,
        has_reserve=has_reserve,
        has_nested=has_nested,
        has_repair_data=has_repair_data,
        max_parallel_width=stats.max_parallel_width,
        ast_depth=stats.depth,
        complexity_score=_complexity_score(block_count, stats, has_nested),
        structure_type=_structure_type(block_count, stats.has_series, stats.has_parallel, has_reserve, has_nested),
        features=features,
        warnings=formula_report.warnings,
    )


def build_scenario_candidates(analysis: SchemeAnalysisResult) -> list[ScenarioCandidate]:
    scenarios: list[ScenarioCandidate] = []
    if analysis.block_count == 0:
        scenarios.append(
            ScenarioCandidate(
                "empty",
                "Пустая расчетная структура",
                STATUS_OK,
                "Между входом и выходом нет расчетных блоков: Pсист=1 и Kг=1.",
                120,
            )
        )
        return scenarios

    if analysis.block_count == 1:
        scenarios.append(
            ScenarioCandidate(
                "single",
                "Один расчетный элемент",
                STATUS_OK,
                "Система сводится к одному блоку; итоговая формула равна показателю этого блока.",
                115,
            )
        )

    if analysis.has_series and not analysis.has_parallel and not analysis.has_reserve:
        scenarios.append(
            ScenarioCandidate(
                "series",
                "Последовательная структура",
                STATUS_OK,
                "Все расчетные блоки лежат в единой цепочке от входа к выходу.",
                110,
            )
        )

    if analysis.has_parallel and not analysis.has_series and not analysis.has_reserve:
        scenarios.append(
            ScenarioCandidate(
                "parallel",
                "Параллельная структура",
                STATUS_OK,
                f"Обнаружена параллельная группа шириной до {analysis.max_parallel_width} ветвей.",
                105,
            )
        )

    if analysis.has_reserve:
        scenarios.append(
            ScenarioCandidate(
                "reserve",
                "Резервированная структура",
                STATUS_OK,
                "В расчетных блоках есть параметр резервирования, поэтому доступна модель резервной группы.",
                115,
            )
        )

    if analysis.has_series and analysis.has_parallel:
        scenarios.append(
            ScenarioCandidate(
                "mixed",
                "Смешанная последовательно-параллельная структура",
                STATUS_OK,
                "В схеме одновременно присутствуют последовательные участки и параллельные ветви.",
                108,
            )
        )

    if analysis.has_nested:
        scenarios.append(
            ScenarioCandidate(
                "nested",
                "Вложенная составная схема",
                STATUS_OK,
                "Есть блоки-подсхемы; формула строится рекурсивно с подстановкой внутренних формул.",
                100,
            )
        )

    scenarios.append(
        ScenarioCandidate(
            "composition",
            "Композиционное построение общей формулы",
            STATUS_OK,
            "Формула может быть построена напрямую по AST структуры: серия, параллель, резерв и вложенность.",
            90,
        )
    )
    return sorted(scenarios, key=lambda item: item.priority, reverse=True)


def build_method_candidates(analysis: SchemeAnalysisResult) -> list[MethodCandidate]:
    candidates: list[MethodCandidate] = []
    candidates.extend(_automatic_candidates(analysis))

    for code in sorted(SUPPORTED_METHODS_BY_CODE, key=_method_sort_key):
        spec = SUPPORTED_METHODS_BY_CODE[code]
        candidates.append(_candidate_for_spec(spec, analysis))

    return sorted(candidates, key=lambda item: item.priority, reverse=True)


def recommend_method(methods: list[MethodCandidate]) -> MethodCandidate:
    usable = [item for item in methods if item.status in {STATUS_OK, STATUS_CONDITIONAL}]
    return max(usable or methods, key=lambda item: item.priority)


def build_recommendation_explanation(analysis: SchemeAnalysisResult, method: MethodCandidate) -> str:
    if method.method_id == AUTO_IDENTITY:
        return "Схема содержит только вход и выход, поэтому расчетная структура не снижает надежность: применяется Pсист=1 и Kг=1."
    if method.method_id == AUTO_SINGLE:
        return "Схема содержит один расчетный блок, поэтому итоговая формула равна показателю этого блока без дополнительной композиции."
    if method.method_id == AUTO_COMPOSITION:
        return (
            f"Рекомендуется композиционное построение, потому что структура распознана как «{analysis.structure_type}». "
            "Этот режим использует фактические связи схемы и не подгоняет сложную топологию под один частный шаблон."
        )
    return (
        f"Рекомендуется {method.method_id}, потому что признаки схемы соответствуют области применимости метода: "
        f"{method.reason}"
    )


def format_method_selection_html(result: MethodSelectionResult) -> str:
    analysis = result.analysis
    recommended_label = _public_method_label(result.recommended_method)
    scenarios = _rows(
        ("Сценарий", "Статус", "Почему применим"),
        ((item.title, item.status, item.reason) for item in result.scenarios),
    )
    suitable = _rows(
        ("Метод", "Статус", "Режим формулы", "Обоснование"),
        (
            (_public_method_label(item), item.status, item.formula_mode, item.reason)
            for item in result.suitable_methods()
        ),
    )
    rejected = _rows(
        ("Метод", "Причина"),
        (
            (_public_method_label(item), item.reason)
            for item in result.methods
            if item.status == STATUS_NO
        ),
    )
    features = ", ".join(analysis.features) if analysis.features else "без специальных признаков"
    warnings = ""
    if analysis.warnings or analysis.unused_blocks:
        warning_items = list(analysis.warnings)
        warning_items.extend(f"Блок «{name}» не входит в путь от входа к выходу и не включен в формулу." for name in analysis.unused_blocks)
        warnings = "<h4>Комментарии и предупреждения</h4><ul>" + "".join(f"<li>{escape(item)}</li>" for item in warning_items) + "</ul>"

    rejected_block = ""
    if rejected != "<p>Нет данных.</p>":
        rejected_block = "<h4>Методы, которые не подходят для этой схемы</h4>" + rejected

    return (
        "<div class='method-selection'>"
        "<h3>Анализ схемы и выбор методики</h3>"
        f"<p><b>Тип структуры:</b> {escape(analysis.structure_type)}<br>"
        f"<b>Расчетных блоков:</b> {analysis.block_count}; <b>связей:</b> {analysis.connection_count}; "
        f"<b>сложность:</b> {analysis.complexity_score}<br>"
        f"<b>Признаки:</b> {escape(features)}</p>"
        "<h4>Рекомендуемый метод</h4>"
        f"<p><b>{escape(recommended_label)}</b><br>"
        f"Режим формулы: {escape(result.formula_mode)}<br>"
        f"{escape(result.explanation)}</p>"
        "<h4>Подходящие сценарии</h4>"
        f"{scenarios}"
        "<h4>Подходящие методы</h4>"
        f"{suitable}"
        f"{rejected_block}"
        f"{warnings}"
        "</div>"
    )


def format_method_selection_text(result: MethodSelectionResult) -> str:
    analysis = result.analysis
    recommended_label = _public_method_label(result.recommended_method)
    lines = [
        "Анализ схемы и выбор методики",
        f"Тип структуры: {analysis.structure_type}",
        f"Расчетных блоков: {analysis.block_count}",
        f"Связей: {analysis.connection_count}",
        f"Признаки: {', '.join(analysis.features) if analysis.features else 'без специальных признаков'}",
        "",
        "Рекомендуемый метод:",
        recommended_label,
        f"Режим формулы: {result.formula_mode}",
        result.explanation,
        "",
        "Подходящие сценарии:",
    ]
    lines.extend(f"- [{item.status}] {item.title}: {item.reason}" for item in result.scenarios)
    lines.extend(["", "Подходящие методы:"])
    lines.extend(
        f"- [{item.status}] {_public_method_label(item)}. {item.reason}"
        for item in result.suitable_methods()
    )
    rejected = [item for item in result.methods if item.status == STATUS_NO]
    if rejected:
        lines.extend(["", "Не подходят:"])
        lines.extend(f"- {_public_method_label(item)}: {item.reason}" for item in rejected)
    if analysis.warnings or analysis.unused_blocks:
        lines.extend(["", "Комментарии и предупреждения:"])
        lines.extend(f"- {item}" for item in analysis.warnings)
        lines.extend(f"- Блок «{name}» не входит в путь от входа к выходу и не включен в формулу." for name in analysis.unused_blocks)
    return "\n".join(lines)


def _public_method_label(method: MethodCandidate) -> str:
    if method.method_id.startswith("AUTO."):
        return method.title
    return f"{method.method_id}: {method.title}"


@dataclass
class _AstStats:
    has_series: bool = False
    has_parallel: bool = False
    has_reserve: bool = False
    max_parallel_width: int = 0
    depth: int = 1


def _collect_ast_stats(expr: FormulaExpr, depth: int = 1) -> _AstStats:
    stats = _AstStats(depth=depth)
    if expr.kind == "series":
        stats.has_series = True
    if expr.kind == "parallel":
        stats.has_parallel = True
        stats.max_parallel_width = len(expr.children)
    if expr.kind == "reserve":
        stats.has_reserve = True
    for child in expr.children:
        child_stats = _collect_ast_stats(child, depth + 1)
        stats.has_series = stats.has_series or child_stats.has_series
        stats.has_parallel = stats.has_parallel or child_stats.has_parallel
        stats.has_reserve = stats.has_reserve or child_stats.has_reserve
        stats.max_parallel_width = max(stats.max_parallel_width, child_stats.max_parallel_width)
        stats.depth = max(stats.depth, child_stats.depth)
    return stats


def _active_blocks(report: FormulaGenerationResult) -> list[BlockModel]:
    return [
        block
        for block_id, block in report.normalized_scheme.blocks.items()
        if block_id in report.normalized_scheme.active_ids and block.kind not in PASS_THROUGH_KINDS
    ]


def _reserve_count(block: BlockModel) -> int:
    try:
        return int(block.params.get("reserve_count", 0))
    except (TypeError, ValueError):
        return 0


def _is_reserve_like(block: BlockModel) -> bool:
    role = str(block.params.get("block_role", "")).lower().strip()
    if role in {"reserve", "k_of_n"}:
        return True
    if "k_required" in block.params or "n_total" in block.params:
        return True
    return _reserve_count(block) > 0


def _has_repair_params(block: BlockModel) -> bool:
    keys = {"Tv", "tv", "t_v", "t_v1", "t_v2", "repair_time"}
    return any(key in block.params for key in keys)


def _features(
    stats: _AstStats,
    blocks: list[BlockModel],
    has_reserve: bool,
    has_nested: bool,
    has_repair_data: bool,
) -> tuple[str, ...]:
    result: list[str] = []
    if stats.has_series:
        result.append("последовательные участки")
    if stats.has_parallel:
        result.append("параллельные ветви")
    if has_reserve:
        result.append("резервирование")
    if has_nested:
        result.append("вложенные подсхемы")
    if has_repair_data:
        result.append("параметры восстановления")
    if len(blocks) > 20:
        result.append("крупная схема")
    return tuple(result)


def _complexity_score(block_count: int, stats: _AstStats, has_nested: bool) -> int:
    score = block_count + stats.depth * 2 + stats.max_parallel_width
    if stats.has_series:
        score += 2
    if stats.has_parallel:
        score += 4
    if stats.has_reserve:
        score += 4
    if has_nested:
        score += 6
    return score


def _structure_type(block_count: int, has_series: bool, has_parallel: bool, has_reserve: bool, has_nested: bool) -> str:
    if block_count == 0:
        return "пустая расчетная структура"
    if block_count == 1:
        return "один расчетный элемент"
    if has_reserve and not has_series and not has_parallel:
        return "резервированная структура"
    if has_series and not has_parallel and not has_reserve:
        return "последовательная структура"
    if has_parallel and not has_series and not has_reserve:
        return "параллельная структура"
    tags = []
    if has_series:
        tags.append("последовательная")
    if has_parallel:
        tags.append("параллельная")
    if has_reserve:
        tags.append("резервированная")
    if has_nested:
        tags.append("вложенная")
    return "смешанная " + "-".join(tags) + " структура"


def _automatic_candidates(analysis: SchemeAnalysisResult) -> list[MethodCandidate]:
    if analysis.block_count == 0:
        return [
            MethodCandidate(
                AUTO_IDENTITY,
                "Тождественная формула пустой расчетной структуры",
                STATUS_OK,
                "Нет расчетных блоков между входом и выходом; надежность структуры равна единице.",
                MODE_IDENTITY,
                140,
                "Граничный случай структурной схемы надежности.",
            )
        ]
    if analysis.block_count == 1:
        return [
            MethodCandidate(
                AUTO_SINGLE,
                "Формула одного расчетного блока",
                STATUS_OK,
                "Структура содержит один блок; итоговый показатель равен показателю блока.",
                MODE_COMPOSITION,
                125,
                "Композиционное правило для вырожденной структуры из одного элемента.",
            )
        ]
    priority = 130 if (analysis.has_series and analysis.has_parallel or analysis.has_nested) else 95
    if analysis.has_reserve:
        priority = max(priority, 105)
    return [
        MethodCandidate(
            AUTO_COMPOSITION,
            "Формула по структуре схемы",
            STATUS_OK,
            "Использует фактическую топологию схемы: последовательные участки, параллельные ветви, резерв и вложенные подсхемы.",
            MODE_COMPOSITION,
            priority,
            "Правила структурных схем надежности: произведение для серии, дополнение отказов для параллели, рекурсивная композиция.",
        )
    ]


def _candidate_for_spec(spec: NormativeMethodSpec, analysis: SchemeAnalysisResult) -> MethodCandidate:
    code = spec.code
    status = STATUS_NO
    reason = "Требует специальных условий, которые не распознаны в текущей графической схеме."
    mode = MODE_TYPICAL
    priority = 10

    if code == "F1.1":
        if analysis.block_count > 0 and analysis.has_series and not analysis.has_parallel and not analysis.has_reserve:
            status = STATUS_OK
            reason = "Схема является последовательной цепочкой независимых невосстанавливаемых элементов."
            priority = 135
        elif analysis.block_count == 1:
            status = STATUS_CONDITIONAL
            reason = "Один блок можно рассматривать как частный случай последовательной структуры."
            priority = 90
        else:
            reason = "Метод F1.1 применим к чистому последовательному соединению; в схеме есть другие топологические признаки."
    elif code == "F1.2":
        if analysis.has_reserve:
            status = STATUS_OK
            reason = "В схеме есть явный параметр резервирования; применима методика резервированной невосстанавливаемой группы."
            mode = MODE_HYBRID
            priority = 110 if analysis.has_repair_data else 132
        elif analysis.has_parallel and not analysis.has_series:
            status = STATUS_CONDITIONAL
            reason = "Параллельная группа может быть интерпретирована как резервирование после выбора сценария cat3."
            priority = 80
        elif analysis.has_parallel:
            status = STATUS_CONDITIONAL
            reason = "Метод может применяться локально к резервному фрагменту, но не ко всей смешанной схеме целиком."
            mode = MODE_HYBRID
            priority = 55
        else:
            reason = "Нет признаков резервирования или параллельной резервной группы."
    elif code == "F1.3":
        if analysis.has_reserve:
            status = STATUS_CONDITIONAL
            reason = "Подходит только если резерв реализован как дублирование с переключателем и задана интенсивность отказов переключателя."
            priority = 60
        else:
            reason = "Не обнаружена структура дублирования с переключателем."
    elif code in {"F1.4", "F1.5", "F2.3", "F6.1", "F6.2", "F6.3", "F7.1", "F7.2"}:
        if analysis.has_parallel:
            status = STATUS_CONDITIONAL
            reason = "Метод связан с мажоритарными/структурными группами; требуется явно задать параметры r, m и порог работоспособности."
            priority = 48
        else:
            reason = "Не обнаружена мажоритарная или многоуровневая структурная группа."
    elif code == "F2.1":
        if analysis.has_repair_data and not analysis.has_reserve:
            status = STATUS_CONDITIONAL
            reason = "Есть параметры восстановления; метод применим при интерпретации элементов как восстанавливаемых."
            priority = 70
        else:
            reason = "Для метода нужны параметры восстановления элементов и соответствующий режим эксплуатации."
    elif code == "F2.2":
        if analysis.has_reserve and analysis.has_repair_data:
            status = STATUS_OK
            reason = "Есть резервирование и параметры восстановления; подходит резерв с восстановлением."
            priority = 136
        elif analysis.has_reserve:
            status = STATUS_CONDITIONAL
            reason = "Есть резервирование, но для полного применения нужны времена восстановления."
            priority = 65
        else:
            reason = "Не обнаружено резервирование с восстановлением."
    elif code in {"F2.4", "F2.5", "F3.1", "F4.1", "F5.1"}:
        reason = "Метод описывает специальные режимы контроля, обнаружения или допустимого простоя, которые не определяются одной топологией схемы."

    return MethodCandidate(
        code,
        spec.title,
        status,
        reason,
        mode,
        priority,
        spec.source,
        spec.limitations,
    )


def _method_sort_key(code: str) -> tuple[int, int]:
    try:
        group, number = code.replace("F", "").split(".")
        return int(group), int(number)
    except ValueError:
        return 99, 99


def _rows(headers: tuple[str, ...], rows: object) -> str:
    body = list(rows)
    if not body:
        return "<p>Нет данных.</p>"
    header_html = "".join(f"<th>{escape(title)}</th>" for title in headers)
    row_html = ""
    for row in body:
        row_html += "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
    return f"<table border='1' cellspacing='0' cellpadding='5'><thead><tr>{header_html}</tr></thead><tbody>{row_html}</tbody></table>"
