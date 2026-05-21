from __future__ import annotations

import csv
from io import StringIO

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.models import BrainResult, ImportContext, ImportSheet
from backend.services.imports.intelligence.normalizers import normalize_text


class CsvParserBrain:
    name = "csv_parser"

    def run(self, context: ImportContext) -> BrainResult:
        if context.file_type != "csv":
            return context.add_result(BrainResult(self.name, "ok", 1.0, data={"skipped": True}))
        diagnostics = []
        try:
            text = context.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = context.content.decode("latin-1", errors="replace")
            diagnostics.append(diagnostic("csv_encoding_fallback", "warning", "CSV lu avec un encodage de secours."))
        delimiter = _detect_delimiter(text)
        reader = csv.reader(StringIO(text), delimiter=delimiter)
        rows: dict[int, dict[int, str]] = {}
        max_column = 0
        for row_index, row in enumerate(reader, start=1):
            values = {column: normalize_text(value) for column, value in enumerate(row, start=1) if normalize_text(value)}
            if values:
                rows[row_index] = values
                max_column = max(max_column, max(values))
        sheet = ImportSheet(name="CSV", rows=rows, max_row=max(rows, default=0), max_column=max_column)
        context.sheets = [sheet]
        if sheet.non_empty_cells_count == 0:
            diagnostics.append(diagnostic("empty_file", "blocking", "Le CSV ne contient aucune donnée lisible."))
        return context.add_result(
            BrainResult(
                self.name,
                "error" if any(item.severity == "blocking" for item in diagnostics) else "ok",
                0.95 if sheet.non_empty_cells_count else 0.0,
                diagnostics,
                {"delimiter": delimiter, "sheets_count": len(context.sheets)},
            )
        )


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in [",", ";", "\t"]}
        return max(counts, key=counts.get)
