from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.benchmarks.scheduler_benchmark import DATASETS, DATASET_ORDER, build_dataset
from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.solver.legacy_solver_adapter import LegacySolverAdapter
from backend.services.solver.models import ScheduleInput, SolverAssignment
from backend.services.solver.ortools_solver import ORToolsMultiStrategySolver, ORToolsSolver
from backend.services.solver.repair import repair_schedule


RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT = RESULTS_DIR / "solver_benchmark_latest.json"


def benchmark_solver_dataset(dataset_name: str) -> dict[str, Any]:
    if dataset_name not in DATASETS:
        raise ValueError(f"Unknown benchmark dataset: {dataset_name}")

    dataset = build_dataset(DATASETS[dataset_name])
    input_data = ScheduleInput(
        classes=dataset["classes"],
        teachers=dataset["teachers"],
        subjects=dataset["subjects"],
        slots=dataset["slots"],
        conditions=dataset["conditions"],
    )

    return {
        "dataset": dataset_name,
        "requested_sessions": _required_sessions(input_data),
        "engines": [
            _run_solver("legacy", LegacySolverAdapter(), input_data),
            _run_solver("ortools", ORToolsSolver(max_time_seconds=10.0), input_data),
        ],
    }


def run_solver_benchmarks(
    dataset_names: list[str],
    output_path: str | Path = DEFAULT_OUTPUT,
    ortools_time_budget_seconds: float = 10.0,
    ortools_strategy: str = "balanced",
    ortools_multi_strategy: bool = False,
) -> dict[str, Any]:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ortools_time_budget_seconds": ortools_time_budget_seconds,
        "ortools_strategy": ortools_strategy,
        "ortools_multi_strategy": ortools_multi_strategy,
        "results": [
            _benchmark_solver_dataset_with_budget(
                name,
                ortools_time_budget_seconds,
                ortools_strategy,
                ortools_multi_strategy,
            )
            for name in dataset_names
        ],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def run_delta_benchmark(
    dataset_name: str,
    output_path: str | Path = RESULTS_DIR / "solver_delta_benchmark_latest.json",
    ortools_time_budget_seconds: float = 10.0,
) -> dict[str, Any]:
    dataset = build_dataset(DATASETS[dataset_name])
    base_input = ScheduleInput(
        classes=dataset["classes"],
        teachers=dataset["teachers"],
        subjects=dataset["subjects"],
        slots=dataset["slots"],
        conditions=dataset["conditions"],
    )
    initial_solver = ORToolsSolver(max_time_seconds=ortools_time_budget_seconds)
    initial = initial_solver.solve(base_input)
    changed_input = _delta_input(base_input, initial.schedule)
    direct_solver = ORToolsSolver(max_time_seconds=ortools_time_budget_seconds)
    direct_repaired = direct_solver.solve(changed_input)
    repair_request = _delta_repair_request(base_input, initial.schedule, changed_input)
    service_repaired = repair_schedule(
        previous_schedule=initial.schedule,
        classes=base_input.classes,
        teachers=base_input.teachers,
        subjects=base_input.subjects,
        slots=base_input.slots,
        conditions=base_input.conditions,
        repair_type="repair_teacher",
        repair_target=repair_request["repair_target"],
        modified_constraints=repair_request["modified_constraints"],
        time_budget=ortools_time_budget_seconds,
    )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset_name,
        "initial": _result_payload("ortools_initial", initial_solver, initial, 0),
        "direct_schedule_input": _result_payload("ortools_delta_direct_schedule_input", direct_solver, direct_repaired, 0),
        "repair_service": _repair_result_payload("ortools_delta_repair_schedule", service_repaired),
        "repaired": _repair_result_payload("ortools_delta_repair_schedule", service_repaired),
        "delta": {
            "changed_sessions": service_repaired.changed_sessions,
            "stability_penalty": service_repaired.stability_penalty,
            "hard_conflicts": service_repaired.hard_conflicts,
            "quality_score": service_repaired.quality_score,
            "time_ms": service_repaired.solver_result.metrics.generation_time_ms,
            "direct_changed_sessions": direct_repaired.metrics.changed_sessions,
            "direct_stability_penalty": direct_repaired.metrics.stability_penalty,
            "repair_service_stability_score": service_repaired.stability_score,
        },
        "progressive_relaxation": _run_progressive_relaxation_case(ortools_time_budget_seconds),
        "policy_comparison": _run_policy_comparison(ortools_time_budget_seconds),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def run_delta_medium_policy_benchmark(
    output_path: str | Path = RESULTS_DIR / "solver_delta_medium_policy_latest.json",
    ortools_time_budget_seconds: float = 10.0,
    dataset_name: str = "medium",
) -> dict[str, Any]:
    if dataset_name not in DATASETS:
        raise ValueError(f"Unknown benchmark dataset: {dataset_name}")

    dataset = build_dataset(DATASETS[dataset_name])
    base_input = ScheduleInput(
        classes=dataset["classes"],
        teachers=dataset["teachers"],
        subjects=dataset["subjects"],
        slots=dataset["slots"],
        conditions=dataset["conditions"],
    )
    initial_time_budget_seconds = (
        max(20.0, ortools_time_budget_seconds)
        if dataset_name == "medium"
        else ortools_time_budget_seconds
    )
    initial_solver = ORToolsSolver(max_time_seconds=initial_time_budget_seconds)
    initial = initial_solver.solve(base_input)
    if not initial.success:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset_name,
            "success": False,
            "message": "Initial OR-Tools schedule failed; cannot run medium delta policy benchmark.",
            "initial_time_budget_seconds": initial_time_budget_seconds,
            "repair_time_budget_seconds": ortools_time_budget_seconds,
            "initial": _result_payload("ortools_initial", initial_solver, initial, 0),
            "policies": [],
        }
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    request = _realistic_policy_delta_request(base_input, initial.schedule)
    policies = []
    for policy in ["strict", "balanced", "flexible"]:
        repaired = repair_schedule(
            previous_schedule=initial.schedule,
            classes=base_input.classes,
            teachers=base_input.teachers,
            subjects=base_input.subjects,
            slots=base_input.slots,
            conditions=base_input.conditions,
            repair_type=request["repair_type"],
            repair_target=request["repair_target"],
            modified_constraints=request["modified_constraints"],
            repair_policy=policy,
            time_budget=ortools_time_budget_seconds,
        )
        policies.append(_medium_policy_summary(repaired))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset_name,
        "success": all(item["success"] for item in policies),
        "initial_time_budget_seconds": initial_time_budget_seconds,
        "repair_time_budget_seconds": ortools_time_budget_seconds,
        "scenario": request["scenario"],
        "initial": _result_payload("ortools_initial", initial_solver, initial, 0),
        "policies": policies,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _benchmark_solver_dataset_with_budget(
    dataset_name: str,
    ortools_time_budget_seconds: float,
    ortools_strategy: str,
    ortools_multi_strategy: bool,
) -> dict[str, Any]:
    if dataset_name not in DATASETS:
        raise ValueError(f"Unknown benchmark dataset: {dataset_name}")

    dataset = build_dataset(DATASETS[dataset_name])
    input_data = ScheduleInput(
        classes=dataset["classes"],
        teachers=dataset["teachers"],
        subjects=dataset["subjects"],
        slots=dataset["slots"],
        conditions=dataset["conditions"],
    )

    engines = [
        _run_solver("legacy", LegacySolverAdapter(), input_data),
        _run_solver(
            "ortools_single_strategy",
            ORToolsSolver(max_time_seconds=ortools_time_budget_seconds, strategy=ortools_strategy),
            input_data,
        ),
    ]
    if ortools_multi_strategy:
        engines.append(
            _run_solver(
                "ortools_multi_strategy",
                ORToolsMultiStrategySolver(max_time_seconds=ortools_time_budget_seconds),
                input_data,
            )
        )
    return {"dataset": dataset_name, "requested_sessions": _required_sessions(input_data), "engines": engines}


