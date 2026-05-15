from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, Depends, Query, Request
from fastapi import HTTPException
from fastapi.responses import Response


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import (
    Condition,
    GenerateScheduleResponse,
    RepairChangedItem,
    RepairProposalPreviewResponse,
    RepairScheduleRequest,
    RepairScheduleResponse,
    ScheduleCell,
)
from backend.services.diagnostics import diagnose_schedule_generation
from backend.services.explainer import explain_generation_failure
from backend.services.scheduler import SchedulerService
from backend.services.scoring import analyze_schedule
from backend.services.scoring import build_schedule_option
from backend.services.solver.models import ScheduleInput
from backend.services.solver.ortools_solver import ORToolsSolver
from backend.services.solver.repair import repair_schedule
from backend.services.solver.models import SolverAssignment
from backend.services.solver.stability import schedule_with_session_ids
from backend.services.excel_import import preview_excel_schedule
from backend.api.platform import build_repair_report_pdf


def _is_complete_option(option: dict) -> bool:
    return bool(
        option.get("id")
        and option.get("schedule") is not None
        and option.get("quality_score") is not None
        and option.get("schedule_signature")
        and isinstance(option.get("metrics"), dict)
    )


def _normalize_options(options: list[dict], selected_option_id: str | None = None) -> list[dict]:
    valid = [opt for opt in options if _is_complete_option(opt)]
    valid.sort(key=lambda option: option.get("quality_score") or 0, reverse=True)
    fallback_selected = selected_option_id if selected_option_id and any(o.get("id") == selected_option_id for o in valid) else (valid[0].get("id") if valid else None)
    for option in valid:
        option["selected"] = option.get("id") == fallback_selected
        option["description"] = str(option.get("description") or "")
        option["schedule_signature"] = str(option.get("schedule_signature") or "")
        option["metrics"] = dict(option.get("metrics") or {})
        option["quality_score"] = int(option.get("quality_score") or 0)
    return valid


