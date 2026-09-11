# AutoResearch API

FastAPI control plane for the local, Git-native AutoResearch MVP.

## Run locally

```bash
uv sync --project backend --extra dev --extra postgres --extra observability
# Optional memory SDK:
# uv sync --project backend --extra memory
cp backend/.env.example backend/.env
set -a; source backend/.env; set +a
uv run --project backend uvicorn autoresearch_api.main:app --reload --reload-dir backend --port 8000
```

Prefer PostgreSQL via Docker (`make postgres-up`) and `backend/.env` (see
`.env.example`). The code default is SQLite so tests and smoke runs work
without a local server.

**New Project** creates a private GitHub repo via `gh` when available, seeds the
math fixture, and registers a `proj_<slug>` schema name (`CREATE SCHEMA` on
Postgres). Hypothesis and trial rows are stored with `project_id` for handoff
and the DB explorer (ORM tables remain in `public`). Git remains the
branch/tag/notes ledger.

**Restart** (`POST /api/projects/{id}/restart`) wipes experiment refs and
project ledger rows, keeps the champion tip, and starts a fresh run.

Workflows must compile as a **research recipe** (`compile_recipe` in
`workflow.py`). Invalid graphs return HTTP **422** on save, create-run, and
restart. See HLD §6 and `frontend/src/recipe.ts`.

## Evaluator contract

Evaluation commands must print exactly one JSON object to stdout:

```json
{"metrics": {"score": 0.42}}
```

Metric values must be numbers. Additional metric keys are allowed for logging
and the evaluation agent. The **metric_gate** defaults to a single `metric` +
`direction` + `min_delta` (scalar). Set `policy: "pareto"` with `objectives[]`
for ε-frontier KEEP/DISCARD without auto-merge. Eval script nodes reject
candidates that modify configured protected paths before the evaluator runs.

## Ports

- `observability/` — Langfuse / noop (agents never import the vendor SDK)
- `memory/` — Honcho / Hindsight / composite / noop (prefs only; not research SoR)

## Checks

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -q backend/tests
```
