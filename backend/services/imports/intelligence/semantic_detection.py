from __future__ import annotations

import re
from typing import Any

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.models import BrainResult, ImportContext, source_trace
from backend.services.imports.intelligence.normalizers import day_key, is_time_like, looks_like_class_token, normalize_text, parse_lesson_cell


class SemanticDetectionBrain:
    name = "semantic_detection"

    def run(self, context: ImportContext) -> BrainResult:
        entities = {
            "classes": [],
            "teachers": [],
            "subjects": [],
            "weekdays": [],
            "time_slots": [],
            "requirements": [],
            "availability": [],
            "constraints": [],
            "schedule_grid_preview": [],
            "lesson_candidates": [],
        }
        diagnostics = []
        headers_by_sheet = {item["sheet_name"]: item for item in context.headers}
        class_by_sheet = {item["sheet_name"]: item for item in context.sheet_classifications}
        seen = {key: set() for key in entities}
        for sheet in context.sheets:
            header = headers_by_sheet.get(sheet.name)
            classification = class_by_sheet.get(sheet.name, {})
            if header and classification.get("sheet_type") == "requirements_table":
                _extract_requirements(sheet, header, entities, seen)
            elif classification.get("sheet_type") in {"teacher_availability", "availability_table"}:
                diagnostics.append(diagnostic("teacher_availability_detected", "info", "Feuille de disponibilités détectée; aucun cours ne sera extrait de cette feuille.", sheet_name=sheet.name, confidence=0.86))
                diagnostics.append(diagnostic("availability_sheet_detected", "info", "Grille de disponibilités détectée; schedule_grid rejeté.", sheet_name=sheet.name, confidence=0.86))
                if header:
                    _extract_availability(sheet, header, entities, seen)
            elif classification.get("sheet_type") == "schedule_grid":
                diagnostics.extend(_extract_schedule_grid_preview(sheet, entities, seen))
            elif classification.get("sheet_type") in {"constraints", "constraints_table", "constraints_text", "mixed_sheet", "unknown_review"}:
                if classification.get("sheet_type") in {"constraints", "constraints_table", "constraints_text"}:
                    diagnostics.append(diagnostic("constraints_sheet_detected", "info", "Feuille de contraintes détectée; aucun cours ne sera extrait de cette feuille.", sheet_name=sheet.name, confidence=0.82))
                _extract_constraints(sheet, entities, seen)
        context.semantic_entities = entities
        count = sum(len(value) for value in entities.values())
        status = "needs_review" if diagnostics else "ok"
        return context.add_result(BrainResult(self.name, status, 0.82 if count else 0.3, diagnostics, {"semantic_entities": entities}))


def _columns(header: dict[str, Any]) -> dict[str, int]:
    return {item["role"]: int(item["column"]) for item in header.get("columns", [])}


def _add_entity(bucket: list[dict[str, Any]], seen: set[str], value: str, trace: dict[str, Any]) -> None:
    cleaned = normalize_text(value)
    if not cleaned:
        return
    key = cleaned.casefold()
    if key in seen:
        return
    seen.add(key)
    bucket.append({"name": cleaned, "confidence": trace["confidence"], "source_trace": trace})


def _extract_requirements(sheet, header: dict[str, Any], entities: dict[str, Any], seen: dict[str, set[str]]) -> None:
    cols = _columns(header)
    for row_index in range(int(header["row"]) + 1, sheet.max_row + 1):
        row = sheet.rows.get(row_index, {})
        class_name = normalize_text(row.get(cols.get("class_name", -1), ""))
        subject = normalize_text(row.get(cols.get("subject_name", -1), ""))
        teacher = normalize_text(row.get(cols.get("teacher_name", -1), ""))
        hours_raw = normalize_text(row.get(cols.get("weekly_hours", -1), ""))
        if not any([class_name, subject, teacher, hours_raw]):
            continue
        confidence = 0.9 if class_name and subject and hours_raw else 0.55
        if class_name:
            _add_entity(entities["classes"], seen["classes"], class_name, source_trace(sheet.name, row_index, cols.get("class_name"), class_name, confidence))
        if subject:
            _add_entity(entities["subjects"], seen["subjects"], subject, source_trace(sheet.name, row_index, cols.get("subject_name"), subject, confidence))
        if teacher:
            _add_entity(entities["teachers"], seen["teachers"], teacher, source_trace(sheet.name, row_index, cols.get("teacher_name"), teacher, confidence))
        entities["requirements"].append(
            {
                "class_name": class_name or None,
                "subject_name": subject or None,
                "teacher_name": teacher or None,
                "weekly_hours": _parse_hours(hours_raw),
                "raw_weekly_hours": hours_raw or None,
                "confidence": confidence,
                "source_trace": source_trace(sheet.name, row_index, None, dict(row), confidence),
            }
        )


