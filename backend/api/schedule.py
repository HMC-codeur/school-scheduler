from fastapi import APIRouter

from backend.data.memory_store import store
from backend.models.schemas import GenerateScheduleResponse
from backend.services.scheduler import SchedulerService

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule() -> GenerateScheduleResponse:
    result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots)
    if result is None:
        store.schedule = {}
        return GenerateScheduleResponse(success=False, message="no valid schedule found", schedule={})

    store.schedule = result
    return GenerateScheduleResponse(success=True, message="schedule generated", schedule=store.schedule)


@router.get("", response_model=dict)
def get_schedule() -> dict:
    return store.schedule
