import pytest

pytest.importorskip("ortools")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from backend.data.store import get_store
from backend.benchmarks.scheduler_benchmark import build_dataset, DATASETS
from backend.benchmarks.solver_benchmark import (
    run_delta_benchmark,
    run_delta_medium_policy_benchmark,
    run_solver_benchmarks,
)
from backend.main import app
from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.scoring import analyze_schedule
from backend.services.solver.legacy_solver_adapter import LegacySolverAdapter
from backend.services.solver.feasibility import check_feasibility
from backend.services.solver.models import ScheduleInput, SolverAssignment
from backend.services.solver.ortools_solver import ORToolsMultiStrategySolver, ORToolsSolver
from backend.services.solver.repair import repair_schedule
from backend.services.solver.stability import schedule_with_session_ids


client = TestClient(app)


def setup_function() -> None:
    get_store().clear_all()


def _assert_valid_hard_schedule(result, classes, teachers, subjects, slots) -> None:
    metrics = analyze_schedule(result.schedule, classes, teachers, subjects, slots)
    assert result.success is True
    assert result.metrics.scheduled_sessions == result.metrics.required_sessions
    assert metrics["teacher_conflicts"] == 0
    assert metrics["class_conflicts"] == 0
    assert metrics["incompatible_assignments"] == 0
    assert metrics["unplaced_sessions"] == 0


def test_legacy_solver_adapter_still_generates_schedule() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00"]

    result = LegacySolverAdapter().solve(ScheduleInput(classes, teachers, subjects, slots))

    assert result.success is True
    assert result.metrics.engine == "legacy"
    assert result.metrics.scheduled_sessions == 1


def test_ortools_generates_simple_schedule_without_conflict() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1), Subject(name="English", hours_per_week=1)]
    teachers = [
        Teacher(id=1, name="T1", subjects=["Math"]),
        Teacher(id=2, name="T2", subjects=["English"]),
    ]
    slots = ["Mon-08:00", "Mon-09:00"]

    result = ORToolsSolver().solve(ScheduleInput(classes, teachers, subjects, slots))

    _assert_valid_hard_schedule(result, classes, teachers, subjects, slots)


def test_ortools_fails_cleanly_without_compatible_teacher() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["English"])]
    slots = ["Mon-08:00"]

    result = ORToolsSolver().solve(ScheduleInput(classes, teachers, subjects, slots))

    assert result.success is False
    assert "feasibility check failed" in result.message
    assert result.metrics.scheduled_sessions == 0
    assert result.metrics.required_sessions == 1


def test_feasibility_check_reports_blocking_subject_and_capacity() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2)]
    teachers = [Teacher(id=1, name="T1", subjects=["English"])]
    slots = ["Mon-08:00"]

    report = check_feasibility(ScheduleInput(classes, teachers, subjects, slots))

    assert report.feasible is False
    codes = {issue.code for issue in report.issues}
    assert "subject_without_teacher" in codes
    assert "global_class_slots_insufficient" in codes


def test_ortools_avoids_teacher_double_booking() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Mon-09:00"]

    result = ORToolsSolver().solve(ScheduleInput(classes, teachers, subjects, slots))
    metrics = analyze_schedule(result.schedule, classes, teachers, subjects, slots)

    assert result.success is True
    assert metrics["teacher_conflicts"] == 0


def test_ortools_avoids_class_double_booking() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1), Subject(name="English", hours_per_week=1)]
    teachers = [
        Teacher(id=1, name="T1", subjects=["Math"]),
        Teacher(id=2, name="T2", subjects=["English"]),
    ]
    slots = ["Mon-08:00", "Mon-09:00"]

    result = ORToolsSolver().solve(ScheduleInput(classes, teachers, subjects, slots))
    metrics = analyze_schedule(result.schedule, classes, teachers, subjects, slots)

    assert result.success is True
    assert metrics["class_conflicts"] == 0


def test_current_generate_endpoint_still_uses_legacy_by_default() -> None:
    client.post("/schedule/load-demo")

    response = client.post("/schedule/generate")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert client.get("/schedule/options").json()[0]["id"].startswith("option-")


