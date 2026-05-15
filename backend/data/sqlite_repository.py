from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.data.db import get_database_path
from backend.data.memory_store import MemoryStore
from backend.models.schemas import Class, Condition, ConditionCreate, LearningGroup, LearningGroupCreate, ScheduleCell, Subject, Teacher, TimeSettings


DEFAULT_SCHOOL_NAME = "Local MVP School"


class SQLiteRepository(MemoryStore):
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_database_path()
        self.repair_proposals: dict[str, dict] = {}
        self.schedule_versions: list[dict] = []
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_default_school()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schools (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    time_settings_json TEXT,
                    selected_schedule_option_id TEXT
                );

                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    max_lessons_per_day INTEGER NOT NULL DEFAULT 6,
                    UNIQUE(school_id, name)
                );

                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    subjects_json TEXT NOT NULL DEFAULT '[]',
                    unavailable_slots_json TEXT NOT NULL DEFAULT '[]',
                    max_lessons_per_day INTEGER NOT NULL DEFAULT 6,
                    UNIQUE(school_id, name)
                );

                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    hours_per_week INTEGER NOT NULL,
                    UNIQUE(school_id, name)
                );

                CREATE TABLE IF NOT EXISTS learning_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                    class_name TEXT NOT NULL,
                    subject_name TEXT NOT NULL,
                    level TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    UNIQUE(school_id, display_name)
                );

                CREATE TABLE IF NOT EXISTS slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    slot TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    UNIQUE(school_id, slot)
                );

                CREATE TABLE IF NOT EXISTS conditions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schedule_entries (
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    slot TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    teacher TEXT NOT NULL,
                    PRIMARY KEY(school_id, slot, class_name)
                );

                CREATE TABLE IF NOT EXISTS schedule_options (
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    option_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(school_id, option_id)
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(schedule_entries)").fetchall()
            }
            if "session_id" not in columns:
                conn.execute("ALTER TABLE schedule_entries ADD COLUMN session_id TEXT")

    def _ensure_default_school(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO schools (id, name) VALUES (1, ?)",
                (DEFAULT_SCHOOL_NAME,),
            )

    @property
    def school_id(self) -> int:
        return 1

    def clear_all(self) -> None:
        with self._connect() as conn:
            for table in (
                "schedule_entries",
                "schedule_options",
                "conditions",
                "slots",
                "teachers",
                "learning_groups",
                "subjects",
                "classes",
            ):
                conn.execute(f"DELETE FROM {table} WHERE school_id = ?", (self.school_id,))
            conn.execute(
                "UPDATE schools SET time_settings_json = NULL, selected_schedule_option_id = NULL WHERE id = ?",
                (self.school_id,),
            )
        self.repair_proposals = {}
        self.schedule_versions = []

    @property
    def classes(self) -> list[Class]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, max_lessons_per_day FROM classes WHERE school_id = ? ORDER BY id",
                (self.school_id,),
            ).fetchall()
        return [Class(id=row["id"], name=row["name"], max_lessons_per_day=row["max_lessons_per_day"]) for row in rows]

    @property
    def teachers(self) -> list[Teacher]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, subjects_json, unavailable_slots_json, max_lessons_per_day
                FROM teachers WHERE school_id = ? ORDER BY id
                """,
                (self.school_id,),
            ).fetchall()
        return [
            Teacher(
                id=row["id"],
                name=row["name"],
                subjects=json.loads(row["subjects_json"]),
                unavailable_slots=json.loads(row["unavailable_slots_json"]),
                max_lessons_per_day=row["max_lessons_per_day"],
            )
            for row in rows
        ]

    @property
    def subjects(self) -> list[Subject]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, hours_per_week FROM subjects WHERE school_id = ? ORDER BY id",
                (self.school_id,),
            ).fetchall()
        return [Subject(name=row["name"], hours_per_week=row["hours_per_week"]) for row in rows]

    @property
    def learning_groups(self) -> list[LearningGroup]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, class_id, class_name, subject_name, level, display_name
                FROM learning_groups WHERE school_id = ? ORDER BY id
                """,
                (self.school_id,),
            ).fetchall()
        return [
            LearningGroup(
                id=row["id"],
                class_id=row["class_id"],
                class_name=row["class_name"],
                subject_name=row["subject_name"],
                level=row["level"],
                display_name=row["display_name"],
            )
            for row in rows
        ]

    @property
    def slots(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT slot FROM slots WHERE school_id = ? ORDER BY position, id",
                (self.school_id,),
            ).fetchall()
        return [row["slot"] for row in rows]

    @slots.setter
    def slots(self, value: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM slots WHERE school_id = ?", (self.school_id,))
            conn.executemany(
                "INSERT INTO slots (school_id, slot, position) VALUES (?, ?, ?)",
                [(self.school_id, slot, index) for index, slot in enumerate(value)],
            )

    @property
    def conditions(self) -> list[Condition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, payload_json FROM conditions WHERE school_id = ? ORDER BY id",
                (self.school_id,),
            ).fetchall()
        return [Condition(id=row["id"], **json.loads(row["payload_json"])) for row in rows]

    @property
    def time_settings(self) -> TimeSettings | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT time_settings_json FROM schools WHERE id = ?",
                (self.school_id,),
            ).fetchone()
        if not row or not row["time_settings_json"]:
            return None
        return TimeSettings(**json.loads(row["time_settings_json"]))

    @time_settings.setter
    def time_settings(self, value: TimeSettings | None) -> None:
        payload = value.model_dump_json() if value else None
        with self._connect() as conn:
            conn.execute(
                "UPDATE schools SET time_settings_json = ? WHERE id = ?",
                (payload, self.school_id),
            )

    @property
    def schedule(self) -> dict[str, dict[str, ScheduleCell]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT slot, class_name, subject, teacher, session_id
                FROM schedule_entries WHERE school_id = ?
                ORDER BY rowid
                """,
                (self.school_id,),
            ).fetchall()
        schedule: dict[str, dict[str, ScheduleCell]] = {}
        for row in rows:
            schedule.setdefault(row["slot"], {})[row["class_name"]] = ScheduleCell(
                subject=row["subject"],
                teacher=row["teacher"],
                session_id=row["session_id"],
            )
        return schedule

    @schedule.setter
    def schedule(self, value: dict[str, dict[str, Any]]) -> None:
        rows = []
        for slot, entries in (value or {}).items():
            for class_name, cell in entries.items():
                if isinstance(cell, ScheduleCell):
                    subject = cell.subject
                    teacher = cell.teacher
                    session_id = cell.session_id
                elif isinstance(cell, dict):
                    subject = str(cell.get("subject", ""))
                    teacher = str(cell.get("teacher", ""))
                    session_id = cell.get("session_id")
                else:
                    subject = ""
                    teacher = ""
                    session_id = None
                rows.append((self.school_id, slot, class_name, subject, teacher, session_id))
        with self._connect() as conn:
            conn.execute("DELETE FROM schedule_entries WHERE school_id = ?", (self.school_id,))
            conn.executemany(
                """
                INSERT INTO schedule_entries (school_id, slot, class_name, subject, teacher, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    @property
    def schedule_options(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM schedule_options
                WHERE school_id = ? ORDER BY position
                """,
                (self.school_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    @schedule_options.setter
    def schedule_options(self, value: list[dict]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM schedule_options WHERE school_id = ?", (self.school_id,))
            conn.executemany(
                """
                INSERT INTO schedule_options (school_id, option_id, position, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (self.school_id, str(option.get("id")), index, json.dumps(option, ensure_ascii=False))
                    for index, option in enumerate(value or [])
                    if option.get("id")
                ],
            )

    @property
    def selected_schedule_option_id(self) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT selected_schedule_option_id FROM schools WHERE id = ?",
                (self.school_id,),
            ).fetchone()
        return row["selected_schedule_option_id"] if row else None

    @selected_schedule_option_id.setter
    def selected_schedule_option_id(self, value: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE schools SET selected_schedule_option_id = ? WHERE id = ?",
                (value, self.school_id),
            )

    def add_class(self, name: str, max_lessons_per_day: int = 6) -> Class:
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO classes (school_id, name, max_lessons_per_day) VALUES (?, ?, ?)",
                    (self.school_id, name, max_lessons_per_day),
                )
                class_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Class '{name}' already exists") from exc
        return Class(id=int(class_id), name=name, max_lessons_per_day=max_lessons_per_day)

    def add_teacher(
        self,
        name: str,
        subjects: list[str],
        unavailable_slots: list[str] | None = None,
        max_lessons_per_day: int = 6,
    ) -> Teacher:
        unavailable_slots = unavailable_slots or []
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO teachers (school_id, name, subjects_json, unavailable_slots_json, max_lessons_per_day)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self.school_id,
                        name,
                        json.dumps(subjects, ensure_ascii=False),
                        json.dumps(unavailable_slots, ensure_ascii=False),
                        max_lessons_per_day,
                    ),
                )
                teacher_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Teacher '{name}' already exists") from exc
        return Teacher(
            id=int(teacher_id),
            name=name,
            subjects=subjects,
            unavailable_slots=unavailable_slots,
            max_lessons_per_day=max_lessons_per_day,
        )

    def add_subject(self, name: str, hours_per_week: int) -> Subject:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO subjects (school_id, name, hours_per_week) VALUES (?, ?, ?)",
                    (self.school_id, name, hours_per_week),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Subject '{name}' already exists") from exc
        return Subject(name=name, hours_per_week=hours_per_week)

    def add_learning_group(self, payload: LearningGroupCreate) -> LearningGroup:
        class_obj = self._resolve_learning_group_class(payload)
        subject = next((item for item in self.subjects if item.name == payload.subject_name), None)
        if subject is None:
            raise ValueError(f"Subject '{payload.subject_name}' does not exist")
        display_name = payload.display_name or f"{class_obj.name} / {subject.name} / {payload.level}"
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO learning_groups (school_id, class_id, class_name, subject_name, level, display_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.school_id, class_obj.id, class_obj.name, subject.name, payload.level, display_name),
                )
                group_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Learning group '{display_name}' already exists") from exc
        return LearningGroup(
            id=int(group_id),
            class_id=class_obj.id,
            class_name=class_obj.name,
            subject_name=subject.name,
            level=payload.level,
            display_name=display_name,
        )

    def delete_learning_group(self, group_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM learning_groups WHERE school_id = ? AND id = ?",
                (self.school_id, group_id),
            )
        return cursor.rowcount > 0

    def add_slot(self, slot: str) -> str:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM slots WHERE school_id = ?",
                    (self.school_id,),
                ).fetchone()
                conn.execute(
                    "INSERT INTO slots (school_id, slot, position) VALUES (?, ?, ?)",
                    (self.school_id, slot, int(row["next_position"])),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Slot '{slot}' already exists") from exc
        return slot

    def add_condition(self, payload: ConditionCreate) -> Condition:
        self._validate_condition_targets(payload)
        condition_payload = payload.model_dump()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO conditions (school_id, payload_json) VALUES (?, ?)",
                (self.school_id, json.dumps(condition_payload, ensure_ascii=False)),
            )
            condition_id = cursor.lastrowid
        return Condition(id=int(condition_id), **condition_payload)

    def delete_condition(self, condition_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM conditions WHERE school_id = ? AND id = ?",
                (self.school_id, condition_id),
            )
        return cursor.rowcount > 0
