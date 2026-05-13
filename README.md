# AI School Timetable Generator (MVP)

Production-style SaaS MVP using FastAPI + Vanilla JS that builds conflict-free school timetables with a backtracking CSP scheduler.

## Folder Structure

```text
backend/
  main.py
  api/
    classes.py
    teachers.py
    subjects.py
    slots.py
    schedule.py
  models/
    schemas.py
  services/
    scheduler.py
  data/
    memory_store.py
frontend/
  index.html
  style.css
  app.js
```

## Features

- In-memory storage for classes, teachers, subjects, and timeslots
- REST API for CRUD-style creation/listing and schedule generation
- Constraint-based scheduler with recursive backtracking
- Frontend dashboard for data entry and schedule visualization

## Scheduling Constraints Enforced

1. Teacher cannot teach multiple classes in the same slot
2. A class cannot have multiple subjects in the same slot
3. Subject weekly hours are exactly allocated per class
4. Invalid combinations are rejected during assignment
5. If no complete solution exists, API returns `no valid schedule found`

## Run Locally

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic
```

### 2) Start server

```bash
uvicorn backend.main:app --reload
```

### 3) Open app

- Dashboard: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

## API Endpoints

- `POST /classes`, `GET /classes`
- `POST /teachers`, `GET /teachers`
- `POST /subjects`, `GET /subjects`
- `POST /slots`, `GET /slots`
- `POST /schedule/generate`
- `GET /schedule`
