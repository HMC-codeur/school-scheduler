# School Scheduler V1 MVP

Vision: générer et éditer un emploi du temps scolaire localement, avec contraintes réelles, persistance JSON et export CSV.

## Stack
- Backend: FastAPI (Python)
- Frontend: HTML/CSS/JS Vanilla
- Stockage: fichiers JSON (`backend/data/*.json`)

## Fonctionnalités MVP
- CRUD classes/professeurs/matières/créneaux
- Génération automatique avec contraintes
- Édition manuelle d'une session
- Validation planning
- Export CSV
- Reset global

## Lancement
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```
Puis ouvrir `http://127.0.0.1:8000`.

## Endpoints principaux
- `POST /classes`, `GET /classes`, `DELETE /classes/{id}`
- `POST /teachers`, `GET /teachers`, `DELETE /teachers/{id}`
- `POST /subjects`, `GET /subjects`, `DELETE /subjects/{id}`
- `POST /slots`, `GET /slots`, `DELETE /slots/{id}`
- `POST /schedule/load-demo`
- `POST /schedule/generate`
- `GET /schedule`, `DELETE /schedule`
- `PUT /schedule/session/{session_id}`
- `GET /schedule/validate`
- `GET /schedule/export/csv`
- `POST /reset`

## Tests
```bash
pytest -q
```

## Roadmap
Phase 1: MVP local JSON + génération + édition + CSV.
Phase 2: DB réelle + auth + multi-école + rôles + exports avancés.
Phase 3: SaaS + IA d'assistance + optimisation + cloud.
