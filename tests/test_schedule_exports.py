import csv
from io import StringIO

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def _generate_demo_schedule() -> None:
    client.post("/schedule/load-demo")
    response = client.post("/schedule/generate")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_csv_export_requires_generated_schedule() -> None:
    response = client.get("/schedule/export/csv")

    assert response.status_code == 404


def test_csv_export_returns_selected_schedule_file() -> None:
    _generate_demo_schedule()

    response = client.get("/schedule/export/csv")
    rows = list(csv.DictReader(StringIO(response.text)))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert rows
    assert set(rows[0]) == {"day", "start_time", "end_time", "class", "teacher", "subject"}
    assert rows[0]["day"]
    assert rows[0]["class"]
    assert rows[0]["teacher"]
    assert rows[0]["subject"]


def test_pdf_export_requires_generated_schedule() -> None:
    response = client.get("/schedule/export/pdf")

    assert response.status_code == 404


def test_pdf_export_returns_valid_pdf_file() -> None:
    _generate_demo_schedule()

    response = client.get("/schedule/export/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content[-32:]
    assert b"Jour" in response.content
    assert b"Heure" in response.content
    assert b"Classe" in response.content
    assert b"BT 0.05 0.06 0.08 rg" in response.content
    assert "Exporté".encode("latin-1") in response.content
    assert "Heure début".encode("latin-1") in response.content
    assert "Matière".encode("latin-1") in response.content


def test_pdf_export_uses_selected_schedule_option() -> None:
    _generate_demo_schedule()
    options = client.get("/schedule/options").json()
    assert options
    selected = options[-1]

    select_response = client.post(f"/schedule/options/{selected['id']}/select")
    assert select_response.status_code == 200

    response = client.get("/schedule/export/pdf")

    assert response.status_code == 200
    assert selected["schedule_signature"].encode("ascii") in response.content


def test_repair_proposal_pdf_export_requires_existing_proposal() -> None:
    response = client.get("/schedule/repair/proposals/missing/export/pdf")

    assert response.status_code == 404
    assert "Repair proposal not found" in response.json()["detail"]


def test_repair_proposal_pdf_export_returns_valid_report() -> None:
    _generate_demo_schedule()
    proposal_response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_teacher",
            "repair_target": "Mr. Khan",
            "repair_policy": "balanced",
            "time_budget_seconds": 5,
            "commit": False,
        },
    )
    assert proposal_response.status_code == 200
    proposal_id = proposal_response.json()["proposal_id"]

    response = client.get(f"/schedule/repair/proposals/{proposal_id}/export/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    assert b"%%EOF" in response.content[-32:]
    assert b"Repair Report" in response.content
    assert proposal_id.encode("ascii") in response.content
    assert b"Planning" in response.content
