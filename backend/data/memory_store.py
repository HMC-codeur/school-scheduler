from datetime import datetime, timedelta
import random
from typing import Dict, List

from backend.models.schemas import Class, Condition, ConditionCreate, ScheduleCell, Subject, Teacher, TimeSettings


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, ScheduleCell]] = {}
        self.schedule_options: list[dict] = []
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
        self.schedule_options = []
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

    def load_large_demo_data(self) -> dict[str, int]:
        """Charge une démo volumineuse mais cohérente pour stress-tester le moteur."""
        self.clear_all()

        # 1) Création de créneaux réalistes sur 5 jours (8h -> 16h, pause déjeuner exclue).
        self.set_time_settings(
            TimeSettings(
                day_start_time="08:00",
                day_end_time="16:00",
                lesson_duration_minutes=55,
                break_duration_minutes=10,
                working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
                lunch_break_start="12:00",
                lunch_break_end="13:00",
            )
        )

        # 2) Matières variées (plusieurs dizaines) avec volume horaire modéré pour rester générable.
        # Important: la somme des heures doit rester <= nb de créneaux hebdo (25 ici),
        # car le moteur applique ces matières à chaque classe.
        subject_templates: list[tuple[str, int]] = [
            ("Mathématiques", 1), ("Français", 1), ("Anglais", 1), ("Histoire", 1), ("Géographie", 1),
            ("Physique", 1), ("Chimie", 1), ("SVT", 1), ("Technologie", 1), ("Informatique", 1),
            ("EPS", 1), ("Arts plastiques", 1), ("Musique", 1), ("Espagnol", 1), ("Allemand", 1),
            ("Philosophie", 1), ("Économie", 1), ("Sciences sociales", 1), ("Latin", 1),
        ]
        for name, hours in subject_templates:
            self.add_subject(name, hours)
        subject_names = [subject.name for subject in self.subjects]

        # 3) Environ 50 classes, chacune avec un plafond quotidien raisonnable.
        classes_count = 50
        for idx in range(1, classes_count + 1):
            max_daily = 6 if idx % 4 else 7
            self.add_class(f"Classe {idx:02d}", max_lessons_per_day=max_daily)

        # 4) Environ 90 professeurs, chacun couvre 2 à 3 matières.
        rng = random.Random(42)  # graine fixe = démo stable/reproductible
        teachers_count = 90
        slots_pool = list(self.slots)
        for idx in range(1, teachers_count + 1):
            teacher_subjects = rng.sample(subject_names, k=2 if idx % 3 else 3)

            # Indisponibilités réalistes (2 à 4 créneaux), surtout tôt le matin / fin de journée.
            preferred_unavailable = [slot for slot in slots_pool if slot.endswith("08:00") or slot.endswith("15:30")]
            unavailable_source = preferred_unavailable if len(preferred_unavailable) >= 4 else slots_pool
            unavailable = sorted(rng.sample(unavailable_source, k=2 + (idx % 3)))

            max_daily = 5 if idx % 5 else 6
            self.add_teacher(
                name=f"Prof {idx:03d}",
                subjects=teacher_subjects,
                unavailable_slots=unavailable,
                max_lessons_per_day=max_daily,
            )

        # 5) Conditions supplémentaires pour créer de vrais défis (sans bloquer totalement le solveur).
        morning_friendly_subjects = ["Mathématiques", "Français", "Physique", "SVT"]
        for subject_name in morning_friendly_subjects:
            self.add_condition(
                ConditionCreate(
                    text=f"Favoriser {subject_name} le matin",
                    condition_type="subject_morning_preference",
                    subject_name=subject_name,
                )
            )

        # Quelques indisponibilités de classes ciblées pour introduire des contraintes croisées.
        for class_index in range(1, 11):
            blocked_slot = slots_pool[class_index % len(slots_pool)]
            self.add_condition(
                ConditionCreate(
                    text=f"Classe {class_index:02d} indisponible sur {blocked_slot}",
                    condition_type="class_unavailable",
                    class_name=f"Classe {class_index:02d}",
                    slot=blocked_slot,
                )
            )

        self.schedule = {}
        self.schedule_options = []
        return {
            "classes": len(self.classes),
            "teachers": len(self.teachers),
            "subjects": len(self.subjects),
            "slots": len(self.slots),
            "conditions": len(self.conditions),
        }

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
