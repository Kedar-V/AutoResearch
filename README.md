# AutoResearch

AutoResearch is a local, Git-native MVP for executable research workflows. The React Flow canvas is a **locked research recipe** (not a freeform DAG palette): exactly one Hypothesis, Execution, Eval script, Evaluation agent, Metric gate, and Git decision, plus an optional DB viewer. Trials are not canvas nodes — Hypothesis owns inner retries; Git decision feeds the outer hypothesis loop.

The FastAPI control plane saves workflows in SQL, tracks projects/hypotheses/trials for handoff, and runs trusted local scripts in Git worktrees. Optional Cursor/OpenAI agents plan hypotheses, edit allow-listed files, and judge evaluations. An improving candidate is committed on a trial branch, evaluated by a protected script, gated, then accepted (merged to champion) or rejected. Rejected and failed trials keep their branches, tags, and Git notes.

## Architecture

React Flow frontend (`:5173`), FastAPI control plane with an **in-process** executor (`:8000`), trusted `LocalRunner`, native Git CLI/worktrees, and contract schemas. Workflows are validated by a shared **recipe compiler** (`compile_recipe` / `compileRecipe` → `CompiledLoop`) on save, run, and project restart (HTTP 422 if invalid). PostgreSQL is the preferred system of record (projects, workflows, runs, hypotheses, trials, chat); `CREATE SCHEMA proj_*` is registered on Postgres but ORM rows stay in `public` scoped by `project_id`. SQLite remains for tests and zero-setup smoke runs.

Git remains authoritative for source, lineage, notes, tags, and promotion history. SQL is the queryable runtime / handoff layer. Optional **observability** (Langfuse) and **memory** (Honcho / Hindsight / composite) ports soft-fail and are never the research ledger.

See [High-Level Design](docs/HIGH_LEVEL_DESIGN.md), [MVP scope](docs/MVP_SCOPE.md), and [architecture.html](docs/architecture.html).

## Loop model (research recipe)

```text
Hypothesis → Execution ⇄ (self-heal)
           → Eval script → Evaluation agent
           → Metric gate → Git decision → Hypothesis (outer feedback)
```

Grammar (enforced in UI + API + executor):

- Exactly one of each required type: `hypothesis`, `execution`, `eval_script`, `evaluation`, `metric_gate`, `git_decision`.
- Legal edges only (e.g. hyp→exec, exec→eval_script and/or exec→evaluation, eval_script→evaluation, evaluation→gate, gate→decision; optional exec→hyp / decision→hyp).
- Post-trial spine must compile to `eval_script → evaluation → metric_gate → git_decision`.
- `allowed_paths` live on the **execution** node (legacy standalone script allow-list is annotation-only).
- Canvas: required nodes are not deletable; illegal connects are blocked; Save/Run require a valid compile; **Reset recipe layout** restores the starter graph.

Behavior:

- Gate green (scalar): accept, merge into `master`, next hypothesis from the new champion.
- Gate red (scalar): reject, leave `master` unchanged, next hypothesis from last stable champion.
- Default gate is **one primary metric** + `direction` + `min_delta`. Opt-in `policy: "pareto"` keeps a non-dominated frontier (no auto-merge); pick the next base in the Frontier panel or `POST /api/projects/{id}/frontier/select`. See `examples/pareto-research/`.
- **Restart** (UI or `POST /api/projects/{id}/restart`): wipe experiment ledger/refs, keep champion tip, start a fresh run (recipe must still compile).
- Click Hypothesis for the agent → hypo → trial slide-over; toolbar **DB** opens the project table explorer.

## Agents (optional)

| Node flag | Module | Role |
|-----------|--------|------|
| `use_planner` on hypothesis | `hypothesis_planner.py` | Detailed experiment plan (Cursor/OpenAI) |
| `use_agent` on execution | `code_agent.py` | Allow-listed file edits before train |
| `use_agent` on evaluation | `evaluation_agent.py` | Accept/reject/retry + optional explainability schema |

Without these flags the deterministic brief / template path still runs. Keys: `CURSOR_API_KEY` (preferred) or `OPENAI_API_KEY` in process env (`source backend/.env` before `make backend-dev`).

## Agent observability (optional Langfuse)

