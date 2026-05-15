import importlib

import pytest

from backend.models.schemas import ClassCreate, SubjectCreate, TeacherCreate
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


def test_teacher_subjects_are_trimmed_and_deduplicated():
    teacher = TeacherCreate(name="T1", subjects=[" Math ", "Physics", "Math", " Physics "])
    assert teacher.subjects == ["Math", "Physics"]


def test_teacher_subjects_reject_empty_entries():
    with pytest.raises(Exception):
        TeacherCreate(name="T1", subjects=["Math", "   "])
