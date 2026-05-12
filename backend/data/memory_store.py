import json
from pathlib import Path
from typing import Any

from backend.models.schemas import Class, ScheduleSession, Slot, Subject, Teacher

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class MemoryStore:
    def __init__(self) -> None:
        self.classes: list[Class] = []
        self.teachers: list[Teacher] = []
        self.subjects: list[Subject] = []
        self.slots: list[Slot] = []
        self.schedule: list[ScheduleSession] = []
        self._ids = {"class": 1, "teacher": 1, "subject": 1, "slot": 1, "session": 1}
        self.load_data()
        self.load_schedule()

    def _path(self, name: str) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR / f"{name}.json"

    def _read(self, name: str) -> Any:
        path = self._path(name)
        if not path.exists():
            path.write_text("[]", encoding="utf-8")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON corrompu: {path.name}") from exc

    def _write(self, name: str, data: Any) -> None:
        self._path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_data(self) -> None:
        self.classes = [Class(**x) for x in self._read("classes")]
        self.teachers = [Teacher(**x) for x in self._read("teachers")]
        self.subjects = [Subject(**x) for x in self._read("subjects")]
        self.slots = [Slot(**x) for x in self._read("slots")]
        self._rebuild_ids()

    def save_data(self) -> None:
        self._write("classes", [x.model_dump() for x in self.classes])
        self._write("teachers", [x.model_dump() for x in self.teachers])
        self._write("subjects", [x.model_dump() for x in self.subjects])
        self._write("slots", [x.model_dump() for x in self.slots])

    def load_schedule(self) -> None:
        self.schedule = [ScheduleSession(**x) for x in self._read("schedule")]
        self._rebuild_ids()

    def save_schedule(self) -> None:
        self._write("schedule", [x.model_dump() for x in self.schedule])

    def reset_data(self) -> None:
        self.classes, self.teachers, self.subjects, self.slots, self.schedule = [], [], [], [], []
        self._ids = {"class": 1, "teacher": 1, "subject": 1, "slot": 1, "session": 1}
        self.save_data(); self.save_schedule()

    def _rebuild_ids(self) -> None:
        self._ids["class"] = max([x.id for x in self.classes], default=0) + 1
        self._ids["teacher"] = max([x.id for x in self.teachers], default=0) + 1
        self._ids["subject"] = max([x.id for x in self.subjects], default=0) + 1
        self._ids["slot"] = max([x.id for x in self.slots], default=0) + 1
        self._ids["session"] = max([x.session_id for x in self.schedule], default=0) + 1


store = MemoryStore()
