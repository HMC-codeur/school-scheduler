from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.solver.models import ScheduleInput, ScheduleResult, SolverAssignment
from backend.services.solver.ortools_solver import ORToolsSolver
from backend.services.solver.stability import (
    SUPPORTED_REPAIR_MODES,
    evaluate_stability,
    repair_pins_from_previous,
    schedule_to_assignments,
    schedule_with_session_ids,
)


RepairMode = Literal["repair_class", "repair_teacher", "repair_day"]
RepairPolicy = Literal["strict", "balanced", "flexible"]
SUPPORTED_REPAIR_POLICIES = {"strict", "balanced", "flexible"}


@dataclass(frozen=True)
class _RepairAttempt:
    name: str
    automatic_pins: list[SolverAssignment]
    relaxed_pins: list[SolverAssignment]
    relaxed_pin_reasons: list[str]


@dataclass(frozen=True)
class RepairScheduleResult:
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]
    solver_result: ScheduleResult
    changed_sessions: int
    stability_penalty: int
    stability_score: int
    hard_conflicts: int
    quality_score: int | None
    diagnostics: dict[str, Any]
    repair_mode: RepairMode
    repair_target: str
    repair_policy: RepairPolicy
    max_changed_sessions: int
    changed_sessions_over_limit: bool
    final_repair_strategy: str
    pinned_assignments: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "schedule": self.schedule,
            "changed_sessions": self.changed_sessions,
            "stability_penalty": self.stability_penalty,
            "stability_score": self.stability_score,
            "hard_conflicts": self.hard_conflicts,
            "quality_score": self.quality_score,
            "diagnostics": self.diagnostics,
            "repair_mode": self.repair_mode,
            "repair_target": self.repair_target,
            "repair_policy": self.repair_policy,
            "max_changed_sessions": self.max_changed_sessions,
            "changed_sessions_over_limit": self.changed_sessions_over_limit,
            "final_repair_strategy": self.final_repair_strategy,
            "pinned_assignments": self.pinned_assignments,
        }


