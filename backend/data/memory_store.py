from datetime import datetime, timedelta
import random
from typing import Dict, List

from backend.models.schemas import Class, Condition, ConditionCreate, LearningGroup, LearningGroupCreate, ScheduleCell, Subject, Teacher, TimeSettings


class MemoryStore:
    def __init__(self) -> None:
        self.classes: List[Class] = []
        self.teachers: List[Teacher] = []
        self.subjects: List[Subject] = []
        self.learning_groups: List[LearningGroup] = []
        self.slots: List[str] = []
        self.schedule: Dict[str, Dict[str, ScheduleCell]] = {}
        self.schedule_options: list[dict] = []
        self.schedule_versions: list[dict] = []
        self.repair_proposals: dict[str, dict] = {}
        self.selected_schedule_option_id: str | None = None
        self.conditions: List[Condition] = []
        self.time_settings: TimeSettings | None = None
        self._class_id = 1
        self._learning_group_id = 1
        self._teacher_id = 1
        self._condition_id = 1

    def clear_all(self) -> None:
        self.classes = []
        self.teachers = []
        self.subjects = []
        self.learning_groups = []
        self.slots = []
        self.schedule = {}
        self.schedule_options = []
        self.schedule_versions = []
        self.repair_proposals = {}
        self.selected_schedule_option_id = None
        self.conditions = []
        self.time_settings = None
        self._class_id = 1
        self._learning_group_id = 1
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

        # 2) Matières variées avec charges inégales pour mieux simuler un collège pilote.
        # Important: la somme des heures doit rester <= nb de créneaux hebdo,
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

        # 4) Professeurs à charges variables : temps partiels, bivalents et quelques profils larges.
        rng = random.Random(42)  # graine fixe = démo stable/reproductible
        teachers_count = 90
        slots_pool = list(self.slots)
        for idx in range(1, teachers_count + 1):
            teacher_subjects = rng.sample(subject_names, k=2 if idx % 3 else 3)

            # Indisponibilités réalistes (2 à 3 créneaux), surtout tôt le matin / fin de journée.
            preferred_unavailable = [slot for slot in slots_pool if slot.endswith("08:00") or slot.endswith("15:30")]
            unavailable_source = preferred_unavailable if len(preferred_unavailable) >= 4 else slots_pool
            unavailable_count = 2 + (idx % 2)
            unavailable = sorted(rng.sample(unavailable_source, k=min(unavailable_count, len(unavailable_source))))

            if idx % 10 == 0:
                max_daily = 4
            elif idx % 4 == 0:
                max_daily = 4
            else:
                max_daily = 5
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
        self.selected_schedule_option_id = None
        return {
            "classes": len(self.classes),
            "teachers": len(self.teachers),
            "subjects": len(self.subjects),
            "slots": len(self.slots),
            "conditions": len(self.conditions),
        }

    def load_learning_groups_demo_data(self) -> dict[str, int]:
        """Charge une petite école avec classes officielles et groupes de niveaux."""
        self.clear_all()
        for day in ["Sun", "Mon", "Tue", "Wed", "Thu"]:
            for hour in ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"]:
                self.add_slot(f"{day}-{hour}")

        for class_name in ["ט", "י", "יא", "יב"]:
            self.add_class(class_name, max_lessons_per_day=6)

        for name, hours in [
            ("היסטוריה", 2),
            ("תנך", 2),
            ("אזרחות", 1),
            ("ספורט", 1),
            ("מתמטיקה", 3),
            ("אנגלית", 3),
        ]:
            self.add_subject(name, hours)

        for class_obj in self.classes:
            for subject_name in ["מתמטיקה", "אנגלית"]:
                for level in ["débutant", "intermédiaire", "avancé"]:
                    self.add_learning_group(
                        LearningGroupCreate(
                            class_id=class_obj.id,
                            subject_name=subject_name,
                            level=level,
                        )
                    )

        self.add_teacher("כהן", ["היסטוריה", "תנך"], ["Sun-08:00"], max_lessons_per_day=5)
        self.add_teacher("לוי", ["אזרחות", "היסטוריה"], ["Mon-13:00"], max_lessons_per_day=4)
        self.add_teacher("מזרחי", ["ספורט"], ["Tue-08:00"], max_lessons_per_day=4)
        self.add_teacher("בן דוד", ["מתמטיקה"], ["Wed-13:00"], max_lessons_per_day=5)
        self.add_teacher("פרץ", ["מתמטיקה"], ["Thu-08:00"], max_lessons_per_day=5)
        self.add_teacher("אברמוב", ["מתמטיקה"], ["Sun-13:00"], max_lessons_per_day=5)
        self.add_teacher("רוזן", ["אנגלית"], ["Mon-08:00"], max_lessons_per_day=5)
        self.add_teacher("סגל", ["אנגלית"], ["Tue-13:00"], max_lessons_per_day=5)
        self.add_teacher("דיין", ["אנגלית"], ["Wed-08:00"], max_lessons_per_day=5)

        return {
            "classes": len(self.classes),
            "learning_groups": len(self.learning_groups),
            "teachers": len(self.teachers),
            "subjects": len(self.subjects),
            "slots": len(self.slots),
            "conditions": len(self.conditions),
        }

    def load_pilot_demo_data(self) -> dict[str, int]:
        """Charge un dataset pilote réaliste, stable et volontairement générable."""
        self.clear_all()

        for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            for hour in ["08:00", "09:00", "10:00", "11:00", "13:00", "14:00"]:
                self.add_slot(f"{day}-{hour}")

        subjects = [
            ("Mathématiques", 3),
            ("Français", 3),
            ("Anglais", 2),
            ("Sciences", 2),
            ("Histoire", 2),
            ("Géographie", 1),
            ("Vie civique", 1),
            ("EPS", 2),
            ("Informatique", 1),
            ("Arts", 1),
        ]
        for name, hours in subjects:
            self.add_subject(name, hours)

        for level in ["6e", "5e", "4e", "3e"]:
            for group in ["A", "B", "C"]:
                self.add_class(f"{level}{group}", max_lessons_per_day=6)

        teacher_specs = [
            ("Mme Laurent", ["Mathématiques"], ["Wed-13:00", "Fri-14:00"], 5),
            ("M. Benhamou", ["Mathématiques", "Informatique"], ["Mon-08:00", "Thu-14:00"], 5),
            ("Mme Cohen", ["Mathématiques"], ["Tue-13:00", "Fri-08:00"], 4),
            ("M. Haddad", ["Mathématiques", "Sciences"], ["Wed-08:00", "Thu-13:00"], 4),
            ("Mme Durand", ["Français"], ["Mon-14:00", "Thu-08:00"], 5),
            ("M. Petit", ["Français", "Histoire"], ["Tue-14:00", "Fri-13:00"], 5),
            ("Mme Amar", ["Français"], ["Wed-13:00", "Fri-14:00"], 4),
            ("Mme Levy", ["Anglais"], ["Mon-08:00", "Wed-14:00"], 4),
            ("M. Rosen", ["Anglais"], ["Tue-08:00", "Thu-13:00", "Fri-14:00"], 3),
            ("Mme Martin", ["Anglais", "Vie civique"], ["Mon-13:00", "Wed-08:00"], 4),
            ("M. Garcia", ["Sciences"], ["Tue-13:00", "Fri-08:00"], 5),
            ("Mme Nguyen", ["Sciences", "Informatique"], ["Mon-14:00", "Thu-08:00"], 4),
            ("M. Morel", ["Sciences"], ["Wed-14:00", "Fri-13:00"], 3),
            ("Mme Barak", ["Histoire", "Géographie"], ["Mon-08:00", "Thu-14:00"], 5),
            ("M. Elbaz", ["Histoire", "Vie civique"], ["Tue-14:00", "Wed-13:00"], 4),
            ("Mme Simon", ["Géographie", "Histoire"], ["Wed-08:00", "Fri-14:00"], 3),
            ("M. Dahan", ["EPS"], ["Mon-13:00", "Tue-13:00"], 5),
            ("Mme Fitoussi", ["EPS"], ["Thu-08:00", "Fri-08:00"], 4),
            ("M. Vidal", ["Informatique", "Mathématiques"], ["Tue-08:00", "Fri-13:00"], 3),
            ("Mme Tessier", ["Arts"], ["Mon-08:00", "Wed-08:00", "Fri-08:00"], 3),
            ("M. Peretz", ["Arts", "Vie civique"], ["Tue-13:00", "Thu-13:00"], 3),
            ("Mme Saada", ["Vie civique", "Français"], ["Mon-14:00", "Wed-14:00"], 3),
        ]
        for name, teacher_subjects, unavailable, max_daily in teacher_specs:
            self.add_teacher(name, teacher_subjects, unavailable, max_lessons_per_day=max_daily)

        conditions = [
            ConditionCreate(
                text="Mathématiques le matin si possible",
                condition_type="subject_morning_preference",
                subject_name="Mathématiques",
            ),
            ConditionCreate(
                text="Français le matin si possible",
                condition_type="subject_morning_preference",
                subject_name="Français",
            ),
            ConditionCreate(
                text="Sciences le matin si possible",
                condition_type="subject_morning_preference",
                subject_name="Sciences",
            ),
            ConditionCreate(
                text="Mme Cohen temps partiel mercredi après-midi",
                condition_type="teacher_unavailable",
                teacher_name="Mme Cohen",
                slot="Wed-14:00",
            ),
            ConditionCreate(
                text="M. Rosen temps partiel vendredi après-midi",
                condition_type="teacher_unavailable",
                teacher_name="M. Rosen",
                slot="Fri-13:00",
            ),
            ConditionCreate(
                text="6eA réunion pédagogique lundi 08h",
                condition_type="class_unavailable",
                class_name="6eA",
                slot="Mon-08:00",
            ),
            ConditionCreate(
                text="5eB sortie sportive jeudi 14h",
                condition_type="class_unavailable",
                class_name="5eB",
                slot="Thu-14:00",
            ),
            ConditionCreate(
                text="4eC atelier externe mardi 13h",
                condition_type="class_unavailable",
                class_name="4eC",
                slot="Tue-13:00",
            ),
            ConditionCreate(
                text="Éviter longues séries pour les 3e",
                condition_type="avoid_long_sequence",
                class_name="3eA",
            ),
            ConditionCreate(
                text="Éviter répétition de Mathématiques en 6eA",
                condition_type="avoid_subject_repeat_same_day",
                class_name="6eA",
                subject_name="Mathématiques",
            ),
        ]
        for condition in conditions:
            self.add_condition(condition)

        self.schedule = {}
        self.schedule_options = []
        self.schedule_versions = []
        self.repair_proposals = {}
        self.selected_schedule_option_id = None
        return {
            "classes": len(self.classes),
            "teachers": len(self.teachers),
            "subjects": len(self.subjects),
            "slots": len(self.slots),
            "conditions": len(self.conditions),
        }

    def add_class(self, name: str, max_lessons_per_day: int = 6) -> Class:
        if any(item.name == name for item in self.classes):
            raise ValueError(f"Class '{name}' already exists")
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
        if any(item.name == name for item in self.teachers):
            raise ValueError(f"Teacher '{name}' already exists")
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

    def add_learning_group(self, payload: LearningGroupCreate) -> LearningGroup:
        class_obj = self._resolve_learning_group_class(payload)
        subject = next((item for item in self.subjects if item.name == payload.subject_name), None)
        if subject is None:
            raise ValueError(f"Subject '{payload.subject_name}' does not exist")
        display_name = payload.display_name or f"{class_obj.name} / {subject.name} / {payload.level}"
        if any(item.display_name == display_name for item in self.learning_groups):
            raise ValueError(f"Learning group '{display_name}' already exists")
        item = LearningGroup(
            id=self._learning_group_id,
            class_id=class_obj.id,
            class_name=class_obj.name,
            subject_name=subject.name,
            level=payload.level,
            display_name=display_name,
        )
        self._learning_group_id += 1
        self.learning_groups.append(item)
        return item

    def _resolve_learning_group_class(self, payload: LearningGroupCreate) -> Class:
        if payload.class_id is not None:
            class_obj = next((item for item in self.classes if item.id == payload.class_id), None)
            if class_obj:
                return class_obj
            raise ValueError(f"Class id '{payload.class_id}' does not exist")
        class_obj = next((item for item in self.classes if item.name == payload.class_name), None)
        if class_obj:
            return class_obj
        raise ValueError(f"Class '{payload.class_name}' does not exist")

    def delete_learning_group(self, group_id: int) -> bool:
        initial = len(self.learning_groups)
        self.learning_groups = [group for group in self.learning_groups if group.id != group_id]
        return len(self.learning_groups) < initial

    def add_slot(self, slot: str) -> str:
        if slot in self.slots:
            raise ValueError(f"Slot '{slot}' already exists")
        self.slots.append(slot)
        return slot

    def add_condition(self, payload: ConditionCreate) -> Condition:
        self._validate_condition_targets(payload)
        item = Condition(id=self._condition_id, **payload.model_dump())
        self._condition_id += 1
        self.conditions.append(item)
        return item

    def _validate_condition_targets(self, payload: ConditionCreate) -> None:
        teacher_names = {teacher.name for teacher in self.teachers}
        class_names = {class_obj.name for class_obj in self.classes}
        subject_names = {subject.name for subject in self.subjects}
        slots = set(self.slots)

        if payload.slot and payload.slot not in slots:
            raise ValueError(f"Slot '{payload.slot}' does not exist")

        if payload.condition_type in {"teacher_unavailable", "teacher_prefer_morning"}:
            if payload.teacher_name not in teacher_names:
                raise ValueError(f"Teacher '{payload.teacher_name}' does not exist")

        if payload.condition_type == "class_unavailable":
            if payload.class_name not in class_names:
                raise ValueError(f"Class '{payload.class_name}' does not exist")

        if payload.condition_type in {"subject_morning_preference", "avoid_subject_repeat"}:
            if payload.subject_name not in subject_names:
                raise ValueError(f"Subject '{payload.subject_name}' does not exist")
            if payload.class_name and payload.class_name not in class_names:
                raise ValueError(f"Class '{payload.class_name}' does not exist")

        if payload.condition_type == "avoid_long_sequence":
            if payload.class_name and payload.class_name not in class_names:
                raise ValueError(f"Class '{payload.class_name}' does not exist")
            if payload.teacher_name and payload.teacher_name not in teacher_names:
                raise ValueError(f"Teacher '{payload.teacher_name}' does not exist")

    def delete_condition(self, condition_id: int) -> bool:
        initial = len(self.conditions)
        self.conditions = [condition for condition in self.conditions if condition.id != condition_id]
        return len(self.conditions) < initial

    def set_time_settings(self, settings: TimeSettings) -> list[str]:
        self.time_settings = settings
        generated_slots = self.generate_slots_from_time_settings(settings)
        if not generated_slots:
            raise ValueError("Time settings generated no slots")
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
