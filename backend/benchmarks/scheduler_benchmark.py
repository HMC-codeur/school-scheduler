from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys
from time import perf_counter
import tracemalloc
from typing import Any

from backend.models.schemas import Class, Condition, Subject, Teacher
from backend.services.diagnostics import diagnose_schedule_generation
from backend.services.scheduler import SchedulerService
from backend.services.scheduler_v2 import FastValidScheduler
from backend.services.scoring import score_schedule


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


RESULTS_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_OUTPUT = RESULTS_DIR / "scheduler_benchmark_latest.json"
DATASET_ORDER = ["small", "pilot_school", "medium", "realistic_school", "hard_school", "large", "xlarge"]


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    classes_count: int
    teachers_count: int
    subjects_count: int
    slots_count: int
    subject_hours: int = 1
    default_max_lessons_per_day: int = 10


DATASETS = {
    "small": DatasetConfig("small", classes_count=10, teachers_count=20, subjects_count=10, slots_count=25),
    "pilot_school": DatasetConfig("pilot_school", classes_count=12, teachers_count=22, subjects_count=10, slots_count=30),
    "medium": DatasetConfig("medium", classes_count=50, teachers_count=90, subjects_count=20, slots_count=30),
    "realistic_school": DatasetConfig("realistic_school", classes_count=18, teachers_count=36, subjects_count=12, slots_count=35),
    "hard_school": DatasetConfig("hard_school", classes_count=24, teachers_count=42, subjects_count=14, slots_count=30),
    "large": DatasetConfig("large", classes_count=100, teachers_count=200, subjects_count=40, slots_count=45),
    "xlarge": DatasetConfig("xlarge", classes_count=250, teachers_count=500, subjects_count=60, slots_count=65),
}


DEFAULT_THRESHOLDS_MS = {
    "small": 60_000,
    "pilot_school": 120_000,
    "medium": 300_000,
    "large": 900_000,
    "xlarge": 1_800_000,
}


def build_dataset(config: DatasetConfig) -> dict[str, list]:
    if config.name == "pilot_school":
        return build_pilot_school_dataset()
    if config.name == "realistic_school":
        return build_realistic_school_dataset()
    if config.name == "hard_school":
        return build_hard_school_dataset()

    subjects = [
        Subject(name=f"Subject {index:02d}", hours_per_week=config.subject_hours)
        for index in range(1, config.subjects_count + 1)
    ]
    subject_names = [subject.name for subject in subjects]
    classes = [
        Class(id=index, name=f"Class {index:03d}", max_lessons_per_day=config.default_max_lessons_per_day)
        for index in range(1, config.classes_count + 1)
    ]
    slots = _build_slots(config.slots_count)

    rng = random.Random(20260513 + config.classes_count)
    teachers: list[Teacher] = []
    for index in range(1, config.teachers_count + 1):
        base_subject = subject_names[(index - 1) % len(subject_names)]
        extra_subjects = rng.sample(subject_names, k=min(2, len(subject_names)))
        teacher_subjects = list(dict.fromkeys([base_subject, *extra_subjects]))
        unavailable_candidates = [slot for slot in slots if slot.endswith("08:00") or slot.endswith("16:00")]
        unavailable = sorted(rng.sample(unavailable_candidates, k=min(2, len(unavailable_candidates))))
        teachers.append(
            Teacher(
                id=index,
                name=f"Teacher {index:03d}",
                subjects=teacher_subjects,
                unavailable_slots=unavailable,
                max_lessons_per_day=config.default_max_lessons_per_day,
            )
        )

    return {"classes": classes, "teachers": teachers, "subjects": subjects, "slots": slots, "conditions": []}


