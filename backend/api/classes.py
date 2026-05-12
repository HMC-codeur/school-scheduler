from fastapi import APIRouter

from backend.data.memory_store import store
from backend.models.schemas import Class, ClassCreate

router = APIRouter(prefix="/classes", tags=["classes"])


@router.post("", response_model=Class)
def create_class(payload: ClassCreate) -> Class:
    return store.add_class(payload.name, payload.max_lessons_per_day)


@router.get("", response_model=list[Class])
def list_classes() -> list[Class]:
    return store.classes
