# AutoResearch API

FastAPI control plane for the local, Git-native AutoResearch MVP.

## Run locally

```bash
uv sync --project backend --extra dev --extra postgres
cp backend/.env.example backend/.env
uv run --project backend uvicorn autoresearch_api.main:app --reload --port 8000
```

The default database is a persistent SQLite file. Set
`AUTORESEARCH_DATABASE_URL` to the PostgreSQL URL from `.env.example` for the
production-shaped local setup.

The configured project repository must be trusted: MVP commands run directly
inside Git worktrees. Podman isolation is intentionally deferred.

## Evaluator contract

Evaluation commands must print exactly one JSON object to stdout:

```json
{"metrics": {"score": 0.42, "latency_ms": 12.7}}
```

Metric values must be numbers. Evaluation nodes reject candidates that modify
configured protected paths before the evaluator is executed.

## Checks

```bash
uv run --project backend ruff check backend/src backend/tests
uv run --project backend pytest -q backend/tests
```
