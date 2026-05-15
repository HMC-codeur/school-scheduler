from fastapi import APIRouter, Depends, HTTPException

from backend.data.memory_store import MemoryStore
from backend.data.store import get_store
from backend.models.schemas import LearningGroup, LearningGroupCreate


router = APIRouter(prefix="/learning-groups", tags=["learning-groups"])


@router.get("", response_model=list[LearningGroup])
def list_learning_groups(store: MemoryStore = Depends(get_store)) -> list[LearningGroup]:
    return store.learning_groups


@router.post("", response_model=LearningGroup)
def create_learning_group(payload: LearningGroupCreate, store: MemoryStore = Depends(get_store)) -> LearningGroup:
    try:
        return store.add_learning_group(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{group_id}", response_model=dict)
def delete_learning_group(group_id: int, store: MemoryStore = Depends(get_store)) -> dict:
    if not store.delete_learning_group(group_id):
        raise HTTPException(status_code=404, detail="Learning group not found")
    return {"message": "Learning group deleted."}
