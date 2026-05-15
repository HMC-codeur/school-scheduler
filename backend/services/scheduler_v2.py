from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter

from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.scheduler import ScheduleResult, SchedulerService
from backend.services.scoring import score_schedule


@dataclass(frozen=True)
class _Session:
    id: int
    class_id: int
    class_name: str
    subject: str


@dataclass(frozen=True)
class _Candidate:
    slot: str
    day: str
    teacher_id: int
    teacher_name: str
    slot_index: int
    day_position: int


@dataclass(frozen=True)
class V2OptimizationResult:
    schedule: dict[str, dict[str, ScheduleCell]]
    improved: bool
    moves_evaluated: int
    moves_accepted: int
    time_ms: int
    penalty_before: int
    penalty_after: int
    score_before: int
    score_after: int


class FastValidScheduler:
    """Experimental Phase A scheduler: hard constraints only."""

    @staticmethod
    def generate(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        *,
        time_budget_ms: int = 5_000,
        fallback_to_current: bool = True,
    ) -> ScheduleResult:
        started_at = perf_counter()
        result = FastValidScheduler.build_fast_valid(
            classes,
            teachers,
            subjects,
            slots,
            conditions,
            time_budget_ms=time_budget_ms,
        )
        if result.success or not fallback_to_current:
            return result

        fallback = SchedulerService.generate(classes, teachers, subjects, slots, conditions)
        fallback.message = f"V2 fast valid failed ({result.message}); fallback used: {fallback.message}"
        fallback.generation_time_ms = int((perf_counter() - started_at) * 1000)
        return fallback

    @staticmethod
    def build_fast_valid(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        *,
        time_budget_ms: int = 5_000,
    ) -> ScheduleResult:
        started_at = perf_counter()
        deadline = started_at + max(1, time_budget_ms) / 1000
        conditions = conditions or []

        def finish(
            success: bool,
            message: str,
            schedule: dict[str, dict[str, ScheduleCell]] | None = None,
            scheduled_sessions: int = 0,
        ) -> ScheduleResult:
            return ScheduleResult(
                success,
                message,
                schedule or {},
                conflicts_count=0 if success else None,
                required_sessions=total_required_sessions,
                scheduled_sessions=scheduled_sessions,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )

        subject_hours = {subject.name: max(0, subject.hours_per_week) for subject in subjects}
        total_required_sessions = len(classes) * sum(subject_hours.values())

        if not classes:
            return finish(False, "V2 fast valid failed: no classes added.")
        if not teachers:
            return finish(False, "V2 fast valid failed: no teachers added.")
        if not subjects:
            return finish(False, "V2 fast valid failed: no subjects added.")
        if not slots:
            return finish(False, "V2 fast valid failed: no time slots added.")

        slot_day = {slot: slot.split("-", 1)[0] for slot in slots}
        days = sorted(set(slot_day.values()))
        slot_order = {slot: index for index, slot in enumerate(slots)}
        slots_by_day: dict[str, list[str]] = defaultdict(list)
        slot_day_position: dict[str, int] = {}
        for slot in slots:
            slot_day_position[slot] = len(slots_by_day[slot_day[slot]])
            slots_by_day[slot_day[slot]].append(slot)

        class_by_name = {class_obj.name: class_obj for class_obj in classes}
        teacher_by_name = {teacher.name: teacher for teacher in teachers}
        teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
        for teacher in teachers:
            for subject_name in teacher.subjects:
                teachers_by_subject[subject_name].append(teacher)

        for subject_name in subject_hours:
            if not teachers_by_subject.get(subject_name):
                return finish(False, f"V2 fast valid failed: subject '{subject_name}' has no compatible teacher.")

        if total_required_sessions > len(classes) * len(slots):
            return finish(False, "V2 fast valid failed: not enough class slots for required sessions.")

        teacher_unavailable: dict[int, set[str]] = {
            teacher.id: set(teacher.unavailable_slots)
            for teacher in teachers
        }
        class_unavailable: dict[int, set[str]] = defaultdict(set)
        for condition in conditions:
            if condition.condition_type == "teacher_unavailable" and condition.teacher_name and condition.slot:
                teacher = teacher_by_name.get(condition.teacher_name)
                if teacher:
                    teacher_unavailable.setdefault(teacher.id, set()).add(condition.slot)
            elif condition.condition_type == "class_unavailable" and condition.class_name and condition.slot:
                class_obj = class_by_name.get(condition.class_name)
                if class_obj:
                    class_unavailable[class_obj.id].add(condition.slot)

        class_daily_limits = {class_obj.id: max(1, class_obj.max_lessons_per_day) for class_obj in classes}
        teacher_daily_limits = {teacher.id: max(1, teacher.max_lessons_per_day) for teacher in teachers}

        for class_obj in classes:
            capacity = _class_weekly_capacity(class_obj, slots, slot_day, class_unavailable[class_obj.id], class_daily_limits[class_obj.id])
            if capacity < sum(subject_hours.values()):
                return finish(
                    False,
                    f"V2 fast valid failed: class '{class_obj.name}' capacity is too low ({capacity}).",
                )

        sessions: list[_Session] = []
        session_id = 0
        for class_obj in classes:
            for subject_name, hours in subject_hours.items():
                for _ in range(hours):
                    sessions.append(_Session(session_id, class_obj.id, class_obj.name, subject_name))
                    session_id += 1

        domains: dict[int, list[_Candidate]] = {}
        for session in sessions:
            candidates: list[_Candidate] = []
            if perf_counter() > deadline:
                return finish(False, "V2 fast valid failed: time budget exceeded while building domains.")
            for slot in slots:
                if slot in class_unavailable[session.class_id]:
                    continue
                day = slot_day[slot]
                for teacher in teachers_by_subject[session.subject]:
                    if slot in teacher_unavailable.get(teacher.id, set()):
                        continue
                    candidates.append(
                        _Candidate(
                            slot=slot,
                            day=day,
                            teacher_id=teacher.id,
                            teacher_name=teacher.name,
                            slot_index=slot_order[slot],
                            day_position=slot_day_position[slot],
                        )
                    )
            if not candidates:
                return finish(
                    False,
                    f"V2 fast valid failed: no candidates for {session.class_name} / {session.subject}.",
                )
            domains[session.id] = candidates

        ordered_sessions = sorted(
            sessions,
            key=lambda session: (
                len(domains[session.id]),
                session.class_id,
                session.subject,
                session.id,
            ),
        )
        remaining: set[int] = {session.id for session in ordered_sessions}
        session_by_id = {session.id: session for session in sessions}
        session_ids_by_class: dict[int, set[int]] = defaultdict(set)
        session_ids_by_teacher: dict[int, set[int]] = defaultdict(set)
        for session in sessions:
            session_ids_by_class[session.class_id].add(session.id)
            for candidate in domains[session.id]:
                session_ids_by_teacher[candidate.teacher_id].add(session.id)

        class_busy: set[tuple[int, str]] = set()
        teacher_busy: set[tuple[int, str]] = set()
        class_day_load: dict[tuple[int, str], int] = defaultdict(int)
        teacher_day_load: dict[tuple[int, str], int] = defaultdict(int)
        teacher_total_load: dict[int, int] = defaultdict(int)
        class_day_positions: dict[tuple[int, str], set[int]] = defaultdict(set)
        teacher_day_positions: dict[tuple[int, str], set[int]] = defaultdict(set)
        assignments: list[tuple[_Session, _Candidate]] = []
        ideal_class_daily_load = max(1, (sum(subject_hours.values()) + max(1, len(days)) - 1) // max(1, len(days)))

        def candidate_is_available(session: _Session, candidate: _Candidate) -> bool:
            if (session.class_id, candidate.slot) in class_busy:
                return False
            if (candidate.teacher_id, candidate.slot) in teacher_busy:
                return False
            if class_day_load[(session.class_id, candidate.day)] >= class_daily_limits[session.class_id]:
                return False
            if teacher_day_load[(candidate.teacher_id, candidate.day)] >= teacher_daily_limits[candidate.teacher_id]:
                return False
            return True

        def candidate_priority(session: _Session, candidate: _Candidate) -> tuple[int, int, int, int, int, int, int, int, int, int, int]:
            class_positions = class_day_positions[(session.class_id, candidate.day)]
            teacher_positions = teacher_day_positions[(candidate.teacher_id, candidate.day)]
            class_gap_delta = _gap_delta_after_add(class_positions, candidate.day_position)
            teacher_gap_delta = _gap_delta_after_add(teacher_positions, candidate.day_position)
            class_isolation = _isolation_penalty(class_positions, candidate.day_position)
            teacher_isolation = _isolation_penalty(teacher_positions, candidate.day_position)
            class_long_sequence = 1 if _creates_long_sequence(class_positions, candidate.day_position) else 0
            teacher_long_sequence = 1 if _creates_long_sequence(teacher_positions, candidate.day_position) else 0
            projected_class_load = class_day_load[(session.class_id, candidate.day)] + 1
            projected_teacher_load = teacher_day_load[(candidate.teacher_id, candidate.day)] + 1
            class_balance_penalty = abs(projected_class_load - ideal_class_daily_load)
            return (
                class_gap_delta,
                teacher_gap_delta,
                class_long_sequence,
                teacher_long_sequence,
                class_isolation,
                teacher_isolation,
                class_balance_penalty,
                projected_class_load,
                projected_teacher_load,
                teacher_total_load[candidate.teacher_id],
                candidate.slot_index,
            )

        def available_candidates(session: _Session) -> list[_Candidate]:
            candidates = [candidate for candidate in domains[session.id] if candidate_is_available(session, candidate)]
            candidates.sort(key=lambda candidate: candidate_priority(session, candidate) + (candidate.teacher_id,))
            return candidates

        def affected_sessions_have_forward_candidate(session: _Session, candidate: _Candidate) -> bool:
            affected = session_ids_by_class[session.class_id] | session_ids_by_teacher[candidate.teacher_id]
            for session_id in affected & remaining:
                remaining_session = session_by_id[session_id]
                if not any(candidate_is_available(remaining_session, item) for item in domains[session_id]):
                    return False
            return True

        def place(session: _Session, candidate: _Candidate) -> None:
            class_busy.add((session.class_id, candidate.slot))
            teacher_busy.add((candidate.teacher_id, candidate.slot))
            class_day_load[(session.class_id, candidate.day)] += 1
            teacher_day_load[(candidate.teacher_id, candidate.day)] += 1
            teacher_total_load[candidate.teacher_id] += 1
            class_day_positions[(session.class_id, candidate.day)].add(candidate.day_position)
            teacher_day_positions[(candidate.teacher_id, candidate.day)].add(candidate.day_position)
            assignments.append((session, candidate))
            remaining.remove(session.id)

        def build_greedy() -> bool:
            ordered_remaining = list(ordered_sessions)
            while ordered_remaining:
                if perf_counter() > deadline:
                    return False
                session = ordered_remaining.pop(0)
                candidates = available_candidates(session)
                if not candidates:
                    return False
                placed = False
                for candidate in candidates:
                    place(session, candidate)
                    if affected_sessions_have_forward_candidate(session, candidate):
                        placed = True
                        break
                    remaining.add(session.id)
                    assignments.pop()
                    class_busy.remove((session.class_id, candidate.slot))
                    teacher_busy.remove((candidate.teacher_id, candidate.slot))
                    class_day_load[(session.class_id, candidate.day)] -= 1
                    teacher_day_load[(candidate.teacher_id, candidate.day)] -= 1
                    teacher_total_load[candidate.teacher_id] -= 1
                    class_day_positions[(session.class_id, candidate.day)].discard(candidate.day_position)
                    teacher_day_positions[(candidate.teacher_id, candidate.day)].discard(candidate.day_position)
                if not placed:
                    return False
            return True

        if not build_greedy():
            message = (
                "V2 fast valid failed: time budget exceeded."
                if perf_counter() > deadline
                else "V2 fast valid failed: constraints conflict."
            )
            return finish(False, message, scheduled_sessions=len(assignments))

        schedule: dict[str, dict[str, ScheduleCell]] = defaultdict(dict)
        for session, candidate in assignments:
            schedule[candidate.slot][session.class_name] = ScheduleCell(
                subject=session.subject,
                teacher=candidate.teacher_name,
            )

        return finish(
            True,
            "V2 fast valid schedule generated successfully.",
            dict(schedule),
            scheduled_sessions=len(assignments),
        )

    @staticmethod
    def optimize_quality(
        schedule: dict[str, dict[str, ScheduleCell]],
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        *,
        time_budget_ms: int = 1_000,
    ) -> V2OptimizationResult:
        started_at = perf_counter()
        deadline = started_at + max(1, time_budget_ms) / 1000
        conditions = conditions or []

        current = _copy_schedule(schedule)
        before_penalty = _quality_penalty(current, slots)["total_penalty"]
        before_score = int(score_schedule(current, classes, teachers, subjects, slots, conditions)["quality_score"])
        before_external_penalty = int(
            score_schedule(current, classes, teachers, subjects, slots, conditions)["metrics"]["total_penalty"]
        )

        context = _HardConstraintContext(classes, teachers, subjects, slots, conditions)
        if not context.is_schedule_valid(current):
            return V2OptimizationResult(
                schedule=current,
                improved=False,
                moves_evaluated=0,
                moves_accepted=0,
                time_ms=int((perf_counter() - started_at) * 1000),
                penalty_before=before_penalty,
                penalty_after=before_penalty,
                score_before=before_score,
                score_after=before_score,
            )

        moves_evaluated = 0
        moves_accepted = 0
        max_passes = 2
        for _ in range(max_passes):
            accepted_this_pass = False
            targeted_moves = _class_gap_targets(current, slots)
            if not targeted_moves:
                break
            for class_name, to_slot in targeted_moves:
                if perf_counter() > deadline:
                    break
                for from_slot, _class_name, cell in _schedule_entries(current, slots):
                    if perf_counter() > deadline:
                        break
                    if _class_name != class_name:
                        continue
                    if to_slot == from_slot or class_name in current.get(to_slot, {}):
                        continue
                    for teacher in context.compatible_teachers(cell.subject):
                        if perf_counter() > deadline:
                            break
                        moves_evaluated += 1
                        trial = _copy_schedule(current)
                        del trial[from_slot][class_name]
                        if not trial[from_slot]:
                            del trial[from_slot]
                        trial.setdefault(to_slot, {})[class_name] = ScheduleCell(
                            subject=cell.subject,
                            teacher=teacher.name,
                        )

                        if not context.is_schedule_valid(trial):
                            continue

                        trial_penalty = _quality_penalty(trial, slots)["total_penalty"]
                        current_penalty = _quality_penalty(current, slots)["total_penalty"]
                        if trial_penalty >= current_penalty:
                            continue

                        trial_scored = score_schedule(trial, classes, teachers, subjects, slots, conditions)
                        trial_score = int(trial_scored["quality_score"])
                        trial_external_penalty = int(trial_scored["metrics"]["total_penalty"])
                        current_scored = score_schedule(current, classes, teachers, subjects, slots, conditions)
                        current_score = int(current_scored["quality_score"])
                        current_external_penalty = int(current_scored["metrics"]["total_penalty"])
                        if trial_score < current_score or trial_external_penalty > current_external_penalty:
                            continue

                        current = trial
                        moves_accepted += 1
                        accepted_this_pass = True
                        break
                    if accepted_this_pass:
                        break
                if accepted_this_pass or perf_counter() > deadline:
                    break
            if not accepted_this_pass or perf_counter() > deadline:
                break

        after_penalty = _quality_penalty(current, slots)["total_penalty"]
        after_scored = score_schedule(current, classes, teachers, subjects, slots, conditions)
        after_score = int(after_scored["quality_score"])
        after_external_penalty = int(after_scored["metrics"]["total_penalty"])
        if after_score < before_score or after_external_penalty > before_external_penalty:
            current = _copy_schedule(schedule)
            after_penalty = before_penalty
            after_score = before_score
            moves_accepted = 0

        return V2OptimizationResult(
            schedule=current,
            improved=after_penalty < before_penalty or after_score > before_score,
            moves_evaluated=moves_evaluated,
            moves_accepted=moves_accepted,
            time_ms=int((perf_counter() - started_at) * 1000),
            penalty_before=before_penalty,
            penalty_after=after_penalty,
            score_before=before_score,
            score_after=after_score,
        )


def _class_weekly_capacity(
    class_obj: Class,
    slots: list[str],
    slot_day: dict[str, str],
    blocked_slots: set[str],
    daily_limit: int,
) -> int:
    available_by_day: dict[str, int] = defaultdict(int)
    for slot in slots:
        if slot in blocked_slots:
            continue
        available_by_day[slot_day[slot]] += 1
    return sum(min(daily_limit, count) for count in available_by_day.values())


def _gap_delta_after_add(positions: set[int], position: int) -> int:
    if not positions:
        return 0
    if position in positions:
        return 0
    minimum = min(positions)
    maximum = max(positions)
    if minimum < position < maximum:
        return -2
    if position < minimum:
        return max(0, minimum - position - 1)
    return max(0, position - maximum - 1)


def _isolation_penalty(positions: set[int], position: int) -> int:
    if not positions:
        return 0
    if position - 1 in positions or position + 1 in positions:
        return 0
    minimum = min(positions)
    maximum = max(positions)
    if minimum < position < maximum:
        return -1
    return 2


def _creates_long_sequence(positions: set[int], position: int, threshold: int = 5) -> bool:
    if position in positions:
        return False
    streak = 1
    cursor = position - 1
    while cursor in positions:
        streak += 1
        if streak >= threshold:
            return True
        cursor -= 1
    cursor = position + 1
    while cursor in positions:
        streak += 1
        if streak >= threshold:
            return True
        cursor += 1
    return False


class _HardConstraintContext:
    def __init__(
        self,
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition],
    ) -> None:
        self.classes = classes
        self.teachers = teachers
        self.subjects = subjects
        self.slots = slots
        self.slot_set = set(slots)
        self.slot_day = {slot: slot.split("-", 1)[0] for slot in slots}
        self.class_by_name = {class_obj.name: class_obj for class_obj in classes}
        self.teacher_by_name = {teacher.name: teacher for teacher in teachers}
        self.subject_hours = {subject.name: max(0, subject.hours_per_week) for subject in subjects}
        self.class_daily_limits = {class_obj.name: max(1, class_obj.max_lessons_per_day) for class_obj in classes}
        self.teacher_daily_limits = {teacher.name: max(1, teacher.max_lessons_per_day) for teacher in teachers}
        self.teacher_subjects = {teacher.name: set(teacher.subjects) for teacher in teachers}
        self.teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
        for teacher in teachers:
            for subject_name in teacher.subjects:
                self.teachers_by_subject[subject_name].append(teacher)

        self.teacher_unavailable: dict[str, set[str]] = {
            teacher.name: set(teacher.unavailable_slots)
            for teacher in teachers
        }
        self.class_unavailable: dict[str, set[str]] = defaultdict(set)
        for condition in conditions:
            if condition.condition_type == "teacher_unavailable" and condition.teacher_name and condition.slot:
                self.teacher_unavailable.setdefault(condition.teacher_name, set()).add(condition.slot)
            elif condition.condition_type == "class_unavailable" and condition.class_name and condition.slot:
                self.class_unavailable[condition.class_name].add(condition.slot)

    def compatible_teachers(self, subject_name: str) -> list[Teacher]:
        return sorted(self.teachers_by_subject.get(subject_name, []), key=lambda teacher: (teacher.name, teacher.id))

    def is_schedule_valid(self, schedule: dict[str, dict[str, ScheduleCell]]) -> bool:
        teacher_slot_use: set[tuple[str, str]] = set()
        class_day_load: dict[tuple[str, str], int] = defaultdict(int)
        teacher_day_load: dict[tuple[str, str], int] = defaultdict(int)
        class_subject_counts: dict[tuple[str, str], int] = defaultdict(int)
        placed_sessions = 0

        for slot, class_entries in schedule.items():
            if slot not in self.slot_set:
                return False
            day = self.slot_day[slot]
            for class_name, cell in class_entries.items():
                if class_name not in self.class_by_name:
                    return False
                if cell.teacher not in self.teacher_by_name:
                    return False
                if cell.subject not in self.subject_hours:
                    return False
                if cell.subject not in self.teacher_subjects.get(cell.teacher, set()):
                    return False
                if slot in self.class_unavailable.get(class_name, set()):
                    return False
                if slot in self.teacher_unavailable.get(cell.teacher, set()):
                    return False
                if (cell.teacher, slot) in teacher_slot_use:
                    return False

                teacher_slot_use.add((cell.teacher, slot))
                class_day_load[(class_name, day)] += 1
                teacher_day_load[(cell.teacher, day)] += 1
                class_subject_counts[(class_name, cell.subject)] += 1
                placed_sessions += 1

                if class_day_load[(class_name, day)] > self.class_daily_limits[class_name]:
                    return False
                if teacher_day_load[(cell.teacher, day)] > self.teacher_daily_limits[cell.teacher]:
                    return False

        expected_sessions = len(self.classes) * sum(self.subject_hours.values())
        if placed_sessions != expected_sessions:
            return False
        for class_obj in self.classes:
            for subject_name, hours in self.subject_hours.items():
                if class_subject_counts[(class_obj.name, subject_name)] != hours:
                    return False
        return True


