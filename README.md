# School Scheduler (FastAPI + Vanilla JS)

Application MVP pour créer des données scolaires (classes, professeurs, matières, créneaux), définir des conditions, générer un emploi du temps, visualiser le planning et les métriques qualité.

## Démarrage rapide

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

- UI: http://127.0.0.1:8000/
- Swagger: http://127.0.0.1:8000/docs

## Variables d'environnement

- `CORS_ALLOW_ORIGINS`: liste CSV d'origines autorisées (ex: `http://localhost,http://127.0.0.1`).
- `CORS_ALLOW_CREDENTIALS`: booléen (`true/false`).

⚠️ Sécurité: la combinaison `CORS_ALLOW_ORIGINS=*` et `CORS_ALLOW_CREDENTIALS=true` est refusée au démarrage.

## Endpoints API

- Classes: `POST /classes`, `GET /classes`
- Professeurs: `POST /teachers`, `GET /teachers`
- Matières: `POST /subjects`, `GET /subjects`
- Créneaux: `POST /slots`, `GET /slots`
- Conditions: `POST /conditions`, `GET /conditions`, `DELETE /conditions/{condition_id}`
- Paramètres horaires: `GET /time-settings`, `POST /time-settings`
- Planning: `POST /schedule/generate`, `GET /schedule`
- Données de démo: `POST /schedule/load-demo`, `POST /schedule/load-large-demo`, `POST /schedule/clear`

## Qualité / tests

```bash
pytest
python -m compileall backend
```

## Limitations connues

- Store en mémoire (`MemoryStore`): les données sont perdues au redémarrage.
- Instance unique: pas de partage d'état distribué.
- Pas d'authentification/autorisation (MVP).

## Troubleshooting

- **Erreur CORS au boot**: vérifier les variables `CORS_ALLOW_ORIGINS` et `CORS_ALLOW_CREDENTIALS`.
- **422 sur création d'entités**: vérifier les champs obligatoires (noms non vides, heures > 0, formats horaires valides).
- **Génération impossible**: réduire les contraintes ou augmenter les créneaux.
