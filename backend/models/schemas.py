from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator




def _strip_and_validate(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _normalize_string_list(values: list[str], field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _strip_and_validate(value, field_name)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)
    max_lessons_per_day: int = Field(default=6, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_and_validate(value, "name")


class Class(BaseModel):
    id: int
    name: str
    max_lessons_per_day: int = Field(default=6, ge=1)


class TeacherCreate(BaseModel):
    name: str = Field(min_length=1)
    subjects: list[str] = Field(default_factory=list)
    unavailable_slots: list[str] = Field(default_factory=list)
    max_lessons_per_day: int = Field(default=6, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_and_validate(value, "name")

    @field_validator("subjects")
    @classmethod
    def validate_subjects(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value, "subjects")


class Teacher(BaseModel):
    id: int
    name: str
    subjects: list[str]
    unavailable_slots: list[str] = Field(default_factory=list)
    max_lessons_per_day: int = Field(default=6, ge=1)

    @field_validator("subjects")
    @classmethod
    def validate_subjects(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value, "subjects")


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)
    hours_per_week: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_and_validate(value, "name")


class Subject(BaseModel):
    name: str
    hours_per_week: int


class SlotCreate(BaseModel):
    slot: str = Field(min_length=1)

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, value: str) -> str:
        return _strip_and_validate(value, "slot")


class ConditionCreate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    condition_type: Literal[
        "teacher_unavailable",
        "class_unavailable",
        "subject_morning_preference",
        "avoid_subject_repeat",
        "subject_prefer_morning",
        "teacher_prefer_morning",
        "avoid_subject_repeat_same_day",
        "avoid_long_sequence",
    ] = "teacher_unavailable"
    type: str | None = None
    teacher_name: str | None = None
    class_name: str | None = None
    subject_name: str | None = None
    slot: str | None = None
    target_id: str | None = None
    slot_id: str | None = None
    hard: bool = True

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "ConditionCreate":
        aliases = {
            "subject_prefer_morning": "subject_morning_preference",
            "avoid_subject_repeat_same_day": "avoid_subject_repeat",
        }
        if self.type:
            self.condition_type = self.type
        self.condition_type = aliases.get(self.condition_type, self.condition_type)

        self.text = (self.text or self.description or "").strip()
        if not self.text:
            raise ValueError("text or description is required")

        if self.slot_id and not self.slot:
            self.slot = self.slot_id

        target = (self.target_id or "").strip() or None
        if self.condition_type == "teacher_unavailable":
            self.teacher_name = (self.teacher_name or target or "").strip() or None
            if not self.teacher_name or not self.slot:
                raise ValueError("teacher_name (or target_id) and slot (or slot_id) are required for teacher_unavailable")
        elif self.condition_type == "class_unavailable":
            self.class_name = (self.class_name or target or "").strip() or None
            if not self.class_name or not self.slot:
                raise ValueError("class_name (or target_id) and slot (or slot_id) are required for class_unavailable")
        elif self.condition_type in {"subject_morning_preference", "avoid_subject_repeat"}:
            self.subject_name = (self.subject_name or target or "").strip() or None
            if not self.subject_name:
                raise ValueError("subject_name (or target_id) is required for this condition type")
        elif self.condition_type == "teacher_prefer_morning":
            self.teacher_name = (self.teacher_name or target or "").strip() or None
            if not self.teacher_name:
                raise ValueError("teacher_name (or target_id) is required for teacher_prefer_morning")
        elif self.condition_type == "avoid_long_sequence":
            self.class_name = (self.class_name or "").strip() or None
            self.teacher_name = (self.teacher_name or "").strip() or None

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
    score_breakdown: list[dict[str, int | str]] | None = None
    required_sessions: int | None = None
    scheduled_sessions: int | None = None
    generation_time_ms: int | None = None
