from __future__ import annotations

from dataclasses import asdict
from html import escape
from typing import Any

from app.formulas.formula_rendering import (
    formula_item_html,
    formula_section_html,
    is_renderable_latex_formula,
    latex_block,
    latex_formula_text,
    latex_to_html,
    readable_formula_text,
    result_metric_formulas_for,
    result_metric_latex_for,
)
from app.core.normative_methods import SUPPORTED_METHODS_BY_CODE, get_method_spec
from app.core.rbd_models import FormulaInfo, FormulaItem, FormulaPackage, ParameterItem, SchemeModel


def generate_formula_package(
    *,
    method_name: str | None = None,
    method_code: str | None = None,
    inputs: dict[str, Any] | None = None,
    numeric_results: dict[str, Any] | None = None,
    scheme: SchemeModel | None = None,
    formula_mode: str | None = None,
    algorithm_name: str | None = None,
    time_horizon: int = 1000,
) -> FormulaPackage:
    """Build the canonical formula package with explicit mode routing."""
    inputs = dict(inputs or {})
    numeric_results = dict(numeric_results or {})
    code = _resolve_method_code(method_name, method_code)

    if formula_mode == "algorithmic" or algorithm_name:
        package = AlgorithmicFormulaGenerator().generate(
            algorithm_name=algorithm_name or "algorithm",
            inputs=inputs,
            numeric_results=numeric_results,
        )
    elif code in SUPPORTED_METHODS_BY_CODE:
        package = NormativeFormulaGenerator().generate(
            method_code=code,
            inputs=inputs,
            numeric_results=numeric_results,
        )
    else:
        package = StructuralFormulaGenerator().generate(
            scheme=scheme,
            inputs=inputs,
            numeric_results=numeric_results,
            time_horizon=time_horizon,
        )
    return FormulaRenderer().render(package)


