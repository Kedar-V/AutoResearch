# AutoResearch

AutoResearch is a local, Git-native MVP for executable research workflows. A React Flow whiteboard connects Hypothesis, Execution, Eval script, Evaluation agent, Metric gate, Git decision, optional Script allow-lists, and a DB viewer. Trials are not palette nodes: Hypothesis owns inner retries; Git decision feeds the outer hypothesis loop.

The FastAPI control plane saves workflows in SQL, tracks projects/hypotheses/trials for handoff, and runs trusted local scripts in Git worktrees. An improving candidate is committed on a trial branch, evaluated by a protected script, gated, then accepted (merged to champion) or rejected. Rejected and failed trials keep their branches, tags, and Git notes.

## Architecture

React Flow frontend, FastAPI/SQLAlchemy control plane, trusted local runner, native Git CLI/worktrees, and contract schemas. PostgreSQL is the preferred system of record (one project registry row plus `project_id`-scoped hypothesis/trial/chat tables; `CREATE SCHEMA` per project when on Postgres). SQLite remains available for tests and zero-setup smoke runs. See [High-Level Design](docs/HIGH_LEVEL_DESIGN.md).

Git remains authoritative for source, lineage, notes, tags, and promotion history. SQL is the queryable runtime projection and session handoff layer.

## Agent observability (optional Langfuse)

AutoResearch records agent explainability (full prompts + generations + heuristic scores) through a swappable `AgentObservability` port. The default backend is `noop`, so the research loop works with zero Langfuse setup.

**Choose a mode** via `AUTORESEARCH_OBSERVABILITY_BACKEND`:

| Value | Meaning |
|---|---|
| `noop` | Off (default) |
| `langfuse-cloud` | Langfuse Cloud (Free or Pro) |
| `langfuse-selfhost` | Local OSS stack (`make langfuse-selfhost-up`) |
| `langfuse` | Generic — use whatever `LANGFUSE_HOST` + keys you set |

### Cloud

```sh
AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-cloud
AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-...
AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-...
AUTORESEARCH_LANGFUSE_HOST=https://cloud.langfuse.com
```

### Self-host (OSS)

```sh
make langfuse-selfhost-up
# UI http://localhost:3000 — admin@autoresearch.local / changeme-langfuse-admin
```

Then in `backend/.env`:

```sh
AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost
AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-autoresearch-local
AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-autoresearch-local-dev-secret
AUTORESEARCH_LANGFUSE_HOST=http://localhost:3000
```

Details: [`ops/langfuse/README.md`](ops/langfuse/README.md). Stop with `make langfuse-selfhost-down`.

Install the SDK with `make backend-install` (includes the `observability` extra). Agents never import Langfuse directly; only `observability/langfuse_adapter.py` does. Evaluation Git notes store vendor-neutral `agent_trace_id` / `prompt_version` / `observability_backend` so you can swap vendors later.

Langfuse dashboards cover LLM cost/latency/scores — not champion `val_bpb` staircases (those stay in the AutoResearch UI).

**Costs:** generations include real token `usage` from OpenAI and Cursor (`RunResult.usage` / `get_usage`). Cursor dollar cost is passed when the SDK reports it; OpenAI cost is computed by Langfuse from model + tokens (no invented numbers). If a provider omits usage, cost stays empty rather than estimated.

## Loop model

```text
Hypothesis → Execution ⇄ (self-heal trials)
           → Evaluation agent ← Eval script
           → Metric gate → Git decision → Hypothesis (outer feedback)
```

- Gate green: accept, merge into `master`, next hypothesis from the new champion.
- Gate red: reject, leave `master` unchanged, next hypothesis from last stable champion.
- Click Hypothesis for the agent → hypo → trial slide-over; click DB for a project table explorer.

## Prerequisites

- Python 3.11 or newer and `uv`
- Node.js 20 or newer and npm
- Git configured with a user name and email in every target repository
- Optional: Docker (Postgres + optional Langfuse), `gh` (for New Project → private GitHub repo)

## Installation And Running

```sh
make backend-install
make frontend-install
make postgres-up          # Docker Postgres on localhost:5432
# ensure backend/.env has AUTORESEARCH_DATABASE_URL=postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch
make backend-dev
make frontend-dev
```

API: `http://localhost:8000`. Canvas: `http://localhost:5173`.

## Target Configuration

```sh
# Preferred SoR — Docker Postgres (make postgres-up):
export AUTORESEARCH_DATABASE_URL='postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch'
# Unit tests / zero-setup fallback only:
# export AUTORESEARCH_DATABASE_URL='sqlite:///./autoresearch.db'
export AUTORESEARCH_PROJECT_ROOT="$PWD/examples/basic-research"
export AUTORESEARCH_RUNTIME_ROOT="$PWD/.autoresearch"
export AUTORESEARCH_CHAMPION_BRANCH='master'
export AUTORESEARCH_ALLOWED_ORIGINS='http://localhost:5173'
export AUTORESEARCH_SCRIPT_TIMEOUT_SECONDS='300'
export AUTORESEARCH_PROTECTED_PATHS='eval.py,tests,.research'
```

Install the Postgres driver with `make backend-install` (includes the `postgres` extra). Start the DB with `make postgres-up` (`ops/postgres/`). The process default remains SQLite when `AUTORESEARCH_DATABASE_URL` is unset (tests/smoke only). Langfuse’s Postgres (if used) is on **5434**, not 5432.

## Example

[`examples/basic-research`](examples/basic-research) starts `score.txt` at `5.0`. Each accepted hypothesis decrements the score by one via `train.py` until `0.0` across five hypotheses. The evaluator prints `{"metrics": {"score": <number>}}`.

## Testing

```sh
make contracts
make test
make check
```

## Deferred Features

Hermes automation, Podman isolation, Temporal orchestration, distributed workers, MCP tool execution, parallel scheduling, and autonomous repair loops are deferred. The MVP runner is for trusted local scripts only. Agent observability via Langfuse (Cloud or optional self-host OSS) is available as a swappable backend (default off).

## License

No project license has been selected yet. Until a license file is added, the repository is source-visible but should not be assumed to grant open-source usage rights.
