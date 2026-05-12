from fastapi import APIRouter

from backend.data.memory_store import store
from backend.models.schemas import GenerateScheduleResponse, ScheduleCell
from backend.services.scheduler import SchedulerService

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule() -> GenerateScheduleResponse:
    result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots)
    if not result.success:
        store.schedule = {}
        return GenerateScheduleResponse(success=False, message=result.message, schedule={})

    store.schedule = result.schedule
    return GenerateScheduleResponse(success=True, message=result.message, schedule=store.schedule)


@router.post("/load-demo", response_model=dict)
def load_demo_data() -> dict:
    store.load_demo_data()
    return {"message": "Demo data loaded."}


@router.post("/clear", response_model=dict)
def clear_all_data() -> dict:
    store.clear_all()
    return {"message": "All data cleared."}


@router.get("", response_model=dict[str, dict[str, ScheduleCell]])
def get_schedule() -> dict[str, dict[str, ScheduleCell]]:
    return store.schedule
