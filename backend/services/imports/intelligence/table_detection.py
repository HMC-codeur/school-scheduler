from __future__ import annotations

from backend.services.imports.intelligence.models import BrainResult, ImportContext


class TableDetectionBrain:
    name = "table_detection"

    def run(self, context: ImportContext) -> BrainResult:
        tables = [
            {"sheet_name": header["sheet_name"], "header_row": header["row"], "columns": header["columns"], "confidence": header["confidence"]}
            for header in context.headers
        ]
        context.raw_tables = tables
        return context.add_result(BrainResult(self.name, "ok", 0.75 if tables else 0.35, data={"tables": tables}))
