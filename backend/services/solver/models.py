from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.schemas import Class, Condition, LearningGroup, ScheduleCell, Subject, Teacher


@dataclass(frozen=True)
class ScheduleInput:
    classes: list[Class]
    teachers: list[Teacher]
    subjects: list[Subject]
    slots: list[str]
    conditions: list[Condition] = field(default_factory=list)
    learning_groups: list[LearningGroup] = field(default_factory=list)
    previous_schedule: dict[str, dict[str, ScheduleCell]] | None = None
    pinned_assignments: list["SolverAssignment"] = field(default_factory=list)
    repair_mode: str | None = None
    repair_target: str | None = None


@dataclass(frozen=True)
class SolverAssignment:
    slot: str
    class_name: str
    subject: str
    teacher_name: str
    session_id: str | None = None


@dataclass(frozen=True)
class SolverMetrics:
    engine: str
    success: bool
    required_sessions: int
    scheduled_sessions: int
    generation_time_ms: int
    hard_conflicts: int = 0
    class_conflicts: int = 0
    teacher_conflicts: int = 0
    incompatible_assignments: int = 0
    unplaced_sessions: int = 0
    quality_score: int | None = None
    soft_score: int | None = None
    gaps_class: int = 0
    gaps_teacher: int = 0
    overloaded_days: int = 0
    spread_penalty: int = 0
    compactness_penalty: int = 0
    long_series_penalty: int = 0
    stability_penalty: int = 0
    changed_sessions: int = 0
    total_score: int | None = None

    def as_dict(self) -> dict[str, int | str | bool | None]:
        return {
            "engine": self.engine,
            "success": self.success,
            "required_sessions": self.required_sessions,
            "scheduled_sessions": self.scheduled_sessions,
            "generation_time_ms": self.generation_time_ms,
            "hard_conflicts": self.hard_conflicts,
            "class_conflicts": self.class_conflicts,
            "teacher_conflicts": self.teacher_conflicts,
            "incompatible_assignments": self.incompatible_assignments,
            "unplaced_sessions": self.unplaced_sessions,
            "quality_score": self.quality_score,
            "soft_score": self.soft_score,
            "gaps_class": self.gaps_class,
            "gaps_teacher": self.gaps_teacher,
            "overloaded_days": self.overloaded_days,
            "spread_penalty": self.spread_penalty,
            "compactness_penalty": self.compactness_penalty,
            "long_series_penalty": self.long_series_penalty,
            "stability_penalty": self.stability_penalty,
            "changed_sessions": self.changed_sessions,
            "total_score": self.total_score,
        }


@dataclass(frozen=True)
class ScheduleResult:
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]
    assignments: list[SolverAssignment]
    metrics: SolverMetrics
