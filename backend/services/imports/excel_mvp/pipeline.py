from __future__ import annotations

import os
import re
from typing import Any
from uuid import uuid4

from backend.models.schemas import ImportedLesson
from backend.services.imports.excel_inspector import ExcelInspection, SheetInspection, inspection_from_reader_result
from backend.services.imports.excel_intelligence.confidence_engine import score_workbook
from backend.services.imports.excel_intelligence.entity_extractor import extract_sheet_entities
from backend.services.imports.excel_intelligence.human_validation import build_validation_questions
from backend.services.imports.excel_intelligence.hypothesis_engine import evaluate_sheet
from backend.services.imports.excel_intelligence.normalization import normalize_workbook_entities
from backend.services.imports.excel_intelligence.parser_selector import select_parser
from backend.services.imports.excel_intelligence.pattern_detector import detect_sheet_patterns
from backend.services.imports.excel_intelligence.role_detector import CLASS_ROLE, HOURS_ROLE, SUBJECT_ROLE, TEACHER_ROLE, is_availability_marker
from backend.services.imports.excel_intelligence.sheet_classifier import classify_sheet
from backend.services.imports.excel_intelligence.sheet_profiler import SheetProfile, profile_sheet
from backend.services.imports.excel_intelligence.workbook_observer import observe_workbook
from backend.services.imports.excel_mvp.column_mapper import ColumnMapping, SYNONYMS, STANDARD_FIELDS, map_columns, mappings_as_dicts
from backend.services.imports.excel_mvp.diagnostics import build_diagnostics, diagnostic
from backend.services.imports.excel_mvp.draft_store import save_import_draft
from backend.services.imports.excel_mvp.entity_extractor import extract_entities, merge_extracted_entities
from backend.services.imports.excel_mvp.normalizer import is_empty_row, normalize_string, parse_number
from backend.services.imports.excel_mvp.reader import ExcelRow, ExcelSheet
from backend.services.imports.excel_mvp.table_detector import detect_table
from backend.services.imports.excel_readers import read_excel_with_fallback
from backend.services.imports.normalizers import fold_key, is_day, is_time_like, normalize_header, normalize_text
from backend.services.imports.parsers import grid_days_columns_parser, grid_days_rows_parser
from backend.services.imports.parsers.common import ParserResult


METADATA_OR_ORACLE_SHEET_NAMES = {
    "expected_import",
    "test_notes",
    "sources",
    "source",
    "readme",
    "manifest",
    "00_manifest",
    "notes",
    "debug",
    "oracle",
}

REVIEW_ONLY_SHEET_KINDS = {
    "constraints_text",
    "entity_list",
    "mixed_list",
    "metadata_or_oracle",
    "unknown",
}

AUTO_EXTRACTION_SHEET_KINDS = {"requirements_table", "schedule_grid", "availability_grid"}


def analyze_excel_content(content: bytes, filename: str | None = None, corrections: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = os.getenv("EXCEL_INTELLIGENCE_MODE", "v1").strip().lower()
    if mode == "v2":
        return _analyze_excel_content_v2(content, filename, corrections=corrections)
    return _analyze_excel_content_v1(content, filename, corrections=corrections)


def analyze_excel_content_debug_compare(content: bytes, filename: str | None = None, corrections: dict[str, Any] | None = None) -> dict[str, Any]:
    result_v1 = _analyze_excel_content_v1(content, filename, corrections=corrections)
    result_v2 = _analyze_excel_content_v2(content, filename, corrections=corrections)
    primary_mode = "v2" if os.getenv("EXCEL_INTELLIGENCE_MODE", "v1").strip().lower() == "v2" else "v1"
    compare = _compare_excel_intelligence(result_v1, result_v2, primary_mode=primary_mode)
    primary_result = result_v2 if primary_mode == "v2" else result_v1
    primary_result.update(
        {
            "debug_compare": True,
            "primary_result_engine": primary_mode,
            "excel_intelligence_compare": compare,
            "v1_result": compare["v1_result"],
            "v2_result": compare["v2_result"],
        }
    )
    return primary_result


def _analyze_excel_content_v1(content: bytes, filename: str | None = None, corrections: dict[str, Any] | None = None) -> dict[str, Any]:
    reader_result = read_excel_with_fallback(content, filename)
    inspection = inspection_from_reader_result(reader_result, filename)
    sheet_results = [_apply_sheet_override(_analyze_sheet(inspection, sheet), inspection, sheet, _sheet_override(corrections, sheet.name)) for sheet in inspection.sheets]
    workbook_observation = observe_workbook(inspection)
    intelligence_by_sheet = _build_excel_intelligence(inspection, workbook_observation, sheet_results)
    requirements_sheets = [item for item in sheet_results if item["detected_format"] == "requirements_table"]
    extracted_entities = merge_extracted_entities([item["_requirements_entities"] for item in requirements_sheets])
    scheduled_lessons = [
        lesson
        for item in sheet_results
        for lesson in item.get("extracted_entities", {}).get("scheduled_lessons", [])
    ]

    summary = _legacy_summary(sheet_results, extracted_entities)
    diagnostics = _legacy_diagnostics(requirements_sheets, extracted_entities)
    import_id = f"analysis_{uuid4().hex[:12]}"
    detected_formats = _unique([item["detected_format"] for item in sheet_results])
    public_sheets = []
    for item in sheet_results:
        public_item = {key: value for key, value in item.items() if not key.startswith("_")}
        public_item.update(intelligence_by_sheet.get(public_item["sheet_name"], {}))
        public_sheets.append(public_item)
    confidence = score_workbook(public_sheets)
    normalized_entities = normalize_workbook_entities(
        public_sheets,
        {
            **extracted_entities,
            "scheduled_lessons": scheduled_lessons,
        },
    )
    _annotate_sheet_statuses(public_sheets)
    validation_questions = build_validation_questions(workbook_observation, public_sheets, confidence)
    result = {
        "import_id": import_id,
        "filename": filename,
        "engine_used": "v1",
        "debug_compare": False,
        "primary_result_engine": "v1",
        "reader_used": reader_result["reader_used"],
        "reader_attempts": reader_result["reader_attempts"],
        "reader_warnings": reader_result["reader_warnings"],
        "workbook_summary": {
            "sheets_count": len(inspection.sheets),
            "detected_formats": detected_formats,
            "reader_engine": inspection.reader_engine,
            "reader_used": reader_result["reader_used"],
            "observed": workbook_observation,
            "confidence": confidence["global_confidence"],
        },
        "sheets": public_sheets,
        "global_diagnostics": _global_diagnostics(inspection, public_sheets),
        "needs_human_mapping": any(item["detected_format"] == "unknown" for item in public_sheets),
        "needs_human_validation": bool(validation_questions),
        "validation_questions": validation_questions,
        "normalized_entities": normalized_entities,
        "confidence": confidence,
        "sheets_detected": [sheet.name for sheet in inspection.sheets],
        "tables": [table for item in requirements_sheets for table in item.get("_tables", [])],
        "detected_columns": [column for item in requirements_sheets for column in item.get("_detected_columns", [])],
        "unmapped_columns": [column for item in requirements_sheets for column in item.get("_unmapped_columns", [])],
        "extracted_entities": {
            **extracted_entities,
            "scheduled_lessons": scheduled_lessons,
        },
        "diagnostics": diagnostics,
        "summary": _augment_summary(summary, public_sheets, scheduled_lessons, []),
        "confidence_score": confidence["global_confidence"],
        "can_commit": not bool(diagnostics.get("blocking")),
    }
    save_import_draft(result)
    return result


def _compare_excel_intelligence(result_v1: dict[str, Any], result_v2: dict[str, Any], primary_mode: str = "v1") -> dict[str, Any]:
    sheets_v1 = {sheet.get("sheet_name"): sheet for sheet in result_v1.get("sheets", [])}
    sheets_v2 = {sheet.get("sheet_name"): sheet for sheet in result_v2.get("sheets", [])}
    sheet_names = _unique([*sheets_v1.keys(), *sheets_v2.keys()])
    sheets = [_compare_sheet(sheets_v1.get(name), sheets_v2.get(name)) for name in sheet_names]
    improvements = [item for item in sheets if item.get("classification_change") == "improved"]
    regressions = [item for item in sheets if item.get("classification_change") == "regressed"]
    changed = [item for item in sheets if item.get("v1_format") != item.get("v2_format")]
    return {
        "mode": "debug_compare_v1_v2",
        "primary_mode": primary_mode,
        "primary_result_engine": primary_mode,
        "v2_default_enabled": False,
        "v1_result": _compact_compare_result(result_v1),
        "v2_result": _compact_compare_result(result_v2),
        "summary": {
            "v1_detected_formats": result_v1.get("workbook_summary", {}).get("detected_formats", []),
            "v2_detected_formats": result_v2.get("workbook_summary", {}).get("detected_formats", []),
            "v1_confidence": result_v1.get("confidence_score"),
            "v2_confidence": result_v2.get("confidence_score"),
            "v1_requirements": result_v1.get("summary", {}).get("requirements_detected", 0),
            "v2_requirements": result_v2.get("summary", {}).get("requirements_detected", 0),
            "v1_scheduled_lessons": result_v1.get("summary", {}).get("scheduled_lessons_detected", 0),
            "v2_scheduled_lessons": result_v2.get("summary", {}).get("scheduled_lessons_detected", 0),
            "v2_availability_entries": len(result_v2.get("extracted_entities", {}).get("teacher_availability", [])),
            "changed_sheets": len(changed),
            "improvements": len(improvements),
            "regressions": len(regressions),
        },
        "sheets": sheets,
        "regressions": regressions,
        "improvements": improvements,
        "result_v2": _compact_compare_result(result_v2),
    }


def _compare_sheet(sheet_v1: dict[str, Any] | None, sheet_v2: dict[str, Any] | None) -> dict[str, Any]:
    v1_format = sheet_v1.get("detected_format") if sheet_v1 else None
    v2_format = sheet_v2.get("detected_format") if sheet_v2 else None
    v1_structured = v1_format not in {None, "unknown", "noisy"}
    v2_structured = v2_format not in {None, "unknown", "noisy"}
    if not v1_structured and v2_structured:
        change = "improved"
    elif v1_structured and not v2_structured:
        change = "regressed"
    elif v1_format != v2_format:
        change = "changed"
    else:
        change = "same"
    return {
        "sheet_name": (sheet_v1 or sheet_v2 or {}).get("sheet_name"),
        "classification_change": change,
        "v1_result": _compact_compare_sheet(sheet_v1),
        "v2_result": _compact_compare_sheet(sheet_v2),
        "v1_format": v1_format,
        "v2_format": v2_format,
        "v1_confidence": sheet_v1.get("confidence") if sheet_v1 else None,
        "v2_confidence": sheet_v2.get("confidence") if sheet_v2 else None,
        "v1_summary": sheet_v1.get("summary", {}) if sheet_v1 else {},
        "v2_summary": sheet_v2.get("summary", {}) if sheet_v2 else {},
        "v2_diagnostic_summary": sheet_v2.get("diagnostic_summary", {}) if sheet_v2 else {},
        "v2_parser_selection": sheet_v2.get("parser_selection", {}) if sheet_v2 else {},
        "v2_possible_types": sheet_v2.get("possible_types", []) if sheet_v2 else [],
    }


def _compact_compare_sheet(sheet: dict[str, Any] | None) -> dict[str, Any]:
    if not sheet:
        return {}
    return {
        "sheet_name": sheet.get("sheet_name"),
        "detected_format": sheet.get("detected_format"),
        "confidence": sheet.get("confidence"),
        "summary": sheet.get("summary", {}),
        "diagnostic_summary": sheet.get("diagnostic_summary", {}),
        "parser_selection": sheet.get("parser_selection", {}),
        "possible_types": sheet.get("possible_types", []),
        "scheduled_lessons_count": len(sheet.get("extracted_entities", {}).get("scheduled_lessons", [])),
        "teacher_availability_count": len(sheet.get("extracted_entities", {}).get("teacher_availability", [])),
    }


def _compact_compare_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine_used": result.get("engine_used"),
        "excel_intelligence_mode": result.get("excel_intelligence_mode"),
        "workbook_summary": result.get("workbook_summary"),
        "summary": result.get("summary"),
        "confidence_score": result.get("confidence_score"),
        "needs_human_mapping": result.get("needs_human_mapping"),
        "needs_human_validation": result.get("needs_human_validation"),
        "sheets": [
            {
                "sheet_name": sheet.get("sheet_name"),
                "detected_format": sheet.get("detected_format"),
                "confidence": sheet.get("confidence"),
                "summary": sheet.get("summary"),
                "diagnostic_summary": sheet.get("diagnostic_summary"),
                "parser_selection": sheet.get("parser_selection"),
                "possible_types": sheet.get("possible_types"),
                "diagnostics": sheet.get("diagnostics"),
            }
            for sheet in result.get("sheets", [])
        ],
    }


