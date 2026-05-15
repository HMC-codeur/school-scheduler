from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from backend.models.schemas import Class, Condition, ScheduleCell, Teacher
from backend.services.scoring import analyze_schedule
from backend.services.solver.base import ScheduleSolver
from backend.services.solver.constraints import (
    STRATEGY_BALANCED,
    STRATEGY_CLASS_FRIENDLY,
    STRATEGY_COMPACT,
    STRATEGY_TEACHER_FRIENDLY,
    SUPPORTED_STRATEGIES,
    StrategyWeights,
    add_soft_quality_objective as constraints_add_soft_quality_objective,
    evaluate_quality as constraints_evaluate_quality,
    quality_explanations as constraints_quality_explanations,
    strategy_weights,
)
from backend.services.solver.feasibility import check_feasibility
from backend.services.solver.models import ScheduleInput, ScheduleResult, SolverAssignment, SolverMetrics
from backend.services.solver.stability import (
    effective_pinned_assignments,
    previous_by_class_subject,
    previous_by_session_id,
    previous_session_ids_by_class_subject,
    stable_session_id,
    stability_cost_for_candidate,
)

try:
    from ortools.sat.python import cp_model
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    cp_model = None


@dataclass(frozen=True)
class _Session:
    id: int
    class_id: int
    class_name: str
    subject: str
    session_id: str


@dataclass(frozen=True)
class _Candidate:
    slot: str
    day: str
    teacher_id: int
    teacher_name: str


