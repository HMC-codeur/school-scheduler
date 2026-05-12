from fastapi import APIRouter
from backend.data.memory_store import store
router = APIRouter(tags=['admin'])
@router.post('/reset')
def reset_all():
    store.reset_data();return {'message':'Application réinitialisée.'}

@router.post('/schedule/load-demo')
def load_demo():
    store.reset_data()
    c1=store.classes.append(__import__('backend.models.schemas',fromlist=['Class']).Class(id=1,name='6A',max_lessons_per_day=6))
    store.classes.append(__import__('backend.models.schemas',fromlist=['Class']).Class(id=2,name='6B',max_lessons_per_day=6))
    store._ids['class']=3
    store.slots=[__import__('backend.models.schemas',fromlist=['Slot']).Slot(id=i+1,label=s) for i,s in enumerate(['Mon-08:00','Mon-09:00','Tue-08:00','Tue-09:00'])]
    store._ids['slot']=5
    store.teachers=[__import__('backend.models.schemas',fromlist=['Teacher']).Teacher(id=1,name='Mme Cohen',subject_ids=[1],unavailable_slot_ids=[2],max_lessons_per_day=6),__import__('backend.models.schemas',fromlist=['Teacher']).Teacher(id=2,name='M. Levy',subject_ids=[2],unavailable_slot_ids=[],max_lessons_per_day=6)]
    store._ids['teacher']=3
    store.subjects=[__import__('backend.models.schemas',fromlist=['Subject']).Subject(id=1,name='Math',weekly_hours=2,allowed_teacher_ids=[1],target_class_ids=[1,2]),__import__('backend.models.schemas',fromlist=['Subject']).Subject(id=2,name='Français',weekly_hours=1,allowed_teacher_ids=[2],target_class_ids=[1,2])]
    store._ids['subject']=3
    store.save_data();store.save_schedule();return {'message':'Demo data loaded.'}
