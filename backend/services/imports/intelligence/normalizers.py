from __future__ import annotations

import re
import unicodedata
from typing import Any


DAY_ALIASES = {
    "mon": ("mon", "monday", "lun", "lundi", "שני", "יום שני"),
    "tue": ("tue", "tuesday", "mar", "mardi", "שלישי", "יום שלישי"),
    "wed": ("wed", "wednesday", "mer", "mercredi", "רביעי", "יום רביעי"),
    "thu": ("thu", "thursday", "jeu", "jeudi", "חמישי", "יום חמישי"),
    "fri": ("fri", "friday", "ven", "vendredi", "שישי", "יום שישי"),
    "sat": ("sat", "saturday", "sam", "samedi", "שבת", "יום שבת"),
    "sun": ("sun", "sunday", "dim", "dimanche", "ראשון", "יום ראשון"),
}

TEACHER_MARKERS = ("teacher", "prof", "professeur", "m.", "mme", "mr", "dr", "מורה", "מר", "גב")
ROOM_MARKERS = ("room", "salle", "s.", "amphi", "חדר", "מעבדה")


def normalize_text(value: Any) -> str:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line)


def fold_key(value: Any) -> str:
    cleaned = normalize_text(value).casefold()
    decomposed = unicodedata.normalize("NFKD", cleaned)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[\s_\-]+", " ", without_accents).strip()


def day_key(value: str) -> str | None:
    cleaned = re.sub(r"^יום\s+", "", normalize_text(value).lower())
    for key, aliases in DAY_ALIASES.items():
        if cleaned in aliases or any(alias in cleaned for alias in aliases if len(alias) > 3):
            return key
    return None


def is_day(value: Any) -> bool:
    return day_key(str(value)) is not None


def is_time_like(value: Any) -> bool:
    text = normalize_text(value).casefold()
    if not text:
        return False
    return bool(
        re.search(r"([01]?\d|2[0-3])\s*[:h]\s*[0-5]\d", text)
        or re.search(r"\b(period|periode|période)\s*\d+\b", text)
        or re.search(r"שיעור\s*\d+", text)
        or re.fullmatch(r"\d{1,2}", text)
    )


def looks_like_class_token(value: str) -> bool:
    cleaned = normalize_text(value).strip("()[]{}.,;:")
    return bool(
        re.fullmatch(r"\d{1,2}[A-Za-zא-ת]?", cleaned)
        or re.fullmatch(r"[A-Za-zא-ת]\d{1,2}", cleaned)
        or re.fullmatch(r"\d(?:e|eme|ème)\s*[A-Za-z]?", fold_key(cleaned))
        or re.fullmatch(r"(seconde|terminale)\s*\d?", fold_key(cleaned))
        or re.fullmatch(r"[זחטיכל][\"'׳]?\d?", cleaned)
        or re.fullmatch(r"י[\"׳]?ב\d?", cleaned)
        or re.fullmatch(r"י[\"׳]?א\d?", cleaned)
        or re.fullmatch(r"י[\"׳]?\d?", cleaned)
    )


def extract_label_value(text: str, labels: tuple[str, ...]) -> str | None:
    joined = "\n".join(normalize_text(line) for line in str(text or "").split("\n"))
    for label in labels:
        match = re.search(rf"(?:^|\n)\s*{re.escape(label)}\s*[:：]\s*([^\n]+)", joined, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1)) or None
        match = re.search(rf"\b{re.escape(label)}\s+([^\n()\-]+)", joined, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1)) or None
    return None


def parse_lesson_cell(text: Any) -> tuple[dict[str, str | None], list[str]]:
    raw = normalize_text(text)
    warnings: list[str] = []
    teacher = extract_label_value(raw, TEACHER_MARKERS)
    room = extract_label_value(raw, ROOM_MARKERS)
    class_name = extract_label_value(raw, ("class", "classe", "כיתה"))

    teacher_match = re.search(r"\((?:M\.|Mme|Mr|Dr)\s+([^)]+)\)", raw, flags=re.IGNORECASE)
    if teacher_match and not teacher:
        teacher = normalize_text(teacher_match.group(1))
    room_match = re.search(r"(?:Salle|Room|S\.|Amphi|חדר|מעבדה)\s*[:：]?\s*([A-Za-z0-9א-ת\"'׳\s-]+)", raw, flags=re.IGNORECASE)
    if room_match and not room:
        room = normalize_text(room_match.group(1)).strip("()")

    content_lines = []
    marker_labels = (*TEACHER_MARKERS, *ROOM_MARKERS, "class", "classe", "כיתה")
    for line in raw.split("\n"):
        if any(re.search(rf"^\s*{re.escape(label)}\s*[:：]", line, flags=re.IGNORECASE) for label in marker_labels):
            continue
        cleaned = normalize_text(line)
        if cleaned:
            content_lines.append(cleaned)
    first = content_lines[0] if content_lines else raw
    tokens = [token.strip("()[]{}.,;:") for token in first.split()]
    if not class_name:
        candidates = [*tokens]
        if len(tokens) >= 2:
            candidates.extend([" ".join(tokens[index:index + 2]) for index in range(len(tokens) - 1)])
        for candidate in reversed(candidates):
            if looks_like_class_token(candidate):
                class_name = candidate
                break
    subject = first
    if class_name:
        subject = re.sub(rf"(?:^|\s){re.escape(class_name)}(?:$|\s)", " ", subject).strip()
    if teacher:
        subject = re.sub(r"\((?:M\.|Mme|Mr|Dr)\s+[^)]+\)", " ", subject, flags=re.IGNORECASE).strip()
    if room:
        subject = re.sub(r"(?:Salle|Room|S\.|Amphi|חדר|מעבדה)\s*[:：]?\s*" + re.escape(room), " ", subject, flags=re.IGNORECASE).strip(" -")
    if not subject:
        subject = first or None
    if raw and not any([teacher, room, class_name]):
        warnings.append("Extraction incertaine depuis une cellule libre.")
    return {
        "subject": subject or None,
        "class_name": class_name or None,
        "teacher": teacher or None,
        "room": room or None,
        "confidence": "0.85" if any([teacher, room, class_name]) else "0.45",
    }, warnings