def _analyze_excel_content_v2(content: bytes, filename: str | None = None, corrections: dict[str, Any] | None = None) -> dict[str, Any]:
    reader_result = read_excel_with_fallback(content, filename)
    inspection = inspection_from_reader_result(reader_result, filename)
    workbook_observation = observe_workbook(inspection)
    sheet_results = [_apply_sheet_override(_analyze_sheet_v2(inspection, sheet), inspection, sheet, _sheet_override(corrections, sheet.name)) for sheet in inspection.sheets]
    requirements_sheets = [item for item in sheet_results if item["detected_format"] == "requirements_table"]
    extracted_entities = merge_extracted_entities([item["_requirements_entities"] for item in requirements_sheets])
    scheduled_lessons = [
        lesson
        for item in sheet_results
        for lesson in item.get("extracted_entities", {}).get("scheduled_lessons", [])
    ]
    teacher_availability = [
        entry
        for item in sheet_results
        for entry in item.get("extracted_entities", {}).get("teacher_availability", [])
    ]

    summary = _legacy_summary(sheet_results, extracted_entities)
    diagnostics = _legacy_diagnostics(requirements_sheets, extracted_entities)
    import_id = f"analysis_{uuid4().hex[:12]}"
    public_sheets = [{key: value for key, value in item.items() if not key.startswith("_")} for item in sheet_results]
    confidence = score_workbook(public_sheets)
    normalized_entities = normalize_workbook_entities(
        public_sheets,
        {
            **extracted_entities,
            "scheduled_lessons": scheduled_lessons,
            "teacher_availability": teacher_availability,
        },
    )
    _annotate_sheet_statuses(public_sheets)
    validation_questions = build_validation_questions(workbook_observation, public_sheets, confidence)
    result = {
        "import_id": import_id,
        "filename": filename,
        "engine_used": "v2",
        "excel_intelligence_mode": "v2",
        "debug_compare": False,
        "primary_result_engine": "v2",
        "reader_used": reader_result["reader_used"],
        "reader_attempts": reader_result["reader_attempts"],
        "reader_warnings": reader_result["reader_warnings"],
        "workbook_summary": {
            "sheets_count": len(inspection.sheets),
            "detected_formats": _unique([item["detected_format"] for item in sheet_results]),
            "reader_engine": inspection.reader_engine,
            "reader_used": reader_result["reader_used"],
            "observed": workbook_observation,
            "confidence": confidence["global_confidence"],
        },
        "sheets": public_sheets,
        "global_diagnostics": _global_diagnostics(inspection, public_sheets),
        "needs_human_mapping": any(item["detected_format"] in {"unknown", "noisy"} for item in public_sheets),
        "needs_human_validation": bool(validation_questions),
        "validation_questions": validation_questions,
        "normalized_entities": normalized_entities,
        "confidence": confidence,
        "sheets_detected": [sheet.name for sheet in inspection.sheets],
        "tables": [table for item in requirements_sheets for table in item.get("_tables", [])],
        "detected_columns": [column for item in requirements_sheets for column in item.get("_detected_columns", [])],
        "unmapped_columns": [column for item in requirements_sheets for column in item.get("_unmapped_columns", [])],
        "extracted_entities": {
            **extracted_entities,
            "scheduled_lessons": scheduled_lessons,
            "teacher_availability": teacher_availability,
        },
        "diagnostics": diagnostics,
        "summary": _augment_summary(summary, public_sheets, scheduled_lessons, teacher_availability),
        "confidence_score": confidence["global_confidence"],
        "can_commit": not bool(diagnostics.get("blocking")),
    }
    save_import_draft(result)
    return result


def _analyze_sheet_v2(inspection: ExcelInspection, sheet: SheetInspection) -> dict[str, Any]:
    profile = profile_sheet(sheet)
    hypothesis = evaluate_sheet(profile)
    cautious_kind = _cautious_sheet_kind(sheet, profile, hypothesis)
    if cautious_kind:
        hypothesis["detected_format"] = cautious_kind["sheet_kind"]
        hypothesis["confidence"] = cautious_kind["confidence"]
        hypothesis["reasons"] = cautious_kind["reasons"]
        hypothesis["hypotheses"] = _prepend_hypothesis(hypothesis["hypotheses"], cautious_kind)

    selection = select_parser(hypothesis["detected_format"], int(hypothesis["confidence"]))
    detected_format = hypothesis["detected_format"]
    if selection.parser_name == "requirements_parser":
        result = _analyze_requirements_sheet(sheet, guard_requirements=True, profile=profile)
        guardrail_status = result.get("requirements_validation", {}).get("status")
        if guardrail_status == "ignored":
            detected_format = "unknown"
            hypothesis["detected_format"] = detected_format
            hypothesis["confidence"] = min(int(hypothesis["confidence"]), 39)
            result = _review_only_sheet_v2(
                sheet,
                "unknown",
                int(hypothesis["confidence"]),
                "Requirements guardrail rejected automatic extraction.",
                needs_review=True,
                diagnostics=result.get("diagnostics", []),
            )
        elif guardrail_status == "needs_review":
            result["needs_human_review"] = True
    elif selection.parser_name == "schedule_grid_parser":
        result = _analyze_schedule_grid_sheet(inspection, sheet, guard_availability_markers=True)
    elif selection.parser_name == "availability_parser":
        result = _analyze_availability_sheet_v2(sheet, profile)
    else:
        result = _review_only_sheet_v2(
            sheet,
            detected_format,
            int(hypothesis["confidence"]),
            selection.reason,
            needs_review=detected_format != "metadata_or_oracle",
        )

    result["detected_format"] = detected_format
    result["sheet_kind"] = detected_format
    result.setdefault("import_action", _import_action_for_sheet_kind(detected_format, int(hypothesis["confidence"])))
    result.setdefault("needs_human_review", result["import_action"] == "candidate_review")
    result["confidence"] = int(hypothesis["confidence"])
    result.setdefault("summary", {})["rows_read"] = sheet.max_row
    result["sheet_profile"] = profile.as_dict()
    result["hypotheses"] = hypothesis["hypotheses"]
    result["possible_types"] = [{"type": item["format"], "confidence": round(item["score"] / 100, 2), "reasons": item.get("reasons", [])} for item in hypothesis["hypotheses"][:4]]
    result["parser_selection"] = selection.as_dict()
    result["diagnostic_summary"] = _sheet_diagnostic_summary(result, hypothesis, selection.reason)
    result["diagnostics"] = [*result.get("diagnostics", []), *_classification_diagnostics(result, hypothesis, selection.reason)]
    result["diagnostics"] = [*_profile_diagnostics(profile, result), *result["diagnostics"]]
    result["diagnostics"] = _filter_sheet_diagnostics_for_kind(result["diagnostics"], detected_format)
    result.setdefault("_requirements_entities", {"classes": [], "teachers": [], "subjects": [], "requirements": []})
    return result


