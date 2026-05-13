from fastapi import APIRouter, Depends
from fastapi import HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import GenerateScheduleResponse, ScheduleCell
from backend.services.explainer import explain_generation_failure
from backend.services.scheduler import SchedulerService

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

    store.schedule_options = SchedulerService.generate_options(
        store.classes, store.teachers, store.subjects, store.slots, store.conditions
    )
    if not store.schedule_options:
        store.schedule_options = [{
            "id": "option-1",
            "label": "Option 1",
            "schedule": result.schedule,
            "quality_score": result.quality_score,
            "conflicts_count": result.conflicts_count,
            "gaps_count": result.gaps_count,
            "repeated_subjects_count": result.repeated_subjects_count,
            "long_sequences_count": result.long_sequences_count,
            "load_balance_status": result.load_balance_status,
            "message": result.message,
            "score_breakdown": result.score_breakdown or [],
        }]
    best_option = max(store.schedule_options, key=lambda option: option.get("quality_score") or 0)
    store.selected_schedule_option_id = best_option.get("id")
    store.schedule = best_option["schedule"]
    return GenerateScheduleResponse(
        success=True,
        message=result.message,
        schedule=store.schedule,
        quality_score=best_option.get("quality_score"),
        conflicts_count=best_option.get("conflicts_count"),
        gaps_count=best_option.get("gaps_count"),
        repeated_subjects_count=best_option.get("repeated_subjects_count"),
        long_sequences_count=best_option.get("long_sequences_count"),
        load_balance_status=best_option.get("load_balance_status"),
        score_breakdown=best_option.get("score_breakdown"),
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
    return {"message": f"Option '{option_id}' selected.", "selected_option_id": option_id}
