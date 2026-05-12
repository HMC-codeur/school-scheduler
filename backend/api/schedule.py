import csv, io
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.data.memory_store import store
from backend.models.schemas import GenerateScheduleResponse, ScheduleSession, ScheduleUpdate
from backend.services.scheduler import SchedulerService

router = APIRouter(prefix="/schedule", tags=["schedule"])

@router.post("/generate", response_model=GenerateScheduleResponse)
def generate_schedule() -> GenerateScheduleResponse:
    result = SchedulerService.generate(store.classes, store.teachers, store.subjects, store.slots)
    if result.success:
        store.schedule = result.schedule
        store.save_schedule()
    return GenerateScheduleResponse(**result.__dict__)

@router.get("", response_model=list[ScheduleSession])
def get_schedule(): return store.schedule

@router.delete("")
def delete_schedule():
    store.schedule=[];store.save_schedule();return {"message":"Planning supprimé."}

@router.put("/session/{session_id}")
def update_session(session_id:int,payload:ScheduleUpdate):
    s=next((x for x in store.schedule if x.session_id==session_id),None)
    if not s: raise HTTPException(404,"Session introuvable")
    for name,col in [("class",store.classes),("teacher",store.teachers),("subject",store.subjects),("slot",store.slots)]:
        if not any(getattr(x,'id')==getattr(payload,f'{name}_id') for x in col): raise HTTPException(400,f"ID {name} invalide")
    teacher=next(t for t in store.teachers if t.id==payload.teacher_id)
    if payload.slot_id in teacher.unavailable_slot_ids: raise HTTPException(400,"Conflit : ce professeur est indisponible à ce créneau.")
    for other in store.schedule:
        if other.session_id==session_id: continue
        if other.class_id==payload.class_id and other.slot_id==payload.slot_id: raise HTTPException(400,"Conflit : cette classe a déjà un cours à ce créneau.")
        if other.teacher_id==payload.teacher_id and other.slot_id==payload.slot_id: raise HTTPException(400,"Conflit : ce professeur enseigne déjà à ce créneau.")
    s.class_id=payload.class_id;s.teacher_id=payload.teacher_id;s.subject_id=payload.subject_id;s.slot_id=payload.slot_id
    store.save_schedule();return {"message":"Session mise à jour."}

@router.get('/validate')
def validate_schedule():
    issues=[]
    for i,a in enumerate(store.schedule):
        for b in store.schedule[i+1:]:
            if a.class_id==b.class_id and a.slot_id==b.slot_id: issues.append('Conflit classe')
            if a.teacher_id==b.teacher_id and a.slot_id==b.slot_id: issues.append('Conflit professeur')
    return {"valid":len(issues)==0,"issues":issues}

@router.get('/export/csv')
def export_csv():
    out=io.StringIO();w=csv.writer(out);w.writerow(["créneau","classe","matière","professeur"])
    c={x.id:x.name for x in store.classes};t={x.id:x.name for x in store.teachers};s={x.id:x.name for x in store.subjects};sl={x.id:x.label for x in store.slots}
    for row in store.schedule:w.writerow([sl.get(row.slot_id,row.slot_id),c.get(row.class_id,row.class_id),s.get(row.subject_id,row.subject_id),t.get(row.teacher_id,row.teacher_id)])
    return StreamingResponse(iter([out.getvalue()]), media_type='text/csv', headers={"Content-Disposition":"attachment; filename=schedule.csv"})
