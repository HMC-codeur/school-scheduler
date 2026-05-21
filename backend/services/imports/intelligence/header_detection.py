from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.models import BrainResult, ImportContext
from backend.services.imports.intelligence.normalizers import fold_key, normalize_text


HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "class_name": ("classe", "classes", "niveau", "groupe", "class", "כיתה"),
    "teacher_name": ("professeur", "prof", "enseignant", "teacher", "מורה"),
    "subject_name": ("matiere", "matière", "discipline", "sujet", "subject", "מקצוע"),
    "weekly_hours": ("heures", "volume", "volume hebdo", "hours", "שעות"),
    "day": ("jour", "weekday", "day", "יום"),
    "time": ("horaire", "heure", "time", "slot", "שעה"),
    "availability": ("disponibilite", "disponibilité", "availability", "זמינות"),
    "constraint": ("contrainte", "constraint", "restriction", "אילוץ"),
}


class HeaderDetectionBrain:
    name = "header_detection"

    def run(self, context: ImportContext) -> BrainResult:
        headers: list[dict[str, Any]] = []
        diagnostics = []
        for sheet in context.sheets:
            best = _detect_sheet_header(sheet)
            if best:
                headers.append(best)
            elif sheet.non_empty_cells_count:
                diagnostics.append(
                    diagnostic(
                        "header_not_found",
                        "warning",
                        "Aucune ligne d'en-tête fiable détectée sur cette feuille.",
                        sheet_name=sheet.name,
                        suggestion="Vérifiez le mapping des colonnes avant d'importer.",
                        confidence=0.7,
                    )
                )
        context.headers = headers
        return context.add_result(
            BrainResult(
                self.name,
                "warning" if diagnostics else "ok",
                0.85 if headers else 0.35,
                diagnostics,
                {"headers": headers},
            )
        )


def detect_header_roles(row_values: dict[int, str]) -> dict[int, dict[str, Any]]:
    roles: dict[int, dict[str, Any]] = {}
    for column, value in row_values.items():
        folded = fold_key(value)
        for role, synonyms in HEADER_SYNONYMS.items():
            if folded in {fold_key(item) for item in synonyms} or any(fold_key(item) in folded for item in synonyms):
                roles[column] = {"role": role, "header": normalize_text(value), "confidence": 0.95 if folded in {fold_key(item) for item in synonyms} else 0.75}
                break
    return roles


def _detect_sheet_header(sheet) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for row_index in range(1, min(sheet.max_row, 12) + 1):
        row = sheet.rows.get(row_index, {})
        roles = detect_header_roles(row)
        if not roles:
            continue
        business_roles = {item["role"] for item in roles.values()}
        score = len(business_roles) + (2 if {"class_name", "subject_name", "weekly_hours"} & business_roles else 0)
        if best is None or score > best["score"]:
            best = {
                "sheet_name": sheet.name,
                "row": row_index,
                "score": score,
                "columns": [
                    {"column": column, **role}
                    for column, role in sorted(roles.items())
                ],
                "roles": sorted(business_roles),
                "confidence": min(0.98, 0.35 + score * 0.12),
            }
    return best
