from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _class_node(path: Path, class_name: str) -> ast.ClassDef:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"Class {class_name} not found in {path}")


def test_visual_editor_has_no_duplicate_public_methods() -> None:
    node = _class_node(ROOT / 'app' / 'gui' / 'gui_visual_editor.py', "ModuleVisualRBD")
    method_names = [
        item.name
        for item in node.body
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
    ]

    duplicates = sorted({name for name in method_names if method_names.count(name) > 1})

    assert duplicates == []


def test_main_window_has_no_duplicate_public_methods() -> None:
    node = _class_node(ROOT / 'app' / 'gui' / 'gui_main.py', "MainWindow")
    method_names = [
        item.name
        for item in node.body
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
    ]

    duplicates = sorted({name for name in method_names if method_names.count(name) > 1})

    assert duplicates == []


def test_import_button_is_user_facing_russian_text() -> None:
    text = (ROOT / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "Import reliability JSON/YAML" not in text
    assert "Импорт расчета JSON/YAML" in text


def test_visual_blocks_show_formula_badges() -> None:
    text = (ROOT / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _formula_badge_text" in text
    assert "painter.drawRoundedRect(badge_rect" in text
    assert "self.setToolTip(f\"{self._formula_badge_text()}: {self.name}\"" in text