def _extract_availability(sheet, header: dict[str, Any], entities: dict[str, Any], seen: dict[str, set[str]]) -> None:
    cols = _columns(header)
    for row_index in range(int(header["row"]) + 1, sheet.max_row + 1):
        row = sheet.rows.get(row_index, {})
        teacher = normalize_text(row.get(cols.get("teacher_name", -1), ""))
        day = normalize_text(row.get(cols.get("day", -1), ""))
        time = normalize_text(row.get(cols.get("time", -1), ""))
        value = normalize_text(row.get(cols.get("availability", -1), ""))
        if not any([teacher, day, time, value]):
            continue
        confidence = 0.85 if teacher and value else 0.55
        if teacher:
            _add_entity(entities["teachers"], seen["teachers"], teacher, source_trace(sheet.name, row_index, cols.get("teacher_name"), teacher, confidence))
        if day:
            _add_entity(entities["weekdays"], seen["weekdays"], day, source_trace(sheet.name, row_index, cols.get("day"), day, confidence))
        if time:
            _add_entity(entities["time_slots"], seen["time_slots"], time, source_trace(sheet.name, row_index, cols.get("time"), time, confidence))
        entities["availability"].append(
            {
                "teacher_name": teacher or None,
                "day": day or None,
                "time": time or None,
                "availability": value or None,
                "confidence": confidence,
                "source_trace": source_trace(sheet.name, row_index, None, dict(row), confidence),
            }
        )


def _extract_schedule_grid_preview(sheet, entities: dict[str, Any], seen: dict[str, set[str]]) -> list[Any]:
    diagnostics = [
        diagnostic("schedule_grid_detected", "info", "Grille de planning détectée.", sheet_name=sheet.name, confidence=0.8),
        diagnostic("schedule_grid_preview_only", "warning", "Grille planning analysée en aperçu uniquement.", sheet_name=sheet.name, suggestion="Validez les cours détectés avant tout import.", confidence=0.8),
        diagnostic("schedule_grid_requires_confirmation", "warning", "Validation humaine obligatoire avant import de cette grille.", sheet_name=sheet.name, confidence=0.85),
    ]
    for row_index, row in sheet.rows.items():
        for column, value in row.items():
            text = normalize_text(value)
            if day_key(text):
                _add_entity(entities["weekdays"], seen["weekdays"], text, source_trace(sheet.name, row_index, column, text, 0.75))
            if is_time_like(text):
                _add_entity(entities["time_slots"], seen["time_slots"], text, source_trace(sheet.name, row_index, column, text, 0.75))
    candidates, low_confidence = _extract_column_day_grid(sheet)
    entities["schedule_grid_preview"].extend(candidates)
    entities["lesson_candidates"].extend(candidates)
    diagnostics.extend(
        diagnostic(
            "low_confidence_grid_cell",
            "info",
            "Cellule de grille extraite avec confiance faible.",
            sheet_name=sheet.name,
            row=item["source_trace"].get("row"),
            column=item["source_trace"].get("column"),
            suggestion="Confirmez la matière, le professeur ou la classe.",
            confidence=item.get("confidence", 0.45),
        )
        for item in low_confidence[:8]
    )
    return diagnostics


