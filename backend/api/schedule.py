from fastapi import APIRouter, Depends


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import GenerateScheduleResponse, ScheduleCell
from backend.services.scheduler import SchedulerService

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule(store: MemoryStore = Depends(get_store)) -> GenerateScheduleResponse:
    result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots, store.conditions)
    if not result.success:
        store.schedule = {}
        return GenerateScheduleResponse(success=False, message=result.message, schedule={})

    store.schedule = result.schedule
    return GenerateScheduleResponse(
        success=True,
        message=result.message,
        schedule=store.schedule,
        quality_score=result.quality_score,
        conflicts_count=result.conflicts_count,
        gaps_count=result.gaps_count,
        repeated_subjects_count=result.repeated_subjects_count,
        long_sequences_count=result.long_sequences_count,
        load_balance_status=result.load_balance_status,
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
