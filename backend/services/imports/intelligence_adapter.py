from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.orchestrator import analyze_import_content


def analyze_with_intelligence_brains(content: bytes, filename: str | None = None) -> dict[str, Any]:
    result = analyze_import_content(content, filename=filename)
    normalized = _normalized_preview(result)
    diagnostics = _diagnostics(result)
    counts = _counts(result, normalized)
    blocking = any(item.get("severity") == "blocking" for item in diagnostics)
    has_data = counts["requirements_count"] > 0 or counts["availability_count"] > 0
    schedule_grid_unextracted = _has_schedule_grid(result) and not has_data

    if schedule_grid_unextracted and not _has_diagnostic(diagnostics, "schedule_grid_requires_review"):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "schedule_grid_requires_review",
                "message": "A schedule grid was detected, but it cannot be applied automatically yet.",
            }
        )
    if not has_data and not _has_diagnostic(diagnostics, "no_importable_data"):
        diagnostics.append(
            {
                "severity": "blocking",
                "code": "no_importable_data",
                "message": "Aucune donnée importable n'a été détectée.",
            }
        )
        blocking = True

    needs_review = bool(diagnostics) or bool(result.get("human_review")) or schedule_grid_unextracted or not has_data
    can_apply = bool(has_data and not blocking)
    summary = {
        **(result.get("summary") or {}),
        "classes_count": counts["classes_count"],
        "teachers_count": counts["teachers_count"],
        "subjects_count": counts["subjects_count"],
        "requirements_count": counts["requirements_count"],
        "availability_count": counts["availability_count"],
    }

    return {
        **result,
        "import_id": result.get("import_id"),
        "filename": filename,
        "status": "blocked" if blocking else result.get("status", "needs_review"),
        "diagnostics": diagnostics,
        "normalized_preview": normalized,
        "summary": summary,
        **counts,
        "confidence": float(result.get("confidence") or 0.0),
        "confidence_score": float(result.get("confidence") or 0.0),
        "can_apply": can_apply,
        "can_commit": can_apply,
        "needs_human_review": needs_review,
    }


def _normalized_preview(result: dict[str, Any]) -> dict[str, list[Any]]:
    preview = result.get("normalized_preview") or {}
    return {
        "classes": list(preview.get("classes") or []),
        "teachers": list(preview.get("teachers") or []),
        "subjects": list(preview.get("subjects") or []),
        "requirements": list(preview.get("requirements") or []),
        "constraints": list(preview.get("constraints") or []),
        "availability": list(preview.get("availability") or []),
        "source_trace": list(preview.get("source_trace") or []),
    }


def _diagnostics(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in result.get("diagnostics") or [] if isinstance(item, dict)]


def _counts(result: dict[str, Any], normalized: dict[str, list[Any]]) -> dict[str, int]:
    summary = result.get("summary") or {}
    return {
        "classes_count": int(summary.get("classes_count") or summary.get("detected_classes") or len(normalized["classes"])),
        "teachers_count": int(summary.get("teachers_count") or summary.get("detected_teachers") or len(normalized["teachers"])),
        "subjects_count": int(summary.get("subjects_count") or summary.get("detected_subjects") or len(normalized["subjects"])),
        "requirements_count": int(summary.get("requirements_count") or len(normalized["requirements"])),
        "availability_count": int(summary.get("availability_count") or len(normalized["availability"])),
    }


def _has_schedule_grid(result: dict[str, Any]) -> bool:
    return any(item.get("sheet_type") == "schedule_grid" for item in result.get("sheet_classifications") or [])


def _has_diagnostic(diagnostics: list[dict[str, Any]], code: str) -> bool:
    return any(item.get("code") == code for item in diagnostics)
