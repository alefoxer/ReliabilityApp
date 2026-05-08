from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtWidgets import QApplication

from app.gui.gui_visual_editor import ModuleVisualRBD, RBDBlock
from app.core.rbd_models import BlockModel, SchemeModel


def test_subscheme_editor_fits_loaded_content_and_uses_safe_default_offsets():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _refresh_scene_viewport" in source
    assert "self._refresh_scene_viewport(fit=True)" in source
    assert 'BlockModel("nested_start", "Start", "in", 120, 140, {})' in source
    assert 'BlockModel("nested_end", "End", "out", 360, 140, {})' in source


def test_subscheme_editor_uses_full_height_without_header_hint():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert 'layout.setContentsMargins(0, 0, 0, 0)' in source
    assert 'layout.addWidget(editor, 1)' in source
    assert "Текущий уровень:" not in source


def test_subscheme_blocks_have_visible_layer_marker():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'app' / 'gui' / 'gui_visual_editor.py').read_text(encoding="utf-8")

    assert "def _draw_subscheme_marker" in source
    assert "role = _block_role(self.props, self.is_subscheme)" in source
    assert 'has_subscheme_marker = self.is_subscheme or role == "subscheme"' in source
    assert "self._draw_subscheme_marker(painter, body)" in source
    assert 'QPen(QColor("#2563eb"), 2.8)' in source
    assert 'QPen(QColor("#1d4ed8"), 1.6)' in source
    assert "inner = body.adjusted(3, 3, -3, -3)" in source
    assert "painter.drawRoundedRect(inner, 5, 5)" in source
    assert "corner_size = 9.0" in source
    assert "body.right() - corner_size - 2" in source
    assert 'block.props["block_role"] = "subscheme"' in source
    assert "self.scene.update()" in source

    marker_source = source.split("def _draw_subscheme_marker", 1)[1].split("def draw_port", 1)[0]
    assert "x - 10" not in marker_source


def test_load_scheme_model_preserves_subscheme_flag():
    app = QApplication.instance() or QApplication([])
    editor = ModuleVisualRBD()
    nested = SchemeModel(
        name="Nested",
        blocks=[
            BlockModel("nested_start", "Start", "in", 120, 140, {}),
            BlockModel("nested_end", "End", "out", 360, 140, {}),
        ],
        connections=[],
    )
    scheme = SchemeModel(
        name="Main",
        blocks=[
            BlockModel("sub", "Составной", "right", 160, 120, {"block_role": "subscheme"}, is_subscheme=True, nested_scheme=nested),
        ],
        connections=[],
    )

    editor.load_scheme_model(scheme)

    assert app is not None
    assert editor.block_items["sub"].is_subscheme is True
    assert editor.block_items["sub"].nested_scheme is nested
    editor.deleteLater()


def test_regular_block_uses_edge_port_stubs_instead_of_center_line():
    block = RBDBlock("LongLabel", "right", 0, 0)
    body = QRectF(-24, -14, 48, 28)

    segments = block._port_stub_segments(body)

    assert segments == [
        (QPointF(-24, 0), QPointF(-40, 0), "left"),
        (QPointF(24, 0), QPointF(40, 0), "right"),
    ]


def test_in_and_out_blocks_keep_original_port_layout():
    in_block = RBDBlock("Start", "in", 0, 0)
    out_block = RBDBlock("End", "out", 0, 0)
    body = QRectF(-24, -14, 48, 28)

    assert in_block._port_stub_segments(body) == [(QPointF(0, 0), QPointF(50, 0), "out")]
    assert out_block._port_stub_segments(body) == [(QPointF(0, 0), QPointF(0, 0), "in")]
