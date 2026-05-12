from fastapi import APIRouter
from backend.data.memory_store import store
from backend.models.schemas import Teacher, TeacherCreate
router = APIRouter(prefix='/teachers', tags=['teachers'])
@router.get('', response_model=list[Teacher])
def list_teachers(): return store.teachers
@router.post('', response_model=Teacher)
def create_teacher(payload:TeacherCreate):
    obj=Teacher(id=store._ids['teacher'],**payload.model_dump());store._ids['teacher']+=1;store.teachers.append(obj);store.save_data();return obj
@router.delete('/{teacher_id}')
def delete_teacher(teacher_id:int):
    store.teachers=[x for x in store.teachers if x.id!=teacher_id];store.subjects=[s.model_copy(update={'allowed_teacher_ids':[i for i in s.allowed_teacher_ids if i!=teacher_id]}) for s in store.subjects];store.schedule=[x for x in store.schedule if x.teacher_id!=teacher_id];store.save_data();store.save_schedule();return {'message':'Professeur supprimé.'}