def _parse_optional_numeric_id(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    cleaned = value.strip()
    if cleaned.isdigit():
        return int(cleaned)
    suffix = cleaned.rsplit("-", 1)[-1]
    if suffix.isdigit():
        return int(suffix)
    raise HTTPException(status_code=422, detail=f"Invalid numeric id: {value}")


def _repair_response_from_result(
    result,
    request: RepairScheduleRequest,
    schedule: dict,
    previous_schedule: dict | None = None,
    classes: list | None = None,
    subjects: list | None = None,
    teachers: list | None = None,
    *,
    committed: bool = False,
    message: str | None = None,
    proposal_id: str | None = None,
) -> RepairScheduleResponse:
    warnings = []
    policy_warning = result.diagnostics.get("policy_warning")
    if policy_warning:
        warnings.append(str(policy_warning))
    changed_items = (
        _build_repair_changed_items(
            previous_schedule or {},
            result.schedule,
            classes or [],
            subjects or [],
            teachers or [],
        )
        if result.success
        else []
    )
    return RepairScheduleResponse(
        success=result.success,
        message=message or result.message,
        schedule=schedule,
        proposal_id=proposal_id,
        changed_sessions=result.changed_sessions,
        stability_penalty=result.stability_penalty,
        stability_score=result.stability_score,
        hard_conflicts=result.hard_conflicts,
        quality_score=result.quality_score,
        repair_type=request.repair_type,
        repair_policy=result.repair_policy,
        repair_target=result.repair_target,
        final_repair_strategy=result.final_repair_strategy,
        changed_sessions_over_limit=result.changed_sessions_over_limit,
        diagnostics={
            "repair_policy": result.repair_policy,
            "final_repair_strategy": result.final_repair_strategy,
            "changed_sessions": result.changed_sessions,
            "stability_score": result.stability_score,
            "stability_penalty": result.stability_penalty,
            "hard_conflicts": result.hard_conflicts,
            "changed_sessions_over_limit": result.changed_sessions_over_limit,
            "policy_warning": policy_warning,
            "repair_attempts": result.diagnostics.get("repair_attempts", []),
            "pins_initial_count": result.diagnostics.get("pins_initial_count"),
            "pins_relaxed_count": result.diagnostics.get("pins_relaxed_count"),
            "relaxed_pin_reasons": result.diagnostics.get("relaxed_pin_reasons", []),
            "solver": result.diagnostics,
        },
        warnings=warnings,
        committed=committed,
        simulation=not request.commit,
        changed_items=changed_items,
        changed_items_count=len(changed_items),
    )


def _repair_proposals(store: MemoryStore) -> dict[str, dict]:
    proposals = getattr(store, "repair_proposals", None)
    if proposals is None:
        proposals = {}
        setattr(store, "repair_proposals", proposals)
    return proposals


def _serializable_schedule(schedule: dict) -> dict:
    serializable: dict[str, dict[str, dict[str, str | None]]] = {}
    for slot, entries in schedule_with_session_ids(schedule or {}).items():
        serializable[slot] = {
            class_name: cell.model_dump()
            for class_name, cell in entries.items()
        }
    return serializable


def _schedule_versions(store: MemoryStore) -> list[dict]:
    versions = getattr(store, "schedule_versions", None)
    if versions is None:
        versions = []
        setattr(store, "schedule_versions", versions)
    return versions


def _record_schedule_version(
    store: MemoryStore,
    *,
    source: str,
    schedule: dict,
    option_id: str | None = None,
    proposal_id: str | None = None,
    previous_schedule: dict | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict:
    versions = _schedule_versions(store)
    version = {
        "version_id": f"schedule-version-{uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "option_id": option_id,
        "proposal_id": proposal_id,
        "schedule": _serializable_schedule(schedule),
        "rollback": {
            "available": previous_schedule is not None,
            "previous_schedule": _serializable_schedule(previous_schedule or {}) if previous_schedule is not None else {},
        },
        "metadata": metadata or {},
    }
    versions.append(version)
    del versions[:-20]
    return version


def _schedule_size(schedule: dict) -> int:
    return sum(len(entries or {}) for entries in (schedule or {}).values())


def _schedule_version_summary(version: dict) -> dict:
    previous_schedule = (version.get("rollback") or {}).get("previous_schedule") or {}
    return {
        "id": version.get("version_id"),
        "reason": version.get("source"),
        "type": version.get("source"),
        "created_at": version.get("created_at"),
        "has_previous_schedule": bool((version.get("rollback") or {}).get("available")),
        "active_schedule_size": _schedule_size(version.get("schedule") or {}),
        "previous_schedule_size": _schedule_size(previous_schedule) if previous_schedule else 0,
        "option_id": version.get("option_id"),
        "proposal_id": version.get("proposal_id"),
        "metadata": version.get("metadata") or {},
    }


def _set_active_schedule_from_version(
    store: MemoryStore,
    schedule: dict,
    *,
    option_id: str,
    message: str,
) -> None:
    store.schedule = schedule_with_session_ids(schedule)
    if not store.schedule:
        store.schedule_options = []
        store.selected_schedule_option_id = None
        return

    option = build_schedule_option(
        option_id=option_id,
        schedule=store.schedule,
        classes=store.classes,
        teachers=store.teachers,
        subjects=store.subjects,
        slots=store.slots,
        constraints=store.conditions,
    )
    option["id"] = option_id
    option["title"] = "Rollback"
    option["selected"] = True
    option["message"] = message
    existing_options = [option_item for option_item in store.schedule_options if option_item.get("id") != option_id]
    store.schedule_options = _normalize_options([option, *existing_options], selected_option_id=option_id)
    store.selected_schedule_option_id = option_id


def _create_repair_proposal(
    store: MemoryStore,
    response: RepairScheduleResponse,
) -> RepairScheduleResponse:
    proposal_id = f"repair-proposal-{uuid4().hex[:12]}"
    proposal = {
        "proposal_id": proposal_id,
        "schedule": response.schedule,
        "changed_items": [item.model_dump() for item in response.changed_items],
        "diagnostics": response.diagnostics,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repair_policy": response.repair_policy,
        "repair_type": response.repair_type,
        "repair_target": response.repair_target,
        "hard_conflicts": response.hard_conflicts,
        "quality_score": response.quality_score,
        "changed_sessions": response.changed_sessions,
        "stability_penalty": response.stability_penalty,
        "stability_score": response.stability_score,
        "final_repair_strategy": response.final_repair_strategy,
        "changed_sessions_over_limit": response.changed_sessions_over_limit,
    }
    _repair_proposals(store)[proposal_id] = proposal
    diagnostics = dict(response.diagnostics)
    diagnostics["proposal"] = {
        "proposal_id": proposal_id,
        "created_at": proposal["created_at"],
        "status": "pending",
    }
    return response.model_copy(
        update={
            "proposal_id": proposal_id,
            "diagnostics": diagnostics,
        }
    )


def _response_from_proposal(proposal: dict, *, committed: bool, message: str) -> RepairScheduleResponse:
    changed_items = [RepairChangedItem(**item) for item in proposal.get("changed_items", [])]
    return RepairScheduleResponse(
        success=True,
        message=message,
        schedule=proposal.get("schedule", {}),
        proposal_id=proposal.get("proposal_id"),
        changed_sessions=int(proposal.get("changed_sessions") or len(changed_items)),
        stability_penalty=int(proposal.get("stability_penalty") or 0),
        stability_score=int(proposal.get("stability_score") or 0),
        hard_conflicts=int(proposal.get("hard_conflicts") or 0),
        quality_score=proposal.get("quality_score"),
        repair_type=str(proposal.get("repair_type") or ""),
        repair_policy=str(proposal.get("repair_policy") or ""),
        repair_target=proposal.get("repair_target"),
        final_repair_strategy=proposal.get("final_repair_strategy"),
        changed_sessions_over_limit=bool(proposal.get("changed_sessions_over_limit")),
        diagnostics=dict(proposal.get("diagnostics") or {}),
        committed=committed,
        simulation=not committed,
        changed_items=changed_items,
        changed_items_count=len(changed_items),
    )


def _preview_from_proposal(proposal: dict) -> RepairProposalPreviewResponse:
    changed_items = [RepairChangedItem(**item) for item in proposal.get("changed_items", [])]
    return RepairProposalPreviewResponse(
        proposal_id=str(proposal.get("proposal_id")),
        proposed_schedule=proposal.get("schedule", {}),
        changed_items=changed_items,
        changed_items_count=len(changed_items),
        diagnostics=dict(proposal.get("diagnostics") or {}),
        repair_type=str(proposal.get("repair_type") or ""),
        repair_policy=str(proposal.get("repair_policy") or ""),
        created_at=str(proposal.get("created_at") or ""),
        stability_score=int(proposal.get("stability_score") or 0),
        hard_conflicts=int(proposal.get("hard_conflicts") or 0),
        quality_score=proposal.get("quality_score"),
    )


def _commit_repair_schedule(
    store: MemoryStore,
    schedule: dict,
    *,
    option_id: str = "repair-1",
    proposal_id: str | None = None,
    previous_schedule: dict | None = None,
    message: str = "OR-Tools repair proposal accepted.",
    quality_score: int | None = None,
    hard_conflicts: int = 0,
) -> None:
    store.schedule = schedule_with_session_ids(schedule)
    option = build_schedule_option(
        option_id=option_id,
        schedule=store.schedule,
        classes=store.classes,
        teachers=store.teachers,
        subjects=store.subjects,
        slots=store.slots,
        constraints=store.conditions,
    )
    option["id"] = option_id
    option["title"] = "OR-Tools Repair"
    option["selected"] = True
    option["message"] = message
    if quality_score is not None:
        option["quality_score"] = int(quality_score)
    option["conflicts_count"] = hard_conflicts
    existing_options = [option_item for option_item in store.schedule_options if option_item.get("id") != option_id]
    store.schedule_options = _normalize_options([option, *existing_options], selected_option_id=option_id)
    store.selected_schedule_option_id = option_id
    _record_schedule_version(
        store,
        source="accepted_proposal" if proposal_id else "repair_commit",
        schedule=store.schedule,
        option_id=option_id,
        proposal_id=proposal_id,
        previous_schedule=previous_schedule,
        metadata={"message": message, "quality_score": quality_score, "hard_conflicts": hard_conflicts},
    )


def _build_repair_changed_items(
    previous_schedule: dict,
    repaired_schedule: dict,
    classes: list,
    subjects: list,
    teachers: list,
) -> list[RepairChangedItem]:
    if not previous_schedule and not repaired_schedule:
        return []
    class_ids = {class_obj.name: class_obj.id for class_obj in classes}
    teacher_ids = {teacher.name: teacher.id for teacher in teachers}
    subject_ids = {subject.name: subject.name for subject in subjects}
    previous = _assignment_records(previous_schedule)
    repaired = _assignment_records(repaired_schedule)
    previous_by_key = _group_assignment_records(previous)
    repaired_by_key = _group_assignment_records(repaired)
    changed: list[RepairChangedItem] = []
    for key in sorted(set(previous_by_key) | set(repaired_by_key)):
        old_items = list(previous_by_key.get(key, []))
        new_items = list(repaired_by_key.get(key, []))
        pair_count = min(len(old_items), len(new_items))
        for index in range(pair_count):
            old = old_items[index]
            new = new_items[index]
            slot_changed = old["slot"] != new["slot"]
            teacher_changed = old["teacher_name"] != new["teacher_name"]
            if not slot_changed and not teacher_changed:
                continue
            if slot_changed and teacher_changed:
                change_type = "slot_and_teacher_changed"
                reason = "Créneau et professeur changés"
            elif slot_changed:
                change_type = "slot_changed"
                reason = "Cours déplacé pendant la réparation"
            else:
                change_type = "teacher_changed"
                reason = "Professeur changé pendant la réparation"
            changed.append(
                _changed_item(
                    old,
                    new,
                    class_ids,
                    subject_ids,
                    teacher_ids,
                    change_type=change_type,
                    reason=reason,
                )
            )
        for old in old_items[pair_count:]:
            changed.append(
                _changed_item(
                    old,
                    None,
                    class_ids,
                    subject_ids,
                    teacher_ids,
                    change_type="removed",
                    reason="Session retirée",
                )
            )
        for new in new_items[pair_count:]:
            changed.append(
                _changed_item(
                    None,
                    new,
                    class_ids,
                    subject_ids,
                    teacher_ids,
                    change_type="added",
                    reason="Session ajoutée",
                )
            )
    return changed


def _assignment_records(schedule: dict) -> list[dict[str, str]]:
    records = []
    for slot, entries in schedule_with_session_ids(schedule).items():
        for class_name, cell in entries.items():
            records.append(
                {
                    "slot": str(slot),
                    "class_name": str(class_name),
                    "subject_name": cell.subject,
                    "teacher_name": cell.teacher,
                    "session_id": cell.session_id or "",
                }
            )
    return sorted(records, key=lambda item: (item["session_id"], item["class_name"], item["subject_name"], item["slot"], item["teacher_name"]))


def _group_assignment_records(records: list[dict[str, str]]) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for record in records:
        grouped.setdefault((record["session_id"], record["class_name"], record["subject_name"]), []).append(record)
    return grouped


def _changed_item(
    old: dict[str, str] | None,
    new: dict[str, str] | None,
    class_ids: dict[str, int],
    subject_ids: dict[str, str],
    teacher_ids: dict[str, int],
    *,
    change_type: str,
    reason: str,
) -> RepairChangedItem:
    current = new or old or {}
    old_teacher = old.get("teacher_name") if old else None
    new_teacher = new.get("teacher_name") if new else None
    class_name = current.get("class_name")
    subject_name = current.get("subject_name")
    session_id = current.get("session_id") or None
    return RepairChangedItem(
        session_id=session_id,
        class_id=class_ids.get(class_name or ""),
        class_name=class_name,
        subject_id=subject_ids.get(subject_name or "", subject_name),
        subject_name=subject_name,
        old_slot=old.get("slot") if old else None,
        new_slot=new.get("slot") if new else None,
        old_teacher_id=teacher_ids.get(old_teacher or ""),
        new_teacher_id=teacher_ids.get(new_teacher or ""),
        old_teacher_name=old_teacher,
        new_teacher_name=new_teacher,
        change_type=change_type,
        reason=reason,
    )

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _extract_excel_upload(body: bytes, content_type: str) -> tuple[str | None, bytes]:
    if "multipart/form-data" not in content_type.lower():
        return None, body
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    for part in message.iter_parts():
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename or payload:
            return filename, payload
    return None, b""


@router.post("/import/excel/preview", response_model=dict)
async def import_excel_preview(request: Request) -> dict:
    body = await request.body()
    filename, content = _extract_excel_upload(body, request.headers.get("content-type", ""))
    preview = preview_excel_schedule(content, filename=filename)
    if preview.get("errors"):
        raise HTTPException(status_code=400, detail=preview["errors"])
    return preview


@router.get("/diagnose", response_model=dict)
def diagnose_schedule(store: MemoryStore = Depends(get_store)) -> dict:
    return diagnose_schedule_generation(
        store.classes,
        store.teachers,
        store.subjects,
        store.slots,
        store.conditions,
        store.time_settings,
        store.learning_groups,
    )


@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule(
    engine: str = Query(default="legacy"),
    store: MemoryStore = Depends(get_store),
) -> GenerateScheduleResponse:
    started_at = perf_counter()
    normalized_engine = engine.strip().lower()
    if store.learning_groups and normalized_engine in {"legacy", "current", "default"}:
        normalized_engine = "ortools"
    if normalized_engine in {"legacy", "current", "default"}:
        return _generate_legacy_schedule(store, started_at)
    if normalized_engine == "ortools":
        return _generate_ortools_schedule(store, started_at)
    raise HTTPException(status_code=400, detail="Unsupported schedule generation engine. Use 'legacy' or 'ortools'.")


def _generate_legacy_schedule(store: MemoryStore, started_at: float) -> GenerateScheduleResponse:
    generated_options = SchedulerService.generate_options(
        store.classes, store.teachers, store.subjects, store.slots, store.conditions
    )
    store.schedule_options = _normalize_options(generated_options)
    best_option = store.schedule_options[0] if store.schedule_options else None
    if best_option is None:
        result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots, store.conditions)
        store.schedule = {}
        store.schedule_options = []
        store.selected_schedule_option_id = None
        message = result.message or explain_generation_failure(store.classes, store.teachers, store.subjects, store.slots)
        return GenerateScheduleResponse(
            success=False,
            message=message,
            schedule={},
            required_sessions=result.required_sessions,
            scheduled_sessions=result.scheduled_sessions,
            generation_time_ms=int((perf_counter() - started_at) * 1000),
        )
    store.selected_schedule_option_id = best_option.get("id")
    normalized_schedule = schedule_with_session_ids(best_option["schedule"])
    best_option["schedule"] = normalized_schedule
    store.schedule = normalized_schedule
    _record_schedule_version(
        store,
        source="generation",
        schedule=store.schedule,
        option_id=store.selected_schedule_option_id,
        metadata={"engine": "legacy", "quality_score": best_option.get("quality_score")},
    )
    metrics = best_option.get("metrics", {})
    conflicts_count = best_option.get("conflicts_count")
    if conflicts_count is None:
        conflicts_count = metrics.get("teacher_conflicts", 0) + metrics.get("class_conflicts", 0)
    return GenerateScheduleResponse(
        success=True,
        message=best_option.get("message") or "Schedule generated successfully.",
        schedule=store.schedule,
        quality_score=best_option.get("quality_score"),
        conflicts_count=conflicts_count,
        gaps_count=best_option.get("gaps_count", metrics.get("empty_gaps", 0)),
        repeated_subjects_count=best_option.get("repeated_subjects_count", 0),
        long_sequences_count=best_option.get("long_sequences_count", 0),
        load_balance_status=best_option.get("load_balance_status") or ("good" if (best_option.get("quality_score") or 0) >= 75 else "average" if (best_option.get("quality_score") or 0) >= 50 else "bad"),
        score_breakdown=best_option.get("score_breakdown", []),
        required_sessions=best_option.get("required_sessions"),
        scheduled_sessions=best_option.get("scheduled_sessions"),
        generation_time_ms=int((perf_counter() - started_at) * 1000),
    )


def _generate_ortools_schedule(store: MemoryStore, started_at: float) -> GenerateScheduleResponse:
    solver = ORToolsSolver()
    result = solver.solve(
        ScheduleInput(
            classes=store.classes,
            teachers=store.teachers,
            subjects=store.subjects,
            slots=store.slots,
            conditions=store.conditions,
            learning_groups=store.learning_groups,
        )
    )
    if not result.success:
        store.schedule = {}
        store.schedule_options = []
        store.selected_schedule_option_id = None
        return GenerateScheduleResponse(
            success=False,
            message=result.message,
            schedule={},
            quality_score=result.metrics.quality_score,
            conflicts_count=result.metrics.hard_conflicts,
            required_sessions=result.metrics.required_sessions,
            scheduled_sessions=result.metrics.scheduled_sessions,
            generation_time_ms=int((perf_counter() - started_at) * 1000),
        )

    store.schedule = result.schedule
    option = build_schedule_option(
        option_id="ortools-1",
        schedule=result.schedule,
        classes=store.classes,
        teachers=store.teachers,
        subjects=store.subjects,
        slots=store.slots,
        constraints=store.conditions,
        learning_groups=store.learning_groups,
    )
    option["id"] = "ortools-1"
    option["title"] = "OR-Tools V1"
    option["selected"] = True
    option["message"] = result.message
    option["quality_score"] = int(result.metrics.quality_score if result.metrics.quality_score is not None else option.get("quality_score", 0))
    option["metrics"] = {**dict(option.get("metrics") or {}), **result.metrics.as_dict()}
    option["conflicts_count"] = result.metrics.hard_conflicts
    option["gaps_count"] = int(option["metrics"].get("empty_gaps") or 0)
    option["repeated_subjects_count"] = 0
    option["long_sequences_count"] = 0
    option["load_balance_status"] = "good" if option["quality_score"] >= 75 else "average" if option["quality_score"] >= 50 else "bad"
    option["required_sessions"] = result.metrics.required_sessions
    option["scheduled_sessions"] = result.metrics.scheduled_sessions
    option["generation_time_ms"] = result.metrics.generation_time_ms
    option["score_breakdown"] = [
        {"rule": "hard_conflicts", "category": "Hard constraints", "label": "Hard conflicts", "points": -25 * result.metrics.hard_conflicts, "count": result.metrics.hard_conflicts, "raw_points": -25 * result.metrics.hard_conflicts},
        {"rule": "placed_sessions", "category": "Placement", "label": "Sessions placed", "points": result.metrics.scheduled_sessions, "count": result.metrics.scheduled_sessions, "raw_points": result.metrics.scheduled_sessions},
    ]
    store.schedule_options = [option]
    store.selected_schedule_option_id = option["id"]
    _record_schedule_version(
        store,
        source="generation",
        schedule=store.schedule,
        option_id=store.selected_schedule_option_id,
        metadata={"engine": "ortools", "quality_score": option["quality_score"]},
    )
    return GenerateScheduleResponse(
        success=True,
        message=result.message,
        schedule=store.schedule,
        quality_score=option["quality_score"],
        conflicts_count=result.metrics.hard_conflicts,
        gaps_count=option["gaps_count"],
        repeated_subjects_count=0,
        long_sequences_count=0,
        load_balance_status=option["load_balance_status"],
        score_breakdown=option["score_breakdown"],
        required_sessions=result.metrics.required_sessions,
        scheduled_sessions=result.metrics.scheduled_sessions,
        generation_time_ms=int((perf_counter() - started_at) * 1000),
    )


@router.post("/repair", response_model=RepairScheduleResponse)
def repair_current_schedule(
    payload: RepairScheduleRequest,
    store: MemoryStore = Depends(get_store),
) -> RepairScheduleResponse:
    previous_schedule = store.schedule
    if not previous_schedule:
        raise HTTPException(status_code=400, detail="No existing schedule to repair. Generate a schedule first.")

    modified_constraints = [
        Condition(id=900000 + index, **condition.model_dump())
        for index, condition in enumerate(payload.modified_constraints, start=1)
    ]
    pinned_assignments = [
        SolverAssignment(
            slot=assignment.slot,
            class_name=assignment.class_name,
            subject=assignment.subject,
            teacher_name=assignment.teacher_name,
            session_id=assignment.session_id,
        )
        for assignment in payload.pinned_assignments
    ]

    result = repair_schedule(
        previous_schedule=previous_schedule,
        classes=store.classes,
        teachers=store.teachers,
        subjects=store.subjects,
        slots=store.slots,
        conditions=store.conditions,
        repair_type=payload.repair_type,
        repair_policy=payload.repair_policy,
        class_id=_parse_optional_numeric_id(payload.class_id),
        teacher_id=_parse_optional_numeric_id(payload.teacher_id),
        day=payload.day,
        repair_target=payload.repair_target,
        modified_constraints=modified_constraints,
        pinned_assignments=pinned_assignments,
        time_budget=payload.time_budget_seconds,
        strategy=payload.strategy,
    )

    if not result.success or result.hard_conflicts != 0:
        return _repair_response_from_result(
            result,
            payload,
            previous_schedule,
            previous_schedule,
            store.classes,
            store.subjects,
            store.teachers,
            committed=False,
        )

    validation = analyze_schedule(
        result.schedule,
        store.classes,
        store.teachers,
        store.subjects,
        store.slots,
        [*store.conditions, *modified_constraints],
    )
    hard_conflicts = (
        int(validation.get("teacher_conflicts", 0))
        + int(validation.get("class_conflicts", 0))
        + int(validation.get("incompatible_assignments", 0))
        + int(validation.get("unplaced_sessions", 0))
    )
    if hard_conflicts != 0:
        result.diagnostics["api_validation"] = {
            "message": "Repaired schedule failed API hard-conflict validation; existing schedule was kept.",
            "hard_conflicts": hard_conflicts,
            "metrics": validation,
        }
        return _repair_response_from_result(
            result,
            payload,
            previous_schedule,
            previous_schedule,
            store.classes,
            store.subjects,
            store.teachers,
            committed=False,
        )

    if not payload.commit:
        response = _repair_response_from_result(
            result,
            payload,
            result.schedule,
            previous_schedule,
            store.classes,
            store.subjects,
            store.teachers,
            committed=False,
            message="Repair simulated successfully. Current schedule unchanged.",
        )
        return _create_repair_proposal(store, response)

    previous_active_schedule = store.schedule
    store.schedule = result.schedule
    option = build_schedule_option(
        option_id="repair-1",
        schedule=result.schedule,
        classes=store.classes,
        teachers=store.teachers,
        subjects=store.subjects,
        slots=store.slots,
        constraints=[*store.conditions, *modified_constraints],
    )
    option["id"] = "repair-1"
    option["title"] = "OR-Tools Repair"
    option["selected"] = True
    option["message"] = result.message
    option["quality_score"] = int(result.quality_score if result.quality_score is not None else option.get("quality_score", 0))
    option["metrics"] = {**dict(option.get("metrics") or {}), **result.solver_result.metrics.as_dict()}
    option["conflicts_count"] = result.hard_conflicts
    option["gaps_count"] = int(option["metrics"].get("empty_gaps") or 0)
    option["required_sessions"] = result.solver_result.metrics.required_sessions
    option["scheduled_sessions"] = result.solver_result.metrics.scheduled_sessions
    option["generation_time_ms"] = result.solver_result.metrics.generation_time_ms
    existing_options = [option_item for option_item in store.schedule_options if option_item.get("id") != "repair-1"]
    store.schedule_options = _normalize_options([option, *existing_options], selected_option_id="repair-1")
    store.selected_schedule_option_id = "repair-1"
    _record_schedule_version(
        store,
        source="repair_commit",
        schedule=store.schedule,
        option_id="repair-1",
        previous_schedule=previous_active_schedule,
        metadata={"repair_type": payload.repair_type, "repair_policy": payload.repair_policy},
    )
    return _repair_response_from_result(
        result,
        payload,
        store.schedule,
        previous_schedule,
        store.classes,
        store.subjects,
        store.teachers,
        committed=True,
        message="Schedule repaired and committed successfully.",
    )


@router.get("/repair/proposals/{proposal_id}", response_model=RepairProposalPreviewResponse)
def preview_repair_proposal(
    proposal_id: str,
    store: MemoryStore = Depends(get_store),
) -> RepairProposalPreviewResponse:
    proposal = _repair_proposals(store).get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Repair proposal not found.")
    return _preview_from_proposal(proposal)


@router.post("/repair/proposals/{proposal_id}/accept", response_model=RepairScheduleResponse)
def accept_repair_proposal(
    proposal_id: str,
    store: MemoryStore = Depends(get_store),
) -> RepairScheduleResponse:
    proposals = _repair_proposals(store)
    proposal = proposals.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Repair proposal not found.")

    if int(proposal.get("hard_conflicts") or 0) != 0:
        raise HTTPException(status_code=400, detail="Repair proposal cannot be accepted because it has hard conflicts.")

    validation = analyze_schedule(
        proposal.get("schedule", {}),
        store.classes,
        store.teachers,
        store.subjects,
        store.slots,
        store.conditions,
    )
    hard_conflicts = (
        int(validation.get("teacher_conflicts", 0))
        + int(validation.get("class_conflicts", 0))
        + int(validation.get("incompatible_assignments", 0))
        + int(validation.get("unplaced_sessions", 0))
    )
    if hard_conflicts != 0:
        raise HTTPException(status_code=400, detail="Repair proposal failed hard-conflict validation.")

    _commit_repair_schedule(
        store,
        proposal.get("schedule", {}),
        option_id=f"repair-{proposal_id}",
        proposal_id=proposal_id,
        previous_schedule=store.schedule,
        message="Repair proposal accepted and committed successfully.",
        quality_score=proposal.get("quality_score"),
        hard_conflicts=hard_conflicts,
    )
    accepted = proposals.pop(proposal_id)
    response = _response_from_proposal(
        accepted,
        committed=True,
        message="Repair proposal accepted and committed successfully.",
    )
    diagnostics = dict(response.diagnostics)
    diagnostics["proposal"] = {
        "proposal_id": proposal_id,
        "created_at": accepted.get("created_at"),
        "status": "accepted",
    }
    return response.model_copy(update={"schedule": store.schedule, "diagnostics": diagnostics})


@router.delete("/repair/proposals/{proposal_id}", response_model=dict)
def delete_repair_proposal(
    proposal_id: str,
    store: MemoryStore = Depends(get_store),
) -> dict:
    proposals = _repair_proposals(store)
    proposal = proposals.pop(proposal_id, None)
    if not proposal:
        raise HTTPException(status_code=404, detail="Repair proposal not found.")
    return {
        "success": True,
        "message": "Repair proposal deleted. Current schedule unchanged.",
        "proposal_id": proposal_id,
        "deleted": True,
    }


@router.get("/repair/proposals/{proposal_id}/export/pdf")
def export_repair_proposal_pdf(
    proposal_id: str,
    store: MemoryStore = Depends(get_store),
) -> Response:
    proposal = _repair_proposals(store).get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Repair proposal not found.")
    pdf = build_repair_report_pdf(proposal, store)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="repair-report-{proposal_id}.pdf"'},
    )


