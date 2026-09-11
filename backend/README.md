# AutoResearch API

FastAPI control plane for the local, Git-native AutoResearch MVP.

## Run locally

```bash
uv sync --project backend --extra dev --extra postgres
cp backend/.env.example backend/.env
uv run --project backend uvicorn autoresearch_api.main:app --reload --port 8000
```

Prefer PostgreSQL via Docker (`make postgres-up`) and `backend/.env` (see
`.env.example`). The code default is SQLite so tests and smoke runs work
without a local server.
a private GitHub repo via `gh` when available, seeds the math fixture, and
registers a `proj_<slug>` schema name (CREATE SCHEMA on Postgres).

Hypothesis and trial rows are stored with `project_id` for handoff and the DB
explorer. Git remains the branch/tag ledger.

## Evaluator contract

Evaluation commands must print exactly one JSON object to stdout:

```json
{"metrics": {"score": 0.42, "latency_ms": 12.7}}
```

Metric values must be numbers. Eval script nodes reject candidates that modify
configured protected paths before the evaluator runs.

## Checks

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -q backend/tests
```
