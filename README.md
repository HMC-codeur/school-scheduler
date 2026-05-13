# School Scheduler MVP

Application de génération d'emplois du temps scolaires.

## Stack
- **Backend**: FastAPI (Python)
- **Frontend**: HTML/CSS/JavaScript Vanilla
- **Tests**: pytest
- **Store**: mémoire (pas de base SQL pour le MVP)

## Lancer le projet
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```
Puis ouvrir `http://localhost:8000`.

## Exécuter les tests
```bash
pytest -q
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

## Fonctionnalités MVP
- Saisie manuelle des classes, matières, professeurs et créneaux.
- Génération de créneaux à partir des horaires.
- Chargement de jeux de données démo (petit et volumineux).
- Génération d'emploi du temps avec métriques de qualité.
- Filtres d'affichage classe/professeur et recherche.
- Dashboard responsive et messages utilisateurs (succès/erreur/chargement).

## Limites actuelles
- Store en mémoire: les données sont perdues au redémarrage.
- Pas d'authentification.
- Algorithme heuristique: certaines contraintes complexes restent imparfaites.

## Troubleshooting
- Si les tests API sont skippés, vérifier `httpx` dans l'environnement.
- Si la génération échoue: vérifier qu'il y a classes + profs + matières + créneaux, et qu'au moins un professeur couvre chaque matière.
- Si l'UI semble vide après clear: recharger une démo ou ajouter des données avant génération.

## Prochaines étapes
- Persistance (SQLite/PostgreSQL) sans casser l'API.
- Export PDF/CSV des plannings.
- Plus de contraintes pédagogiques et priorisation avancée.