def build_pilot_school_dataset() -> dict[str, list]:
    subjects = [
        Subject(name="Mathématiques", hours_per_week=3),
        Subject(name="Français", hours_per_week=3),
        Subject(name="Anglais", hours_per_week=2),
        Subject(name="Sciences", hours_per_week=2),
        Subject(name="Histoire", hours_per_week=2),
        Subject(name="Géographie", hours_per_week=1),
        Subject(name="Vie civique", hours_per_week=1),
        Subject(name="EPS", hours_per_week=2),
        Subject(name="Informatique", hours_per_week=1),
        Subject(name="Arts", hours_per_week=1),
    ]
    class_names = [f"{level}{group}" for level in ["6e", "5e", "4e", "3e"] for group in ["A", "B", "C"]]
    classes = [
        Class(id=index, name=name, max_lessons_per_day=6)
        for index, name in enumerate(class_names, start=1)
    ]
    slots = [
        f"{day}-{hour}"
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]
        for hour in ["08:00", "09:00", "10:00", "11:00", "13:00", "14:00"]
    ]
    teacher_specs = [
        ("Mme Laurent", ["Mathématiques"], ["Wed-13:00", "Fri-14:00"], 5),
        ("M. Benhamou", ["Mathématiques", "Informatique"], ["Mon-08:00", "Thu-14:00"], 5),
        ("Mme Cohen", ["Mathématiques"], ["Tue-13:00", "Fri-08:00"], 4),
        ("M. Haddad", ["Mathématiques", "Sciences"], ["Wed-08:00", "Thu-13:00"], 4),
        ("Mme Durand", ["Français"], ["Mon-14:00", "Thu-08:00"], 5),
        ("M. Petit", ["Français", "Histoire"], ["Tue-14:00", "Fri-13:00"], 5),
        ("Mme Amar", ["Français"], ["Wed-13:00", "Fri-14:00"], 4),
        ("Mme Levy", ["Anglais"], ["Mon-08:00", "Wed-14:00"], 4),
        ("M. Rosen", ["Anglais"], ["Tue-08:00", "Thu-13:00", "Fri-14:00"], 3),
        ("Mme Martin", ["Anglais", "Vie civique"], ["Mon-13:00", "Wed-08:00"], 4),
        ("M. Garcia", ["Sciences"], ["Tue-13:00", "Fri-08:00"], 5),
        ("Mme Nguyen", ["Sciences", "Informatique"], ["Mon-14:00", "Thu-08:00"], 4),
        ("M. Morel", ["Sciences"], ["Wed-14:00", "Fri-13:00"], 3),
        ("Mme Barak", ["Histoire", "Géographie"], ["Mon-08:00", "Thu-14:00"], 5),
        ("M. Elbaz", ["Histoire", "Vie civique"], ["Tue-14:00", "Wed-13:00"], 4),
        ("Mme Simon", ["Géographie", "Histoire"], ["Wed-08:00", "Fri-14:00"], 3),
        ("M. Dahan", ["EPS"], ["Mon-13:00", "Tue-13:00"], 5),
        ("Mme Fitoussi", ["EPS"], ["Thu-08:00", "Fri-08:00"], 4),
        ("M. Vidal", ["Informatique", "Mathématiques"], ["Tue-08:00", "Fri-13:00"], 3),
        ("Mme Tessier", ["Arts"], ["Mon-08:00", "Wed-08:00", "Fri-08:00"], 3),
        ("M. Peretz", ["Arts", "Vie civique"], ["Tue-13:00", "Thu-13:00"], 3),
        ("Mme Saada", ["Vie civique", "Français"], ["Mon-14:00", "Wed-14:00"], 3),
    ]
    teachers = [
        Teacher(
            id=index,
            name=name,
            subjects=teacher_subjects,
            unavailable_slots=unavailable,
            max_lessons_per_day=max_daily,
        )
        for index, (name, teacher_subjects, unavailable, max_daily) in enumerate(teacher_specs, start=1)
    ]
    conditions = [
        Condition(id=1, text="Mathématiques le matin si possible", condition_type="subject_morning_preference", subject_name="Mathématiques"),
        Condition(id=2, text="Français le matin si possible", condition_type="subject_morning_preference", subject_name="Français"),
        Condition(id=3, text="Sciences le matin si possible", condition_type="subject_morning_preference", subject_name="Sciences"),
        Condition(id=4, text="Mme Cohen temps partiel mercredi après-midi", condition_type="teacher_unavailable", teacher_name="Mme Cohen", slot="Wed-14:00"),
        Condition(id=5, text="M. Rosen temps partiel vendredi après-midi", condition_type="teacher_unavailable", teacher_name="M. Rosen", slot="Fri-13:00"),
        Condition(id=6, text="6eA réunion pédagogique lundi 08h", condition_type="class_unavailable", class_name="6eA", slot="Mon-08:00"),
        Condition(id=7, text="5eB sortie sportive jeudi 14h", condition_type="class_unavailable", class_name="5eB", slot="Thu-14:00"),
        Condition(id=8, text="4eC atelier externe mardi 13h", condition_type="class_unavailable", class_name="4eC", slot="Tue-13:00"),
        Condition(id=9, text="Éviter longues séries pour les 3e", condition_type="avoid_long_sequence", class_name="3eA"),
        Condition(id=10, text="Éviter répétition de Mathématiques en 6eA", condition_type="avoid_subject_repeat", class_name="6eA", subject_name="Mathématiques"),
    ]
    return {"classes": classes, "teachers": teachers, "subjects": subjects, "slots": slots, "conditions": conditions}


