from fastapi import APIRouter
from backend.data.memory_store import store
from backend.models.schemas import Slot, SlotCreate
router = APIRouter(prefix='/slots', tags=['slots'])
@router.get('', response_model=list[Slot])
def list_slots(): return store.slots
@router.post('', response_model=Slot)
def create_slot(payload:SlotCreate):
    obj=Slot(id=store._ids['slot'],**payload.model_dump());store._ids['slot']+=1;store.slots.append(obj);store.save_data();return obj
@router.delete('/{slot_id}')
def delete_slot(slot_id:int):
    store.slots=[x for x in store.slots if x.id!=slot_id];store.schedule=[x for x in store.schedule if x.slot_id!=slot_id];store.save_data();store.save_schedule();return {'message':'Créneau supprimé.'}
