"""Ready-to-run project demos used by the UI and tests.

The demo layer is intentionally separate from the editor: it loads a normal
structured import file, converts it to the internal scheme model and runs the
same formula/calculation pipeline as a user-loaded project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.import_export.external_reliability_import import (
    ImportComparison,
    compare_imported_scheme_with_expected,
    imported_project_to_scheme,
    load_imported_project,
)
from app.core.rbd_models import CalculationResult, SchemeModel, formula_short_text
from app.core.scheme_adapter import calculate_scheme_reliability
from app.utils.paths import examples_path


SNE_DEMO_PATH = examples_path("imported", "sne_emrtu_project.json")
SNE_DEMO_SCHEME_ID = "sne_document_demo"


@dataclass(frozen=True, slots=True)
class DemoScenarioResult:
    """Calculated demo scenario ready for display in the application."""

    project_name: str
    source_path: Path
    scheme: SchemeModel
    calculation: CalculationResult
    comparisons: list[ImportComparison]
    warnings: list[str]
    time_horizon: int
    simulations: int

    @property
    def formula_preview(self) -> str:
        return formula_short_text(self.calculation.formula, max_lines=2)


def load_sne_emrtu_demo(
    *,
    time_horizon: int = 158,
    simulations: int = 10000,
    method: str = "Аналитический расчёт демо-схемы",
) -> DemoScenarioResult:
    """Load and calculate the SNE EMRTU reference example.

    The example comes from the normalized JSON import file. It is not
    hard-coded into parser logic and therefore documents the intended pipeline:
    external document -> reviewed structured JSON/YAML -> scheme -> formula.
    """
    project = load_imported_project(SNE_DEMO_PATH)
    scheme = imported_project_to_scheme(project, SNE_DEMO_SCHEME_ID, time_horizon=time_horizon)
    _localize_sne_demo_scheme(scheme)
    calculation = calculate_scheme_reliability(
        scheme,
        time_horizon=time_horizon,
        simulations=simulations,
        method=method,
    )
    _hide_manual_review_text_from_demo_calculation(calculation)
    comparisons = compare_imported_scheme_with_expected(
        project,
        SNE_DEMO_SCHEME_ID,
        time_horizon=time_horizon,
    )
    warnings = [_translate_demo_warning(item) for item in scheme.metadata.get("import_warnings", [])]
    warnings = [warning for warning in warnings if not _is_manual_review_text(warning)]
    return DemoScenarioResult(
        project_name=project.project_name,
        source_path=SNE_DEMO_PATH,
        scheme=scheme,
        calculation=calculation,
        comparisons=comparisons,
        warnings=warnings,
        time_horizon=time_horizon,
        simulations=simulations,
    )


def comparison_lines_for_display(comparisons: list[ImportComparison]) -> list[str]:
    """Format reference comparison results without internal technical ids."""
    lines: list[str] = []
    status_labels = {
        "match": "совпадает",
        "different": "отличается",
        "cannot_check": "невозможно проверить",
    }
    for item in comparisons:
        status = status_labels.get(item.status, item.status)
        if item.expected is None or item.actual is None:
            lines.append(f"{item.metric}: {status}")
            continue
        delta = item.abs_delta if item.abs_delta is not None else 0.0
        lines.append(
            f"{item.metric}: эталон {item.expected:.9f}, программа {item.actual:.9f}, "
            f"отклонение {delta:.3g}, статус: {status}"
        )
    return lines


def _localize_sne_demo_scheme(scheme: SchemeModel) -> None:
    """Use short Russian display names in the teacher-facing SNE demo."""
    scheme.name = "Демо-схема СНЭ"
    scheme.metadata["suppress_manual_review_warnings"] = True
    if scheme.metadata.get("imported_scheme_id") == "auxiliary_needs_chain_4":
        scheme.name = "Внутренняя наглядная цепь собственных нужд"
    names_by_id = {
        "start": "Вход",
        "end": "Выход",
        "B1": "Группа резерва 175 из 204",
        "B2": "Блок собственных нужд МКТН.563255.007",
        "B3": "Управление",
        "B4": "Силовые кабели",
        "B5": "Инфо кабели",
        "B6": "Коммутация",
        "B2A": "Внутренний участок цепи собственных нужд 1",
        "B2B": "Внутренний участок цепи собственных нужд 2",
        "B2C": "Внутренний участок цепи собственных нужд 3",
        "B2D": "Внутренний участок цепи собственных нужд 4",
    }
    fallback_index = 1
    for block in scheme.iter_blocks_recursive():
        if block.block_id in names_by_id:
            block.name = names_by_id[block.block_id]
        elif block.kind not in {"in", "out", "junction"}:
            block.name = f"Блок{fallback_index}"
            fallback_index += 1
        if block.params.get("block_role") == "k_of_n":
            block.params["suppress_manual_review_warning"] = True
        if block.nested_scheme is not None:
            _localize_sne_demo_scheme(block.nested_scheme)
    scheme.metadata["demo_display_names"] = {
        block.block_id: block.name
        for block in scheme.iter_blocks_recursive()
    }


def _translate_demo_warning(text: object) -> str:
    value = str(text)
    translations = {
        "Reference source contains values that appear inconsistent between table products and conclusion text; table values are used here.": (
            "В исходных данных есть расхождение между таблицей и выводом; для демо используются табличные значения."
        ),
        "DOC/PDF figures are not imported as semantic schemes.": (
            "Рисунки из DOC/PDF не переносятся как расчетные схемы."
        ),
        "The demo visualizes the 175-of-204 reserve as one aggregate block; it is not expanded into 204 elements.": (
            "Резерв 175 из 204 в демо показан одним агрегированным блоком, а не 204 отдельными элементами."
        ),
        "Formula for sliding loaded reserve 175 of 204.": (
            "Формула скользящего нагруженного резерва требует отдельной ручной проверки."
        ),
        "Any imported formula damaged by DOC/PDF conversion.": (
            "Формулы, поврежденные при преобразовании DOC/PDF, не используются без проверки."
        ),
        "Durability/resource calculations if they are used as normative outputs.": (
            "Расчеты ресурса требуют проверки перед использованием как нормативных результатов."
        ),
    }
    return translations.get(value, value)


def _hide_manual_review_text_from_demo_calculation(calculation: CalculationResult) -> None:
    """Keep SNE demo user output clean while preserving the calculation model."""
    if calculation.formula is not None:
        calculation.formula.warnings = [
            warning for warning in calculation.formula.warnings if not _is_manual_review_text(warning)
        ]
        package = calculation.formula.package
        if package is not None:
            _hide_manual_review_text_from_package(package)
        _hide_manual_review_text_from_package(calculation.formula_package)
    calculation.details["formula_warnings"] = [
        warning
        for warning in calculation.details.get("formula_warnings", [])
        if not _is_manual_review_text(warning)
    ]


def _hide_manual_review_text_from_package(package: object | None) -> None:
    if package is None:
        return
    package.warnings = [warning for warning in package.warnings if not _is_manual_review_text(warning)]
    package.intermediate_formulas = [
        item
        for item in package.intermediate_formulas
        if not _is_manual_review_text(item.label)
        and not _is_manual_review_text(item.instantiated_formula)
        and not _is_manual_review_text(item.display_latex)
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
