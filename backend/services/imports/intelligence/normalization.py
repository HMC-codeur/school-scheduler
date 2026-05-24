from __future__ import annotations

from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportContext


class NormalizationBrain:
    name = "normalization"

    def run(self, context: ImportContext) -> BrainResult:
        entities = context.semantic_entities
        normalized = {
            "classes": [_entity(item) for item in entities.get("classes", [])],
            "teachers": [_entity(item) for item in entities.get("teachers", [])],
            "subjects": [_entity(item) for item in entities.get("subjects", [])],
            "requirements": [_requirement(item) for item in entities.get("requirements", [])],
            "constraints": list(entities.get("constraints", [])),
            "availability": list(entities.get("availability", [])),
            "schedule_grid_preview": list(entities.get("schedule_grid_preview", [])),
            "lesson_candidates": list(entities.get("lesson_candidates", [])),
            "source_trace": [],
        }
        for bucket in ("classes", "teachers", "subjects", "requirements", "constraints", "availability", "schedule_grid_preview", "lesson_candidates"):
            for item in normalized[bucket]:
                trace = item.get("source_trace")
                if trace:
                    normalized["source_trace"].append({"entity_type": bucket, **trace})
        context.normalized_data = normalized
        count = sum(len(normalized[key]) for key in ("classes", "teachers", "subjects", "requirements", "constraints", "availability", "schedule_grid_preview"))
        return context.add_result(BrainResult(self.name, "ok", 0.86 if count else 0.35, data={"normalized_data": normalized}))


def _entity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "confidence": item.get("confidence", 0.6),
        "source_trace": item.get("source_trace"),
    }


def _requirement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "class_name": item.get("class_name"),
        "subject_name": item.get("subject_name"),
        "teacher_name": item.get("teacher_name"),
        "weekly_hours": item.get("weekly_hours"),
        "confidence": item.get("confidence", 0.6),
        "source_trace": item.get("source_trace"),
    }
