from __future__ import annotations

import re
from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportContext
from backend.services.imports.intelligence.normalizers import fold_key, normalize_text, parse_lesson_cell


SHEET_TYPES = {
    "schedule_grid",
    "requirements_table",
    "teacher_availability",
    "availability_table",
    "constraints",
    "constraints_table",
    "constraints_text",
    "entity_list",
    "metadata",
    "mixed_sheet",
    "ignored",
    "unknown_review",
}


class SheetClassificationBrain:
    name = "sheet_classification"

    def run(self, context: ImportContext) -> BrainResult:
        sheets_by_name = {sheet.name: sheet for sheet in context.sheets}
        classifications = [_classify(profile, context.headers, sheets_by_name.get(profile["sheet_name"])) for profile in context.sheet_profiles]
        context.sheet_classifications = classifications
        needs_review = any(item["needs_human_review"] for item in classifications)
        return context.add_result(
            BrainResult(
                self.name,
                "needs_review" if needs_review else "ok",
                _average(classifications),
                data={"sheet_classifications": classifications},
            )
        )


AVAILABILITY_HINTS = (
    "availability",
    "available",
    "unavailable",
    "disponibilite",
    "disponible",
    "indisponible",
    "זמינות",
    "זמין",
    "פנוי",
)
AVAILABILITY_MARKERS = {"זמין", "לא זמין", "פנוי", "לא פנוי", "available", "unavailable", "yes", "no", "כן", "לא"}
CONSTRAINT_HINTS = (
    "constraint",
    "constraints",
    "contrainte",
    "contraintes",
    "restriction",
    "blocked",
    "max hours",
    "unavailable teacher",
    "teacher unavailable",
    "teacher_unavailable",
    "class_max_daily_hours",
    "avoid",
    "אסור",
    "אילוץ",
    "אילוצים",
    "מגבלה",
    "מגבלות",
)
TEACHER_MARKER_PATTERN = re.compile(r"(?:^|\b)(teacher|prof|professeur|mme|mr|dr)\s*[:：]?|מורה\s*[:：]", re.IGNORECASE)


def _classify(profile: dict[str, Any], headers: list[dict[str, Any]], sheet: Any | None = None) -> dict[str, Any]:
    sheet_name = profile["sheet_name"]
    header = next((item for item in headers if item["sheet_name"] == sheet_name), None)
    roles = set(header.get("roles", [])) if header else set()
    signals = _content_signals(sheet_name, sheet)
    reasons: list[str] = []

    if profile["is_empty"]:
        return _item(sheet_name, "ignored", 0.98, False, ["Feuille vide."])
    if profile["is_probably_metadata"]:
        return _item(sheet_name, "metadata", 0.95, False, ["Nom de feuille de type notes/source/metadata."])
    if {"class_name", "subject_name", "weekly_hours"}.issubset(roles):
        if "teacher_name" not in roles:
            reasons.append("Table de besoins probable, mais colonne professeur absente.")
        return _item(sheet_name, "requirements_table", 0.92 if "teacher_name" in roles else 0.78, "teacher_name" not in roles, reasons or ["Colonnes classe, matière, professeur et heures détectées."])
    if {"teacher_name", "day", "time", "availability"}.issubset(roles) or {"teacher_name", "availability"}.issubset(roles):
        return _item(sheet_name, "teacher_availability", 0.9, False, ["Colonnes professeur, jour/horaire et disponibilité détectées."])
    if "constraint" in roles:
        return _item(sheet_name, "constraints_table", 0.84, True, ["Colonnes ou texte de contraintes détectés."])
    if _looks_like_availability_sheet(profile, signals):
        return _item(sheet_name, "teacher_availability", 0.86, False, ["Marqueurs de disponibilité détectés; extraction de cours désactivée pour cette feuille."])
    if _looks_like_constraints_sheet(signals):
        return _item(sheet_name, "constraints_table", 0.82, True, ["Contraintes détectées; extraction de cours désactivée pour cette feuille."])
    if _looks_like_schedule_grid(profile, signals):
        return _item(sheet_name, "schedule_grid", 0.8, True, ["Grille avec jours, créneaux et cellules de cours détectée; review recommandée avant extraction."])
    if len({"class_name", "teacher_name", "subject_name"} & roles) >= 1 and profile["non_empty_cells"] > 3:
        return _item(sheet_name, "entity_list", 0.68, True, ["Liste d'entités probable, sans besoins horaires complets."])
    if profile["has_tables"] and profile["non_empty_cells"] > 8:
        return _item(sheet_name, "mixed_sheet", 0.5, True, ["Feuille tabulaire mais rôle métier incertain."])
    return _item(sheet_name, "unknown_review", 0.35, True, ["Structure non reconnue avec assez de confiance."])


