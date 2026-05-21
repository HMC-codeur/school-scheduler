from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportContext
from backend.services.imports.intelligence.normalizers import fold_key, normalize_text


SUBJECT_ALIASES = {
    "math": "Mathématiques",
    "maths": "Mathématiques",
    "mathematiques": "Mathématiques",
    "mathematique": "Mathématiques",
}


class ImportRepairBrain:
    name = "repair"

    def run(self, context: ImportContext) -> BrainResult:
        repairs: list[dict[str, Any]] = []
        for bucket in ("classes", "teachers", "subjects"):
            context.semantic_entities[bucket] = _dedupe_entities(context.semantic_entities.get(bucket, []), bucket, repairs)
        for requirement in context.semantic_entities.get("requirements", []):
            for field in ("class_name", "teacher_name", "subject_name"):
                original = requirement.get(field)
                normalized = _normalize_value(original, field)
                if original != normalized:
                    repairs.append({"type": "normalize_value", "field": field, "from": original, "to": normalized, "source_trace": requirement.get("source_trace")})
                    requirement[field] = normalized
        return context.add_result(BrainResult(self.name, "ok", 0.9, data={"repairs": repairs}))


def _normalize_value(value: Any, field: str) -> str | None:
    cleaned = normalize_text(value)
    if not cleaned:
        return None
    if field == "subject_name":
        return SUBJECT_ALIASES.get(fold_key(cleaned), cleaned)
    return " ".join(part for part in cleaned.split())


def _dedupe_entities(items: list[dict[str, Any]], bucket: str, repairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        name = _normalize_value(item.get("name"), "subject_name" if bucket == "subjects" else bucket[:-1])
        if not name:
            continue
        key = fold_key(name)
        if key in seen:
            repairs.append({"type": "merge_duplicate", "entity_type": bucket, "value": item.get("name"), "merged_into": name, "source_trace": item.get("source_trace")})
            continue
        seen.add(key)
        clone = dict(item)
        clone["name"] = name
        result.append(clone)
    return result
