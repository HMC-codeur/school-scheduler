import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def test_diagnose_reports_missing_baseline_data() -> None:
    response = client.get("/schedule/diagnose")
    payload = response.json()

    assert response.status_code == 200
    assert set(payload) >= {"can_generate", "blocking_issues", "warnings", "stats"}
    assert payload["can_generate"] is False
    assert any("Aucune classe" in issue for issue in payload["blocking_issues"])
    assert any("Aucun professeur" in issue for issue in payload["blocking_issues"])
    assert any("Aucune matière" in issue for issue in payload["blocking_issues"])
    assert any("Aucun créneau" in issue for issue in payload["blocking_issues"])


def test_schedule_diagnose_route_is_registered() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/schedule/diagnose" in paths


def test_diagnose_reports_missing_compatible_teacher() -> None:
    client.post("/classes", json={"name": "6A", "max_lessons_per_day": 6})
    client.post("/subjects", json={"name": "Math", "hours_per_week": 1})
    client.post("/teachers", json={"name": "Mme A", "subjects": ["English"], "max_lessons_per_day": 6})
    client.post("/slots", json={"slot": "Mon-08:00"})

    payload = client.get("/schedule/diagnose").json()

    assert payload["can_generate"] is False
    assert any("Aucun professeur compatible" in issue for issue in payload["blocking_issues"])
    assert any("matière inconnue" in warning for warning in payload["warnings"])


def test_diagnose_reports_capacity_insufficient() -> None:
    client.post("/classes", json={"name": "6A", "max_lessons_per_day": 6})
    client.post("/subjects", json={"name": "Math", "hours_per_week": 2})
    client.post("/teachers", json={"name": "Mme A", "subjects": ["Math"], "max_lessons_per_day": 6})
    client.post("/slots", json={"slot": "Mon-08:00"})

    payload = client.get("/schedule/diagnose").json()

    assert payload["can_generate"] is False
    assert any("Capacité insuffisante" in issue for issue in payload["blocking_issues"])


def test_diagnose_reports_impossible_constraints() -> None:
    client.post("/classes", json={"name": "6A", "max_lessons_per_day": 6})
    client.post("/subjects", json={"name": "Math", "hours_per_week": 1})
    client.post("/teachers", json={"name": "Mme A", "subjects": ["Math"], "max_lessons_per_day": 6})
    client.post("/slots", json={"slot": "Mon-08:00"})
    client.post(
        "/conditions",
        json={
            "text": "Classe bloquée",
            "condition_type": "class_unavailable",
            "class_name": "6A",
            "slot": "Mon-08:00",
        },
    )

    payload = client.get("/schedule/diagnose").json()

    assert payload["can_generate"] is False
    assert any("Contrainte impossible" in issue for issue in payload["blocking_issues"])
