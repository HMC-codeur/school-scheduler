from datetime import datetime, timedelta
from typing import Dict, List

from backend.models.schemas import Class, Condition, ConditionCreate, ScheduleCell, Subject, Teacher, TimeSettings


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, ScheduleCell]] = {}
        self.conditions: List[Condition] = []
        self.time_settings: TimeSettings | None = None
        self._class_id = 1
        self._teacher_id = 1
        self._condition_id = 1

    def clear_all(self) -> None:
        self.classes = []
        self.teachers = []
        self.subjects = []
        self.slots = []
        self.schedule = {}
        self.conditions = []
        self.time_settings = None
        self._class_id = 1
        self._teacher_id = 1
        self._condition_id = 1

    def load_demo_data(self) -> None:
        self.clear_all()
        self.add_class("Grade 7A", max_lessons_per_day=5)
        self.add_class("Grade 8B", max_lessons_per_day=5)
        self.add_class("Grade 9C", max_lessons_per_day=6)

        self.add_subject("Math", 3)
        self.add_subject("Science", 2)
        self.add_subject("English", 2)
        self.add_subject("History", 1)

        self.add_teacher("Mr. Khan", ["Math", "Science"], ["Mon-09:00", "Thu-09:00"], max_lessons_per_day=4)
        self.add_teacher("Ms. Lee", ["English", "History"], ["Tue-08:00"], max_lessons_per_day=4)
        self.add_teacher("Mrs. Patel", ["Math", "History"], ["Fri-10:00"], max_lessons_per_day=5)
        self.add_teacher("Mr. Gomez", ["Science", "English"], ["Wed-08:00", "Fri-09:00"], max_lessons_per_day=4)

        for slot in [
            "Mon-08:00", "Mon-09:00", "Tue-08:00", "Tue-09:00", "Wed-08:00",
            "Wed-09:00", "Thu-08:00", "Thu-09:00", "Fri-08:00", "Fri-09:00", "Fri-10:00",
        ]:
            self.add_slot(slot)

    def add_class(self, name: str, max_lessons_per_day: int = 6) -> Class:
        item = Class(id=self._class_id, name=name, max_lessons_per_day=max_lessons_per_day)
        self._class_id += 1
        self.classes.append(item)
        return item

    def add_teacher(
        self,
        name: str,
        subjects: list[str],
        unavailable_slots: list[str] | None = None,
        max_lessons_per_day: int = 6,
    ) -> Teacher:
        item = Teacher(
            id=self._teacher_id,
            name=name,
            subjects=subjects,
            unavailable_slots=unavailable_slots or [],
            max_lessons_per_day=max_lessons_per_day,
        )
        self._teacher_id += 1
        self.teachers.append(item)
        return item

    def add_subject(self, name: str, hours_per_week: int) -> Subject:
        existing = next((s for s in self.subjects if s.name == name), None)
        if existing:
            raise ValueError(f"Subject '{name}' already exists")
        item = Subject(name=name, hours_per_week=hours_per_week)
        self.subjects.append(item)
        return item

    def add_slot(self, slot: str) -> str:
        if slot in self.slots:
            raise ValueError(f"Slot '{slot}' already exists")
        self.slots.append(slot)
        return slot

    def add_condition(self, payload: ConditionCreate) -> Condition:
        item = Condition(id=self._condition_id, **payload.model_dump())
        self._condition_id += 1
        self.conditions.append(item)
        return item

    def delete_condition(self, condition_id: int) -> bool:
        initial = len(self.conditions)
        self.conditions = [condition for condition in self.conditions if condition.id != condition_id]
        return len(self.conditions) < initial

    def set_time_settings(self, settings: TimeSettings) -> list[str]:
        self.time_settings = settings
        generated_slots = self.generate_slots_from_time_settings(settings)
        self.slots = generated_slots
        return generated_slots

    def generate_slots_from_time_settings(self, settings: TimeSettings) -> list[str]:
        start = datetime.strptime(settings.day_start_time, "%H:%M")
        end = datetime.strptime(settings.day_end_time, "%H:%M")
        if end <= start:
            raise ValueError("End time must be after start time")

        lunch_start = datetime.strptime(settings.lunch_break_start, "%H:%M") if settings.lunch_break_start else None
        lunch_end = datetime.strptime(settings.lunch_break_end, "%H:%M") if settings.lunch_break_end else None
        if (lunch_start and not lunch_end) or (lunch_end and not lunch_start):
            raise ValueError("Lunch break start and end must both be provided")
        if lunch_start and lunch_end and lunch_end <= lunch_start:
            raise ValueError("Lunch break end must be after lunch break start")

        lesson_delta = timedelta(minutes=settings.lesson_duration_minutes)
        break_delta = timedelta(minutes=settings.break_duration_minutes)

        slots: list[str] = []
        for day in settings.working_days:
            current = start
            while current + lesson_delta <= end:
                lesson_start = current
                lesson_end = current + lesson_delta
                if lunch_start and lunch_end and lesson_start < lunch_end and lesson_end > lunch_start:
                    current = lunch_end
                    continue
                slots.append(f"{day}-{lesson_start.strftime('%H:%M')}")
                current = lesson_end + break_delta
        return slots


store = MemoryStore()
