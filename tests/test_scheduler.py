from backend.models.schemas import Class, Subject, Teacher
from backend.services.scheduler import SchedulerService


def test_successful_schedule_generation():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2), Subject(name="English", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["English"])]
    slots = ["Mon-08", "Tue-08", "Wed-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is True
    assert result.schedule
    assert result.quality_score is not None
    assert 0 <= result.quality_score <= 100
    assert result.conflicts_count is not None
    assert result.gaps_count is not None
    assert result.repeated_subjects_count is not None
    assert result.long_sequences_count is not None
    assert result.load_balance_status in {"good", "average", "bad"}


def test_fail_when_subject_has_no_teacher():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["English"])]
    slots = ["Mon-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is False
    assert "no teacher assigned" in result.message


def test_fail_when_not_enough_slots():
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=3)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"]), Teacher(id=2, name="T2", subjects=["Math"])]
    slots = ["Mon-08", "Tue-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is False
    assert "not enough slots" in result.message.lower()


def test_teacher_unavailable_slots_are_respected():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], unavailable_slots=["Mon-08"])]
    slots = ["Mon-08", "Tue-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is True
    assert "A" in result.schedule["Tue-08"]
    assert "Mon-08" not in result.schedule


def test_class_daily_max_hours_enforced():
    classes = [Class(id=1, name="A", max_lessons_per_day=1)]
    subjects = [Subject(name="Math", hours_per_week=3)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08", "Mon-09", "Tue-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is False
    assert "daily max is too low" in result.message.lower()


def test_teacher_daily_max_hours_enforced():
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=1)]
    slots = ["Mon-08", "Mon-09"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is False
    assert "constraints conflict" in result.message.lower()


def test_impossible_schedule_with_teacher_unavailability_reports_clear_message():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], unavailable_slots=["Mon-08"])]
    slots = ["Mon-08"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is False
    assert "no available slots" in result.message.lower()


def test_scheduler_spreads_lessons_across_days_when_possible():
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=2), Subject(name="English", hours_per_week=2)]
    teachers = [Teacher(id=1, name="TM", subjects=["Math"]), Teacher(id=2, name="TE", subjects=["English"])]
    slots = ["Mon-08", "Mon-09", "Tue-08", "Tue-09"]

    result = SchedulerService.generate(classes, teachers, subjects, slots)

    assert result.success is True
    used_days = {slot.split("-", 1)[0] for slot, cells in result.schedule.items() if "A" in cells}
    assert used_days == {"Mon", "Tue"}
