from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from backend.models.schemas import ScheduleCell
from backend.services.solver.models import ScheduleInput, SolverAssignment


SUPPORTED_REPAIR_MODES = {"repair_class", "repair_teacher", "repair_day"}


@dataclass(frozen=True)
class StabilitySummary:
    changed_sessions: int
    slot_changes: int
    teacher_changes: int
    stability_penalty: int
    explanations: list[str]

    def as_dict(self) -> dict[str, int | list[str]]:
        return {
            "changed_sessions": self.changed_sessions,
            "slot_changes": self.slot_changes,
            "teacher_changes": self.teacher_changes,
            "stability_penalty": self.stability_penalty,
            "explanations": self.explanations,
        }


def stable_session_id(class_name: str, subject: str, occurrence: int) -> str:
    return f"session-{_slug(class_name)}-{_slug(subject)}-{occurrence:04d}"


def schedule_with_session_ids(
    schedule: dict[str, dict[str, ScheduleCell]] | None,
) -> dict[str, dict[str, ScheduleCell]]:
    if not schedule:
        return {}

    records = []
    for slot, entries in schedule.items():
        for class_name, cell in entries.items():
            subject, teacher, session_id = _cell_parts(cell)
            records.append(
                {
                    "slot": str(slot),
                    "class_name": str(class_name),
                    "subject": subject,
                    "teacher": teacher,
                    "session_id": session_id,
                }
            )

    by_logical_course: dict[tuple[str, str], list[dict[str, str | None]]] = defaultdict(list)
    for record in records:
        by_logical_course[(str(record["class_name"]), str(record["subject"]))].append(record)

    assigned_ids: dict[tuple[str, str, str, str], str] = {}
    for (class_name, subject), items in by_logical_course.items():
        items.sort(key=lambda item: (str(item["slot"]), str(item["teacher"]), str(item.get("session_id") or "")))
        used = {str(item["session_id"]) for item in items if item.get("session_id")}
        for index, item in enumerate(items, start=1):
            session_id = str(item["session_id"]) if item.get("session_id") else ""
            if not session_id:
                candidate = stable_session_id(class_name, subject, index)
                suffix = index
                while candidate in used:
                    suffix += 1
                    candidate = stable_session_id(class_name, subject, suffix)
                session_id = candidate
                used.add(session_id)
            assigned_ids[(str(item["slot"]), class_name, subject, str(item["teacher"]))] = session_id

    normalized: dict[str, dict[str, ScheduleCell]] = {}
    for record in records:
        slot = str(record["slot"])
        class_name = str(record["class_name"])
        subject = str(record["subject"])
        teacher = str(record["teacher"])
        normalized.setdefault(slot, {})[class_name] = ScheduleCell(
            subject=subject,
            teacher=teacher,
            session_id=assigned_ids[(slot, class_name, subject, teacher)],
        )
    return normalized


def previous_session_ids_by_class_subject(
    schedule: dict[str, dict[str, ScheduleCell]] | None,
) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for assignment in schedule_to_assignments(schedule):
        if assignment.session_id:
            grouped[(assignment.class_name, assignment.subject)].append(assignment.session_id)
    return grouped


def schedule_to_assignments(schedule: dict[str, dict[str, ScheduleCell]] | None) -> list[SolverAssignment]:
    if not schedule:
        return []
    assignments: list[SolverAssignment] = []
    normalized = schedule_with_session_ids(schedule)
    for slot, entries in normalized.items():
        for class_name, cell in entries.items():
            assignments.append(
                SolverAssignment(
                    slot=slot,
                    class_name=class_name,
                    subject=cell.subject,
                    teacher_name=cell.teacher,
                    session_id=cell.session_id,
                )
            )
    return assignments


def repair_pins_from_previous(input_data: ScheduleInput) -> list[SolverAssignment]:
    previous = schedule_to_assignments(input_data.previous_schedule)
    if not previous or not input_data.repair_mode or not input_data.repair_target:
        return []
    if input_data.repair_mode not in SUPPORTED_REPAIR_MODES:
        return []

    pins: list[SolverAssignment] = []
    for assignment in previous:
        if input_data.repair_mode == "repair_class" and assignment.class_name == input_data.repair_target:
            continue
        if input_data.repair_mode == "repair_teacher" and assignment.teacher_name == input_data.repair_target:
            continue
        if input_data.repair_mode == "repair_day" and _day_of(assignment.slot) == input_data.repair_target:
            continue
        pins.append(assignment)
    return pins