def _run_solver(engine: str, solver, input_data: ScheduleInput) -> dict[str, Any]:
    started_at = perf_counter()
    result = solver.solve(input_data)
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    metrics = result.metrics.as_dict()
    return _result_payload(engine, solver, result, elapsed_ms)


def _result_payload(engine: str, solver, result, elapsed_ms: int) -> dict[str, Any]:
    metrics = result.metrics.as_dict()
    return {
        "engine": engine,
        "success": result.success,
        "message": result.message,
        "time_ms": elapsed_ms or metrics["generation_time_ms"],
        "required_sessions": metrics["required_sessions"],
        "scheduled_sessions": metrics["scheduled_sessions"],
        "class_conflicts": metrics["class_conflicts"],
        "teacher_conflicts": metrics["teacher_conflicts"],
        "hard_conflicts": metrics["hard_conflicts"],
        "quality_score": metrics["quality_score"],
        "total_score": metrics.get("total_score"),
        "soft_score": metrics.get("soft_score"),
        "gaps_class": metrics.get("gaps_class"),
        "gaps_teacher": metrics.get("gaps_teacher"),
        "overloaded_days": metrics.get("overloaded_days"),
        "spread_penalty": metrics.get("spread_penalty"),
        "compactness_penalty": metrics.get("compactness_penalty"),
        "long_series_penalty": metrics.get("long_series_penalty"),
        "stability_penalty": metrics.get("stability_penalty"),
        "diagnostics": dict(getattr(solver, "last_diagnostics", {}) or {}),
    }


