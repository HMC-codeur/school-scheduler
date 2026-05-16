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


def _xml_xlsx_fixture(rows: list[list[str]]) -> bytes:
    cells = []
    for row_index, row in enumerate(rows, start=1):
        cell_xml = []
        for column_index, value in enumerate(row, start=1):
            if value == "":
                continue
            reference = f"{_column_name(column_index)}{row_index}"
            cell_xml.append(f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        cells.append(f'<row r="{row_index}">{"".join(cell_xml)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(cells)}</sheetData>'
        '</worksheet>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Planning" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def _xlsx_fixture(rows: list[list[str]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError:
        return _xml_xlsx_fixture(rows)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Planning"
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _simple_workbook() -> bytes:
    return _xlsx_fixture(
        [
            ["", "Lundi", "Mardi"],
            ["08:00-09:00", "Math\nClasse: 7A\nProf: David Cohen\nSalle: 101", "Physique\nClass: 8B\nTeacher: Miriam Israeli\nRoom: 202"],
            ["09:00-10:00", "English 7A\nTeacher: Dana", ""],
        ]
    )


def _preview(workbook: bytes):
    return client.post(
        "/schedule/import/excel/preview",
        files={"file": ("planning.xlsx", workbook, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def test_excel_import_preview_extracts_real_workbook_without_mutating_store() -> None:
    response = _preview(_simple_workbook())
    payload = response.json()

    assert response.status_code == 200
    assert payload["days"] == ["Lundi", "Mardi"]
    assert payload["slots"] == ["08:00-09:00", "09:00-10:00"]
    assert payload["classes"] == ["7A", "8B"]
    assert payload["teachers"] == ["David Cohen", "Miriam Israeli", "Dana"]
    assert payload["subjects"] == ["Math", "Physique", "English"]
    assert payload["rooms"] == ["101", "202"]
    assert payload["counts"]["lessons"] == 3
    assert payload["lessons"][0]["slot_key"] == "Mon-08:00"
    assert payload["lessons"][0]["session_id"].startswith("imp_mon_0800_7A_Math")
    assert payload["can_commit"] is True
    assert payload["import_id"]
    assert payload["errors"] == []
    assert not get_store().classes
    assert not get_store().schedule


def test_excel_import_preview_empty_file_returns_400() -> None:
    response = _preview(_xlsx_fixture([]))

    assert response.status_code == 400
    assert "Feuille vide" in str(response.json()["detail"])


def test_excel_import_preview_rejects_invalid_xlsx() -> None:
    response = _preview(b"not a zip")

    assert response.status_code == 400
    assert "corrompu" in str(response.json()["detail"])


def test_excel_import_preview_supports_french_hebrew_english_aliases() -> None:
    workbook = _xlsx_fixture(
        [
            ["", "יום ראשון", "Monday", "Mardi"],
            ["08:00", "מתמטיקה\nכיתה: 6א\nמורה: כהן\nחדר: 101", "Science\nClass: 7A\nTeacher: Smith\nRoom: Lab", "Français\nClasse: 8B\nProfesseur: Levy\nSalle: 202"],
        ]
    )

    payload = _preview(workbook).json()

    assert payload["days"] == ["יום ראשון", "Monday", "Mardi"]
    assert payload["classes"] == ["6א", "7A", "8B"]
    assert payload["teachers"] == ["כהן", "Smith", "Levy"]
    assert payload["rooms"] == ["101", "Lab", "202"]
    assert [lesson["slot_key"] for lesson in payload["lessons"]] == ["Sun-08:00", "Mon-08:00", "Tue-08:00"]


def test_excel_import_commit_replace_success_and_downstream_exports() -> None:
    preview = _preview(_simple_workbook()).json()
    response = client.post("/schedule/import/excel/commit", json={"import_id": preview["import_id"], "mode": "replace"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["active_schedule_entries_count"] == 3
    assert payload["schedule_option_id"].startswith("import-")
    assert client.get("/schedule").json()["Mon-08:00"]["7A"]["subject"] == "Math"
    assert client.get("/schedule/export/csv").status_code == 200
    assert client.get("/schedule/export/pdf").status_code == 200
    assert client.get("/schedule/export/json").status_code == 200
    diagnose = client.get("/schedule/diagnose").json()
    assert "active_schedule" in diagnose
    repair = client.post(
        "/schedule/repair",
        json={"repair_type": "repair_teacher", "repair_target": "David Cohen", "repair_policy": "balanced", "commit": False},
    )
    assert repair.status_code in {200, 400}


def test_excel_import_commit_dry_run_does_not_write() -> None:
    preview = _preview(_simple_workbook()).json()

    response = client.post("/schedule/import/excel/commit", json={"import_id": preview["import_id"], "dry_run": True})

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert get_store().schedule == {}
    assert client.get("/schedule").json() == {}


def test_excel_import_commit_create_missing_entities_false_errors() -> None:
    preview = _preview(_simple_workbook()).json()

    response = client.post(
        "/schedule/import/excel/commit",
        json={"lessons": preview["lessons"], "create_missing_entities": False},
    )

    assert response.status_code == 400
    assert "Entités inconnues" in str(response.json()["detail"])


def test_excel_import_commit_merge_conflict_fails() -> None:
    preview = _preview(_simple_workbook()).json()
    assert client.post("/schedule/import/excel/commit", json={"lessons": preview["lessons"], "mode": "replace"}).status_code == 200

    response = client.post("/schedule/import/excel/commit", json={"lessons": preview["lessons"], "mode": "merge"})

    assert response.status_code == 400
    assert "Conflit" in str(response.json()["detail"])


def test_excel_import_commit_detects_teacher_conflict() -> None:
    workbook = _xlsx_fixture(
        [
            ["", "Lundi", "Mardi"],
            ["08:00", "Math\nClasse: 7A\nProf: David Cohen", "Science\nClasse: 8B\nProf: David Cohen"],
        ]
    )
    preview = _preview(workbook).json()
    preview["lessons"][1]["slot_key"] = preview["lessons"][0]["slot_key"]

    response = client.post("/schedule/import/excel/commit", json={"lessons": preview["lessons"]})

    assert response.status_code == 400
    assert "Conflit professeur" in str(response.json()["detail"])


def test_excel_import_persists_in_sqlite_after_repository_recreation() -> None:
    preview = _preview(_simple_workbook()).json()
    assert client.post("/schedule/import/excel/commit", json={"import_id": preview["import_id"]}).status_code == 200

    from backend.data.sqlite_repository import SQLiteRepository

    restarted = SQLiteRepository(get_store().db_path)
    assert restarted.schedule["Mon-08:00"]["7A"].subject == "Math"
