from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from backend.models.schemas import Class, Condition, Subject, Teacher
from backend.services.solver.models import ScheduleInput


@dataclass(frozen=True)
class FeasibilityIssue:
    code: str
    message: str
    severity: str = "error"
    class_name: str | None = None
    teacher_name: str | None = None
    subject_name: str | None = None
    slot: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "class_name": self.class_name,
            "teacher_name": self.teacher_name,
            "subject_name": self.subject_name,
            "slot": self.slot,
        }


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    issues: list[FeasibilityIssue] = field(default_factory=list)
    warnings: list[FeasibilityIssue] = field(default_factory=list)
    required_sessions: int = 0
    class_capacity: int = 0
    teacher_capacity: int = 0

    def as_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "issues": [issue.as_dict() for issue in self.issues],
            "warnings": [warning.as_dict() for warning in self.warnings],
            "required_sessions": self.required_sessions,
            "class_capacity": self.class_capacity,
            "teacher_capacity": self.teacher_capacity,
        }


def check_feasibility(input_data: ScheduleInput) -> FeasibilityReport:
    issues: list[FeasibilityIssue] = []
    warnings: list[FeasibilityIssue] = []
    required_sessions = _required_sessions(input_data.classes, input_data.subjects)

    if not input_data.classes:
        issues.append(FeasibilityIssue("missing_classes", "Cannot solve: no classes were provided."))
    if not input_data.teachers:
        issues.append(FeasibilityIssue("missing_teachers", "Cannot solve: no teachers were provided."))
    if not input_data.subjects:
        issues.append(FeasibilityIssue("missing_subjects", "Cannot solve: no subjects were provided."))
    if not input_data.slots:
        issues.append(FeasibilityIssue("missing_slots", "Cannot solve: no time slots were provided."))
    if issues:
        return FeasibilityReport(False, issues, warnings, required_sessions, 0, 0)

    slot_day = {slot: slot.split("-", 1)[0] if "-" in slot else slot for slot in input_data.slots}
    days = sorted(set(slot_day.values()))
    class_unavailable = _class_unavailability(input_data.classes, input_data.conditions)
    teacher_unavailable = _teacher_unavailability(input_data.teachers, input_data.conditions)
    subject_hours = {subject.name: max(0, subject.hours_per_week) for subject in input_data.subjects}
    teachers_by_subject = _teachers_by_subject(input_data.teachers)

    for subject in input_data.subjects:
        if not teachers_by_subject.get(subject.name):
            issues.append(
                FeasibilityIssue(
                    "subject_without_teacher",
                    f"Cannot solve: subject '{subject.name}' has no compatible teacher.",
                    subject_name=subject.name,
                )
            )

    weekly_hours = sum(subject_hours.values())
    class_capacity = 0
    for class_obj in input_data.classes:
        capacity = _class_capacity(class_obj, input_data.slots, slot_day, class_unavailable[class_obj.id])
        class_capacity += capacity
        if weekly_hours > capacity:
            issues.append(
                FeasibilityIssue(
                    "class_capacity_too_low",
                    f"Class '{class_obj.name}' needs {weekly_hours} session(s), but only {capacity} feasible slot(s) remain.",
                    class_name=class_obj.name,
                )
            )

    teacher_capacity = 0
    for teacher in input_data.teachers:
        capacity = _teacher_capacity(teacher, input_data.slots, slot_day, teacher_unavailable[teacher.id])
        teacher_capacity += capacity
        if teacher.subjects and capacity <= 0:
            issues.append(
                FeasibilityIssue(
                    "teacher_no_available_slots",
                    f"Teacher '{teacher.name}' has no available slot.",
                    teacher_name=teacher.name,
                )
            )

    if required_sessions > len(input_data.classes) * len(input_data.slots):
        issues.append(
            FeasibilityIssue(
                "global_class_slots_insufficient",
                f"Need {required_sessions} session(s), but classes provide only {len(input_data.classes) * len(input_data.slots)} slot positions.",
            )
        )
    if required_sessions > teacher_capacity:
        issues.append(
            FeasibilityIssue(
                "global_teacher_capacity_insufficient",
                f"Need {required_sessions} session(s), but teacher weekly capacity is only {teacher_capacity}.",
            )
        )

    for subject in input_data.subjects:
        subject_need = len(input_data.classes) * max(0, subject.hours_per_week)
        subject_capacity = sum(
            _teacher_capacity(teacher, input_data.slots, slot_day, teacher_unavailable[teacher.id])
            for teacher in teachers_by_subject.get(subject.name, [])
        )
        if subject_need > subject_capacity:
            issues.append(
                FeasibilityIssue(
                    "subject_teacher_capacity_insufficient",
                    f"Subject '{subject.name}' needs {subject_need} session(s), but compatible teachers provide {subject_capacity}.",
                    subject_name=subject.name,
                )
            )

    for class_obj in input_data.classes:
        blocked = len(class_unavailable[class_obj.id])
        if blocked >= len(input_data.slots):
            issues.append(
                FeasibilityIssue(
                    "class_fully_unavailable",
                    f"Class '{class_obj.name}' is unavailable for all slots.",
                    class_name=class_obj.name,
                )
            )
        elif blocked >= int(len(input_data.slots) * 0.7):
            warnings.append(
                FeasibilityIssue(
                    "class_heavily_constrained",
                    f"Class '{class_obj.name}' is unavailable for {blocked}/{len(input_data.slots)} slots.",
                    "warning",
                    class_name=class_obj.name,
                )
            )

    for teacher in input_data.teachers:
        blocked = len(teacher_unavailable[teacher.id])
        if blocked >= int(len(input_data.slots) * 0.7):
            warnings.append(
                FeasibilityIssue(
                    "teacher_heavily_constrained",
                    f"Teacher '{teacher.name}' is unavailable for {blocked}/{len(input_data.slots)} slots.",
                    "warning",
                    teacher_name=teacher.name,
                )
            )

    if not days:
        issues.append(FeasibilityIssue("invalid_slot_days", "Cannot solve: no valid day information could be derived from slots."))

    return FeasibilityReport(
        feasible=not issues,
        issues=issues,
        warnings=warnings,
        required_sessions=required_sessions,
        class_capacity=class_capacity,
        teacher_capacity=teacher_capacity,
    )


