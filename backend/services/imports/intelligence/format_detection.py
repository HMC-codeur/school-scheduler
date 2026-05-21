from __future__ import annotations

from pathlib import Path

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.models import BrainResult, ImportContext


class FormatDetectionBrain:
    name = "format_detection"

    def run(self, context: ImportContext) -> BrainResult:
        suffix = Path(context.filename or "").suffix.casefold()
        head = context.content[:16]
        file_type = "unknown"
        diagnostics = []

        if suffix in {".xlsx", ".xlsm"} or head.startswith(b"PK"):
            file_type = "xlsx"
        elif suffix == ".xls":
            file_type = "xls"
            diagnostics.append(
                diagnostic(
                    "xls_legacy_format",
                    "warning",
                    "Fichier Excel ancien format détecté. Il peut être lu si les lecteurs installés le supportent.",
                    suggestion="Si l'analyse échoue, réenregistrez le fichier en .xlsx.",
                    confidence=0.8,
                )
            )
        elif suffix == ".csv" or _looks_like_csv(context.content):
            file_type = "csv"
        elif suffix == ".pdf" or head.startswith(b"%PDF"):
            file_type = "pdf"
            diagnostics.append(
                diagnostic(
                    "unsupported_for_now",
                    "blocking",
                    "PDF détecté. L'import PDF/OCR n'est pas activé pour le moment.",
                    suggestion="Exportez le fichier en Excel ou CSV pour ce MVP.",
                    confidence=1.0,
                )
            )
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            file_type = "image"
            diagnostics.append(
                diagnostic(
                    "unsupported_for_now",
                    "blocking",
                    "Image détectée. L'import image/OCR n'est pas activé pour le moment.",
                    suggestion="Utilisez un fichier Excel ou CSV.",
                    confidence=1.0,
                )
            )
        else:
            diagnostics.append(
                diagnostic(
                    "unknown_file_type",
                    "blocking",
                    "Format de fichier non reconnu.",
                    suggestion="Utilisez un fichier .xlsx ou .csv.",
                    confidence=0.5,
                )
            )

        context.file_type = file_type  # type: ignore[assignment]
        status = "error" if any(item.severity == "blocking" for item in diagnostics) else "ok"
        confidence = 1.0 if file_type in {"xlsx", "csv", "pdf", "image"} else 0.4
        return context.add_result(
            BrainResult(
                brain_name=self.name,
                status=status,  # type: ignore[arg-type]
                confidence=confidence,
                diagnostics=diagnostics,
                data={"file_type": file_type},
            )
        )


def _looks_like_csv(content: bytes) -> bool:
    sample = content[:2048]
    if not sample or b"\x00" in sample:
        return False
    text = sample.decode("utf-8-sig", errors="ignore")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return any(separator in lines[0] for separator in [",", ";", "\t"]) and any(
        separator in lines[1] for separator in [",", ";", "\t"]
    )
