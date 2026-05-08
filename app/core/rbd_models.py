from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class BlockModel:
    """Описание блока структурной схемы надежности."""

    block_id: str
    name: str
    kind: str
    x: float
    y: float
    params: dict[str, Any] = field(default_factory=dict)
    is_subscheme: bool = False
    nested_scheme: "SchemeModel | None" = None


@dataclass(slots=True)
class ConnectionModel:
    """Описание связи между двумя блоками."""

    connection_id: str
    source_id: str
    source_port: str
    target_id: str
    target_port: str


@dataclass(slots=True)
class SchemeModel:
    """Полное описание схемы редактора в сериализуемом виде."""

    name: str = "Новая схема"
    blocks: list[BlockModel] = field(default_factory=list)
    connections: list[ConnectionModel] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def block_by_id(self, block_id: str) -> BlockModel | None:
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def block_by_name(self, name: str) -> BlockModel | None:
        for block in self.blocks:
            if block.name == name:
                return block
        return None

    def iter_blocks_recursive(self, *, include_pass_through: bool = True):
        """Yield blocks from this scheme and all nested subschemes."""
        for block in self.blocks:
            if include_pass_through or block.kind not in {"in", "out", "junction"}:
                yield block
            if block.is_subscheme and block.nested_scheme is not None:
                yield from block.nested_scheme.iter_blocks_recursive(include_pass_through=include_pass_through)

    def nested_depth(self) -> int:
        """Return maximum nesting depth; flat schemes have depth 0."""
        child_depths = [
            1 + block.nested_scheme.nested_depth()
            for block in self.blocks
            if block.is_subscheme and block.nested_scheme is not None
        ]
        return max(child_depths, default=0)


@dataclass(slots=True)
class FormulaInfo:
    """Символьная формула надежности для отображения и отчетов."""

    text: str
    latex: str = ""
    is_exact: bool = True
    note: str = ""
    structural: str = ""
    computational: str = ""
    steps: list[str] = field(default_factory=list)
    symbols: dict[str, str] = field(default_factory=dict)
    used_blocks: list[str] = field(default_factory=list)
    unused_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    package: "FormulaPackage | None" = None


FormulaMode = Literal["normative", "structural_fallback", "algorithmic"]


@dataclass(slots=True)
class FormulaItem:
    """One formula line in the canonical formula package."""

    key: str
    label: str
    symbolic_template: str
    instantiated_formula: str = ""
    numeric_value: Any = None
    comment: str = ""
    order: int = 0
    formula_id: str = ""
    source: str = ""
    verification_status: str = ""
    general_expression: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    general_latex: str = ""
    instantiated_latex: str = ""
    display_latex: str = ""
    plain_text: str = ""
    html_text: str = ""


@dataclass(slots=True)
class ParameterItem:
    """One input parameter line in the canonical formula package."""

    name: str
    value: Any
    unit: str = ""
    comment: str = ""
    order: int = 0


@dataclass(slots=True)
class FormulaPackage:
    """Canonical formula generation result consumed by UI, reports and tests."""

    formula_mode: FormulaMode
    is_normative: bool
    method_code: str | None
    title: str
    source_label: str
    source_details: str
    applicability: str
    limitations: str = ""
    warnings: list[str] = field(default_factory=list)
    formulas: list[FormulaItem] = field(default_factory=list)
    intermediate_formulas: list[FormulaItem] = field(default_factory=list)
    result_formulas: list[FormulaItem] = field(default_factory=list)
    parameter_lines: list[ParameterItem] = field(default_factory=list)
    numeric_results: dict[str, Any] = field(default_factory=dict)
    latex_text: str = ""
    plain_text: str = ""
    html_text: str = ""
    export_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


FORMULA_NOT_BUILT_MESSAGE = "Формула пока не построена. Сначала постройте схему и нажмите «Сгенерировать формулу»."


def formula_display_lines(formula: FormulaInfo | None) -> list[str]:
    """Return only user-facing final formula lines, without technical details."""
    if formula is None or not formula.text.strip():
        return []
    lines: list[str] = []
    for raw_line in formula.text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("Pсист", "Kг_сист", "T0", "λ")):
            lines.append(line)
            continue
        if not lines:
            lines.append(line)
    return lines


def formula_short_text(formula: FormulaInfo | None, *, max_lines: int = 3) -> str:
    """Compact formula text for summary panels, result screens and graph captions."""
    lines = formula_display_lines(formula)
    if not lines:
        return FORMULA_NOT_BUILT_MESSAGE
    return "\n".join(lines[:max_lines])


@dataclass(slots=True)
class CalculationResult:
    """Унифицированный результат расчета."""

    method_name: str
    indicators: dict[str, float | str]
    source: str
    formula: FormulaInfo | None = None
    formula_package: FormulaPackage | None = None
    graph_points: dict[str, list[float]] | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReportData:
    """Единый контейнер данных для генераторов отчетов."""

    title: str
    subtitle: str
    created_at: datetime
    inputs: dict[str, Any]
    results: dict[str, Any]
    method_name: str
    methodology: str
    calculation_method: str = "Аналитический расчёт"
    formula_text: str = ""
    formula_latex: str = ""
    formula_package: FormulaPackage | None = None
    scheme_name: str = ""
    scheme_image_path: str = ""
    scheme_images: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    charts: list[str] = field(default_factory=list)
    tables: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
    project_name: str = "Надёжность технических средств"
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    threshold_metric: str = "P"
    threshold_value: float | None = None
    threshold_passed: bool | None = None
    threshold_conclusion: str = ""
    final_conclusion: str = ""


@dataclass(slots=True)
class ValidationMessage:
    """Сообщение валидации."""

    level: str
    text: str


@dataclass(slots=True)
class ValidationResult:
    """Результат проверки входных данных или схемы."""

    ok: bool
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [message.text for message in self.messages if message.level == "error"]

    @property
    def warnings(self) -> list[str]:
        return [message.text for message in self.messages if message.level == "warning"]
