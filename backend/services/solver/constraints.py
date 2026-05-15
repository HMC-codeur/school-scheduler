from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from backend.models.schemas import ScheduleCell, Teacher
from backend.services.scoring import analyze_schedule
from backend.services.solver.models import ScheduleInput
from backend.services.solver.stability import evaluate_stability


STRATEGY_BALANCED = "balanced"
STRATEGY_COMPACT = "compact"
STRATEGY_TEACHER_FRIENDLY = "teacher_friendly"
STRATEGY_CLASS_FRIENDLY = "class_friendly"
SUPPORTED_STRATEGIES = {
    STRATEGY_BALANCED,
    STRATEGY_COMPACT,
    STRATEGY_TEACHER_FRIENDLY,
    STRATEGY_CLASS_FRIENDLY,
}


@dataclass(frozen=True)
class StrategyWeights:
    gaps_class: int = 12
    gaps_teacher: int = 5
    overloaded_class_day: int = 4
    overloaded_teacher_day: int = 3
    spread: int = 5
    class_week_balance: int = 2
    long_series_class: int = 8
    long_series_teacher: int = 4
    compactness: int = 1
    morning_preference: int = 3
    teacher_load_preassignment: int = 1


@dataclass(frozen=True)
class QualityObjective:
    terms: list[tuple[int, object]]


def strategy_weights(strategy: str) -> StrategyWeights:
    if strategy == STRATEGY_COMPACT:
        return StrategyWeights(
            gaps_class=18,
            gaps_teacher=9,
            compactness=3,
            long_series_class=10,
            long_series_teacher=6,
            class_week_balance=1,
        )
    if strategy == STRATEGY_TEACHER_FRIENDLY:
        return StrategyWeights(
            gaps_class=8,
            gaps_teacher=14,
            overloaded_class_day=3,
            overloaded_teacher_day=8,
            spread=4,
            compactness=1,
            teacher_load_preassignment=3,
        )
    if strategy == STRATEGY_CLASS_FRIENDLY:
        return StrategyWeights(
            gaps_class=16,
            gaps_teacher=4,
            overloaded_class_day=7,
            overloaded_teacher_day=2,
            spread=8,
            compactness=2,
            long_series_class=12,
        )
    return StrategyWeights()