def _repair_result_payload(engine: str, repaired) -> dict[str, Any]:
    result = repaired.solver_result
    metrics = result.metrics.as_dict()
    return {
        "engine": engine,
        "success": repaired.success,
        "message": repaired.message,
        "time_ms": metrics["generation_time_ms"],
        "required_sessions": metrics["required_sessions"],
        "scheduled_sessions": metrics["scheduled_sessions"],
        "class_conflicts": metrics["class_conflicts"],
        "teacher_conflicts": metrics["teacher_conflicts"],
        "hard_conflicts": repaired.hard_conflicts,
        "quality_score": repaired.quality_score,
        "total_score": metrics.get("total_score"),
        "soft_score": metrics.get("soft_score"),
        "gaps_class": metrics.get("gaps_class"),
        "gaps_teacher": metrics.get("gaps_teacher"),
        "overloaded_days": metrics.get("overloaded_days"),
        "spread_penalty": metrics.get("spread_penalty"),
        "compactness_penalty": metrics.get("compactness_penalty"),
        "long_series_penalty": metrics.get("long_series_penalty"),
        "stability_penalty": repaired.stability_penalty,
        "stability_score": repaired.stability_score,
        "changed_sessions": repaired.changed_sessions,
        "repair_mode": repaired.repair_mode,
        "repair_target": repaired.repair_target,
        "repair_policy": repaired.repair_policy,
        "max_changed_sessions": repaired.max_changed_sessions,
        "changed_sessions_over_limit": repaired.changed_sessions_over_limit,
        "final_repair_strategy": repaired.final_repair_strategy,
        "diagnostics": repaired.diagnostics,
    }


def _delta_input(input_data: ScheduleInput, previous_schedule: dict) -> ScheduleInput:
    first_slot = next(iter(previous_schedule))
    first_class, first_cell = next(iter(previous_schedule[first_slot].items()))
    condition = Condition(
        id=900001,
        text="Delta benchmark teacher unavailable",
        condition_type="teacher_unavailable",
        teacher_name=first_cell.teacher,
        slot=first_slot,
    )
    return ScheduleInput(
        classes=input_data.classes,
        teachers=input_data.teachers,
        subjects=input_data.subjects,
        slots=input_data.slots,
        conditions=[*input_data.conditions, condition],
        previous_schedule=previous_schedule,
        repair_mode="repair_teacher",
        repair_target=first_cell.teacher,
    )


