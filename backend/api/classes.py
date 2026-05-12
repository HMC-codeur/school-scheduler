from fastapi import APIRouter, HTTPException
from backend.data.memory_store import store
from backend.models.schemas import Class, ClassCreate
router = APIRouter(prefix='/classes', tags=['classes'])
@router.get('', response_model=list[Class])
def list_classes(): return store.classes
@router.post('', response_model=Class)
def create_class(payload:ClassCreate):
    obj=Class(id=store._ids['class'],**payload.model_dump());store._ids['class']+=1;store.classes.append(obj);store.save_data();return obj
@router.delete('/{class_id}')
def delete_class(class_id:int):
    store.classes=[x for x in store.classes if x.id!=class_id];store.subjects=[s.model_copy(update={'target_class_ids':[i for i in s.target_class_ids if i!=class_id]}) for s in store.subjects];store.schedule=[x for x in store.schedule if x.class_id!=class_id];store.save_data();store.save_schedule();return {'message':'Classe supprimée.'}
