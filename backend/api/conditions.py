from fastapi import APIRouter, HTTPException

from backend.data.memory_store import store
from backend.models.schemas import Condition, ConditionCreate

router = APIRouter(prefix="/conditions", tags=["conditions"])


@router.post("", response_model=Condition)
def create_condition(payload: ConditionCreate) -> Condition:
    return store.add_condition(payload)


@router.get("", response_model=list[Condition])
def list_conditions() -> list[Condition]:
    return store.conditions


@router.delete("/{condition_id}", response_model=dict)
def delete_condition(condition_id: int) -> dict:
    deleted = store.delete_condition(condition_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Condition not found")
    return {"message": "Condition deleted."}
