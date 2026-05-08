from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from app.gui.gui_calculator import ModuleUniversalCalc
from app.gui.gui_visual_editor import ModuleVisualRBD
from app.core.reliability_contribution_analysis import analyze_scheme_contributions
from app.core.rbd_models import BlockModel, ConnectionModel, SchemeModel
from app.core.scheme_adapter import calculate_scheme_reliability


def _series_scheme() -> SchemeModel:
    return SchemeModel(
        name="Contribution demo",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0),
            BlockModel("pump-A", "Насос главный", "right", 120, 0, {"lambda": 0.002, "Tv": 8.0}),
            BlockModel("sensor-B", "Датчик давления", "right", 260, 0, {"lambda": 0.001, "Tv": 12.0}),
            BlockModel("end", "End", "out", 420, 0),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "pump-A", "in"),
            ConnectionModel("c2", "pump-A", "out", "sensor-B", "in"),
            ConnectionModel("c3", "sensor-B", "out", "end", "in"),
        ],
    )


def test_contribution_analysis_uses_current_scheme_element_names() -> None:
    analysis = analyze_scheme_contributions(_series_scheme(), time_horizon=100, metric="P")

    assert analysis.metric == "P"
    assert [item.name for item in analysis.elements] == ["Насос главный", "Датчик давления"]
    assert analysis.total_values["P"] > 0.0
    assert sum(item.contribution_percent["P"] for item in analysis.elements) == pytest.approx(100.0)
    assert all(item.values["P"] > 0.0 for item in analysis.elements)
    assert all("Kg" in item.values and "Kog" in item.values and "T0" in item.values for item in analysis.elements)


def test_contribution_analysis_switches_metric_and_normalizes_percent() -> None:
    analysis = analyze_scheme_contributions(_series_scheme(), time_horizon=100, metric="Kog")

    assert analysis.metric == "Kog"
    assert analysis.metric_label == "Kог"
    assert analysis.total_values["Kog"] > 0.0
    assert sum(item.contribution_percent["Kog"] for item in analysis.elements) == pytest.approx(100.0)


def test_visual_editor_contains_interactive_contribution_histogram() -> None:
    app = QApplication.instance() or QApplication([])
    editor = ModuleVisualRBD()

    editor.load_scheme_model(_series_scheme())
    editor.contribution_metric_combo.setCurrentIndex(editor.contribution_metric_combo.findData("Kg"))
    editor.refresh_contribution_analysis()

    assert app is not None
    assert editor.contribution_metric_combo.currentData() == "Kg"
    assert len(editor._contribution_bars) == 2
    assert len(editor._contribution_items) == 2
    assert "Kг" in editor.contribution_status.text()
    assert editor.contribution_group.parent() is None
    assert not editor.contribution_group.isVisible()
    editor.deleteLater()


def test_calculator_hosts_contribution_histogram_in_results_tabs() -> None:
    app = QApplication.instance() or QApplication([])
    calc = ModuleUniversalCalc()
    result = calculate_scheme_reliability(_series_scheme(), time_horizon=100, simulations=100)

    calc.apply_scheme_result(result)

    assert app is not None
    assert [calc.results_tabs.tabText(index) for index in range(calc.results_tabs.count())] == [
        "Результаты",
        "Анализ вкладов",
        "Подробности",
    ]
    assert len(calc.contribution_analysis._contribution_bars) == 2
    assert "P(t)" in calc.contribution_analysis.status.text()
    calc.deleteLater()
