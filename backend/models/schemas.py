from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)
    max_lessons_per_day: int = Field(default=6, ge=1)


class Class(BaseModel):
    id: int
    name: str
    max_lessons_per_day: int = Field(default=6, ge=1)


class TeacherCreate(BaseModel):
    name: str = Field(min_length=1)
    subjects: list[str] = Field(default_factory=list)
    unavailable_slots: list[str] = Field(default_factory=list)
    max_lessons_per_day: int = Field(default=6, ge=1)


class Teacher(BaseModel):
    id: int
    name: str
    subjects: list[str]
    unavailable_slots: list[str] = Field(default_factory=list)
    max_lessons_per_day: int = Field(default=6, ge=1)


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)
    hours_per_week: int = Field(gt=0)


class Subject(BaseModel):
    name: str
    hours_per_week: int


class SlotCreate(BaseModel):
    slot: str = Field(min_length=1)


class ConditionCreate(BaseModel):
    text: str = Field(min_length=1)
    condition_type: Literal[
        "teacher_unavailable",
        "class_unavailable",
        "subject_morning_preference",
        "avoid_subject_repeat",
    ] = "teacher_unavailable"
    teacher_name: str | None = None
    class_name: str | None = None
    subject_name: str | None = None
    slot: str | None = None

    @model_validator(mode="after")
    def validate_by_type(self) -> "ConditionCreate":
        if self.condition_type == "teacher_unavailable":
            if not self.teacher_name or not self.slot:
                raise ValueError("teacher_name and slot are required for teacher_unavailable")
        elif self.condition_type == "class_unavailable":
            if not self.class_name or not self.slot:
                raise ValueError("class_name and slot are required for class_unavailable")
        elif self.condition_type == "subject_morning_preference":
            if not self.subject_name:
                raise ValueError("subject_name is required for subject_morning_preference")
        elif self.condition_type == "avoid_subject_repeat":
            if not self.subject_name:
                raise ValueError("subject_name is required for avoid_subject_repeat")
        return self


class Condition(ConditionCreate):
    id: int


class TimeSettings(BaseModel):
    day_start_time: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    day_end_time: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    lesson_duration_minutes: int = Field(gt=0)
    break_duration_minutes: int = Field(ge=0)
    working_days: list[str] = Field(min_length=1)
    lunch_break_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    lunch_break_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")


class SessionRequirement(BaseModel):
    class_id: int
    class_name: str
    subject: str


class ScheduledEntry(BaseModel):
    slot: str
    class_name: str
    subject: str
    teacher_name: str


class ScheduleCell(BaseModel):
    subject: str
    teacher: str


class GenerateScheduleResponse(BaseModel):
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]
    quality_score: int | None = None
    conflicts_count: int | None = None
    gaps_count: int | None = None
    repeated_subjects_count: int | None = None
    long_sequences_count: int | None = None
    load_balance_status: str | None = None
