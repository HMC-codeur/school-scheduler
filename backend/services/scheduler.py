from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import random
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
    score_breakdown: list[dict[str, int | str]] | None = None
    required_sessions: int | None = None
    scheduled_sessions: int | None = None
    generation_time_ms: int | None = None


class SchedulerService:
    STRATEGY_BALANCED = "balanced"
    STRATEGY_AVOID_REPEATS = "avoid_repeats"
    STRATEGY_CONTINUOUS = "continuous"

    @staticmethod
    def _schedule_signature(schedule: dict[str, dict[str, ScheduleCell]]) -> str:
        normalized = {
            slot: {class_name: cell.model_dump() for class_name, cell in entries.items()}
            for slot, entries in schedule.items()
        }
        payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]

    @staticmethod
    def _build_option_description(metrics: dict) -> str:
        return (
            f"Score {metrics.get('quality_score', '--')}/100 · "
            f"conflits {metrics.get('conflicts_count', 0)} · "
            f"trous {metrics.get('gaps_count', 0)} · "
            f"répétitions {metrics.get('repeated_subjects_count', 0)} · "
            f"séquences longues {metrics.get('long_sequences_count', 0)} · "
            f"équilibrage {metrics.get('load_balance_status', '-')}"
        )

    @staticmethod
    def generate(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        strategy: str = STRATEGY_BALANCED,
        default_max_lessons_per_class_per_day: int = 6,
        default_max_lessons_per_teacher_per_day: int = 6,
    ) -> ScheduleResult:
        started_at = perf_counter()
        if not classes:
            return ScheduleResult(
                False,
                "Cannot generate schedule: no classes added.",
                {},
                required_sessions=0,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )
        if not teachers:
            return ScheduleResult(
                False,
                "Cannot generate schedule: no teachers added.",
                {},
                required_sessions=0,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )
        if not subjects:
            return ScheduleResult(
                False,
                "Cannot generate schedule: no subjects added.",
                {},
                required_sessions=0,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )
        if not slots:
            return ScheduleResult(
                False,
                "Cannot generate schedule: no time slots added.",
                {},
                required_sessions=0,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )

        conditions = conditions or []

        def day_of(slot: str) -> str:
            return slot.split("-", 1)[0]

        # We keep the original slot order so existing callers still receive
        # the same slot keys format and deterministic behavior.
        slot_order = {slot: idx for idx, slot in enumerate(slots)}
        days = sorted({day_of(s) for s in slots})
        if not days:
            return ScheduleResult(
                False,
                "Cannot generate schedule: no valid day information in slots.",
                {},
                required_sessions=0,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
            )

        subject_hours = {s.name: s.hours_per_week for s in subjects}
        total_required_sessions = len(classes) * sum(subject_hours.values())
        total_available_sessions = len(classes) * len(slots)
        if total_required_sessions > total_available_sessions:
            return ScheduleResult(
                False,
                "Cannot generate schedule: not enough slots for all required subject hours.",
                {},
                required_sessions=total_required_sessions,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
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
                    required_sessions=total_required_sessions,
                    scheduled_sessions=0,
                    generation_time_ms=int((perf_counter() - started_at) * 1000),
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
                    required_sessions=total_required_sessions,
                    scheduled_sessions=0,
                    generation_time_ms=int((perf_counter() - started_at) * 1000),
                )

        teacher_by_name = {t.name: t for t in teachers}
        class_by_name = {c.name: c for c in classes}

        forced_teacher_unavailable: dict[int, set[str]] = defaultdict(set)
        class_unavailable_slots: dict[int, set[str]] = defaultdict(set)
        morning_subjects: set[str] = set()
        morning_teachers: set[str] = set()
        avoid_repeat_subject_scopes: dict[str, set[int] | None] = {}
        avoid_long_sequence_requested = False

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
            elif condition.condition_type == "teacher_prefer_morning" and condition.teacher_name:
                morning_teachers.add(condition.teacher_name)
            elif condition.condition_type == "avoid_subject_repeat" and condition.subject_name:
                if condition.class_name:
                    class_obj = class_by_name.get(condition.class_name)
                    if class_obj:
                        avoid_repeat_subject_scopes[condition.subject_name] = {class_obj.id}
                else:
                    avoid_repeat_subject_scopes[condition.subject_name] = None
            elif condition.condition_type == "avoid_long_sequence":
                avoid_long_sequence_requested = True

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
                    required_sessions=total_required_sessions,
                    scheduled_sessions=0,
                    generation_time_ms=int((perf_counter() - started_at) * 1000),
                )

        for class_obj in classes:
            blocked = class_unavailable_slots.get(class_obj.id, set())
            available_capacity = len([slot for slot in slots if slot not in blocked])
            if available_capacity < weekly_hours_per_class:
                return ScheduleResult(
                    False,
                    (
                        f"Cannot generate schedule: class '{class_obj.name}' has not enough available slots "
                        f"({weekly_hours_per_class} required, {available_capacity} available)."
                    ),
                    {},
                    required_sessions=total_required_sessions,
                    scheduled_sessions=0,
                    generation_time_ms=int((perf_counter() - started_at) * 1000),
                )

        sessions: list[tuple[Class, str]] = []
        for class_obj in classes:
            for subject_name, hours in subject_hours.items():
                sessions.extend((class_obj, subject_name) for _ in range(hours))

        def evaluate_quality(assignments: list[dict[str, str]]) -> dict[str, int | str]:
            class_by_name = {c.name: c for c in classes}
            teacher_by_name = {t.name: t for t in teachers}
            slot_to_day = {slot: day_of(slot) for slot in slots}
            slots_per_day: dict[str, list[str]] = defaultdict(list)
            for slot in slots:
                slots_per_day[slot_to_day[slot]].append(slot)

            class_day_slots: dict[tuple[str, str], set[str]] = defaultdict(set)
            class_day_subjects: dict[tuple[str, str], list[str]] = defaultdict(list)
            teacher_day_slots: dict[tuple[str, str], set[str]] = defaultdict(set)
            teacher_slot_use: dict[tuple[str, str], list[str]] = defaultdict(list)
            class_slot_use: dict[tuple[str, str], int] = defaultdict(int)
            score_breakdown: list[dict[str, int | str]] = []

            for item in assignments:
                day = slot_to_day[item["slot"]]
                class_day_slots[(item["class"], day)].add(item["slot"])
                class_day_subjects[(item["class"], day)].append(item["subject"])
                teacher_day_slots[(item["teacher"], day)].add(item["slot"])
                teacher_slot_use[(item["teacher"], item["slot"])].append(item["class"])
                class_slot_use[(item["class"], item["slot"])] += 1

            score = 100
            conflicts_count = 0
            gaps_count = 0
            repeated_subjects_count = 0
            long_sequences_count = 0
            teacher_long_sequences_count = 0

            def add_rule(rule: str, label: str, points: int) -> None:
                nonlocal score
                score += points
                score_breakdown.append({"rule": rule, "label": label, "points": points})

            def has_long_sequence(positions: list[int], threshold: int = 5) -> bool:
                streak = 1
                for idx in range(1, len(positions)):
                    if positions[idx] == positions[idx - 1] + 1:
                        streak += 1
                    else:
                        streak = 1
                    if streak >= threshold:
                        return True
                return False

            for (teacher_name, slot), class_names in teacher_slot_use.items():
                if len(class_names) > 1:
                    conflicts_count += 1
                    add_rule("teacher_conflict", f"Le professeur {teacher_name} est utilisé dans plusieurs classes sur le créneau {slot}", -100)

            for (class_name, slot), count in class_slot_use.items():
                if count > 1:
                    conflicts_count += 1
                    add_rule("class_conflict", f"La classe {class_name} a plusieurs cours sur le créneau {slot}", -100)

            for item in assignments:
                teacher = teacher_by_name.get(item["teacher"])
                if teacher and item["subject"] not in teacher.subjects:
                    add_rule("teacher_subject_incompatible", f"Le professeur {teacher.name} est affecté à une matière non compatible ({item['subject']})", -80)
                if teacher and item["slot"] in teacher_unavailable.get(teacher.id, set()):
                    add_rule("teacher_unavailable_slot", f"Le professeur {teacher.name} est placé sur un créneau indisponible ({item['slot']})", -70)
                class_obj = class_by_name.get(item["class"])
                if class_obj and item["slot"] in class_unavailable_slots.get(class_obj.id, set()):
                    add_rule("class_unavailable_slot", f"La classe {class_obj.name} est placée sur un créneau indisponible ({item['slot']})", -70)

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
                        if holes > 0:
                            gaps_count += holes
                            for _ in range(holes):
                                add_rule("class_gap", f"Trou détecté pour la classe {class_obj.name} le {day}", -3)

                    # Penalize many repeated subjects on same day.
                    subject_count = defaultdict(int)
                    for subject_name in subjects_in_day:
                        subject_count[subject_name] += 1
                    for repeated in subject_count.values():
                        if repeated > 1:
                            excess = repeated - 1
                            repeated_subjects_count += excess
                            add_rule("avoid_subject_repeat_same_day", f"Matière répétée plusieurs fois pour la classe {class_obj.name} le {day}", -8 * excess)

                    # Penalize long streaks of consecutive classes.
                    if has_long_sequence(positions, threshold=5):
                        long_sequences_count += 1
                        rule_id = "avoid_long_sequence" if avoid_long_sequence_requested else "class_long_sequence"
                        add_rule(rule_id, f"Série longue (>4 cours consécutifs) détectée pour la classe {class_obj.name} le {day}", -6)

            teacher_loads: list[int] = []
            for teacher in teachers:
                teacher_load = 0
                for day in days:
                    used_slots = teacher_day_slots[(teacher.name, day)]
                    teacher_load += len(used_slots)
                    ordered_slots = sorted(used_slots, key=lambda s: slot_order[s])
                    positions = [slot_order[s] for s in ordered_slots]
                    if positions:
                        span = positions[-1] - positions[0] + 1
                        holes = span - len(positions)
                        if holes > 0:
                            gaps_count += holes
                            for _ in range(holes):
                                add_rule("teacher_gap", f"Trou détecté pour le professeur {teacher.name} le {day}", -2)
                    if has_long_sequence(positions, threshold=5):
                        teacher_long_sequences_count += 1
                        rule_id = "avoid_long_sequence" if avoid_long_sequence_requested else "teacher_long_sequence"
                        add_rule(rule_id, f"Série longue (>4 cours consécutifs) détectée pour le professeur {teacher.name} le {day}", -6)
                teacher_loads.append(teacher_load)

            long_sequences_count += teacher_long_sequences_count

            morning_subjects_in_conditions = {c.subject_name for c in (conditions or []) if c.condition_type == "subject_morning_preference" and c.subject_name}
            for item in assignments:
                if item["subject"] in morning_subjects_in_conditions:
                    time_part = item["slot"].split("-", 1)[1] if "-" in item["slot"] else "23:59"
                    if time_part < "12:00":
                        add_rule("subject_morning_preference", f"{item['subject']} placée le matin", 3)
                        break
            for teacher_name in morning_teachers:
                teacher_slots = [a["slot"] for a in assignments if a["teacher"] == teacher_name]
                if not teacher_slots:
                    continue
                if any((s.split("-", 1)[1] if "-" in s else "23:59") < "12:00" for s in teacher_slots):
                    add_rule("teacher_morning_preference", f"Le professeur {teacher_name} enseigne le matin comme préféré", 3)

            class_loads = [sum(len(class_day_slots[(class_obj.name, day)]) for day in days) for class_obj in classes]
            if class_loads and max(class_loads) - min(class_loads) <= 2:
                add_rule("class_load_balance", "Charge des classes bien équilibrée", 5)
            if teacher_loads and max(teacher_loads) - min(teacher_loads) <= 2:
                add_rule("teacher_load_balance", "Charge des professeurs bien équilibrée", 5)
            if class_loads and teacher_loads and (max(class_loads) - min(class_loads) <= 2) and (max(teacher_loads) - min(teacher_loads) <= 2):
                add_rule("global_distribution", "Bonne répartition globale du planning", 5)

            bounded_score = max(0, min(100, score))
            load_balance_status = "good" if bounded_score >= 75 else "average" if bounded_score >= 50 else "bad"

            return {
                "quality_score": bounded_score,
                "conflicts_count": conflicts_count,
                "gaps_count": gaps_count,
                "repeated_subjects_count": repeated_subjects_count,
                "long_sequences_count": long_sequences_count,
                "load_balance_status": load_balance_status,
                "score_breakdown": score_breakdown,
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
            strategy_attempt = (attempt + (0 if strategy == SchedulerService.STRATEGY_BALANCED else 1 if strategy == SchedulerService.STRATEGY_AVOID_REPEATS else 2)) % 3
            if strategy_attempt == 0:
                ordered_sessions = sorted(sessions, key=lambda x: len(teachers_by_subject.get(x[1], [])))
            elif strategy_attempt == 1:
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
                continuity_hint = middle_distance if strategy == SchedulerService.STRATEGY_CONTINUOUS else 0
                repeat_hint = same_day_subject_count if strategy == SchedulerService.STRATEGY_AVOID_REPEATS else 0
                return (same_day_subject_count + repeat_hint, is_afternoon_penalty, daily_load, continuity_hint, middle_distance, slot_order[slot])

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
            impossible_reasons: list[str] = []
            if len(slots) < weekly_hours_per_class:
                impossible_reasons.append("pas assez de créneaux")

            missing_teachers = [subject_name for subject_name in subject_hours if not teachers_by_subject.get(subject_name)]
            if missing_teachers:
                impossible_reasons.append("aucun professeur compatible")

            strict_constraints = len(forced_teacher_unavailable) + len(class_unavailable_slots)
            if strict_constraints > len(slots):
                impossible_reasons.append("trop de contraintes")

            heavily_blocked_teachers = []
            for teacher in teachers:
                blocked_count = len(teacher_unavailable.get(teacher.id, set()))
                if blocked_count >= max(1, int(len(slots) * 0.7)):
                    heavily_blocked_teachers.append(teacher.name)
            if heavily_blocked_teachers:
                impossible_reasons.append("prof indisponible sur trop de créneaux")

            for class_obj in classes:
                available = len([slot for slot in slots if slot not in class_unavailable_slots.get(class_obj.id, set())])
                if available < weekly_hours_per_class:
                    impossible_reasons.append("volume demandé impossible")
                    break

            reason_text = ", ".join(dict.fromkeys(impossible_reasons)) or (
                "constraints conflict. Check teacher unavailable slots, class unavailable slots, "
                "daily max lessons per class/teacher, or reduce weekly subject hours"
            )
            return ScheduleResult(
                False,
                f"Cannot generate schedule: {reason_text}.",
                {},
                required_sessions=total_required_sessions,
                scheduled_sessions=0,
                generation_time_ms=int((perf_counter() - started_at) * 1000),
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
            score_breakdown=list(best_quality_metrics.get("score_breakdown", [])),
            required_sessions=total_required_sessions,
            scheduled_sessions=len(best_assignments),
            generation_time_ms=int((perf_counter() - started_at) * 1000),
        )

    @staticmethod
    def generate_options(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
    ) -> list[dict]:
        option_defs = [
            (SchedulerService.STRATEGY_BALANCED, "option-1", "Option 1", 1),
            (SchedulerService.STRATEGY_AVOID_REPEATS, "option-2", "Option 2", 2),
            (SchedulerService.STRATEGY_CONTINUOUS, "option-3", "Option 3", 3),
        ]
        options: list[dict] = []
        for strategy, option_id, label, seed in option_defs:
            rng = random.Random(seed)
            shuffled_classes = list(classes)
            shuffled_subjects = list(subjects)
            shuffled_slots = list(slots)
            shuffled_teachers = []
            rng.shuffle(shuffled_classes)
            rng.shuffle(shuffled_subjects)
            rng.shuffle(shuffled_slots)
            for teacher in teachers:
                teacher_subjects = list(teacher.subjects)
                rng.shuffle(teacher_subjects)
                shuffled_teachers.append(teacher.model_copy(update={"subjects": teacher_subjects}))
            rng.shuffle(shuffled_teachers)

            result = SchedulerService.generate(
                shuffled_classes, shuffled_teachers, shuffled_subjects, shuffled_slots, conditions, strategy=strategy
            )
            if not result.success:
                continue
            metrics = {
                "quality_score": result.quality_score,
                "conflicts_count": result.conflicts_count,
                "gaps_count": result.gaps_count,
                "repeated_subjects_count": result.repeated_subjects_count,
                "long_sequences_count": result.long_sequences_count,
                "load_balance_status": result.load_balance_status,
            }
            options.append(
                {
                    "id": option_id,
                    "label": label,
                    "schedule": result.schedule,
                    **metrics,
                    "score_breakdown": result.score_breakdown or [],
                    "description": SchedulerService._build_option_description(metrics),
                    "schedule_signature": SchedulerService._schedule_signature(result.schedule),
                    "message": result.message,
                }
            )
        signatures = {option["schedule_signature"] for option in options}
        if len(signatures) == 1 and options:
            for option in options:
                option["description"] = f"{option['description']} · Aucune variante différente trouvée avec les données actuelles."
        return options