def build_realistic_school_dataset() -> dict[str, list]:
    subjects = [
        Subject(name="Math", hours_per_week=4),
        Subject(name="English", hours_per_week=3),
        Subject(name="Science", hours_per_week=3),
        Subject(name="History", hours_per_week=2),
        Subject(name="Geography", hours_per_week=2),
        Subject(name="Hebrew", hours_per_week=3),
        Subject(name="Sports", hours_per_week=2),
        Subject(name="Art", hours_per_week=1),
        Subject(name="Music", hours_per_week=1),
        Subject(name="Computer Science", hours_per_week=2),
        Subject(name="Civics", hours_per_week=1),
        Subject(name="Literature", hours_per_week=2),
    ]
    subject_names = [subject.name for subject in subjects]
    classes = [
        Class(id=index, name=f"Grade {7 + ((index - 1) // 3)}{chr(65 + ((index - 1) % 3))}", max_lessons_per_day=7)
        for index in range(1, 19)
    ]
    slots = _build_slots(35)
    rng = random.Random(20260514)
    teachers: list[Teacher] = []
    for index in range(1, 37):
        primary = subject_names[(index - 1) % len(subject_names)]
        extra = rng.sample(subject_names, k=2)
        unavailable = sorted(rng.sample([slot for slot in slots if slot.endswith("08:00") or slot.endswith("14:00")], k=2))
        teachers.append(
            Teacher(
                id=index,
                name=f"Teacher R{index:02d}",
                subjects=list(dict.fromkeys([primary, *extra])),
                unavailable_slots=unavailable,
                max_lessons_per_day=6,
            )
        )
    conditions: list[Condition] = [
        Condition(id=1, text="Math morning", condition_type="subject_morning_preference", subject_name="Math"),
        Condition(id=2, text="Science morning", condition_type="subject_morning_preference", subject_name="Science"),
        Condition(id=3, text="Teacher R01 prefers morning", condition_type="teacher_prefer_morning", teacher_name="Teacher R01"),
    ]
    for index, class_obj in enumerate(classes[:6], start=4):
        conditions.append(
            Condition(
                id=index,
                text=f"{class_obj.name} unavailable first slot",
                condition_type="class_unavailable",
                class_name=class_obj.name,
                slot=slots[index % len(slots)],
            )
        )
    return {"classes": classes, "teachers": teachers, "subjects": subjects, "slots": slots, "conditions": conditions}


def build_hard_school_dataset() -> dict[str, list]:
    classes = [
        Class(id=index, name=f"Hard Class {index:02d}", max_lessons_per_day=5)
        for index in range(1, 13)
    ]
    subjects = [
        Subject(name="Math", hours_per_week=4),
        Subject(name="English", hours_per_week=3),
        Subject(name="Science", hours_per_week=3),
        Subject(name="History", hours_per_week=2),
        Subject(name="Geography", hours_per_week=2),
        Subject(name="Hebrew", hours_per_week=3),
        Subject(name="Sports", hours_per_week=2),
        Subject(name="Computer Science", hours_per_week=2),
    ]
    slots = _build_slots(25)
    teachers: list[Teacher] = []
    rng = random.Random(20260515)
    subject_names = [subject.name for subject in subjects]
    for index in range(1, 25):
        primary = subject_names[(index - 1) % len(subject_names)]
        extra = rng.sample(subject_names, k=1)
        unavailable_pool = [slot for slot in slots if slot.endswith("08:00") or slot.endswith("13:00")]
        unavailable = sorted(rng.sample(unavailable_pool, k=min(2, len(unavailable_pool))))
        teachers.append(
            Teacher(
                id=index,
                name=f"Teacher H{index:02d}",
                subjects=list(dict.fromkeys([primary, *extra])),
                unavailable_slots=unavailable,
                max_lessons_per_day=5,
            )
        )
    conditions: list[Condition] = [
        Condition(id=1, text="Math morning", condition_type="subject_morning_preference", subject_name="Math"),
        Condition(id=2, text="English morning", condition_type="subject_morning_preference", subject_name="English"),
    ]
    for index, class_obj in enumerate(classes[:10], start=3):
        conditions.append(
            Condition(
                id=index,
                text=f"{class_obj.name} blocked",
                condition_type="class_unavailable",
                class_name=class_obj.name,
                slot=slots[(index * 2) % len(slots)],
            )
        )
    return {"classes": classes, "teachers": teachers, "subjects": subjects, "slots": slots, "conditions": conditions}


