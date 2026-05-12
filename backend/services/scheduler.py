from collections import defaultdict
from dataclasses import dataclass

from backend.models.schemas import Class, ScheduleCell, Subject, Teacher


@dataclass
class ScheduleResult:
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]


class SchedulerService:
    @staticmethod
    def generate(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        default_max_lessons_per_class_per_day: int = 6,
        default_max_lessons_per_teacher_per_day: int = 6,
    ) -> ScheduleResult:
        if not classes:
            return ScheduleResult(False, "Cannot generate schedule: no classes added.", {})
        if not teachers:
            return ScheduleResult(False, "Cannot generate schedule: no teachers added.", {})
        if not subjects:
            return ScheduleResult(False, "Cannot generate schedule: no subjects added.", {})
        if not slots:
            return ScheduleResult(False, "Cannot generate schedule: no time slots added.", {})

        def day_of(slot: str) -> str:
            return slot.split("-", 1)[0]

        # We keep the original slot order so existing callers still receive
        # the same slot keys format and deterministic behavior.
        slot_order = {slot: idx for idx, slot in enumerate(slots)}
        days = sorted({day_of(s) for s in slots})
        if not days:
            return ScheduleResult(False, "Cannot generate schedule: no valid day information in slots.", {})

        subject_hours = {s.name: s.hours_per_week for s in subjects}
        total_required_sessions = len(classes) * sum(subject_hours.values())
        total_available_sessions = len(classes) * len(slots)
        if total_required_sessions > total_available_sessions:
            return ScheduleResult(
                False,
                "Cannot generate schedule: not enough slots for all required subject hours.",
                {},
            )

        weekly_hours_per_class = sum(subject_hours.values())
        for class_obj in classes:
            class_daily_limit = max(1, getattr(class_obj, "max_lessons_per_day", default_max_lessons_per_class_per_day))
            class_weekly_capacity = len(days) * class_daily_limit
            if weekly_hours_per_class > class_weekly_capacity:
                return ScheduleResult(
                    False,
                    (
                        f"Cannot generate schedule: class '{class_obj.name}' daily max is too low for weekly requirements "
                        f"({weekly_hours_per_class} required, {class_weekly_capacity} max capacity)."
                    ),
                    {},
                )

        teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
        for teacher in teachers:
            for sub in teacher.subjects:
                teachers_by_subject[sub].append(teacher)

        for subject_name in subject_hours:
            if not teachers_by_subject.get(subject_name):
                return ScheduleResult(
                    False,
                    f"Cannot generate schedule: subject '{subject_name}' has no teacher assigned.",
                    {},
                )

        teacher_unavailable = {t.id: set(t.unavailable_slots) for t in teachers}

        for teacher in teachers:
            available_slots = [slot for slot in slots if slot not in teacher_unavailable[teacher.id]]
            teacher_daily_limit = max(1, getattr(teacher, "max_lessons_per_day", default_max_lessons_per_teacher_per_day))
            teacher_weekly_capacity = len(days) * teacher_daily_limit
            capped_capacity = min(len(available_slots), teacher_weekly_capacity)
            if capped_capacity <= 0 and teacher.subjects:
                return ScheduleResult(
                    False,
                    f"Cannot generate schedule: teacher '{teacher.name}' has no available slots.",
                    {},
                )

        sessions: list[tuple[Class, str]] = []
        for class_obj in classes:
            for subject_name, hours in subject_hours.items():
                sessions.extend((class_obj, subject_name) for _ in range(hours))

        def schedule_score(assignments: list[dict[str, str]]) -> int:
            """
            Compute a quality score for a complete schedule.

            Higher is better. Conflicts should never happen because constraints
            are checked while placing sessions, but we still keep strong penalties
            as a safety net for future edits.
            """
            class_by_name = {c.name: c for c in classes}
            slot_to_day = {slot: day_of(slot) for slot in slots}
            slots_per_day: dict[str, list[str]] = defaultdict(list)
            for slot in slots:
                slots_per_day[slot_to_day[slot]].append(slot)

            class_day_slots: dict[tuple[str, str], set[str]] = defaultdict(set)
            class_day_subjects: dict[tuple[str, str], list[str]] = defaultdict(list)
            teacher_slot_use: dict[tuple[str, str], int] = defaultdict(int)

            for item in assignments:
                day = slot_to_day[item["slot"]]
                class_day_slots[(item["class"], day)].add(item["slot"])
                class_day_subjects[(item["class"], day)].append(item["subject"])
                teacher_slot_use[(item["teacher"], item["slot"])] += 1

            score = 0

            # Heavy penalty for any conflict (should be zero in normal cases).
            for count in teacher_slot_use.values():
                if count > 1:
                    score -= 500 * (count - 1)

            for class_obj in classes:
                per_day_load = []
                for day in days:
                    key = (class_obj.name, day)
                    used_slots = class_day_slots[key]
                    subjects_in_day = class_day_subjects[key]
                    load = len(used_slots)
                    per_day_load.append(load)

                    if load == 0:
                        continue

                    ordered_slots = sorted(used_slots, key=lambda s: slot_order[s])
                    positions = [slot_order[s] for s in ordered_slots]

                    # Penalize gaps inside the active part of the day.
                    if positions:
                        span = positions[-1] - positions[0] + 1
                        holes = span - len(positions)
                        score -= holes * 6

                    # Penalize many repeated subjects on same day.
                    subject_count = defaultdict(int)
                    for subject_name in subjects_in_day:
                        subject_count[subject_name] += 1
                    for repeated in subject_count.values():
                        if repeated > 1:
                            score -= (repeated - 1) * 4

                    # Penalize long streaks of consecutive classes.
                    streak = 1
                    for idx in range(1, len(positions)):
                        if positions[idx] == positions[idx - 1] + 1:
                            streak += 1
                            if streak > 2:
                                score -= 3
                        else:
                            streak = 1

                # Reward balanced load across days (small variance).
                avg = sum(per_day_load) / len(per_day_load)
                imbalance = sum(abs(v - avg) for v in per_day_load)
                score -= int(imbalance * 2)

            return score

        def build_schedule(assignments: list[dict[str, str]]) -> dict[str, dict[str, ScheduleCell]]:
            schedule: dict[str, dict[str, ScheduleCell]] = defaultdict(dict)
            for item in assignments:
                schedule[item["slot"]][item["class"]] = ScheduleCell(
                    subject=item["subject"],
                    teacher=item["teacher"],
                )
            return dict(schedule)

        best_assignments: list[dict[str, str]] | None = None
        best_score: int | None = None

        for attempt in range(3):
            # Try multiple session orders and keep the best quality score.
            # This improves schedule quality while staying deterministic.
            if attempt == 0:
                ordered_sessions = sorted(sessions, key=lambda x: len(teachers_by_subject.get(x[1], [])))
            elif attempt == 1:
                ordered_sessions = sorted(sessions, key=lambda x: (x[0].name, -subject_hours[x[1]]))
            else:
                ordered_sessions = sorted(sessions, key=lambda x: (x[1], x[0].name))

            teacher_busy: dict[tuple[int, str], bool] = {}
            class_busy: dict[tuple[int, str], bool] = {}
            class_daily_load: dict[tuple[int, str], int] = defaultdict(int)
            teacher_daily_load: dict[tuple[int, str], int] = defaultdict(int)
            class_subject_day_count: dict[tuple[int, str, str], int] = defaultdict(int)
            assignments: list[dict[str, str]] = []

            def slot_priority(class_id: int, subject_name: str, slot: str) -> tuple[int, int, int, int]:
                day = day_of(slot)
                same_day_subject_count = class_subject_day_count[(class_id, subject_name, day)]
                daily_load = class_daily_load[(class_id, day)]
                # Encourage middle-of-day first to reduce edge gaps,
                # then alternate day usage to spread courses.
                middle_distance = abs(slot_order[slot] - (len(slots) // 2))
                return (same_day_subject_count, daily_load, middle_distance, slot_order[slot])

            def backtrack(index: int) -> bool:
                if index == len(ordered_sessions):
                    return True

                class_obj, subject_name = ordered_sessions[index]
                valid_teachers = teachers_by_subject[subject_name]
                candidate_slots = sorted(slots, key=lambda s: slot_priority(class_obj.id, subject_name, s))

                for slot in candidate_slots:
                    day = day_of(slot)
                    if class_busy.get((class_obj.id, slot)):
                        continue

                    class_daily_limit = max(
                        1, getattr(class_obj, "max_lessons_per_day", default_max_lessons_per_class_per_day)
                    )
                    if class_daily_load[(class_obj.id, day)] >= class_daily_limit:
                        continue

                    sorted_teachers = sorted(
                        valid_teachers,
                        key=lambda t: (
                            teacher_daily_load[(t.id, day)],
                            slot in teacher_unavailable[t.id],
                            t.name,
                        ),
                    )

                    for teacher in sorted_teachers:
                        if slot in teacher_unavailable[teacher.id]:
                            continue
                        if teacher_busy.get((teacher.id, slot)):
                            continue

                        teacher_daily_limit = max(
                            1, getattr(teacher, "max_lessons_per_day", default_max_lessons_per_teacher_per_day)
                        )
                        if teacher_daily_load[(teacher.id, day)] >= teacher_daily_limit:
                            continue

                        class_busy[(class_obj.id, slot)] = True
                        teacher_busy[(teacher.id, slot)] = True
                        class_daily_load[(class_obj.id, day)] += 1
                        teacher_daily_load[(teacher.id, day)] += 1
                        class_subject_day_count[(class_obj.id, subject_name, day)] += 1
                        assignments.append(
                            {
                                "slot": slot,
                                "class": class_obj.name,
                                "subject": subject_name,
                                "teacher": teacher.name,
                            }
                        )

                        if backtrack(index + 1):
                            return True

                        assignments.pop()
                        class_busy.pop((class_obj.id, slot), None)
                        teacher_busy.pop((teacher.id, slot), None)
                        class_daily_load[(class_obj.id, day)] -= 1
                        teacher_daily_load[(teacher.id, day)] -= 1
                        class_subject_day_count[(class_obj.id, subject_name, day)] -= 1

                return False

            if backtrack(0):
                candidate_score = schedule_score(assignments)
                if best_score is None or candidate_score > best_score:
                    best_score = candidate_score
                    best_assignments = list(assignments)

        if not best_assignments:
            return ScheduleResult(
                False,
                (
                    "Cannot generate schedule: constraints conflict. "
                    "Check teacher unavailable slots, daily max lessons per class/teacher, "
                    "or reduce weekly subject hours."
                ),
                {},
            )

        return ScheduleResult(True, "Schedule generated successfully.", build_schedule(best_assignments))
