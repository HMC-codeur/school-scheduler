import importlib

import pytest

from pydantic import ValidationError

from backend.models.schemas import ClassCreate, ConditionCreate, SubjectCreate, TeacherCreate
from backend.models.schemas import Class, Subject, Teacher
from backend.services.scheduler import SchedulerService


def test_cors_disallows_wildcard_with_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    with pytest.raises(ValueError):
        import backend.config

        importlib.reload(backend.config)
        backend.config.get_settings.cache_clear()
        backend.config.get_settings()


def test_validation_rejects_blank_name():
    with pytest.raises(Exception):
        ClassCreate(name="   ", max_lessons_per_day=4)


def test_validation_rejects_non_positive_hours():
    with pytest.raises(Exception):
        SubjectCreate(name="Math", hours_per_week=0)


def test_generate_schedule_non_regression_success():
    classes = [Class(id=1, name="A", max_lessons_per_day=5)]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], unavailable_slots=[], max_lessons_per_day=5)]
    slots = ["Mon-08:00"]
    response = SchedulerService.generate(classes, teachers, subjects, slots)
    assert response.success is True


def test_condition_type_alias_is_honored():
    payload = {
        "type": "class_unavailable",
        "text": "Classe indisponible",
        "class_name": "6A",
        "slot": "Mon-08:00",
    }
    condition = __import__("backend.models.schemas", fromlist=["ConditionCreate"]).ConditionCreate(**payload)
    assert condition.condition_type == "class_unavailable"
    assert condition.class_name == "6A"


def test_teacher_unavailable_slots_accepts_valid_slot():
    teacher = TeacherCreate(
        name="Mme Dupont",
        subjects=["Math"],
        unavailable_slots=["Mon-08:00", "Fri-15:30"],
    )
    assert teacher.unavailable_slots == ["Mon-08:00", "Fri-15:30"]


def test_teacher_unavailable_slots_rejects_invalid_slot():
    with pytest.raises(ValidationError, match="unavailable_slots item must match format Ddd-HH:MM"):
        TeacherCreate(name="Mme Dupont", subjects=["Math"], unavailable_slots=["Lun-08:00"])


def test_condition_slot_accepts_valid_slot():
    condition = ConditionCreate(
        condition_type="teacher_unavailable",
        text="Teacher unavailable",
        teacher_name="M. Martin",
        slot="Tue-09:45",
    )
    assert condition.slot == "Tue-09:45"


def test_condition_slot_rejects_invalid_slot():
    with pytest.raises(ValidationError, match="slot must match format Ddd-HH:MM"):
        ConditionCreate(
            condition_type="class_unavailable",
            text="Class unavailable",
            class_name="6A",
            slot="Tuesday-09:45",
        )