def _delta_repair_request(input_data: ScheduleInput, previous_schedule: dict, changed_input: ScheduleInput) -> dict[str, Any]:
    first_slot = next(iter(previous_schedule))
    first_cell = next(iter(previous_schedule[first_slot].values()))
    added_constraints = changed_input.conditions[len(input_data.conditions):]
    return {
        "repair_target": first_cell.teacher,
        "modified_constraints": added_constraints,
    }


def _realistic_policy_delta_request(input_data: ScheduleInput, previous_schedule: dict) -> dict[str, Any]:
    assignments = _schedule_assignments(previous_schedule)
    if len(assignments) < 3:
        return _small_policy_delta_request(assignments)

    by_teacher: dict[str, list[SolverAssignment]] = {}
    for assignment in assignments:
        by_teacher.setdefault(assignment.teacher_name, []).append(assignment)
    target_teacher, teacher_assignments = max(by_teacher.items(), key=lambda item: len(item[1]))
    teacher_change = teacher_assignments[0]

    pinned_candidates = [
        assignment
        for assignment in assignments
        if assignment.teacher_name != target_teacher
    ]
    class_change = _first_different_day_assignment(pinned_candidates, teacher_change.slot) or pinned_candidates[0]
    day_change = _first_same_day_assignment(
        [assignment for assignment in pinned_candidates if assignment != class_change],
        teacher_change.slot,
    )
    if day_change is None:
        day_change = pinned_candidates[-1]

    modified_constraints = [
        Condition(
            id=920001,
            text="Medium policy delta teacher unavailable",
            condition_type="teacher_unavailable",
            teacher_name=teacher_change.teacher_name,
            slot=teacher_change.slot,
        ),
        Condition(
            id=920002,
            text="Medium policy delta class blocked",
            condition_type="class_unavailable",
            class_name=class_change.class_name,
            slot=class_change.slot,
        ),
        Condition(
            id=920003,
            text="Medium policy delta day pressure",
            condition_type="teacher_unavailable",
            teacher_name=day_change.teacher_name,
            slot=day_change.slot,
        ),
    ]
    return {
        "repair_type": "repair_teacher",
        "repair_target": target_teacher,
        "modified_constraints": modified_constraints,
        "scenario": {
            "teacher_unavailable": f"{teacher_change.teacher_name} at {teacher_change.slot}",
            "class_constraint": f"{class_change.class_name} unavailable at {class_change.slot}",
            "day_constraint": f"{day_change.teacher_name} unavailable at {day_change.slot}",
        },
    }


def _small_policy_delta_request(assignments: list[SolverAssignment]) -> dict[str, Any]:
    first = assignments[0]
    modified_constraints = [
        Condition(
            id=920001,
            text="Policy delta teacher unavailable",
            condition_type="teacher_unavailable",
            teacher_name=first.teacher_name,
            slot=first.slot,
        )
    ]
    return {
        "repair_type": "repair_teacher",
        "repair_target": first.teacher_name,
        "modified_constraints": modified_constraints,
        "scenario": {"teacher_unavailable": f"{first.teacher_name} at {first.slot}"},
    }


def _schedule_assignments(schedule: dict[str, dict[str, ScheduleCell]]) -> list[SolverAssignment]:
    assignments: list[SolverAssignment] = []
    for slot, entries in schedule.items():
        for class_name, cell in entries.items():
            if isinstance(cell, ScheduleCell):
                subject = cell.subject
                teacher = cell.teacher
            elif isinstance(cell, dict):
                subject = str(cell.get("subject", ""))
                teacher = str(cell.get("teacher", ""))
            else:
                subject = str(getattr(cell, "subject", ""))
                teacher = str(getattr(cell, "teacher", ""))
            assignments.append(SolverAssignment(slot=slot, class_name=class_name, subject=subject, teacher_name=teacher))
    return assignments


def _first_different_day_assignment(assignments: list[SolverAssignment], slot: str) -> SolverAssignment | None:
    day = _day_of(slot)
    return next((assignment for assignment in assignments if _day_of(assignment.slot) != day), None)


def _first_same_day_assignment(assignments: list[SolverAssignment], slot: str) -> SolverAssignment | None:
    day = _day_of(slot)
    return next((assignment for assignment in assignments if _day_of(assignment.slot) == day), None)