def _item(sheet_name: str, sheet_type: str, confidence: float, needs_review: bool, reasons: list[str]) -> dict[str, Any]:
    return {
        "sheet_name": sheet_name,
        "sheet_type": sheet_type,
        "confidence": round(confidence, 3),
        "needs_human_review": bool(needs_review),
        "reasons": reasons,
    }


def _average(items: list[dict[str, Any]]) -> float:
    if not items:
        return 0.0
    return round(sum(float(item["confidence"]) for item in items) / len(items), 3)


def _content_signals(sheet_name: str, sheet: Any | None) -> dict[str, Any]:
    values = [normalize_text(sheet_name)]
    cell_values: list[str] = []
    if sheet:
        for row in sheet.rows.values():
            for value in row.values():
                text = normalize_text(value)
                if text:
                    values.append(text)
                    cell_values.append(text)
    folded_values = [fold_key(value) for value in values if normalize_text(value)]
    folded_cells = [fold_key(value) for value in cell_values if normalize_text(value)]
    availability_markers = sum(1 for value in folded_cells if value in {fold_key(marker) for marker in AVAILABILITY_MARKERS})
    availability_hints = sum(1 for value in folded_values if any(hint in value for hint in AVAILABILITY_HINTS))
    constraint_hints = sum(1 for value in folded_values if any(hint in value for hint in CONSTRAINT_HINTS))
    constraint_sentences = sum(1 for value in folded_values if _looks_like_constraint_text(value))
    teacher_markers = sum(1 for value in cell_values if TEACHER_MARKER_PATTERN.search(value))
    lesson_like_cells = sum(1 for value in cell_values if _looks_like_lesson_cell(value))
    grid_value_cells = max(len(folded_cells), 1)
    return {
        "availability_markers": availability_markers,
        "availability_hints": availability_hints,
        "availability_marker_density": availability_markers / grid_value_cells,
        "constraint_hints": constraint_hints,
        "constraint_sentences": constraint_sentences,
        "teacher_markers": teacher_markers,
        "lesson_like_cells": lesson_like_cells,
    }


def _looks_like_availability_sheet(profile: dict[str, Any], signals: dict[str, Any]) -> bool:
    grid_shape = profile["day_cells"] >= 2 and profile["non_empty_cells"] >= 4
    strong_markers = signals["availability_markers"] >= 2 and signals["availability_marker_density"] >= 0.18
    weak_name_or_header = signals["availability_hints"] >= 1 and signals["availability_markers"] >= 1
    few_lessons = signals["lesson_like_cells"] <= max(1, signals["availability_markers"] // 3) and signals["teacher_markers"] == 0
    return grid_shape and few_lessons and (strong_markers or weak_name_or_header)


def _looks_like_constraints_sheet(signals: dict[str, Any]) -> bool:
    return signals["constraint_hints"] >= 1 and (signals["constraint_sentences"] >= 1 or signals["lesson_like_cells"] == 0)


def _looks_like_schedule_grid(profile: dict[str, Any], signals: dict[str, Any]) -> bool:
    if profile["day_cells"] < 2 or profile["time_cells"] < 1 or profile["non_empty_cells"] < 4:
        return False
    if signals["availability_marker_density"] >= 0.18 and signals["availability_markers"] >= max(2, signals["lesson_like_cells"]):
        return False
    if signals["constraint_hints"] >= 2 and signals["lesson_like_cells"] == 0:
        return False
    return signals["lesson_like_cells"] >= 2 or signals["teacher_markers"] >= 1


def _looks_like_lesson_cell(value: str) -> bool:
    text = normalize_text(value)
    folded = fold_key(text)
    if not text or folded in {fold_key(marker) for marker in AVAILABILITY_MARKERS} or _looks_like_constraint_text(folded):
        return False
    parsed, warnings = parse_lesson_cell(text)
    return bool(parsed.get("teacher") or parsed.get("class_name") or (TEACHER_MARKER_PATTERN.search(text) and parsed.get("subject")) or (parsed.get("subject") and not warnings and len(text.split()) >= 2))


def _looks_like_constraint_text(folded: str) -> bool:
    return bool(
        any(hint in folded for hint in CONSTRAINT_HINTS)
        or re.search(r"\b(?:pas|not)\s+(?:disponible|available)\b", folded)
        or "לא זמין" in folded
    )