def repair_schedule(
    *,
    previous_schedule: dict[str, dict[str, ScheduleCell]],
    repair_type: RepairMode,
    dataset: dict[str, Any] | None = None,
    classes: list[Class] | None = None,
    teachers: list[Teacher] | None = None,
    subjects: list[Subject] | None = None,
    slots: list[str] | None = None,
    conditions: list[Condition] | None = None,
    class_id: int | None = None,
    teacher_id: int | None = None,
    day: str | None = None,
    repair_target: str | None = None,
    modified_constraints: list[Condition] | None = None,
    pinned_assignments: list[SolverAssignment] | None = None,
    time_budget: float | None = None,
    strategy: str = "balanced",
    repair_policy: RepairPolicy = "balanced",
) -> RepairScheduleResult:
    if repair_type not in SUPPORTED_REPAIR_MODES:
        raise ValueError(f"Unsupported repair type: {repair_type}")
    if repair_policy not in SUPPORTED_REPAIR_POLICIES:
        raise ValueError(f"Unsupported repair policy: {repair_policy}")

    previous_schedule = schedule_with_session_ids(previous_schedule)
    normalized = _normalize_dataset(dataset, classes, teachers, subjects, slots, conditions)
    target = _resolve_repair_target(
        repair_type=repair_type,
        classes=normalized["classes"],
        teachers=normalized["teachers"],
        class_id=class_id,
        teacher_id=teacher_id,
        day=day,
        repair_target=repair_target,
    )
    repair_conditions = [*normalized["conditions"], *(modified_constraints or [])]
    provisional_input = ScheduleInput(
        classes=normalized["classes"],
        teachers=normalized["teachers"],
        subjects=normalized["subjects"],
        slots=normalized["slots"],
        conditions=repair_conditions,
        previous_schedule=previous_schedule,
        repair_mode=repair_type,
        repair_target=target,
    )
    auto_pins = repair_pins_from_previous(provisional_input)
    attempts = _build_repair_attempts(auto_pins, previous_schedule, repair_type, target, repair_policy)
    solved_attempt: _RepairAttempt | None = None
    solved_result: ScheduleResult | None = None
    solved_diagnostics: dict[str, Any] = {}
    repair_attempts: list[dict[str, Any]] = []
    successful_attempts: list[tuple[_RepairAttempt, ScheduleResult, dict[str, Any]]] = []

    for attempt in attempts:
        input_data = ScheduleInput(
            classes=normalized["classes"],
            teachers=normalized["teachers"],
            subjects=normalized["subjects"],
            slots=normalized["slots"],
            conditions=repair_conditions,
            previous_schedule=previous_schedule,
            pinned_assignments=[*attempt.automatic_pins, *(pinned_assignments or [])],
            repair_mode=None,
            repair_target=None,
        )
        solver = ORToolsSolver(max_time_seconds=time_budget or 10.0, strategy=strategy)
        result = solver.solve(input_data)
        diagnostics = dict(solver.last_diagnostics or {})
        repair_attempts.append(
            {
                "strategy": attempt.name,
                "success": result.success,
                "message": result.message,
                "automatic_pins": len(attempt.automatic_pins),
                "explicit_pins": len(pinned_assignments or []),
                "pins_relaxed_count": len(attempt.relaxed_pins),
                "relaxed_pin_reasons": attempt.relaxed_pin_reasons,
                "hard_conflicts": result.metrics.hard_conflicts,
                "cp_status": diagnostics.get("cp_status"),
            }
        )
        if result.success and result.metrics.hard_conflicts == 0:
            successful_attempts.append((attempt, result, diagnostics))
            if repair_policy in {"strict", "balanced"}:
                solved_attempt = attempt
                solved_result = result
                solved_diagnostics = diagnostics
                break

    if successful_attempts and repair_policy == "flexible":
        solved_attempt, solved_result, solved_diagnostics = max(
            successful_attempts,
            key=lambda item: (
                int(item[1].metrics.quality_score or 0),
                int(item[1].metrics.total_score or 0),
                -int(item[1].metrics.changed_sessions),
            ),
        )
    elif solved_result is None:
        solved_attempt = attempts[-1]
        solved_result = result
        solved_diagnostics = diagnostics

    result = solved_result
    final_attempt = solved_attempt
    stability = evaluate_stability(previous_schedule, result.schedule)
    diagnostics = dict(solved_diagnostics)
    pins_relaxed_count = len(final_attempt.relaxed_pins)
    relaxed_message = ""
    if pins_relaxed_count:
        relaxed_message = f" Réparation stricte impossible, {pins_relaxed_count} pins ont été relâchés."
    diagnostics["repair_service"] = {
        "repair_mode": repair_type,
        "repair_target": target,
        "automatic_pins": len(final_attempt.automatic_pins),
        "explicit_pins": len(pinned_assignments or []),
        "modified_constraints": len(modified_constraints or []),
        "stability": stability.as_dict(),
        "repair_attempts": repair_attempts,
        "pins_initial_count": len(auto_pins),
        "pins_relaxed_count": pins_relaxed_count,
        "relaxed_pin_reasons": final_attempt.relaxed_pin_reasons,
        "final_repair_strategy": final_attempt.name,
    }
    diagnostics["repair_attempts"] = repair_attempts
    diagnostics["pins_initial_count"] = len(auto_pins)
    diagnostics["pins_relaxed_count"] = pins_relaxed_count
    diagnostics["relaxed_pin_reasons"] = final_attempt.relaxed_pin_reasons
    diagnostics["final_repair_strategy"] = final_attempt.name
    diagnostics.setdefault("stability_explanations", stability.explanations)

    stability_penalty = result.metrics.stability_penalty or stability.stability_penalty
    changed_sessions = result.metrics.changed_sessions or stability.changed_sessions
    max_changed_sessions = _max_changed_sessions(repair_policy, auto_pins)
    changed_sessions_over_limit = changed_sessions > max_changed_sessions
    policy_warning = None
    if changed_sessions_over_limit:
        policy_warning = (
            f"Repair policy {repair_policy} changed {changed_sessions} session(s), "
            f"above the configured limit of {max_changed_sessions}."
        )
    diagnostics["repair_service"].update(
        {
            "repair_policy": repair_policy,
            "policy_used": repair_policy,
            "max_changed_sessions": max_changed_sessions,
            "changed_sessions_over_limit": changed_sessions_over_limit,
            "policy_warning": policy_warning,
        }
    )
    diagnostics["repair_policy"] = repair_policy
    diagnostics["policy_used"] = repair_policy
    diagnostics["max_changed_sessions"] = max_changed_sessions
    diagnostics["changed_sessions_over_limit"] = changed_sessions_over_limit
    diagnostics["policy_warning"] = policy_warning
    return RepairScheduleResult(
        success=result.success,
        message=f"{result.message}{relaxed_message}",
        schedule=result.schedule,
        solver_result=result,
        changed_sessions=changed_sessions,
        stability_penalty=stability_penalty,
        stability_score=max(0, 100 - stability_penalty),
        hard_conflicts=result.metrics.hard_conflicts,
        quality_score=result.metrics.quality_score,
        diagnostics=diagnostics,
        repair_mode=repair_type,
        repair_target=target,
        repair_policy=repair_policy,
        max_changed_sessions=max_changed_sessions,
        changed_sessions_over_limit=changed_sessions_over_limit,
        final_repair_strategy=final_attempt.name,
        pinned_assignments=len(final_attempt.automatic_pins) + len(pinned_assignments or []),
    )


