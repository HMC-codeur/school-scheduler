def parse_natural_language_request(text: str) -> dict:
    return {"status": "stub", "intent": "unknown", "text": text}


def explain_schedule_problem(problem: str) -> str:
    return f"[Stub IA] Analyse à venir: {problem}"


def suggest_schedule_changes(schedule: dict, constraints: list[dict]) -> list[dict]:
    return [{"status": "stub", "message": "Suggestions IA bientôt disponibles."}]


def detect_absence_request(text: str) -> dict:
    lowered = text.lower()
    return {"status": "stub", "detected": "absent" in lowered or "absence" in lowered, "text": text}


def propose_replacement(teacher_id: int, slot_id: str) -> dict:
    return {"status": "stub", "teacher_id": teacher_id, "slot_id": slot_id, "message": "Remplacement IA bientôt disponible."}
