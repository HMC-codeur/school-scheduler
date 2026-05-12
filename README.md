# School Scheduler MVP

School Scheduler est un MVP de génération automatique d’emplois du temps pour établissements scolaires (écoles, yeshivot, lycées, universités).

## Stack
- **Backend**: Python + FastAPI
- **Frontend**: HTML/CSS/JavaScript vanilla
- **Stockage**: in-memory (MVP)

## Current MVP Features
- Gestion des classes
- Gestion des professeurs
- Gestion des matières
- Gestion des créneaux
- Génération automatique d’emploi du temps
- Vue classe
- Vue professeur
- Chargement de données démo

## Démarrage
### 1) Installer les dépendances
```bash
pip install -r requirements.txt
```

### 2) Lancer le backend
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 3) Ouvrir le frontend
Ouvrir `http://localhost:8000` dans le navigateur.

## Endpoints API
- `POST /classes`, `GET /classes`
- `POST /teachers`, `GET /teachers`
- `POST /subjects`, `GET /subjects`
- `POST /slots`, `GET /slots`
- `POST /schedule/generate`, `GET /schedule`
- `POST /schedule/load-demo`
- (support additionnel existant: `/conditions`, `/time-settings`, `/schedule/clear`, `/schedule/load-large-demo`)

## Limites actuelles MVP
- Pas de persistance (redémarrage = perte des données)
- Pas d’authentification
- Pas d’édition manuelle fine du planning généré
- Pas d’export PDF/Excel

## Next Steps
- Persistance database
- Authentification
- Contraintes avancées (disponibilités détaillées, préférences, salles)
- Édition manuelle du planning
- Export PDF/Excel
- Interface admin multi-école
