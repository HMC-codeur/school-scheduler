from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from pathlib import Path

from backend.api.classes import router as classes_router
from backend.api.conditions import router as conditions_router
from backend.api.imports import router as imports_router
from backend.api.learning_groups import router as learning_groups_router
from backend.api.schedule import router as schedule_router
from backend.api.slots import router as slots_router
from backend.api.subjects import router as subjects_router
from backend.api.teachers import router as teachers_router
from backend.api.time_settings import router as time_settings_router
from backend.api.platform import router as platform_router
from backend.config import get_settings

app = FastAPI(title="AI School Timetable Generator", version="0.1.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=settings.cors_expose_headers,
)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def pydantic_validation_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "Validation error", "errors": exc.errors()})


app.include_router(classes_router)
app.include_router(conditions_router)
app.include_router(imports_router)
app.include_router(learning_groups_router)
app.include_router(teachers_router)
app.include_router(subjects_router)
app.include_router(slots_router)
app.include_router(schedule_router)
app.include_router(time_settings_router)
app.include_router(platform_router)

ROOT_DIR = Path(__file__).resolve().parent.parent
REACT_FRONTEND_DIR = ROOT_DIR / "frontend-react" / "dist"
LEGACY_FRONTEND_DIR = ROOT_DIR / "frontend"

FRONTEND_DIR = REACT_FRONTEND_DIR if REACT_FRONTEND_DIR.exists() else LEGACY_FRONTEND_DIR


@app.get("/import-excel", include_in_schema=False)
def import_excel_spa() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
