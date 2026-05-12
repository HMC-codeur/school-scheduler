from pydantic import BaseModel, Field


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


class Condition(BaseModel):
    id: int
    text: str


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
