from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from backend.models.schemas import Class, LearningGroup, ScheduleCell, Subject, Teacher


def _schedule_to_dict(schedule: dict[str, dict[str, ScheduleCell]] | dict | None) -> dict:
    if not schedule:
        return {}
    normalized: dict[str, dict] = {}
    for slot, class_entries in schedule.items():
        normalized[slot] = {}
        for class_name, cell in class_entries.items():
            if isinstance(cell, ScheduleCell):
                normalized[slot][class_name] = cell.model_dump()
            elif hasattr(cell, "model_dump"):
                normalized[slot][class_name] = cell.model_dump()
            elif isinstance(cell, dict):
                normalized_cell = {
                    "subject": str(cell.get("subject", "")),
                    "teacher": str(cell.get("teacher", "")),
                }
                if cell.get("session_id"):
                    normalized_cell["session_id"] = str(cell.get("session_id"))
                normalized[slot][class_name] = normalized_cell
            else:
                normalized[slot][class_name] = {"subject": "", "teacher": ""}
    return normalized


def compute_schedule_signature(schedule) -> str:
    normalized = _schedule_to_dict(schedule)
    payload = json.dumps(normalized if normalized else {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _required_sessions(classes: list[Class], subjects: list[Subject], learning_groups: list[LearningGroup] | None = None) -> int:
    groups = learning_groups or []
    if not groups:
        return len(classes) * sum(max(0, subject.hours_per_week) for subject in subjects)
    subject_hours = {subject.name: max(0, subject.hours_per_week) for subject in subjects}
    grouped_subjects = {(group.class_id, group.subject_name) for group in groups}
    total = 0
    for class_obj in classes:
        for subject in subjects:
            if (class_obj.id, subject.name) in grouped_subjects:
                total += sum(subject_hours[subject.name] for group in groups if group.class_id == class_obj.id and group.subject_name == subject.name)
            else:
                total += subject_hours[subject.name]
    return total


def analyze_schedule(schedule, classes, teachers, subjects, slots, constraints=None, learning_groups: list[LearningGroup] | None = None) -> dict:
    normalized = _schedule_to_dict(schedule)
    metrics = {
        "teacher_conflicts": 0,
        "class_conflicts": 0,
        "incompatible_assignments": 0,
        "unplaced_sessions": 0,
        "empty_gaps": 0,
        "overloaded_days": 0,
        "teacher_overload": 0,
        "total_penalty": 0,
    }

    if not normalized:
        expected = _required_sessions(classes, subjects, learning_groups)
        metrics["unplaced_sessions"] = expected
        metrics["total_penalty"] = max(100, expected * 20)
        return metrics

    slot_order = {slot: idx for idx, slot in enumerate(slots)}
    teacher_subjects = {t.name: set(t.subjects) for t in teachers}
    required_total = _required_sessions(classes, subjects, learning_groups)

    teacher_slot_use: dict[tuple[str, str], int] = defaultdict(int)
    class_slot_use: dict[tuple[str, str], int] = defaultdict(int)
    class_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    class_day_counts: dict[tuple[str, str], int] = defaultdict(int)
    teacher_day_counts: dict[tuple[str, str], int] = defaultdict(int)

    placed_sessions = 0
    for slot, entries in normalized.items():
        day = slot.split("-", 1)[0] if "-" in slot else slot
        for class_name, cell in entries.items():
            placed_sessions += 1
            teacher = str(cell.get("teacher", ""))
            subject = str(cell.get("subject", ""))
            teacher_slot_use[(teacher, slot)] += 1
            class_slot_use[(class_name, slot)] += 1
            if subject and teacher and subject not in teacher_subjects.get(teacher, set()):
                metrics["incompatible_assignments"] += 1
            pos = slot_order.get(slot)
            if pos is not None:
                class_day_positions[(class_name, day)].append(pos)
            class_day_counts[(class_name, day)] += 1
            teacher_day_counts[(teacher, day)] += 1

    metrics["teacher_conflicts"] = sum(max(0, count - 1) for count in teacher_slot_use.values())
    metrics["class_conflicts"] = sum(max(0, count - 1) for count in class_slot_use.values())
    metrics["unplaced_sessions"] = max(0, required_total - placed_sessions)

    for positions in class_day_positions.values():
        if len(positions) < 2:
            continue
        ordered = sorted(positions)
        internal_span = ordered[-1] - ordered[0] + 1
        metrics["empty_gaps"] += max(0, internal_span - len(ordered))

    class_daily_limit = {c.name: max(1, c.max_lessons_per_day) for c in classes}
    for (class_name, _day), count in class_day_counts.items():
        if count > class_daily_limit.get(class_name, 6):
            metrics["overloaded_days"] += 1

    teacher_daily_limit = {t.name: max(1, t.max_lessons_per_day) for t in teachers}
    for (teacher_name, _day), count in teacher_day_counts.items():
        if teacher_name and count > teacher_daily_limit.get(teacher_name, 6):
            metrics["teacher_overload"] += 1

    metrics["total_penalty"] = (
        metrics["teacher_conflicts"] * 25
        + metrics["class_conflicts"] * 25
        + metrics["incompatible_assignments"] * 30
        + metrics["unplaced_sessions"] * 20
        + metrics["overloaded_days"] * 8
        + metrics["teacher_overload"] * 8
        + metrics["empty_gaps"] * 3
    )
    return metrics


def score_schedule(schedule, classes, teachers, subjects, slots, constraints=None, learning_groups: list[LearningGroup] | None = None) -> dict:
    metrics = analyze_schedule(schedule, classes, teachers, subjects, slots, constraints, learning_groups)
    raw_score = 100 - int(metrics.get("total_penalty", 0))
    if not _schedule_to_dict(schedule):
        raw_score = min(raw_score, 0)
    quality_score = max(0, min(100, raw_score))

    if quality_score >= 90:
        description = "Planning excellent avec très peu de problèmes détectés."
    elif quality_score >= 75:
        description = "Planning solide avec quelques petits ajustements possibles."
    elif quality_score >= 50:
        description = "Planning utilisable mais plusieurs optimisations sont recommandées."
    else:
        description = "Planning fragile: conflits ou sessions non placées à corriger en priorité."

    public_metrics = {
        "teacher_conflicts": int(metrics.get("teacher_conflicts", 0)),
        "class_conflicts": int(metrics.get("class_conflicts", 0)),
        "unplaced_sessions": int(metrics.get("unplaced_sessions", 0)),
        "empty_gaps": int(metrics.get("empty_gaps", 0)),
        "overloaded_days": int(metrics.get("overloaded_days", 0)),
        "teacher_overload": int(metrics.get("teacher_overload", 0)),
        "total_penalty": int(metrics.get("total_penalty", 0)),
    }
    return {"quality_score": quality_score, "metrics": public_metrics, "description": description}


def build_schedule_option(option_id, schedule, classes, teachers, subjects, slots, constraints=None, learning_groups: list[LearningGroup] | None = None) -> dict:
    scored = score_schedule(schedule, classes, teachers, subjects, slots, constraints, learning_groups)
    number = option_id.split("-")[-1] if "-" in option_id else option_id
    return {
        "id": str(option_id),
        "title": f"Option {number}",
        "description": str(scored.get("description") or ""),
        "quality_score": int(scored.get("quality_score", 0)),
        "selected": False,
        "schedule_signature": compute_schedule_signature(schedule),
        "metrics": dict(scored.get("metrics") or {}),
        "score_breakdown": [],
        "schedule": _schedule_to_dict(schedule),
    }


def rank_schedule_options(options) -> list:
    valid = [o for o in options if isinstance(o, dict) and o.get("schedule_signature")]
    deduped: list[dict] = []
    seen = set()
    for option in valid:
        sig = option.get("schedule_signature")
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(option)
    deduped.sort(key=lambda o: int(o.get("quality_score", 0)), reverse=True)
    for idx, option in enumerate(deduped, start=1):
        option["id"] = f"option-{idx}"
        option["title"] = f"Option {idx}"
        option["selected"] = idx == 1
    return deduped