def _cautious_sheet_kind(sheet: SheetInspection, profile: SheetProfile, hypothesis: dict[str, Any]) -> dict[str, Any] | None:
    metadata_match = _metadata_or_oracle_sheet_name(sheet.name)
    if metadata_match:
        return {
            "sheet_kind": "metadata_or_oracle",
            "confidence": 100,
            "reasons": [f"Sheet name '{sheet.name}' is reserved for metadata, test oracle, notes or debug data."],
        }

    constraint_score, constraint_reasons = _constraints_text_score(sheet, profile)
    mixed_score, mixed_reasons = _mixed_list_score(sheet, profile)
    entity_score, entity_reasons = _entity_list_score(sheet, profile)

    if constraint_score >= 70:
        return {"sheet_kind": "constraints_text", "confidence": constraint_score, "reasons": constraint_reasons}
    if mixed_score >= 70:
        return {"sheet_kind": "mixed_list", "confidence": mixed_score, "reasons": mixed_reasons}
    if entity_score >= 72:
        return {"sheet_kind": "entity_list", "confidence": entity_score, "reasons": entity_reasons}

    detected = str(hypothesis.get("detected_format") or "unknown")
    confidence = int(hypothesis.get("confidence") or 0)
    if confidence < 40 and detected == "unknown":
        return {"sheet_kind": "unknown", "confidence": confidence, "reasons": ["Low confidence across importable sheet types."]}
    return None


def _metadata_or_oracle_sheet_name(sheet_name: str) -> bool:
    if sheet_name.strip() == "Notes":
        return True
    folded = fold_key(sheet_name).replace(" ", "_").replace("-", "_")
    compact = re.sub(r"_+", "_", folded).strip("_")
    return compact in (METADATA_OR_ORACLE_SHEET_NAMES - {"notes"})


def _constraints_text_score(sheet: SheetInspection, profile: SheetProfile) -> tuple[int, list[str]]:
    if profile.availability_marker_density >= 0.18 and sheet.max_column >= 3:
        return 0, []
    values = _sheet_text_values(sheet)
    if not values:
        return 0, []
    hits = sum(1 for value in values if _looks_like_constraint_text(value))
    longish = sum(1 for value in values if len(value) >= 22 or len(value.split()) >= 5)
    sentence_ratio = (hits + min(longish, hits)) / max(len(values), 1)
    name_hint = _sheet_name_has_any(sheet.name, ("contrainte", "constraint", "אילוץ", "אילוצים", "מגבלה", "מגבלות"))
    score = int(round(min(100, hits * 18 + sentence_ratio * 55 + (20 if name_hint else 0) + profile.free_text_noise_score * 15)))
    reasons: list[str] = []
    if name_hint:
        reasons.append("Sheet name suggests free-form constraints")
    if hits:
        reasons.append(f"{hits} constraint-like sentence(s) detected")
    if profile.free_text_noise_score >= 0.35:
        reasons.append("Free text dominates the sheet")
    return score, reasons


def _mixed_list_score(sheet: SheetInspection, profile: SheetProfile) -> tuple[int, list[str]]:
    if _has_coherent_requirements_header(profile):
        return 0, []
    values = [fold_key(value) for value in _sheet_text_values(sheet)]
    teacher_hits = sum(1 for value in values if any(token in value for token in ("teacher", "prof", "professeur", "מורה", "rav", "rabbi", "רב")))
    class_hits = sum(1 for value in values if any(token in value for token in ("class", "classe", "כיתה", "groupe")))
    subject_hits = sum(1 for value in values if any(token in value for token in ("subject", "matiere", "matière", "מקצוע")))
    remark_hits = sum(1 for value in values if any(token in value for token in ("remarque", "note", "comment", "constraint", "contrainte", "אילוץ")))
    categories = sum(1 for count in (teacher_hits, class_hits, subject_hits, remark_hits) if count)
    name_hint = _sheet_name_has_any(sheet.name, ("liste", "list", "profs", "classes", "רשימה", "רשימות", "מבולגן"))
    score = int(round(min(100, categories * 22 + (18 if name_hint else 0) + profile.table_shape_score * 18)))
    reasons: list[str] = []
    if name_hint:
        reasons.append("Sheet name suggests a list or mixed entity sheet")
    if categories >= 3:
        reasons.append("Teacher/class/subject/note signals are mixed together")
    return score, reasons


def _entity_list_score(sheet: SheetInspection, profile: SheetProfile) -> tuple[int, list[str]]:
    if _has_coherent_requirements_header(profile):
        return 0, []
    values = [fold_key(value) for value in _sheet_text_values(sheet)]
    hits = sum(1 for value in values if any(token in value for token in ("teacher", "prof", "professeur", "מורה", "class", "classe", "כיתה", "subject", "matiere", "מקצוע")))
    name_hint = _sheet_name_has_any(sheet.name, ("profs", "teachers", "classes", "subjects", "matieres", "matières"))
    score = int(round(min(100, hits * 12 + (24 if name_hint else 0) + profile.table_shape_score * 24)))
    reasons: list[str] = []
    if name_hint:
        reasons.append("Sheet name suggests entity lists")
    if hits:
        reasons.append(f"{hits} entity keyword(s) detected")
    return score, reasons


def _has_coherent_requirements_header(profile: SheetProfile) -> bool:
    return any(item.get("business_header_score") == 1 for item in profile.header_candidates)


def _sheet_name_has_any(sheet_name: str, tokens: tuple[str, ...]) -> bool:
    folded = fold_key(sheet_name)
    return any(fold_key(token) in folded for token in tokens)


def _sheet_text_values(sheet: SheetInspection) -> list[str]:
    return [
        normalize_text(value)
        for row in sheet.rows.values()
        for value in row.values()
        if normalize_text(value)
    ]


def _prepend_hypothesis(hypotheses: list[dict[str, Any]], cautious_kind: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "format": cautious_kind["sheet_kind"],
            "score": cautious_kind["confidence"],
            "reasons": cautious_kind["reasons"],
            "breakdown": {"guardrail": "pre_extraction_sheet_kind"},
        },
        *[item for item in hypotheses if item.get("format") != cautious_kind["sheet_kind"]],
    ]


def _import_action_for_sheet_kind(sheet_kind: str, confidence: int) -> str:
    if sheet_kind == "metadata_or_oracle":
        return "ignored"
    if sheet_kind in AUTO_EXTRACTION_SHEET_KINDS and confidence >= 40:
        return "extract"
    return "candidate_review"


def _sheet_override(corrections: dict[str, Any] | None, sheet_name: str) -> dict[str, Any] | None:
    overrides = (corrections or {}).get("sheet_overrides") or {}
    override = overrides.get(sheet_name)
    return override if isinstance(override, dict) else None