def test_ortools_generate_endpoint_works_with_engine_parameter() -> None:
    client.post("/classes", json={"name": "A", "max_lessons_per_day": 6})
    client.post("/subjects", json={"name": "Math", "hours_per_week": 1})
    client.post("/teachers", json={"name": "T1", "subjects": ["Math"], "max_lessons_per_day": 6})
    client.post("/slots", json={"slot": "Mon-08:00"})

    response = client.post("/schedule/generate?engine=ortools")
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["scheduled_sessions"] == payload["required_sessions"] == 1
    cell = next(iter(next(iter(payload["schedule"].values())).values()))
    assert cell["session_id"]
    assert client.get("/schedule/options").json()[0]["id"] == "ortools-1"


def test_ortools_distinguishes_repeated_subject_sessions_with_session_ids() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]

    result = ORToolsSolver(max_time_seconds=3.0).solve(ScheduleInput(classes, teachers, subjects, slots))

    _assert_valid_hard_schedule(result, classes, teachers, subjects, slots)
    session_ids = [
        cell.session_id
        for entries in result.schedule.values()
        for cell in entries.values()
    ]
    assert len(session_ids) == 2
    assert len(set(session_ids)) == 2
    assert all(session_id and session_id.startswith("session-a-math-") for session_id in session_ids)


def _seed_repair_api_dataset() -> dict:
    class_a = client.post("/classes", json={"name": "A", "max_lessons_per_day": 3}).json()
    class_b = client.post("/classes", json={"name": "B", "max_lessons_per_day": 3}).json()
    client.post("/subjects", json={"name": "Math", "hours_per_week": 1})
    teacher_1 = client.post(
        "/teachers",
        json={"name": "T1", "subjects": ["Math"], "max_lessons_per_day": 3},
    ).json()
    teacher_2 = client.post(
        "/teachers",
        json={"name": "T2", "subjects": ["Math"], "max_lessons_per_day": 3},
    ).json()
    for slot in ["Mon-08:00", "Tue-08:00", "Wed-08:00"]:
        client.post("/slots", json={"slot": slot})
    generated = client.post("/schedule/generate?engine=ortools")
    assert generated.status_code == 200
    assert generated.json()["success"] is True
    return {
        "class_a": class_a,
        "class_b": class_b,
        "teacher_1": teacher_1,
        "teacher_2": teacher_2,
    }


def _first_schedule_entry(schedule: dict) -> tuple[str, str, dict]:
    slot = next(iter(schedule))
    class_name, cell = next(iter(schedule[slot].items()))
    return slot, class_name, cell


def test_repair_endpoint_without_existing_schedule_returns_clear_error() -> None:
    response = client.post("/schedule/repair", json={"repair_type": "repair_day", "day": "Mon"})

    assert response.status_code == 400
    assert "No existing schedule" in response.json()["detail"]


def test_repair_endpoint_repair_class_works_and_returns_stability_metrics() -> None:
    ids = _seed_repair_api_dataset()

    response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "class_id": ids["class_a"]["id"],
            "repair_policy": "balanced",
            "time_budget_seconds": 3,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["hard_conflicts"] == 0
    assert payload["repair_type"] == "repair_class"
    assert payload["repair_policy"] == "balanced"
    assert "stability_score" in payload
    assert "repair_attempts" in payload["diagnostics"]
    assert payload["committed"] is True
    assert payload["simulation"] is False


def test_repair_endpoint_commit_false_never_modifies_current_schedule() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "simulate class unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    )
    payload = response.json()
    after = client.get("/schedule").json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["committed"] is False
    assert payload["simulation"] is True
    assert payload["proposal_id"]
    assert payload["message"] == "Repair simulated successfully. Current schedule unchanged."
    assert payload["changed_items_count"] == len(payload["changed_items"])
    assert payload["changed_items_count"] >= 1
    first_change = payload["changed_items"][0]
    assert first_change["session_id"]
    assert first_change["class_id"] is not None
    assert first_change["subject_id"] is not None
    assert first_change["change_type"] in {
        "slot_changed",
        "teacher_changed",
        "slot_and_teacher_changed",
        "added",
        "removed",
    }
    assert first_change["old_slot"] or first_change["new_slot"]
    assert after == before


