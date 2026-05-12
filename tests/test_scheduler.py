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
    classes = [Class(id=1, name="A")]
    subjects = [Subject(name="Math", hours_per_week=3)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08", "Mon-09", "Tue-08"]

    result = SchedulerService.generate(
        classes,
        teachers,
        subjects,
        slots,
        max_lessons_per_class_per_day=1,
    )

    assert result.success is False
    assert "class daily max" in result.message.lower()


def test_teacher_daily_max_hours_enforced():
    classes = [Class(id=1, name="A"), Class(id=2, name="B")]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"])]
    slots = ["Mon-08", "Mon-09"]

    result = SchedulerService.generate(
        classes,
        teachers,
        subjects,
        slots,
        max_lessons_per_teacher_per_day=1,
    )

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