class ORToolsSolver(ScheduleSolver):
    engine_name = "ortools"
    STRATEGY_BALANCED = STRATEGY_BALANCED
    STRATEGY_COMPACT = STRATEGY_COMPACT
    STRATEGY_TEACHER_FRIENDLY = STRATEGY_TEACHER_FRIENDLY
    STRATEGY_CLASS_FRIENDLY = STRATEGY_CLASS_FRIENDLY

    def __init__(
        self,
        max_time_seconds: float = 10.0,
        workers: int = 4,
        strategy: str = STRATEGY_BALANCED,
        weights: StrategyWeights | None = None,
    ) -> None:
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"Unsupported OR-Tools strategy: {strategy}")
        self.max_time_seconds = max_time_seconds
        self.workers = workers
        self.strategy = strategy
        self.weights = weights or strategy_weights(strategy)
        self.last_diagnostics: dict[str, Any] = {}

    def solve(self, input_data: ScheduleInput) -> ScheduleResult:
        started_at = perf_counter()
        required_sessions = _required_sessions(input_data)
        self.last_diagnostics = {
            "engine": self.engine_name,
            "required_sessions": required_sessions,
            "time_budget_seconds": self.max_time_seconds,
            "workers": self.workers,
            "preassign_teachers": True,
            "strategy": self.strategy,
            "has_previous_schedule": input_data.previous_schedule is not None,
            "repair_mode": input_data.repair_mode,
            "repair_target": input_data.repair_target,
        }

        if cp_model is None:
            return _failure(
                "OR-Tools is not installed. Install the 'ortools' package to use engine=ortools.",
                input_data,
                started_at,
                required_sessions,
            )
        feasibility = check_feasibility(input_data)
        self.last_diagnostics["pipeline"] = {
            "feasibility_check": "passed" if feasibility.feasible else "failed",
            "solve_valid_timetable": "pending",
            "optimize_quality": "pending",
            "explain_problems": "pending",
            "local_repair_ready": False,
        }
        self.last_diagnostics["feasibility"] = feasibility.as_dict()
        if not feasibility.feasible:
            first_issue = feasibility.issues[0]
            self.last_diagnostics["pipeline"]["solve_valid_timetable"] = "skipped"
            self.last_diagnostics["pipeline"]["optimize_quality"] = "skipped"
            self.last_diagnostics["pipeline"]["explain_problems"] = "completed"
            return _failure(
                f"OR-Tools feasibility check failed: {first_issue.message}",
                input_data,
                started_at,
                required_sessions,
            )

        context = _HardConstraintContext(input_data)
        effective_pins = effective_pinned_assignments(input_data)
        sessions = _prioritize_sessions(_build_sessions(input_data), input_data, context)
        domains = _build_domains(sessions, input_data, context, self.strategy, self.weights, effective_pins)
        self.last_diagnostics.update(_domain_diagnostics(domains))
        empty_domains = [session for session in sessions if not domains.get(session.id)]
        if empty_domains:
            session = empty_domains[0]
            self.last_diagnostics["first_empty_domain"] = f"{session.class_name}/{session.subject}"
            return _failure(
                f"OR-Tools solver failed: no compatible slot/teacher for {session.class_name} / {session.subject}.",
                input_data,
                started_at,
                required_sessions,
            )

        model = cp_model.CpModel()
        variables: dict[tuple[int, int], object] = {}
        for session in sessions:
            for candidate_index, _candidate in enumerate(domains[session.id]):
                variables[(session.id, candidate_index)] = model.NewBoolVar(f"s{session.id}_c{candidate_index}")
        self.last_diagnostics["boolean_variables"] = len(variables)

        for session in sessions:
            model.Add(sum(variables[(session.id, index)] for index in range(len(domains[session.id]))) == 1)

        by_class_slot: dict[tuple[int, str], list[object]] = defaultdict(list)
        by_teacher_slot: dict[tuple[int, str], list[object]] = defaultdict(list)
        by_class_day: dict[tuple[int, str], list[object]] = defaultdict(list)
        by_teacher_day: dict[tuple[int, str], list[object]] = defaultdict(list)
        by_class_subject_day: dict[tuple[int, str, str], list[object]] = defaultdict(list)
        by_subject_slot: dict[tuple[str, str], list[object]] = defaultdict(list)
        teacher_expected_loads: dict[int, int] = defaultdict(int)

        for session in sessions:
            session_teacher_ids = set()
            for candidate_index, candidate in enumerate(domains[session.id]):
                var = variables[(session.id, candidate_index)]
                by_class_slot[(session.class_id, candidate.slot)].append(var)
                by_teacher_slot[(candidate.teacher_id, candidate.slot)].append(var)
                by_class_day[(session.class_id, candidate.day)].append(var)
                by_teacher_day[(candidate.teacher_id, candidate.day)].append(var)
                by_class_subject_day[(session.class_id, session.subject, candidate.day)].append(var)
                by_subject_slot[(session.subject, candidate.slot)].append(var)
                session_teacher_ids.add(candidate.teacher_id)
            for teacher_id in session_teacher_ids:
                teacher_expected_loads[teacher_id] += 1

        for vars_for_resource in by_class_slot.values():
            model.Add(sum(vars_for_resource) <= 1)
        for vars_for_resource in by_teacher_slot.values():
            model.Add(sum(vars_for_resource) <= 1)
        for (class_id, _day), vars_for_resource in by_class_day.items():
            model.Add(sum(vars_for_resource) <= context.class_daily_limits[class_id])
        for (teacher_id, _day), vars_for_resource in by_teacher_day.items():
            model.Add(sum(vars_for_resource) <= context.teacher_daily_limits[teacher_id])
        pinning = _add_pinning_constraints(model, variables, domains, sessions, effective_pins)
        self.last_diagnostics["class_slot_constraints"] = len(by_class_slot)
        self.last_diagnostics["teacher_slot_constraints"] = len(by_teacher_slot)
        self.last_diagnostics["class_day_constraints"] = len(by_class_day)
        self.last_diagnostics["teacher_day_constraints"] = len(by_teacher_day)
        self.last_diagnostics["pinned_assignments"] = pinning["pinned_assignments"]
        self.last_diagnostics["pinning_constraints"] = pinning["pinning_constraints"]

        quality_objective = constraints_add_soft_quality_objective(
            model=model,
            input_data=input_data,
            context=context,
            by_class_slot=by_class_slot,
            by_teacher_slot=by_teacher_slot,
            by_class_day=by_class_day,
            by_teacher_day=by_teacher_day,
            by_class_subject_day=by_class_subject_day,
            by_subject_slot=by_subject_slot,
            teacher_expected_loads=teacher_expected_loads,
            weights=self.weights,
        )
        if quality_objective.terms:
            stability_terms = _stability_objective_terms(variables, domains, sessions, input_data)
            quality_objective.terms.extend(stability_terms)
            self.last_diagnostics["stability_terms"] = len(stability_terms)
            model.Minimize(sum(weight * term for weight, term in quality_objective.terms))
        self.last_diagnostics["soft_terms"] = len(quality_objective.terms)
        self.last_diagnostics["soft_constraints_enabled"] = True

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.max_time_seconds
        solver.parameters.num_search_workers = self.workers
        status = solver.Solve(model)
        self.last_diagnostics["cp_status"] = solver.StatusName(status)
        self.last_diagnostics["cp_wall_time_seconds"] = round(float(solver.WallTime()), 4)
        self.last_diagnostics["cp_conflicts"] = int(solver.NumConflicts())
        self.last_diagnostics["cp_branches"] = int(solver.NumBranches())
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if status == cp_model.INFEASIBLE:
                message = "OR-Tools solver failed: constraints are infeasible for the V1 hard-constraints model."
            else:
                message = "OR-Tools solver failed: no feasible schedule found within the V1 time budget."
            return _failure(
                message,
                input_data,
                started_at,
                required_sessions,
            )
        self.last_diagnostics["pipeline"]["solve_valid_timetable"] = "completed"

        assignments: list[SolverAssignment] = []
        schedule: dict[str, dict[str, ScheduleCell]] = defaultdict(dict)
        for session in sessions:
            for candidate_index, candidate in enumerate(domains[session.id]):
                if solver.BooleanValue(variables[(session.id, candidate_index)]):
                    assignments.append(
                        SolverAssignment(
                            slot=candidate.slot,
                            class_name=session.class_name,
                            subject=session.subject,
                            teacher_name=candidate.teacher_name,
                            session_id=session.session_id,
                        )
                    )
                    schedule[candidate.slot][session.class_name] = ScheduleCell(
                        subject=session.subject,
                        teacher=candidate.teacher_name,
                        session_id=session.session_id,
                    )
                    break

        normalized_schedule = dict(schedule)
        quality = constraints_evaluate_quality(input_data, normalized_schedule, started_at)
        metrics = _build_metrics(input_data, normalized_schedule, assignments, started_at, success=True, quality=quality)
        self.last_diagnostics["scheduled_sessions"] = metrics.scheduled_sessions
        self.last_diagnostics["hard_conflicts"] = metrics.hard_conflicts
        self.last_diagnostics["quality"] = quality
        self.last_diagnostics["quality_explanations"] = constraints_quality_explanations(input_data, normalized_schedule, quality)
        self.last_diagnostics["stability"] = {
            "stability_penalty": metrics.stability_penalty,
            "changed_sessions": metrics.changed_sessions,
        }
        self.last_diagnostics["pipeline"]["optimize_quality"] = "completed"
        self.last_diagnostics["pipeline"]["explain_problems"] = "completed"
        self.last_diagnostics["pipeline"]["local_repair_ready"] = True
        return ScheduleResult(
            success=True,
            message="OR-Tools experimental solver generated a valid hard-constraints schedule.",
            schedule=normalized_schedule,
            assignments=assignments,
            metrics=metrics,
        )


