from fastapi import APIRouter, Depends
from fastapi import HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import GenerateScheduleResponse, ScheduleCell
from backend.services.explainer import explain_generation_failure
from backend.services.scheduler import SchedulerService


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

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule(store: MemoryStore = Depends(get_store)) -> GenerateScheduleResponse:
    result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots, store.conditions)
    if not result.success:
        store.schedule = {}
        store.schedule_options = []
        store.selected_schedule_option_id = None
        message = result.message or explain_generation_failure(store.classes, store.teachers, store.subjects, store.slots)
        return GenerateScheduleResponse(success=False, message=message, schedule={})

    generated_options = SchedulerService.generate_options(
        store.classes, store.teachers, store.subjects, store.slots, store.conditions
    )
    store.schedule_options = _normalize_options(generated_options)
    best_option = store.schedule_options[0] if store.schedule_options else None
    if best_option is None:
        return GenerateScheduleResponse(success=False, message="No schedule option could be generated.", schedule={})
    store.selected_schedule_option_id = best_option.get("id")
    store.schedule = best_option["schedule"]
    return GenerateScheduleResponse(
        success=True,
        message=result.message,
        schedule=store.schedule,
        quality_score=best_option.get("quality_score"),
        conflicts_count=best_option.get("metrics", {}).get("teacher_conflicts", 0) + best_option.get("metrics", {}).get("class_conflicts", 0),
        gaps_count=best_option.get("metrics", {}).get("empty_gaps", 0),
        repeated_subjects_count=0,
        long_sequences_count=0,
        load_balance_status="good" if (best_option.get("quality_score") or 0) >= 75 else "average" if (best_option.get("quality_score") or 0) >= 50 else "bad",
        score_breakdown=[],
        required_sessions=result.required_sessions,
        scheduled_sessions=result.scheduled_sessions,
        generation_time_ms=result.generation_time_ms,
    )


@router.post("/load-demo", response_model=dict)
def load_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    store.load_demo_data()
    return {"message": "Demo data loaded."}


@router.post("/load-large-demo", response_model=dict)
def load_large_demo_data(store: MemoryStore = Depends(get_store)) -> dict:
    stats = store.load_large_demo_data()
    return {"message": "Large demo data loaded.", "stats": stats}


@router.post("/clear", response_model=dict)
def clear_all_data(store: MemoryStore = Depends(get_store)) -> dict:
    store.clear_all()
    return {"message": "All data cleared."}


@router.get("", response_model=dict[str, dict[str, ScheduleCell]])
def get_schedule(store: MemoryStore = Depends(get_store)) -> dict[str, dict[str, ScheduleCell]]:
    return store.schedule


@router.post("/options/{option_id}/select", response_model=dict)
def select_option(option_id: str, store: MemoryStore = Depends(get_store)) -> dict:
    option = next((item for item in store.schedule_options if item.get("id") == option_id), None)
    if not option:
        raise HTTPException(status_code=404, detail="Schedule option not found")
    store.selected_schedule_option_id = option_id
    store.schedule = option.get("schedule", {})
    store.schedule_options = _normalize_options(store.schedule_options, selected_option_id=option_id)
    return {"message": f"Option '{option_id}' selected.", "selected_option_id": option_id}