AutoResearch records agent explainability (full prompts + generations + heuristic scores) through a swappable `AgentObservability` port. Default backend is `noop`.

| `AUTORESEARCH_OBSERVABILITY_BACKEND` | Meaning |
|---|---|
| `noop` | Off (default) |
| `langfuse-cloud` | Langfuse Cloud |
| `langfuse-selfhost` | Local OSS (`make langfuse-selfhost-up`) |
| `langfuse` | Generic host + keys |

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

```sh
AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost
AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-autoresearch-local
AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-autoresearch-local-dev-secret
AUTORESEARCH_LANGFUSE_HOST=http://localhost:3000
```

Details: [`ops/langfuse/README.md`](ops/langfuse/README.md). Agents never import Langfuse directly. Evaluation Git notes store vendor-neutral `agent_trace_id` / `prompt_version` / `observability_backend`.

Langfuse covers LLM cost/latency/scores — not champion `val_bpb` staircases (those stay in the AutoResearch UI). Usage is real provider tokens only; no invented dollar amounts.

## Agent memory (optional Honcho / Hindsight)

Preferences and soft lessons via `AgentMemory` (default `noop`). Git/Postgres remain SoR.

| `AUTORESEARCH_MEMORY_BACKEND` | Meaning |
|---|---|
| `noop` | Off (default) |
| `honcho` | Honcho session/preference memory (`uv sync --extra memory`) |
| `hindsight` | Hindsight retain/recall (install vendor client separately) |
| `composite` | Fan-out retain + merged recall (`AUTORESEARCH_MEMORY_PROVIDERS=honcho,hindsight`) |

```sh
AUTORESEARCH_MEMORY_BACKEND=honcho
AUTORESEARCH_HONCHO_API_KEY=...
AUTORESEARCH_HONCHO_WORKSPACE_ID=autoresearch
```

Briefs inject an advisory Memory section; outcomes and handoff call retain.

## Prerequisites

- Python 3.11+ and `uv`
- Node.js 20+ and npm
- Git user name/email in every target repository
- Optional: Docker (Postgres + Langfuse), `gh` (optional private GitHub remotes)

## Installation and running

```sh
make backend-install
make frontend-install
make postgres-up          # Docker Postgres on localhost:5432
# ensure backend/.env has AUTORESEARCH_DATABASE_URL=postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch
set -a; source backend/.env; set +a   # agent + observability + memory keys
make backend-dev
make frontend-dev
```

API: `http://localhost:8000`. Canvas: `http://localhost:5173`.

## Target configuration

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

Langfuse’s Postgres (if used) is on host **5434**, not 5432. Never point `AUTORESEARCH_DATABASE_URL` at the Langfuse DB.

## Example

[`examples/basic-research`](examples/basic-research) starts `score.txt` at `5.0`. Each accepted hypothesis decrements the score by one via `train.py` until `0.0` across five hypotheses. The evaluator prints `{"metrics": {"score": <number>}}`. The starter recipe includes `execution → eval_script` so the post-trial spine compiles.

**New project** (UI or `POST /api/projects`):

| `source` | Behavior |
|----------|----------|
| `seed` (default) | Local math fixture; optional private GitHub via connected `gh` |
| `local` | Register an existing Git repo root (`local_path`) |
| `git` | Clone `git_url` into `.autoresearch/projects/<name>/` |

`GET /api/github/status` reports whether `gh` is installed/authenticated and which owner would be used (`AUTORESEARCH_GITHUB_OWNER` or `gh` login — never a hardcoded personal account).

Bench projects under `.autoresearch/projects/` (e.g. `tinylm-bench`) use the same control plane with richer train/eval loops.

## Testing

```sh
make contracts
make test
make check
```

## Deferred features

Hermes automation, Podman isolation, Temporal orchestration, distributed workers, MCP tool nodes, parallel scheduling, rebase/re-eval merge queues, frontier auto-pick/crowding, tolerance/significance gates, and autonomous repair loops beyond inner retries are deferred. The MVP runner is for trusted local scripts only. Langfuse observability and Honcho/Hindsight memory are optional swappable backends (default off). The default gate remains a single primary metric; ε-Pareto is opt-in via `policy: "pareto"`.

## License

No project license has been selected yet. Until a license file is added, the repository is source-visible but should not be assumed to grant open-source usage rights.