def _copy_schedule(schedule: dict[str, dict[str, ScheduleCell]]) -> dict[str, dict[str, ScheduleCell]]:
    copied: dict[str, dict[str, ScheduleCell]] = {}
    for slot, entries in schedule.items():
        copied[slot] = {}
        for class_name, cell in entries.items():
            if isinstance(cell, ScheduleCell):
                copied[slot][class_name] = ScheduleCell(subject=cell.subject, teacher=cell.teacher)
            else:
                copied[slot][class_name] = ScheduleCell(
                    subject=str(getattr(cell, "subject", "")),
                    teacher=str(getattr(cell, "teacher", "")),
                )
    return copied


def _schedule_entries(
    schedule: dict[str, dict[str, ScheduleCell]],
    slots: list[str],
) -> list[tuple[str, str, ScheduleCell]]:
    slot_order = {slot: index for index, slot in enumerate(slots)}
    entries: list[tuple[str, str, ScheduleCell]] = []
    for slot, class_entries in schedule.items():
        for class_name, cell in class_entries.items():
            entries.append((slot, class_name, cell))
    return sorted(entries, key=lambda item: (slot_order.get(item[0], len(slots)), item[1], item[2].subject))


def _class_gap_targets(schedule: dict[str, dict[str, ScheduleCell]], slots: list[str]) -> list[tuple[str, str]]:
    slot_day = {slot: slot.split("-", 1)[0] for slot in slots}
    slots_by_day: dict[str, list[str]] = defaultdict(list)
    for slot in slots:
        slots_by_day[slot_day[slot]].append(slot)
    position_by_slot = {
        slot: index
        for day_slots in slots_by_day.values()
        for index, slot in enumerate(day_slots)
    }
    slot_by_day_position = {
        (day, index): slot
        for day, day_slots in slots_by_day.items()
        for index, slot in enumerate(day_slots)
    }

    class_day_positions: dict[tuple[str, str], set[int]] = defaultdict(set)
    for slot, entries in schedule.items():
        day = slot_day.get(slot)
        if day is None:
            continue
        position = position_by_slot.get(slot)
        if position is None:
            continue
        for class_name in entries:
            class_day_positions[(class_name, day)].add(position)

    targets: list[tuple[str, str]] = []
    for (class_name, day), positions in sorted(class_day_positions.items()):
        if len(positions) < 2:
            continue
        for position in range(min(positions) + 1, max(positions)):
            if position in positions:
                continue
            slot = slot_by_day_position.get((day, position))
            if slot is not None:
                targets.append((class_name, slot))
    return targets