class ORToolsMultiStrategySolver(ScheduleSolver):
    engine_name = "ortools_multi_strategy"

    def __init__(
        self,
        max_time_seconds: float = 10.0,
        workers: int = 4,
        strategies: list[str] | None = None,
    ) -> None:
        self.max_time_seconds = max_time_seconds
        self.workers = workers
        self.strategies = strategies or [
            STRATEGY_BALANCED,
            STRATEGY_COMPACT,
            STRATEGY_TEACHER_FRIENDLY,
            STRATEGY_CLASS_FRIENDLY,
        ]
        self.last_diagnostics: dict[str, Any] = {}

    def solve(self, input_data: ScheduleInput) -> ScheduleResult:
        per_strategy_budget = max(1.0, self.max_time_seconds)
        attempts: list[tuple[str, ScheduleResult, dict[str, Any]]] = []
        for strategy in self.strategies:
            solver = ORToolsSolver(
                max_time_seconds=per_strategy_budget,
                workers=self.workers,
                strategy=strategy,
            )
            result = solver.solve(input_data)
            attempts.append((strategy, result, dict(solver.last_diagnostics)))

        successful = [item for item in attempts if item[1].success]
        candidates = successful or attempts
        winning_strategy, best_result, best_diagnostics = max(
            candidates,
            key=lambda item: (
                1 if item[1].success else 0,
                int(item[1].metrics.total_score or item[1].metrics.quality_score or 0),
                -int(item[1].metrics.gaps_class + item[1].metrics.gaps_teacher),
            ),
        )
        self.last_diagnostics = {
            **best_diagnostics,
            "engine": self.engine_name,
            "strategy": winning_strategy,
            "winning_strategy": winning_strategy,
            "multi_strategy": True,
            "per_strategy_time_budget_seconds": per_strategy_budget,
            "strategy_results": [
                {
                    "strategy": strategy,
                    "success": result.success,
                    "total_score": result.metrics.total_score,
                    "hard_conflicts": result.metrics.hard_conflicts,
                    "time_ms": result.metrics.generation_time_ms,
                    "cp_status": diagnostics.get("cp_status"),
                }
                for strategy, result, diagnostics in attempts
            ],
        }
        return best_result


class _HardConstraintContext:
    def __init__(self, input_data: ScheduleInput) -> None:
        self.slot_day = {slot: slot.split("-", 1)[0] if "-" in slot else slot for slot in input_data.slots}
        self.slots_by_day: dict[str, list[str]] = defaultdict(list)
        for slot in input_data.slots:
            self.slots_by_day[self.slot_day[slot]].append(slot)
        self.days = sorted(self.slots_by_day)
        self.slot_day_position = {
            slot: position
            for day_slots in self.slots_by_day.values()
            for position, slot in enumerate(day_slots)
        }
        self.teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
        for teacher in input_data.teachers:
            for subject in teacher.subjects:
                self.teachers_by_subject[subject].append(teacher)
        self.teacher_unavailable = {teacher.id: set(teacher.unavailable_slots) for teacher in input_data.teachers}
        self.class_unavailable: dict[int, set[str]] = defaultdict(set)
        self.class_daily_limits = {class_obj.id: max(1, class_obj.max_lessons_per_day) for class_obj in input_data.classes}
        self.teacher_daily_limits = {teacher.id: max(1, teacher.max_lessons_per_day) for teacher in input_data.teachers}
        self.teacher_by_id = {teacher.id: teacher for teacher in input_data.teachers}
        self.teacher_capacity = {
            teacher.id: self._teacher_weekly_capacity(teacher, input_data.slots)
            for teacher in input_data.teachers
        }

        class_by_name = {class_obj.name: class_obj for class_obj in input_data.classes}
        teacher_by_name = {teacher.name: teacher for teacher in input_data.teachers}
        for condition in input_data.conditions:
            if condition.condition_type == "teacher_unavailable" and condition.teacher_name and condition.slot:
                teacher = teacher_by_name.get(condition.teacher_name)
                if teacher:
                    self.teacher_unavailable.setdefault(teacher.id, set()).add(condition.slot)
            elif condition.condition_type == "class_unavailable" and condition.class_name and condition.slot:
                class_obj = class_by_name.get(condition.class_name)
                if class_obj:
                    self.class_unavailable[class_obj.id].add(condition.slot)

    def _teacher_weekly_capacity(self, teacher: Teacher, slots: list[str]) -> int:
        available_by_day: dict[str, int] = defaultdict(int)
        for slot in slots:
            if slot in self.teacher_unavailable.get(teacher.id, set()):
                continue
            available_by_day[self.slot_day[slot]] += 1
        daily_limit = self.teacher_daily_limits[teacher.id]
        return sum(min(daily_limit, count) for count in available_by_day.values())