def _build_slots(count: int) -> list[str]:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    times = [
        "08:00",
        "09:00",
        "10:00",
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
        "16:00",
        "17:00",
        "18:00",
        "19:00",
        "20:00",
    ]
    if count <= 0:
        return []
    daily_base = count // len(days)
    extra_days = count % len(days)
    slots: list[str] = []
    for index, day in enumerate(days):
        daily_count = min(len(times), daily_base + (1 if index < extra_days else 0))
        slots.extend(f"{day}-{time}" for time in times[:daily_count])
    return slots[:count]


def benchmark_dataset(
    name: str,
    total_threshold_ms: int | None = None,
    include_diagnostics: bool = True,
    track_memory: bool = False,
    compare_v2: bool = False,
    v2_time_budget_ms: int = 5_000,
    v2_quality_time_budget_ms: int = 1_000,
) -> dict[str, Any]:
    if name not in DATASETS:
        raise ValueError(f"Unknown benchmark dataset: {name}")

    benchmark_started = perf_counter()
    config = DATASETS[name]
    dataset_started = perf_counter()
    dataset = build_dataset(config)
    dataset_build_time_ms = _elapsed_ms(dataset_started)
    classes = dataset["classes"]
    teachers = dataset["teachers"]
    subjects = dataset["subjects"]
    slots = dataset["slots"]
    conditions = dataset["conditions"]

    if track_memory:
        tracemalloc.start()

    generation_started = perf_counter()
    generation = SchedulerService.generate(classes, teachers, subjects, slots, conditions)
    generation_time_ms = _elapsed_ms(generation_started)

    options_started = perf_counter()
    options = SchedulerService.generate_options(classes, teachers, subjects, slots, conditions)
    options_time_ms = _elapsed_ms(options_started)

    scoring_started = perf_counter()
    for option in options:
        score_schedule(option.get("schedule", {}), classes, teachers, subjects, slots, conditions)
    scoring_time_ms = _elapsed_ms(scoring_started)

    diagnostics_time_ms = None
    diagnostic_can_generate = None
    if include_diagnostics:
        diagnostics_started = perf_counter()
        diagnostic = diagnose_schedule_generation(classes, teachers, subjects, slots, conditions)
        diagnostics_time_ms = _elapsed_ms(diagnostics_started)
        diagnostic_can_generate = bool(diagnostic.get("can_generate"))

    v2_phase_a = None
    v2_phase_b = None
    if compare_v2:
        v2_started = perf_counter()
        v2_result = FastValidScheduler.generate(
            classes,
            teachers,
            subjects,
            slots,
            conditions,
            time_budget_ms=v2_time_budget_ms,
            fallback_to_current=False,
        )
        v2_time_ms = _elapsed_ms(v2_started)
        v2_score = score_schedule(v2_result.schedule, classes, teachers, subjects, slots, conditions)
        v2_required = int(v2_result.required_sessions or 0)
        v2_scheduled = int(v2_result.scheduled_sessions or 0)
        v2_phase_a = {
            "success": v2_result.success,
            "message": v2_result.message,
            "time_ms": v2_time_ms,
            "required_sessions": v2_result.required_sessions,
            "scheduled_sessions": v2_result.scheduled_sessions,
            "placement_rate": round((v2_scheduled / max(1, v2_required)) * 100, 2),
            "quality_score": int(v2_score.get("quality_score", 0)),
            "metrics": dict(v2_score.get("metrics") or {}),
            "fallback_used": False,
        }
        if v2_result.success:
            v2_optimized = FastValidScheduler.optimize_quality(
                v2_result.schedule,
                classes,
                teachers,
                subjects,
                slots,
                conditions,
                time_budget_ms=v2_quality_time_budget_ms,
            )
            v2_phase_b_score = score_schedule(v2_optimized.schedule, classes, teachers, subjects, slots, conditions)
            phase_b_scheduled = sum(len(entries) for entries in v2_optimized.schedule.values())
            v2_phase_b = {
                "success": True,
                "time_ms": v2_optimized.time_ms,
                "moves_evaluated": v2_optimized.moves_evaluated,
                "moves_accepted": v2_optimized.moves_accepted,
                "improved": v2_optimized.improved,
                "penalty_before": v2_optimized.penalty_before,
                "penalty_after": v2_optimized.penalty_after,
                "score_before": v2_optimized.score_before,
                "score_after": v2_optimized.score_after,
                "quality_score": int(v2_phase_b_score.get("quality_score", 0)),
                "metrics": dict(v2_phase_b_score.get("metrics") or {}),
                "scheduled_sessions": phase_b_scheduled,
                "required_sessions": v2_result.required_sessions,
            }

    total_time_ms = _elapsed_ms(benchmark_started)
    if track_memory:
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        current_memory, peak_memory = 0, 0

    option_scores = [int(option.get("quality_score", 0)) for option in options]
    average_score = round(sum(option_scores) / len(option_scores), 2) if option_scores else None
    penalty_summary = summarize_penalties(options)
    penalty_counts = summarize_penalty_counts(penalty_summary)
    threshold_ms = total_threshold_ms if total_threshold_ms is not None else DEFAULT_THRESHOLDS_MS[name]
    threshold_exceeded = total_time_ms > threshold_ms
    placement_rate = round((int(generation.scheduled_sessions or 0) / int(generation.required_sessions or 1)) * 100, 2)

    return {
        "dataset": name,
        "config": {
            "classes": config.classes_count,
            "teachers": config.teachers_count,
            "subjects": config.subjects_count,
            "slots": config.slots_count,
        },
        "success": generation.success,
        "message": generation.message,
        "total_time_ms": total_time_ms,
        "dataset_build_time_ms": dataset_build_time_ms,
        "generation_time_ms": generation_time_ms,
        "options_time_ms": options_time_ms,
        "scoring_time_ms": scoring_time_ms,
        "diagnostics_time_ms": diagnostics_time_ms,
        "diagnostic_can_generate": diagnostic_can_generate,
        "phase_times_ms": {
            "dataset_build": dataset_build_time_ms,
            "single_generation": generation_time_ms,
            "multiple_options": options_time_ms,
            "external_scoring": scoring_time_ms,
            "diagnostics": diagnostics_time_ms,
        },
        "required_sessions": generation.required_sessions,
        "scheduled_sessions": generation.scheduled_sessions,
        "placement_rate": placement_rate,
        "conflicts_count": generation.conflicts_count,
        "options_generated": len(options),
        "average_score": average_score,
        "score_min": min(option_scores) if option_scores else None,
        "score_max": max(option_scores) if option_scores else None,
        "score_samples": option_scores,
        "penalty_summary": penalty_summary,
        "penalty_counts": penalty_counts,
        "class_gaps_count": penalty_counts["class_gaps"],
        "teacher_gaps_count": penalty_counts["teacher_gaps"],
        "long_sequences_count": penalty_counts["long_sequences"],
        "top_penalty_categories": penalty_summary[:5],
        "memory_current_kb": round(current_memory / 1024, 2),
        "memory_peak_kb": round(peak_memory / 1024, 2),
        "memory_tracked": track_memory,
        "memory_note": "disabled by default because tracemalloc significantly distorts scheduler timings",
        "threshold_ms": threshold_ms,
        "threshold_exceeded": threshold_exceeded,
        "v2_phase_a": v2_phase_a,
        "v2_phase_b": v2_phase_b,
    }


