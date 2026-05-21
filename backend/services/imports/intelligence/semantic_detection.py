from __future__ import annotations

import re
from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportContext, source_trace
from backend.services.imports.intelligence.normalizers import day_key, is_time_like, normalize_text


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
        }
        headers_by_sheet = {item["sheet_name"]: item for item in context.headers}
        class_by_sheet = {item["sheet_name"]: item for item in context.sheet_classifications}
        seen = {key: set() for key in entities}
        for sheet in context.sheets:
            header = headers_by_sheet.get(sheet.name)
            classification = class_by_sheet.get(sheet.name, {})
            if header and classification.get("sheet_type") == "requirements_table":
                _extract_requirements(sheet, header, entities, seen)
            elif header and classification.get("sheet_type") == "teacher_availability":
                _extract_availability(sheet, header, entities, seen)
            elif classification.get("sheet_type") == "schedule_grid":
                _extract_grid_hints(sheet, entities, seen)
            elif classification.get("sheet_type") in {"constraints", "mixed_sheet", "unknown_review"}:
                _extract_constraints(sheet, entities, seen)
        context.semantic_entities = entities
        count = sum(len(value) for value in entities.values())
        return context.add_result(BrainResult(self.name, "ok", 0.82 if count else 0.3, data={"semantic_entities": entities}))


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


def _extract_grid_hints(sheet, entities: dict[str, Any], seen: dict[str, set[str]]) -> None:
    for row_index, row in sheet.rows.items():
        for column, value in row.items():
            text = normalize_text(value)
            if day_key(text):
                _add_entity(entities["weekdays"], seen["weekdays"], text, source_trace(sheet.name, row_index, column, text, 0.75))
            if is_time_like(text):
                _add_entity(entities["time_slots"], seen["time_slots"], text, source_trace(sheet.name, row_index, column, text, 0.75))


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