def test_repair_proposal_accept_applies_simulated_schedule_and_preserves_changes() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    simulated = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "proposal class unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    ).json()
    proposal_id = simulated["proposal_id"]

    accepted_response = client.post(f"/schedule/repair/proposals/{proposal_id}/accept")
    accepted = accepted_response.json()
    after = client.get("/schedule").json()

    assert accepted_response.status_code == 200
    assert accepted["success"] is True
    assert accepted["committed"] is True
    assert accepted["simulation"] is False
    assert accepted["proposal_id"] == proposal_id
    assert accepted["changed_items"] == simulated["changed_items"]
    assert accepted["changed_items_count"] == simulated["changed_items_count"]
    assert accepted["schedule"] == simulated["schedule"]
    assert after == simulated["schedule"]
    assert after != before
    assert all(
        cell["session_id"]
        for entries in after.values()
        for cell in entries.values()
    )
    assert client.post(f"/schedule/repair/proposals/{proposal_id}/accept").status_code == 404


def test_repair_proposal_preview_returns_details_without_modifying_schedule() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    simulated = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "preview class unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    ).json()

    preview_response = client.get(f"/schedule/repair/proposals/{simulated['proposal_id']}")
    preview = preview_response.json()
    after = client.get("/schedule").json()

    assert preview_response.status_code == 200
    assert preview["proposal_id"] == simulated["proposal_id"]
    assert preview["proposed_schedule"] == simulated["schedule"]
    assert preview["changed_items"] == simulated["changed_items"]
    assert preview["changed_items_count"] == simulated["changed_items_count"]
    assert preview["repair_type"] == "repair_class"
    assert preview["repair_policy"] == simulated["repair_policy"]
    assert preview["created_at"]
    assert preview["hard_conflicts"] == 0
    assert "diagnostics" in preview
    assert all(item["session_id"] for item in preview["changed_items"])
    assert after == before


def test_repair_proposal_preview_unknown_returns_404() -> None:
    response = client.get("/schedule/repair/proposals/unknown-proposal")

    assert response.status_code == 404
    assert "Repair proposal not found" in response.json()["detail"]


def test_repair_proposal_accept_and_delete_still_work_after_preview() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    first = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "preview accept unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    ).json()
    assert client.get(f"/schedule/repair/proposals/{first['proposal_id']}").status_code == 200
    accepted = client.post(f"/schedule/repair/proposals/{first['proposal_id']}/accept")
    assert accepted.status_code == 200
    assert client.get("/schedule").json() == first["schedule"]

    # Reset with a fresh proposal to verify delete remains read-only after preview.
    get_store().clear_all()
    _seed_repair_api_dataset()
    before_delete = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before_delete)
    second = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "preview delete unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    ).json()
    assert client.get(f"/schedule/repair/proposals/{second['proposal_id']}").status_code == 200
    deleted = client.delete(f"/schedule/repair/proposals/{second['proposal_id']}")
    assert deleted.status_code == 200
    assert client.get("/schedule").json() == before_delete
    assert before != before_delete or before_delete


def test_repair_proposal_delete_rejects_without_modifying_schedule() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    simulated = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": False,
            "modified_constraints": [
                {
                    "text": "reject class unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    ).json()

    delete_response = client.delete(f"/schedule/repair/proposals/{simulated['proposal_id']}")
    after = client.get("/schedule").json()

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert after == before
    assert client.delete(f"/schedule/repair/proposals/{simulated['proposal_id']}").status_code == 404


def test_unknown_and_invalid_repair_proposals_are_not_accepted() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    store = get_store()
    store.repair_proposals["bad-proposal"] = {
        "proposal_id": "bad-proposal",
        "schedule": before,
        "changed_items": [],
        "diagnostics": {},
        "created_at": "2026-05-15T00:00:00+00:00",
        "repair_policy": "balanced",
        "repair_type": "repair_class",
        "hard_conflicts": 1,
        "quality_score": 0,
    }

    missing = client.post("/schedule/repair/proposals/missing-proposal/accept")
    invalid = client.post("/schedule/repair/proposals/bad-proposal/accept")
    after = client.get("/schedule").json()

    assert missing.status_code == 404
    assert invalid.status_code == 400
    assert after == before
    assert "bad-proposal" in store.repair_proposals


def test_repair_endpoint_commit_true_modifies_current_schedule_on_success() -> None:
    _seed_repair_api_dataset()
    before = client.get("/schedule").json()
    slot, class_name, _cell = _first_schedule_entry(before)

    response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "repair_target": class_name,
            "commit": True,
            "modified_constraints": [
                {
                    "text": "commit class unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": class_name,
                    "slot": slot,
                }
            ],
            "time_budget_seconds": 3,
        },
    )
    payload = response.json()
    after = client.get("/schedule").json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["committed"] is True
    assert payload["simulation"] is False
    assert payload["message"] == "Schedule repaired and committed successfully."
    assert payload["changed_items_count"] == len(payload["changed_items"])
    assert payload["changed_items_count"] >= 1
    for item in payload["changed_items"]:
        assert item["session_id"]
        assert item["class_id"] is not None
        assert item["subject_id"] is not None
        assert item["reason"]
    assert after == payload["schedule"]
    assert after != before
    after_session_ids = {
        cell["session_id"]
        for entries in after.values()
        for cell in entries.values()
    }
    assert {item["session_id"] for item in payload["changed_items"]} <= after_session_ids


