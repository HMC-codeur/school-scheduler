from backend.models.schemas import Class, Condition, Subject, Teacher
from backend.services.scheduler import SchedulerService


def test_successful_schedule_generation():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2), Subject(name="English", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["English"])]
    slots = ["Mon-08", "Tue-08", "Wed-08"]
    result = SchedulerService.generate(classes, teachers, subjects, slots)
    assert result.success is True
    assert result.required_sessions == 3
    assert result.scheduled_sessions == 3
    assert result.generation_time_ms is not None
    assert result.generation_time_ms >= 0


def test_teacher_unavailable_condition_is_respected():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Tue-08:00"]
    conditions = [Condition(id=1, text="condition", condition_type="teacher_unavailable", teacher_name="T1", slot="Mon-08:00")]
    result = SchedulerService.generate(classes, teachers, subjects, slots, conditions)
    assert result.success is True
    assert "Mon-08:00" not in result.schedule


def test_subject_morning_preference_influences_schedule_if_possible():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-13:00", "Mon-08:00"]
    conditions = [Condition(id=1, text="condition", condition_type="subject_morning_preference", subject_name="Math")]
    result = SchedulerService.generate(classes, teachers, subjects, slots, conditions)
    assert result.success is True
    assert "A" in result.schedule["Mon-08:00"]


def test_avoid_subject_repeat_condition_is_taken_if_possible():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08:00", "Mon-09:00", "Tue-08:00"]
    conditions = [Condition(id=1, text="condition", condition_type="avoid_subject_repeat", subject_name="Math")]
    result = SchedulerService.generate(classes, teachers, subjects, slots, conditions)
    assert result.success is True
    used_slots = [slot for slot, entries in result.schedule.items() if "A" in entries]
    used_days = {slot.split("-", 1)[0] for slot in used_slots}
    assert used_days == {"Mon", "Tue"}


def test_failure_returns_session_counts_and_generation_time():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]) ]
    slots = ["Mon-08:00"]
    conditions = [
        Condition(
            id=1,
            text="condition",
            condition_type="teacher_unavailable",
            teacher_name="T1",
            slot="Mon-08:00",
        )
    ]

    result = SchedulerService.generate(classes, teachers, subjects, slots, conditions)

    assert result.success is False
    assert result.required_sessions == 1
    assert result.scheduled_sessions == 0
    assert result.generation_time_ms is not None
    assert result.generation_time_ms >= 0
