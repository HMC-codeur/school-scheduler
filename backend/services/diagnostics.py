from collections import defaultdict

from backend.models.schemas import Class, Condition, Subject, Teacher, TimeSettings
from backend.services.scheduler import SchedulerService


def diagnose_schedule_generation(
    classes: list[Class],
    teachers: list[Teacher],
    subjects: list[Subject],
    slots: list[str],
    conditions: list[Condition] | None = None,
    time_settings: TimeSettings | None = None,
) -> dict:
    conditions = conditions or []
    blocking_issues: list[str] = []
    warnings: list[str] = []

    stats = {
        "classes": len(classes),
        "teachers": len(teachers),
        "subjects": len(subjects),
        "slots": len(slots),
        "conditions": len(conditions),
        "required_sessions": len(classes) * sum(subject.hours_per_week for subject in subjects),
        "available_class_sessions": len(classes) * len(slots),
    }

    if not classes:
        blocking_issues.append("Aucune classe n'a été ajoutée.")
    if not teachers:
        blocking_issues.append("Aucun professeur n'a été ajouté.")
    if not subjects:
        blocking_issues.append("Aucune matière n'a été ajoutée.")
    if not slots:
        if time_settings:
            blocking_issues.append("Les réglages horaires actuels ne produisent aucun créneau.")
        else:
            blocking_issues.append("Aucun créneau n'a été ajouté.")

    if blocking_issues:
        return {"can_generate": False, "blocking_issues": blocking_issues, "warnings": warnings, "stats": stats}

    subject_names = {subject.name for subject in subjects}
    teacher_names = {teacher.name for teacher in teachers}
    class_names = {class_obj.name for class_obj in classes}
    slot_values = set(slots)

    teachers_by_subject: dict[str, list[Teacher]] = defaultdict(list)
    for teacher in teachers:
        for subject_name in teacher.subjects:
            if subject_name not in subject_names:
                warnings.append(f"Le professeur '{teacher.name}' référence une matière inconnue: '{subject_name}'.")
                continue
            teachers_by_subject[subject_name].append(teacher)

    for subject in subjects:
        compatible = teachers_by_subject.get(subject.name, [])
        if not compatible:
            blocking_issues.append(f"Aucun professeur compatible pour la matière '{subject.name}'.")

    required_per_class = sum(subject.hours_per_week for subject in subjects)
    if stats["required_sessions"] > stats["available_class_sessions"]:
        blocking_issues.append(
            f"Capacité insuffisante: {stats['required_sessions']} cours requis pour {stats['available_class_sessions']} places classe."
        )

    days = {slot.split("-", 1)[0] for slot in slots}
    for class_obj in classes:
        weekly_capacity = len(days) * max(1, class_obj.max_lessons_per_day)
        if required_per_class > weekly_capacity:
            blocking_issues.append(
                f"Capacité insuffisante pour la classe '{class_obj.name}': {required_per_class} cours requis, {weekly_capacity} max."
            )

    teacher_blocked_slots: dict[str, set[str]] = {teacher.name: set(teacher.unavailable_slots) for teacher in teachers}
    class_blocked_slots: dict[str, set[str]] = defaultdict(set)
    for condition in conditions:
        if condition.slot and condition.slot not in slot_values:
            blocking_issues.append(f"Contrainte impossible: le créneau '{condition.slot}' n'existe pas.")
        if condition.teacher_name and condition.teacher_name not in teacher_names:
            blocking_issues.append(f"Contrainte impossible: le professeur '{condition.teacher_name}' n'existe pas.")
        if condition.class_name and condition.class_name not in class_names:
            blocking_issues.append(f"Contrainte impossible: la classe '{condition.class_name}' n'existe pas.")
        if condition.subject_name and condition.subject_name not in subject_names:
            blocking_issues.append(f"Contrainte impossible: la matière '{condition.subject_name}' n'existe pas.")
        if condition.condition_type == "teacher_unavailable" and condition.teacher_name and condition.slot:
            teacher_blocked_slots.setdefault(condition.teacher_name, set()).add(condition.slot)
        if condition.condition_type == "class_unavailable" and condition.class_name and condition.slot:
            class_blocked_slots[condition.class_name].add(condition.slot)

    for class_obj in classes:
        available_slots = [slot for slot in slots if slot not in class_blocked_slots[class_obj.name]]
        if len(available_slots) < required_per_class:
            blocking_issues.append(
                f"Contrainte impossible pour la classe '{class_obj.name}': {required_per_class} cours requis, {len(available_slots)} créneaux disponibles."
            )

    for subject in subjects:
        available_teacher_slots = 0
        for teacher in teachers_by_subject.get(subject.name, []):
            available_slots = [slot for slot in slots if slot not in teacher_blocked_slots.get(teacher.name, set())]
            available_teacher_slots += min(len(available_slots), len(days) * max(1, teacher.max_lessons_per_day))
        required_for_subject = len(classes) * subject.hours_per_week
        if available_teacher_slots < required_for_subject:
            blocking_issues.append(
                f"Capacité prof insuffisante pour '{subject.name}': {required_for_subject} cours requis, {available_teacher_slots} places prof compatibles."
            )

    if not blocking_issues:
        result = SchedulerService.generate(
            classes,
            teachers,
            subjects,
            slots,
            conditions,
            quality_attempts=1,
        )
        if not result.success:
            blocking_issues.append(f"Contraintes impossibles: {result.message}")

    return {
        "can_generate": not blocking_issues,
        "blocking_issues": list(dict.fromkeys(blocking_issues)),
        "warnings": list(dict.fromkeys(warnings)),
        "stats": stats,
    }
