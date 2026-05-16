import re
from typing import Any, Literal

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


def _validate_slot_format(value: str) -> str:
    cleaned = _strip_and_validate(value, "slot")
    if not re.fullmatch(r"[A-Za-zÀ-ÿ0-9_ ]+-([01]\d|2[0-3]):[0-5]\d", cleaned):
        raise ValueError("slot must use the format Day-HH:MM, for example Mon-08:00")
    return cleaned


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


class LearningGroupCreate(BaseModel):
    class_id: int | None = None
    class_name: str | None = None
    subject_name: str = Field(min_length=1)
    level: str = Field(min_length=1)
    display_name: str | None = None

    @field_validator("class_name", "display_name")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("subject_name", "level")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _strip_and_validate(value, "learning group field")

    @model_validator(mode="after")
    def require_class_reference(self) -> "LearningGroupCreate":
        if self.class_id is None and not self.class_name:
            raise ValueError("class_id or class_name is required")
        return self


class LearningGroup(BaseModel):
    id: int
    class_id: int
    class_name: str
    subject_name: str
    level: str
    display_name: str


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

    @field_validator("unavailable_slots")
    @classmethod
    def validate_unavailable_slots(cls, value: list[str]) -> list[str]:
        return [_validate_slot_format(slot) for slot in _normalize_string_list(value, "unavailable_slots")]


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

    @field_validator("unavailable_slots")
    @classmethod
    def validate_unavailable_slots(cls, value: list[str]) -> list[str]:
        return [_validate_slot_format(slot) for slot in _normalize_string_list(value, "unavailable_slots")]


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
        return _validate_slot_format(value)


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
        allowed_types = {
            "teacher_unavailable",
            "class_unavailable",
            "subject_morning_preference",
            "avoid_subject_repeat",
            "teacher_prefer_morning",
            "avoid_long_sequence",
        }
        if self.type:
            self.condition_type = self.type
        self.condition_type = aliases.get(self.condition_type, self.condition_type)
        if self.condition_type not in allowed_types:
            raise ValueError(f"Unsupported condition type: {self.condition_type}")

        self.text = (self.text or self.description or "").strip()
        if not self.text:
            raise ValueError("text or description is required")

        if self.slot_id and not self.slot:
            self.slot = self.slot_id
        if self.slot:
            self.slot = _validate_slot_format(self.slot)

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
    session_id: str | None = None


class ImportWarning(BaseModel):
    code: str
    message: str
    row: int | None = None
    column: int | None = None
    value: Any | None = None
    lesson_index: int | None = None


class ImportError(BaseModel):
    code: str
    message: str
    row: int | None = None
    column: int | None = None
    value: Any | None = None
    lesson_index: int | None = None


class ImportedLesson(BaseModel):
    day: str
    slot: str
    class_name: str | None = None
    subject: str | None = None
    teacher: str | None = None
    room: str | None = None
    row: int | None = None
    column: int | None = None
    raw: str
    day_key: str | None = None
    slot_label: str | None = None
    slot_key: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    session_id: str | None = None
    normalized: dict[str, str] = Field(default_factory=dict)
    warnings: list[ImportWarning] = Field(default_factory=list)


class ExcelImportPreviewResponse(BaseModel):
    filename: str | None = None
    days: list[str] = Field(default_factory=list)
    slots: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    teachers: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    rooms: list[str] = Field(default_factory=list)
    lessons: list[ImportedLesson] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warning_details: list[ImportWarning] = Field(default_factory=list)
    error_details: list[ImportError] = Field(default_factory=list)
    can_commit: bool = False
    import_id: str | None = None
    preview_hash: str | None = None
    sheet_name: str | None = None
    parser_used: str | None = None


class ExcelImportCommitRequest(BaseModel):
    import_id: str | None = None
    lessons: list[ImportedLesson] | None = None
    mode: Literal["replace", "merge"] = "replace"
    dry_run: bool = False
    create_missing_entities: bool = True
    selected: bool = True
    synthesize_schedule_option: bool = True
    fail_on_conflict: bool = True

    @model_validator(mode="after")
    def require_import_source(self) -> "ExcelImportCommitRequest":
        if not self.import_id and not self.lessons:
            raise ValueError("import_id or lessons is required")
        return self


