from __future__ import annotations

from zipfile import ZipFile
from datetime import datetime

import pytest

from app.core.rbd_models import ReportData
from app.reports.report_exporters import export_docx, export_xlsx


def _sample_report() -> ReportData:
    return ReportData(
        title="Отчет по расчету",
        subtitle="Инженерный отчет",
        created_at=datetime(2026, 4, 21, 12, 0),
        inputs={"lambda": 0.001, "t": 1000},
        results={"P": 0.9, "T0": 1000},
        method_name="F1.1",
        methodology="Методическая формула проекта",
        calculation_method="Аналитический расчет",
        formula_text="P(t)=e^{-lambda t}",
    )


def test_export_docx_does_not_show_internal_auto_id(tmp_path):
    pytest.importorskip("docx")
    report = _sample_report()
    report.method_name = "AUTO.COMPOSITION"
    report.formula_text = "Pсист(t)=B1\nAUTO.COMPOSITION"
    target = export_docx(tmp_path / "report.docx", report)

    with ZipFile(target) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "AUTO.COMPOSITION" not in document_xml
    assert "Pсист(t)=B1" in document_xml


def test_export_xlsx_does_not_show_internal_auto_id(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    report = _sample_report()
    report.method_name = "AUTO.COMPOSITION"
    report.formula_text = "Pсист(t)=B1\nAUTO.COMPOSITION"
    target = export_xlsx(tmp_path / "report.xlsx", report)
    workbook = openpyxl.load_workbook(target)

    values = [
        str(cell.value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    ]

    assert all("AUTO.COMPOSITION" not in value for value in values)
    assert any("Pсист(t)=B1" in value for value in values)
