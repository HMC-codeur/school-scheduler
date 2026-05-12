from fastapi import APIRouter
from backend.data.memory_store import store
from backend.models.schemas import Subject, SubjectCreate
router = APIRouter(prefix='/subjects', tags=['subjects'])
@router.get('', response_model=list[Subject])
def list_subjects(): return store.subjects
@router.post('', response_model=Subject)
def create_subject(payload:SubjectCreate):
    obj=Subject(id=store._ids['subject'],**payload.model_dump());store._ids['subject']+=1;store.subjects.append(obj);store.save_data();return obj
@router.delete('/{subject_id}')
def delete_subject(subject_id:int):
    store.subjects=[x for x in store.subjects if x.id!=subject_id];store.schedule=[x for x in store.schedule if x.subject_id!=subject_id];store.save_data();store.save_schedule();return {'message':'Matière supprimée.'}