@router.post("/load-demo", response_model=dict)
def load_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    store.load_demo_data()
    return {"message": "Demo data loaded."}


@router.post("/load-large-demo", response_model=dict)
def load_large_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    stats = store.load_large_demo_data()
    return {"message": "Large demo data loaded.", "stats": stats}


@router.post("/load-pilot-demo", response_model=dict)
def load_pilot_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    stats = store.load_pilot_demo_data()
    return {"message": "Pilot demo data loaded.", "stats": stats}


@router.post("/load-learning-groups-demo", response_model=dict)
def load_learning_groups_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    stats = store.load_learning_groups_demo_data()
    return {"message": "Learning groups demo data loaded.", "stats": stats}


@router.post("/clear", response_model=dict)
def clear_all_data(store: MemoryStore = Depends(get_store)) -> dict:
    store.clear_all()
    return {"message": "All data cleared."}


@router.get("/versions", response_model=list[dict])
def list_schedule_versions(store: MemoryStore = Depends(get_store)) -> list[dict]:
    return [_schedule_version_summary(version) for version in reversed(_schedule_versions(store))]


@router.post("/versions/{version_id}/rollback", response_model=dict)
def rollback_schedule_version(
    version_id: str,
    store: MemoryStore = Depends(get_store),
) -> dict:
    version = next((item for item in _schedule_versions(store) if item.get("version_id") == version_id), None)
    if not version:
        raise HTTPException(status_code=404, detail="Schedule version not found.")

    rollback = version.get("rollback") or {}
    if not rollback.get("available"):
        raise HTTPException(status_code=400, detail="Schedule version has no previous schedule to restore.")

    previous_schedule = rollback.get("previous_schedule") or {}
    current_schedule = store.schedule
    option_id = f"rollback-{version_id}"
    _set_active_schedule_from_version(
        store,
        previous_schedule,
        option_id=option_id,
        message=f"Rolled back schedule version {version_id}.",
    )
    _repair_proposals(store).clear()
    rollback_version = _record_schedule_version(
        store,
        source="rollback",
        schedule=store.schedule,
        option_id=option_id if store.schedule else None,
        previous_schedule=current_schedule,
        metadata={"rolled_back_from": version_id},
    )
    return {
        "success": True,
        "message": f"Schedule rolled back from version {version_id}.",
        "rolled_back_from": version_id,
        "version_id": rollback_version["version_id"],
        "schedule": store.schedule,
    }


@router.get("", response_model=dict[str, dict[str, ScheduleCell]])
def get_schedule(store: MemoryStore = Depends(get_store)) -> dict[str, dict[str, ScheduleCell]]:
    return store.schedule


@router.post("/options/{option_id}/select", response_model=dict)
def select_option(option_id: str, store: MemoryStore = Depends(get_store)) -> dict:
    option = next((item for item in store.schedule_options if item.get("id") == option_id), None)
    if not option:
        raise HTTPException(status_code=404, detail="Schedule option not found")
    previous_schedule = store.schedule
    store.selected_schedule_option_id = option_id
    store.schedule = schedule_with_session_ids(option.get("schedule", {}))
    store.schedule_options = _normalize_options(store.schedule_options, selected_option_id=option_id)
    _record_schedule_version(
        store,
        source="option_select",
        schedule=store.schedule,
        option_id=option_id,
        previous_schedule=previous_schedule,
        metadata={"message": f"Option '{option_id}' selected."},
    )
    return {"message": f"Option '{option_id}' selected.", "selected_option_id": option_id}