def _required_sessions(classes: list[Class], subjects: list[Subject]) -> int:
    return len(classes) * sum(max(0, subject.hours_per_week) for subject in subjects)


def _teachers_by_subject(teachers: list[Teacher]) -> dict[str, list[Teacher]]:
    grouped: dict[str, list[Teacher]] = defaultdict(list)
    for teacher in teachers:
        for subject_name in teacher.subjects:
            grouped[subject_name].append(teacher)
    return grouped


def _class_unavailability(classes: list[Class], conditions: list[Condition]) -> dict[int, set[str]]:
    by_name = {class_obj.name: class_obj for class_obj in classes}
    unavailable: dict[int, set[str]] = defaultdict(set)
    for condition in conditions:
        if condition.condition_type != "class_unavailable" or not condition.class_name or not condition.slot:
            continue
        class_obj = by_name.get(condition.class_name)
        if class_obj:
            unavailable[class_obj.id].add(condition.slot)
    return unavailable


def _teacher_unavailability(teachers: list[Teacher], conditions: list[Condition]) -> dict[int, set[str]]:
    by_name = {teacher.name: teacher for teacher in teachers}
    unavailable: dict[int, set[str]] = {
        teacher.id: set(teacher.unavailable_slots)
        for teacher in teachers
    }
    for condition in conditions:
        if condition.condition_type != "teacher_unavailable" or not condition.teacher_name or not condition.slot:
            continue
        teacher = by_name.get(condition.teacher_name)
        if teacher:
            unavailable.setdefault(teacher.id, set()).add(condition.slot)
    return unavailable


def _class_capacity(class_obj: Class, slots: list[str], slot_day: dict[str, str], blocked: set[str]) -> int:
    available_by_day: dict[str, int] = defaultdict(int)
    for slot in slots:
        if slot in blocked:
            continue
        available_by_day[slot_day[slot]] += 1
    return sum(min(max(1, class_obj.max_lessons_per_day), count) for count in available_by_day.values())


def _teacher_capacity(teacher: Teacher, slots: list[str], slot_day: dict[str, str], blocked: set[str]) -> int:
    available_by_day: dict[str, int] = defaultdict(int)
    for slot in slots:
        if slot in blocked:
            continue
        available_by_day[slot_day[slot]] += 1
    return sum(min(max(1, teacher.max_lessons_per_day), count) for count in available_by_day.values())
