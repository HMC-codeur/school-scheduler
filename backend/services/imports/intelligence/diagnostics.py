from __future__ import annotations

from backend.services.imports.intelligence.models import ImportDiagnostic


def diagnostic(
    code: str,
    severity: str,
    message: str,
    *,
    sheet_name: str | None = None,
    row: int | None = None,
    column: str | None = None,
    suggestion: str | None = None,
    confidence: float = 1.0,
) -> ImportDiagnostic:
    return ImportDiagnostic(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        sheet_name=sheet_name,
        row=row,
        column=column,
        suggestion=suggestion,
        confidence=confidence,
    )


def flatten_diagnostics(groups: list[list[ImportDiagnostic]]) -> list[ImportDiagnostic]:
    return [item for group in groups for item in group]
