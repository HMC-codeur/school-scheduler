# School Scheduler MVP

Application de génération d'emplois du temps scolaires.

## Stack
- **Backend**: FastAPI (Python)
- **Frontend**: HTML/CSS/JavaScript Vanilla
- **Tests**: pytest
- **Store**: mémoire (pas de base SQL pour le MVP)

## Lancer le projet

### Windows PowerShell
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Si la commande `python` pointe vers le lanceur WindowsApps au lieu du venv, utiliser directement :
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### macOS / Linux
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```
Puis ouvrir `http://localhost:8000`.

## Exécuter les tests

### Windows PowerShell
```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall backend
```

### macOS / Linux
```bash
python -m pytest -q
python -m compileall backend
```

## Endpoints principaux
- `GET /classes`, `POST /classes`
- `GET /teachers`, `POST /teachers`
- `GET /subjects`, `POST /subjects`
- `GET /slots`, `POST /slots`
- `GET /conditions`, `POST /conditions`, `DELETE /conditions/{id}`
- `GET /time-settings`, `POST /time-settings`
- `POST /schedule/load-demo`
- `POST /schedule/load-large-demo`
- `POST /schedule/generate`
- `POST /schedule/clear`
- `GET /schedule`
- `GET /schedule/diagnose`
- `GET /schedule/export/csv`
- `GET /schedule/export/pdf`

## Fonctionnalités MVP
- Saisie manuelle des classes, matières, professeurs et créneaux.
- Persistance locale SQLite pour conserver les données entre redémarrages.
- Génération de créneaux à partir des horaires.
- Chargement de jeux de données démo (petit et volumineux).
- Génération d'emploi du temps avec métriques de qualité.
- Diagnostic de génération via `GET /schedule/diagnose`.
- Export du planning sélectionné en CSV et PDF.
- Filtres d'affichage classe/professeur et recherche.
- Dashboard responsive et messages utilisateurs (succès/erreur/chargement).

## Exports
Après génération, le planning sélectionné est exportable :

- `GET /schedule/export/csv` retourne un fichier CSV avec les colonnes `day`, `start_time`, `end_time`, `class`, `teacher`, `subject`.
- `GET /schedule/export/pdf` retourne un PDF simple et lisible.

Si aucun planning n'a encore été généré, ces endpoints retournent `404`.

## Local benchmark
Le scheduler peut être benchmarké localement sans démarrer l'API :

### Windows PowerShell
```powershell
.\.venv\Scripts\python.exe -m backend.benchmarks.scheduler_benchmark --dataset small
.\.venv\Scripts\python.exe -m backend.benchmarks.scheduler_benchmark --dataset medium
.\.venv\Scripts\python.exe -m backend.benchmarks.scheduler_benchmark --all
```

### macOS / Linux
```bash
python -m backend.benchmarks.scheduler_benchmark --dataset small
python -m backend.benchmarks.scheduler_benchmark --dataset medium
python -m backend.benchmarks.scheduler_benchmark --all
```

Le rapport JSON est écrit par défaut ici :

```text
backend/benchmarks/results/scheduler_benchmark_latest.json
```

Le rapport inclut les temps de génération/options/scoring, les sessions placées, les scores min/max/moyens, la mémoire peak et les principales catégories de pénalités (`top_penalty_categories`).

Datasets disponibles :
- `small`: 10 classes, 20 professeurs, 10 matières.
- `medium`: 50 classes, 90 professeurs, 20 matières.
- `large`: 100 classes, 200 professeurs, 40 matières.
- `xlarge`: 250 classes, 500 professeurs, 60 matières.

Chaque dataset garde une marge de créneaux volontaire afin d'éviter que le benchmark standard mesure surtout un cas de backtracking extrêmement serré.

Les seuils de performance sont informatifs par défaut. Pour rendre un dépassement bloquant :

```powershell
.\.venv\Scripts\python.exe -m backend.benchmarks.scheduler_benchmark --dataset small --enforce-thresholds
```

Les seuils sont ajustables sans modifier le code :

```powershell
.\.venv\Scripts\python.exe -m backend.benchmarks.scheduler_benchmark --dataset small --small-threshold-ms 30000
```

## Persistance locale
Le MVP utilise SQLite par défaut via une couche repository (`backend/data/repository.py` et `backend/data/sqlite_repository.py`).
La base locale est créée automatiquement ici :

```text
backend/data/school_scheduler.sqlite3
```

Pour utiliser un autre fichier, définir `SCHOOL_SCHEDULER_DB_PATH`.

### Windows PowerShell
```powershell
$env:SCHOOL_SCHEDULER_DB_PATH="C:\temp\school-scheduler.sqlite3"
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### macOS / Linux
```bash
export SCHOOL_SCHEDULER_DB_PATH=/tmp/school-scheduler.sqlite3
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

`memory_store.py` reste dans le projet comme fallback/compatibilité pendant la transition. Supabase/PostgreSQL n'est pas encore connecté: la couche repository est là pour préparer cette migration sans casser les endpoints.

## Limites actuelles
- SQLite local mono-école: pas encore de multi-tenant ni de synchronisation cloud.
- Pas d'authentification.
- Algorithme heuristique: certaines contraintes complexes restent imparfaites.

## Troubleshooting
- Si les tests API sont skippés, vérifier `httpx` dans l'environnement.
- Si la génération échoue: vérifier qu'il y a classes + profs + matières + créneaux, et qu'au moins un professeur couvre chaque matière.
- Pour comprendre un échec, appeler `GET /schedule/diagnose`.
- Si l'UI semble vide après clear: recharger une démo ou ajouter des données avant génération.

## Prochaines étapes
- Persistance (SQLite/PostgreSQL) sans casser l'API.
- Export PDF/CSV des plannings.
- Plus de contraintes pédagogiques et priorisation avancée.
