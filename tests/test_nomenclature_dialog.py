from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.gui.gui_dialogs import DialogNomenclature


APP = QApplication.instance() or QApplication([])


def test_nomenclature_dialog_returns_full_payload() -> None:
    dialog = DialogNomenclature(initial_data={"purpose_code": "general", "usage_mode_code": "cyclic"})
    try:
        data = dialog.get_data()
    finally:
        dialog.close()

    assert {
        "purpose_code",
        "purpose_label",
        "usage_mode_code",
        "usage_mode_label",
        "recovery_mode_code",
        "recovery_mode_label",
        "requires_tto",
        "tto",
        "summary_text",
        "recommended_metrics_text",
    }.issubset(data.keys())
    assert data["purpose_code"] == "general"
    assert data["usage_mode_code"] == "cyclic"


def test_nomenclature_dialog_tto_enabled_only_for_serviceable_mode() -> None:
    dialog = DialogNomenclature()
    try:
        dialog.recovery_buttons["serviceable"].setChecked(True)
        dialog._on_selection_changed()
        assert dialog.line_tto.isEnabled() is True

        dialog.recovery_buttons["recoverable"].setChecked(True)
        dialog._on_selection_changed()
        assert dialog.line_tto.isEnabled() is False

        dialog.recovery_buttons["nonrecoverable"].setChecked(True)
        dialog._on_selection_changed()
        assert dialog.line_tto.isEnabled() is False
    finally:
        dialog.close()
