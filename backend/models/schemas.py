from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)
    max_lessons_per_day: int = Field(default=6, ge=1)


class Class(ClassCreate):
    id: int


class TeacherCreate(BaseModel):
    name: str = Field(min_length=1)
    subject_ids: list[int] = Field(default_factory=list)
    unavailable_slot_ids: list[int] = Field(default_factory=list)
    max_lessons_per_day: int = Field(default=6, ge=1)


class Teacher(TeacherCreate):
    id: int


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)
    weekly_hours: int = Field(gt=0)
    allowed_teacher_ids: list[int] = Field(default_factory=list)
    target_class_ids: list[int] = Field(default_factory=list)


class Subject(SubjectCreate):
    id: int


class SlotCreate(BaseModel):
    label: str = Field(min_length=1)


class Slot(SlotCreate):
    id: int


class ScheduleSession(BaseModel):
    session_id: int
    class_id: int
    teacher_id: int
    subject_id: int
    slot_id: int


class ScheduleUpdate(BaseModel):
    class_id: int
    teacher_id: int
    subject_id: int
    slot_id: int


class GenerateScheduleResponse(BaseModel):
    success: bool
    message: str
    schedule: list[ScheduleSession]
    stats: dict = Field(default_factory=dict)
    details: list[str] = Field(default_factory=list)
