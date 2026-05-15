from collections import defaultdict
from dataclasses import dataclass
import random
import sys
from time import perf_counter

from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher
from backend.services.scoring import build_schedule_option, rank_schedule_options


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
    def generate(
        classes: list[Class],
        teachers: list[Teacher],
        subjects: list[Subject],
        slots: list[str],
        conditions: list[Condition] | None = None,
        strategy: str = STRATEGY_BALANCED,
        default_max_lessons_per_class_per_day: int = 6,
        default_max_lessons_per_teacher_per_day: int = 6,
        generation_seed: int | None = None,
        quality_attempts: int = 5,
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

        # We keep the incoming slot order for returned keys and deterministic
        # behavior, and also maintain per-day positions for comfort heuristics.
        slot_order = {slot: idx for idx, slot in enumerate(slots)}
        slot_day = {slot: slot.split("-", 1)[0] for slot in slots}
        slot_time_part = {slot: (slot.split("-", 1)[1] if "-" in slot else "23:59") for slot in slots}
        day_slot_order: dict[str, dict[str, int]] = defaultdict(dict)
        slots_by_day: dict[str, list[str]] = defaultdict(list)
        for slot in slots:
            day = slot_day[slot]
            day_slot_order[day][slot] = len(slots_by_day[day])
            slots_by_day[day].append(slot)
        slot_day_position = {slot: day_slot_order[slot_day[slot]][slot] for slot in slots}
        slot_day_middle_distance = {
            slot: abs(slot_day_position[slot] - max(0, (len(slots_by_day[slot_day[slot]]) - 1) // 2))
            for slot in slots
        }
        days = sorted(set(slot_day.values()))

        def day_of(slot: str) -> str:
            return slot_day.get(slot, slot.split("-", 1)[0])
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
        sys.setrecursionlimit(max(sys.getrecursionlimit(), total_required_sessions + 200))
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
        class_daily_limits = {
            class_obj.id: max(1, getattr(class_obj, "max_lessons_per_day", default_max_lessons_per_class_per_day))
            for class_obj in classes
        }
        teacher_daily_limits = {
            teacher.id: max(1, getattr(teacher, "max_lessons_per_day", default_max_lessons_per_teacher_per_day))
            for teacher in teachers
        }

        def effective_class_capacity(class_obj: Class, blocked_slots: set[str] | None = None) -> int:
            blocked_slots = blocked_slots or set()
            daily_limit = class_daily_limits[class_obj.id]
            capacity = 0
            for day in days:
                available_in_day = sum(1 for slot in slots_by_day[day] if slot not in blocked_slots)
                capacity += min(daily_limit, available_in_day)
            return capacity

        for class_obj in classes:
            class_daily_limit = class_daily_limits[class_obj.id]
            class_weekly_capacity = effective_class_capacity(class_obj)
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
        rng = random.Random(generation_seed if generation_seed is not None else 0)
        class_tiebreak = {class_obj.id: idx for idx, class_obj in enumerate(rng.sample(classes, k=len(classes)))}
        subject_tiebreak = {subject.name: idx for idx, subject in enumerate(rng.sample(subjects, k=len(subjects)))}
        teacher_tiebreak = {teacher.id: idx for idx, teacher in enumerate(rng.sample(teachers, k=len(teachers)))}
        slot_tiebreak = {slot: idx for idx, slot in enumerate(rng.sample(slots, k=len(slots)))}

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
        available_teachers_by_subject_slot: dict[tuple[str, str], list[Teacher]] = {}

        for teacher in teachers:
            available_slots = [slot for slot in slots if slot not in teacher_unavailable[teacher.id]]
            teacher_daily_limit = teacher_daily_limits[teacher.id]
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

        for subject_name, subject_teachers in teachers_by_subject.items():
            for slot in slots:
                available_teachers_by_subject_slot[(subject_name, slot)] = [
                    teacher for teacher in subject_teachers if slot not in teacher_unavailable[teacher.id]
                ]

        for class_obj in classes:
            blocked = class_unavailable_slots.get(class_obj.id, set())
            available_capacity = effective_class_capacity(class_obj, blocked)
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
            slots_per_day: dict[str, list[str]] = defaultdict(list)
            for slot in slots:
                slots_per_day[slot_day[slot]].append(slot)

            class_day_slots: dict[tuple[str, str], set[str]] = defaultdict(set)
            class_day_subjects: dict[tuple[str, str], list[str]] = defaultdict(list)
            teacher_day_slots: dict[tuple[str, str], set[str]] = defaultdict(set)
            teacher_slot_use: dict[tuple[str, str], list[str]] = defaultdict(list)
            class_slot_use: dict[tuple[str, str], int] = defaultdict(int)
            score_breakdown: list[dict[str, int | str]] = []

            for item in assignments:
                day = slot_day[item["slot"]]
                class_day_slots[(item["class"], day)].add(item["slot"])
                class_day_subjects[(item["class"], day)].append(item["subject"])
                teacher_day_slots[(item["teacher"], day)].add(item["slot"])
                teacher_slot_use[(item["teacher"], item["slot"])].append(item["class"])
                class_slot_use[(item["class"], item["slot"])] += 1

            raw_score = 100
            conflicts_count = 0
            gaps_count = 0
            repeated_subjects_count = 0
            long_sequences_count = 0
            teacher_long_sequences_count = 0

            comfort_penalty_caps = {
                "class_gap": -30,
                "teacher_gap": -25,
                "class_long_sequence": -30,
                "teacher_long_sequence": -20,
                "avoid_long_sequence": -40,
            }
            score_events: dict[tuple[str, str], dict[str, int | str]] = {}

            def add_rule(rule: str, label: str, points: int, count: int = 1) -> None:
                key = (rule, label)
                if key not in score_events:
                    score_events[key] = {"rule": rule, "label": label, "points": 0, "count": 0}
                score_events[key]["points"] = int(score_events[key]["points"]) + points
                score_events[key]["count"] = int(score_events[key]["count"]) + count

            def rule_category(rule: str, points: int) -> str:
                if rule in {"class_gap"}:
                    return "Trous classes"
                if rule in {"teacher_gap"}:
                    return "Trous professeurs"
                if "long_sequence" in rule:
                    return "Longues séries"
                if "conflict" in rule:
                    return "Conflits"
                if rule in {"unplaced_sessions"}:
                    return "Sessions non placées"
                if rule in {"subject_morning_preference", "teacher_morning_preference"}:
                    return "Préférences respectées"
                if points > 0:
                    return "Bonus"
                return "Autres pénalités"

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
                            add_rule(
                                "class_gap",
                                f"{holes} trou{'s' if holes > 1 else ''} détecté{'s' if holes > 1 else ''} pour la classe {class_obj.name} le {day}",
                                -3 * holes,
                                count=holes,
                            )

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
                            add_rule(
                                "teacher_gap",
                                f"{holes} trou{'s' if holes > 1 else ''} détecté{'s' if holes > 1 else ''} pour le professeur {teacher.name} le {day}",
                                -2 * holes,
                                count=holes,
                            )
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

            rule_totals: dict[str, int] = defaultdict(int)
            for event in score_events.values():
                rule_totals[str(event["rule"])] += int(event["points"])

            capped_rule_totals = dict(rule_totals)
            for rule, cap in comfort_penalty_caps.items():
                if capped_rule_totals.get(rule, 0) < cap:
                    capped_rule_totals[rule] = cap

            for event in score_events.values():
                rule = str(event["rule"])
                points = int(event["points"])
                rule_total = rule_totals.get(rule, 0)
                capped_total = capped_rule_totals.get(rule, rule_total)
                adjusted_points = points
                if points < 0 and rule_total < capped_total and rule_total != 0:
                    adjusted_points = round(points * capped_total / rule_total)
                item = {
                    "rule": rule,
                    "category": rule_category(rule, int(adjusted_points)),
                    "label": str(event["label"]),
                    "points": int(adjusted_points),
                    "raw_points": points,
                    "count": int(event["count"]),
                }
                if adjusted_points != points:
                    item["capped"] = "true"
                score_breakdown.append(item)

            raw_score += sum(int(item["points"]) for item in score_breakdown)
            bounded_score = max(0, min(100, raw_score))
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

        class_required_hours = {class_obj.id: sum(subject_hours.values()) for class_obj in classes}
        class_available_capacity = {
            class_obj.id: len([slot for slot in slots if slot not in class_unavailable_slots.get(class_obj.id, set())])
            for class_obj in classes
        }
        ideal_daily_load = max(1, (weekly_hours_per_class + max(1, len(days)) - 1) // max(1, len(days)))

        attempts_count = max(1, quality_attempts)
        for attempt in range(attempts_count):
            # Try multiple session orders and keep the best quality score.
            # This improves schedule quality while staying deterministic.
            strategy_attempt = (attempt + (0 if strategy == SchedulerService.STRATEGY_BALANCED else 1 if strategy == SchedulerService.STRATEGY_AVOID_REPEATS else 2)) % 5
            if strategy_attempt == 0:
                ordered_sessions = sorted(
                    sessions,
                    key=lambda x: (
                        len(teachers_by_subject.get(x[1], [])),
                        -subject_hours[x[1]],
                        class_available_capacity[x[0].id] - class_required_hours[x[0].id],
                        class_tiebreak[x[0].id],
                        subject_tiebreak[x[1]],
                    ),
                )
            elif strategy_attempt == 1:
                ordered_sessions = sorted(
                    sessions,
                    key=lambda x: (
                        -(class_required_hours[x[0].id]),
                        len(teachers_by_subject.get(x[1], [])),
                        class_tiebreak[x[0].id],
                        -subject_hours[x[1]],
                        subject_tiebreak[x[1]],
                    ),
                )
            elif strategy_attempt == 2:
                ordered_sessions = sorted(sessions, key=lambda x: (subject_tiebreak[x[1]], class_tiebreak[x[0].id]))
            elif strategy_attempt == 3:
                ordered_sessions = sorted(sessions, key=lambda x: (class_tiebreak[x[0].id], len(teachers_by_subject.get(x[1], [])), subject_tiebreak[x[1]]))
            else:
                ordered_sessions = sorted(sessions, key=lambda x: (-subject_hours[x[1]], subject_tiebreak[x[1]], class_tiebreak[x[0].id]))

            teacher_busy: dict[tuple[int, str], bool] = {}
            class_busy: dict[tuple[int, str], bool] = {}
            class_daily_load: dict[tuple[int, str], int] = defaultdict(int)
            teacher_daily_load: dict[tuple[int, str], int] = defaultdict(int)
            class_subject_day_count: dict[tuple[int, str, str], int] = defaultdict(int)
            class_day_positions: dict[tuple[int, str], set[int]] = defaultdict(set)
            teacher_day_positions: dict[tuple[int, str], set[int]] = defaultdict(set)
            assignments: list[dict[str, str]] = []

            def created_holes_after_add(positions: set[int], position: int) -> int:
                if not positions:
                    return 0
                min_position = min(positions)
                max_position = max(positions)
                if min_position < position < max_position:
                    return 0
                if position < min_position:
                    return max(0, min_position - position - 1)
                if position > max_position:
                    return max(0, position - max_position - 1)
                return 0

            def creates_long_streak(positions: set[int], position: int, threshold: int = 5) -> bool:
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

            def adjacent_to_existing(positions: set[int], position: int) -> bool:
                return (position - 1) in positions or (position + 1) in positions

            def slot_priority(class_id: int, subject_name: str, slot: str) -> tuple[int, int, int, int, int, int, int, int, int]:
                day = slot_day[slot]
                day_position = slot_day_position[slot]
                current_positions = class_day_positions[(class_id, day)]
                same_day_subject_count = class_subject_day_count[(class_id, subject_name, day)]
                if subject_name in avoid_repeat_subject_scopes:
                    scope = avoid_repeat_subject_scopes[subject_name]
                    if scope is None or class_id in scope:
                        same_day_subject_count += 2
                daily_load = class_daily_load[(class_id, day)]

                subject_spread_penalty = 0
                if subject_hours.get(subject_name, 0) > 1 and same_day_subject_count > 0:
                    subject_days_used = sum(
                        1 for candidate_day in days if class_subject_day_count[(class_id, subject_name, candidate_day)] > 0
                    )
                    if subject_days_used < min(subject_hours[subject_name], len(days)):
                        subject_spread_penalty = 3

                created_holes = created_holes_after_add(current_positions, day_position)
                isolation_penalty = 0
                if current_positions and not adjacent_to_existing(current_positions, day_position):
                    isolation_penalty = 2
                long_series_weight = 5 if strategy_attempt in {0, 1, 3} else 0
                long_series_penalty = long_series_weight if creates_long_streak(current_positions, day_position) else 0
                overloaded_day_penalty = 2 if daily_load >= ideal_daily_load else 0

                # morning preference: before 12:00 if possible
                is_afternoon_penalty = 0
                if subject_name in morning_subjects and slot_time_part[slot] >= "12:00":
                    is_afternoon_penalty = 2
                middle_distance = slot_day_middle_distance[slot]
                continuity_hint = created_holes + isolation_penalty if strategy == SchedulerService.STRATEGY_CONTINUOUS else 0
                repeat_hint = same_day_subject_count if strategy == SchedulerService.STRATEGY_AVOID_REPEATS else 0
                return (
                    overloaded_day_penalty,
                    same_day_subject_count + repeat_hint + subject_spread_penalty,
                    long_series_penalty,
                    created_holes if strategy_attempt != 4 else created_holes * 3,
                    isolation_penalty + continuity_hint if strategy_attempt != 4 else isolation_penalty * 2 + continuity_hint,
                    is_afternoon_penalty,
                    daily_load,
                    middle_distance,
                    slot_tiebreak[slot],
                )

            def teacher_slot_priority(teacher: Teacher, slot: str) -> tuple[int, int, int, int, int]:
                day = slot_day[slot]
                day_position = slot_day_position[slot]
                current_positions = teacher_day_positions[(teacher.id, day)]
                created_holes = created_holes_after_add(current_positions, day_position)
                isolation_penalty = 0
                if current_positions and not adjacent_to_existing(current_positions, day_position):
                    isolation_penalty = 2
                long_series_weight = 3 if strategy_attempt in {0, 1, 3} else 0
                long_series_penalty = long_series_weight if creates_long_streak(current_positions, day_position) else 0
                return (
                    long_series_penalty,
                    created_holes,
                    isolation_penalty,
                    teacher_daily_load[(teacher.id, day)],
                    teacher_tiebreak[teacher.id],
                )

            def backtrack(index: int) -> bool:
                if index == len(ordered_sessions):
                    return True

                class_obj, subject_name = ordered_sessions[index]
                valid_teachers = teachers_by_subject[subject_name]
                candidates: list[tuple[tuple, str, Teacher]] = []
                for slot in slots:
                    day = slot_day[slot]
                    if class_busy.get((class_obj.id, slot)):
                        continue
                    if slot in class_unavailable_slots.get(class_obj.id, set()):
                        continue

                    class_daily_limit = class_daily_limits[class_obj.id]
                    if class_daily_load[(class_obj.id, day)] >= class_daily_limit:
                        continue

                    base_slot_priority = slot_priority(class_obj.id, subject_name, slot)
                    for teacher in available_teachers_by_subject_slot[(subject_name, slot)]:
                        if teacher_busy.get((teacher.id, slot)):
                            continue

                        teacher_daily_limit = teacher_daily_limits[teacher.id]
                        if teacher_daily_load[(teacher.id, day)] >= teacher_daily_limit:
                            continue
                        candidates.append((base_slot_priority + teacher_slot_priority(teacher, slot), slot, teacher))

                candidates.sort(key=lambda item: item[0])
                for _priority, slot, teacher in candidates:
                    day = slot_day[slot]
                    class_busy[(class_obj.id, slot)] = True
                    teacher_busy[(teacher.id, slot)] = True
                    class_daily_load[(class_obj.id, day)] += 1
                    teacher_daily_load[(teacher.id, day)] += 1
                    class_subject_day_count[(class_obj.id, subject_name, day)] += 1
                    class_day_positions[(class_obj.id, day)].add(slot_day_position[slot])
                    teacher_day_positions[(teacher.id, day)].add(slot_day_position[slot])
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
                    class_day_positions[(class_obj.id, day)].discard(slot_day_position[slot])
                    teacher_day_positions[(teacher.id, day)].discard(slot_day_position[slot])

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
        strategies = [
            SchedulerService.STRATEGY_BALANCED,
            SchedulerService.STRATEGY_AVOID_REPEATS,
            SchedulerService.STRATEGY_CONTINUOUS,
        ]
        option_seeds = [0, 5, 16]
        option_defs = [(strategies[index % len(strategies)], seed) for index, seed in enumerate(option_seeds)]
        options: list[dict] = []
        for strategy, seed in option_defs:
            result = SchedulerService.generate(
                classes,
                teachers,
                subjects,
                slots,
                conditions,
                strategy=strategy,
                generation_seed=seed,
                quality_attempts=2,
            )
            if not result.success:
                continue
            option = build_schedule_option(
                option_id=f"option-{seed}",
                schedule=result.schedule,
                classes=classes,
                teachers=teachers,
                subjects=subjects,
                slots=slots,
                constraints=conditions,
            )
            option["message"] = result.message
            option["quality_score"] = int(result.quality_score or option.get("quality_score") or 0)
            option["score_breakdown"] = list(result.score_breakdown or [])
            option["conflicts_count"] = int(result.conflicts_count or 0)
            option["gaps_count"] = int(result.gaps_count or 0)
            option["repeated_subjects_count"] = int(result.repeated_subjects_count or 0)
            option["long_sequences_count"] = int(result.long_sequences_count or 0)
            option["load_balance_status"] = result.load_balance_status
            option["required_sessions"] = result.required_sessions
            option["scheduled_sessions"] = result.scheduled_sessions
            option["generation_time_ms"] = result.generation_time_ms
            options.append(option)
        return rank_schedule_options(options)[:3]
