from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportContext


SHEET_TYPES = {
    "schedule_grid",
    "requirements_table",
    "teacher_availability",
    "constraints",
    "entity_list",
    "metadata",
    "mixed_sheet",
    "ignored",
    "unknown_review",
}


class SheetClassificationBrain:
    name = "sheet_classification"

    def run(self, context: ImportContext) -> BrainResult:
        classifications = [_classify(profile, context.headers) for profile in context.sheet_profiles]
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


def _classify(profile: dict[str, Any], headers: list[dict[str, Any]]) -> dict[str, Any]:
    sheet_name = profile["sheet_name"]
    header = next((item for item in headers if item["sheet_name"] == sheet_name), None)
    roles = set(header.get("roles", [])) if header else set()
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
    if profile["day_cells"] >= 2 and profile["time_cells"] >= 1 and profile["non_empty_cells"] >= 4:
        return _item(sheet_name, "schedule_grid", 0.76, True, ["Grille avec jours et créneaux détectée; review recommandée avant extraction."])
    if "constraint" in roles:
        return _item(sheet_name, "constraints", 0.8, True, ["Colonnes ou texte de contraintes détectés."])
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