def add_soft_quality_objective(
    model: Any,
    input_data: ScheduleInput,
    context: Any,
    by_class_slot: dict[tuple[int, str], list[object]],
    by_teacher_slot: dict[tuple[int, str], list[object]],
    by_class_day: dict[tuple[int, str], list[object]],
    by_teacher_day: dict[tuple[int, str], list[object]],
    by_class_subject_day: dict[tuple[int, str, str], list[object]],
    by_subject_slot: dict[tuple[str, str], list[object]],
    teacher_expected_loads: dict[int, int],
    weights: StrategyWeights,
) -> QualityObjective:
    terms: list[tuple[int, object]] = []
    class_used = _build_usage_bools(model, "class_slot", by_class_slot)
    teacher_used = _build_usage_bools(model, "teacher_slot", by_teacher_slot)
    class_weekly_hours = sum(max(0, subject.hours_per_week) for subject in input_data.subjects)
    day_count = max(1, len(context.days))
    ideal_class_daily_load = max(1, (class_weekly_hours + day_count - 1) // day_count)

    _add_gap_penalties(model, terms, class_used, context.slots_by_day, weights.gaps_class, "class_gap")
    _add_gap_penalties(model, terms, teacher_used, context.slots_by_day, weights.gaps_teacher, "teacher_gap")
    _add_long_sequence_penalties(model, terms, class_used, context.slots_by_day, weights.long_series_class, "class_long")
    _add_long_sequence_penalties(model, terms, teacher_used, context.slots_by_day, weights.long_series_teacher, "teacher_long")

    for class_obj in input_data.classes:
        for day in context.days:
            load = sum(by_class_day.get((class_obj.id, day), []))
            overload = model.NewIntVar(0, len(context.slots_by_day[day]), f"class_overload_{class_obj.id}_{day}")
            model.Add(overload >= load - ideal_class_daily_load)
            terms.append((weights.overloaded_class_day, overload))

            delta = model.NewIntVar(-len(context.slots_by_day[day]), len(context.slots_by_day[day]), f"class_spread_delta_{class_obj.id}_{day}")
            deviation = model.NewIntVar(0, len(context.slots_by_day[day]), f"class_spread_dev_{class_obj.id}_{day}")
            model.Add(delta == load - ideal_class_daily_load)
            model.AddAbsEquality(deviation, delta)
            terms.append((weights.class_week_balance, deviation))

    for teacher in input_data.teachers:
        expected_load = teacher_expected_loads.get(teacher.id, 0)
        if expected_load <= 0:
            continue
        ideal_teacher_daily_load = max(1, (expected_load + day_count - 1) // day_count)
        for day in context.days:
            load = sum(by_teacher_day.get((teacher.id, day), []))
            overload = model.NewIntVar(0, len(context.slots_by_day[day]), f"teacher_overload_{teacher.id}_{day}")
            model.Add(overload >= load - ideal_teacher_daily_load)
            terms.append((weights.overloaded_teacher_day, overload))

    for class_obj in input_data.classes:
        for subject in input_data.subjects:
            ideal_subject_daily = max(1, (max(0, subject.hours_per_week) + day_count - 1) // day_count)
            for day in context.days:
                count = sum(by_class_subject_day.get((class_obj.id, subject.name, day), []))
                repeated = model.NewIntVar(0, max(0, subject.hours_per_week), f"subject_spread_{class_obj.id}_{_safe_name(subject.name)}_{day}")
                model.Add(repeated >= count - ideal_subject_daily)
                terms.append((weights.spread, repeated))

    morning_subjects, morning_teachers = _morning_preferences(input_data)
    for (class_id, slot), used in class_used.items():
        position = context.slot_day_position.get(slot, 0)
        terms.append((weights.compactness, used * position))
    for subject_name in morning_subjects:
        for (_subject_name, slot), vars_for_subject_slot in by_subject_slot.items():
            if _subject_name != subject_name or _slot_is_morning(slot):
                continue
            for var in vars_for_subject_slot:
                terms.append((weights.morning_preference, var))
    for teacher in input_data.teachers:
        if teacher.name not in morning_teachers:
            continue
        for (teacher_id, slot), vars_for_teacher_slot in by_teacher_slot.items():
            if teacher_id != teacher.id or _slot_is_morning(slot):
                continue
            for var in vars_for_teacher_slot:
                terms.append((weights.morning_preference, var))

    return QualityObjective(terms=terms)


def evaluate_quality(
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
    class_daily_target = max(1, (sum(subject_hours.values()) + max(1, len(days)) - 1) // max(1, len(days)))

    class_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    teacher_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    class_day_load: dict[tuple[str, str], int] = defaultdict(int)
    teacher_day_load: dict[tuple[str, str], int] = defaultdict(int)
    class_subject_day_load: dict[tuple[str, str, str], int] = defaultdict(int)
    teacher_total_load: dict[str, int] = defaultdict(int)

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

    gaps_class = sum(_gap_count(positions) for positions in class_day_positions.values())
    gaps_teacher = sum(_gap_count(positions) for positions in teacher_day_positions.values())
    long_series_penalty = (
        sum(1 for positions in class_day_positions.values() if _has_long_sequence(positions))
        + sum(1 for positions in teacher_day_positions.values() if _has_long_sequence(positions))
    )
    compactness_penalty = sum(_span_penalty(positions) for positions in class_day_positions.values())
    compactness_penalty += sum(_span_penalty(positions) for positions in teacher_day_positions.values()) // 2

    overloaded_days = 0
    spread_penalty = 0
    for class_obj in input_data.classes:
        for day in days:
            load = class_day_load[(class_obj.name, day)]
            overloaded_days += max(0, load - class_daily_target)
            spread_penalty += abs(load - class_daily_target)

    for teacher_name, total_load in teacher_total_load.items():
        teacher_target = max(1, (total_load + max(1, len(days)) - 1) // max(1, len(days)))
        for day in days:
            load = teacher_day_load[(teacher_name, day)]
            overloaded_days += max(0, load - teacher_target)

    for class_obj in input_data.classes:
        for subject_name, hours in subject_hours.items():
            ideal_subject_daily = max(1, (hours + max(1, len(days)) - 1) // max(1, len(days)))
            for day in days:
                spread_penalty += max(0, class_subject_day_load[(class_obj.name, subject_name, day)] - ideal_subject_daily) * 2

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
    stability_penalty = 0
    stability = evaluate_stability(input_data.previous_schedule, schedule)
    stability_penalty = stability.stability_penalty
    total_penalty = (
        hard_conflicts * 100
        + gaps_class * 8
        + gaps_teacher * 3
        + overloaded_days * 4
        + spread_penalty * 2
        + long_series_penalty * 6
        + compactness_penalty
        + stability_penalty
    )
    required_sessions = max(1, len(input_data.classes) * sum(subject_hours.values()))
    normalized_penalty_points = int((total_penalty * 100) / max(1, required_sessions * 20))
    total_score = max(0, min(100, 100 - normalized_penalty_points))
    return {
        "gaps_class": gaps_class,
        "gaps_teacher": gaps_teacher,
        "overloaded_days": overloaded_days,
        "spread_penalty": spread_penalty,
        "compactness_penalty": compactness_penalty,
        "long_series_penalty": long_series_penalty,
        "stability_penalty": stability_penalty,
        "changed_sessions": stability.changed_sessions,
        "hard_conflicts": hard_conflicts,
        "soft_score": max(0, 100 - normalized_penalty_points),
        "total_penalty": total_penalty,
        "total_score": total_score,
        "generation_time_ms": int((perf_counter() - started_at) * 1000),
    }


def quality_explanations(
    input_data: ScheduleInput,
    schedule: dict[str, dict[str, ScheduleCell]],
    quality: dict[str, int],
    max_items: int = 8,
) -> list[str]:
    explanations: list[str] = []
    if quality["hard_conflicts"] == 0:
        explanations.append("Hard constraints are satisfied: no class or teacher conflict was detected.")

    slot_day = {slot: slot.split("-", 1)[0] if "-" in slot else slot for slot in input_data.slots}
    position_by_slot = _position_by_slot(input_data.slots, slot_day)
    class_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    teacher_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    teacher_day_load: dict[tuple[str, str], int] = defaultdict(int)
    class_subject_day_load: dict[tuple[str, str, str], int] = defaultdict(int)

    for slot, entries in schedule.items():
        day = slot_day.get(slot, slot.split("-", 1)[0])
        position = position_by_slot.get(slot, 0)
        for class_name, cell in entries.items():
            class_day_positions[(class_name, day)].append(position)
            teacher_day_positions[(cell.teacher, day)].append(position)
            teacher_day_load[(cell.teacher, day)] += 1
            class_subject_day_load[(class_name, cell.subject, day)] += 1

    issues: list[tuple[int, str]] = []
    for (class_name, day), positions in class_day_positions.items():
        gaps = _gap_count(positions)
        if gaps:
            issues.append((gaps * 10, f"Class {class_name} has {gaps} gap(s) on {day}."))
    for (teacher_name, day), positions in teacher_day_positions.items():
        gaps = _gap_count(positions)
        if gaps:
            issues.append((gaps * 8, f"Teacher {teacher_name} has {gaps} gap(s) on {day}."))
    for teacher in input_data.teachers:
        for (teacher_name, day), load in teacher_day_load.items():
            if teacher_name == teacher.name and load > teacher.max_lessons_per_day:
                issues.append((load, f"Teacher {teacher_name} has {load} lessons on {day}."))
    for class_obj in input_data.classes:
        for subject in input_data.subjects:
            for (class_name, subject_name, day), load in class_subject_day_load.items():
                if class_name == class_obj.name and subject_name == subject.name and load > 1:
                    issues.append((load, f"{subject_name} is concentrated for class {class_name} on {day} ({load} lessons)."))

    for _weight, message in sorted(issues, reverse=True)[:max_items]:
        explanations.append(message)
    if not issues:
        explanations.append("No major soft-constraint issue was detected by the V2 quality model.")
    stability = evaluate_stability(input_data.previous_schedule, schedule)
    explanations.extend(stability.explanations[: max(0, max_items - len(explanations))])
    explanations.append(f"OR-Tools quality score: {quality['total_score']}/100.")
    return explanations


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


def _morning_preferences(input_data: ScheduleInput) -> tuple[set[str], set[str]]:
    morning_subjects: set[str] = set()
    morning_teachers: set[str] = set()
    for condition in input_data.conditions:
        if condition.condition_type == "subject_morning_preference" and condition.subject_name:
            morning_subjects.add(condition.subject_name)
        elif condition.condition_type == "teacher_prefer_morning" and condition.teacher_name:
            morning_teachers.add(condition.teacher_name)
    return morning_subjects, morning_teachers


def _slot_is_morning(slot: str) -> bool:
    time_part = slot.split("-", 1)[1] if "-" in slot else slot
    return time_part < "12:00"


def _position_by_slot(slots: list[str], slot_day: dict[str, str]) -> dict[str, int]:
    positions_by_day: dict[str, int] = defaultdict(int)
    positions: dict[str, int] = {}
    for slot in slots:
        day = slot_day[slot]
        positions[slot] = positions_by_day[day]
        positions_by_day[day] += 1
    return positions


def _span_penalty(positions: list[int]) -> int:
    if len(positions) < 2:
        return 0
    ordered = sorted(positions)
    return max(0, ordered[-1] - ordered[0] + 1 - len(ordered))


def _gap_count(positions: list[int]) -> int:
    return _span_penalty(positions)


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


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)