def _apply_sheet_override(
    detected: dict[str, Any],
    inspection: ExcelInspection,
    sheet: SheetInspection,
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    if not override:
        return detected
    forced_format = _normalize_forced_format(override.get("format"))
    if forced_format is None:
        return detected

    old_format = detected.get("detected_format")
    old_confidence = detected.get("confidence")
    if forced_format == "ignored":
        result = _forced_ignored_sheet(sheet)
    elif forced_format == "requirements_table":
        result = _analyze_requirements_sheet(sheet, column_roles=override.get("column_roles") if isinstance(override.get("column_roles"), dict) else None)
    elif forced_format == "availability_grid":
        result = _analyze_availability_sheet_v2(sheet, profile_sheet(sheet))
    elif forced_format == "schedule_grid":
        result = _analyze_schedule_grid_sheet(inspection, sheet, guard_availability_markers=True)
    else:
        return detected

    result["detected_format"] = forced_format
    result["confidence"] = max(int(float(result.get("confidence") or 0) * 100) if isinstance(result.get("confidence"), float) and result.get("confidence") <= 1 else int(result.get("confidence") or 0), 80)
    result["user_correction"] = {
        "applied": True,
        "old_format": old_format,
        "old_confidence": old_confidence,
        "new_format": forced_format,
        "column_roles": override.get("column_roles") or {},
    }
    result.setdefault("diagnostics", []).insert(
        0,
        diagnostic(
            "suggestion",
            "human_correction_applied",
            "Correction utilisateur appliquée",
            f"הוחלה בחירה ידנית: {old_format} -> {forced_format}.",
            old_format=old_format,
            new_format=forced_format,
            old_confidence=old_confidence,
        ),
    )
    return result


def _normalize_forced_format(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if normalized in {"requirements_table", "availability_grid", "schedule_grid", "ignored"}:
        return normalized
    if normalized in {"unknown", "noisy"}:
        return "ignored"
    return None


def _forced_ignored_sheet(sheet: SheetInspection) -> dict[str, Any]:
    return {
        "sheet_name": sheet.name,
        "detected_format": "ignored",
        "confidence": 100,
        "summary": {"rows_read": sheet.max_row, "non_empty_cells": sheet.non_empty_cells_count},
        "extracted_entities": {},
        "diagnostics": [],
        "preview": _sheet_preview(sheet),
        "ignored_reason": "הגיליון לא יובא בעקבות בחירה ידנית.",
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _apply_column_role_overrides(
    headers: list[Any],
    mappings: list[ColumnMapping],
    column_roles: dict[str, Any],
) -> tuple[list[ColumnMapping], list[dict[str, Any]]]:
    role_by_column = {_column_to_index(column): _role_to_field(role) for column, role in column_roles.items()}
    role_by_column = {column: field for column, field in role_by_column.items() if column is not None}
    result: list[ColumnMapping] = []
    used_fields: set[str] = set()
    for mapping in mappings:
        if mapping.column_index in role_by_column:
            field = role_by_column[mapping.column_index]
            reason = "בחירה ידנית."
            confidence = 1.0 if field else 0.0
        else:
            field = mapping.mapped_field
            reason = mapping.reason
            confidence = mapping.confidence
        if field in used_fields:
            field = None
            reason = "Rôle déjà utilisé par une autre colonne."
            confidence = 0.0
        if field:
            used_fields.add(field)
        result.append(ColumnMapping(mapping.column_index, mapping.original_name, field, confidence, reason))
    unmapped = [
        {"column_index": item.column_index, "original_name": item.original_name}
        for item in result
        if not item.mapped_field and item.original_name
    ]
    for column_index, field in role_by_column.items():
        if column_index <= len(result) or not field:
            continue
        result.append(ColumnMapping(column_index, _header_at(headers, column_index), field, 1.0, "בחירה ידנית."))
    return result, unmapped


def _role_to_field(value: Any) -> str | None:
    role = fold_key(value)
    return {
        "class": "class_name",
        "classe": "class_name",
        "class name": "class_name",
        "subject": "subject_name",
        "matiere": "subject_name",
        "subject name": "subject_name",
        "teacher": "teacher_name",
        "prof": "teacher_name",
        "teacher name": "teacher_name",
        "hours": "weekly_hours",
        "heures": "weekly_hours",
        "weekly hours": "weekly_hours",
        "ignored": None,
        "ignore": None,
        "": None,
    }.get(role)


def _column_to_index(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if number > 0 else None
    if not re.fullmatch(r"[A-Za-z]+", text):
        return None
    index = 0
    for char in text.upper():
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index


def _header_at(headers: list[Any], column_index: int) -> str:
    if 1 <= column_index <= len(headers):
        return "" if headers[column_index - 1] is None else str(headers[column_index - 1])
    return ""


def _annotate_sheet_statuses(sheets: list[dict[str, Any]]) -> None:
    for sheet in sheets:
        fmt = sheet.get("detected_format")
        import_action = sheet.get("import_action")
        confidence = _confidence_percent(sheet.get("confidence"))
        forced_status = sheet.get("requirements_validation", {}).get("status")
        if import_action == "ignored":
            status = "ignored"
            needs_review = False
            message = sheet.get("human_message") or "גיליון זה לא יובא."
        elif import_action == "candidate_review":
            status = "needs_review" if fmt not in {"unknown", "noisy"} else "ignored"
            needs_review = True
            message = sheet.get("human_message") or "Feuille ambiguë : validation humaine nécessaire avant import."
        elif forced_status == "needs_review":
            status = "needs_review"
            needs_review = True
            message = "הגיליון דורש בדיקה ידנית לפני ייבוא"
        elif forced_status == "ignored":
            status = "ignored"
            needs_review = True
            message = "הגיליון נראה כמו דרישות שעות, אבל אין מספיק שורות תקינות"
        elif fmt == "ignored":
            status = "ignored"
            needs_review = False
            message = "גיליון זה לא יובא."
        elif fmt in {"unknown", "noisy"}:
            status = "ignored"
            needs_review = True
            message = "הגיליון לא יובא כי רמת הביטחון נמוכה."
        elif 40 <= confidence <= 79:
            status = "needs_review"
            needs_review = True
            message = _human_sheet_message(fmt, review=True)
        else:
            status = "ready"
            needs_review = False
            message = _human_sheet_message(fmt, review=False)
        if sheet.get("user_correction", {}).get("applied"):
            status = "ready" if fmt != "ignored" else "ignored"
            needs_review = False
        sheet["status"] = status
        sheet["needs_review"] = needs_review
        sheet["needs_human_review"] = needs_review
        sheet["human_message"] = message
        sheet["extracted_count"] = _extracted_count(sheet.get("extracted_entities", {}))


def _human_sheet_message(fmt: str, review: bool) -> str:
    messages = {
        "requirements_table": "נראה שגיליון זה מכיל דרישות שעות.",
        "availability_grid": "נראה שגיליון זה מכיל זמינות מורים.",
        "schedule_grid": "נראה שגיליון זה מכיל מערכת שעות.",
    }
    base = messages.get(fmt, "צריך לבדוק את הגיליון ידנית.")
    if review:
        return f"{base} נדרש אימות ידני לפני ייבוא אמין."
    return base


def _augment_summary(
    summary: dict[str, Any],
    sheets: list[dict[str, Any]],
    scheduled_lessons: list[dict[str, Any]],
    teacher_availability: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **summary,
        "sheets_detected_count": len(sheets),
        "sheets_ready": sum(1 for sheet in sheets if sheet.get("status") == "ready"),
        "sheets_ambiguous": sum(1 for sheet in sheets if sheet.get("needs_review")),
        "sheets_ignored": sum(1 for sheet in sheets if sheet.get("status") == "ignored"),
        "scheduled_lessons_detected": len(scheduled_lessons),
        "teacher_availability_detected": len(teacher_availability),
    }


def _confidence_percent(value: Any) -> int:
    try:
        confidence = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return round(confidence * 100) if confidence <= 1 else round(confidence)


def _build_excel_intelligence(
    inspection: ExcelInspection,
    workbook_observation: dict[str, Any],
    sheet_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    legacy_by_name = {item["sheet_name"]: item for item in sheet_results}
    observation_by_name = {item["sheet_name"]: item for item in workbook_observation.get("sheets", [])}
    result: dict[str, dict[str, Any]] = {}
    for sheet in inspection.sheets:
        patterns = detect_sheet_patterns(sheet)
        classification = classify_sheet(sheet, patterns)
        legacy = legacy_by_name.get(sheet.name, {})
        extraction = extract_sheet_entities(inspection, sheet, legacy.get("detected_format") or _first_type(classification))
        result[sheet.name] = {
            "observation": observation_by_name.get(sheet.name, {}),
            "patterns_detected": patterns,
            "classification": classification,
            "possible_types": classification.get("possible_types", []),
            "intelligence_extraction": extraction,
        }
    return result


def _first_type(classification: dict[str, Any]) -> str:
    possible = classification.get("possible_types") or []
    return possible[0].get("type", "unknown") if possible else "unknown"


def _analyze_sheet(inspection: ExcelInspection, sheet: SheetInspection) -> dict[str, Any]:
    requirements = _analyze_requirements_sheet(sheet)
    schedule = _analyze_schedule_grid_sheet(inspection, sheet)
    list_detection = _analyze_simple_list_sheet(sheet)
    candidates = [requirements, schedule, list_detection]
    best = max(candidates, key=lambda item: item.get("confidence", 0.0))
    if best["confidence"] < 0.35:
        return _unknown_sheet(sheet, best)
    return best


def _analyze_requirements_sheet(
    sheet: SheetInspection,
    column_roles: dict[str, Any] | None = None,
    *,
    guard_requirements: bool = False,
    profile: SheetProfile | None = None,
) -> dict[str, Any]:
    excel_sheet = _to_excel_sheet(sheet)
    table = detect_table(excel_sheet)
    mappings, unmapped = map_columns(table.headers)
    if column_roles:
        mappings, unmapped = _apply_column_role_overrides(table.headers, mappings, column_roles)
    fields = {mapping.mapped_field for mapping in mappings if mapping.mapped_field}
    core_score = len(fields & {"class_name", "subject_name", "weekly_hours"}) / 3
    confidence = round(min(0.98, table.confidence * 0.55 + core_score * 0.45), 2)
    if not {"class_name", "subject_name"}.issubset(fields):
        confidence = min(confidence, 0.3)
    if column_roles and {"class_name", "subject_name", "weekly_hours"}.issubset(fields):
        confidence = max(confidence, 0.82)
    mapping_dicts = mappings_as_dicts(mappings)
    for item in mapping_dicts:
        item["sheet_name"] = sheet.name
    for item in unmapped:
        item["sheet_name"] = sheet.name
    extracted = extract_entities(sheet_name=sheet.name, data_rows=table.data_rows, mappings=mappings)
    validation = _validate_requirement_extraction(sheet, table, mappings, extracted, profile=profile) if guard_requirements else None
    if validation:
        extracted = validation["filtered_entities"]
    low_confidence_columns = [item for item in mapping_dicts if item.get("mapped_field") and item.get("confidence", 0) < 0.8]
    diagnostics = build_diagnostics(
        tables=[{"sheet_name": sheet.name, "header_row_index": table.header_row_index}] if table.header_row_index else [],
        extracted_entities=extracted,
        unmapped_columns=unmapped,
        low_confidence_columns=low_confidence_columns,
        ignored_empty_rows=table.ignored_empty_rows,
    )
    flattened_diagnostics = _flatten_diagnostics(diagnostics)
    if validation:
        flattened_diagnostics = validation["diagnostics"] + flattened_diagnostics
    return {
        "sheet_name": sheet.name,
        "detected_format": "requirements_table",
        "confidence": confidence,
        "summary": {
            "rows_read": table.total_rows_read,
            "detected_header_row": table.header_row_index,
            "data_rows_detected": len(table.data_rows),
            "requirements_detected": len(extracted["requirements"]),
            **(validation["summary"] if validation else {}),
        },
        "extracted_entities": extracted,
        "diagnostics": flattened_diagnostics,
        "preview": _sheet_preview(sheet),
        "column_role_overrides_applied": bool(column_roles),
        **({"requirements_validation": validation["public"]} if validation else {}),
        "_requirements_entities": extracted,
        "_tables": [
            {
                "sheet_name": sheet.name,
                "header_row_index": table.header_row_index,
                "headers": table.headers,
                "data_rows_detected": len(table.data_rows),
                "ignored_empty_rows": table.ignored_empty_rows,
                "confidence": confidence,
            }
        ],
        "_detected_columns": mapping_dicts,
        "_unmapped_columns": unmapped,
    }


def _validate_requirement_extraction(
    sheet: SheetInspection,
    table: Any,
    mappings: list[ColumnMapping],
    extracted: dict[str, Any],
    *,
    profile: SheetProfile | None = None,
) -> dict[str, Any]:
    field_columns = {mapping.mapped_field: mapping.column_index for mapping in mappings if mapping.mapped_field}
    required_fields = {"class_name", "subject_name", "teacher_name", "weekly_hours"}
    header_roles = _requirement_header_roles(profile, table.header_row_index)
    strong_header = required_fields.issubset(field_columns) and {CLASS_ROLE, SUBJECT_ROLE, TEACHER_ROLE, HOURS_ROLE}.issubset(header_roles)
    suspicious_name = _suspicious_requirements_sheet_name(sheet.name)
    positive_evidence: list[str] = []
    negative_evidence: list[str] = []
    if strong_header:
        positive_evidence.append("נמצאה שורת כותרות חזקה לטבלת דרישות שעות")
    else:
        negative_evidence.append("כותרות דרישות שעות אינן באותה שורה באופן עקבי")
    if "weekly_hours" not in field_columns:
        negative_evidence.append("עמודת השעות אינה ניתנת לזיהוי בצורה אמינה")
    if suspicious_name:
        negative_evidence.append("שם הגיליון מתאים יותר לאילוצים, הערות או רשימות")

    valid_requirements: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    hours_parse_attempts = 0
    hours_parse_successes = 0
    for requirement in extracted.get("requirements", []):
        row = sheet.rows.get(int(requirement.get("source_row") or 0), {})
        raw_hours = requirement.get("weekly_hours_raw")
        if raw_hours not in (None, ""):
            hours_parse_attempts += 1
            if parse_number(raw_hours) is not None:
                hours_parse_successes += 1
        reasons = _invalid_requirement_reasons(requirement, row)
        if reasons:
            invalid_rows.append({"source_row": requirement.get("source_row"), "reasons": reasons})
        else:
            valid_requirements.append(requirement)

    valid_count = len(valid_requirements)
    invalid_count = len(invalid_rows)
    total = valid_count + invalid_count
    valid_ratio = round(valid_count / total, 3) if total else 0.0
    hours_ratio = round(hours_parse_successes / hours_parse_attempts, 3) if hours_parse_attempts else 0.0
    min_valid_rows = 1 if len(table.data_rows) <= 2 else 2
    row_evidence_ok = valid_count >= min_valid_rows and valid_ratio >= 0.5
    ready = strong_header and row_evidence_ok and (not suspicious_name or hours_ratio >= 0.5)

    if valid_count:
        positive_evidence.append("נמצאו שורות דרישות תקינות")
    else:
        negative_evidence.append("לא נמצאו שורות דרישות תקינות")
    if hours_parse_attempts and hours_ratio < 0.5:
        negative_evidence.append("עמודת השעות מכילה בעיקר ערכים לא מספריים")
    if invalid_count > valid_count:
        negative_evidence.append("רוב השורות אינן תואמות class+subject+teacher+hours")
    if _dictionary_like_rows(sheet, table):
        negative_evidence.append("השורות נראות כמו רשימות או מילונים ולא כמו דרישות שעות")
    if profile and profile.availability_marker_density >= 0.12:
        negative_evidence.append("נמצאו הרבה סימוני זמינות בגיליון")

    if ready:
        status = "ready"
        parser_guardrail_reason = None
    elif valid_count == 0 and not strong_header:
        status = "ignored"
        parser_guardrail_reason = "No valid requirement rows and no coherent requirements header."
    else:
        status = "needs_review"
        parser_guardrail_reason = "Requirements candidate is too weak for automatic import."

    filtered_entities = {
        "classes": _unique([item.get("class_name") for item in valid_requirements]),
        "teachers": _unique([item.get("teacher_name") for item in valid_requirements]),
        "subjects": _unique([item.get("subject_name") for item in valid_requirements]),
        "requirements": valid_requirements,
    }
    public = {
        "detected_header_row": table.header_row_index,
        "valid_requirement_rows": valid_count,
        "invalid_requirement_rows": invalid_count,
        "valid_requirement_ratio": valid_ratio,
        "hours_parse_success_ratio": hours_ratio,
        "positive_evidence": positive_evidence,
        "negative_evidence": negative_evidence,
        "parser_guardrail_reason": parser_guardrail_reason,
        "status": status,
        "invalid_rows": invalid_rows[:12],
    }
    diagnostics = [
        diagnostic(
            "suggestion" if ready else "warning",
            "requirements_table_validation",
            "בדיקת דרישות שעות",
            "נמצאו שורות דרישות תקינות" if ready else "הגיליון נראה כמו דרישות שעות, אבל אין מספיק שורות תקינות",
            **{key: value for key, value in public.items() if key != "invalid_rows"},
        )
    ]
    if "weekly_hours" not in field_columns or (hours_parse_attempts and hours_ratio < 0.5):
        diagnostics.append(
            diagnostic(
                "warning",
                "requirements_hours_column_unreliable",
                "עמודת שעות לא אמינה",
                "עמודת השעות אינה ניתנת לזיהוי בצורה אמינה",
                hours_parse_success_ratio=hours_ratio,
            )
        )
    if status != "ready":
        diagnostics.append(
            diagnostic(
                "warning",
                "requirements_manual_review_required",
                "נדרשת בדיקה ידנית",
                "הגיליון דורש בדיקה ידנית לפני ייבוא",
                parser_guardrail_reason=parser_guardrail_reason,
            )
        )
    return {
        "filtered_entities": filtered_entities,
        "summary": {
            "valid_requirement_rows": valid_count,
            "invalid_requirement_rows": invalid_count,
            "valid_requirement_ratio": valid_ratio,
            "hours_parse_success_ratio": hours_ratio,
            "parser_guardrail_reason": parser_guardrail_reason,
            "requirements_validation_status": status,
        },
        "public": public,
        "diagnostics": diagnostics,
    }


def _requirement_header_roles(profile: SheetProfile | None, header_row: int | None) -> set[str]:
    if not profile or header_row is None:
        return set()
    return {
        match.role
        for match in profile.role_matches
        if match.row == header_row and match.role in {CLASS_ROLE, SUBJECT_ROLE, TEACHER_ROLE, HOURS_ROLE}
    }


def _invalid_requirement_reasons(requirement: dict[str, Any], row: dict[int, Any]) -> list[str]:
    reasons: list[str] = []
    class_name = normalize_text(requirement.get("class_name"))
    subject_name = normalize_text(requirement.get("subject_name"))
    teacher_name = normalize_text(requirement.get("teacher_name"))
    hours = requirement.get("weekly_hours")
    if not class_name or not _looks_like_class_value(class_name):
        reasons.append("missing_or_unreliable_class")
    if not subject_name or _looks_like_label(subject_name) or is_availability_marker(subject_name):
        reasons.append("missing_or_unreliable_subject")
    if not teacher_name or _looks_like_label(teacher_name):
        reasons.append("missing_or_unreliable_teacher")
    if hours is None:
        reasons.append("hours_not_parseable")
    row_text = " ".join(normalize_text(value) for value in row.values())
    if _looks_like_constraint_text(row_text):
        reasons.append("constraint_or_note_row")
    return reasons


def _looks_like_class_value(value: str) -> bool:
    folded = fold_key(value)
    if _looks_like_label(value):
        return False
    if any(char.isdigit() for char in folded):
        return True
    return any(token in folded for token in ("כיתה", "יא", "יב", "ט", "י ", "ז", "ח", "7", "8", "9", "10", "11", "12"))


def _looks_like_label(value: str) -> bool:
    folded = fold_key(value)
    labels = {
        "class",
        "classe",
        "כיתה",
        "subject",
        "matiere",
        "מקצוע",
        "teacher",
        "prof",
        "professeur",
        "מורה",
        "hours",
        "heures",
        "שעות",
        "type",
        "nom",
        "name",
        "alias",
    }
    return folded in labels or folded.endswith("_hours") or folded.endswith("_rule")


def _looks_like_constraint_text(value: str) -> bool:
    folded = fold_key(value)
    tokens = (
        "constraint",
        "contrainte",
        "contraintes",
        "unavailable",
        "indisponible",
        "ne travaille pas",
        "ne peut pas",
        "pas plus",
        "pas moins",
        "maximum",
        "minimum",
        "pas le",
        "pas lundi",
        "pas mardi",
        "pas mercredi",
        "pas jeudi",
        "pas vendredi",
        "max daily",
        "prefer",
        "prefere",
        "préfère",
        "required",
        "obligatoire",
        "avoid",
        "eviter",
        "éviter",
        "unknown rule",
        "blocking",
        "recommendation",
        "אילוץ",
        "מגבלה",
        "לא זמין",
        "לא פנוי",
        "לא עובד",
        "ביום",
        "יותר מ",
        "פחות מ",
    )
    return any(token in folded for token in tokens)


def _dictionary_like_rows(sheet: SheetInspection, table: Any) -> bool:
    type_like = 0
    checked = 0
    for row in table.data_rows:
        first = normalize_text(sheet.rows.get(row.row_index, {}).get(1))
        if not first:
            continue
        checked += 1
        if fold_key(first) in {"teacher", "class", "subject", "prof", "classe", "matiere"} or "_" in first:
            type_like += 1
    return checked >= 3 and type_like / checked >= 0.5


def _suspicious_requirements_sheet_name(sheet_name: str) -> bool:
    folded = fold_key(sheet_name)
    tokens = (
        "contrainte",
        "constraint",
        "אילוץ",
        "אילוצים",
        "מגבלה",
        "מגבלות",
        "note",
        "whatsapp",
        "liste",
        "list",
        "רשימה",
        "רשימות",
    )
    return any(token in folded for token in tokens)


def _analyze_schedule_grid_sheet(inspection: ExcelInspection, sheet: SheetInspection, *, guard_availability_markers: bool = False) -> dict[str, Any]:
    single_sheet_inspection = ExcelInspection(
        filename=inspection.filename,
        sheet_names=[sheet.name],
        sheets=[sheet],
        reader_engine=inspection.reader_engine,
        warnings=inspection.warnings,
    )
    candidates = [
        grid_days_columns_parser.parse(single_sheet_inspection),
        grid_days_rows_parser.parse(single_sheet_inspection),
    ]
    result = max(candidates, key=lambda item: item.score, default=ParserResult("none", "unknown", 0.0, sheet_name=sheet.name))
    day_cells = len(sheet.possible_day_headers)
    time_cells = len(sheet.possible_time_cells)
    marker_cells = len(sheet.possible_teacher_markers) + len(sheet.possible_room_markers)
    signal = min(1.0, (day_cells / 6) * 0.5 + (time_cells / 8) * 0.25 + (marker_cells / 8) * 0.25)
    lesson_score = min(1.0, len(result.lessons) / 10)
    confidence = round(max(result.confidence, signal * 0.7 + lesson_score * 0.3), 2)
    if day_cells < 2 or time_cells < 1:
        confidence = min(confidence, 0.3)
    lessons = [_lesson_to_dict(lesson) for lesson in result.lessons]
    guard_diagnostics: list[dict[str, Any]] = []
    if guard_availability_markers:
        lessons, guard_diagnostics = _guard_schedule_availability_lessons(sheet, lessons)
    return {
        "sheet_name": sheet.name,
        "detected_format": "schedule_grid",
        "confidence": confidence,
        "summary": {
            "rows_read": sheet.max_row,
            "scheduled_lessons_detected": len(lessons),
            "grid_layout": result.detected_layout,
        },
        "extracted_entities": {
            "scheduled_lessons": lessons,
            "classes": _unique([lesson.get("class_name") for lesson in lessons]),
            "teachers": _unique([lesson.get("teacher_name") for lesson in lessons]),
            "subjects": _unique([lesson.get("subject") or lesson.get("subject_name") for lesson in lessons]),
            "rooms": _unique([lesson.get("room") or lesson.get("room_name") for lesson in lessons]),
        },
        "diagnostics": guard_diagnostics + [_issue_to_dict(item, "warning") for item in result.warnings] + [_issue_to_dict(item, "blocking") for item in result.errors],
        "preview": _sheet_preview(sheet),
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _analyze_simple_list_sheet(sheet: SheetInspection) -> dict[str, Any]:
    header_cells = []
    for row_index in range(1, min(sheet.max_row, 10) + 1):
        for column, value in sheet.rows.get(row_index, {}).items():
            header = normalize_header(value)
            if header:
                header_cells.append((header, row_index, column, value))
    folded_values = [fold_key(value) for row in sheet.rows.values() for value in row.values()]
    teacher_signal = sum(1 for value in folded_values if any(token in value for token in ("teacher", "prof", "professeur", "מורה", "email", "mail", "טלפון", "phone")))
    class_signal = sum(1 for value in folded_values if any(token in value for token in ("class", "classe", "כיתה", "groupe")))
    subject_signal = sum(1 for value in folded_values if any(token in value for token in ("subject", "matiere", "matière", "מקצוע")))
    availability_signal = teacher_signal + len(sheet.possible_day_headers) + sum(1 for value in folded_values if any(token in value for token in ("disponible", "indisponible", "available", "unavailable", "פנוי", "לא פנוי")))
    choices = [
        ("teacher_list", teacher_signal),
        ("class_list", class_signal),
        ("subject_list", subject_signal),
        ("availability_grid", availability_signal if len(sheet.possible_day_headers) >= 2 and teacher_signal else 0),
        ("constraints_table", sum(1 for value in folded_values if any(token in value for token in ("constraint", "contrainte", "אילוץ")))),
    ]
    detected_format, score = max(choices, key=lambda item: item[1], default=("unknown", 0))
    confidence = round(min(0.75, score / 6), 2)
    values = _extract_list_values(sheet, detected_format) if confidence >= 0.35 else []
    entity_key = {
        "teacher_list": "teachers",
        "class_list": "classes",
        "subject_list": "subjects",
        "availability_grid": "availability",
        "constraints_table": "constraints",
    }.get(detected_format, "items")
    return {
        "sheet_name": sheet.name,
        "detected_format": detected_format,
        "confidence": confidence,
        "summary": {"rows_read": sheet.max_row, "items_detected": len(values)},
        "extracted_entities": {entity_key: values},
        "diagnostics": [],
        "preview": _sheet_preview(sheet),
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _analyze_availability_sheet_v2(sheet: SheetInspection, profile: SheetProfile) -> dict[str, Any]:
    entries = _extract_teacher_availability(sheet)
    teachers = _unique([entry.get("teacher_name") for entry in entries])
    return {
        "sheet_name": sheet.name,
        "detected_format": "availability_grid",
        "confidence": 0,
        "summary": {
            "rows_read": sheet.max_row,
            "availability_entries_detected": len(entries),
            "scheduled_lessons_detected": 0,
        },
        "extracted_entities": {
            "teacher_availability": entries,
            "teachers": teachers,
            "scheduled_lessons": [],
        },
        "diagnostics": [],
        "preview": _sheet_preview(sheet),
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _extract_teacher_availability(sheet: SheetInspection) -> list[dict[str, Any]]:
    day_header_row = _best_day_header_row(sheet)
    if day_header_row is None:
        return []
    day_columns = [
        (column, value)
        for column, value in sorted(sheet.rows.get(day_header_row, {}).items())
        if is_day(value)
    ]
    if not day_columns:
        return []
    teacher_column = _best_teacher_column(sheet, day_header_row, day_columns[0][0])
    entries: list[dict[str, Any]] = []
    for row_index in range(day_header_row + 1, sheet.max_row + 1):
        teacher_name = normalize_text(sheet.rows.get(row_index, {}).get(teacher_column))
        if not teacher_name:
            continue
        slot = _availability_slot_for_row(sheet, row_index, teacher_column)
        for column, day in day_columns:
            raw = normalize_text(sheet.rows.get(row_index, {}).get(column))
            if not is_availability_marker(raw):
                continue
            entries.append(
                {
                    "teacher_name": teacher_name,
                    "day": day,
                    "slot": slot,
                    "status": _availability_status(raw),
                    "raw_value": raw,
                    "source_sheet": sheet.name,
                    "source_row": row_index,
                    "source_column": column,
                }
            )
    return entries


def _best_day_header_row(sheet: SheetInspection) -> int | None:
    counts: dict[int, int] = {}
    for item in sheet.possible_day_headers:
        counts[item["row"]] = counts.get(item["row"], 0) + 1
    row, count = max(counts.items(), key=lambda item: item[1], default=(None, 0))
    return row if count >= 1 else None


def _best_teacher_column(sheet: SheetInspection, header_row: int, first_day_column: int) -> int:
    header_values = sheet.rows.get(header_row, {})
    for column in range(1, first_day_column):
        if "teacher" in fold_key(header_values.get(column)) or "prof" in fold_key(header_values.get(column)) or "מורה" in fold_key(header_values.get(column)):
            return column
    return 1


def _availability_slot_for_row(sheet: SheetInspection, row_index: int, teacher_column: int) -> str | None:
    for column, value in sorted(sheet.rows.get(row_index, {}).items()):
        if column != teacher_column and is_time_like(value):
            return value
    return None


def _availability_status(value: str) -> str:
    folded = fold_key(value)
    unavailable = {"לא זמין", "לא פנוי", "unavailable", "no", "לא"}
    if any(fold_key(marker) == folded or (len(fold_key(marker)) > 3 and fold_key(marker) in folded) for marker in unavailable):
        return "unavailable"
    return "available"


def _guard_schedule_availability_lessons(sheet: SheetInspection, lessons: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not lessons:
        return lessons, []
    invalid: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for lesson in lessons:
        subject = lesson.get("subject") or lesson.get("subject_name")
        raw_text = ((lesson.get("raw") or {}).get("text") if isinstance(lesson.get("raw"), dict) else "") or ""
        marker_subject = is_availability_marker(subject)
        marker_raw = is_availability_marker(raw_text)
        missing_core = not lesson.get("teacher_name") and not lesson.get("class_name")
        if marker_subject or (marker_raw and missing_core):
            invalid.append(lesson)
        else:
            valid.append(lesson)

    if not invalid:
        return lessons, []

    message = "Extraction planning ignorée car les cellules ressemblent à des disponibilités, pas à des cours."
    details = {
        "invalid_candidates": len(invalid),
        "valid_candidates": len(valid),
        "availability_marker_density": profile_sheet(sheet).availability_marker_density,
    }
    if len(invalid) >= len(valid) and details["availability_marker_density"] >= 0.15:
        return [], [
            diagnostic(
                "warning",
                "schedule_grid_availability_markers_rejected",
                "Extraction planning ignorée",
                message,
                **details,
            )
        ]
    return valid, [
        diagnostic(
            "warning",
            "schedule_grid_availability_marker_cells_skipped",
            "Cellules de disponibilité ignorées",
            "Des cellules de disponibilité ont été ignorées pendant l'extraction du planning.",
            **details,
        )
    ]


def _ignored_sheet_v2(sheet: SheetInspection, detected_format: str, confidence: int, reason: str) -> dict[str, Any]:
    ignored_reason = reason
    if confidence < 40:
        ignored_reason = "Confidence is below 40 and the sheet looks ambiguous or noisy."
    return {
        "sheet_name": sheet.name,
        "detected_format": detected_format,
        "confidence": confidence,
        "summary": {"rows_read": sheet.max_row, "non_empty_cells": sheet.non_empty_cells_count},
        "extracted_entities": {},
        "diagnostics": [],
        "preview": _sheet_preview(sheet),
        "ignored_reason": ignored_reason,
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _review_only_sheet_v2(
    sheet: SheetInspection,
    sheet_kind: str,
    confidence: int,
    reason: str,
    *,
    needs_review: bool,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = {} if sheet_kind in {"unknown", "noisy"} else _extract_review_candidates(sheet, sheet_kind)
    import_action = _import_action_for_sheet_kind(sheet_kind, confidence)
    if confidence < 40:
        reason = "Confidence is below 40 and the sheet looks ambiguous or noisy."
    sheet_diagnostics = _filter_sheet_diagnostics_for_kind(diagnostics or [], sheet_kind)
    if sheet_kind == "metadata_or_oracle":
        sheet_diagnostics.append(
            diagnostic(
                "suggestion",
                "sheet_metadata_ignored",
                "Feuille metadata ignorée",
                "Feuille ignorée : metadata, oracle de test, notes ou debug.",
            )
        )
    elif needs_review:
        sheet_diagnostics.append(_ambiguous_sheet_warning())
    return {
        "sheet_name": sheet.name,
        "detected_format": sheet_kind,
        "sheet_kind": sheet_kind,
        "import_action": import_action,
        "needs_human_review": needs_review,
        "confidence": confidence,
        "summary": {
            "rows_read": sheet.max_row,
            "non_empty_cells": sheet.non_empty_cells_count,
            "scheduled_lessons_detected": 0,
            "requirements_detected": 0,
            "candidate_entities_detected": _extracted_count(candidates),
        },
        "extracted_entities": candidates,
        "diagnostics": sheet_diagnostics,
        "preview": _sheet_preview(sheet),
        "ignored_reason": reason if import_action == "ignored" or sheet_kind in {"unknown", "noisy"} else None,
        "review_reason": reason if import_action != "ignored" else None,
        "human_message": "Feuille ambiguë : validation humaine nécessaire avant import." if needs_review else None,
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _extract_review_candidates(sheet: SheetInspection, sheet_kind: str) -> dict[str, Any]:
    teachers: list[str] = []
    classes: list[str] = []
    subjects: list[str] = []
    constraints: list[dict[str, Any]] = []
    for row_index, row in sorted(sheet.rows.items()):
        row_values = [normalize_text(value) for value in row.values() if normalize_text(value)]
        if not row_values:
            continue
        row_text = " ".join(row_values)
        folded = fold_key(row_text)
        typed_value = _typed_entity_value(row_values)
        if typed_value:
            entity_type, value = typed_value
            if entity_type == "teacher":
                teachers.append(value)
            elif entity_type == "class":
                classes.append(value)
            elif entity_type == "subject":
                subjects.append(value)
        elif sheet_kind in {"entity_list", "mixed_list"}:
            for value in row_values:
                if _looks_like_class_value(value):
                    classes.append(value)
                elif any(token in fold_key(value) for token in ("teacher", "prof", "professeur", "מורה")):
                    continue
        if sheet_kind == "constraints_text" or _looks_like_constraint_text(row_text) or any(token in folded for token in ("remarque", "note", "comment")):
            constraints.append(
                {
                    "text": row_text,
                    "confidence": 0.75 if _looks_like_constraint_text(row_text) else 0.45,
                    "needs_human_validation": True,
                    "source_sheet": sheet.name,
                    "source_row": row_index,
                }
            )
    return {
        "teacher_candidates": _unique(teachers),
        "class_candidates": _unique(classes),
        "subject_candidates": _unique(subjects),
        "constraint_candidates": constraints[:80],
        "scheduled_lessons": [],
        "requirements": [],
    }


def _typed_entity_value(row_values: list[str]) -> tuple[str, str] | None:
    if len(row_values) < 2:
        return None
    entity_type = fold_key(row_values[0])
    value = row_values[1]
    if entity_type in {"teacher", "prof", "professeur", "מורה"}:
        return "teacher", value
    if entity_type in {"class", "classe", "כיתה", "groupe"}:
        return "class", value
    if entity_type in {"subject", "matiere", "matière", "מקצוע"}:
        return "subject", value
    return None


def _filter_sheet_diagnostics_for_kind(diagnostics: list[dict[str, Any]], sheet_kind: str) -> list[dict[str, Any]]:
    if sheet_kind in {"requirements_table", "schedule_grid"}:
        return diagnostics
    forbidden = {"no_class_detected", "no_subject_detected", "no_table_detected"}
    return [item for item in diagnostics if item.get("code") not in forbidden]


def _ambiguous_sheet_warning() -> dict[str, Any]:
    return diagnostic(
        "warning",
        "sheet_needs_human_review",
        "Validation humaine nécessaire",
        "Feuille ambiguë : validation humaine nécessaire avant import.",
    )


def _sheet_diagnostic_summary(result: dict[str, Any], hypothesis: dict[str, Any], selection_reason: str) -> dict[str, Any]:
    return {
        "detected_format": result.get("detected_format"),
        "sheet_kind": result.get("sheet_kind"),
        "import_action": result.get("import_action"),
        "needs_human_review": result.get("needs_human_review"),
        "confidence": result.get("confidence"),
        "top_reasons": hypothesis.get("reasons", [])[:4],
        "ignored_reason": result.get("ignored_reason"),
        "extracted_entities_count": _extracted_count(result.get("extracted_entities", {})),
        "warnings": [item.get("message") for item in result.get("diagnostics", []) if item.get("severity") in {"warning", "suggestion"}][:8],
        "parser_reason": selection_reason,
    }


def _classification_diagnostics(result: dict[str, Any], hypothesis: dict[str, Any], selection_reason: str) -> list[dict[str, Any]]:
    fmt = result.get("detected_format")
    confidence = int(result.get("confidence") or 0)
    reasons = hypothesis.get("reasons", [])[:4]
    if fmt == "requirements_table":
        message = "Detected as requirements_table because class, subject, teacher and hours columns were found."
    elif fmt == "availability_grid":
        message = "Detected as availability_grid because availability markers and teacher/day structure were detected."
    elif fmt == "schedule_grid":
        message = "Detected as schedule_grid because a coherent day/slot planning structure was found."
    elif fmt == "constraints_text":
        message = "Classée constraints_text : extraction automatique de cours désactivée; contraintes candidates à valider."
    elif fmt == "mixed_list":
        message = "Classée mixed_list : extraction automatique de lessons désactivée; entités candidates à valider."
    elif fmt == "entity_list":
        message = "Classée entity_list : extraction automatique de lessons désactivée; entités candidates à valider."
    elif fmt == "metadata_or_oracle":
        message = "Feuille ignorée car elle ressemble à une metadata, un oracle de test, des notes ou du debug."
    elif fmt == "noisy":
        message = "Ignored as noisy because confidence is below 40 or the sheet looks like free text notes."
    else:
        message = selection_reason
    return [
        diagnostic(
            "suggestion" if confidence >= 40 else "warning",
            "excel_intelligence_v2_classification",
            "Classification Excel v2",
            message,
            reasons=reasons,
            ignored_reason=result.get("ignored_reason"),
        )
    ]


def _profile_diagnostics(profile: SheetProfile, result: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    best_header = max(profile.header_candidates, key=lambda item: item.get("business_header_score", item.get("score", 0)), default=None)
    if result.get("detected_format") == "requirements_table" and best_header and best_header.get("business_header_score") == 1:
        ignored = int(best_header.get("title_noise_rows_above") or 0)
        items.append(
            diagnostic(
                "suggestion",
                "business_header_row_detected",
                "Ligne d'en-tête détectée",
                f"Ligne d'en-tête détectée à la ligne {best_header['row']}; colonnes classe, matière, professeur et heures détectées.",
                header_row=best_header["row"],
                ignored_title_rows=ignored,
                roles=best_header.get("roles", []),
            )
        )
        if ignored:
            items.append(
                diagnostic(
                    "suggestion",
                    "title_noise_rows_ignored",
                    "Lignes de titre ignorées",
                    "Les lignes de titre au-dessus ont été ignorées.",
                    ignored_title_rows=ignored,
                )
            )
    if result.get("detected_format") == "availability_grid" and profile.availability_marker_density > 0:
        items.append(
            diagnostic(
                "suggestion",
                "availability_markers_detected",
                "Marqueurs de disponibilité détectés",
                "Pattern availability_matrix détecté; schedule_grid rejeté car les valeurs principales sont des disponibilités.",
                availability_marker_density=profile.availability_marker_density,
            )
        )
    return items


def _extracted_count(entities: dict[str, Any]) -> int:
    return sum(len(value) for value in entities.values() if isinstance(value, list))


def _legacy_summary(sheet_results: list[dict[str, Any]], extracted_entities: dict[str, Any]) -> dict[str, Any]:
    requirement_summaries = [item["summary"] for item in sheet_results if item["detected_format"] == "requirements_table"]
    total_rows_read = sum(item.get("rows_read", 0) for item in (result["summary"] for result in sheet_results))
    first_header = next((item.get("detected_header_row") for item in requirement_summaries if item.get("detected_header_row")), None)
    data_rows = sum(item.get("data_rows_detected", 0) for item in requirement_summaries)
    ignored_empty_rows = sum(table.get("ignored_empty_rows", 0) for result in sheet_results for table in result.get("_tables", []))
    imported_rows_count = len(extracted_entities["requirements"])
    return {
        "total_rows_read": total_rows_read,
        "header_row": first_header,
        "detected_header_row": first_header,
        "data_rows_detected": data_rows,
        "total_data_rows_detected": data_rows,
        "ignored_empty_rows": ignored_empty_rows,
        "imported_rows_count": imported_rows_count,
        "classes_detected": len(extracted_entities["classes"]),
        "teachers_detected": len(extracted_entities["teachers"]),
        "subjects_detected": len(extracted_entities["subjects"]),
        "requirements_detected": imported_rows_count,
        "scheduled_lessons_detected": sum(item["summary"].get("scheduled_lessons_detected", 0) for item in sheet_results),
    }


def _legacy_diagnostics(requirements_sheets: list[dict[str, Any]], extracted_entities: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if requirements_sheets:
        flattened = [item for sheet in requirements_sheets for item in sheet["diagnostics"]]
        return {
            "blocking": [item for item in flattened if item.get("severity") == "blocking"],
            "warnings": [item for item in flattened if item.get("severity") == "warning"],
            "suggestions": [item for item in flattened if item.get("severity") == "suggestion"],
        }
    if extracted_entities.get("requirements"):
        return {"blocking": [], "warnings": [], "suggestions": []}
    return {"blocking": [], "warnings": [], "suggestions": []}


def _global_diagnostics(inspection: ExcelInspection, sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    diagnostics = [diagnostic("warning", "workbook_reader_warning", "Avertissement lecture Excel", item) for item in inspection.warnings]
    if not sheets:
        diagnostics.append(diagnostic("blocking", "empty_workbook", "Fichier vide", "Le fichier ne contient aucune feuille lisible."))
    return diagnostics


def _to_excel_sheet(sheet: SheetInspection) -> ExcelSheet:
    rows: list[ExcelRow] = []
    for row_index in range(1, sheet.max_row + 1):
        row = sheet.rows.get(row_index, {})
        values = [row.get(column) for column in range(1, sheet.max_column + 1)]
        rows.append(ExcelRow(row_index=row_index, values=values))
    return ExcelSheet(sheet.name, sheet.max_row, sheet.max_column, rows)


def _unknown_sheet(sheet: SheetInspection, best: dict[str, Any]) -> dict[str, Any]:
    return {
        "sheet_name": sheet.name,
        "detected_format": "unknown",
        "confidence": round(best.get("confidence", 0.0), 2),
        "summary": {"rows_read": sheet.max_row, "non_empty_cells": sheet.non_empty_cells_count},
        "extracted_entities": {},
        "diagnostics": [
            diagnostic(
                "suggestion",
                "human_mapping_required",
                "Mapping requis",
                "Cette feuille est lisible mais son format n'est pas reconnu avec assez de confiance.",
                suggestion="Choisissez le type de feuille et les colonnes/lignes importantes.",
            )
        ],
        "preview": _sheet_preview(sheet),
        "suggested_format": best.get("detected_format", "unknown"),
        "_requirements_entities": {"classes": [], "teachers": [], "subjects": [], "requirements": []},
    }


def _sheet_preview(sheet: SheetInspection, limit: int = 12) -> list[list[str]]:
    return sheet.first_rows[:limit]


def _flatten_diagnostics(diagnostics: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return diagnostics.get("blocking", []) + diagnostics.get("warnings", []) + diagnostics.get("suggestions", [])


def _lesson_to_dict(lesson: ImportedLesson) -> dict[str, Any]:
    data = lesson.model_dump()
    data["subject_name"] = data.get("subject_name") or data.get("subject")
    data["teacher_name"] = data.get("teacher_name") or data.get("teacher")
    data["room_name"] = data.get("room_name") or data.get("room")
    return data


def _issue_to_dict(item: Any, severity: str) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        data = item.model_dump()
    elif isinstance(item, dict):
        data = dict(item)
    else:
        data = {"message": str(item)}
    data.setdefault("severity", severity)
    data.setdefault("title", data.get("code", severity))
    return data


def _extract_list_values(sheet: SheetInspection, detected_format: str) -> list[str]:
    values: list[str] = []
    header_row = _best_header_row(sheet)
    if header_row is None:
        return values
    headers = {column: normalize_header(value) or fold_key(value) for column, value in sheet.rows.get(header_row, {}).items()}
    wanted = {
        "teacher_list": ("teacher", "prof", "professeur", "מורה"),
        "class_list": ("class", "classe", "כיתה", "groupe"),
        "subject_list": ("subject", "matiere", "matière", "מקצוע"),
    }.get(detected_format, ())
    target_columns = [column for column, header in headers.items() if header in wanted or any(token in header for token in wanted)]
    if not target_columns and headers:
        target_columns = [min(headers)]
    for row_index in range(header_row + 1, sheet.max_row + 1):
        for column in target_columns:
            value = normalize_string(sheet.rows.get(row_index, {}).get(column))
            if value:
                values.append(value)
                break
    return _unique(values)


def _best_header_row(sheet: SheetInspection) -> int | None:
    best_row = None
    best_score = 0
    for row_index in range(1, min(sheet.max_row, 10) + 1):
        score = sum(1 for value in sheet.rows.get(row_index, {}).values() if normalize_header(value) or fold_key(value) in {"email", "mail", "phone", "telephone", "טלפון"})
        if score > best_score:
            best_row = row_index
            best_score = score
    return best_row


def _workbook_confidence(sheets: list[dict[str, Any]]) -> float:
    if not sheets:
        return 0.0
    return round(sum(float(item.get("confidence") or 0) for item in sheets) / len(sheets), 2)


def _unique(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _old_analyze_excel_content(content: bytes, filename: str | None = None) -> dict[str, Any]:
    sheets = []
    detected_columns: list[dict[str, Any]] = []
    unmapped_columns: list[dict[str, Any]] = []
    low_confidence_columns: list[dict[str, Any]] = []
    extracted_per_sheet: list[dict[str, Any]] = []
    table_summaries: list[dict[str, Any]] = []
    ignored_empty_rows = 0
    total_rows_read = 0
    total_data_rows_detected = 0
    for sheet in sheets:
        total_rows_read += sheet.max_row
        table = detect_table(sheet)
        if table.header_row_index is None:
            table_summaries.append({"sheet_name": sheet.sheet_name, "header_row_index": None, "confidence": 0.0})
            continue
        mappings, unmapped = map_columns(table.headers)
        mapping_dicts = mappings_as_dicts(mappings)
        for item in mapping_dicts:
            item["sheet_name"] = sheet.sheet_name
        for item in unmapped:
            item["sheet_name"] = sheet.sheet_name
        detected_columns.extend(mapping_dicts)
        unmapped_columns.extend(unmapped)
        low_confidence_columns.extend([item for item in mapping_dicts if item.get("mapped_field") and item.get("confidence", 0) < 0.8])
        extracted = extract_entities(sheet_name=sheet.sheet_name, data_rows=table.data_rows, mappings=mappings)
        extracted_per_sheet.append(extracted)
        ignored_empty_rows += table.ignored_empty_rows
        total_data_rows_detected += len(table.data_rows)
        table_summaries.append({"sheet_name": sheet.sheet_name, "header_row_index": table.header_row_index, "headers": table.headers, "data_rows_detected": len(table.data_rows), "ignored_empty_rows": table.ignored_empty_rows, "confidence": table.confidence})
    extracted_entities = merge_extracted_entities(extracted_per_sheet)
    diagnostics = build_diagnostics(tables=[item for item in table_summaries if item.get("header_row_index")], extracted_entities=extracted_entities, unmapped_columns=unmapped_columns, low_confidence_columns=low_confidence_columns, ignored_empty_rows=ignored_empty_rows)
    if not sheets:
        diagnostics["blocking"].append(diagnostic("blocking", "empty_workbook", "Fichier vide", "Le fichier ne contient aucune feuille non vide."))
    imported_rows_count = len(extracted_entities["requirements"])
    first_header = next((item.get("header_row_index") for item in table_summaries if item.get("header_row_index")), None)
    summary = {
        "total_rows_read": total_rows_read,
        "header_row": first_header,
        "detected_header_row": first_header,
        "data_rows_detected": total_data_rows_detected,
        "total_data_rows_detected": total_data_rows_detected,
        "ignored_empty_rows": ignored_empty_rows,
        "imported_rows_count": imported_rows_count,
        "classes_detected": len(extracted_entities["classes"]),
        "teachers_detected": len(extracted_entities["teachers"]),
        "subjects_detected": len(extracted_entities["subjects"]),
        "requirements_detected": imported_rows_count,
    }
    result = {
        "import_id": f"analysis_{uuid4().hex[:12]}",
        "filename": filename,
        "sheets_detected": [sheet.sheet_name for sheet in sheets],
        "tables": table_summaries,
        "detected_columns": detected_columns,
        "unmapped_columns": unmapped_columns,
        "extracted_entities": extracted_entities,
        "diagnostics": diagnostics,
        "summary": summary,
        "confidence_score": _confidence_score(table_summaries, diagnostics),
        "can_commit": not bool(diagnostics.get("blocking")),
    }
    save_import_draft(result)
    return result


def excel_import_schema() -> dict[str, Any]:
    return {
        "standard_fields": STANDARD_FIELDS,
        "synonyms": SYNONYMS,
        "recommended_example": [
            {"Classe": "7A", "Matière": "Math", "Professeur": "David Cohen", "Heures": 4},
            {"Classe": "8B", "Matière": "Science", "Professeur": "Miriam Levi", "Heures": 3},
        ],
    }


def _confidence_score(tables: list[dict[str, Any]], diagnostics: dict[str, list[dict[str, Any]]]) -> float:
    if diagnostics.get("blocking") or not tables:
        return 0.0
    score = sum(float(item.get("confidence") or 0) for item in tables) / len(tables)
    warning_penalty = min(0.25, len(diagnostics.get("warnings", [])) * 0.01)
    return round(max(0.0, score - warning_penalty), 2)
