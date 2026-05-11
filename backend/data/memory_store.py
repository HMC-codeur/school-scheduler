from typing import Dict, List

from backend.models.schemas import Class, Subject, Teacher


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, str]] = {}
        self._class_id = 1
        self._teacher_id = 1

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
