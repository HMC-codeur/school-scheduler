from __future__ import annotations

from statistics import mean
from typing import Any

from backend.services.imports.intelligence.models import BrainResult, ImportDiagnostic


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def status_from_diagnostics(diagnostics: list[ImportDiagnostic], default: str = "ok") -> str:
    severities = {item.severity for item in diagnostics}
    if "blocking" in severities or "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    return default


def aggregate_confidence(results: list[BrainResult]) -> float:
    values = [result.confidence for result in results if result.confidence is not None]
    if not values:
        return 0.0
    return round(clamp(mean(values)), 3)


def entity_confidence(entity: dict[str, Any], fallback: float = 0.6) -> float:
    trace = entity.get("source_trace") or {}
    if isinstance(trace, dict) and trace.get("confidence") is not None:
        return clamp(float(trace["confidence"]))
    return fallback