def _day_of(slot: str) -> str:
    return slot.split("-", 1)[0] if "-" in slot else slot


def _run_progressive_relaxation_case(ortools_time_budget_seconds: float) -> dict[str, Any]:
    case = _hard_repair_case()
    repaired = repair_schedule(
        previous_schedule=case["previous"],
        classes=case["classes"],
        teachers=case["teachers"],
        subjects=case["subjects"],
        slots=case["slots"],
        repair_type="repair_class",
        class_id=1,
        modified_constraints=case["constraints"],
        time_budget=ortools_time_budget_seconds,
    )
    return _repair_policy_summary(repaired)


def _run_policy_comparison(ortools_time_budget_seconds: float) -> list[dict[str, Any]]:
    case = _hard_repair_case()
    results = []
    for policy in ["strict", "balanced", "flexible"]:
        repaired = repair_schedule(
            previous_schedule=case["previous"],
            classes=case["classes"],
            teachers=case["teachers"],
            subjects=case["subjects"],
            slots=case["slots"],
            repair_type="repair_class",
            class_id=1,
            modified_constraints=case["constraints"],
            time_budget=ortools_time_budget_seconds,
            repair_policy=policy,
        )
        results.append(_repair_policy_summary(repaired))
    return results


def _hard_repair_case() -> dict[str, Any]:
    classes = [Class(id=1, name="A", max_lessons_per_day=3), Class(id=2, name="B", max_lessons_per_day=3)]
    subjects = [Subject(name="Math", hours_per_week=1)]
    teachers = [Teacher(id=1, name="T1", subjects=["Math"], max_lessons_per_day=3)]
    slots = ["Mon-08:00", "Tue-08:00", "Wed-08:00"]
    previous = {
        "Mon-08:00": {"A": ScheduleCell(subject="Math", teacher="T1")},
        "Tue-08:00": {"B": ScheduleCell(subject="Math", teacher="T1")},
    }
    constraints = [
        Condition(id=910001, text="A cannot use Mon", condition_type="class_unavailable", class_name="A", slot="Mon-08:00"),
        Condition(id=910002, text="A cannot use Wed", condition_type="class_unavailable", class_name="A", slot="Wed-08:00"),
    ]
    return {
        "classes": classes,
        "subjects": subjects,
        "teachers": teachers,
        "slots": slots,
        "previous": previous,
        "constraints": constraints,
    }


def _repair_policy_summary(repaired) -> dict[str, Any]:
    return {
        "repair_policy": repaired.repair_policy,
        "success": repaired.success,
        "changed_sessions": repaired.changed_sessions,
        "stability_penalty": repaired.stability_penalty,
        "stability_score": repaired.stability_score,
        "hard_conflicts": repaired.hard_conflicts,
        "quality_score": repaired.quality_score,
        "time_ms": repaired.solver_result.metrics.generation_time_ms,
        "final_repair_strategy": repaired.final_repair_strategy,
        "max_changed_sessions": repaired.max_changed_sessions,
        "changed_sessions_over_limit": repaired.changed_sessions_over_limit,
        "policy_warning": repaired.diagnostics.get("policy_warning"),
        "pins_initial_count": repaired.diagnostics.get("pins_initial_count"),
        "pins_relaxed_count": repaired.diagnostics.get("pins_relaxed_count"),
        "relaxed_pin_reasons": repaired.diagnostics.get("relaxed_pin_reasons", []),
        "repair_attempts": repaired.diagnostics.get("repair_attempts", []),
    }


