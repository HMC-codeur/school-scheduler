from fastapi import APIRouter, HTTPException

from backend.data.memory_store import store
from backend.models.schemas import TimeSettings

router = APIRouter(prefix="/time-settings", tags=["time-settings"])


@router.get("", response_model=TimeSettings | None)
def get_time_settings() -> TimeSettings | None:
    return store.time_settings


@router.post("", response_model=dict)
def set_time_settings(payload: TimeSettings) -> dict:
    try:
        slots = store.set_time_settings(payload)
        return {"message": "Time settings saved and slots generated.", "slots": slots}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