def test_repair_endpoint_repair_teacher_works_with_string_id() -> None:
    ids = _seed_repair_api_dataset()

    response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_teacher",
            "teacher_id": f"teacher-{ids['teacher_1']['id']}",
            "repair_policy": "strict",
            "time_budget_seconds": 3,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["hard_conflicts"] == 0
    assert payload["repair_policy"] == "strict"


def test_repair_endpoint_repair_day_works() -> None:
    _seed_repair_api_dataset()

    response = client.post(
        "/schedule/repair",
        json={"repair_type": "repair_day", "day": "Mon", "repair_policy": "flexible", "time_budget_seconds": 3},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["hard_conflicts"] == 0
    assert payload["repair_policy"] == "flexible"


def test_repair_endpoint_invalid_policy_and_type_are_rejected() -> None:
    policy_response = client.post(
        "/schedule/repair",
        json={"repair_type": "repair_day", "day": "Mon", "repair_policy": "wild"},
    )
    type_response = client.post(
        "/schedule/repair",
        json={"repair_type": "repair_room", "repair_target": "R1"},
    )

    assert policy_response.status_code == 422
    assert type_response.status_code == 422


def test_repair_endpoint_failed_repair_keeps_existing_schedule() -> None:
    class_a = client.post("/classes", json={"name": "A", "max_lessons_per_day": 1}).json()
    client.post("/subjects", json={"name": "Math", "hours_per_week": 1})
    client.post("/teachers", json={"name": "T1", "subjects": ["Math"], "max_lessons_per_day": 1})
    client.post("/slots", json={"slot": "Mon-08:00"})
    assert client.post("/schedule/generate?engine=ortools").json()["success"] is True
    before = client.get("/schedule").json()

    response = client.post(
        "/schedule/repair",
        json={
            "repair_type": "repair_class",
            "class_id": class_a["id"],
            "modified_constraints": [
                {
                    "text": "A unavailable",
                    "condition_type": "class_unavailable",
                    "class_name": "A",
                    "slot": "Mon-08:00",
                }
            ],
            "time_budget_seconds": 3,
        },
    )
    after = client.get("/schedule").json()

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["committed"] is False
    assert response.json()["changed_items_count"] == 0
    assert after == before


def test_repair_endpoint_existing_generate_still_uses_legacy_default() -> None:
    client.post("/schedule/load-demo")

    response = client.post("/schedule/generate")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert client.get("/schedule/options").json()[0]["id"].startswith("option-")


def test_ortools_dataset_regression_stays_scalable_without_medium_benchmark_cost() -> None:
    dataset = build_dataset(DATASETS["small"])
    input_data = ScheduleInput(
        dataset["classes"],
        dataset["teachers"],
        dataset["subjects"],
        dataset["slots"],
        dataset["conditions"],
    )
    solver = ORToolsSolver(max_time_seconds=5.0)

    result = solver.solve(input_data)

    _assert_valid_hard_schedule(result, dataset["classes"], dataset["teachers"], dataset["subjects"], dataset["slots"])
    assert solver.last_diagnostics["boolean_variables"] <= 10_000
    assert solver.last_diagnostics["cp_status"] in {"OPTIMAL", "FEASIBLE"}
    quality = solver.last_diagnostics["quality"]
    assert result.metrics.quality_score == quality["total_score"]
    assert set(quality) >= {
        "gaps_class",
        "gaps_teacher",
        "overloaded_days",
        "spread_penalty",
        "compactness_penalty",
        "long_series_penalty",
        "stability_penalty",
        "soft_score",
        "total_score",
    }
    assert result.metrics.total_score == quality["total_score"]
    assert result.metrics.total_score >= 80
    assert isinstance(solver.last_diagnostics["quality_explanations"], list)
    assert solver.last_diagnostics["quality_explanations"]


def test_ortools_multi_strategy_returns_valid_winning_strategy() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1), Subject(name="English", hours_per_week=1)]
    teachers = [
        Teacher(id=1, name="T1", subjects=["Math"]),
        Teacher(id=2, name="T2", subjects=["English"]),
    ]
    slots = ["Mon-08:00", "Mon-09:00"]
    input_data = ScheduleInput(classes, teachers, subjects, slots)
    solver = ORToolsMultiStrategySolver(max_time_seconds=1.0)

    result = solver.solve(input_data)

    _assert_valid_hard_schedule(result, classes, teachers, subjects, slots)
    assert solver.last_diagnostics["winning_strategy"] in {"balanced", "compact", "teacher_friendly", "class_friendly"}
    assert len(solver.last_diagnostics["strategy_results"]) == 4
    assert result.metrics.total_score is not None


