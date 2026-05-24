from __future__ import annotations

from typing import Any
from uuid import uuid4

from backend.services.imports.intelligence.confidence import aggregate_confidence
from backend.services.imports.intelligence.csv_parser import CsvParserBrain
from backend.services.imports.intelligence.format_detection import FormatDetectionBrain
from backend.services.imports.intelligence.header_detection import HeaderDetectionBrain
from backend.services.imports.intelligence.human_review import HumanReviewBrain
from backend.services.imports.intelligence.models import ImportContext
from backend.services.imports.intelligence.normalization import NormalizationBrain
from backend.services.imports.intelligence.repair import ImportRepairBrain
from backend.services.imports.intelligence.semantic_detection import SemanticDetectionBrain
from backend.services.imports.intelligence.sheet_classification import SheetClassificationBrain
from backend.services.imports.intelligence.table_detection import TableDetectionBrain
from backend.services.imports.intelligence.validation import ValidationBrain
from backend.services.imports.intelligence.workbook_profiling import WorkbookProfilingBrain
from backend.services.imports.intelligence.xlsx_parser import XlsxParserBrain

_IMPORT_DRAFTS: dict[str, dict[str, Any]] = {}


MVP_BRAINS = [
    FormatDetectionBrain(),
    XlsxParserBrain(),
    CsvParserBrain(),
    WorkbookProfilingBrain(),
    HeaderDetectionBrain(),
    TableDetectionBrain(),
    SheetClassificationBrain(),
    SemanticDetectionBrain(),
    ImportRepairBrain(),
    NormalizationBrain(),
    ValidationBrain(),
    HumanReviewBrain(),
]


def analyze_import_content(content: bytes, filename: str | None = None) -> dict[str, Any]:
    context = ImportContext(filename=filename or "upload", content=content)
    for brain in MVP_BRAINS:
        if _has_blocking_format(context, brain.name):
            break
        try:
            brain.run(context)
        except Exception as exc:
            from backend.services.imports.intelligence.diagnostics import diagnostic
            from backend.services.imports.intelligence.models import BrainResult

            context.add_result(
                BrainResult(
                    brain.name,
                    "error",
                    0.0,
                    [diagnostic("brain_failed", "error", f"Analyse interrompue dans {brain.name}.", suggestion="Essayez de simplifier le fichier ou contactez le support.", confidence=0.6)],
                    {"technical_error": exc.__class__.__name__},
                )
            )
    result = _build_response(context)
    _save_import_draft(_draft_from_response(result))
    return result


def get_import_analysis(import_id: str) -> dict[str, Any] | None:
    draft = _get_import_draft(import_id)
    if not draft:
        return None
    return draft.get("analysis_response") or draft


def confirm_import(import_id: str, corrections: dict[str, Any] | None = None) -> dict[str, Any] | None:
    draft = _get_import_draft(import_id)
    if not draft:
        return None
    response = dict(draft.get("analysis_response") or draft)
    response["confirmed_corrections"] = corrections or {}
    response["status"] = "ok" if response.get("status") != "blocked" else "needs_review"
    draft["analysis_response"] = response
    _save_import_draft(draft)
    return response


