from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.header_detection import detect_header_roles
from backend.services.imports.intelligence.models import BrainResult, ImportContext
from backend.services.imports.intelligence.normalizers import fold_key, is_day, is_time_like


METADATA_NAMES = {"sources", "source", "notes", "readme", "metadata", "manifest", "oracle", "debug", "test_notes", "expected_import"}


class WorkbookProfilingBrain:
    name = "workbook_profiling"

    def run(self, context: ImportContext) -> BrainResult:
        profiles = [_profile_sheet(sheet) for sheet in context.sheets]
        context.sheet_profiles = profiles
        languages = sorted({language for profile in profiles for language in profile["detected_languages"]})
        context.detected_language = "he" if "he" in languages else "fr" if "fr" in languages else "en" if "latin" in languages else None
        diagnostics = []
        if not profiles:
            diagnostics.append(diagnostic("empty_workbook", "blocking", "Aucune feuille lisible n'a été trouvée."))
        for profile in profiles:
            if profile["is_empty"]:
                diagnostics.append(diagnostic("empty_sheet", "warning", "Feuille vide ignorée.", sheet_name=profile["sheet_name"]))
            elif profile["is_very_small"]:
                diagnostics.append(diagnostic("very_small_sheet", "info", "Feuille très courte; extraction automatique prudente.", sheet_name=profile["sheet_name"]))
        return context.add_result(
            BrainResult(
                self.name,
                "error" if any(item.severity == "blocking" for item in diagnostics) else "ok",
                0.9 if profiles else 0.0,
                diagnostics,
                {"sheets_count": len(profiles), "detected_languages": languages, "sheet_profiles": profiles},
            )
        )


def _profile_sheet(sheet) -> dict[str, Any]:
    total_cells = max(sheet.max_row * sheet.max_column, 1)
    languages: set[str] = set()
    header_rows = 0
    day_cells = 0
    time_cells = 0
    text_cells = 0
    for row in sheet.rows.values():
        if detect_header_roles(row):
            header_rows += 1
        for value in row.values():
            text = str(value)
            if any("א" <= char <= "ת" for char in text):
                languages.add("he")
            if any(char in "éèêàùçôîï" for char in text.casefold()):
                languages.add("fr")
            if any("a" <= char <= "z" for char in text.casefold()):
                languages.add("latin")
            if is_day(text):
                day_cells += 1
            if is_time_like(text):
                time_cells += 1
            if text.strip():
                text_cells += 1
    folded_name = fold_key(sheet.name)
    is_metadata = folded_name in METADATA_NAMES or any(token in folded_name for token in METADATA_NAMES)
    non_empty = sheet.non_empty_cells_count
    return {
        "sheet_name": sheet.name,
        "max_row": sheet.max_row,
        "max_column": sheet.max_column,
        "non_empty_cells": non_empty,
        "density": round(non_empty / total_cells, 3),
        "detected_languages": sorted(languages),
        "has_tables": header_rows > 0,
        "header_candidate_rows": header_rows,
        "has_merged_cells": sheet.merged_cells_count > 0,
        "merged_cells_count": sheet.merged_cells_count,
        "is_empty": non_empty == 0,
        "is_very_small": 0 < non_empty <= 3,
        "is_probably_metadata": is_metadata,
        "day_cells": day_cells,
        "time_cells": time_cells,
        "text_cells": text_cells,
    }
