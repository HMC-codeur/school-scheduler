from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Iterable, Sequence

from backend.services.imports.intelligence.normalizers import parse_lesson_cell


LESSON_MARKERS = (
    "lesson",
    "course",
    "subject",
    "matiere",
    "matière",
    "cours",
    "שיעור",
    "מקצוע",
)
TEACHER_MARKERS = (
    "teacher",
    "prof",
    "professeur",
    "mme",
    "mr",
    "dr",
    "מורה",
    "מר",
    "גב",
)
CLASS_MARKERS = (
    "class",
    "classe",
    "group",
    "groupe",
    "כיתה",
    "שכבה",
    "קבוצה",
)
ROOM_MARKERS = (
    "room",
    "salle",
    "amphi",
    "lab",
    "laboratoire",
    "חדר",
    "מעבדה",
)
AVAILABILITY_MARKERS = (
    "availability",
    "available",
    "unavailable",
    "disponibilite",
    "disponibilité",
    "disponible",
    "indisponible",
    "yes",
    "no",
    "זמינות",
    "זמין",
    "לא זמין",
    "פנוי",
    "לא פנוי",
    "כן",
    "לא",
)
CONSTRAINT_MARKERS = (
    "constraint",
    "constraints",
    "contrainte",
    "contraintes",
    "restriction",
    "blocked",
    "blocking",
    "avoid",
    "forbidden",
    "max hours",
    "teacher unavailable",
    "unavailable teacher",
    "teacher_unavailable",
    "class_max_daily_hours",
    "pas disponible",
    "not available",
    "אילוץ",
    "אילוצים",
    "מגבלה",
    "מגבלות",
    "אסור",
    "חסום",
)
NOISE_NOTES_MARKERS = (
    "note",
    "notes",
    "comment",
    "comments",
    "remarque",
    "remarques",
    "todo",
    "rappel",
    "reminder",
    "whatsapp",
    "mail",
    "email",
    "operational",
    "תזכורת",
    "הערה",
    "הערות",
    "כללי",
)
ENTITY_LIST_MARKERS = (
    "list",
    "liste",
    "names",
    "students",
    "teachers",
    "classes",
    "subjects",
    "רשימה",
    "שמות",
    "מורים",
    "כיתות",
    "מקצועות",
)

_GERESH_TRANSLATION = str.maketrans(
    {
        "\u05f3": "'",
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u05f4": '"',
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
    }
)
_NIQQUD_RE = re.compile(r"[\u0591-\u05c7]")
_REPEATED_PUNCT_RE = re.compile(r"([!?.,;:])\1+")
_TOKEN_RE = re.compile(r"[\w\u0590-\u05ff']+")


def normalize_school_text(text: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).translate(_GERESH_TRANSLATION)
    normalized = _NIQQUD_RE.sub("", normalized)
    normalized = "".join(char.lower() if "A" <= char <= "Z" else char for char in normalized)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = _REPEATED_PUNCT_RE.sub(r"\1", normalized)
    normalized = re.sub(r"[\t\r\n]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def fuzzy_contains_any(text: object, terms: Sequence[str], threshold: float = 0.82) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    normalized_terms = tuple(normalize_school_text(term) for term in terms if normalize_school_text(term))
    if any(term in normalized for term in normalized_terms):
        return True
    tokens = _search_windows(normalized)
    return any(_close_enough(token, term, threshold) for token in tokens for term in normalized_terms)


def count_fuzzy_hits(texts: Iterable[object], terms: Sequence[str], threshold: float = 0.82) -> int:
    return sum(1 for text in texts if fuzzy_contains_any(text, terms, threshold=threshold))


def is_short_repeated_status(text: object) -> bool:
    normalized = normalize_school_text(text)
    tokens = _TOKEN_RE.findall(normalized)
    if not tokens or len(tokens) > 4:
        return False
    unique = set(tokens)
    return (
        fuzzy_contains_any(normalized, AVAILABILITY_MARKERS, threshold=0.82)
        and (len(unique) <= 2 or len(normalized) <= 16)
    )


def looks_lesson_like(text: object) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    if looks_availability_like(normalized) or looks_constraint_like(normalized) or looks_noise_like(normalized):
        return False
    parsed, warnings = parse_lesson_cell(normalized)
    has_entity = bool(parsed.get("teacher") or parsed.get("class_name") or parsed.get("room"))
    has_lesson_marker = fuzzy_contains_any(normalized, (*LESSON_MARKERS, *TEACHER_MARKERS, *CLASS_MARKERS, *ROOM_MARKERS), threshold=0.86)
    token_count = len(_TOKEN_RE.findall(normalized))
    return bool(
        has_entity
        or (parsed.get("subject") and not warnings and token_count >= 2)
        or (parsed.get("subject") and has_lesson_marker and token_count >= 2)
    )


def looks_schedule_grid_lesson_candidate(text: object, *, has_timetable_context: bool = False) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    if is_short_repeated_status(normalized) or looks_availability_like(normalized):
        return False
    if looks_constraint_like(normalized) or looks_noise_like(normalized):
        has_school_marker = fuzzy_contains_any(normalized, (*TEACHER_MARKERS, *CLASS_MARKERS, *ROOM_MARKERS), threshold=0.86)
        if not has_school_marker:
            return False
    if looks_constraint_like(normalized):
        return False
    if looks_lesson_like(normalized):
        return True
    if not has_timetable_context:
        return False
    tokens = _TOKEN_RE.findall(normalized)
    has_letters = any(re.search(r"[a-z\u0590-\u05ff]", token) for token in tokens)
    return bool(has_letters and len(normalized) >= 3)


def looks_availability_like(text: object) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    if is_short_repeated_status(normalized):
        return True
    return fuzzy_contains_any(normalized, AVAILABILITY_MARKERS, threshold=0.82)


def looks_constraint_like(text: object) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    return bool(
        fuzzy_contains_any(normalized, CONSTRAINT_MARKERS, threshold=0.82)
        or re.search(r"\b(?:pas|not)\s+(?:disponible|available)\b", normalized)
        or "לא זמין" in normalized
    )


def looks_noise_like(text: object) -> bool:
    normalized = normalize_school_text(text)
    if not normalized:
        return False
    token_count = len(_TOKEN_RE.findall(normalized))
    note_like = fuzzy_contains_any(normalized, NOISE_NOTES_MARKERS, threshold=0.84)
    operational_sentence = token_count >= 7 and re.search(r"[.;:]|\b(?:please|todo|rappel|note|comment)\b|הער", normalized)
    return bool(note_like or operational_sentence)


def _search_windows(text: str) -> tuple[str, ...]:
    tokens = _TOKEN_RE.findall(text)
    windows = list(tokens)
    for size in (2, 3):
        windows.extend(" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1))
    return tuple(windows)


def _close_enough(value: str, term: str, threshold: float) -> bool:
    if len(value) < 3 or len(term) < 3:
        return False
    if abs(len(value) - len(term)) > max(3, len(term) // 2):
        return False
    return difflib.SequenceMatcher(None, value, term).ratio() >= threshold