def _build_repair_attempts(
    auto_pins: list[SolverAssignment],
    previous_schedule: dict[str, dict[str, ScheduleCell]],
    repair_type: RepairMode,
    target: str,
    repair_policy: RepairPolicy,
) -> list[_RepairAttempt]:
    if not auto_pins:
        return [_RepairAttempt("strict_pins", [], [], [])]
    pin_scores = [
        (pin, _pin_relaxation_score(pin, previous_schedule, repair_type, target))
        for pin in auto_pins
    ]
    close_pins = [pin for pin, score in pin_scores if score >= 3]
    medium_pins = [pin for pin, score in pin_scores if score >= 1]
    if repair_policy == "strict":
        attempts = [
            _attempt("strict_pins", auto_pins, []),
            _attempt("relax_near_target", auto_pins, close_pins),
            _attempt("relax_related_area", auto_pins, medium_pins),
            _attempt("stability_objective_only", auto_pins, auto_pins),
        ]
    elif repair_policy == "flexible":
        attempts = [
            _attempt("strict_pins", auto_pins, []),
            _attempt("relax_related_area", auto_pins, medium_pins),
            _attempt("stability_objective_only", auto_pins, auto_pins),
        ]
    else:
        attempts = [
            _attempt("strict_pins", auto_pins, []),
            _attempt("relax_near_target", auto_pins, close_pins),
            _attempt("relax_related_area", auto_pins, medium_pins),
            _attempt("stability_objective_only", auto_pins, auto_pins),
        ]
    deduped: list[_RepairAttempt] = []
    seen: set[tuple[str, ...]] = set()
    for attempt in attempts:
        key = tuple(sorted(_pin_key(pin) for pin in attempt.automatic_pins))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(attempt)
    return deduped