def test_solver_benchmark_exports_ortools_diagnostics(tmp_path) -> None:
    output = tmp_path / "solver_benchmark.json"

    report = run_solver_benchmarks(
        ["small"],
        output_path=output,
        ortools_time_budget_seconds=1.0,
        ortools_strategy="compact",
        ortools_multi_strategy=False,
    )

    assert output.exists()
    ortools = report["results"][0]["engines"][1]
    assert ortools["engine"] == "ortools_single_strategy"
    diagnostics = ortools["diagnostics"]
    assert diagnostics["time_budget_seconds"] == 1.0
    assert diagnostics["strategy"] == "compact"
    assert diagnostics["boolean_variables"] > 0
    assert diagnostics["avg_domain_size"] > 0
    assert "quality" in diagnostics
    assert "quality_explanations" in diagnostics


def test_realistic_and_hard_school_datasets_are_available() -> None:
    for name in ["realistic_school", "hard_school"]:
        dataset = build_dataset(DATASETS[name])
        assert dataset["classes"]
        assert dataset["teachers"]
        assert dataset["subjects"]
        assert dataset["slots"]
        report = check_feasibility(
            ScheduleInput(
                dataset["classes"],
                dataset["teachers"],
                dataset["subjects"],
                dataset["slots"],
                dataset["conditions"],
            )
        )
        assert report.required_sessions > 0


def test_previous_schedule_identical_has_zero_stability_penalty() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    first = ORToolsSolver(max_time_seconds=5.0).solve(ScheduleInput(classes, teachers, subjects, slots))

    second = ORToolsSolver(max_time_seconds=5.0).solve(
        ScheduleInput(classes, teachers, subjects, slots, previous_schedule=first.schedule)
    )

    assert second.success is True
    assert second.metrics.stability_penalty == 0
    assert second.metrics.changed_sessions == 0


def test_stability_penalty_positive_when_previous_schedule_must_change() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {"Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")}}
    conditions = [
        Condition(id=1, text="T1 unavailable", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")
    ]

    result = ORToolsSolver(max_time_seconds=5.0).solve(
        ScheduleInput(classes, teachers, subjects, slots, conditions, previous_schedule=previous)
    )

    assert result.success is True
    assert result.metrics.stability_penalty > 0
    assert result.metrics.changed_sessions > 0
    assert result.metrics.hard_conflicts == 0


def test_repair_preserves_session_id_when_session_moves() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {
            "A": ScheduleCell(subject="Math", teacher="T1", session_id="session-custom-a-math-0001")
        }
    }
    conditions = [
        Condition(id=1, text="A unavailable", condition_type="class_unavailable", class_name="A", slot="Mon-08:00")
    ]

    result = ORToolsSolver(max_time_seconds=3.0).solve(
        ScheduleInput(classes, teachers, subjects, slots, conditions, previous_schedule=previous)
    )

    assert result.success is True
    assert result.schedule["Tue-08:00"]["A"].session_id == "session-custom-a-math-0001"
    assert result.metrics.hard_conflicts == 0


def test_old_schedule_without_session_id_is_migrated_for_repair() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {"Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")}}

    migrated = schedule_with_session_ids(previous)
    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        time_budget=3.0,
    )

    assert migrated["Mon-08:00"]["A"].session_id == "session-a-math-0001"
    assert repaired.success is True
    assert any(cell.session_id for entries in repaired.schedule.values() for cell in entries.values())
    assert repaired.hard_conflicts == 0