class CommitResponse(BaseModel):
    success: bool
    message: str
    mode: str
    dry_run: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_entities: dict[str, int] = Field(default_factory=dict)
    updated_entities: dict[str, int] = Field(default_factory=dict)
    imported_lessons_count: int = 0
    active_schedule_entries_count: int = 0
    schedule_option_id: str | None = None
    selected_schedule_option_id: str | None = None
    schedule: dict[str, dict[str, ScheduleCell]] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    export_ready: bool = False
    repair_ready: bool = False


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


class RepairPinnedAssignment(BaseModel):
    slot: str
    class_name: str
    subject: str
    teacher_name: str
    session_id: str | None = None

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, value: str) -> str:
        return _validate_slot_format(value)

    @field_validator("class_name", "subject", "teacher_name")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        return _strip_and_validate(value, "assignment field")


class RepairScheduleRequest(BaseModel):
    repair_type: Literal["repair_class", "repair_teacher", "repair_day"]
    repair_policy: Literal["strict", "balanced", "flexible"] = "balanced"
    class_id: int | str | None = None
    teacher_id: int | str | None = None
    day: str | None = None
    repair_target: str | None = None
    modified_constraints: list[ConditionCreate] = Field(default_factory=list)
    pinned_assignments: list[RepairPinnedAssignment] = Field(default_factory=list)
    time_budget_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    strategy: Literal["balanced", "compact", "teacher_friendly", "class_friendly"] = "balanced"
    commit: bool = True

    @model_validator(mode="after")
    def validate_target(self) -> "RepairScheduleRequest":
        if self.repair_type == "repair_class" and self.class_id is None and not self.repair_target:
            raise ValueError("repair_class requires class_id or repair_target")
        if self.repair_type == "repair_teacher" and self.teacher_id is None and not self.repair_target:
            raise ValueError("repair_teacher requires teacher_id or repair_target")
        if self.repair_type == "repair_day" and not self.day and not self.repair_target:
            raise ValueError("repair_day requires day or repair_target")
        if self.day:
            self.day = _strip_and_validate(self.day, "day")
        if self.repair_target:
            self.repair_target = _strip_and_validate(self.repair_target, "repair_target")
        return self


class RepairChangedItem(BaseModel):
    session_id: str | None = None
    class_id: int | str | None = None
    class_name: str | None = None
    subject_id: int | str | None = None
    subject_name: str | None = None
    old_slot: str | None = None
    new_slot: str | None = None
    old_teacher_id: int | str | None = None
    new_teacher_id: int | str | None = None
    old_teacher_name: str | None = None
    new_teacher_name: str | None = None
    change_type: Literal[
        "slot_changed",
        "teacher_changed",
        "slot_and_teacher_changed",
        "added",
        "removed",
    ]
    reason: str | None = None


class RepairScheduleResponse(BaseModel):
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]
    proposal_id: str | None = None
    changed_sessions: int = 0
    stability_penalty: int = 0
    stability_score: int = 0
    hard_conflicts: int = 0
    quality_score: int | None = None
    repair_type: str
    repair_policy: str
    repair_target: str | None = None
    final_repair_strategy: str | None = None
    changed_sessions_over_limit: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    committed: bool = False
    simulation: bool = False
    changed_items: list[RepairChangedItem] = Field(default_factory=list)
    changed_items_count: int = 0


class RepairProposalPreviewResponse(BaseModel):
    proposal_id: str
    proposed_schedule: dict[str, dict[str, ScheduleCell]]
    changed_items: list[RepairChangedItem] = Field(default_factory=list)
    changed_items_count: int = 0
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    repair_type: str
    repair_policy: str
    created_at: str
    stability_score: int = 0
    hard_conflicts: int = 0
    quality_score: int | None = None
