from __future__ import annotations

from backend.services.imports.intelligence.diagnostics import diagnostic
from backend.services.imports.intelligence.models import BrainResult, ImportContext
from backend.services.imports.intelligence.normalizers import fold_key


class ValidationBrain:
    name = "validation"

    def run(self, context: ImportContext) -> BrainResult:
        diagnostics = []
        data = context.normalized_data
        requirements = data.get("requirements", [])
        classes_with_requirements = {fold_key(item.get("class_name")) for item in requirements if item.get("class_name")}
        for class_item in data.get("classes", []):
            if fold_key(class_item.get("name")) not in classes_with_requirements:
                diagnostics.append(diagnostic("class_without_requirements", "warning", f"La classe {class_item.get('name')} n'a pas de besoins horaires détectés.", sheet_name=_sheet(class_item), confidence=0.8))
        seen_requirements = set()
        for requirement in requirements:
            trace = requirement.get("source_trace") or {}
            if not requirement.get("class_name"):
                diagnostics.append(diagnostic("requirement_missing_class", "blocking", "Un besoin horaire n'a pas de classe.", sheet_name=trace.get("sheet"), row=trace.get("row"), suggestion="Renseignez la classe ou ignorez la ligne.", confidence=0.95))
            if not requirement.get("subject_name"):
                diagnostics.append(diagnostic("requirement_missing_subject", "blocking", "Un besoin horaire n'a pas de matière.", sheet_name=trace.get("sheet"), row=trace.get("row"), suggestion="Renseignez la matière ou ignorez la ligne.", confidence=0.95))
            if not requirement.get("teacher_name"):
                diagnostics.append(diagnostic("missing_teacher", "warning", "Un besoin horaire n'a pas de professeur.", sheet_name=trace.get("sheet"), row=trace.get("row"), suggestion="Ajoutez le professeur si cette information est connue.", confidence=0.9))
            hours = requirement.get("weekly_hours")
            if hours is None or not isinstance(hours, (int, float)) or hours <= 0 or hours > 40:
                diagnostics.append(diagnostic("invalid_weekly_hours", "error", "Volume horaire invalide ou absent.", sheet_name=trace.get("sheet"), row=trace.get("row"), suggestion="Indiquez un nombre d'heures hebdomadaires positif.", confidence=0.9))
            key = (fold_key(requirement.get("class_name")), fold_key(requirement.get("subject_name")), fold_key(requirement.get("teacher_name")), hours)
            if key in seen_requirements:
                diagnostics.append(diagnostic("duplicate_requirement", "warning", "Besoin horaire en doublon probable.", sheet_name=trace.get("sheet"), row=trace.get("row"), suggestion="Vérifiez si cette ligne doit être fusionnée.", confidence=0.8))
            seen_requirements.add(key)
        for item in context.sheet_classifications:
            if item.get("sheet_type") in {"ignored", "metadata"}:
                diagnostics.append(diagnostic("sheet_ignored", "info", "Feuille ignorée pour l'import automatique.", sheet_name=item.get("sheet_name"), confidence=item.get("confidence", 0.8)))
            elif item.get("needs_human_review"):
                diagnostics.append(diagnostic("sheet_needs_human_review", "warning", "Feuille à confirmer avant import.", sheet_name=item.get("sheet_name"), suggestion="Confirmez son type ou ignorez-la.", confidence=item.get("confidence", 0.6)))
        status = "error" if any(item.severity in {"blocking", "error"} for item in diagnostics) else "warning" if diagnostics else "ok"
        return context.add_result(BrainResult(self.name, status, 0.78 if diagnostics else 0.95, diagnostics, {"diagnostics_count": len(diagnostics)}))  # type: ignore[arg-type]


def _sheet(item: dict) -> str | None:
    trace = item.get("source_trace") or {}
    return trace.get("sheet")
