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

        for teacher in teachers:
            available_slots = [slot for slot in slots if slot not in set(teacher.unavailable_slots)]
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

        sessions.sort(key=lambda x: len(teachers_by_subject.get(x[1], [])))

        teacher_busy: dict[tuple[int, str], bool] = {}
        class_busy: dict[tuple[int, str], bool] = {}
        class_daily_load: dict[tuple[int, str], int] = defaultdict(int)
        teacher_daily_load: dict[tuple[int, str], int] = defaultdict(int)
        class_subject_day_count: dict[tuple[int, str, str], int] = defaultdict(int)
        assignments: list[dict[str, str]] = []

        teacher_unavailable = {t.id: set(t.unavailable_slots) for t in teachers}

        def slot_score(class_id: int, subject_name: str, slot: str) -> tuple[int, int, int]:
            day = day_of(slot)
            same_day_subject_count = class_subject_day_count[(class_id, subject_name, day)]
            daily_load = class_daily_load[(class_id, day)]
            return (same_day_subject_count, daily_load, slots.index(slot))

        def backtrack(index: int) -> bool:
            if index == len(sessions):
                return True

            class_obj, subject_name = sessions[index]
            valid_teachers = teachers_by_subject[subject_name]

            candidate_slots = sorted(slots, key=lambda s: slot_score(class_obj.id, subject_name, s))

            for slot in candidate_slots:
                day = day_of(slot)
                if class_busy.get((class_obj.id, slot)):
                    continue
                class_daily_limit = max(1, getattr(class_obj, "max_lessons_per_day", default_max_lessons_per_class_per_day))
                if class_daily_load[(class_obj.id, day)] >= class_daily_limit:
                    continue

                for teacher in valid_teachers:
                    if slot in teacher_unavailable[teacher.id]:
                        continue
                    if teacher_busy.get((teacher.id, slot)):
                        continue
                    teacher_daily_limit = max(1, getattr(teacher, "max_lessons_per_day", default_max_lessons_per_teacher_per_day))
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

        if not backtrack(0):
            return ScheduleResult(
                False,
                (
                    "Cannot generate schedule: constraints conflict. "
                    "Check teacher unavailable slots, daily max lessons per class/teacher, "
                    "or reduce weekly subject hours."
                ),
                {},
            )

        schedule: dict[str, dict[str, ScheduleCell]] = defaultdict(dict)
        for item in assignments:
            schedule[item["slot"]][item["class"]] = ScheduleCell(
                subject=item["subject"],
                teacher=item["teacher"],
            )
        return ScheduleResult(True, "Schedule generated successfully.", dict(schedule))
