from fastapi import APIRouter, HTTPException

from backend.data.memory_store import store
from backend.models.schemas import SlotCreate

router = APIRouter(prefix="/slots", tags=["slots"])


@router.post("", response_model=str)
def create_slot(payload: SlotCreate) -> str:
    try:
        return store.add_slot(payload.slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[str])
def list_slots() -> list[str]:
    return store.slots
