from __future__ import annotations

from pathlib import Path

from app.import_export.import_safety import ALLOWED_BLOCK_KINDS, ensure_finite_float
from app.core.rbd_models import BlockModel, SchemeModel, ValidationMessage, ValidationResult


def validate_positive_number(name: str, value: float, *, allow_zero: bool = False) -> ValidationResult:
    try:
        number = ensure_finite_float(value, name)
    except ValueError:
        return ValidationResult(ok=False, messages=[ValidationMessage("error", f"Параметр «{name}» должен быть конечным числом.")])
    threshold_ok = number >= 0 if allow_zero else number > 0
    if threshold_ok:
        return ValidationResult(ok=True)
    ending = "неотрицательным" if allow_zero else "положительным"
    return ValidationResult(ok=False, messages=[ValidationMessage("error", f"Параметр «{name}» должен быть {ending}.")])


def validate_probability(name: str, value: float) -> ValidationResult:
    try:
        number = ensure_finite_float(value, name)
    except ValueError:
        return ValidationResult(ok=False, messages=[ValidationMessage("error", f"Параметр «{name}» должен быть конечным числом.")])
    if 0 <= number <= 1:
        return ValidationResult(ok=True)
    return ValidationResult(ok=False, messages=[ValidationMessage("error", f"Параметр «{name}» должен быть в диапазоне от 0 до 1.")])


def validate_scheme(scheme: SchemeModel, *, _path: str | None = None, _seen: set[int] | None = None) -> ValidationResult:
    """Validate a scheme recursively, including nested subschemes."""
    path = _path or scheme.name or "Схема"
    seen = _seen or set()
    if id(scheme) in seen:
        return ValidationResult(ok=False, messages=[ValidationMessage("error", f"{path}: обнаружена циклическая ссылка на подсхему.")])
    seen.add(id(scheme))
    messages: list[ValidationMessage] = []
    if not scheme.blocks:
        return ValidationResult(ok=False, messages=[ValidationMessage("error", f"{path}: схема пустая. Добавьте Р’С…РѕРґ, Р’С‹С…РѕРґ, блоки и связи.")])

    block_ids = [block.block_id for block in scheme.blocks]
    ids = set(block_ids)
    if len(block_ids) != len(ids):
        messages.append(ValidationMessage("error", f"{path}: идентификаторы блоков должны быть уникальными."))

    names = [block.name for block in scheme.blocks]
    if len(names) != len(set(names)):
        messages.append(ValidationMessage("error", f"{path}: имена блоков должны быть уникальными."))

    start_count = sum(1 for block in scheme.blocks if block.kind == "in")
    end_count = sum(1 for block in scheme.blocks if block.kind == "out")
    if start_count != 1:
        messages.append(ValidationMessage("error", f"{path}: в схеме должен быть ровно один блок «Вход» / «Р’С…РѕРґ» / «Âõîä»."))
    if end_count != 1:
        messages.append(ValidationMessage("error", f"{path}: в схеме должен быть ровно один блок «Выход» / «Р’С‹С…РѕРґ» / «Âûõîä»."))

    incoming: dict[str, int] = {block.block_id: 0 for block in scheme.blocks}
    outgoing: dict[str, int] = {block.block_id: 0 for block in scheme.blocks}
    seen_edges: set[tuple[str, str, str, str]] = set()
    for connection in scheme.connections:
        edge_key = (connection.source_id, connection.source_port, connection.target_id, connection.target_port)
        if edge_key in seen_edges:
            messages.append(ValidationMessage("warning", f"{path}: в схеме есть дублирующиеся связи."))
            continue
        seen_edges.add(edge_key)

        if connection.source_id not in ids or connection.target_id not in ids:
            messages.append(ValidationMessage("error", f"{path}: обнаружена связь с несуществующим блоком."))
            continue
        if connection.source_id == connection.target_id:
            messages.append(ValidationMessage("error", f"{path}: связь блока с самим собой не допускается."))
            continue
        outgoing[connection.source_id] += 1
        incoming[connection.target_id] += 1

    for block in scheme.blocks:
        if block.kind not in ALLOWED_BLOCK_KINDS:
            messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» неизвестный тип «{block.kind}»."))
        if block.kind == "in" and incoming[block.block_id] > 0:
            messages.append(ValidationMessage("error", f"{path}: у блока «Р’С…РѕРґ» не должно быть входящих связей."))
        if block.kind == "out" and outgoing[block.block_id] > 0:
            messages.append(ValidationMessage("error", f"{path}: у блока «Р’С‹С…РѕРґ» не должно быть исходящих связей."))
        if block.kind not in {"in", "out"} and incoming[block.block_id] == 0:
            messages.append(ValidationMessage("warning", f"{path}: блок «{block.name}» не имеет входящих связей."))
        if block.kind not in {"in", "out"} and outgoing[block.block_id] == 0:
            messages.append(ValidationMessage("warning", f"{path}: блок «{block.name}» не имеет исходящих связей."))

    if start_count == 1 and end_count == 1:
        start_id = next(block.block_id for block in scheme.blocks if block.kind == "in")
        end_id = next(block.block_id for block in scheme.blocks if block.kind == "out")
        forward: dict[str, list[str]] = {block.block_id: [] for block in scheme.blocks}
        reverse: dict[str, list[str]] = {block.block_id: [] for block in scheme.blocks}
        for connection in scheme.connections:
            if connection.source_id in ids and connection.target_id in ids and connection.source_id != connection.target_id:
                forward[connection.source_id].append(connection.target_id)
                reverse[connection.target_id].append(connection.source_id)
        reachable_from_start = _reachable(forward, start_id)
        can_reach_end = _reachable(reverse, end_id)
        active_ids = reachable_from_start & can_reach_end
        if end_id not in reachable_from_start:
            messages.append(ValidationMessage("error", f"{path}: нет расчетного пути от входа к выходу."))
        for block in scheme.blocks:
            if block.kind not in {"in", "out"} and block.block_id not in active_ids:
                messages.append(
                    ValidationMessage(
                        "warning",
                        f"{path}: блок «{block.name}» не входит в путь от входа к выходу и не будет включен / РЅРµ Р±СѓРґРµС‚ РІРєР»СЋС‡РµРЅ / íå áóäåò âêëþ÷åí в формулу.",
                    )
                )
        if _has_cycle(forward):
            messages.append(ValidationMessage("error", f"{path}: обнаружен цикл; циклические схемы не поддерживаются."))

    for block in scheme.blocks:
        messages.extend(_validate_block_semantics(block, path))
        if block.is_subscheme:
            if block.nested_scheme is None:
                messages.append(ValidationMessage("error", f"{path}: блок «{block.name}» помечен как подсхема, но внутренняя схема не задана."))
                continue
            nested_result = validate_scheme(block.nested_scheme, _path=f"{path} / {block.name}", _seen=seen)
            messages.extend(nested_result.messages)
    seen.discard(id(scheme))

    return ValidationResult(ok=not any(message.level == "error" for message in messages), messages=messages)