def test_pinning_respects_fixed_session() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    pin = SolverAssignment(slot="Tue-08:00", class_name="A", subject="Math", teacher_name="T1")

    result = ORToolsSolver(max_time_seconds=5.0).solve(
        ScheduleInput(classes, teachers, subjects, slots, pinned_assignments=[pin])
    )

    assert result.success is True
    assert "A" in result.schedule["Tue-08:00"]
    assert result.schedule["Tue-08:00"]["A"].teacher == "T1"


def test_repair_mode_pins_unaffected_schedule_area() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T2")},
    }
    conditions = [
        Condition(id=1, text="T1 unavailable", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")
    ]

    result = ORToolsSolver(max_time_seconds=5.0).solve(
        ScheduleInput(
            classes,
            teachers,
            subjects,
            slots,
            conditions,
            previous_schedule=previous,
            repair_mode="repair_class",
            repair_target="A",
        )
    )

    assert result.success is True
    assert result.schedule["Tue-08:00"]["B"].teacher == "T2"
    assert result.metrics.changed_sessions <= 1


def test_delta_benchmark_reports_stability_metrics(tmp_path) -> None:
    output = tmp_path / "delta.json"

    report = run_delta_benchmark("small", output_path=output, ortools_time_budget_seconds=5.0)

    assert output.exists()
    assert report["delta"]["hard_conflicts"] == 0
    assert report["delta"]["stability_penalty"] >= 0
    assert "changed_sessions" in report["delta"]


def test_repair_schedule_accepts_previous_schedule() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {"Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")}}

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.repair_mode == "repair_class"
    assert repaired.repair_target == "A"
    assert repaired.hard_conflicts == 0
    assert "repair_service" in repaired.diagnostics


def test_repair_schedule_repair_class_keeps_other_classes_pinned() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T2")},
    }
    modified = [
        Condition(id=1, text="T1 unavailable", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")
    ]

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.schedule["Tue-08:00"]["B"].teacher == "T2"
    assert repaired.changed_sessions <= 1
    assert repaired.hard_conflicts == 0
    assert repaired.diagnostics["final_repair_strategy"] == "strict_pins"
    assert repaired.diagnostics["pins_relaxed_count"] == 0
    assert repaired.diagnostics["policy_used"] == "balanced"


def test_repair_schedule_repair_teacher_keeps_other_teachers_pinned() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T2")},
    }
    modified = [
        Condition(id=1, text="T1 unavailable", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")
    ]

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_teacher",
        teacher_id=1,
        modified_constraints=modified,
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.schedule["Tue-08:00"]["B"].teacher == "T2"
    assert repaired.hard_conflicts == 0


def test_repair_schedule_repair_day_keeps_other_days_pinned() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T2")},
    }
    modified = [
        Condition(id=1, text="T1 unavailable", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")
    ]

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_day",
        day="Mon",
        modified_constraints=modified,
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.schedule["Tue-08:00"]["B"].teacher == "T2"
    assert repaired.hard_conflicts == 0


def test_repair_schedule_respects_explicit_pins() -> None:
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T2")},
    }
    pin = SolverAssignment(slot="Tue-08:00", class_name="B", subject="Math", teacher_name="T2")

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        pinned_assignments=[pin],
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.schedule["Tue-08:00"]["B"].teacher == "T2"
    assert repaired.hard_conflicts == 0


def test_repair_schedule_does_not_change_legacy_default() -> None:
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00"]

    result = LegacySolverAdapter().solve(ScheduleInput(classes, teachers, subjects, slots))

    assert result.success is True
    assert result.metrics.engine == "legacy"


def test_repair_schedule_progressively_relaxes_pins_when_strict_repair_is_impossible() -> None:
    classes = [Class(id=1, name="A", max_lessons_per_day=3), Class(id=2, name="B", max_lessons_per_day=3)]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3)]
    slots = ["Mon-08:00", "Tue-08:00", "Wed-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T1")},
    }
    modified = [
        Condition(id=1, text="A blocked Mon", condition_type="class_unavailable", class_name="A", slot="Mon-08:00"),
        Condition(id=2, text="A blocked Wed", condition_type="class_unavailable", class_name="A", slot="Wed-08:00"),
    ]

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        time_budget=5.0,
    )

    metrics = analyze_schedule(repaired.schedule, classes, teachers, subjects, slots, modified)
    assert repaired.success is True
    assert metrics["teacher_conflicts"] == 0
    assert metrics["class_conflicts"] == 0
    assert metrics["unplaced_sessions"] == 0
    assert repaired.hard_conflicts == 0
    assert repaired.diagnostics["pins_initial_count"] == 1
    assert repaired.diagnostics["pins_relaxed_count"] == 1
    assert repaired.diagnostics["final_repair_strategy"] != "strict_pins"
    assert repaired.diagnostics["relaxed_pin_reasons"]
    assert len(repaired.diagnostics["repair_attempts"]) >= 2
    assert "pins ont été relâchés" in repaired.message


