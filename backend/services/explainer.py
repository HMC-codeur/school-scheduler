from backend.models.schemas import Class, Subject, Teacher


def explain_generation_failure(
    classes: list[Class],
    teachers: list[Teacher],
    subjects: list[Subject],
    slots: list[str],
) -> str:
    if not classes:
        return "Cannot generate schedule: no classes added."
    if not teachers:
        return "Cannot generate schedule: no teachers added."
    if not subjects:
        return "Cannot generate schedule: no subjects added."
    if not slots:
        return "Cannot generate schedule: no time slots added."

    teacher_subjects = {s for t in teachers for s in t.subjects}
    missing = [s.name for s in subjects if s.name not in teacher_subjects]
    if missing:
        return f"Cannot generate schedule: no compatible teacher for subjects {', '.join(missing)}."

    required = len(classes) * sum(s.hours_per_week for s in subjects)
    capacity = len(classes) * len(slots)
    if required > capacity:
        return (
            "Cannot generate schedule: not enough slots for required weekly sessions "
            f"({required} required, {capacity} capacity)."
        )

    return (
        "Cannot generate schedule: constraints conflict. Check teacher unavailability, daily limits, "
        "and class blocked slots."
    )
