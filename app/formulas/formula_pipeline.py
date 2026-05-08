from __future__ import annotations

from typing import Any

import app.core.dependability_backend as backend
from app.formulas.formula_rendering import FormulaRenderer, readable_formula_text, result_metric_formulas_for
from app.formulas.graph_formula_builder import build_formula_report, evaluate_formula_for_scheme
from app.core.normative_methods import SUPPORTED_METHODS_BY_CODE, NormativeMethodSpec, get_method_spec
from app.core.rbd_models import FormulaInfo, FormulaItem, FormulaPackage, ParameterItem, SchemeModel


FORMULA_MODE_NORMATIVE = "normative"
FORMULA_MODE_STRUCTURAL = "structural_fallback"
FORMULA_MODE_ALGORITHMIC = "algorithmic"


class NormativeFormulaGenerator:
    def generate(
        self,
        method_code: str,
        *,
        inputs: dict[str, Any] | None = None,
        numeric_results: dict[str, Any] | None = None,
    ) -> FormulaPackage:
        spec = SUPPORTED_METHODS_BY_CODE[method_code]
        builder = getattr(self, f"build_{method_code.lower().replace('.', '')}", None)
        if builder is None:
            builder = self._build_generic
        package = builder(spec, inputs=inputs or {}, numeric_results=numeric_results or {})
        return FormulaRenderer.render(package)

    def _build_generic(
        self,
        spec: NormativeMethodSpec,
        *,
        inputs: dict[str, Any],
        numeric_results: dict[str, Any],
    ) -> FormulaPackage:
        formulas = self._formula_items_from_dict(spec.formulas)
        result_formulas = self._result_items(spec, numeric_results)
        intermediate = self._intermediate_items(spec, inputs, numeric_results)
        warnings: list[str] = []
        limitations = spec.limitations
        if spec.code == "F6.3":
            warnings.append("Метод F6.3 в текущей реализации корректно показывает P(t), но не предоставляет полноценный показатель T0.")
        return FormulaPackage(
            formula_mode=FORMULA_MODE_NORMATIVE,
            is_normative=True,
            method_code=spec.code,
            title=spec.display_name,
            source_label="Нормативный генератор проекта",
            source_details=spec.source,
            applicability=spec.applicability,
            limitations=limitations,
            warnings=warnings,
            formulas=formulas,
            intermediate_formulas=intermediate,
            result_formulas=result_formulas,
            parameter_lines=self._parameter_items(spec, inputs),
            numeric_results=dict(numeric_results),
            metadata={"generator": "NormativeFormulaGenerator", "method_title": spec.title},
        )

    def _intermediate_items(
        self,
        spec: NormativeMethodSpec,
        inputs: dict[str, Any],
        numeric_results: dict[str, Any],
    ) -> list[FormulaItem]:
        items: list[FormulaItem] = []
        if spec.code == "F2.2":
            cat3 = int(inputs.get("cat3", inputs.get("cat3_f22", 0)) or 0)
            if cat3 in {1, 2, 3}:
                t_v = inputs.get("t_v", 0)
                m = inputs.get("m", 0)
                tv_value = numeric_results.get("Tv")
                kg_value = numeric_results.get("Kg")
                kog_value = numeric_results.get("Kog")
                items.extend(
                    [
                        FormulaItem(
                            key="Tv_normative",
                            label="Нормативное среднее время восстановления",
                            symbolic_template="T_v = t_v / (m + 1)",
                            instantiated_formula=f"T_v = {t_v} / ({m} + 1)",
                            numeric_value=tv_value,
                            comment="Нормативная постобработка для F2.2, cat3=1..3.",
                            order=10,
                        ),
                        FormulaItem(
                            key="Kg_normative",
                            label="Коэффициент готовности",
                            symbolic_template="K_g = T_0 / (T_0 + T_v)",
                            instantiated_formula=(
                                f"K_g = {numeric_results.get('T0', 0)} / "
                                f"({numeric_results.get('T0', 0)} + {tv_value})"
                            ),
                            numeric_value=kg_value,
                            comment="Берётся из нормативной формулы, а не из общей структурной постобработки.",
                            order=11,
                        ),
                        FormulaItem(
                            key="Kog_normative",
                            label="Коэффициент оперативной готовности",
                            symbolic_template="K_og = K_g · P(t)",
                            instantiated_formula=f"K_og = {kg_value} · {numeric_results.get('P', 0)}",
                            numeric_value=kog_value,
                            comment="Нормативная связка для F2.2.",
                            order=12,
                        ),
                    ]
                )
        return items

    def _parameter_items(self, spec: NormativeMethodSpec, inputs: dict[str, Any]) -> list[ParameterItem]:
        rows: list[ParameterItem] = []
        for order, arg in enumerate(spec.args, start=1):
            if arg not in inputs:
                continue
            doc = spec.parameter_docs.get(arg)
            rows.append(
                ParameterItem(
                    name=doc.symbol if doc else arg,
                    value=inputs[arg],
                    unit="" if doc is None else doc.unit,
                    comment="" if doc is None else doc.name,
                    order=order,
                )
            )
        return rows

    def _formula_items_from_dict(self, formulas: dict[str, str]) -> list[FormulaItem]:
        items: list[FormulaItem] = []
        for order, (label, formula) in enumerate(formulas.items(), start=1):
            items.append(
                FormulaItem(
                    key=label,
                    label=label,
                    symbolic_template=formula,
                    instantiated_formula=readable_formula_text(formula),
                    order=order,
                )
            )
        return items

    def _result_items(self, spec: NormativeMethodSpec, numeric_results: dict[str, Any]) -> list[FormulaItem]:
        items: list[FormulaItem] = []
        result_map = result_metric_formulas_for(numeric_results.keys())
        for order, key in enumerate(spec.result_fields, start=100):
            if key not in numeric_results:
                continue
            items.append(
                FormulaItem(
                    key=key,
                    label=key,
                    symbolic_template=result_map.get(key, key),
                    instantiated_formula=result_map.get(key, key),
                    numeric_value=numeric_results[key],
                    comment="Числовой результат backend.",
                    order=order,
                )
            )
        return items

    def build_f11(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f12(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f13(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f14(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f15(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f21(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f22(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f23(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f24(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f25(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f26(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f27(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f31(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f41(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f51(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f61(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f62(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f63(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f71(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)

    def build_f72(self, spec: NormativeMethodSpec, *, inputs: dict[str, Any], numeric_results: dict[str, Any]) -> FormulaPackage:
        return self._build_generic(spec, inputs=inputs, numeric_results=numeric_results)


class StructuralFormulaGenerator:
    def generate(self, scheme: SchemeModel, *, time_horizon: int = 1000) -> FormulaPackage:
        report = build_formula_report(scheme)
        numeric_results = evaluate_formula_for_scheme(scheme, time_horizon=time_horizon)
        formulas = [
            FormulaItem(
                key="P_structural",
                label="Структурная формула P(t)",
                symbolic_template=report.symbolic_formula_reliability,
                instantiated_formula=f"Pсист(t) = {report.symbolic_formula_reliability}",
                numeric_value=numeric_results.get("P"),
                comment="Композиционная формула по AST схемы.",
                order=1,
            ),
            FormulaItem(
                key="Kg_structural",
                label="Структурная формула Kг",
                symbolic_template=report.symbolic_formula_availability,
                instantiated_formula=f"Kг_сист = {report.symbolic_formula_availability}",
                numeric_value=numeric_results.get("Kg"),
                comment="Композиционная формула по AST схемы.",
                order=2,
            ),
        ]
        intermediate = [
            FormulaItem(
                key="P_structure",
                label="Структура по P",
                symbolic_template=report.formula_ast_reliability.render_structure(),
                instantiated_formula=report.formula_ast_reliability.render_structure(),
                order=10,
            ),
            FormulaItem(
                key="Kg_structure",
                label="Структура по Kг",
                symbolic_template=report.formula_ast_availability.render_structure(),
                instantiated_formula=report.formula_ast_availability.render_structure(),
                order=11,
            ),
        ]
        result_formulas = []
        equivalent_t0 = self._equivalent_t0(report)
        if equivalent_t0 is not None:
            numeric_results["T0"] = equivalent_t0
            result_formulas.append(
                FormulaItem(
                    key="T0_equivalent",
                    label="Эквивалентная оценка T0",
                    symbolic_template="T0 = 1 / Σλi",
                    instantiated_formula=f"T0 = {equivalent_t0}",
                    numeric_value=equivalent_t0,
                    comment="Оценка по суммарной интенсивности отказов активных блоков.",
                    order=100,
                )
            )
        package = FormulaPackage(
            formula_mode=FORMULA_MODE_STRUCTURAL,
            is_normative=False,
            method_code=None,
            title=f"Структурная композиционная формула: {scheme.name}",
            source_label="Structural fallback generator",
            source_details=(
                "Схема не была подтверждена как конкретный нормативный метод, поэтому используется "
                "композиционная AST-формула как ненормативный fallback."
            ),
            applicability="Подходит для схем, где есть последовательная, параллельная, резервная или вложенная композиция.",
            limitations="Формула отражает структуру схемы, является ненормативной композиционной моделью и не объявляется формулой ОСТ/ГОСТ.",
            warnings=list(report.warnings),
            formulas=formulas,
            intermediate_formulas=intermediate,
            result_formulas=result_formulas,
            numeric_results=numeric_results,
            metadata={
                "generator": "StructuralFormulaGenerator",
                "structural": "\n".join(item.instantiated_formula for item in intermediate),
                "computational": "\n".join(
                    [
                        f"P = {report.computable_formula_reliability}",
                        f"Kг = {report.computable_formula_availability}",
                    ]
                ),
                "symbols": dict(report.symbols),
                "used_blocks": list(report.used_blocks),
                "unused_blocks": list(report.unused_blocks),
                "steps": list(report.explanation_steps),
            },
        )
        return FormulaRenderer.render(package)

    def _equivalent_t0(self, report) -> float | None:
        lam_values: list[float] = []
        for block_id in report.normalized_scheme.active_ids:
            block = report.normalized_scheme.blocks[block_id]
            if block.kind in {"in", "out", "junction"}:
                continue
            lam = float(block.params.get("lambda", 0.0) or 0.0)
            if lam > 0:
                lam_values.append(lam)
        if not lam_values:
            return None
        return backend.f11(t=1, lam_list=lam_values).get("T0")


class AlgorithmicFormulaGenerator:
    def generate(
        self,
        *,
        algorithm_name: str,
        inputs: dict[str, Any] | None = None,
        numeric_results: dict[str, Any] | None = None,
    ) -> FormulaPackage:
        inputs = inputs or {}
        numeric_results = numeric_results or {}
        package = FormulaPackage(
            formula_mode=FORMULA_MODE_ALGORITHMIC,
            is_normative=False,
            method_code=None,
            title=f"Алгоритмический режим: {algorithm_name}",
            source_label="Algorithmic formula generator",
            source_details="Формула построена как отдельный алгоритмический режим, а не как нормативный метод.",
            applicability=f"Используется для режима {algorithm_name}.",
            limitations="Результат не должен интерпретироваться как нормативная формула F1.1-F7.2 без явного соответствия методу.",
            formulas=[
                FormulaItem(
                    key="algorithmic_mode",
                    label="Алгоритмическое правило",
                    symbolic_template=algorithm_name,
                    instantiated_formula=algorithm_name,
                    comment="Отдельный алгоритмический контур.",
                    order=1,
                )
            ],
            parameter_lines=[
                ParameterItem(name=str(key), value=value, order=index)
                for index, (key, value) in enumerate(inputs.items(), start=1)
            ],
            numeric_results=dict(numeric_results),
            metadata={"generator": "AlgorithmicFormulaGenerator"},
        )
        return FormulaRenderer.render(package)


def _infer_method_code(method_code: str | None = None, method_name: str | None = None) -> str | None:
    if method_code:
        return method_code
    if method_name and method_name in SUPPORTED_METHODS_BY_CODE:
        return method_name
    if method_name:
        spec = get_method_spec(method_name)
        if spec is not None:
            return spec.code
    return None


def generate_formula_package(
    *,
    scheme: SchemeModel | None = None,
    method_code: str | None = None,
    method_name: str | None = None,
    inputs: dict[str, Any] | None = None,
    numeric_results: dict[str, Any] | None = None,
    time_horizon: int = 1000,
    formula_mode: str | None = None,
    algorithm_name: str | None = None,
) -> FormulaPackage:
    resolved_method_code = _infer_method_code(method_code, method_name)
    if formula_mode == FORMULA_MODE_ALGORITHMIC or algorithm_name:
        return AlgorithmicFormulaGenerator().generate(
            algorithm_name=algorithm_name or "special_algorithm",
            inputs=inputs,
            numeric_results=numeric_results,
        )
    if resolved_method_code and resolved_method_code in SUPPORTED_METHODS_BY_CODE:
        return NormativeFormulaGenerator().generate(
            resolved_method_code,
            inputs=inputs,
            numeric_results=numeric_results,
        )
    if scheme is None:
        return AlgorithmicFormulaGenerator().generate(
            algorithm_name=algorithm_name or "generic_formula_fallback",
            inputs=inputs,
            numeric_results=numeric_results,
        )
    return StructuralFormulaGenerator().generate(scheme, time_horizon=time_horizon)


def formula_package_to_formula_info(package: FormulaPackage) -> FormulaInfo:
    ordered_items = [
        *sorted(package.formulas, key=lambda item: item.order),
        *sorted(package.result_formulas, key=lambda item: item.order),
    ]
    text = "\n".join(
        readable_formula_text(item.instantiated_formula or item.symbolic_template)
        for item in ordered_items
    )
    note = (
        f"Источник формулы: {package.source_label}. "
        f"Режим: {package.formula_mode}. "
        f"{package.source_details}"
    )
    if package.limitations:
        note += f"\nОграничения: {package.limitations}"
    if package.warnings:
        note += "\nПредупреждения: " + "; ".join(package.warnings)
    structural = str(package.metadata.get("structural", "")) or "\n".join(
        item.instantiated_formula for item in sorted(package.intermediate_formulas, key=lambda row: row.order)
    )
    return FormulaInfo(
        text=text,
        is_exact=True,
        note=note,
        structural=structural,
        computational=str(package.metadata.get("computational", "")),
        steps=list(package.metadata.get("steps", [])),
        symbols=dict(package.metadata.get("symbols", {})),
        used_blocks=list(package.metadata.get("used_blocks", [])),
        unused_blocks=list(package.metadata.get("unused_blocks", [])),
        warnings=list(package.warnings),
    )
