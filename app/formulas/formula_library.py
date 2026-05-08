"""Structured formula library for scheme-based reliability generation.

The definitions here are intentionally conservative: they describe formulas
implemented and used by the project, without pretending to be external GOST
clauses. Real standards can be added later by filling ``source`` with an exact
document reference and adding stricter applicability predicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.formulas.formula_rendering import latex_formula_text


@dataclass(frozen=True, slots=True)
class FormulaDefinition:
    """One selectable formula from the project method library."""

    formula_id: str
    title: str
    source: str
    formula_type: str
    metric: str
    fragment_kind: str
    applies_to: str
    applicability: str
    limitations: str
    parameters: tuple[str, ...]
    parameter_docs: dict[str, str]
    general_formula: str
    display_formula: str
    computable_formula: str
    priority: int = 0
    examples: tuple[str, ...] = field(default_factory=tuple)
    verification_status: str = "project_method"
    source_type: str = "project_method"
    manual_review_required: bool = False
    general_latex: str = ""
    display_latex: str = ""

    def __post_init__(self) -> None:
        if not self.general_latex:
            object.__setattr__(self, "general_latex", latex_formula_text(self.general_formula))
        if not self.display_latex:
            object.__setattr__(self, "display_latex", latex_formula_text(self.display_formula))


PROJECT_SOURCE = (
    "Методическая формула проекта: реализованное правило структурных схем "
    "надежности. Не является самостоятельной ссылкой на ГОСТ без добавления "
    "точного нормативного документа."
)


FORMULA_LIBRARY: dict[str, FormulaDefinition] = {
    "STRUCT.IDENTITY.P": FormulaDefinition(
        formula_id="STRUCT.IDENTITY.P",
        title="Пустая расчетная структура",
        source=PROJECT_SOURCE,
        formula_type="тождественная формула",
        metric="P",
        fragment_kind="one",
        applies_to="Схема без расчетных блоков между входом и выходом.",
        applicability="Используется только для граничного случая: вход напрямую соединен с выходом.",
        limitations="Не описывает реальные элементы, а фиксирует отсутствие влияющих блоков.",
        parameters=(),
        parameter_docs={},
        general_formula="Pсист(t) = 1",
        display_formula="Pсист(t) = 1",
        computable_formula="1",
        priority=100,
    ),
    "STRUCT.ELEMENT.P": FormulaDefinition(
        formula_id="STRUCT.ELEMENT.P",
        title="Одиночный элемент",
        source=PROJECT_SOURCE,
        formula_type="элементная формула",
        metric="P",
        fragment_kind="symbol",
        applies_to="Один расчетный блок схемы.",
        applicability="Если для блока задана интенсивность отказов λ, значение P(t) вычисляется как exp(-λt); иначе используется заданный символ блока.",
        limitations="Для разных законов распределения отказов требуется отдельная формула элемента.",
        parameters=("P_i", "lambda_i", "t"),
        parameter_docs={
            "P_i": "вероятность безотказной работы i-го блока",
            "lambda_i": "интенсивность отказов i-го блока, 1/ч",
            "t": "время работы, ч",
        },
        general_formula="P_i(t) = exp(-λ_i · t)",
        display_formula="P_i(t) = e^(-λ_i · t)",
        computable_formula="exp(-lambda_i * t)",
        priority=90,
    ),
    "STRUCT.ELEMENT.K": FormulaDefinition(
        formula_id="STRUCT.ELEMENT.K",
        title="Коэффициент готовности одиночного элемента",
        source=PROJECT_SOURCE,
        formula_type="элементная формула",
        metric="Kг",
        fragment_kind="symbol",
        applies_to="Один расчетный блок с заданным Kг или параметрами λ и Tв.",
        applicability="Если Kг задан явно, используется это значение; при наличии λ и Tв применяется Kг = 1/(1+λTв).",
        limitations="Для сложных восстановительных режимов требуется отдельная методика F2/F7.",
        parameters=("K_i", "lambda_i", "Tв_i"),
        parameter_docs={
            "K_i": "коэффициент готовности i-го блока",
            "lambda_i": "интенсивность отказов i-го блока, 1/ч",
            "Tв_i": "среднее время восстановления i-го блока, ч",
        },
        general_formula="K_i = 1 / (1 + λ_i · Tв_i)",
        display_formula="K_i = 1 / (1 + λ_i · Tв_i)",
        computable_formula="1 / (1 + lambda_i * Tv_i)",
        priority=90,
    ),
    "STRUCT.SERIES.P": FormulaDefinition(
        formula_id="STRUCT.SERIES.P",
        title="Последовательное соединение",
        source=PROJECT_SOURCE,
        formula_type="структурная композиция",
        metric="P",
        fragment_kind="series",
        applies_to="Фрагмент, где отказ любого элемента приводит к отказу фрагмента.",
        applicability="Независимые блоки соединены последовательно в расчетном пути.",
        limitations="Не учитывает общие причины отказов и зависимые отказы.",
        parameters=("N", "P_i"),
        parameter_docs={
            "N": "количество блоков или подфрагментов в последовательной группе",
            "P_i": "вероятность безотказной работы i-го блока или подфрагмента",
        },
        general_formula="Pсер(t) = ∏_{i=1}^{N} P_i(t)",
        display_formula="Pсер(t) = P_1(t) · P_2(t) · ... · P_N(t)",
        computable_formula="prod(P_i for i in 1..N)",
        priority=120,
        examples=("Для B1, B2, B3: P = B1 · B2 · B3",),
    ),
    "STRUCT.PARALLEL.P": FormulaDefinition(
        formula_id="STRUCT.PARALLEL.P",
        title="Параллельное соединение",
        source=PROJECT_SOURCE,
        formula_type="структурная композиция",
        metric="P",
        fragment_kind="parallel",
        applies_to="Фрагмент с независимыми ветвями, где достаточно работоспособности хотя бы одной ветви.",
        applicability="Ветви имеют общую точку разветвления и общую точку слияния.",
        limitations="Не учитывает зависимые отказы ветвей и общий отказ узла разветвления/слияния.",
        parameters=("N", "P_i"),
        parameter_docs={
            "N": "количество параллельных ветвей",
            "P_i": "вероятность безотказной работы i-й ветви",
        },
        general_formula="Pпар(t) = 1 - ∏_{i=1}^{N}(1 - P_i(t))",
        display_formula="Pпар(t) = 1 - (1-P_1)(1-P_2)...(1-P_N)",
        computable_formula="1 - prod(1 - P_i for i in 1..N)",
        priority=120,
        examples=("Для B1, B2: P = 1 - (1-B1)(1-B2)",),
    ),
    "STRUCT.RESERVE.P": FormulaDefinition(
        formula_id="STRUCT.RESERVE.P",
        title="Резервирование одинакового блока",
        source=PROJECT_SOURCE,
        formula_type="структурная композиция",
        metric="P",
        fragment_kind="reserve",
        applies_to="Блок с параметром reserve_count, трактуемый как основной элемент плюс одинаковые резервные копии.",
        applicability="Все копии блока считаются независимыми и имеют одинаковую вероятность P_i.",
        limitations="MVP резервирования: разные параметры резервных элементов и переключатель не раскрываются без выбора отдельной методики.",
        parameters=("m", "P_i"),
        parameter_docs={
            "m": "число резервных копий; всего элементов m+1",
            "P_i": "вероятность безотказной работы основного/резервного одинакового элемента",
        },
        general_formula="Pрез(t) = 1 - (1 - P_i(t))^(m+1)",
        display_formula="Pрез(t) = 1 - (1 - P_i)^(m+1)",
        computable_formula="1 - (1 - P_i)**(m + 1)",
        priority=115,
    ),
    "STRUCT.SERIES.K": FormulaDefinition(
        formula_id="STRUCT.SERIES.K",
        title="Последовательное соединение для коэффициента готовности",
        source=PROJECT_SOURCE,
        formula_type="структурная композиция",
        metric="Kг",
        fragment_kind="series",
        applies_to="Последовательная группа независимых элементов.",
        applicability="Используется принятая в проекте независимая модель готовности.",
        limitations="Для ремонтных зависимостей нужна отдельная восстановительная методика.",
        parameters=("N", "K_i"),
        parameter_docs={"N": "число элементов", "K_i": "коэффициент готовности i-го элемента"},
        general_formula="Kг,сер = ∏_{i=1}^{N} K_i",
        display_formula="Kг,сер = K_1 · K_2 · ... · K_N",
        computable_formula="prod(K_i for i in 1..N)",
        priority=100,
    ),
    "STRUCT.PARALLEL.K": FormulaDefinition(
        formula_id="STRUCT.PARALLEL.K",
        title="Параллельное соединение для коэффициента готовности",
        source=PROJECT_SOURCE,
        formula_type="структурная композиция",
        metric="Kг",
        fragment_kind="parallel",
        applies_to="Параллельная группа независимых ветвей.",
        applicability="Используется принятая в проекте независимая модель готовности.",
        limitations="Для ремонтных зависимостей нужна отдельная восстановительная методика.",
        parameters=("N", "K_i"),
        parameter_docs={"N": "число ветвей", "K_i": "коэффициент готовности i-й ветви"},
        general_formula="Kг,пар = 1 - ∏_{i=1}^{N}(1 - K_i)",
        display_formula="Kг,пар = 1 - (1-K_1)(1-K_2)...(1-K_N)",
        computable_formula="1 - prod(1 - K_i for i in 1..N)",
        priority=100,
    ),
    "STRUCT.EQUIVALENT.T0": FormulaDefinition(
        formula_id="STRUCT.EQUIVALENT.T0",
        title="Эквивалентная средняя наработка по суммарной интенсивности отказов",
        source=PROJECT_SOURCE,
        formula_type="показатель результата",
        metric="T0",
        fragment_kind="scheme",
        applies_to="Расчетная схема, для активных блоков которой заданы интенсивности отказов λ.",
        applicability="Используется как согласованная с текущим расчетом оценка T0: T0 = 1 / Σλi.",
        limitations="Это эквивалентная оценка по активным блокам схемы. Для сложных восстановительных и резервированных режимов следует использовать специализированные методики F2/F7.",
        parameters=("lambda_i",),
        parameter_docs={
            "lambda_i": "интенсивность отказов i-го активного блока схемы, 1/ч",
        },
        general_formula="T0 = 1 / Σ λ_i",
        display_formula="T0 = 1 / (λ_1 + λ_2 + ... + λ_N)",
        computable_formula="1 / sum(lambda_i)",
        priority=80,
        examples=("Для B1 и B2: T0 = 1 / (λ_B1 + λ_B2)",),
    ),
}

FORMULA_LIBRARY.update(
    {
        "DOC.LOADED_RESERVE_1_1.P": FormulaDefinition(
            formula_id="DOC.LOADED_RESERVE_1_1.P",
            title="Нагруженный резерв: один основной и один резервный элемент",
            source=(
                "Заготовка формулы из внешнего инженерного документа. Извлеченную "
                "формулу нужно сверить с первоисточником перед использованием."
            ),
            formula_type="заготовка внешней методики",
            metric="P",
            fragment_kind="reserve_loaded_1_of_2",
            applies_to="Нагруженный резерв, где достаточно одного работоспособного элемента из двух одинаковых элементов.",
            applicability="Только после ручной проверки импортированного текста формулы.",
            limitations="Не выбирается автоматически и не считается проверенной ГОСТ/нормативной формулой.",
            parameters=("lambda", "t"),
            parameter_docs={"lambda": "интенсивность отказов, 1/ч", "t": "время работы, ч"},
            general_formula="требуется ручная проверка",
            display_formula="требуется ручная проверка",
            computable_formula="",
            priority=0,
            verification_status="needs_review",
            source_type="external_document",
            manual_review_required=True,
        ),
        "DOC.SLIDING_LOADED_RESERVE_K_OF_N.P": FormulaDefinition(
            formula_id="DOC.SLIDING_LOADED_RESERVE_K_OF_N.P",
            title="Скользящий нагруженный резерв k из N",
            source=(
                "Заготовка формулы из внешнего инженерного документа. Используются "
                "нормализованные параметры схемы k_required и n_total, но точную методику нужно проверить вручную."
            ),
            formula_type="заготовка внешней методики",
            metric="P",
            fragment_kind="reserve_sliding_k_of_n",
            applies_to="Скользящий нагруженный резерв, где должны оставаться работоспособными не менее k элементов из N.",
            applicability="Только после ручной проверки импортированного текста формулы и исходных допущений.",
            limitations="Не выбирается автоматически. Резерв k из N не эквивалентен простому reserve_count.",
            parameters=("lambda", "t", "k_required", "n_total", "C", "n"),
            parameter_docs={
                "lambda": "интенсивность отказов, 1/ч",
                "t": "время работы, ч",
                "k_required": "требуемое число работоспособных элементов",
                "n_total": "общее число элементов",
                "C": "коэффициент методики из источника",
                "n": "параметр суммирования/индекс из источника",
            },
            general_formula="требуется ручная проверка",
            display_formula="требуется ручная проверка для скользящего резерва k из N",
            computable_formula="",
            priority=0,
            verification_status="needs_review",
            source_type="external_document",
            manual_review_required=True,
        ),
    }
)


def formula_for_fragment(kind: str, metric: str = "P") -> FormulaDefinition | None:
    """Return the best project formula for an AST fragment kind and metric."""
    metric_key = "K" if metric in {"K", "Kg", "Kг"} else "P"
    candidates = [
        definition
        for definition in FORMULA_LIBRARY.values()
        if definition.fragment_kind == kind and (definition.metric == metric_key or definition.metric == "Kг")
    ]
    if not candidates and kind == "one" and metric_key == "P":
        return FORMULA_LIBRARY["STRUCT.IDENTITY.P"]
    return max(candidates, key=lambda item: item.priority) if candidates else None
