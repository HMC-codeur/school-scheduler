import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def _hard_conflicts(schedule: dict) -> tuple[int, int]:
    teacher_slots: dict[tuple[str, str], int] = {}
    target_slots: dict[tuple[str, str], int] = {}
    for slot, entries in schedule.items():
        for target, cell in entries.items():
            teacher = cell["teacher"] if isinstance(cell, dict) else cell.teacher
            teacher_slots[(teacher, slot)] = teacher_slots.get((teacher, slot), 0) + 1
            target_slots[(target, slot)] = target_slots.get((target, slot), 0) + 1
    teacher_conflicts = sum(max(0, count - 1) for count in teacher_slots.values())
    target_conflicts = sum(max(0, count - 1) for count in target_slots.values())
    return teacher_conflicts, target_conflicts


def test_existing_generation_without_groups_still_works() -> None:
    assert client.post("/schedule/load-demo").status_code == 200

    response = client.post("/schedule/generate")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["scheduled_sessions"] == payload["required_sessions"]
    assert client.get("/learning-groups").json() == []


def test_learning_groups_crud_allows_multiple_levels_for_same_class_subject() -> None:
    assert client.post("/classes", json={"name": "יב", "max_lessons_per_day": 6}).status_code == 200
    assert client.post("/subjects", json={"name": "math", "hours_per_week": 2}).status_code == 200

    first = client.post("/learning-groups", json={"class_name": "יב", "subject_name": "math", "level": "débutant"})
    second = client.post("/learning-groups", json={"class_name": "יב", "subject_name": "math", "level": "avancé"})
    groups = client.get("/learning-groups").json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert [group["display_name"] for group in groups] == ["יב / math / débutant", "יב / math / avancé"]

    deleted = client.delete(f"/learning-groups/{groups[0]['id']}")
    assert deleted.status_code == 200
    assert len(client.get("/learning-groups").json()) == 1


def test_learning_groups_demo_generates_without_hard_conflicts() -> None:
    load = client.post("/schedule/load-learning-groups-demo")
    assert load.status_code == 200
    assert load.json()["stats"]["classes"] == 4
    assert load.json()["stats"]["learning_groups"] == 24

    diagnosis = client.get("/schedule/diagnose").json()
    assert diagnosis["can_generate"] is True
    assert diagnosis["stats"]["learning_groups"] == 24

    response = client.post("/schedule/generate")
    payload = response.json()
    schedule = client.get("/schedule").json()
    teacher_conflicts, target_conflicts = _hard_conflicts(schedule)

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["scheduled_sessions"] == payload["required_sessions"]
    assert payload["conflicts_count"] == 0
    assert teacher_conflicts == 0
    assert target_conflicts == 0
    assert any(" / מתמטיקה / avancé" in target for entries in schedule.values() for target in entries)
    assert any("יב" == target for entries in schedule.values() for target in entries)


def test_learning_group_diagnostics_report_group_without_teacher() -> None:
    assert client.post("/classes", json={"name": "יא", "max_lessons_per_day": 6}).status_code == 200
    assert client.post("/subjects", json={"name": "anglais", "hours_per_week": 2}).status_code == 200
    assert client.post("/subjects", json={"name": "histoire", "hours_per_week": 1}).status_code == 200
    assert client.post("/teachers", json={"name": "כהן", "subjects": ["histoire"], "max_lessons_per_day": 4}).status_code == 200
    assert client.post("/slots", json={"slot": "Mon-08:00"}).status_code == 200
    assert client.post("/slots", json={"slot": "Mon-09:00"}).status_code == 200
    assert client.post("/learning-groups", json={"class_name": "יא", "subject_name": "anglais", "level": "débutant"}).status_code == 200

    diagnosis = client.get("/schedule/diagnose").json()

    assert diagnosis["can_generate"] is False
    assert any("Groupe 'יא / anglais / débutant' sans professeur compatible" in issue for issue in diagnosis["blocking_issues"])
