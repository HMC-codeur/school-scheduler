from typing import Dict, List

from backend.models.schemas import Class, Condition, ScheduleCell, Subject, Teacher


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, ScheduleCell]] = {}
        self.conditions: List[Condition] = []
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

    def add_condition(self, text: str) -> Condition:
        item = Condition(id=self._condition_id, text=text)
        self._condition_id += 1
        self.conditions.append(item)
        return item

    def delete_condition(self, condition_id: int) -> bool:
        initial = len(self.conditions)
        self.conditions = [condition for condition in self.conditions if condition.id != condition_id]
        return len(self.conditions) < initial


store = MemoryStore()