class NormativeFormulaGenerator:
    """Specialized formula generator for known F1.1-F7.2 methods."""

    def generate(
        self,
        *,
        method_code: str,
        inputs: dict[str, Any] | None = None,
        numeric_results: dict[str, Any] | None = None,
    ) -> FormulaPackage:
        builder = getattr(self, f"build_{_builder_suffix(method_code)}", None)
        if builder is None:
            builder = self._build_generic
        return builder(method_code, dict(inputs or {}), dict(numeric_results or {}))

    def _build_generic(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        spec = SUPPORTED_METHODS_BY_CODE[method_code]
        formula_items = [
            FormulaItem(
                key=f"{method_code}:{name}",
                label=_user_formula_label(method_code, str(name)),
                symbolic_template=str(value),
                general_expression=str(value),
                instantiated_formula=readable_formula_text(value),
                general_latex=latex_formula_text(value),
                instantiated_latex=latex_formula_text(value),
                display_latex=latex_formula_text(value),
                plain_text=readable_formula_text(value),
                order=index,
            )
            for index, (name, value) in enumerate(_scenario_formulas(spec.formulas, inputs).items(), start=1)
        ]
        result_items = [item for item in _result_formula_items(numeric_results) if item.label in spec.result_fields]
        warnings: list[str] = []
        limitations = spec.limitations
        if method_code == "F6.3":
            warnings.append("F6.3: показатель T0 в текущей реализации ограничен; пакет формул показывает только P.")
        return FormulaPackage(
            formula_mode="normative",
            is_normative=True,
            method_code=method_code,
            title=spec.display_name,
            source_label="Реестр нормативных методов F1.1-F7.2",
            source_details=spec.source,
            applicability=spec.applicability,
            limitations=limitations,
            warnings=warnings,
            formulas=formula_items,
            intermediate_formulas=_intermediate_items(method_code, inputs, numeric_results),
            result_formulas=result_items,
            parameter_lines=_parameter_items(inputs),
            numeric_results=numeric_results,
            metadata={"generator": "NormativeFormulaGenerator", "method_name": spec.display_name},
        )

    def build_f11(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f12(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f13(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f14(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f15(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f21(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f22(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        package = self._build_generic(method_code, inputs, numeric_results)
        cat = _cat_value(inputs)
        if cat in {1, 2, 3}:
            t_v = inputs.get("t_v")
            m = inputs.get("m")
            instantiated = ""
            if t_v is not None and m is not None:
                try:
                    instantiated = f"Tv = {float(t_v):.8g} / ({int(m)} + 1) = {numeric_results.get('Tv', '')}"
                except (TypeError, ValueError):
                    instantiated = "Tv = t_v / (m + 1)"
            package.intermediate_formulas.append(
                FormulaItem(
                    key="F2.2:Tv:normative",
                    label="Нормативная формула Tв",
                    symbolic_template="Tv = t_v / (m + 1)",
                    instantiated_formula=instantiated or "Tv = t_v / (m + 1)",
                    numeric_value=numeric_results.get("Tv"),
                    comment="Нормативная ветка Tv для F2.2 при cat3=1,2,3; ее нельзя заменять общей постобработкой.",
                    order=10,
                    general_latex=r"T_{\text{в}} = \frac{t_{\text{в}}}{m + 1}",
                    instantiated_latex=(
                        rf"T_{{\text{{в}}}} = \frac{{{float(t_v):.8g}}}{{{int(m)} + 1}} = {numeric_results.get('Tv', '')}"
                        if t_v is not None and m is not None else r"T_{\text{в}} = \frac{t_{\text{в}}}{m + 1}"
                    ),
                    display_latex=r"T_{\text{в}} = \frac{t_{\text{в}}}{m + 1}",
                )
            )
            package.intermediate_formulas.append(
                FormulaItem(
                    key="F2.2:KgKog:normative",
                    label="Нормативные формулы Kг и Kог",
                    symbolic_template="Kg = T0 / (T0 + Tv); Kog = Kg * P",
                    instantiated_formula=(
                        f"Kg = {numeric_results.get('T0', 'T0')} / ({numeric_results.get('T0', 'T0')} + "
                        f"{numeric_results.get('Tv', 'Tv')}), Kog = {numeric_results.get('Kg', 'Kg')} * {numeric_results.get('P', 'P')}"
                    ),
                    numeric_value={"Kg": numeric_results.get("Kg"), "Kog": numeric_results.get("Kog")},
                    comment="Сохраняет исправленную расчетную логику backend для F2.2.",
                    order=11,
                    general_latex=(
                        r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}; "
                        r"K_{\text{ог}} = K_{\text{г}} \cdot P"
                    ),
                    instantiated_latex=(
                        rf"K_{{\text{{г}}}} = \frac{{{numeric_results.get('T0', 'T_0')}}}"
                        rf"{{{numeric_results.get('T0', 'T_0')} + {numeric_results.get('Tv', 'T_{\\text{в}}')}}}; "
                        rf"K_{{\text{{ог}}}} = {numeric_results.get('Kg', 'K_{\\text{г}}')} \cdot {numeric_results.get('P', 'P')}"
                    ),
                    display_latex=(
                        r"K_{\text{г}} = \frac{T_0}{T_0 + T_{\text{в}}}; "
                        r"K_{\text{ог}} = K_{\text{г}} \cdot P"
                    ),
                )
            )
        return package

    def build_f23(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f24(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f25(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f26(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f27(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f31(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f41(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f51(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f61(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f62(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f63(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        package = self._build_generic(method_code, inputs, numeric_results)
        package.limitations = package.limitations or "T0 для F6.3 в текущей реализации ограничен; поддерживаемый выходной показатель - P."
        package.warnings.append("F6.3 показывает P(t); T0 отмечен как ограниченный/отсутствующий и не экспортируется как полноценная формула результата.")
        package.result_formulas = [item for item in package.result_formulas if item.label != "T0"]
        return package

    def build_f71(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)

    def build_f72(self, method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(method_code, inputs, numeric_results)


class StructuralFormulaGenerator:
    """Fallback generator for schemes without an exact normative method."""

    def generate(
        self,
        *,
        scheme: SchemeModel | None,
        inputs: dict[str, Any] | None = None,
        numeric_results: dict[str, Any] | None = None,
        time_horizon: int = 1000,
    ) -> FormulaPackage:
        if scheme is None:
            return FormulaPackage(
                formula_mode="structural_fallback",
                is_normative=False,
                method_code=None,
                title="Структурная формула",
                source_label="Структурное построение формулы",
                source_details="Точная нормативная методика не задана; пакет построен по правилам структурной композиции.",
                applicability="Использовать только как ненормативное структурное пояснение.",
                limitations="Это не формула ОСТ/F-методики; not normative.",
                warnings=["Схема не передана, поэтому детализация структурной формулы ограничена."],
                parameter_lines=_parameter_items(inputs or {}),
                numeric_results=dict(numeric_results or {}),
                metadata={"generator": "StructuralFormulaGenerator"},
            )

        from app.formulas.formula_engine import FormulaGenerationService

        engine_result = FormulaGenerationService().generate(scheme, time_horizon=time_horizon)
        report = engine_result.base_report
        results = dict(numeric_results or engine_result.numeric_results)
        formulas = [
            FormulaItem(
                key="structural:P",
                label="Вероятность безотказной работы",
                symbolic_template=f"Pсист(t) = {report.symbolic_formula_reliability}",
                instantiated_formula=f"Pсист(t) = {report.symbolic_formula_reliability}",
                general_latex=rf"P_{{\text{{сист}}}}(t) = {report.formula_ast_reliability.render_latex()}",
                instantiated_latex=rf"P_{{\text{{сист}}}}(t) = {report.formula_ast_reliability.render_latex()}",
                display_latex=rf"P_{{\text{{сист}}}}(t) = {report.formula_ast_reliability.render_latex()}",
                numeric_value=results.get("P"),
                comment="Ненормативная структурная формула по схеме.",
                order=1,
            ),
            FormulaItem(
                key="structural:Kg",
                label="Коэффициент готовности",
                symbolic_template=f"Kг_сист = {report.symbolic_formula_availability.replace(' · ', ' * ')}",
                instantiated_formula=f"Kг_сист = {report.symbolic_formula_availability.replace(' · ', ' * ')}",
                general_latex=rf"K_{{\text{{г,сист}}}} = {report.formula_ast_availability.render_latex()}",
                instantiated_latex=rf"K_{{\text{{г,сист}}}} = {report.formula_ast_availability.render_latex()}",
                display_latex=rf"K_{{\text{{г,сист}}}} = {report.formula_ast_availability.render_latex()}",
                numeric_value=results.get("Kg"),
                comment="Ненормативная структурная формула по схеме.",
                order=2,
            ),
        ]
        intermediate = [
            FormulaItem(
                key="structural:rules",
                label="Правила композиции",
                symbolic_template="последовательно: произведение; параллельно: 1 - произведение отказов ветвей; резерв: 1 - (1 - P)^(m+1)",
                instantiated_formula=report.formula_ast_reliability.render_structure(),
                comment="Это структурные правила, их нельзя выдавать за F1.1-F7.2.",
                order=1,
            )
        ]
        for index, item in enumerate(engine_result.instantiated_formulas, start=10):
            if item.node_type == "single_element":
                continue
            intermediate.append(
                FormulaItem(
                    key=f"library:{item.fragment_id}:{item.metric}",
                    label=f"{item.title} ({item.metric})",
                    symbolic_template=item.general_formula,
                    instantiated_formula=item.instantiated_formula,
                    numeric_value=item.numeric_value,
                    comment=item.explanation,
                    order=index,
                    formula_id=item.formula_id,
                    source=item.source,
                    verification_status=item.verification_status,
                    general_expression=item.general_formula,
                    parameters=dict(item.parameter_substitution),
                    general_latex=item.general_latex,
                    instantiated_latex=item.instantiated_latex,
                    display_latex=item.display_latex,
                )
            )
        warnings = list(report.warnings)
        warnings.extend(engine_result.warnings)
        warnings.append("Режим формулы: структурная ненормативная формула (structural_fallback, not normative).")
        warnings = list(dict.fromkeys(warnings))
        return FormulaPackage(
            formula_mode="structural_fallback",
            is_normative=False,
            method_code=None,
            title=f"Структурная формула: {scheme.name}",
            source_label="Структурное построение по схеме (structural)",
            source_details="Формула построена по фактической топологии схемы.",
            applicability="Для схемы не выбрана точная нормативная методика; формула поясняет последовательные, параллельные и резервированные фрагменты.",
            limitations="Ненормативная структурная композиция; not normative. Не подписывать как ОСТ или F1.1-F7.2 без точного совпадения методики.",
            warnings=warnings,
            formulas=formulas,
            intermediate_formulas=intermediate,
            result_formulas=_result_formula_items(results),
            parameter_lines=[ParameterItem(symbol, desc, comment="scheme symbol", order=index) for index, (symbol, desc) in enumerate(report.symbols.items(), start=1)],
            numeric_results=results,
            metadata={
                "generator": "StructuralFormulaGenerator",
                "used_blocks": report.used_blocks,
                "unused_blocks": report.unused_blocks,
                "structural": "\n".join([f"P: {report.formula_ast_reliability.render_structure()}", f"Kg: {report.formula_ast_availability.render_structure()}"]),
                "computational": "\n".join([f"P = {report.computable_formula_reliability}", f"Kg = {report.computable_formula_availability}"]),
                "steps": list(dict.fromkeys(report.explanation_steps + engine_result.explanation_steps)),
                "symbols": report.symbols,
                "analysis": [
                    {
                        "fragment_id": item.fragment_id,
                        "node_type": item.node_type,
                        "fragment_kind": item.fragment_kind,
                        "metric": item.metric,
                        "elements": list(item.elements),
                        "parameters": dict(item.parameters),
                        "reason": item.reason,
                    }
                    for item in engine_result.analysis
                ],
                "selected_formulas": [
                    {
                        "fragment_id": item.fragment_id,
                        "formula_id": item.definition.formula_id if item.definition else None,
                        "status": item.status,
                        "reason": item.reason,
                        "candidates": [candidate.formula_id for candidate in item.candidates],
                    }
                    for item in engine_result.selections
                ],
                "general_formulas": {
                    item.fragment_id: item.general_formula for item in engine_result.instantiated_formulas
                },
                "instantiated_formulas": {
                    item.fragment_id: item.instantiated_formula for item in engine_result.instantiated_formulas
                },
                "final_formulas": {
                    "P": report.symbolic_formula_reliability,
                    "Kg": report.symbolic_formula_availability,
                },
                "numeric_results": dict(results),
                "formula_engine": "FormulaGenerationService",
            },
        )


class AlgorithmicFormulaGenerator:
    """Formula package generator for special algorithmic modes."""

    def generate(
        self,
        *,
        algorithm_name: str,
        inputs: dict[str, Any] | None = None,
        numeric_results: dict[str, Any] | None = None,
    ) -> FormulaPackage:
        return FormulaPackage(
            formula_mode="algorithmic",
            is_normative=False,
            method_code=None,
            title=f"Алгоритмическая формула: {algorithm_name}",
            source_label="Алгоритмический режим расчета",
            source_details=f"Пакет формул построен алгоритмическим маршрутом: {algorithm_name}.",
            applicability="Используется для минимальных путей, специальных мажоритарных сценариев и других явно заданных алгоритмов.",
            limitations="Алгоритмический результат не является нормативным автоматически.",
            warnings=["Режим формулы: алгоритмический; нормативный статус нужно обосновывать отдельно."],
            formulas=[
                FormulaItem(
                    key=f"algorithmic:{algorithm_name}",
                    label=str(algorithm_name),
                    symbolic_template="Алгоритмическая процедура; см. промежуточные шаги и численные результаты.",
                    instantiated_formula="Алгоритмическая процедура; см. промежуточные шаги и численные результаты.",
                    order=1,
                )
            ],
            parameter_lines=_parameter_items(inputs or {}),
            numeric_results=dict(numeric_results or {}),
            metadata={"generator": "AlgorithmicFormulaGenerator", "algorithm_name": algorithm_name},
        )


class FormulaRenderer:
    """Render FormulaPackage without choosing mode or inventing formulas."""

    def render(self, package: FormulaPackage) -> FormulaPackage:
        for item in package.formulas + package.intermediate_formulas + package.result_formulas:
            _ensure_latex_fields(item)
        package.plain_text = self.to_plain_text(package)
        package.latex_text = self.to_latex_text(package)
        package.html_text = self.to_html(package)
        package.export_payload = self.to_export_payload(package)
        return package

    def to_latex_text(self, package: FormulaPackage) -> str:
        lines = [package.title]
        for section_title, items in (
            ("Формулы", package.formulas),
            ("Промежуточные формулы", package.intermediate_formulas),
            ("Формулы результатов", package.result_formulas),
        ):
            if not items:
                continue
            lines.extend(["", section_title + ":"])
            for item in sorted(items, key=lambda value: value.order):
                formula = item.instantiated_latex or item.display_latex or item.general_latex
                if formula:
                    lines.append(f"- {item.label}: {latex_block(formula)}")
                if item.general_latex and item.general_latex != formula:
                    lines.append(f"  общая формула: {latex_block(item.general_latex)}")
        return "\n".join(lines)

    def to_plain_text(self, package: FormulaPackage) -> str:
        lines = [
            package.title,
            f"режим формулы: {_formula_mode_label(package.formula_mode)}",
            f"нормативная формула: {'да' if package.is_normative else 'нет'}",
            f"источник: {package.source_label}",
        ]
        if package.applicability:
            lines.append(f"область применения: {package.applicability}")
        if package.limitations:
            lines.append(f"ограничения: {package.limitations}")
        if package.parameter_lines:
            lines.extend(["", "Параметры:"])
            lines.extend(f"- {item.name} = {item.value}{(' ' + item.unit) if item.unit else ''}" for item in sorted(package.parameter_lines, key=lambda item: item.order))
        if package.formulas:
            lines.extend(["", "Формулы:"])
            lines.extend(_plain_formula_line(item) for item in sorted(package.formulas, key=lambda item: item.order))
        if package.intermediate_formulas:
            lines.extend(["", "Промежуточные формулы:"])
            lines.extend(_plain_formula_line(item) for item in sorted(package.intermediate_formulas, key=lambda item: item.order))
        if package.result_formulas:
            lines.extend(["", "Формулы результатов:"])
            lines.extend(_plain_formula_line(item) for item in sorted(package.result_formulas, key=lambda item: item.order))
        if package.numeric_results:
            lines.extend(["", "Численные результаты:"])
            lines.extend(f"- {key} = {value}" for key, value in package.numeric_results.items())
        if package.warnings:
            lines.extend(["", "Предупреждения:"])
            lines.extend(f"- {warning}" for warning in package.warnings)
        return "\n".join(str(line) for line in lines if line is not None)

    def to_html(self, package: FormulaPackage) -> str:
        formula_blocks = "".join(
            _html_formula_section(title, items)
            for title, items in (
                ("Основные формулы", package.formulas),
                ("Промежуточные формулы", package.intermediate_formulas),
                ("Формулы результатов", package.result_formulas),
            )
            if items
        )
        parameters = _parameter_lines_html(package.parameter_lines)
        warnings = "".join(f"<li>{escape(str(warning))}</li>" for warning in package.warnings)
        return (
            f"<h3>{escape(package.title)}</h3>"
            f"<p><b>Режим формулы:</b> {escape(_formula_mode_label(package.formula_mode))}<br>"
            f"<b>Нормативная формула:</b> {escape('да' if package.is_normative else 'нет')}<br>"
            f"<b>Источник:</b> {escape(package.source_label)}</p>"
            f"<p><b>Область применения:</b> {escape(package.applicability)}</p>"
            f"<p><b>Ограничения:</b> {escape(package.limitations or '-')}</p>"
            f"{parameters}"
            f"{formula_blocks or '<p>Формулы недоступны.</p>'}"
            f"{'<p><b>Предупреждения:</b></p><ul>' + warnings + '</ul>' if warnings else ''}"
        )

    def to_export_payload(self, package: FormulaPackage) -> dict[str, Any]:
        return {
            "formula_mode": package.formula_mode,
            "is_normative": package.is_normative,
            "method_code": package.method_code,
            "title": package.title,
            "source_label": package.source_label,
            "source_details": package.source_details,
            "applicability": package.applicability,
            "limitations": package.limitations,
            "warnings": list(package.warnings),
            "formulas": [asdict(item) for item in package.formulas],
            "intermediate_formulas": [asdict(item) for item in package.intermediate_formulas],
            "result_formulas": [asdict(item) for item in package.result_formulas],
            "parameter_lines": [asdict(item) for item in package.parameter_lines],
            "numeric_results": dict(package.numeric_results),
            "latex_text": package.latex_text,
            "metadata": dict(package.metadata),
        }


def formula_package_to_info(package: FormulaPackage) -> FormulaInfo:
    metadata = package.metadata
    return FormulaInfo(
        text="\n".join(_display_formula_lines(package)) or package.plain_text,
        latex=package.latex_text,
        is_exact=package.formula_mode != "algorithmic",
        note=f"{package.source_label}\nрежим: {_formula_mode_label(package.formula_mode)}; нормативная: {'да' if package.is_normative else 'нет'}",
        structural=str(metadata.get("structural", "")),
        computational=str(metadata.get("computational", "")),
        steps=list(metadata.get("steps", [])),
        symbols=dict(metadata.get("symbols", {})),
        used_blocks=list(metadata.get("used_blocks", [])),
        unused_blocks=list(metadata.get("unused_blocks", [])),
        warnings=list(package.warnings),
        package=package,
    )


def _resolve_method_code(method_name: str | None, method_code: str | None) -> str | None:
    if method_code:
        return method_code
    if not method_name:
        return None
    if method_name in SUPPORTED_METHODS_BY_CODE:
        return method_name
    spec = get_method_spec(method_name)
    return spec.code if spec else None


def _builder_suffix(method_code: str) -> str:
    return method_code.lower().replace(".", "")


def _cat_value(inputs: dict[str, Any]) -> int | None:
    for key in ("cat3", "cat3_f22", "cat3_f2", "cat3_f24"):
        if key in inputs:
            try:
                return int(inputs[key])
            except (TypeError, ValueError):
                return None
    return None


def _scenario_formulas(formulas: dict[str, str], inputs: dict[str, Any]) -> dict[str, str]:
    cat = _cat_value(inputs)
    if cat is None:
        return dict(formulas)
    selected = {
        key: value
        for key, value in formulas.items()
        if f"cat3={cat}" in key or "cat3=" not in key or f"cat3={cat}" in value
    }
    return selected or dict(formulas)


def _intermediate_items(method_code: str, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> list[FormulaItem]:
    items: list[FormulaItem] = []
    if "Kg" in numeric_results and "P" in numeric_results and "Kog" in numeric_results:
        items.append(
            FormulaItem(
                key=f"{method_code}:Kog",
                label="Проверка Kог",
                symbolic_template="Kog = Kg * P",
                instantiated_formula=f"Kog = {numeric_results.get('Kg')} * {numeric_results.get('P')} = {numeric_results.get('Kog')}",
                numeric_value=numeric_results.get("Kog"),
                order=100,
            )
        )
    return items


def _parameter_items(inputs: dict[str, Any]) -> list[ParameterItem]:
    return [
        ParameterItem(name=str(key), value=value, order=index)
        for index, (key, value) in enumerate(inputs.items(), start=1)
    ]


def _user_formula_label(method_code: str, raw_label: str) -> str:
    text = str(raw_label or "").strip()
    if not text:
        return "Формула"
    special = {
        "Kog consistency": "Проверка Kог",
        "Tv for cat3=1..3": "Нормативная формула Tв",
        "Kg and Kog for cat3=1..3": "Нормативные формулы Kг и Kог",
        "T_v,K_g(cat3=1..3)": "Формулы Tв и Kг",
    }
    if text in special:
        return special[text]
    if text.startswith("cat3="):
        return f"Основная формула метода {method_code}"
    return text


def _result_formula_items(results: dict[str, Any]) -> list[FormulaItem]:
    latex_by_key = result_metric_latex_for(results.keys())
    return [
        FormulaItem(
            key=f"result:{key}",
            label=key,
            symbolic_template=str(value),
            instantiated_formula=readable_formula_text(value),
            numeric_value=results.get(key),
            order=index,
            general_latex=latex_by_key.get(key, latex_formula_text(value)),
            instantiated_latex=latex_by_key.get(key, latex_formula_text(value)),
            display_latex=latex_by_key.get(key, latex_formula_text(value)),
        )
        for index, (key, value) in enumerate(result_metric_formulas_for(results.keys()).items(), start=1)
    ]


def _plain_formula_line(item: FormulaItem) -> str:
    formula = item.plain_text or readable_formula_text(item.instantiated_latex or item.instantiated_formula or item.symbolic_template)
    suffix = f" = {item.numeric_value}" if item.numeric_value not in (None, "") else ""
    comment = f" ({item.comment})" if item.comment else ""
    return f"- {item.label}: {formula}{suffix}{comment}"


def _html_formula_line(item: FormulaItem) -> str:
    source = item.instantiated_formula or item.symbolic_template
    formula = item.instantiated_latex or item.display_latex or item.general_latex or (
        latex_formula_text(source) if is_renderable_latex_formula(source) else source
    )
    return formula_item_html(
        item.label,
        latex_to_html(formula),
        numeric_value=item.numeric_value,
        comment=item.comment,
    )


def _html_formula_section(title: str, items: list[FormulaItem]) -> str:
    rows = "".join(_html_formula_line(item) for item in sorted(items, key=lambda item: item.order))
    return formula_section_html(title, rows)


def _parameter_lines_html(items: list[ParameterItem]) -> str:
    if not items:
        return ""
    title = "Обозначения блоков" if any(str(item.comment) == "scheme symbol" for item in items) else "Обозначения"
    rows = "".join(
        "<div style='margin:2px 0; color:#536274; font-size:11px; line-height:1.3; word-break:break-word;'>"
        f"<b>{escape(str(item.name))}</b> - {escape(str(item.value))}"
        f"{'; ' + escape(str(item.comment)) if item.comment else ''}"
        "</div>"
        for item in sorted(items, key=lambda item: item.order)
    )
    return formula_section_html(title, rows)


def _display_formula_lines(package: FormulaPackage) -> list[str]:
    if package.formula_mode == "structural_fallback":
        return [item.instantiated_formula for item in package.formulas if item.instantiated_formula]
    return [
        f"{item.label}: {item.instantiated_latex or item.instantiated_formula or readable_formula_text(item.symbolic_template)}"
        for item in package.formulas + package.intermediate_formulas + package.result_formulas
    ]


def _formula_mode_label(mode: str) -> str:
    return {
        "normative": "нормативная методика",
        "structural_fallback": "структурная формула, не нормативная (not normative)",
        "algorithmic": "алгоритмический режим",
    }.get(str(mode), str(mode))


def _ensure_latex_fields(item: FormulaItem) -> None:
    general_source = item.general_expression or item.symbolic_template
    instantiated_source = item.instantiated_formula or item.symbolic_template
    if not item.general_latex and is_renderable_latex_formula(general_source):
        item.general_latex = latex_formula_text(general_source)
    if not item.instantiated_latex and is_renderable_latex_formula(instantiated_source):
        item.instantiated_latex = latex_formula_text(instantiated_source)
    if not item.display_latex:
        item.display_latex = item.instantiated_latex or item.general_latex
    if not item.plain_text:
        item.plain_text = readable_formula_text(item.instantiated_latex or item.instantiated_formula or item.symbolic_template)
    if not item.html_text:
        item.html_text = latex_to_html(item.instantiated_latex or item.display_latex or item.general_latex or instantiated_source)


def _f22_kg_kog_latex(numeric_results: dict[str, Any]) -> str:
    t0 = numeric_results.get("T0") or "T_0"
    tv = numeric_results.get("Tv") or r"T_{\text{в}}"
    kg = numeric_results.get("Kg") or r"K_{\text{г}}"
    p = numeric_results.get("P") or "P"
    return (
        rf"K_{{\text{{г}}}} = \frac{{{t0}}}{{{t0} + {tv}}}; "
        rf"K_{{\text{{ог}}}} = {kg} \cdot {p}"
    )