def _extract_column_day_grid(sheet) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    day_headers_by_row: dict[int, list[tuple[int, str, str]]] = {}
    for row_index, row in sheet.rows.items():
        for column, value in row.items():
            text = normalize_text(value)
            key = day_key(text)
            if key:
                day_headers_by_row.setdefault(row_index, []).append((column, text, key))
    candidates: list[dict[str, Any]] = []
    low_confidence: list[dict[str, Any]] = []
    seen_cells: set[tuple[int, int]] = set()
    for header_row, day_headers in day_headers_by_row.items():
        ordered_headers = sorted(day_headers, key=lambda item: item[0])
        for index, (start_column, day_label, _) in enumerate(ordered_headers):
            next_column = ordered_headers[index + 1][0] if index + 1 < len(ordered_headers) else sheet.max_column + 1
            for row_index in range(header_row + 1, sheet.max_row + 1):
                time_label = _time_for_row(sheet, row_index, start_column, next_column)
                if not time_label:
                    continue
                for column in range(start_column, min(next_column, sheet.max_column + 1)):
                    if (row_index, column) in seen_cells:
                        continue
                    raw_cell = normalize_text(sheet.rows.get(row_index, {}).get(column, ""))
                    if not raw_cell or day_key(raw_cell) or is_time_like(raw_cell) or looks_like_class_token(raw_cell):
                        continue
                    seen_cells.add((row_index, column))
                    parsed, warnings = parse_lesson_cell(raw_cell)
                    class_name = parsed.get("class_name") or _class_for_column(sheet, header_row, row_index, column)
                    subject = parsed.get("subject")
                    teacher = parsed.get("teacher")
                    confidence = _grid_cell_confidence(class_name, day_label, time_label, raw_cell, subject, teacher, warnings)
                    item = {
                        "class_name": class_name,
                        "day": day_label,
                        "time": time_label,
                        "slot": f"{day_label} {time_label}".strip(),
                        "raw_cell": raw_cell,
                        "subject": subject,
                        "teacher": teacher,
                        "confidence": confidence,
                        "source_trace": source_trace(sheet.name, row_index, column, raw_cell, confidence),
                    }
                    candidates.append(item)
                    if confidence < 0.6:
                        low_confidence.append(item)
    return candidates, low_confidence


def _time_for_row(sheet, row_index: int, start_column: int, next_column: int) -> str | None:
    row = sheet.rows.get(row_index, {})
    for column in range(1, start_column):
        value = normalize_text(row.get(column, ""))
        if is_time_like(value):
            return value
    for column in range(next_column, sheet.max_column + 1):
        value = normalize_text(row.get(column, ""))
        if is_time_like(value):
            return value
    return None


def _class_for_column(sheet, header_row: int, row_index: int, column: int) -> str | None:
    for lookup_row in range(row_index - 1, header_row, -1):
        value = normalize_text(sheet.rows.get(lookup_row, {}).get(column, ""))
        if looks_like_class_token(value):
            return value
    for lookup_column in range(column - 1, 0, -1):
        value = normalize_text(sheet.rows.get(row_index, {}).get(lookup_column, ""))
        if looks_like_class_token(value):
            return value
        if is_time_like(value) or day_key(value):
            break
    return None


def _grid_cell_confidence(class_name: str | None, day: str | None, time: str | None, raw_cell: str, subject: str | None, teacher: str | None, warnings: list[str]) -> float:
    score = 0.35
    if class_name:
        score += 0.18
    if day:
        score += 0.12
    if time:
        score += 0.12
    if subject and subject != raw_cell:
        score += 0.08
    elif subject:
        score += 0.04
    if teacher:
        score += 0.12
    if warnings:
        score -= 0.08
    return round(max(0.35, min(score, 0.86)), 3)


def _extract_constraints(sheet, entities: dict[str, Any], seen: dict[str, set[str]]) -> None:
    for row_index, row in sheet.rows.items():
        text = " ".join(normalize_text(value) for value in row.values() if normalize_text(value))
        if len(text) >= 12 and re.search(r"pas|avoid|éviter|indisponible|contrainte|לא זמין|אסור", text, re.IGNORECASE):
            entities["constraints"].append({"text": text, "confidence": 0.55, "source_trace": source_trace(sheet.name, row_index, None, text, 0.55)})


def _parse_hours(value: Any) -> int | float | None:
    text = normalize_text(value).replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number
