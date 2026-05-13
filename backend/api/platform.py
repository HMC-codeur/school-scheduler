from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from backend.data.memory_store import MemoryStore
from backend.data.store import get_store

router = APIRouter(tags=["platform"])


@router.get('/health')
def health() -> dict:
    return {"status": "ok"}


@router.get('/stats')
def stats(store: MemoryStore = Depends(get_store)) -> dict:
    return {
        "classes": len(store.classes),
        "teachers": len(store.teachers),
        "subjects": len(store.subjects),
        "slots": len(store.slots),
        "constraints": len(store.conditions),
        "has_schedule": bool(store.schedule),
    }


@router.get('/constraints')
def list_constraints(store: MemoryStore = Depends(get_store)) -> list:
    return store.conditions


@router.post('/constraints')
def create_constraint(payload: dict, store: MemoryStore = Depends(get_store)) -> dict:
    # Alias léger vers /conditions pour compatibilité historique
    from backend.models.schemas import ConditionCreate
    condition = store.add_condition(ConditionCreate(**payload))
    return condition.model_dump()


@router.delete('/constraints/{constraint_id}')
def delete_constraint(constraint_id: int, store: MemoryStore = Depends(get_store)) -> dict:
    if not store.delete_condition(constraint_id):
        raise HTTPException(status_code=404, detail='Constraint not found')
    return {"message": "Constraint deleted."}


@router.get('/schedule/options')
def schedule_options(store: MemoryStore = Depends(get_store)) -> list[dict]:
    selected_option_id = store.selected_schedule_option_id
    return [
        {
            **option,
            "selected": option.get("id") == selected_option_id,
        }
        for option in store.schedule_options
    ]


@router.get('/schedule/export/json')
def export_schedule_json(store: MemoryStore = Depends(get_store)) -> dict:
    return {"schedule": store.schedule, "options": store.schedule_options}


@router.get('/schedule/export/csv', response_class=PlainTextResponse)
def export_schedule_csv(store: MemoryStore = Depends(get_store)) -> str:
    lines = ['slot,class,subject,teacher']
    for slot, entries in store.schedule.items():
        for class_name, cell in entries.items():
            lines.append(f'{slot},{class_name},{cell.subject},{cell.teacher}')
    return '\n'.join(lines)