def _medium_policy_summary(repaired) -> dict[str, Any]:
    metrics = repaired.solver_result.metrics
    return {
        "repair_policy": repaired.repair_policy,
        "success": repaired.success,
        "changed_sessions": repaired.changed_sessions,
        "stability_score": repaired.stability_score,
        "stability_penalty": repaired.stability_penalty,
        "quality_score": repaired.quality_score,
        "gaps_count": int(metrics.gaps_class + metrics.gaps_teacher),
        "gaps_class": metrics.gaps_class,
        "gaps_teacher": metrics.gaps_teacher,
        "hard_conflicts": repaired.hard_conflicts,
        "final_repair_strategy": repaired.final_repair_strategy,
        "time_ms": metrics.generation_time_ms,
        "changed_sessions_over_limit": repaired.changed_sessions_over_limit,
        "max_changed_sessions": repaired.max_changed_sessions,
        "policy_warning": repaired.diagnostics.get("policy_warning"),
        "pins_relaxed_count": repaired.diagnostics.get("pins_relaxed_count"),
    }


def _required_sessions(input_data: ScheduleInput) -> int:
    return len(input_data.classes) * sum(max(0, subject.hours_per_week) for subject in input_data.subjects)


def print_solver_summary(report: dict[str, Any], output_path: str | Path) -> None:
    header = "dataset | engine | status | feasibility | time | sessions | hard_conflicts | score | gaps_c | gaps_t | overload | spread | compact | cp_status"
    print(header)
    print("-" * len(header))
    for result in report["results"]:
        dataset = result["dataset"]
        for engine in result["engines"]:
            status = "success" if engine["success"] else "failure"
            diagnostics = dict(engine.get("diagnostics") or {})
            quality = dict(diagnostics.get("quality") or {})
            pipeline = dict(diagnostics.get("pipeline") or {})
            print(
                f"{dataset} | {engine['engine']} | {status} | "
                f"{pipeline.get('feasibility_check', '-')} | "
                f"{engine['time_ms']}ms | "
                f"{engine['scheduled_sessions']}/{engine['required_sessions']} | "
                f"{engine['hard_conflicts']} | "
                f"{engine['quality_score']} | "
                f"{quality.get('gaps_class', '-')} | "
                f"{quality.get('gaps_teacher', '-')} | "
                f"{quality.get('overloaded_days', '-')} | "
                f"{quality.get('spread_penalty', '-')} | "
                f"{quality.get('compactness_penalty', '-')} | "
                f"{diagnostics.get('cp_status', '-')} | "
                f"vars={diagnostics.get('boolean_variables', '-')}"
            )
    print(f"report={Path(output_path)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare legacy and OR-Tools schedule solvers.")
    parser.add_argument("--dataset", choices=DATASET_ORDER, default="small", help="Dataset size to benchmark.")
    parser.add_argument("--all", action="store_true", help="Run all benchmark datasets.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to write the JSON report.")
    parser.add_argument(
        "--ortools-time-budget-seconds",
        type=float,
        default=10.0,
        help="CP-SAT time budget for the experimental OR-Tools solver.",
    )
    parser.add_argument(
        "--ortools-strategy",
        choices=["balanced", "compact", "teacher_friendly", "class_friendly"],
        default="balanced",
        help="Single OR-Tools strategy to benchmark.",
    )
    parser.add_argument(
        "--ortools-multi-strategy",
        action="store_true",
        help="Also run OR-Tools across all V2 strategies and keep the best result.",
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="Run a delta repair benchmark using an initial OR-Tools schedule and a small new constraint.",
    )
    parser.add_argument(
        "--delta-medium-policies",
        action="store_true",
        help="Run a realistic medium delta repair benchmark comparing strict, balanced, and flexible policies.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.delta:
        report = run_delta_benchmark(args.dataset, args.output, args.ortools_time_budget_seconds)
        print(json.dumps(report["delta"], indent=2))
        print(f"report={Path(args.output)}")
        return
    if args.delta_medium_policies:
        report = run_delta_medium_policy_benchmark(args.output, args.ortools_time_budget_seconds)
        print(json.dumps(report["policies"], indent=2))
        print(f"report={Path(args.output)}")
        return
    dataset_names = DATASET_ORDER if args.all else [args.dataset]
    report = run_solver_benchmarks(
        dataset_names,
        args.output,
        args.ortools_time_budget_seconds,
        args.ortools_strategy,
        args.ortools_multi_strategy,
    )
    print_solver_summary(report, args.output)


if __name__ == "__main__":
    main()