def apply_import(import_id: str, store: Any) -> dict[str, Any] | None:
    draft = _get_import_draft(import_id)
    if not draft:
        return None
    response = draft.get("analysis_response") or draft
    normalized = response.get("normalized_preview") or {}
    created = {"classes": 0, "teachers": 0, "subjects": 0}
    existing_classes = {_clean(item.name).casefold() for item in getattr(store, "classes", [])}
    existing_teachers = {_clean(item.name).casefold() for item in getattr(store, "teachers", [])}
    existing_subjects = {_clean(item.name).casefold() for item in getattr(store, "subjects", [])}
    for item in normalized.get("classes", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_classes:
            store.add_class(name)
            existing_classes.add(name.casefold())
            created["classes"] += 1
    for item in normalized.get("teachers", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_teachers:
            store.add_teacher(name, [])
            existing_teachers.add(name.casefold())
            created["teachers"] += 1
    for item in normalized.get("subjects", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_subjects:
            store.add_subject(name, 1)
            existing_subjects.add(name.casefold())
            created["subjects"] += 1
    return {"import_id": import_id, "status": "applied", "created_entities": created}


def _has_blocking_format(context: ImportContext, next_brain_name: str) -> bool:
    if next_brain_name == "format_detection":
        return False
    return any(item.code == "unsupported_for_now" and item.severity == "blocking" for item in context.diagnostics)


def _build_response(context: ImportContext) -> dict[str, Any]:
    import_id = f"intelligence_{uuid4().hex[:12]}"
    diagnostics = _dedupe_diagnostics([item.to_dict() for item in context.diagnostics])
    blocking = [item for item in diagnostics if item["severity"] == "blocking"]
    errors = [item for item in diagnostics if item["severity"] == "error"]
    status = "blocked" if blocking else "needs_review" if errors or context.human_review_items else "ok"
    normalized = context.normalized_data or _empty_normalized()
    confidence = aggregate_confidence(context.brain_results)
    return {
        "import_id": import_id,
        "status": status,
        "file_type": context.file_type,
        "confidence": confidence,
        "summary": {
            "sheets_count": len(context.sheets),
            "detected_classes": len(normalized.get("classes", [])),
            "detected_teachers": len(normalized.get("teachers", [])),
            "detected_subjects": len(normalized.get("subjects", [])),
            "requirements_count": len(normalized.get("requirements", [])),
            "schedule_grid_preview_count": len(normalized.get("schedule_grid_preview", [])),
            "lesson_candidates_count": len(normalized.get("lesson_candidates", [])),
            "diagnostics_count": len(diagnostics),
            "review_items_count": len(context.human_review_items),
        },
        "sheet_profiles": context.sheet_profiles,
        "sheet_classifications": context.sheet_classifications,
        "normalized_preview": normalized,
        "diagnostics": diagnostics,
        "human_review": context.human_review_items,
        "brain_results": [result.to_dict() for result in context.brain_results],
    }


def _draft_from_response(response: dict[str, Any]) -> dict[str, Any]:
    normalized = response.get("normalized_preview") or {}
    diagnostics = response.get("diagnostics") or []
    return {
        "import_id": response["import_id"],
        "analysis_response": response,
        "diagnostics": {
            "blocking": [item for item in diagnostics if item.get("severity") == "blocking"],
            "warnings": [item for item in diagnostics if item.get("severity") == "warning"],
            "suggestions": [item for item in diagnostics if item.get("severity") == "info"],
        },
        "extracted_entities": {
            "classes": [item.get("name") for item in normalized.get("classes", []) if item.get("name")],
            "teachers": [item.get("name") for item in normalized.get("teachers", []) if item.get("name")],
            "subjects": [item.get("name") for item in normalized.get("subjects", []) if item.get("name")],
            "requirements": normalized.get("requirements", []),
            "schedule_grid_preview": normalized.get("schedule_grid_preview", []),
            "lesson_candidates": normalized.get("lesson_candidates", []),
        },
    }


def _dedupe_diagnostics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("code"), item.get("severity"), item.get("message"), item.get("sheet_name"), item.get("row"), item.get("column"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _empty_normalized() -> dict[str, list[Any]]:
    return {"classes": [], "teachers": [], "subjects": [], "requirements": [], "constraints": [], "availability": [], "schedule_grid_preview": [], "lesson_candidates": [], "source_trace": []}


def _save_import_draft(draft: dict[str, Any]) -> None:
    _IMPORT_DRAFTS[draft["import_id"]] = draft


def _get_import_draft(import_id: str) -> dict[str, Any] | None:
    return _IMPORT_DRAFTS.get(import_id)


def clear_import_drafts() -> None:
    _IMPORT_DRAFTS.clear()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
