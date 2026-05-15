import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.main import app


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def _first_teacher_name() -> str:
    teachers = client.get("/teachers").json()
    assert teachers
    return teachers[0]["name"]


def _first_schedule_slot_and_class(schedule: dict) -> tuple[str, str]:
    for slot, entries in schedule.items():
        for class_name in entries:
            return slot, class_name
    raise AssertionError("schedule is empty")


def test_generate_options_repair_preview_accept_reject_clear_pdf_smoke() -> None:
    store = get_store()

    assert client.post("/schedule/load-demo").status_code == 200

    generate = client.post("/schedule/generate")
    assert generate.status_code == 200
    assert generate.json()["success"] is True
    assert client.get("/schedule/export/pdf").content.startswith(b"%PDF-")

    options = client.get("/schedule/options").json()
    assert options
    assert len([option for option in options if option.get("selected")]) == 1
    assert len(store.schedule_versions) == 1
    assert store.schedule_versions[-1]["source"] == "generation"

    option_to_select = options[-1]["id"]
    selected = client.post(f"/schedule/options/{option_to_select}/select")
    assert selected.status_code == 200
    assert selected.json()["selected_option_id"] == option_to_select
    assert store.schedule_versions[-1]["source"] == "option_select"
    assert store.schedule_versions[-1]["rollback"]["available"] is True

    before_reject = client.get("/schedule").json()
    slot, class_name = _first_schedule_slot_and_class(before_reject)
    repair_payload = {
        "repair_type": "repair_class",
        "repair_target": class_name,
        "repair_policy": "balanced",
        "time_budget_seconds": 5,
        "commit": False,
        "modified_constraints": [
            {
                "text": "rollback smoke class unavailable",
                "condition_type": "class_unavailable",
                "class_name": class_name,
                "slot": slot,
            }
        ],
    }

    simulated = client.post("/schedule/repair", json=repair_payload)
    assert simulated.status_code == 200
    simulated_payload = simulated.json()
    proposal_id = simulated_payload["proposal_id"]
    assert simulated_payload["simulation"] is True
    assert client.get("/schedule").json() == before_reject

    preview = client.get(f"/schedule/repair/proposals/{proposal_id}")
    assert preview.status_code == 200
    assert preview.json()["proposal_id"] == proposal_id
    assert preview.json()["proposed_schedule"] == simulated_payload["schedule"]
    assert client.get(f"/schedule/repair/proposals/{proposal_id}/export/pdf").content.startswith(b"%PDF-")

    rejected = client.delete(f"/schedule/repair/proposals/{proposal_id}")
    assert rejected.status_code == 200
    assert client.get("/schedule").json() == before_reject

    simulated_again = client.post("/schedule/repair", json=repair_payload).json()
    accepted = client.post(f"/schedule/repair/proposals/{simulated_again['proposal_id']}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["committed"] is True
    assert client.get("/schedule").json() == simulated_again["schedule"]
    assert store.schedule_versions[-1]["source"] == "accepted_proposal"
    assert store.schedule_versions[-1]["proposal_id"] == simulated_again["proposal_id"]
    assert store.schedule_versions[-1]["rollback"]["available"] is True

    cleared = client.post("/schedule/clear")
    assert cleared.status_code == 200
    assert client.get("/schedule").json() == {}
    assert client.get("/schedule/options").json() == []
    assert store.schedule_versions == []


def test_schedule_versions_api_and_rollback_contract() -> None:
    store = get_store()

    assert client.post("/schedule/load-demo").status_code == 200
    assert client.post("/schedule/generate").json()["success"] is True

    generation_version = store.schedule_versions[-1]
    generation_versions = client.get("/schedule/versions")
    assert generation_versions.status_code == 200
    generation_summary = generation_versions.json()[0]
    assert generation_summary["id"] == generation_version["version_id"]
    assert generation_summary["reason"] == "generation"
    assert generation_summary["type"] == "generation"
    assert generation_summary["created_at"]
    assert generation_summary["has_previous_schedule"] is False
    assert generation_summary["active_schedule_size"] > 0
    assert generation_summary["previous_schedule_size"] == 0

    rejected_rollback = client.post(f"/schedule/versions/{generation_version['version_id']}/rollback")
    assert rejected_rollback.status_code == 400
    assert "no previous schedule" in rejected_rollback.json()["detail"]

    options = client.get("/schedule/options").json()
    assert len(options) >= 2
    first_schedule = client.get("/schedule").json()
    selected_option_id = options[-1]["id"]
    assert client.post(f"/schedule/options/{selected_option_id}/select").status_code == 200
    selected_schedule = client.get("/schedule").json()
    assert selected_schedule != {}

    option_version = store.schedule_versions[-1]
    option_summary = client.get("/schedule/versions").json()[0]
    assert option_summary["id"] == option_version["version_id"]
    assert option_summary["reason"] == "option_select"
    assert option_summary["has_previous_schedule"] is True
    assert option_summary["previous_schedule_size"] > 0

    rollback = client.post(f"/schedule/versions/{option_version['version_id']}/rollback")
    rollback_payload = rollback.json()

    assert rollback.status_code == 200
    assert rollback_payload["success"] is True
    assert rollback_payload["rolled_back_from"] == option_version["version_id"]
    assert rollback_payload["schedule"] == first_schedule
    assert client.get("/schedule").json() == first_schedule
    assert store.schedule_versions[-1]["source"] == "rollback"
    assert store.schedule_versions[-1]["rollback"]["available"] is True
    assert store.repair_proposals == {}


def test_accepted_repair_version_can_be_rolled_back() -> None:
    store = get_store()

    assert client.post("/schedule/load-demo").status_code == 200
    assert client.post("/schedule/generate").json()["success"] is True
    before_repair = client.get("/schedule").json()

    slot, class_name = _first_schedule_slot_and_class(before_repair)
    repair_payload = {
        "repair_type": "repair_class",
        "repair_target": class_name,
        "repair_policy": "balanced",
        "time_budget_seconds": 5,
        "commit": False,
        "modified_constraints": [
            {
                "text": "rollback smoke class unavailable",
                "condition_type": "class_unavailable",
                "class_name": class_name,
                "slot": slot,
            }
        ],
    }
    simulated = client.post("/schedule/repair", json=repair_payload).json()
    proposal_id = simulated["proposal_id"]
    assert proposal_id in store.repair_proposals

    accepted = client.post(f"/schedule/repair/proposals/{proposal_id}/accept")
    assert accepted.status_code == 200
    accepted_schedule = client.get("/schedule").json()
    assert accepted_schedule == simulated["schedule"]
    assert accepted_schedule != before_repair

    accepted_version = store.schedule_versions[-1]
    versions = client.get("/schedule/versions").json()
    assert versions[0]["id"] == accepted_version["version_id"]
    assert versions[0]["reason"] == "accepted_proposal"
    assert versions[0]["has_previous_schedule"] is True

    rollback = client.post(f"/schedule/versions/{accepted_version['version_id']}/rollback")
    assert rollback.status_code == 200
    assert rollback.json()["schedule"] == before_repair
    assert client.get("/schedule").json() == before_repair
    assert store.schedule_versions[-1]["source"] == "rollback"

    assert client.post("/schedule/clear").status_code == 200
    assert client.get("/schedule/versions").json() == []