def effective_pinned_assignments(input_data: ScheduleInput) -> list[SolverAssignment]:
    deduped: dict[str, SolverAssignment] = {}
    for assignment in [*repair_pins_from_previous(input_data), *input_data.pinned_assignments]:
        key = assignment.session_id or f"{assignment.class_name}|{assignment.subject}|{assignment.slot}|{assignment.teacher_name}"
        deduped[key] = assignment
    return list(deduped.values())


def stability_cost_for_candidate(
    previous_by_class_subject: dict[tuple[str, str], list[SolverAssignment]],
    class_name: str,
    subject: str,
    slot: str,
    teacher_name: str,
) -> int:
    previous = previous_by_class_subject.get((class_name, subject), [])
    if not previous:
        return 0
    best = 100
    for item in previous:
        cost = 0
        if item.slot != slot:
            cost += 6
        if item.teacher_name != teacher_name:
            cost += 4
        best = min(best, cost)
    return best


def previous_by_class_subject(previous_schedule: dict[str, dict[str, ScheduleCell]] | None) -> dict[tuple[str, str], list[SolverAssignment]]:
    grouped: dict[tuple[str, str], list[SolverAssignment]] = defaultdict(list)
    for assignment in schedule_to_assignments(previous_schedule):
        grouped[(assignment.class_name, assignment.subject)].append(assignment)
    return grouped


def previous_by_session_id(previous_schedule: dict[str, dict[str, ScheduleCell]] | None) -> dict[str, SolverAssignment]:
    return {
        assignment.session_id: assignment
        for assignment in schedule_to_assignments(previous_schedule)
        if assignment.session_id
    }


def evaluate_stability(
    previous_schedule: dict[str, dict[str, ScheduleCell]] | None,
    new_schedule: dict[str, dict[str, ScheduleCell]],
    max_explanations: int = 10,
) -> StabilitySummary:
    previous_by_id = previous_by_session_id(previous_schedule)
    previous = previous_by_class_subject(previous_schedule)
    if not previous:
        return StabilitySummary(0, 0, 0, 0, [])

    slot_changes = 0
    teacher_changes = 0
    changed_sessions = 0
    explanations: list[str] = []

    for assignment in schedule_to_assignments(new_schedule):
        if assignment.session_id and assignment.session_id in previous_by_id:
            matches = [previous_by_id[assignment.session_id]]
        else:
            matches = previous.get((assignment.class_name, assignment.subject), [])
        if not matches:
            continue
        best = min(
            matches,
            key=lambda item: (
                0 if item.slot == assignment.slot else 1,
                0 if item.teacher_name == assignment.teacher_name else 1,
            ),
        )
        slot_changed = best.slot != assignment.slot
        teacher_changed = best.teacher_name != assignment.teacher_name
        if not slot_changed and not teacher_changed:
            continue
        changed_sessions += 1
        if slot_changed:
            slot_changes += 1
            if len(explanations) < max_explanations:
                explanations.append(
                    f"Course {assignment.subject} {assignment.class_name} moved from {best.slot} to {assignment.slot}."
                )
        if teacher_changed:
            teacher_changes += 1
            if len(explanations) < max_explanations:
                explanations.append(
                    f"Teacher changed for {assignment.subject} {assignment.class_name}: {best.teacher_name} -> {assignment.teacher_name}."
                )

    if changed_sessions and len(explanations) < max_explanations:
        explanations.append(f"{changed_sessions} session(s) changed compared with the previous timetable.")
    penalty = slot_changes * 6 + teacher_changes * 4
    return StabilitySummary(changed_sessions, slot_changes, teacher_changes, penalty, explanations)


def _day_of(slot: str) -> str:
    return slot.split("-", 1)[0] if "-" in slot else slot


def _cell_parts(cell: ScheduleCell | dict | object) -> tuple[str, str, str | None]:
    if isinstance(cell, ScheduleCell):
        return cell.subject, cell.teacher, cell.session_id
    if isinstance(cell, dict):
        return str(cell.get("subject", "")), str(cell.get("teacher", "")), _optional_text(cell.get("session_id"))
    return (
        str(getattr(cell, "subject", "")),
        str(getattr(cell, "teacher", "")),
        _optional_text(getattr(cell, "session_id", None)),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"
