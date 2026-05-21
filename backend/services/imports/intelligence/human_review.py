from __future__ import annotations

from backend.services.imports.intelligence.models import BrainResult, ImportContext


class HumanReviewBrain:
    name = "human_review"

    def run(self, context: ImportContext) -> BrainResult:
        items = []
        for diagnostic in context.diagnostics:
            if diagnostic.severity not in {"blocking", "error", "warning"}:
                continue
            if diagnostic.code == "missing_teacher":
                items.append(_item("fill_missing_teacher", "Quel professeur faut-il affecter à cette ligne ?", [], None, diagnostic.confidence, False, diagnostic))
            elif diagnostic.code in {"requirement_missing_class", "requirement_missing_subject", "invalid_weekly_hours"}:
                items.append(_item("fix_requirement", diagnostic.message, [], None, diagnostic.confidence, True, diagnostic))
            elif diagnostic.code == "sheet_needs_human_review":
                items.append(_item("confirm_sheet_type", f"Que faut-il faire avec la feuille '{diagnostic.sheet_name}' ?", ["Ignorer", "Besoins horaires", "Disponibilités", "Contraintes"], "Ignorer", diagnostic.confidence, False, diagnostic))
            elif diagnostic.code == "unsupported_for_now":
                items.append(_item("unsupported_file", diagnostic.message, ["Changer de fichier"], "Changer de fichier", diagnostic.confidence, True, diagnostic))
        items.sort(key=lambda item: (not item["blocking"], -item["confidence"]))
        context.human_review_items = items[:12]
        return context.add_result(
            BrainResult(
                self.name,
                "needs_review" if items else "ok",
                0.85 if items else 0.95,
                data={"human_review": context.human_review_items},
            )
        )


def _item(correction_type, question, options, recommended_value, confidence, blocking, diagnostic):
    return {
        "correction_type": correction_type,
        "question": question,
        "options": options,
        "recommended_value": recommended_value,
        "confidence": round(float(confidence), 3),
        "blocking": bool(blocking),
        "diagnostic_code": diagnostic.code,
        "sheet_name": diagnostic.sheet_name,
        "row": diagnostic.row,
        "column": diagnostic.column,
    }
