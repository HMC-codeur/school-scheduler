# Solver architecture

## Decision: no PostgreSQL for this step

This step deliberately does not add PostgreSQL or any new database layer. The priority is to stabilize the scheduling brain first: inputs, solver contract, output format, metrics, tests, and benchmarks. A stronger persistence model should come after the business model and solver behavior are stable enough to avoid storing the wrong abstractions.

The repository may already contain simple persistence code for current app state. This architecture does not expand it and does not require a migration.

## Why isolate the solver

The scheduler is now prepared for multiple engines through `backend/services/solver/`:

- `models.py`: small internal DTOs for solver input, result, assignments, and metrics.
- `base.py`: `ScheduleSolver` interface.
- `legacy_solver_adapter.py`: wrapper around the existing `SchedulerService`.
- `ortools_solver.py`: experimental Google OR-Tools CP-SAT solver.

The public schedule format stays compatible with the existing frontend and API:

```json
{
  "Mon-08:00": {
    "Grade 7A": {
      "subject": "Math",
      "teacher": "Mr. Khan"
    }
  }
}
```

## Legacy vs OR-Tools

The legacy solver remains the default engine. `POST /schedule/generate` still uses the existing option-generation flow and keeps returning the same response shape.

The OR-Tools solver is experimental and must be explicitly selected:

```powershell
curl -X POST "http://localhost:8000/schedule/generate?engine=ortools"
```

OR-Tools V1 handles only basic hard constraints:

- one class cannot have two lessons in the same slot;
- one teacher cannot teach two classes in the same slot;
- teachers must be compatible with the assigned subject;
- every required class/subject session is placed exactly once;
- teacher and class slot conflicts are forbidden;
- existing teacher and class unavailability conditions are respected;
- existing daily max lesson limits are respected.

It does not yet optimize timetable comfort, gaps, repeated subjects, fairness, preferences, or long sequences. Its current goal is a valid conflict-free baseline that can be benchmarked.

## Tests

Install dependencies:

```powershell
.\.venv\Scripts\python -X utf8 -m pip install -r requirements.txt
```

Run all tests:

```powershell
.\.venv\Scripts\python -X utf8 -m pytest
```

If Windows denies access to the default pytest temp directory, run with temp paths inside the workspace:

```powershell
$env:TMP="$PWD\.tmp"; $env:TEMP="$PWD\.tmp"; .\.venv\Scripts\python -X utf8 -m pytest
```

Run only solver/API tests:

```powershell
.\.venv\Scripts\python -X utf8 -m pytest tests\test_ortools_solver.py tests\test_api_endpoints.py
```

## Benchmarks

The existing scheduler benchmark is unchanged:

```powershell
.\.venv\Scripts\python -X utf8 -m backend.benchmarks.scheduler_benchmark --dataset small
```

The new solver comparison benchmark compares legacy and OR-Tools:

```powershell
.\.venv\Scripts\python -X utf8 -m backend.benchmarks.solver_benchmark --dataset small
```

Run all configured datasets:

```powershell
.\.venv\Scripts\python -X utf8 -m backend.benchmarks.solver_benchmark --all
```

JSON output is written by default to:

```text
backend/benchmarks/results/solver_benchmark_latest.json
```

## Known V1 limits

- OR-Tools currently returns one valid schedule, not multiple ranked options.
- The OR-Tools score is intentionally simple: sessions placed, hard conflicts, success/failure, and generation time.
- Soft constraints and quality optimization are still owned by the legacy solver/scoring path.
- The frontend is unchanged; OR-Tools is available through the API parameter only.
- No database schema was added or changed for this work.

## Recommended next step

After validating OR-Tools on real school-sized datasets, add soft objectives incrementally: minimize gaps, spread repeated subjects across days, balance teacher load, and then compare solver quality against legacy through the benchmark report before introducing any persistence changes.
