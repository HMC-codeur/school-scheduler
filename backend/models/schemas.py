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