def summarize_penalties(options: list[dict]) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for option in options:
        for item in option.get("score_breakdown", []) or []:
            rule = str(item.get("rule", "unknown"))
            points = int(item.get("points", 0))
            raw_points = int(item.get("raw_points", points))
            count = int(item.get("count", 1))
            if rule not in summary:
                summary[rule] = {
                    "rule": rule,
                    "points": 0,
                    "raw_points": 0,
                    "items": 0,
                    "count": 0,
                    "capped_items": 0,
                }
            summary[rule]["points"] += points
            summary[rule]["raw_points"] += raw_points
            summary[rule]["items"] += 1
            summary[rule]["count"] += count
            if item.get("capped"):
                summary[rule]["capped_items"] += 1
    return sorted(summary.values(), key=lambda item: (int(item["points"]), item["rule"]))


def summarize_penalty_counts(penalty_summary: list[dict[str, Any]]) -> dict[str, int]:
    by_rule = {str(item.get("rule")): int(item.get("count", 0)) for item in penalty_summary}
    return {
        "class_gaps": by_rule.get("class_gap", 0),
        "teacher_gaps": by_rule.get("teacher_gap", 0),
        "long_sequences": (
            by_rule.get("class_long_sequence", 0)
            + by_rule.get("teacher_long_sequence", 0)
            + by_rule.get("avoid_long_sequence", 0)
        ),
    }