def _quality_penalty(schedule: dict[str, dict[str, ScheduleCell]], slots: list[str]) -> dict[str, int]:
    slot_day = {slot: slot.split("-", 1)[0] for slot in slots}
    positions_by_day: dict[str, dict[str, int]] = defaultdict(dict)
    for slot in slots:
        positions_by_day[slot_day[slot]][slot] = len(positions_by_day[slot_day[slot]])

    class_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    teacher_day_positions: dict[tuple[str, str], list[int]] = defaultdict(list)
    for slot, entries in schedule.items():
        day = slot_day.get(slot, slot.split("-", 1)[0])
        position = positions_by_day.get(day, {}).get(slot)
        if position is None:
            continue
        for class_name, cell in entries.items():
            class_day_positions[(class_name, day)].append(position)
            teacher_day_positions[(cell.teacher, day)].append(position)

    class_gaps = sum(_gap_count(positions) for positions in class_day_positions.values())
    teacher_gaps = sum(_gap_count(positions) for positions in teacher_day_positions.values())
    class_long_sequences = sum(1 for positions in class_day_positions.values() if _has_long_sequence(positions))
    teacher_long_sequences = sum(1 for positions in teacher_day_positions.values() if _has_long_sequence(positions))
    total_penalty = (
        class_gaps * 3
        + teacher_gaps * 2
        + class_long_sequences * 6
        + teacher_long_sequences * 6
    )
    return {
        "class_gaps": class_gaps,
        "teacher_gaps": teacher_gaps,
        "class_long_sequences": class_long_sequences,
        "teacher_long_sequences": teacher_long_sequences,
        "total_penalty": total_penalty,
    }


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
