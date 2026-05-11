from fastapi import APIRouter

from backend.data.memory_store import store
from backend.models.schemas import Teacher, TeacherCreate

router = APIRouter(prefix="/teachers", tags=["teachers"])


@router.post("", response_model=Teacher)
def create_teacher(payload: TeacherCreate) -> Teacher:
    return store.add_teacher(payload.name, payload.subjects)


@router.get("", response_model=list[Teacher])
def list_teachers() -> list[Teacher]:
    return store.teachers
