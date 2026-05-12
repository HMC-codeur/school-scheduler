from typing import Dict, List

from backend.models.schemas import Class, ScheduleCell, Subject, Teacher


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, ScheduleCell]] = {}
        self._class_id = 1
        self._teacher_id = 1

    def clear_all(self) -> None:
        self.classes = []
        self.teachers = []
        self.subjects = []
        self.slots = []
        self.schedule = {}
        self._class_id = 1
        self._teacher_id = 1

    def load_demo_data(self) -> None:
        self.clear_all()
        for class_name in ["Grade 7A", "Grade 8B", "Grade 9C"]:
            self.add_class(class_name)

        self.add_subject("Math", 3)
        self.add_subject("Science", 2)
        self.add_subject("English", 2)
        self.add_subject("History", 1)

        self.add_teacher("Mr. Khan", ["Math", "Science"])
        self.add_teacher("Ms. Lee", ["English", "History"])
        self.add_teacher("Mrs. Patel", ["Math", "History"])
        self.add_teacher("Mr. Gomez", ["Science", "English"])

        for slot in [
            "Mon-08:00", "Mon-09:00", "Tue-08:00", "Tue-09:00", "Wed-08:00",
            "Wed-09:00", "Thu-08:00", "Thu-09:00", "Fri-08:00", "Fri-09:00", "Fri-10:00",
        ]:
            self.add_slot(slot)

    def add_class(self, name: str) -> Class:
        item = Class(id=self._class_id, name=name)
        self._class_id += 1
        self.classes.append(item)
        return item

    def add_teacher(self, name: str, subjects: list[str]) -> Teacher:
        item = Teacher(id=self._teacher_id, name=name, subjects=subjects)
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


store = MemoryStore()
