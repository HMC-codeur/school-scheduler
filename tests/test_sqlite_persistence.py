from backend.data.sqlite_repository import SQLiteRepository
from backend.models.schemas import ConditionCreate, ScheduleCell, TimeSettings


def test_sqlite_repository_persists_after_logical_restart(tmp_path) -> None:
    db_path = tmp_path / "scheduler.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.clear_all()

    repo.add_class("6A", max_lessons_per_day=5)
    repo.add_subject("Math", 2)
    repo.add_slot("Mon-08:00")
    repo.add_teacher("Mme A", ["Math"], ["Mon-08:00"], max_lessons_per_day=4)
    repo.add_condition(
        ConditionCreate(
            text="Math le matin",
            condition_type="subject_morning_preference",
            subject_name="Math",
        )
    )
    repo.time_settings = TimeSettings(
        day_start_time="08:00",
        day_end_time="10:00",
        lesson_duration_minutes=60,
        break_duration_minutes=0,
        working_days=["Mon"],
    )
    repo.schedule = {"Mon-08:00": {"6A": ScheduleCell(subject="Math", teacher="Mme A")}}
    repo.schedule_options = [
        {
            "id": "option-1",
            "selected": True,
            "quality_score": 100,
            "schedule_signature": "abc12345",
            "metrics": {},
            "schedule": {"Mon-08:00": {"6A": {"subject": "Math", "teacher": "Mme A"}}},
        }
    ]
    repo.selected_schedule_option_id = "option-1"

    restarted = SQLiteRepository(db_path)

    assert [class_obj.name for class_obj in restarted.classes] == ["6A"]
    assert [subject.name for subject in restarted.subjects] == ["Math"]
    assert restarted.slots == ["Mon-08:00"]
    assert restarted.teachers[0].unavailable_slots == ["Mon-08:00"]
    assert restarted.conditions[0].subject_name == "Math"
    assert restarted.time_settings is not None
    assert restarted.schedule["Mon-08:00"]["6A"].teacher == "Mme A"
    assert restarted.schedule_options[0]["schedule_signature"] == "abc12345"
    assert restarted.selected_schedule_option_id == "option-1"
