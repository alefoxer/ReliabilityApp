from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import app.core.dependability_backend as lib
from app.formulas.formula_rendering import formula_dict_to_plain, result_metric_formulas_for
from app.core.method_metadata import METHOD_GUIDES, PARAMETER_DOCS, MethodGuide, ParameterDoc


COMMON_SOURCE = (
    "Нормативная база проекта: формулы и расчётные соотношения, зафиксированные в проектных "
    "материалах и дополнительно предоставленные пользователем как утверждённый набор методов "
    "F1.1-F7.2 для данного проекта."
)

RESULT_PT0 = ("P", "T0")
RESULT_REPAIRABLE = ("P", "T0", "Tv", "Kg", "Kog")
RESULT_TEMPORARY = ("P", "T0", "Tpr", "Kg", "Kog")
RESULT_AVAILABILITY = ("T0", "Kg", "Kog")


@dataclass(frozen=True, slots=True)
class NormativeMethodSpec:
    code: str
    title: str
    func: Callable[..., dict]
    mode: str
    args: tuple[str, ...]
    formulas: dict[str, str]
    source: str
    applicability: str
    limitations: str = ""
    result_fields: tuple[str, ...] = ("P", "T0", "Tv", "Kg", "Kog", "Tpr")

    @property
    def display_name(self) -> str:
        return f"{self.code}: {self.title}"

    @property
    def methodology_text(self) -> str:
        parts = [
            f"Метод: {self.display_name}",
            f"Описание: {self.description}",
        ]
        if self.parameter_docs:
            params = "; ".join(f"{doc.symbol} - {doc.name}" for doc in self.parameter_docs.values())
            parts.append(f"Параметры: {params}")
        if self.mode == "vector":
            parts.append(
                "Таблица элементов: λi - интенсивность отказов i-го элемента; "
                "Tвi - среднее время восстановления i-го элемента."
            )
        all_formulas = dict(self.formulas)
        all_formulas.update(self.result_formulas)
        formulas = formula_dict_to_plain(all_formulas)
        if formulas:
            parts.append(f"Формулы: {formulas}")
        parts.append(f"Что рассчитывает: {self.calculates}")
        parts.append(f"Где применяется: {self.use_when}")
        if self.limitations:
            parts.append(f"Ограничения: {self.limitations}")
        parts.append("Нормативная база: утвержденный набор формул F1.1-F7.2, используемый в проекте.")
        return "\n".join(parts)

    @property
    def guide(self) -> MethodGuide:
        return METHOD_GUIDES[self.code]

    @property
    def description(self) -> str:
        return self.guide.description

    @property
    def calculates(self) -> str:
        return self.guide.calculates

    @property
    def use_when(self) -> str:
        return self.guide.use_when

    @property
    def example(self) -> str:
        return self.guide.example

    @property
    def parameter_docs(self) -> dict[str, ParameterDoc]:
        return {arg: PARAMETER_DOCS[arg] for arg in self.args if arg in PARAMETER_DOCS}

    @property
    def result_formulas(self) -> dict[str, str]:
        return result_metric_formulas_for(self.result_fields)


