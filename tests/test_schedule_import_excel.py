from __future__ import annotations

from html import escape
from io import BytesIO
import zipfile

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _xlsx_fixture(rows: list[list[str]]) -> bytes:
    cells = []
    for row_index, row in enumerate(rows, start=1):
        cell_xml = []
        for column_index, value in enumerate(row, start=1):
            if value == "":
                continue
            reference = f"{_column_name(column_index)}{row_index}"
            cell_xml.append(
                f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            )
        cells.append(f'<row r="{row_index}">{"".join(cell_xml)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells)}</sheetData>'
        '</worksheet>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Planning" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def test_excel_import_preview_extracts_hebrew_schedule_without_mutating_store() -> None:
    workbook = _xlsx_fixture(
        [
            ["", "יום ראשון", "יום שני", "יום שלישי"],
            ["08:00", "מתמטיקה 6א\nמורה: כהן\nחדר: 101", "אנגלית 6ב\nמורה: לוי\nחדר: 202", ""],
            ["09:00", "מדעים כיתה 7א\nמורה: מזרחי\nחדר: מעבדה", "", "היסטוריה 8A\nמורה: דוד"],
        ]
    )

    response = client.post(
        "/schedule/import/excel/preview",
        files={"file": ("planning.xlsx", workbook, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["days"] == ["יום ראשון", "יום שני", "יום שלישי"]
    assert payload["slots"] == ["08:00", "09:00"]
    assert payload["classes"] == ["6א", "6ב", "7א", "8A"]
    assert payload["teachers"] == ["כהן", "לוי", "מזרחי", "דוד"]
    assert payload["subjects"] == ["מתמטיקה", "אנגלית", "מדעים", "היסטוריה"]
    assert payload["rooms"] == ["101", "202", "מעבדה"]
    assert payload["counts"]["lessons"] == 4
    assert payload["lessons"][0] == {
        "subject": "מתמטיקה",
        "class_name": "6א",
        "teacher": "כהן",
        "room": "101",
        "day": "יום ראשון",
        "slot": "08:00",
        "row": 2,
        "column": 2,
        "raw": "מתמטיקה 6א\nמורה: כהן\nחדר: 101",
    }
    assert payload["errors"] == []
    assert not get_store().classes
    assert not get_store().schedule


def test_excel_import_preview_rejects_invalid_xlsx() -> None:
    response = client.post(
        "/schedule/import/excel/preview",
        files={"file": ("planning.xlsx", b"not a zip", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 400
    assert "invalide" in response.json()["detail"][0]
