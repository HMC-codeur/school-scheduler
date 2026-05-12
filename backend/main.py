from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.classes import router as classes_router
from backend.api.conditions import router as conditions_router
from backend.api.schedule import router as schedule_router
from backend.api.slots import router as slots_router
from backend.api.subjects import router as subjects_router
from backend.api.teachers import router as teachers_router

app = FastAPI(title="AI School Timetable Generator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(classes_router)
app.include_router(conditions_router)
app.include_router(teachers_router)
app.include_router(subjects_router)
app.include_router(slots_router)
app.include_router(schedule_router)

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