SUPPORTED_METHODS: tuple[NormativeMethodSpec, ...] = (
    NormativeMethodSpec(
        code="F1.1",
        title="Последовательное соединение",
        func=lib.f11,
        mode="vector",
        args=("t",),
        formulas={
            "P(t)": r"P(t)=e^{-t\sum_i \lambda_i}",
            "T_0": r"T_0=\frac{1}{\sum_i \lambda_i}",
        },
        source=f"{COMMON_SOURCE} Формула задана в предоставленном методе `f11`.",
        applicability="Последовательное соединение независимых элементов.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F1.2",
        title="Сложное резервирование",
        func=lib.f12,
        mode="scalar",
        args=("cat3", "t", "n", "m", "lam", "lam_p"),
        formulas={
            "cat3=1": r"P(t)=\sum_{i=0}^{m} C_N^i e^{-(N-i)\lambda t}\left(1-e^{-\lambda t}\right)^i",
            "cat3=2": r"P(t)=\frac{\prod_{i=0}^{m}(n+i a)}{a^m m!}\sum_{i=0}^{m}\frac{(-1)^i C_m^i e^{-(n+i a)\lambda t}}{n+i a},\ a=\lambda_p/\lambda",
            "cat3=3": r"P(t)=e^{-n\lambda t}\sum_{i=0}^{m}\frac{(n\lambda t)^i}{i!}",
            "T_0(cat3=3)": r"T_0=\frac{m+1}{n\lambda}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f12`.",
        applicability="Сценарии нагруженного, облегчённого, ненагруженного и неоднородного резервирования.",
        limitations="Для сценария с разными элементами T0 вычисляется численно интегрированием по схеме, предоставленной в реализации.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F1.3",
        title="Дублирование с переключателем",
        func=lib.f13,
        mode="scalar",
        args=("t", "lam", "lam_s"),
        formulas={
            "P(t)": r"P(t)=\frac{3\lambda}{3\lambda+\lambda_s}\left(e^{-\lambda t}-e^{-(2\lambda+\lambda_s)t}\right)+\frac{\lambda_s e^{-\lambda t}+2\lambda e^{-(3\lambda+\lambda_s)t}}{2\lambda+\lambda_s}",
            "T_0": r"T_0=\frac{1}{3\lambda+\lambda_s}+\frac{9\lambda}{(3\lambda+\lambda_s)(2\lambda+\lambda_s)}+\frac{\lambda_s}{3\lambda+\lambda_s}\left(\frac{1}{\lambda}+\frac{3}{2\lambda+\lambda_s}\right)",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f13`.",
        applicability="Дублирование с переключателем.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F1.4",
        title="Мажоритарная структура 2 из 3",
        func=lib.f14,
        mode="scalar",
        args=("t", "lam1", "lam2"),
        formulas={
            "P(t)": r"P(t)=\left(e^{-3\lambda_1 t}+3e^{-2\lambda_1 t}(1-e^{-\lambda_1 t})\right)e^{-\lambda_2 t}",
            "T_0": r"T_0=\frac{3}{2\lambda_1+\lambda_2}-\frac{2}{3\lambda_1+\lambda_2}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f14`.",
        applicability="Мажоритарная структура 2 из 3 с внешним элементом λ2.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F1.5",
        title="Две мажоритарные группы",
        func=lib.f15,
        mode="scalar",
        args=("t", "lam1", "lam2"),
        formulas={
            "P(t)": r"P(t)=\left(e^{-3\lambda_1 t}+3e^{-2\lambda_1 t}(1-e^{-\lambda_1 t})\right)\left(e^{-3\lambda_2 t}+3e^{-2\lambda_2 t}(1-e^{-\lambda_2 t})\right)",
            "T_0": r"T_0=\frac{35}{6(\lambda_1+\lambda_2)}-\frac{6}{2\lambda_1+3\lambda_2}-\frac{6}{3\lambda_1+2\lambda_2}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f15`.",
        applicability="Две мажоритарные группы.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F2.1",
        title="Восстанавливаемая система",
        func=lib.f21,
        mode="vector",
        args=("cat3_f2", "t", "n"),
        formulas={
            "cat3=1": r"K_g=\prod_i \frac{1}{1+\lambda_i T_{vi}},\quad P(t)=\prod_i e^{-t/T_{0i}}",
            "cat3=2": r"K_g=\frac{1}{1+T_v/T_0},\quad P(t)=e^{-t/T_0}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f21`.",
        applicability="Независимое и одновременное восстановление.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.2",
        title="Резерв с восстановлением",
        func=lib.f22,
        mode="scalar",
        args=("cat3_f22", "t", "n", "m", "t_v", "lam", "lam_p", "lam_s"),
        formulas={
            "cat3=1": r"T_0=\frac{\sum_{i=0}^{m} C_N^i(\lambda T_v)^i}{n\lambda C_N^m(\lambda T_v)^m},\quad T_v=\frac{T_v}{m+1}",
            "cat3=2": r"T_0=\frac{m!(\sum_{i=1}^{m}\Pi_i(\lambda T_v)^i/i!+1)}{\lambda \Pi (\lambda T_v)^m},\ a=\lambda_p/\lambda",
            "cat3=3": r"T_0=\frac{1}{n\lambda}\sum_{i=0}^{m}\frac{C_m^i i!}{(n\lambda T_v)^i}",
            "T_v,K_g(cat3=1..3)": r"T_v=\frac{t_v}{m+1},\quad K_g=\frac{T_0}{T_0+T_v}",
            "cat3=4": r"K_g=\frac{\Sigma_{up}}{\Sigma_{d2}},\quad T_0=\frac{\Sigma_{up}}{n\lambda \Sigma_{d1}}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f22`.",
        applicability="Нагруженный, облегчённый, ненагруженный резерв и ненадёжный переключатель.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.3",
        title="Мажоритарная восстанавливаемая",
        func=lib.f23,
        mode="vector",
        args=("t", "m"),
        formulas={
            "T_0": r"T_0=\frac{\prod_i(1+\lambda_i T_{vi})-\prod_i(\lambda_i T_{vi})}{\sum_i \left(\prod_j \lambda_j T_{vj}\right)/T_{vi}}",
            "K_g": r"K_g=1-\prod_i \frac{\lambda_i T_{vi}}{1+\lambda_i T_{vi}}",
            "P(t)": r"P(t)=e^{-t/T_0}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f23`.",
        applicability="Мажоритарные восстанавливаемые системы.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.4",
        title="Неполный контроль",
        func=lib.f24,
        mode="scalar",
        args=("cat3_f24", "t", "n", "m", "lam", "t_v", "t_obn", "gamma", "lam_s"),
        formulas={
            "cat3=1": r"T_0=\left[n\gamma\lambda+n(1-\gamma)\lambda \frac{\Sigma_1}{\Sigma_2}\right]^{-1},\quad K_g=\frac{\Sigma_2}{\Sigma_3}",
            "cat3=2": r"K_g=\sum_{i=0}^{m}P_i,\quad T_0=\left[n\lambda\left(\gamma+(1-\gamma)\frac{P_m}{K_g}\right)\right]^{-1}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f24`.",
        applicability="Системы с неполным контролем и параметром γ.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.5",
        title="Смешанный контроль / переключение",
        func=lib.f25,
        mode="scalar",
        args=("cat3", "t", "n", "lam", "t_v", "t_obn", "t_vp", "gamma", "p_s", "lam_p"),
        formulas={
            "T_0": r"T_0=\frac{1+a_1+a_2}{n\lambda(1-p_s+a_1+a_2)}",
            "K_g": r"K_g=\frac{1+a_1+a_2}{1+a_1+a_2+a_3+a_4}",
            "T_v": r"T_v=\frac{a_3+a_4}{n\lambda(1-p_s+a_1+a_2)}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f25`.",
        applicability="Смешанный контроль и переключение с параметрами a1-a4 по предоставленной формуле.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.6",
        title="Два разных элемента с восстановлением",
        func=lib.f26,
        mode="scalar",
        args=("t", "lam1", "lam2", "t_v1", "t_v2"),
        formulas={
            "T_0": r"T_0=\frac{1+3\lambda_1 T_{v1}}{6\lambda_1^2 T_{v1}+(1+3\lambda_1 T_{v1})\lambda_2}",
            "T_v": r"T_v=\frac{(1+3\lambda_1 T_{v1})\lambda_2 T_{v2}+3\lambda_1^2 T_{v1}^2}{6\lambda_1^2 T_{v1}+(1+3\lambda_1 T_{v1})\lambda_2}",
            "K_g": r"K_g=\frac{1}{1+T_v/T_0}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f26`.",
        applicability="Два разных элемента с восстановлением.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F2.7",
        title="Два симметричных элемента",
        func=lib.f27,
        mode="scalar",
        args=("t", "lam1", "lam2", "t_v1", "t_v2"),
        formulas={
            "T_0": r"T_0=\frac{(1+3\lambda_1 T_{v1})(1+3\lambda_2 T_{v2})}{6\lambda_1^2 T_{v1}(1+3\lambda_2 T_{v2})+6\lambda_2^2 T_{v2}(1+3\lambda_1 T_{v1})}",
            "T_v": r"T_v=\frac{3\lambda_2^2 T_{v2}^2(1+3\lambda_1 T_{v1})+3\lambda_1^2 T_{v1}^2(1+3\lambda_2 T_{v2})}{6\lambda_1^2 T_{v1}(1+3\lambda_2 T_{v2})+6\lambda_2^2 T_{v2}(1+3\lambda_1 T_{v1})}",
            "K_g": r"K_g=\frac{1}{1+T_v/T_0}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f27`.",
        applicability="Два симметричных элемента с восстановлением.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F3.1",
        title="Периодический контроль",
        func=lib.f31,
        mode="scalar",
        args=("cat3", "t", "n", "m", "lam", "t_p", "Tv_"),
        formulas={
            "T_0": r"T_0=\frac{\Sigma_1}{\Sigma_3},\quad P(t)=(\Sigma_4)^K\Sigma_5,\quad K_{og}=K_g(\Sigma_4)^{K^*}\Sigma_6",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f31`.",
        applicability="Периодический контроль для схем m из N.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F4.1",
        title="Смешанный m из n с контролем",
        func=lib.f41,
        mode="scalar",
        args=("t", "n", "m", "lam1", "lam2", "t_v2", "t_p"),
        formulas={
            "frac": r"f=\frac{1-e^{-\lambda_1 T_p}}{\lambda_1 T_p(1+\lambda_2 T_{v2})}",
            "T_0": r"T_0=\frac{\Sigma_1}{n(\lambda_1+\lambda_2)C_N^m f^n(1-f)^m}",
            "P(t)": r"P(t)=\Sigma_2,\quad K_{og}=\Sigma_3",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f41`.",
        applicability="Смешанные m из n структуры с контролем.",
        result_fields=RESULT_REPAIRABLE,
    ),
    NormativeMethodSpec(
        code="F5.1",
        title="Допустимое время простоя",
        func=lib.f51,
        mode="scalar",
        args=("t", "lam", "t_dop", "Tv_in"),
        formulas={
            "T_0": r"T_0=\frac{e^{t_{доп}/T_{вн}}}{\lambda}",
            "T_{pr}": r"T_{pr}=T_{вн}e^{-t_{доп}/T_{вн}}",
            "K_g": r"K_g=\frac{T_0}{T_0+T_{pr}}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f51`.",
        applicability="Расчёт с допустимым временем простоя.",
        result_fields=RESULT_TEMPORARY,
    ),
    NormativeMethodSpec(
        code="F6.1",
        title="Мажоритарная структура m из r1",
        func=lib.f61,
        mode="scalar",
        args=("t", "r1", "m", "lambda_upr", "lam"),
        formulas={
            "P(t)": r"P(t)=e^{-\lambda_{upr} t}\sum_{i=0}^{m} C_{r1}^i e^{-(r1-i)\lambda t}(1-e^{-\lambda t})^i",
            "T_0": r"T_0=\sum_{i=0}^{m}C_{r1}^i \sum_{j=0}^{i}\frac{(-1)^j C_i^j}{\lambda_{upr}+(r1-i+j)\lambda}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f61`.",
        applicability="Структурная надёжность мажоритарной структуры.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F6.2",
        title="Двухуровневая мажоритарность",
        func=lib.f62,
        mode="scalar",
        args=("t", "r1", "r2", "m", "lam1", "lam2", "t_upr"),
        formulas={
            "P(t)": r"P(t)=e^{-t/T_{upr}}\sum_{i=0}^{\lfloor m/r2\rfloor}\left[C_{r1}^i e^{-(r1-i)\lambda_1 t}(1-e^{-\lambda_1 t})^i \cdot \Sigma_{j}\right]",
            "T_0": r"T_0=\sum_k C_{r1}^k \Sigma_{l1}\Sigma_j\Sigma_{l2}\frac{(-1)^{l1+l2}C_k^{l1}C_j^{l2}}{1/T_{upr}+\lambda_1(r1-k+l1)+\lambda_2((r1-k)r2-j+l2)}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f62`.",
        applicability="Двухуровневая мажоритарность.",
        result_fields=RESULT_PT0,
    ),
    NormativeMethodSpec(
        code="F6.3",
        title="Трёхуровневая мажоритарность",
        func=lib.f63,
        mode="scalar",
        args=("t", "r1", "r2", "r3", "m", "lam1", "lam2", "lam3", "t_upr"),
        formulas={
            "P(t)": r"P(t)=e^{-t/T_{upr}}\sum_{k1}\sum_{k2}\sum_j C_{r1}^{k1}C_{(r1-k1)r2}^{k2}C_v^j \cdot e^{-(r1-k1)\lambda_1 t}e^{-((r1-k1)r2-k2)\lambda_2 t}e^{-(v-j)\lambda_3 t}\cdot(\ldots)",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f63`.",
        applicability="Трёхуровневая мажоритарность.",
        limitations="В предоставленной реализации T0 оставлен равным 0.0, поэтому метод выдаёт рабочий расчёт P(t), а T0 трактуется как отсутствующий в текущем наборе материалов.",
        result_fields=("P",),
    ),
    NormativeMethodSpec(
        code="F7.1",
        title="Структура с покрытием",
        func=lib.f71,
        mode="scalar",
        args=("t", "r1", "m", "t_upr", "k_upr", "ko_upr", "t_1", "k_1", "ko_1"),
        formulas={
            "K_g": r"K_g=K_{upr}\sum_{i=0}^{m} C_{r1}^i K_1^{r1-i}(1-K_1)^i",
            "K_{og}": r"K_{og}=K_{o,upr}\sum_{i=0}^{m} C_{r1}^i K_{o1}^{r1-i}(1-K_{o1})^i",
            "T_0": r"T_0=\frac{K_g}{K_{upr} C_{r1}^m K_1^{r1-m}(1-K_1)^m \left(1/T_{upr}+(r1-m)/T_1\right)}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f71`.",
        applicability="Структура с покрытием отказов.",
        result_fields=("T0", "Kg", "Kog"),
    ),
    NormativeMethodSpec(
        code="F7.2",
        title="Двухуровневая структура с покрытием",
        func=lib.f72,
        mode="scalar",
        args=("t", "r1", "r2", "m", "t_upr", "k_upr", "ko_upr", "t_1", "k_1", "ko_1", "t_2", "k_2", "ko_2"),
        formulas={
            "K_g": r"K_g=K_{upr}\sum_i \sum_j C_{r1}^i C_{(r1-i)r2}^j K_1^{r1-i}(1-K_1)^i K_2^{(r1-i)r2-j}(1-K_2)^j",
            "K_{og}": r"K_{og}=K_{o,upr}\sum_i \sum_j C_{r1}^i C_{(r1-i)r2}^j K_{o1}^{r1-i}(1-K_{o1})^i K_{o2}^{(r1-i)r2-j}(1-K_{o2})^j",
            "T_0": r"T_0=\frac{K_g}{K_{upr}\Sigma_d}",
        },
        source=f"{COMMON_SOURCE} Соотношения заданы в предоставленном методе `f72`.",
        applicability="Двухуровневая структура с покрытием отказов.",
        result_fields=("T0", "Kg", "Kog"),
    ),
)


UNSUPPORTED_METHODS: dict[str, str] = {}


def _professional_methodology_text(self: NormativeMethodSpec) -> str:
    parts = [
        f"Метод: {self.display_name}",
        f"Описание: {self.description}",
        f"Где применяется: {self.use_when}",
        f"Что рассчитывает: {self.calculates}",
    ]
    if self.parameter_docs:
        params = "; ".join(
            f"{doc.symbol} - {doc.name}: {doc.meaning} Единицы: {doc.unit}. Роль: {doc.role}"
            for doc in self.parameter_docs.values()
        )
        parts.append(f"Параметры: {params}")
    if self.mode == "vector":
        parts.append(
            "Таблица элементов: λi - интенсивность отказов i-го элемента; "
            "Tвi - среднее время восстановления i-го элемента."
        )
    all_formulas = dict(self.formulas)
    all_formulas.update(self.result_formulas)
    formulas = formula_dict_to_plain(all_formulas)
    if formulas:
        parts.append(f"Формулы: {formulas}")
    parts.append(f"Пример применения: {self.example}")
    if self.limitations:
        parts.append(f"Ограничения: {self.limitations}")
    parts.append("Нормативная база: утвержденный набор формул F1.1-F7.2, используемый в проекте.")
    return "\n".join(parts)


NormativeMethodSpec.methodology_text = property(_professional_methodology_text)

SUPPORTED_METHODS_BY_NAME = {spec.display_name: spec for spec in SUPPORTED_METHODS}
SUPPORTED_METHODS_BY_CODE = {spec.code: spec for spec in SUPPORTED_METHODS}


def supported_method_names() -> list[str]:
    return [spec.display_name for spec in SUPPORTED_METHODS]


def get_method_spec(method_name: str) -> NormativeMethodSpec | None:
    return SUPPORTED_METHODS_BY_NAME.get(method_name)


def disabled_methods_summary() -> str:
    return "Все методы F1.1-F7.2 доступны в соответствии с предоставленным набором формул."