def _required_sessions(input_data: ScheduleInput) -> int:
    return len(input_data.classes) * sum(max(0, subject.hours_per_week) for subject in input_data.subjects)


def _build_sessions(input_data: ScheduleInput) -> list[_Session]:
    sessions: list[_Session] = []
    numeric_id = 0
    previous_ids = previous_session_ids_by_class_subject(input_data.previous_schedule)
    occurrence_by_course: dict[tuple[str, str], int] = defaultdict(int)
    for class_obj in input_data.classes:
        for subject in input_data.subjects:
            key = (class_obj.name, subject.name)
            for _ in range(max(0, subject.hours_per_week)):
                occurrence_by_course[key] += 1
                occurrence = occurrence_by_course[key]
                existing_ids = previous_ids.get(key, [])
                logical_session_id = (
                    existing_ids[occurrence - 1]
                    if occurrence <= len(existing_ids)
                    else stable_session_id(class_obj.name, subject.name, occurrence)
                )
                sessions.append(_Session(numeric_id, class_obj.id, class_obj.name, subject.name, logical_session_id))
                numeric_id += 1
    return sessions


def _prioritize_sessions(
    sessions: list[_Session],
    input_data: ScheduleInput,
    context: _HardConstraintContext,
) -> list[_Session]:
    subject_teacher_count = {
        subject.name: len(context.teachers_by_subject.get(subject.name, []))
        for subject in input_data.subjects
    }
    class_available_slots = {
        class_obj.id: sum(1 for slot in input_data.slots if slot not in context.class_unavailable.get(class_obj.id, set()))
        for class_obj in input_data.classes
    }
    return sorted(
        sessions,
        key=lambda session: (
            subject_teacher_count.get(session.subject, 0),
            class_available_slots.get(session.class_id, 0),
            session.subject,
            session.class_name,
            session.id,
        ),
    )


def _build_domains(
    sessions: list[_Session],
    input_data: ScheduleInput,
    context: _HardConstraintContext,
    strategy: str,
    weights: StrategyWeights,
    pinned_assignments: list[SolverAssignment] | None = None,
) -> dict[int, list[_Candidate]]:
    domains: dict[int, list[_Candidate]] = {}
    teacher_loads: dict[int, int] = defaultdict(int)
    pinned_by_class_subject: dict[tuple[str, str], list[SolverAssignment]] = defaultdict(list)
    for pinned in pinned_assignments or []:
        pinned_by_class_subject[(pinned.class_name, pinned.subject)].append(pinned)
    for session in sessions:
        session_pins = [
            pin
            for pin in pinned_by_class_subject.get((session.class_name, session.subject), [])
            if not pin.session_id or pin.session_id == session.session_id
        ]
        teacher = _select_teacher_for_session(session, input_data, context, teacher_loads, strategy, weights, session_pins)
        if teacher is None:
            domains[session.id] = []
            continue
        teacher_loads[teacher.id] += 1

        candidates = []
        for slot in input_data.slots:
            if slot in context.class_unavailable.get(session.class_id, set()):
                continue
            if slot in context.teacher_unavailable.get(teacher.id, set()):
                continue
            if session_pins and not any(pin.slot == slot and pin.teacher_name == teacher.name for pin in session_pins):
                continue
            candidates.append(
                _Candidate(
                    slot=slot,
                    day=context.slot_day[slot],
                    teacher_id=teacher.id,
                    teacher_name=teacher.name,
                )
            )
        domains[session.id] = candidates
    return domains


