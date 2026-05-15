from fastapi import APIRouter, Depends, HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import Class, ClassCreate

router = APIRouter(prefix="/classes", tags=["classes"])


@router.post("", response_model=Class)
def create_class(payload: ClassCreate, store: MemoryStore = Depends(get_store)) -> Class:
    try:
        return store.add_class(payload.name, payload.max_lessons_per_day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[Class])
def list_classes(store: MemoryStore = Depends(get_store)) -> list[Class]:
    return store.classes