def test_delta_benchmark_reports_progressive_relaxation_case(tmp_path) -> None:
    output = tmp_path / "delta_hard.json"

    report = run_delta_benchmark("small", output_path=output, ortools_time_budget_seconds=5.0)
    hard_delta = report["progressive_relaxation"]

    assert output.exists()
    assert hard_delta["success"] is True
    assert hard_delta["hard_conflicts"] == 0
    assert hard_delta["pins_initial_count"] == 1
    assert hard_delta["pins_relaxed_count"] == 1
    assert hard_delta["final_repair_strategy"] != "strict_pins"
    assert hard_delta["relaxed_pin_reasons"]
    assert len(report["policy_comparison"]) == 3
    assert {item["repair_policy"] for item in report["policy_comparison"]} == {"strict", "balanced", "flexible"}


def test_delta_medium_policy_benchmark_exports_expected_metrics(tmp_path) -> None:
    output = tmp_path / "delta_medium_policies.json"

    report = run_delta_medium_policy_benchmark(
        output_path=output,
        ortools_time_budget_seconds=5.0,
        dataset_name="small",
    )

    assert output.exists()
    assert report["policies"]
    assert {item["repair_policy"] for item in report["policies"]} == {"strict", "balanced", "flexible"}
    for item in report["policies"]:
        assert set(item) >= {
            "changed_sessions",
            "stability_score",
            "stability_penalty",
            "quality_score",
            "gaps_count",
            "hard_conflicts",
            "final_repair_strategy",
            "time_ms",
            "changed_sessions_over_limit",
        }
        assert item["hard_conflicts"] == 0


def test_repair_policy_diagnostics_and_threshold_warning() -> None:
    classes, subjects, teachers, slots, previous, modified = _policy_repair_fixture()

    repaired = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        repair_policy="strict",
        time_budget=5.0,
    )

    assert repaired.success is True
    assert repaired.hard_conflicts == 0
    assert repaired.repair_policy == "strict"
    assert repaired.diagnostics["policy_used"] == "strict"
    assert repaired.max_changed_sessions == 1
    assert repaired.changed_sessions_over_limit is True
    assert repaired.diagnostics["policy_warning"]


def test_repair_policies_control_stability_vs_flexibility() -> None:
    classes, subjects, teachers, slots, previous, modified = _policy_repair_fixture()

    strict = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        repair_policy="strict",
        time_budget=5.0,
    )
    balanced = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        repair_policy="balanced",
        time_budget=5.0,
    )
    flexible = repair_schedule(
        previous_schedule=previous,
        classes=classes,
        teachers=teachers,
        subjects=subjects,
        slots=slots,
        repair_type="repair_class",
        class_id=1,
        modified_constraints=modified,
        repair_policy="flexible",
        time_budget=5.0,
    )

    assert strict.hard_conflicts == balanced.hard_conflicts == flexible.hard_conflicts == 0
    assert strict.changed_sessions <= balanced.changed_sessions
    assert flexible.changed_sessions >= strict.changed_sessions
    assert strict.diagnostics["policy_used"] == "strict"
    assert balanced.diagnostics["policy_used"] == "balanced"
    assert flexible.diagnostics["policy_used"] == "flexible"
    assert flexible.max_changed_sessions >= balanced.max_changed_sessions >= strict.max_changed_sessions


def _policy_repair_fixture():
    classes = [Class(id=1, name="A", max_lessons_per_day=3), Class(id=2, name="B", max_lessons_per_day=3)]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3)]
    slots = ["Mon-08:00", "Tue-08:00", "Wed-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T1")},
    }
    modified = [
        Condition(id=1, text="A blocked Mon", condition_type="class_unavailable", class_name="A", slot="Mon-08:00"),
        Condition(id=2, text="A blocked Wed", condition_type="class_unavailable", class_name="A", slot="Wed-08:00"),
    ]
    return classes, subjects, teachers, slots, previous, modified
