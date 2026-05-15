from fastapi import APIRouter, Depends, HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import SlotCreate

router = APIRouter(prefix="/slots", tags=["slots"])


@router.post("", response_model=str)
def create_slot(payload: SlotCreate, store: MemoryStore = Depends(get_store)) -> str:
    try:
        return store.add_slot(payload.slot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[str])
def list_slots(store: MemoryStore = Depends(get_store)) -> list[str]:
    return store.slots
