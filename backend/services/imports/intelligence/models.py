from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


DiagnosticSeverity = Literal["info", "warning", "error", "blocking"]
BrainStatus = Literal["ok", "warning", "error", "needs_review"]
FileType = Literal["xlsx", "xls", "csv", "pdf", "image", "unknown"]


@dataclass
class ImportDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    sheet_name: str | None = None
    row: int | None = None
    column: str | None = None
    suggestion: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "sheet_name": self.sheet_name,
            "row": self.row,
            "column": self.column,
            "suggestion": self.suggestion,
            "confidence": round(float(self.confidence), 3),
        }


@dataclass
class BrainResult:
    brain_name: str
    status: BrainStatus
    confidence: float
    diagnostics: list[ImportDiagnostic] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brain_name": self.brain_name,
            "status": self.status,
            "confidence": round(float(self.confidence), 3),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "data": self.data,
        }


@dataclass
class ImportCell:
    row: int
    column: int
    value: str


@dataclass
class ImportSheet:
    name: str
    rows: dict[int, dict[int, str]] = field(default_factory=dict)
    max_row: int = 0
    max_column: int = 0
    merged_cells_count: int = 0

    @property
    def non_empty_cells_count(self) -> int:
        return sum(1 for row in self.rows.values() for value in row.values() if str(value).strip())

    def first_rows(self, limit: int = 12, max_columns: int = 12) -> list[list[str]]:
        return [
            [self.rows.get(row_index, {}).get(col_index, "") for col_index in range(1, min(self.max_column, max_columns) + 1)]
            for row_index in range(1, min(self.max_row, limit) + 1)
        ]


@dataclass
class ImportContext:
    filename: str
    file_type: FileType = "unknown"
    content: bytes = b""
    sheets: list[ImportSheet] = field(default_factory=list)
    raw_tables: list[dict[str, Any]] = field(default_factory=list)
    detected_language: str | None = None
    sheet_profiles: list[dict[str, Any]] = field(default_factory=list)
    sheet_classifications: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, Any]] = field(default_factory=list)
    semantic_entities: dict[str, Any] = field(default_factory=dict)
    normalized_data: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[ImportDiagnostic] = field(default_factory=list)
    human_review_items: list[dict[str, Any]] = field(default_factory=list)
    brain_results: list[BrainResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_diagnostics(self, diagnostics: list[ImportDiagnostic]) -> None:
        self.diagnostics.extend(diagnostics)

    def add_result(self, result: BrainResult) -> BrainResult:
        self.brain_results.append(result)
        self.add_diagnostics(result.diagnostics)
        return result


def source_trace(sheet: str, row: int | None, column: int | str | None, original_value: Any, confidence: float) -> dict[str, Any]:
    return {
        "sheet": sheet,
        "row": row,
        "column": str(column) if column is not None else None,
        "original_value": original_value,
        "confidence": round(float(confidence), 3),
    }