def _select_teacher_for_session(
    session: _Session,
    input_data: ScheduleInput,
    context: _HardConstraintContext,
    teacher_loads: dict[int, int],
    strategy: str,
    weights: StrategyWeights,
    pinned_assignments: list[SolverAssignment] | None = None,
) -> Teacher | None:
    if pinned_assignments:
        pinned_teacher_names = {pin.teacher_name for pin in pinned_assignments}
        for teacher in context.teachers_by_subject.get(session.subject, []):
            if teacher.name not in pinned_teacher_names:
                continue
            capacity = context.teacher_capacity.get(teacher.id, 0)
            if teacher_loads[teacher.id] < capacity and _feasible_slots_for_teacher_session(session, teacher, input_data, context):
                return teacher
        return None

    candidates: list[tuple[float, int, int, int, str, Teacher]] = []
    for teacher in context.teachers_by_subject.get(session.subject, []):
        capacity = context.teacher_capacity.get(teacher.id, 0)
        if teacher_loads[teacher.id] >= capacity:
            continue
        feasible_slots = _feasible_slots_for_teacher_session(session, teacher, input_data, context)
        if not feasible_slots:
            continue
        load_ratio = teacher_loads[teacher.id] / max(1, capacity)
        subject_count = len(teacher.subjects)
        if strategy == STRATEGY_TEACHER_FRIENDLY:
            key = (load_ratio * weights.teacher_load_preassignment, teacher_loads[teacher.id], -len(feasible_slots), subject_count, teacher.name, teacher)
        elif strategy == STRATEGY_COMPACT:
            key = (load_ratio, -len(feasible_slots), teacher_loads[teacher.id], subject_count, teacher.name, teacher)
        elif strategy == STRATEGY_CLASS_FRIENDLY:
            key = (load_ratio, subject_count, teacher_loads[teacher.id], -len(feasible_slots), teacher.name, teacher)
        else:
            key = (load_ratio, teacher_loads[teacher.id], -len(feasible_slots), subject_count, teacher.name, teacher)
        candidates.append(key)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[:4])
    return candidates[0][5]


def _feasible_slots_for_teacher_session(
    session: _Session,
    teacher: Teacher,
    input_data: ScheduleInput,
    context: _HardConstraintContext,
) -> list[str]:
    return [
        slot
        for slot in input_data.slots
        if slot not in context.class_unavailable.get(session.class_id, set())
        and slot not in context.teacher_unavailable.get(teacher.id, set())
    ]


def _domain_diagnostics(domains: dict[int, list[_Candidate]]) -> dict[str, int | float]:
    sizes = [len(candidates) for candidates in domains.values()]
    if not sizes:
        return {
            "sessions": 0,
            "candidate_variables": 0,
            "min_domain_size": 0,
            "max_domain_size": 0,
            "avg_domain_size": 0.0,
            "empty_domains": 0,
        }
    return {
        "sessions": len(sizes),
        "candidate_variables": sum(sizes),
        "min_domain_size": min(sizes),
        "max_domain_size": max(sizes),
        "avg_domain_size": round(sum(sizes) / len(sizes), 2),
        "empty_domains": sum(1 for size in sizes if size == 0),
    }


def _add_pinning_constraints(
    model: Any,
    variables: dict[tuple[int, int], object],
    domains: dict[int, list[_Candidate]],
    sessions: list[_Session],
    pinned_assignments: list[SolverAssignment],
) -> dict[str, int]:
    pinning_constraints = 0
    for pinned in pinned_assignments:
        matching_vars: list[object] = []
        for session in sessions:
            if pinned.session_id and session.session_id != pinned.session_id:
                continue
            if session.class_name != pinned.class_name or session.subject != pinned.subject:
                continue
            for candidate_index, candidate in enumerate(domains.get(session.id, [])):
                if candidate.slot == pinned.slot and candidate.teacher_name == pinned.teacher_name:
                    matching_vars.append(variables[(session.id, candidate_index)])
        if matching_vars:
            model.Add(sum(matching_vars) == 1)
            pinning_constraints += 1
    return {"pinned_assignments": len(pinned_assignments), "pinning_constraints": pinning_constraints}


def _stability_objective_terms(
    variables: dict[tuple[int, int], object],
    domains: dict[int, list[_Candidate]],
    sessions: list[_Session],
    input_data: ScheduleInput,
) -> list[tuple[int, object]]:
    previous = previous_by_class_subject(input_data.previous_schedule)
    previous_by_id = previous_by_session_id(input_data.previous_schedule)
    if not previous and not previous_by_id:
        return []
    terms: list[tuple[int, object]] = []
    for session in sessions:
        for candidate_index, candidate in enumerate(domains.get(session.id, [])):
            exact_previous = previous_by_id.get(session.session_id)
            if exact_previous:
                cost = (6 if exact_previous.slot != candidate.slot else 0) + (
                    4 if exact_previous.teacher_name != candidate.teacher_name else 0
                )
            else:
                cost = stability_cost_for_candidate(
                    previous,
                    session.class_name,
                    session.subject,
                    candidate.slot,
                    candidate.teacher_name,
                )
            if cost:
                terms.append((cost, variables[(session.id, candidate_index)]))
    return terms


@dataclass(frozen=True)
class _QualityObjective:
    terms: list[tuple[int, object]]


