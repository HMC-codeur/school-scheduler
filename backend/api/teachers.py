from fastapi import APIRouter, Depends, HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import Teacher, TeacherCreate

router = APIRouter(prefix="/teachers", tags=["teachers"])


@router.post("", response_model=Teacher)
def create_teacher(payload: TeacherCreate, store: MemoryStore = Depends(get_store)) -> Teacher:
    try:
        return store.add_teacher(
            payload.name,
            payload.subjects,
            payload.unavailable_slots,
            payload.max_lessons_per_day,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[Teacher])
def list_teachers(store: MemoryStore = Depends(get_store)) -> list[Teacher]:
    return store.teachers