def _reachable(graph: dict[str, list[str]], start_id: str) -> set[str]:
    visited: set[str] = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(graph.get(current, []))
    return visited


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for next_id in graph.get(node_id, []):
            if visit(next_id):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in graph)


def _validate_block_semantics(block: BlockModel, path: str) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    if block.kind in {"in", "out", "junction"}:
        return messages
    role = _block_role(block)
    for key in ("P", "Kg", "K"):
        if key in block.params:
            _validate_probability_param(block, key, path, messages)
    for key in ("lambda", "Tv", "T0", "t"):
        if key in block.params:
            _validate_non_negative_param(block, key, path, messages)
    if "reserve_count" in block.params:
        _validate_integer_param(block, "reserve_count", path, messages, minimum=0)
    if role == "reserve" and "reserve_count" not in block.params:
        messages.append(ValidationMessage("error", f"{path}: для блока «{block.name}» типа «Элемент с резервом» нужно задать reserve_count."))
    if role == "k_of_n":
        if "k_required" not in block.params or "n_total" not in block.params:
            messages.append(ValidationMessage("error", f"{path}: для блока «{block.name}» нужны k_required и n_total."))
        else:
            k_value = _validate_integer_param(block, "k_required", path, messages, minimum=1)
            n_value = _validate_integer_param(block, "n_total", path, messages, minimum=1)
            if k_value is not None and n_value is not None and k_value > n_value:
                messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр k_required не может быть больше n_total."))
    if role == "ordinary" and any(key in block.params for key in ("reserve_count", "k_required", "n_total", "reserve_type")):
        messages.append(ValidationMessage("warning", f"{path}: у обычного блока «{block.name}» заданы специальные параметры резерва."))
    return messages


def _validate_probability_param(block: BlockModel, key: str, path: str, messages: list[ValidationMessage]) -> None:
    try:
        value = ensure_finite_float(block.params[key], key)
    except ValueError:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть конечным числом."))
        return
    if not 0 <= value <= 1:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть в диапазоне 0..1."))


def _validate_non_negative_param(block: BlockModel, key: str, path: str, messages: list[ValidationMessage]) -> None:
    try:
        value = ensure_finite_float(block.params[key], key)
    except ValueError:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть конечным числом."))
        return
    if value < 0:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} не может быть отрицательным."))


def _validate_integer_param(block: BlockModel, key: str, path: str, messages: list[ValidationMessage], *, minimum: int) -> int | None:
    try:
        value = ensure_finite_float(block.params[key], key)
    except ValueError:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть конечным числом."))
        return None
    integer = int(value)
    if value != integer:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть целым числом."))
        return None
    if integer < minimum:
        messages.append(ValidationMessage("error", f"{path}: у блока «{block.name}» параметр {key} должен быть не меньше {minimum}."))
        return None
    return integer


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


def validate_scheme_file(path: str | Path) -> ValidationResult:
    candidate = Path(path)
    if not candidate.exists():
        return ValidationResult(ok=False, messages=[ValidationMessage("error", "Файл схемы не найден.")])
    if candidate.suffix.lower() != ".json":
        return ValidationResult(ok=False, messages=[ValidationMessage("error", "Поддерживается только формат JSON.")])
    return ValidationResult(ok=True)
