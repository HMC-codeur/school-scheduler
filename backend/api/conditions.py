from fastapi import APIRouter, Depends, HTTPException


from backend.data.store import get_store
from backend.data.memory_store import MemoryStore
from backend.models.schemas import Condition, ConditionCreate

router = APIRouter(prefix="/conditions", tags=["conditions"])
constraints_router = APIRouter(prefix="/constraints", tags=["conditions"])


@router.post("", response_model=Condition)
@constraints_router.post("", response_model=Condition)
def create_condition(payload: ConditionCreate, store: MemoryStore = Depends(get_store)) -> Condition:
    return store.add_condition(payload)


@router.get("", response_model=list[Condition])
@constraints_router.get("", response_model=list[Condition])
def list_conditions(store: MemoryStore = Depends(get_store)) -> list[Condition]:
    return store.conditions


@router.delete("/{condition_id}", response_model=dict)
@constraints_router.delete("/{condition_id}", response_model=dict)
def delete_condition(condition_id: int, store: MemoryStore = Depends(get_store)) -> dict:
    deleted = store.delete_condition(condition_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Condition not found")
    return {"message": "Condition deleted."}
