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
