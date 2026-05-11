from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)


class Class(BaseModel):
    id: int
    name: str


class TeacherCreate(BaseModel):
    name: str = Field(min_length=1)
    subjects: list[str] = Field(default_factory=list)


class Teacher(BaseModel):
    id: int
    name: str
    subjects: list[str]


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1)
    hours_per_week: int = Field(gt=0)


class Subject(BaseModel):
    name: str
    hours_per_week: int


class SlotCreate(BaseModel):
    slot: str = Field(min_length=1)


class SessionRequirement(BaseModel):
    class_id: int
    class_name: str
    subject: str


class ScheduledEntry(BaseModel):
    slot: str
    class_name: str
    subject: str
    teacher_name: str


class GenerateScheduleResponse(BaseModel):
    success: bool
    message: str
    schedule: dict[str, dict[str, str]]
