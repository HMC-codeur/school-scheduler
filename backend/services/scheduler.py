from collections import defaultdict

from backend.models.schemas import Class, Subject, Teacher


class SchedulerService:
    @staticmethod
    def generate(
        classes: list[Class], teachers: list[Teacher], subjects: list[Subject], slots: list[str]
    ) -> dict[str, dict[str, dict[str, str]]] | None:
        if not classes or not teachers or not subjects or not slots:
            return None

        subject_hours = {s.name: s.hours_per_week for s in subjects}
        sessions: list[tuple[Class, str]] = []
        for class_obj in classes:
            for subject_name, hours in subject_hours.items():
                sessions.extend((class_obj, subject_name) for _ in range(hours))

        if len(sessions) > len(classes) * len(slots):
            return None

        teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
        for teacher in teachers:
            for sub in teacher.subjects:
                teachers_by_subject[sub].append(teacher)

        for subject in subject_hours:
            if not teachers_by_subject.get(subject):
                return None

        sessions.sort(key=lambda x: len(teachers_by_subject.get(x[1], [])))

        teacher_busy: dict[tuple[int, str], bool] = {}
        class_busy: dict[tuple[int, str], bool] = {}
        assignments: list[dict[str, str]] = []

        def backtrack(index: int) -> bool:
            if index == len(sessions):
                return True

            class_obj, subject_name = sessions[index]
            valid_teachers = teachers_by_subject[subject_name]

            for slot in slots:
                if class_busy.get((class_obj.id, slot)):
                    continue

                for teacher in valid_teachers:
                    if teacher_busy.get((teacher.id, slot)):
                        continue

                    class_busy[(class_obj.id, slot)] = True
                    teacher_busy[(teacher.id, slot)] = True
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

            return False

        if not backtrack(0):
            return None

        schedule: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        for item in assignments:
            schedule[item["slot"]][item["class"]] = {
                "subject": item["subject"],
                "teacher": item["teacher"],
            }
        return dict(schedule)