def _add_soft_quality_objective(
    model: Any,
    input_data: ScheduleInput,
    context: _HardConstraintContext,
    by_class_slot: dict[tuple[int, str], list[object]],
    by_teacher_slot: dict[tuple[int, str], list[object]],
    by_class_day: dict[tuple[int, str], list[object]],
    by_teacher_day: dict[tuple[int, str], list[object]],
    by_class_subject_day: dict[tuple[int, str, str], list[object]],
    teacher_expected_loads: dict[int, int],
) -> _QualityObjective:
    terms: list[tuple[int, object]] = []
    class_used = _build_usage_bools(model, "class_slot", by_class_slot)
    teacher_used = _build_usage_bools(model, "teacher_slot", by_teacher_slot)
    class_weekly_hours = sum(max(0, subject.hours_per_week) for subject in input_data.subjects)
    day_count = max(1, len(context.days))
    ideal_class_daily_load = max(1, (class_weekly_hours + day_count - 1) // day_count)

    _add_gap_penalties(model, terms, class_used, context.slots_by_day, weight=12, prefix="class_gap")
    _add_gap_penalties(model, terms, teacher_used, context.slots_by_day, weight=5, prefix="teacher_gap")
    _add_long_sequence_penalties(model, terms, class_used, context.slots_by_day, weight=8, prefix="class_long")
    _add_long_sequence_penalties(model, terms, teacher_used, context.slots_by_day, weight=4, prefix="teacher_long")

    for class_obj in input_data.classes:
        for day in context.days:
            load = sum(by_class_day.get((class_obj.id, day), []))
            overload = model.NewIntVar(0, len(context.slots_by_day[day]), f"class_overload_{class_obj.id}_{day}")
            model.Add(overload >= load - ideal_class_daily_load)
            terms.append((4, overload))

            delta = model.NewIntVar(-len(context.slots_by_day[day]), len(context.slots_by_day[day]), f"class_spread_delta_{class_obj.id}_{day}")
            deviation = model.NewIntVar(0, len(context.slots_by_day[day]), f"class_spread_dev_{class_obj.id}_{day}")
            model.Add(delta == load - ideal_class_daily_load)
            model.AddAbsEquality(deviation, delta)
            terms.append((2, deviation))

    for teacher in input_data.teachers:
        expected_load = teacher_expected_loads.get(teacher.id, 0)
        if expected_load <= 0:
            continue
        ideal_teacher_daily_load = max(1, (expected_load + day_count - 1) // day_count)
        for day in context.days:
            load = sum(by_teacher_day.get((teacher.id, day), []))
            overload = model.NewIntVar(0, len(context.slots_by_day[day]), f"teacher_overload_{teacher.id}_{day}")
            model.Add(overload >= load - ideal_teacher_daily_load)
            terms.append((3, overload))

    for class_obj in input_data.classes:
        for subject in input_data.subjects:
            ideal_subject_daily = max(1, (max(0, subject.hours_per_week) + day_count - 1) // day_count)
            for day in context.days:
                count = sum(by_class_subject_day.get((class_obj.id, subject.name, day), []))
                repeated = model.NewIntVar(0, max(0, subject.hours_per_week), f"subject_spread_{class_obj.id}_{subject.name}_{day}")
                model.Add(repeated >= count - ideal_subject_daily)
                terms.append((5, repeated))

    for (class_id, slot), used in class_used.items():
        terms.append((1, used * context.slot_day_position.get(slot, 0)))

    return _QualityObjective(terms=terms)


def _build_usage_bools(model: Any, prefix: str, by_resource_slot: dict[tuple[int, str], list[object]]) -> dict[tuple[int, str], object]:
    usage: dict[tuple[int, str], object] = {}
    for key, vars_for_slot in by_resource_slot.items():
        used = model.NewBoolVar(f"{prefix}_{key[0]}_{_safe_name(key[1])}")
        model.Add(used == sum(vars_for_slot))
        usage[key] = used
    return usage


def _add_gap_penalties(
    model: Any,
    terms: list[tuple[int, object]],
    usage: dict[tuple[int, str], object],
    slots_by_day: dict[str, list[str]],
    weight: int,
    prefix: str,
) -> None:
    resource_ids = sorted({resource_id for resource_id, _slot in usage})
    for resource_id in resource_ids:
        for day, day_slots in slots_by_day.items():
            for index, slot in enumerate(day_slots):
                used_mid = usage.get((resource_id, slot))
                if used_mid is None:
                    continue
                before = [usage[(resource_id, item)] for item in day_slots[:index] if (resource_id, item) in usage]
                after = [usage[(resource_id, item)] for item in day_slots[index + 1:] if (resource_id, item) in usage]
                if not before or not after:
                    continue
                has_before = model.NewBoolVar(f"{prefix}_before_{resource_id}_{day}_{index}")
                has_after = model.NewBoolVar(f"{prefix}_after_{resource_id}_{day}_{index}")
                gap = model.NewBoolVar(f"{prefix}_{resource_id}_{day}_{index}")
                model.AddMaxEquality(has_before, before)
                model.AddMaxEquality(has_after, after)
                model.Add(gap <= has_before)
                model.Add(gap <= has_after)
                model.Add(gap <= 1 - used_mid)
                model.Add(gap >= has_before + has_after - used_mid - 1)
                terms.append((weight, gap))


def _add_long_sequence_penalties(
    model: Any,
    terms: list[tuple[int, object]],
    usage: dict[tuple[int, str], object],
    slots_by_day: dict[str, list[str]],
    weight: int,
    prefix: str,
    threshold: int = 5,
) -> None:
    resource_ids = sorted({resource_id for resource_id, _slot in usage})
    for resource_id in resource_ids:
        for day, day_slots in slots_by_day.items():
            if len(day_slots) < threshold:
                continue
            for index in range(0, len(day_slots) - threshold + 1):
                window = [usage.get((resource_id, slot)) for slot in day_slots[index:index + threshold]]
                if any(item is None for item in window):
                    continue
                long_sequence = model.NewBoolVar(f"{prefix}_{resource_id}_{day}_{index}")
                model.Add(long_sequence >= sum(window) - threshold + 1)
                terms.append((weight, long_sequence))


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)


def _build_metrics(
    input_data: ScheduleInput,
    schedule: dict[str, dict[str, ScheduleCell]],
    assignments: list[SolverAssignment],
    started_at: float,
    success: bool,
    quality: dict[str, int] | None = None,
) -> SolverMetrics:
    required_sessions = _required_sessions(input_data)
    scored = analyze_schedule(
        schedule,
        input_data.classes,
        input_data.teachers,
        input_data.subjects,
        input_data.slots,
        input_data.conditions,
    )
    class_conflicts = int(scored.get("class_conflicts", 0))
    teacher_conflicts = int(scored.get("teacher_conflicts", 0))
    incompatible = int(scored.get("incompatible_assignments", 0))
    unplaced = int(scored.get("unplaced_sessions", max(0, required_sessions - len(assignments))))
    hard_conflicts = class_conflicts + teacher_conflicts + incompatible + unplaced
    final_quality_score = int(quality["total_score"]) if quality is not None else max(0, min(100, 100 - hard_conflicts * 25))
    return SolverMetrics(
        engine=ORToolsSolver.engine_name,
        success=success,
        required_sessions=required_sessions,
        scheduled_sessions=len(assignments),
        generation_time_ms=int((perf_counter() - started_at) * 1000),
        hard_conflicts=hard_conflicts,
        class_conflicts=class_conflicts,
        teacher_conflicts=teacher_conflicts,
        incompatible_assignments=incompatible,
        unplaced_sessions=unplaced,
        quality_score=final_quality_score,
        soft_score=int(quality.get("soft_score", final_quality_score)) if quality else None,
        gaps_class=int(quality.get("gaps_class", 0)) if quality else 0,
        gaps_teacher=int(quality.get("gaps_teacher", 0)) if quality else 0,
        overloaded_days=int(quality.get("overloaded_days", 0)) if quality else 0,
        spread_penalty=int(quality.get("spread_penalty", 0)) if quality else 0,
        compactness_penalty=int(quality.get("compactness_penalty", 0)) if quality else 0,
        long_series_penalty=int(quality.get("long_series_penalty", 0)) if quality else 0,
        stability_penalty=int(quality.get("stability_penalty", 0)) if quality else 0,
        changed_sessions=int(quality.get("changed_sessions", 0)) if quality else 0,
        total_score=final_quality_score,
    )


def _evaluate_quality(
    input_data: ScheduleInput,
    schedule: dict[str, dict[str, ScheduleCell]],
    started_at: float,
) -> dict[str, int]:
    slot_day = {slot: slot.split("-", 1)[0] if "-" in slot else slot for slot in input_data.slots}
    slots_by_day: dict[str, list[str]] = defaultdict(list)
    for slot in input_data.slots:
        slots_by_day[slot_day[slot]].append(slot)
    days = sorted(slots_by_day)
    position_by_slot = {
        slot: position
        for day_slots in slots_by_day.values()
        for position, slot in enumerate(day_slots)
    }
    subject_hours = {subject.name: max(0, subject.hours_per_week) for subject in input_data.subjects}
    class_ids_by_name = {class_obj.name: class_obj.id for class_obj in input_data.classes}
    class_daily_target = max(1, (sum(subject_hours.values()) + max(1, len(days)) - 1) // max(1, len(days)))

    class_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    teacher_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    class_day_load: dict[tuple[str, str], int] = defaultdict(int)
    teacher_day_load: dict[tuple[str, str], int] = defaultdict(int)
    class_subject_day_load: dict[tuple[str, str, str], int] = defaultdict(int)
    teacher_total_load: dict[str, int] = defaultdict(int)
    compactness_penalty = 0

    for slot, entries in schedule.items():
        day = slot_day.get(slot, slot.split("-", 1)[0])
        position = position_by_slot.get(slot, 0)
        for class_name, cell in entries.items():
            class_day_positions[(class_name, day)].append(position)
            teacher_day_positions[(cell.teacher, day)].append(position)
            class_day_load[(class_name, day)] += 1
            teacher_day_load[(cell.teacher, day)] += 1
            class_subject_day_load[(class_name, cell.subject, day)] += 1
            teacher_total_load[cell.teacher] += 1
            compactness_penalty += position

    gaps_class = sum(_gap_count(positions) for positions in class_day_positions.values())
    gaps_teacher = sum(_gap_count(positions) for positions in teacher_day_positions.values())
    long_sequences = (
        sum(1 for positions in class_day_positions.values() if _has_long_sequence(positions))
        + sum(1 for positions in teacher_day_positions.values() if _has_long_sequence(positions))
    )

    overloaded_days = 0
    spread_penalty = 0
    for class_obj in input_data.classes:
        for day in days:
            load = class_day_load[(class_obj.name, day)]
            if load > class_daily_target:
                overloaded_days += load - class_daily_target
            spread_penalty += abs(load - class_daily_target)

    for teacher_name, total_load in teacher_total_load.items():
        teacher_target = max(1, (total_load + max(1, len(days)) - 1) // max(1, len(days)))
        for day in days:
            load = teacher_day_load[(teacher_name, day)]
            if load > teacher_target:
                overloaded_days += load - teacher_target

    for class_obj in input_data.classes:
        for subject_name, hours in subject_hours.items():
            ideal_subject_daily = max(1, (hours + max(1, len(days)) - 1) // max(1, len(days)))
            for day in days:
                repeated = max(0, class_subject_day_load[(class_obj.name, subject_name, day)] - ideal_subject_daily)
                spread_penalty += repeated * 2

    hard = analyze_schedule(
        schedule,
        input_data.classes,
        input_data.teachers,
        input_data.subjects,
        input_data.slots,
        input_data.conditions,
    )
    hard_conflicts = (
        int(hard.get("class_conflicts", 0))
        + int(hard.get("teacher_conflicts", 0))
        + int(hard.get("incompatible_assignments", 0))
        + int(hard.get("unplaced_sessions", 0))
    )
    compactness_scaled = compactness_penalty // 20
    total_penalty = (
        hard_conflicts * 100
        + gaps_class * 8
        + gaps_teacher * 3
        + overloaded_days * 4
        + spread_penalty * 2
        + long_sequences * 6
        + compactness_scaled
    )
    required_sessions = max(1, _required_sessions(input_data))
    normalized_penalty_points = int((total_penalty * 100) / max(1, required_sessions * 20))
    return {
        "gaps_class": gaps_class,
        "gaps_teacher": gaps_teacher,
        "overloaded_days": overloaded_days,
        "spread_penalty": spread_penalty,
        "compactness_penalty": compactness_scaled,
        "long_sequences": long_sequences,
        "hard_conflicts": hard_conflicts,
        "total_penalty": total_penalty,
        "total_score": max(0, min(100, 100 - normalized_penalty_points)),
        "generation_time_ms": int((perf_counter() - started_at) * 1000),
    }


def _quality_explanations(quality: dict[str, int]) -> list[str]:
    explanations: list[str] = []
    if quality["hard_conflicts"] == 0:
        explanations.append("Hard constraints are satisfied: no class or teacher conflict was detected.")
    if quality["gaps_class"]:
        explanations.append(f"Class gaps remain: {quality['gaps_class']} empty slot(s) inside class days.")
    else:
        explanations.append("Class days are compact: no class gap was detected.")
    if quality["gaps_teacher"]:
        explanations.append(f"Teacher gaps remain: {quality['gaps_teacher']} empty slot(s) inside teacher days.")
    else:
        explanations.append("Teacher days are compact: no teacher gap was detected.")
    if quality["overloaded_days"]:
        explanations.append(f"Some days are heavier than the weekly target by {quality['overloaded_days']} lesson unit(s).")
    else:
        explanations.append("Daily loads stay within the computed weekly-balance target.")
    if quality["spread_penalty"]:
        explanations.append(f"Weekly spread can improve: spread penalty is {quality['spread_penalty']}.")
    else:
        explanations.append("Lessons are evenly spread across the week for the V1 quality model.")
    if quality["long_sequences"]:
        explanations.append(f"Long sequences detected: {quality['long_sequences']} sequence(s) of five or more lessons.")
    else:
        explanations.append("No long sequence of five or more lessons was detected.")
    explanations.append(f"OR-Tools quality score: {quality['total_score']}/100.")
    return explanations


def _gap_count(positions: list[int]) -> int:
    if len(positions) < 2:
        return 0
    ordered = sorted(positions)
    return max(0, ordered[-1] - ordered[0] + 1 - len(ordered))


def _has_long_sequence(positions: list[int], threshold: int = 5) -> bool:
    if len(positions) < threshold:
        return False
    ordered = sorted(positions)
    streak = 1
    for index in range(1, len(ordered)):
        if ordered[index] == ordered[index - 1] + 1:
            streak += 1
            if streak >= threshold:
                return True
        else:
            streak = 1
    return False


def _failure(
    message: str,
    input_data: ScheduleInput,
    started_at: float,
    required_sessions: int,
) -> ScheduleResult:
    metrics = SolverMetrics(
        engine=ORToolsSolver.engine_name,
        success=False,
        required_sessions=required_sessions,
        scheduled_sessions=0,
        generation_time_ms=int((perf_counter() - started_at) * 1000),
        hard_conflicts=required_sessions,
        unplaced_sessions=required_sessions,
        quality_score=0,
    )
    return ScheduleResult(False, message, {}, [], metrics)
