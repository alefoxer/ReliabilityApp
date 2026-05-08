from datetime import datetime

import pytest

from app.import_export.external_reliability_import import imported_project_from_dict, imported_project_to_scheme
from app.core.rbd_models import BlockModel, ConnectionModel, ReportData, SchemeModel
from app.reports.report_exporters import export_html, export_xlsx
from app.core.validators import validate_scheme


def test_validate_scheme_rejects_nan_and_infinite_numbers():
    scheme = SchemeModel(
        name="BadNumbers",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"lambda": float("nan"), "P": float("inf")}),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )

    result = validate_scheme(scheme)

    assert not result.ok
    assert any("конечным" in error for error in result.errors)


def test_validate_scheme_rejects_invalid_probability_and_reserve_values():
    scheme = SchemeModel(
        name="BadParams",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"P": 1.2, "reserve_count": 1.5}),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )

    result = validate_scheme(scheme)

    assert not result.ok
    assert any("0..1" in error for error in result.errors)
    assert any("целым" in error for error in result.errors)


def test_validate_scheme_rejects_k_required_greater_than_n_total():
    scheme = SchemeModel(
        name="BadKofN",
        blocks=[
            BlockModel("start", "Start", "in", 0, 0, {}),
            BlockModel("b1", "A", "right", 10, 0, {"k_required": 3, "n_total": 2}),
            BlockModel("end", "End", "out", 20, 0, {}),
        ],
        connections=[
            ConnectionModel("c1", "start", "out", "b1", "left"),
            ConnectionModel("c2", "b1", "right", "end", "in"),
        ],
    )

    result = validate_scheme(scheme)

    assert not result.ok
    assert any("k_required" in error and "n_total" in error for error in result.errors)


def test_xlsx_export_escapes_formula_like_user_strings(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    report = ReportData(
        title="=HYPERLINK(\"http://example.test\")",
        subtitle="+SUM(1,2)",
        created_at=datetime(2026, 4, 21, 12, 0),
        inputs={"comment": "@cmd", "negative text": "-1+2", "number": 7},
        results={"P": 0.9},
        method_name="F1.1",
        methodology="=not_a_formula",
    )

    target = export_xlsx(tmp_path / "safe.xlsx", report)
    workbook = openpyxl.load_workbook(target, data_only=False)

    summary = workbook.worksheets[0]
    inputs = workbook.worksheets[2]
    assert summary["A2"].value.startswith("'=")
    assert inputs["B2"].value.startswith("'@")
    assert inputs["B3"].value.startswith("'-")
    assert inputs["B4"].value == 7


def test_html_export_escapes_user_content(tmp_path):
    report = ReportData(
        title='<script>alert("x")</script>',
        subtitle="<b>bold</b>",
        created_at=datetime(2026, 4, 21, 12, 0),
        inputs={"name": "<img src=x onerror=alert(1)>"},
        results={"P": 0.9},
        method_name="F1.1",
        methodology="<script>bad()</script>",
    )

    target = export_html(tmp_path / "safe.html", report)
    content = target.read_text(encoding="utf-8")

    assert "<script>alert" not in content
    assert "&lt;script&gt;alert" in content
    assert "<img src=x" not in content


def test_imported_project_rejects_nested_scheme_cycles():
    project = imported_project_from_dict(
        {
            "schema_version": "1.0",
            "project_name": "Cycle",
            "schemes": {
                "main": {
                    "name": "Main",
                    "root": {"type": "nested_scheme", "scheme_id": "main"},
                }
            },
        }
    )

    with pytest.raises(ValueError, match="cycle"):
        imported_project_to_scheme(project, "main")
