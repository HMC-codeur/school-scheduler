from fastapi import APIRouter, Depends, HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import Subject, SubjectCreate

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("", response_model=Subject)
def create_subject(payload: SubjectCreate, store: MemoryStore = Depends(get_store)) -> Subject:
    try:
        return store.add_subject(payload.name, payload.hours_per_week)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[Subject])
def list_subjects(store: MemoryStore = Depends(get_store)) -> list[Subject]:
    return store.subjects