def run_benchmarks(
    dataset_names: list[str],
    output_path: str | Path = DEFAULT_OUTPUT,
    enforce_thresholds: bool = False,
    threshold_overrides: dict[str, int] | None = None,
    include_diagnostics: bool = True,
    track_memory: bool = False,
    compare_v2: bool = False,
    v2_time_budget_ms: int = 5_000,
    v2_quality_time_budget_ms: int = 1_000,
) -> dict[str, Any]:
    threshold_overrides = threshold_overrides or {}
    output = Path(output_path)
    previous_report = _read_previous_report(output)
    results = [
        benchmark_dataset(
            name,
            total_threshold_ms=threshold_overrides.get(name),
            include_diagnostics=include_diagnostics,
            track_memory=track_memory,
            compare_v2=compare_v2,
            v2_time_budget_ms=v2_time_budget_ms,
            v2_quality_time_budget_ms=v2_quality_time_budget_ms,
        )
        for name in dataset_names
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds_enforced": enforce_thresholds,
        "diagnostics_included": include_diagnostics,
        "memory_tracked": track_memory,
        "v2_compared": compare_v2,
        "v2_time_budget_ms": v2_time_budget_ms if compare_v2 else None,
        "v2_quality_time_budget_ms": v2_quality_time_budget_ms if compare_v2 else None,
        "results": results,
        "comparison": compare_with_previous(results, previous_report),
        "analysis": analyze_benchmark_results(results),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if enforce_thresholds:
        exceeded = [result for result in results if result["threshold_exceeded"]]
        if exceeded:
            names = ", ".join(result["dataset"] for result in exceeded)
            raise SystemExit(f"Benchmark thresholds exceeded for: {names}")

    return report


def _read_previous_report(output_path: Path) -> dict[str, Any] | None:
    if not output_path.exists():
        return None
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compare_with_previous(results: list[dict[str, Any]], previous_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not previous_report:
        return []
    previous_by_dataset = {
        str(result.get("dataset")): result
        for result in previous_report.get("results", [])
        if isinstance(result, dict) and result.get("dataset")
    }
    comparisons: list[dict[str, Any]] = []
    for result in results:
        dataset = str(result.get("dataset"))
        previous = previous_by_dataset.get(dataset)
        if not previous:
            continue

        current_score = result.get("average_score")
        previous_score = previous.get("average_score")
        current_scheduled = int(result.get("scheduled_sessions") or 0)
        previous_scheduled = int(previous.get("scheduled_sessions") or 0)
        current_conflicts = int(result.get("conflicts_count") or 0)
        previous_conflicts = int(previous.get("conflicts_count") or 0)

        score_delta = None
        if current_score is not None and previous_score is not None:
            score_delta = round(float(current_score) - float(previous_score), 2)

        comparisons.append(
            {
                "dataset": dataset,
                "average_score_before": previous_score,
                "average_score_after": current_score,
                "average_score_delta": score_delta,
                "scheduled_sessions_before": previous_scheduled,
                "scheduled_sessions_after": current_scheduled,
                "scheduled_sessions_delta": current_scheduled - previous_scheduled,
                "conflicts_before": previous_conflicts,
                "conflicts_after": current_conflicts,
                "conflicts_delta": current_conflicts - previous_conflicts,
            }
        )
    return comparisons


def analyze_benchmark_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[str] = []
    recommendations: list[str] = []
    phase_names = ["dataset_build", "single_generation", "multiple_options", "external_scoring", "diagnostics"]

    for result in results:
        dataset = result["dataset"]
        phases = result.get("phase_times_ms", {})
        numeric_phases = {
            name: int(phases.get(name) or 0)
            for name in phase_names
            if phases.get(name) is not None
        }
        if numeric_phases:
            dominant_phase, dominant_ms = max(numeric_phases.items(), key=lambda item: item[1])
            findings.append(f"{dataset}: phase dominante = {dominant_phase} ({dominant_ms}ms).")

        generation_ms = int(result.get("generation_time_ms") or 0)
        options_ms = int(result.get("options_time_ms") or 0)
        diagnostics_ms = int(result.get("diagnostics_time_ms") or 0)
        if generation_ms and options_ms >= generation_ms * 2:
            findings.append(
                f"{dataset}: les options multiples coûtent {round(options_ms / generation_ms, 2)}x une génération simple."
            )
        if generation_ms and diagnostics_ms >= int(generation_ms * 0.8):
            findings.append(
                f"{dataset}: le diagnostic est coûteux car il relance une génération de faisabilité."
            )
        if float(result.get("placement_rate") or 0) < 100:
            findings.append(f"{dataset}: placement incomplet ({result.get('placement_rate')}%).")
        v2_phase_a = result.get("v2_phase_a")
        if isinstance(v2_phase_a, dict):
            if not v2_phase_a.get("success"):
                findings.append(f"{dataset}: V2 Phase A n'a pas trouvé de planning valide ({v2_phase_a.get('message')}).")
            else:
                findings.append(
                    f"{dataset}: V2 Phase A hard-only termine en {v2_phase_a.get('time_ms')}ms "
                    f"avec score externe {v2_phase_a.get('quality_score')}."
                )
        v2_phase_b = result.get("v2_phase_b")
        if isinstance(v2_phase_b, dict):
            findings.append(
                f"{dataset}: V2 Phase B termine en {v2_phase_b.get('time_ms')}ms, "
                f"score {v2_phase_b.get('score_before')} -> {v2_phase_b.get('score_after')}, "
                f"pénalité {v2_phase_b.get('penalty_before')} -> {v2_phase_b.get('penalty_after')}."
            )

    recommendations.extend(
        [
            "Pré-calculer davantage les compatibilités professeur/matière/créneau avant le backtracking.",
            "Éviter les scans complets de candidats à chaque session; maintenir des index de disponibilités par sujet, jour et créneau.",
            "Remplacer à terme le diagnostic de faisabilité complet par des checks structurels puis une génération optionnelle explicite.",
            "Profiler le scoring séparément quand les plannings dépassent plusieurs dizaines de milliers de sessions.",
            "Étudier une parallélisation future des seeds d'options, car les options sont indépendantes.",
        ]
    )
    return {"findings": findings, "recommendations": recommendations}


def print_summary(report: dict[str, Any], output_path: str | Path) -> None:
    comparisons = {item["dataset"]: item for item in report.get("comparison", [])}
    header = (
        "dataset | status | total | build | gen1 | options | scoring | diag | "
        "sessions | place% | score | conflicts | class_gaps | teacher_gaps | long_seq"
    )
    print(header)
    print("-" * len(header))
    for result in report["results"]:
        status = "success" if result["success"] else "failure"
        placed = result.get("scheduled_sessions") or 0
        required = result.get("required_sessions") or 0
        score = result.get("average_score")
        threshold_note = " threshold-exceeded" if result.get("threshold_exceeded") else ""
        comparison = comparisons.get(result["dataset"], {})
        score_delta = comparison.get("average_score_delta")
        delta_note = f" | score_delta={score_delta:+.2f}" if isinstance(score_delta, (int, float)) else ""
        print(
            f"{result['dataset']} | {status}{threshold_note} | "
            f"{result['total_time_ms']}ms | "
            f"{result.get('dataset_build_time_ms', 0)}ms | "
            f"{result['generation_time_ms']}ms | "
            f"{result['options_time_ms']}ms | "
            f"{result['scoring_time_ms']}ms | "
            f"{result.get('diagnostics_time_ms') if result.get('diagnostics_time_ms') is not None else '-'}ms | "
            f"{placed}/{required} | "
            f"{result.get('placement_rate', '-')} | "
            f"{score if score is not None else '-'} | "
            f"{result.get('conflicts_count', '-')} | "
            f"{result.get('class_gaps_count', '-')} | "
            f"{result.get('teacher_gaps_count', '-')} | "
            f"{result.get('long_sequences_count', '-')}"
            f"{delta_note}"
        )
        v2_phase_a = result.get("v2_phase_a")
        if isinstance(v2_phase_a, dict):
            v2_status = "success" if v2_phase_a.get("success") else "failure"
            print(
                f"  v2_phase_a | {v2_status} | "
                f"{v2_phase_a.get('time_ms')}ms | "
                f"{v2_phase_a.get('scheduled_sessions')}/{v2_phase_a.get('required_sessions')} | "
                f"place%={v2_phase_a.get('placement_rate')} | "
                f"score={v2_phase_a.get('quality_score')} | "
                f"metrics={v2_phase_a.get('metrics')}"
            )
        v2_phase_b = result.get("v2_phase_b")
        if isinstance(v2_phase_b, dict):
            print(
                f"  v2_phase_b | success | "
                f"{v2_phase_b.get('time_ms')}ms | "
                f"{v2_phase_b.get('scheduled_sessions')}/{v2_phase_b.get('required_sessions')} | "
                f"score={v2_phase_b.get('score_before')}->{v2_phase_b.get('score_after')} | "
                f"penalty={v2_phase_b.get('penalty_before')}->{v2_phase_b.get('penalty_after')} | "
                f"moves={v2_phase_b.get('moves_accepted')}/{v2_phase_b.get('moves_evaluated')} | "
                f"metrics={v2_phase_b.get('metrics')}"
            )
    analysis = report.get("analysis", {})
    if analysis.get("findings"):
        print("\nFindings:")
        for finding in analysis["findings"]:
            print(f"- {finding}")
    if analysis.get("recommendations"):
        print("\nRecommendations:")
        for recommendation in analysis["recommendations"]:
            print(f"- {recommendation}")
    print(f"report={Path(output_path)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local scheduler benchmarks.")
    parser.add_argument("--dataset", choices=DATASET_ORDER, default="small", help="Dataset size to benchmark.")
    parser.add_argument("--all", action="store_true", help="Run all benchmark datasets.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to write the JSON report.")
    parser.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Skip the /schedule/diagnose-equivalent phase. By default it is measured separately.",
    )
    parser.add_argument(
        "--track-memory",
        action="store_true",
        help="Enable tracemalloc. Disabled by default because it significantly slows scheduler timings.",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit with an error if a dataset exceeds its configured threshold.",
    )
    parser.add_argument(
        "--compare-v2",
        action="store_true",
        help="Also run the experimental hard-constraints-only V2 Phase A builder.",
    )
    parser.add_argument(
        "--v2-time-budget-ms",
        type=int,
        default=5_000,
        help="Time budget for the experimental V2 Phase A builder when --compare-v2 is enabled.",
    )
    parser.add_argument(
        "--v2-quality-time-budget-ms",
        type=int,
        default=1_000,
        help="Time budget for the experimental V2 Phase B optimizer when --compare-v2 is enabled.",
    )
    parser.add_argument("--small-threshold-ms", type=int, help="Override small total-time threshold.")
    parser.add_argument("--pilot-school-threshold-ms", type=int, help="Override pilot_school total-time threshold.")
    parser.add_argument("--medium-threshold-ms", type=int, help="Override medium total-time threshold.")
    parser.add_argument("--large-threshold-ms", type=int, help="Override large total-time threshold.")
    parser.add_argument("--xlarge-threshold-ms", type=int, help="Override xlarge total-time threshold.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset_names = DATASET_ORDER if args.all else [args.dataset]
    thresholds = {
        name: value
        for name, value in {
            "small": args.small_threshold_ms,
            "pilot_school": args.pilot_school_threshold_ms,
            "medium": args.medium_threshold_ms,
            "large": args.large_threshold_ms,
            "xlarge": args.xlarge_threshold_ms,
        }.items()
        if value is not None
    }
    report = run_benchmarks(
        dataset_names=dataset_names,
        output_path=args.output,
        enforce_thresholds=args.enforce_thresholds,
        threshold_overrides=thresholds,
        include_diagnostics=not args.skip_diagnostics,
        track_memory=args.track_memory,
        compare_v2=args.compare_v2,
        v2_time_budget_ms=args.v2_time_budget_ms,
        v2_quality_time_budget_ms=args.v2_quality_time_budget_ms,
    )
    print_summary(report, args.output)


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


if __name__ == "__main__":
    main()