def _max_changed_sessions(repair_policy: RepairPolicy, auto_pins: list[SolverAssignment]) -> int:
    if repair_policy == "strict":
        return max(1, len(auto_pins) // 4)
    if repair_policy == "flexible":
        return max(6, len(auto_pins) * 2)
    return max(3, len(auto_pins))


def _attempt(name: str, auto_pins: list[SolverAssignment], relaxed: list[SolverAssignment]) -> _RepairAttempt:
    relaxed_keys = {_pin_key(pin) for pin in relaxed}
    kept = [pin for pin in auto_pins if _pin_key(pin) not in relaxed_keys]
    reasons = [_relaxed_pin_reason(pin, name) for pin in relaxed]
    return _RepairAttempt(name, kept, relaxed, reasons)


def _pin_relaxation_score(
    pin: SolverAssignment,
    previous_schedule: dict[str, dict[str, ScheduleCell]],
    repair_type: RepairMode,
    target: str,
) -> int:
    target_assignments = _target_assignments(previous_schedule, repair_type, target)
    if not target_assignments:
        return 1
    score = 0
    pin_day = _day_of(pin.slot)
    for assignment in target_assignments:
        if pin.slot == assignment.slot:
            score = max(score, 4)
        if pin_day == _day_of(assignment.slot):
            score = max(score, 3)
        if pin.teacher_name == assignment.teacher_name:
            score = max(score, 2)
        if pin.class_name == assignment.class_name:
            score = max(score, 2)
        if pin.subject == assignment.subject:
            score = max(score, 1)
    return score


def _target_assignments(
    previous_schedule: dict[str, dict[str, ScheduleCell]],
    repair_type: RepairMode,
    target: str,
) -> list[SolverAssignment]:
    assignments: list[SolverAssignment] = []
    for assignment in schedule_to_assignments(previous_schedule):
        if repair_type == "repair_class" and assignment.class_name == target:
            assignments.append(assignment)
        elif repair_type == "repair_teacher" and assignment.teacher_name == target:
            assignments.append(assignment)
        elif repair_type == "repair_day" and _day_of(assignment.slot) == target:
            assignments.append(assignment)
    return assignments


def _relaxed_pin_reason(pin: SolverAssignment, strategy: str) -> str:
    return (
        f"Relaxed pin {pin.class_name}/{pin.subject} at {pin.slot} with {pin.teacher_name} "
        f"for repair strategy {strategy}."
    )


def _pin_key(pin: SolverAssignment) -> str:
    if pin.session_id:
        return pin.session_id
    return f"{pin.slot}|{pin.class_name}|{pin.subject}|{pin.teacher_name}"


def _day_of(slot: str) -> str:
    return slot.split("-", 1)[0] if "-" in slot else slot


def _normalize_dataset(
    dataset: dict[str, Any] | None,
    classes: list[Class] | None,
    teachers: list[Teacher] | None,
    subjects: list[Subject] | None,
    slots: list[str] | None,
    conditions: list[Condition] | None,
) -> dict[str, Any]:
    if dataset is not None:
        classes = classes if classes is not None else dataset.get("classes")
        teachers = teachers if teachers is not None else dataset.get("teachers")
        subjects = subjects if subjects is not None else dataset.get("subjects")
        slots = slots if slots is not None else dataset.get("slots")
        conditions = conditions if conditions is not None else dataset.get("conditions", [])
    missing = [
        name
        for name, value in {
            "classes": classes,
            "teachers": teachers,
            "subjects": subjects,
            "slots": slots,
        }.items()
        if value is None
    ]
    if missing:
        raise ValueError(f"Missing repair dataset field(s): {', '.join(missing)}")
    return {
        "classes": list(classes or []),
        "teachers": list(teachers or []),
        "subjects": list(subjects or []),
        "slots": list(slots or []),
        "conditions": list(conditions or []),
    }


def _resolve_repair_target(
    *,
    repair_type: RepairMode,
    classes: list[Class],
    teachers: list[Teacher],
    class_id: int | None,
    teacher_id: int | None,
    day: str | None,
    repair_target: str | None,
) -> str:
    if repair_target:
        return repair_target
    if repair_type == "repair_class":
        if class_id is None:
            raise ValueError("repair_class requires class_id or repair_target.")
        for class_obj in classes:
            if class_obj.id == class_id:
                return class_obj.name
        raise ValueError(f"Unknown class_id for repair_class: {class_id}")
    if repair_type == "repair_teacher":
        if teacher_id is None:
            raise ValueError("repair_teacher requires teacher_id or repair_target.")
        for teacher in teachers:
            if teacher.id == teacher_id:
                return teacher.name
        raise ValueError(f"Unknown teacher_id for repair_teacher: {teacher_id}")
    if not day:
        raise ValueError("repair_day requires day or repair_target.")
    return day
