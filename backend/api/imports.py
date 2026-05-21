from __future__ import annotations

import csv
import hashlib
import json
from io import BytesIO, StringIO
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from backend.data.repository import SchedulerRepository
from backend.data.store import get_store
from backend.models.schemas import ExcelImportCommitRequest
from backend.services.excel_import import commit_excel_import, excel_import_max_bytes, preview_excel_schedule


router = APIRouter(prefix="/imports", tags=["imports"])

_ANALYSES: dict[str, dict[str, Any]] = {}


@router.post("/analyze", response_model=dict)
async def analyze_import(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    if len(content or b"") > excel_import_max_bytes():
        raise HTTPException(status_code=413, detail=f"Import file is too large. Limit is {excel_import_max_bytes()} bytes.")
    result = _analyze_content(content, filename=file.filename)
    _ANALYSES[result["import_id"]] = result
    return result


@router.get("/{import_id}", response_model=dict)
def get_import(import_id: str) -> dict:
    result = _ANALYSES.get(import_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Import analysis '{import_id}' not found")
    return result


@router.post("/{import_id}/confirm", response_model=dict)
def confirm_import(import_id: str, corrections: dict[str, Any] | None = None) -> dict:
    result = _ANALYSES.get(import_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Import analysis '{import_id}' not found")
    confirmed = {**result, "status": "confirmed", "corrections": corrections or {}}
    _ANALYSES[import_id] = confirmed
    return confirmed


@router.post("/{import_id}/apply", response_model=dict)
def apply_import(import_id: str, store: SchedulerRepository = Depends(get_store)) -> dict:
    result = _ANALYSES.get(import_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Import analysis '{import_id}' not found")
    preview = result.get("normalized_preview", {})
    created = _create_missing_entities(preview, store)
    return {
        "import_id": import_id,
        "status": "applied",
        "created_entities": created,
        "message": "Import analysis applied to reference data.",
    }


@router.post("/excel/analyze", response_model=dict)
async def analyze_excel(
    file: UploadFile | None = File(default=None),
    corrections: str | None = Form(default=None),
    debug_compare: bool = Query(default=False),
) -> dict:
    if file is None:
        raise HTTPException(status_code=400, detail="Aucun fichier Excel reçu.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Aucun fichier Excel reçu.")
    if len(content or b"") > excel_import_max_bytes():
        raise HTTPException(status_code=413, detail=f"Excel file is too large. Limit is {excel_import_max_bytes()} bytes.")
    if not _is_excel_filename(file.filename):
        raise HTTPException(status_code=400, detail="Format invalide. Utilisez un fichier .xlsx ou .xlsm.")
    mvp_result = _try_excel_mvp_analyze(content, file.filename, corrections, debug_compare)
    if mvp_result is not None:
        return mvp_result
    preview = preview_excel_schedule(content, filename=file.filename)
    if preview.get("errors"):
        result = _analyze_xlsx_table(content, file.filename)
        result["engine_used"] = "v1"
        return result
    return _excel_preview_to_analysis(preview, filename=file.filename, legacy=True)


@router.get("/excel/schema", response_model=dict)
def get_excel_schema() -> dict:
    return {
        "standard_fields": ["class_name", "subject_name", "teacher_name", "weekly_hours"],
        "supported_files": [".csv", ".xlsx"],
    }


@router.post("/excel/{import_id}/commit", response_model=dict)
def commit_excel(import_id: str, store: SchedulerRepository = Depends(get_store)) -> dict:
    mvp_result = _try_excel_mvp_commit(import_id, store)
    if mvp_result is not None:
        return mvp_result
    response = commit_excel_import(ExcelImportCommitRequest(import_id=import_id), store)
    if not response.success:
        raise HTTPException(status_code=400, detail=response.model_dump(mode="json"))
    return response.model_dump(mode="json")


def _try_excel_mvp_analyze(
    content: bytes,
    filename: str | None,
    corrections: str | None,
    debug_compare: bool,
) -> dict[str, Any] | None:
    try:
        from backend.services.imports.excel_mvp import analyze_excel_content, analyze_excel_content_debug_compare
        from backend.services.imports.excel_readers import ExcelReadError
    except (ImportError, ModuleNotFoundError):
        return None

    try:
        parsed_corrections = _parse_corrections(corrections)
        if debug_compare:
            return analyze_excel_content_debug_compare(content, filename=filename, corrections=parsed_corrections)
        return analyze_excel_content(content, filename=filename, corrections=parsed_corrections)
    except ExcelReadError as exc:
        raise HTTPException(status_code=400, detail=getattr(exc, "message", "Lecture Excel impossible.")) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Le fichier Excel semble vide, corrompu ou non supporté.") from exc


def _try_excel_mvp_commit(import_id: str, store: SchedulerRepository) -> dict[str, Any] | None:
    try:
        from backend.services.imports.excel_mvp import commit_excel_mvp_import, get_import_draft
    except (ImportError, ModuleNotFoundError):
        return None

    draft = get_import_draft(import_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Import draft '{import_id}' not found")
    result = commit_excel_mvp_import(draft, store)
    if result.get("status") == "blocked":
        raise HTTPException(status_code=409, detail=result)
    return result


def _parse_corrections(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Corrections invalides: JSON attendu.") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Corrections invalides: objet JSON attendu.")
    return parsed


def _analyze_content(content: bytes, filename: str | None) -> dict[str, Any]:
    file_type = _file_type(filename)
    if not content:
        return _blocked_analysis(filename, file_type, "empty_file", "Fichier vide.")
    if file_type == "csv":
        return _analyze_csv(content, filename)
    if file_type == "xlsx":
        preview = preview_excel_schedule(content, filename=filename)
        if preview.get("errors"):
            result = _analyze_xlsx_table(content, filename)
            if result["status"] != "blocked":
                return result
            return _analysis_from_diagnostic(filename, file_type, preview["errors"])
        return _excel_preview_to_analysis(preview, filename=filename)
    return _blocked_analysis(filename, file_type, "unsupported_for_now", "Format non supporté pour l'analyse d'import.")


def _analyze_csv(content: bytes, filename: str | None) -> dict[str, Any]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(StringIO(text), dialect=dialect))
    if not rows or not rows[0]:
        return _blocked_analysis(filename, "csv", "empty_csv", "CSV vide ou sans en-têtes lisibles.")

    mapped_rows = [_map_csv_row(row) for row in rows]
    classes = _unique(item.get("class_name") for item in mapped_rows)
    teachers = _unique(item.get("teacher_name") for item in mapped_rows)
    subjects = _unique(item.get("subject_name") for item in mapped_rows)
    requirements = [item for item in mapped_rows if item.get("class_name") or item.get("subject_name") or item.get("teacher_name")]
    diagnostics = []
    if not requirements:
        diagnostics.append(_diagnostic("warning", "no_requirements", "Aucune ligne de besoin exploitable détectée."))
    if any(not item.get("teacher_name") for item in requirements):
        diagnostics.append(_diagnostic("warning", "missing_teacher", "Certaines lignes n'ont pas de professeur détecté."))
    return _analysis_payload(
        filename=filename,
        file_type="csv",
        status="ok" if requirements else "needs_review",
        confidence=0.75 if requirements else 0.35,
        summary={
            "rows_count": len(rows),
            "requirements_count": len(requirements),
            "classes_count": len(classes),
            "teachers_count": len(teachers),
            "subjects_count": len(subjects),
        },
        normalized_preview={
            "classes": [{"name": name} for name in classes],
            "teachers": [{"name": name} for name in teachers],
            "subjects": [{"name": name} for name in subjects],
            "requirements": requirements,
            "constraints": [],
            "availability": [],
            "source_trace": [],
        },
        diagnostics=diagnostics,
    )


def _analyze_xlsx_table(content: bytes, filename: str | None) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return _blocked_analysis(filename, "xlsx", "xlsx_reader_unavailable", "Le lecteur XLSX n'est pas disponible.")

    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception:
        return _blocked_analysis(filename, "xlsx", "xlsx_read_failed", "Fichier Excel vide, corrompu ou non supporté.")

    try:
        best: tuple[int, str, list[Any], list[list[Any]]] | None = None
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            for index, row in enumerate(rows[:20]):
                roles = [_header_role(str(value)) for value in row]
                score = sum(1 for role in roles if role)
                if score >= 2 and (best is None or score > sum(1 for role in [_header_role(str(value)) for value in best[2]] if role)):
                    best = (index, sheet.title, row, rows)
        if best is None:
            return _blocked_analysis(filename, "xlsx", "no_table_detected", "Aucun tableau de besoins exploitable détecté.")

        header_index, sheet_name, header_row, rows = best
        column_roles = {index: _header_role(str(value)) for index, value in enumerate(header_row)}
        mapped_rows = []
        for row in rows[header_index + 1 :]:
            mapped = {}
            for index, value in enumerate(row):
                role = column_roles.get(index)
                if role:
                    mapped[role] = _clean(value)
            if any(mapped.values()):
                mapped_rows.append(mapped)
    finally:
        workbook.close()

    classes = _unique(item.get("class_name") for item in mapped_rows)
    teachers = _unique(item.get("teacher_name") for item in mapped_rows)
    subjects = _unique(item.get("subject_name") for item in mapped_rows)
    requirements = [item for item in mapped_rows if item.get("class_name") or item.get("subject_name") or item.get("teacher_name")]
    diagnostics = []
    if not requirements:
        diagnostics.append(_diagnostic("warning", "no_requirements", "Aucune ligne de besoin exploitable détectée."))
    result = _analysis_payload(
        filename=filename,
        file_type="xlsx",
        status="ok" if requirements else "needs_review",
        confidence=0.72 if requirements else 0.35,
        summary={
            "sheets_count": len(rows) and 1,
            "requirements_count": len(requirements),
            "classes_count": len(classes),
            "teachers_count": len(teachers),
            "subjects_count": len(subjects),
        },
        normalized_preview={
            "classes": [{"name": name} for name in classes],
            "teachers": [{"name": name} for name in teachers],
            "subjects": [{"name": name} for name in subjects],
            "requirements": requirements,
            "constraints": [],
            "availability": [],
            "source_trace": [],
        },
        diagnostics=diagnostics,
    )
    result["sheet_profiles"] = [{"sheet_name": sheet_name, "parser_used": "tracked_xlsx_table"}]
    result["sheet_classifications"] = [{"sheet_name": sheet_name, "sheet_type": "requirements_table"}]
    return result


def _excel_preview_to_analysis(preview: dict[str, Any], filename: str | None, legacy: bool = False) -> dict[str, Any]:
    counts = preview.get("counts", {})
    diagnostics = [_diagnostic("warning", "excel_warning", item) for item in preview.get("warnings", [])]
    payload = _analysis_payload(
        filename=filename,
        file_type="xlsx",
        status="ok",
        confidence=0.7 if preview.get("can_commit") else 0.45,
        summary={
            "sheets_count": 1 if preview.get("sheet_name") else 0,
            "requirements_count": counts.get("lessons", 0),
            "classes_count": counts.get("classes", 0),
            "teachers_count": counts.get("teachers", 0),
            "subjects_count": counts.get("subjects", 0),
        },
        normalized_preview={
            "classes": [{"name": name} for name in preview.get("classes", [])],
            "teachers": [{"name": name} for name in preview.get("teachers", [])],
            "subjects": [{"name": name} for name in preview.get("subjects", [])],
            "requirements": preview.get("lessons", []),
            "constraints": [],
            "availability": [],
            "source_trace": [],
        },
        diagnostics=diagnostics,
        import_id=preview.get("import_id"),
    )
    payload["sheet_profiles"] = [{"sheet_name": preview.get("sheet_name"), "parser_used": preview.get("parser_used")}]
    payload["sheet_classifications"] = [{"sheet_name": preview.get("sheet_name"), "sheet_type": "schedule_grid"}]
    payload["can_commit"] = bool(preview.get("can_commit"))
    if legacy:
        payload["engine_used"] = "v1"
    return payload


def _analysis_from_diagnostic(filename: str | None, file_type: str, messages: list[str]) -> dict[str, Any]:
    return _analysis_payload(
        filename=filename,
        file_type=file_type,
        status="blocked",
        confidence=0.0,
        summary={"requirements_count": 0},
        normalized_preview=_empty_preview(),
        diagnostics=[_diagnostic("blocking", "unsupported_or_unreadable", message) for message in messages],
    )


def _blocked_analysis(filename: str | None, file_type: str, code: str, message: str) -> dict[str, Any]:
    return _analysis_payload(
        filename=filename,
        file_type=file_type,
        status="blocked",
        confidence=0.0,
        summary={"requirements_count": 0},
        normalized_preview=_empty_preview(),
        diagnostics=[_diagnostic("blocking", code, message)],
    )


def _analysis_payload(
    *,
    filename: str | None,
    file_type: str,
    status: str,
    confidence: float,
    summary: dict[str, Any],
    normalized_preview: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    import_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "import_id": import_id or _import_id(filename, file_type, summary, normalized_preview),
        "filename": filename,
        "status": status,
        "file_type": file_type,
        "confidence": confidence,
        "confidence_score": confidence,
        "summary": summary,
        "sheet_profiles": [],
        "sheet_classifications": [],
        "normalized_preview": normalized_preview,
        "diagnostics": diagnostics,
        "human_review": _human_review(diagnostics),
        "can_commit": status == "ok",
    }
    return result


def _map_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key, value in row.items():
        role = _header_role(key)
        if role:
            mapped[role] = _clean(value)
    return mapped


def _header_role(value: str | None) -> str | None:
    normalized = _clean(value).casefold().replace("é", "e").replace("è", "e")
    if normalized in {"classe", "class", "class_name", "כיתה"}:
        return "class_name"
    if normalized in {"matiere", "subject", "subject_name", "מקצוע"}:
        return "subject_name"
    if normalized in {"professeur", "prof", "teacher", "teacher_name", "מורה"}:
        return "teacher_name"
    if normalized in {"heures", "hours", "weekly_hours", "שעות"}:
        return "weekly_hours"
    return None


def _create_missing_entities(preview: dict[str, Any], store: SchedulerRepository) -> dict[str, int]:
    created = {"classes": 0, "teachers": 0, "subjects": 0}
    existing_classes = {_clean(item.name).casefold() for item in store.classes}
    existing_teachers = {_clean(item.name).casefold() for item in store.teachers}
    existing_subjects = {_clean(item.name).casefold() for item in store.subjects}
    for item in preview.get("classes", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_classes:
            store.add_class(name)
            existing_classes.add(name.casefold())
            created["classes"] += 1
    for item in preview.get("subjects", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_subjects:
            store.add_subject(name, 1)
            existing_subjects.add(name.casefold())
            created["subjects"] += 1
    for item in preview.get("teachers", []):
        name = _clean(item.get("name"))
        if name and name.casefold() not in existing_teachers:
            store.add_teacher(name, [])
            existing_teachers.add(name.casefold())
            created["teachers"] += 1
    return created


def _file_type(filename: str | None) -> str:
    suffix = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if suffix in {"csv", "xlsx"}:
        return suffix
    if suffix in {"xlsm", "xls"}:
        return "xlsx"
    return suffix or "unknown"


def _is_excel_filename(filename: str | None) -> bool:
    return (filename or "").lower().endswith((".xlsx", ".xlsm"))


def _empty_preview() -> dict[str, list[Any]]:
    return {"classes": [], "teachers": [], "subjects": [], "requirements": [], "constraints": [], "availability": [], "source_trace": []}


def _diagnostic(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


def _human_review(diagnostics: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"question": item["message"], "code": item["code"]} for item in diagnostics if item.get("severity") in {"blocking", "warning"}]


def _import_id(filename: str | None, file_type: str, summary: dict[str, Any], preview: dict[str, Any]) -> str:
    digest = hashlib.sha1(repr((filename, file_type, summary, preview)).encode("utf-8")).hexdigest()[:12]
    return f"analysis_{digest}"


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
