from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter

from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher


@dataclass
class ScheduleResult:
    success: bool
    message: str
    schedule: dict[str, dict[str, ScheduleCell]]
    quality_score: int | None = None
    conflicts_count: int | None = None
    gaps_count: int | None = None
    repeated_subjects_count: int | None = None
    long_sequences_count: int | None = None
    load_balance_status: str | None = None
    required_sessions: int | None = None
    scheduled_sessions: int | None = None
    generation_time_ms: int | None = None


class SchedulerService:
    @staticmethod
    def generate(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        default_max_lessons_per_class_per_day: int = 6,
        default_max_lessons_per_teacher_per_day: int = 6,
    ) -> ScheduleResult:
        started_at = perf_counter()
        if not classes:
            return ScheduleResult(False, "Cannot generate schedule: no classes added.", {})
        if not teachers:
            return ScheduleResult(False, "Cannot generate schedule: no teachers added.", {})
        if not subjects:
            return ScheduleResult(False, "Cannot generate schedule: no subjects added.", {})
        if not slots:
            return ScheduleResult(False, "Cannot generate schedule: no time slots added.", {})

        conditions = conditions or []

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

        teacher_by_name = {t.name: t for t in teachers}
        class_by_name = {c.name: c for c in classes}

        forced_teacher_unavailable: dict[int, set[str]] = defaultdict(set)
        class_unavailable_slots: dict[int, set[str]] = defaultdict(set)
        morning_subjects: set[str] = set()
        avoid_repeat_subject_scopes: dict[str, set[int] | None] = {}

        for condition in conditions:
            if condition.condition_type == "teacher_unavailable" and condition.teacher_name and condition.slot:
                teacher = teacher_by_name.get(condition.teacher_name)
                if teacher:
                    forced_teacher_unavailable[teacher.id].add(condition.slot)
            elif condition.condition_type == "class_unavailable" and condition.class_name and condition.slot:
                class_obj = class_by_name.get(condition.class_name)
                if class_obj:
                    class_unavailable_slots[class_obj.id].add(condition.slot)
            elif condition.condition_type == "subject_morning_preference" and condition.subject_name:
                morning_subjects.add(condition.subject_name)
            elif condition.condition_type == "avoid_subject_repeat" and condition.subject_name:
                if condition.class_name:
                    class_obj = class_by_name.get(condition.class_name)
                    if class_obj:
                        avoid_repeat_subject_scopes[condition.subject_name] = {class_obj.id}
                else:
                    avoid_repeat_subject_scopes[condition.subject_name] = None

        teacher_unavailable = {t.id: set(t.unavailable_slots) | forced_teacher_unavailable.get(t.id, set()) for t in teachers}

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

        def evaluate_quality(assignments: list[dict[str, str]]) -> dict[str, int | str]:
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

            score = 100
            conflicts_count = 0
            gaps_count = 0
            repeated_subjects_count = 0
            long_sequences_count = 0

            # Heavy penalty for any conflict (should be zero in normal cases).
            for count in teacher_slot_use.values():
                if count > 1:
                    overbookings = count - 1
                    conflicts_count += overbookings
                    score -= 50 * overbookings

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
                        gaps_count += holes
                        score -= holes * 6

                    # Penalize many repeated subjects on same day.
                    subject_count = defaultdict(int)
                    for subject_name in subjects_in_day:
                        subject_count[subject_name] += 1
                    for repeated in subject_count.values():
                        if repeated > 1:
                            repeated_subjects_count += repeated - 1
                            score -= (repeated - 1) * 4

                    # Penalize long streaks of consecutive classes.
                    streak = 1
                    for idx in range(1, len(positions)):
                        if positions[idx] == positions[idx - 1] + 1:
                            streak += 1
                            if streak > 2:
                                long_sequences_count += 1
                                score -= 3
                        else:
                            streak = 1

                # Reward balanced load across days (small variance).
                avg = sum(per_day_load) / len(per_day_load)
                imbalance = sum(abs(v - avg) for v in per_day_load)
                score -= int(imbalance * 2)

            max_imbalance = max(sum(subject_hours.values()) for _ in classes)
            load_balance_status = "good" if score >= 75 else "average" if score >= 50 else "bad"
            if max_imbalance > 0 and score >= 85 and conflicts_count == 0 and gaps_count <= 2:
                load_balance_status = "good"

            return {
                "quality_score": max(0, min(100, score)),
                "conflicts_count": conflicts_count,
                "gaps_count": gaps_count,
                "repeated_subjects_count": repeated_subjects_count,
                "long_sequences_count": long_sequences_count,
                "load_balance_status": load_balance_status,
            }

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
        best_quality_metrics: dict[str, int | str] | None = None

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

            def slot_priority(class_id: int, subject_name: str, slot: str) -> tuple[int, int, int, int, int]:
                day = day_of(slot)
                same_day_subject_count = class_subject_day_count[(class_id, subject_name, day)]
                if subject_name in avoid_repeat_subject_scopes:
                    scope = avoid_repeat_subject_scopes[subject_name]
                    if scope is None or class_id in scope:
                        same_day_subject_count += 2
                daily_load = class_daily_load[(class_id, day)]
                # morning preference: before 12:00 if possible
                time_part = slot.split("-", 1)[1] if "-" in slot else "23:59"
                is_afternoon_penalty = 0
                if subject_name in morning_subjects and time_part >= "12:00":
                    is_afternoon_penalty = 2
                middle_distance = abs(slot_order[slot] - (len(slots) // 2))
                return (same_day_subject_count, is_afternoon_penalty, daily_load, middle_distance, slot_order[slot])

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
                    if slot in class_unavailable_slots.get(class_obj.id, set()):
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
                quality_metrics = evaluate_quality(assignments)
                candidate_score = int(quality_metrics["quality_score"])
                if best_score is None or candidate_score > best_score:
                    best_score = candidate_score
                    best_assignments = list(assignments)
                    best_quality_metrics = quality_metrics

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

        return ScheduleResult(
            True,
            "Schedule generated successfully.",
            build_schedule(best_assignments),
            quality_score=int(best_quality_metrics["quality_score"]),
            conflicts_count=int(best_quality_metrics["conflicts_count"]),
            gaps_count=int(best_quality_metrics["gaps_count"]),
            repeated_subjects_count=int(best_quality_metrics["repeated_subjects_count"]),
            long_sequences_count=int(best_quality_metrics["long_sequences_count"]),
            load_balance_status=str(best_quality_metrics["load_balance_status"]),
        )
