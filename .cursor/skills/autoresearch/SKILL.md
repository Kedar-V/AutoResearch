---
name: autoresearch
description: >-
  Operate the AutoResearch Git-native research loop (projects, runs, planner,
  execution agent, worktrees). Use when setting up Postgres or observability/Langfuse,
  connecting GitHub (gh auth), creating/importing projects, cleaning up or resetting
  a project run, restarting the API with keys, starting tinylm/nanochat benches,
  or debugging hypothesis/trial ledger and Git experiment refs.
---

# AutoResearch

Local control plane: FastAPI `:8000`, UI `:5173`, preferred SoR **PostgreSQL
via Docker** (`make postgres-up` → `localhost:5432`; SQLite only for tests /
zero-setup smoke), runtime `.autoresearch/`, project clones
`.autoresearch/projects/<name>/`.

## Setup

Use when the user says set up AutoResearch, configure the database, Postgres,
Langfuse, enable tracing, first-time observability, **connect GitHub**, or
create/import a project. **For Langfuse, always ask which mode they want before
writing env or starting containers.** Do not assume Cloud or self-host.

**For GitHub / New Project, always check connection status and guide the user
before creating a private remote.** Do not assume `gh` is installed or logged
in. Do **not** hardcode `AUTORESEARCH_GITHUB_OWNER` to a personal account
(never `Kedar-V`). Leave it empty so the API uses `gh api user` login, or set
it only to the user's confirmed login/org.

Env file: `$ROOT/backend/.env` (never commit). Restart API after changes
(`source backend/.env` then `make backend-dev`).

### Shared prerequisite

```sh
cd "$ROOT"
make backend-install   # includes postgres + observability (langfuse) extras
```

### First-run: connect GitHub (prompt the user)

When setting up AutoResearch, creating a project with a private GitHub remote,
or the user asks about GitHub / `gh`, **ask and guide** — do not silently skip
or invent an owner.

Ask (one question):

> Do you want AutoResearch to create private GitHub remotes for new projects?
>
> 1. **Yes** — connect GitHub CLI (`gh`) to your account (recommended for push
>    of experiment branches/tags)
> 2. **No** — local-only projects for now (you can import/clone later)

#### If Yes — walk them through

1. Check status (API if running, else CLI):

```sh
# Prefer API when backend is up:
curl -s http://127.0.0.1:8000/api/github/status
# Or CLI:
command -v gh && gh auth status && gh api user --jq .login
```

2. If `gh` missing:

```sh
brew install gh   # macOS; otherwise https://cli.github.com
```

3. Authenticate (browser flow):

```sh
gh auth login -h github.com -p https -w
```

Explain: choose GitHub.com → HTTPS → Login with a web browser → paste the
one-time code when prompted.

4. Confirm login:

```sh
gh api user --jq .login
curl -s http://127.0.0.1:8000/api/github/status
```

5. Env (optional override only):

```sh
# Leave empty to use the authenticated gh login:
AUTORESEARCH_GITHUB_OWNER=
# Or set explicitly to their login / org they can write to:
# AUTORESEARCH_GITHUB_OWNER=their-login-or-org
```

Never write someone else's username. After env changes, restart the API with
`source backend/.env`.

6. In the UI **New project** dialog: pick Toy seed / Import local / Clone URL.
   Check **Create private GitHub repo** only when status shows authenticated.
   Owner shown is `resolved_owner` from `/api/github/status`.

#### If No — local / import paths

- **Toy seed**: local math fixture under `.autoresearch/projects/<name>/` (no remote).
- **Import local**: register an existing Git repo root (`source=local`, `local_path=...`).
- **Clone URL**: `git clone` into `.autoresearch/projects/<name>/` (`source=git`).

GitHub remains optional later; they can push manually or recreate with
`create_github` once `gh` is connected.

### PostgreSQL (preferred system of record)

Preferred SoR for local/dev. Run it with **Docker** (`make postgres-up`).
Driver: `psycopg` via the `postgres` extra (`make backend-install`). URL must
use `postgresql+psycopg://...`.

| Service | Host port |
|---------|-----------|
| AutoResearch Postgres | **5432** (`make postgres-up`) |
| Langfuse Postgres | **5434** (`make langfuse-selfhost-up`) |

Never point `AUTORESEARCH_DATABASE_URL` at Langfuse.

#### 1. Start Postgres (Docker)

```sh
cd "$ROOT"
make postgres-up
# make postgres-logs
# make postgres-down
```

Compose: `ops/postgres/docker-compose.yml` — user/db/password `autoresearch`,
volume `autoresearch_postgres_data`, bound to `127.0.0.1:5432`.

#### 2. Env

In `backend/.env` (merge; see `backend/.env.example`):

```sh
AUTORESEARCH_DATABASE_URL=postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch
```

SQLite remains only for unit tests / zero-setup smoke when the URL is unset
(`sqlite:///./autoresearch.db`). Prefer Docker Postgres for normal API runs.

#### 3. Schema bootstrap (automatic)

On API startup, `ensure_schema()` runs `Base.metadata.create_all` against the
configured URL. **No Alembic migrations in MVP** — tables are created if
missing. Soft column adds exist only for SQLite legacy DBs.

Control-plane tables live in the default **`public`** schema:

| Table | Role |
|-------|------|
| `projects` | Registry (`name`, `local_path`, `github_url`, `pg_schema`, `is_active`) |
| `workflows` | Versioned DAG JSON (`definition`), optional `project_id` |
| `runs` / `node_runs` | Workflow execution + per-node status/output |
| `metrics` | Numeric metrics per run (`project_id` scoped) |
| `hypotheses` / `trials` | Ledger rows (`project_id`; Git remains branch/tag SoT) |
| `chat_messages` / `chat_summaries` | Handoff / DB explorer chat |

Verify (Docker exec if `psql` is not installed on the host):

```sh
docker compose -f ops/postgres/docker-compose.yml exec postgres \
  psql -U autoresearch -d autoresearch -c '\dt' -c '\dn'
```

#### 4. Per-project Postgres schemas

On **New Project** (seed / import local / clone), the API:

1. Stores `projects.pg_schema = proj_<slug>` (`schema_name()`: lowercased
   alphanumerics → underscores, max 48 chars after `proj_`).
2. When the dialect is PostgreSQL, runs:
   `CREATE SCHEMA IF NOT EXISTS "proj_<slug>"`.

`POST /api/projects` body:

| Field | Notes |
|-------|--------|
| `name` | required |
| `source` | `seed` (default), `local`, or `git` |
| `create_github` | optional; requires connected `gh`; ignored for `source=git` |
| `local_path` | required for `source=local` (Git repo root) |
| `git_url` | required for `source=git` |
| `github_owner` | optional per-request override; else env / `gh` login |

`GET /api/github/status` reports install + auth + `resolved_owner`.

Today ORM tables still sit in **`public`** and are scoped by `project_id`.
The `proj_*` schemas are reserved/registered for isolation / explorer use —
do **not** expect hypothesis/trial rows inside `proj_*` yet. Git remains the
branch/tag/notes ledger.

#### 5. Project wipe on Postgres

Cleanup SQL in this skill defaults to `sqlite3` on `autoresearch.db`. When
using Docker Postgres:

```sh
docker compose -f ops/postgres/docker-compose.yml exec -T postgres \
  psql -U autoresearch -d autoresearch <<SQL
DELETE FROM node_runs WHERE run_id IN (SELECT id FROM runs WHERE project_id='$PID');
DELETE FROM metrics WHERE project_id='$PID' OR run_id IN (SELECT id FROM runs WHERE project_id='$PID');
DELETE FROM trials WHERE project_id='$PID';
DELETE FROM hypotheses WHERE project_id='$PID';
DELETE FROM chat_messages WHERE project_id='$PID';
DELETE FROM chat_summaries WHERE project_id='$PID';
DELETE FROM runs WHERE project_id='$PID';
SQL
```

Never wipe the Langfuse DB on 5434. Details: `ops/postgres/README.md`.

### Observability / Langfuse

**Always ask which mode they want before writing env or starting containers.**

Ask (one question):

> How should agent observability run?
>
> 1. **noop** — off (default; research loop only, no Langfuse)
> 2. **langfuse-cloud** — Langfuse Cloud (Free or Pro); needs project API keys
> 3. **langfuse-selfhost** — local OSS via Docker (`make langfuse-selfhost-up`)

Then apply **only** the chosen path. Core agents work in all modes; missing
keys with a Langfuse mode selected falls back to noop soft-fail.

### Agent memory (Honcho / Hindsight)

Optional vendor memory for **preferences and soft lessons** only. Git + Postgres
remain the research SoR. Port: `backend/src/autoresearch_api/memory/` (noop |
honcho | hindsight | composite). Soft-fail like Langfuse.

```sh
# In backend/.env — pick one
AUTORESEARCH_MEMORY_BACKEND=noop
# AUTORESEARCH_MEMORY_BACKEND=honcho
# AUTORESEARCH_HONCHO_API_KEY=...
# AUTORESEARCH_HONCHO_WORKSPACE_ID=autoresearch
# AUTORESEARCH_MEMORY_BACKEND=composite
# AUTORESEARCH_MEMORY_PROVIDERS=honcho,hindsight
```

Install Honcho SDK when enabling it: `uv sync --project backend --extra memory`.
Hindsight uses its own client package (install separately). Briefs inject a
Memory section on recall; outcomes/handoff call retain. Never wipe vendor DBs
on project Restart.

Optional: create Langfuse prompts named `autoresearch/hypothesis`,
`autoresearch/execution`, `autoresearch/evaluation` (code defaults until then).

#### Mode: noop

```sh
# In backend/.env
AUTORESEARCH_OBSERVABILITY_BACKEND=noop
# Leave LANGFUSE_* empty or unused
```

Tell the user tracing is off; champion metrics still live in AutoResearch UI/Git.

#### Mode: langfuse-cloud

1. Ask them for **public key**, **secret key**, and **host** (default
   `https://cloud.langfuse.com`; EU if they use EU cloud).
2. Write `backend/.env` (merge; do not wipe unrelated keys):

```sh
AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-cloud
AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-...
AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-...
AUTORESEARCH_LANGFUSE_HOST=https://cloud.langfuse.com
```

3. Restart the API with keys in the process env (see API restart below).
4. Confirm: run one planner/execution/eval loop → traces appear in their
   Langfuse Cloud project under session/`run_id`.

#### Mode: langfuse-selfhost

1. Start the local stack (copies `.env.example` → `ops/langfuse/.env` if needed):

```sh
cd "$ROOT"
make langfuse-selfhost-up
```

2. UI: `http://localhost:3000` — default login
   `admin@autoresearch.local` / `changeme-langfuse-admin` (change for anything shared).
3. Write `backend/.env` with seeded local keys:

```sh
AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost
AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-autoresearch-local
AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-autoresearch-local-dev-secret
AUTORESEARCH_LANGFUSE_HOST=http://localhost:3000
```

4. Restart the API. Postgres for Langfuse is on host **5434** (not 5432) so it
   does not clash with AutoResearch Postgres.
5. Stop later with `make langfuse-selfhost-down`. Details: `ops/langfuse/README.md`.

#### Mode notes

| Backend value | Host resolution |
|---------------|-----------------|
| `noop` | N/A |
| `langfuse-cloud` | Cloud host unless user overrides |
| `langfuse-selfhost` | `http://localhost:3000` unless user overrides |
| `langfuse` | Generic: whatever `AUTORESEARCH_LANGFUSE_HOST` + keys say |

Do **not** import `langfuse` outside `observability/langfuse_adapter.py`.
Git notes use vendor-neutral `agent_trace_id` / `prompt_version` /
`observability_backend`. Langfuse charts ≠ champion `val_bpb` plots
(those stay in AutoResearch UI). Pass through real token usage/cost from
Cursor/OpenAI only — never invent usage or dollar amounts for the UI.

## Cleanup / reset a project run

Use when the user says clean up, reset, start fresh, or wipe the previous run.
Default target is the **active project** (often `tinylm-bench`). Do **not**
reset `master` to an older seed unless explicitly asked — keep current champion
code; only wipe experiment ledger + refs.

UI **Restart** (topbar) calls `POST /api/projects/{id}/restart` — same wipe +
auto-starts a fresh run. Prefer that for interactive resets.

Substitute:

| Var | Example (`tinylm-bench`) |
|-----|--------------------------|
| `ROOT` | repo root (`AutoResearch/`) |
| `REPO` | `$ROOT/.autoresearch/projects/<name>` |
| `RUNTIME` | `$ROOT/.autoresearch` |
| `PID` | project UUID from `SELECT id,name FROM projects` |
| `DB` | `$ROOT/autoresearch.db` |
| `WF` | `<name>-loop` (e.g. `tinylm-bench-loop`) |

### 1. Local wipe

```sh
set -e
ROOT=... REPO=... RUNTIME=... PID=... DB=...

# Worktrees + briefs
git -C "$REPO" worktree list --porcelain | awk '/^worktree /{print $2}' | while read -r wt; do
  case "$wt" in "$REPO") ;; *) git -C "$REPO" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt" ;; esac
done
git -C "$REPO" worktree prune
rm -rf "$RUNTIME/worktrees"/H*
rm -f "$RUNTIME/briefs"/H*.md

# Experiment branches + decision tags
git -C "$REPO" for-each-ref --format='%(refname:short)' refs/heads/hypothesis refs/heads/trial \
  | while read -r b; do git -C "$REPO" branch -D "$b"; done
git -C "$REPO" tag -l 'accepted/*' 'rejected/*' 'failed/*' \
  | while read -r t; do git -C "$REPO" tag -d "$t"; done

# Research notes
for ref in research/hypotheses research/decisions research/evaluations research/champions; do
  git -C "$REPO" notes --ref="$ref" list 2>/dev/null | awk '{print $2}' | while read -r c; do
    git -C "$REPO" notes --ref="$ref" remove --ignore-missing "$c" 2>/dev/null || true
  done
done

git -C "$REPO" checkout master
git -C "$REPO" reset --hard HEAD
git -C "$REPO" clean -fd

sqlite3 "$DB" <<SQL
DELETE FROM node_runs WHERE run_id IN (SELECT id FROM runs WHERE project_id='$PID');
DELETE FROM metrics WHERE project_id='$PID' OR run_id IN (SELECT id FROM runs WHERE project_id='$PID');
DELETE FROM trials WHERE project_id='$PID';
DELETE FROM hypotheses WHERE project_id='$PID';
DELETE FROM chat_messages WHERE project_id='$PID';
DELETE FROM chat_summaries WHERE project_id='$PID';
DELETE FROM runs WHERE project_id='$PID';
SQL
```

Insert a fresh chat summary row afterward if the UI expects one.

### 2. Remote wipe (same GitHub repo)

```sh
git -C "$REPO" fetch origin --prune
git -C "$REPO" ls-remote --heads origin 'hypothesis/*' 'trial/*' \
  | awk '{print $2}' | sed 's#refs/heads/##' \
  | while read -r b; do git -C "$REPO" push origin --delete "$b"; done
git -C "$REPO" ls-remote --tags origin 'accepted/*' 'rejected/*' 'failed/*' \
  | awk '{print $2}' | sed 's#refs/tags/##' | sed 's#\^{}##' | sort -u \
  | while read -r t; do
      [ -n "$t" ] || continue
      git -C "$REPO" push origin --delete "refs/tags/$t" || true
    done
# Drop any tags fetch recreated locally
git -C "$REPO" tag -l 'accepted/*' 'rejected/*' 'failed/*' \
  | while read -r t; do git -C "$REPO" tag -d "$t"; done
```

### 3. Reactivate

```sh
curl -s -X POST "http://127.0.0.1:8000/api/projects/$PID/activate"
curl -s -X PUT "http://127.0.0.1:8000/api/workflows/$WF" \
  -H 'Content-Type: application/json' \
  --data-binary @"$REPO/research-loop.json"
```

Verify: 0 hypotheses/trials/runs for `PID`; only `master` locally; 0 remote
`hypothesis/*` / `trial/*` / decision tags. Tell the user to hard-refresh the UI.

## API restart (with agent keys)

`Settings` ignores non-`AUTORESEARCH_*` keys; `CURSOR_API_KEY` / `OPENAI_API_KEY`
must be in the process env (e.g. `source backend/.env` before `make backend-dev`).
Langfuse keys use the `AUTORESEARCH_LANGFUSE_*` / `AUTORESEARCH_OBSERVABILITY_BACKEND`
prefix and are loaded via Settings after `source backend/.env`.

```sh
set -a; source "$ROOT/backend/.env"; set +a
lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill -9 2>/dev/null || true
cd "$ROOT"
# Prefer Postgres from .env; SQLite only if unset / smoke:
# export AUTORESEARCH_DATABASE_URL='postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch'
# export AUTORESEARCH_DATABASE_URL='sqlite:///./autoresearch.db'
export AUTORESEARCH_PROJECT_ROOT="$PWD/examples/basic-research"
export AUTORESEARCH_RUNTIME_ROOT="$PWD/.autoresearch"
export AUTORESEARCH_CHAMPION_BRANCH='master'
export AUTORESEARCH_ALLOWED_ORIGINS='http://localhost:5173'
export AUTORESEARCH_SCRIPT_TIMEOUT_SECONDS='900'
export AUTORESEARCH_PROTECTED_PATHS='eval.py,tests,.research'
# Leave empty to use `gh` login; never hardcode a personal owner.
# export AUTORESEARCH_GITHUB_OWNER=''
make backend-dev
```

If `.env` already sets `AUTORESEARCH_DATABASE_URL`, do not override it with
SQLite in the restart shell unless intentionally falling back.

## Bench workflow flags

In `research-loop.json` hypothesis/execution/evaluation config:

- `use_planner: true` — LLM writes a detailed experiment plan (not a generic title)
- `use_agent: true` on **execution** — Cursor/OpenAI edits allow-listed files, then the
  execution `command` runs training (e.g. `run_train.py` / `train.py`)
- `eval_script` — trusted metrics-only step (reads `metrics.json`); does not train
- `metric_gate` — **single** primary `metric` + `direction` + `min_delta` only
  (multi-objective / Pareto / tolerance / significance policies are not MVP)
- `use_agent: true` on **evaluation** — Cursor/OpenAI writes real accept/reject/retry judgments (not a metric template)
- `explainability_schema` on **evaluation** only — optional JSON Schema for custom
  explainability fields under `explainability` (confidence, attribution, etc.).
  Validated by the evaluation agent; ignored by hypothesis/execution and by the
  metric gate. Clear/`null` disables. Does not change `recommendation` enum or gate math.
- `history_window` / `max_hypotheses` — history-aware planning bounds
- `model: composer-2.5` when using Cursor

After editing the JSON, PUT the workflow and push the project repo if desired.

## Known pitfalls

- Stale live-run widget: bind to the **current project workflow** only; after cleanup, refresh UI.
- Trial diff URLs: use `{trial_id:path}` for ids like `H0001/T001`.
- Promotion fails with “champion worktree must be clean” → cleanup / hard-reset master WT
  (error lists porcelain paths). Keep champion WD clean while runs are active.
- Accepted tag/note but **no** merge on master (often followed by “champion advanced”):
  stop the run, `git reset --hard` to the trial’s `hypothesis_base_commit`,
  `git merge --no-ff trial/<H>/<T>`, then cherry-pick any later champion-only commits
  (resolve keeping the accepted trial’s metric-winning edits), record a champions note
  on the merge tip, resume from the cleaned champion.
- Do not commit `backend/.env` or secrets.
- Observability: ask Langfuse mode before setup; `langfuse-*` without keys → silent noop.
- Self-host Langfuse Postgres is on **5434**; AutoResearch SoR is **5432** —
  never point `AUTORESEARCH_DATABASE_URL` at the Langfuse DB.
- ORM tables are in **`public`**; `proj_*` schemas are registered on project
  create but rows are still `project_id`-scoped in `public`.
- URL dialect: use `postgresql+psycopg://…` with the `postgres` extra installed.
- Start SoR with `make postgres-up` (Docker **5432**); Langfuse DB is **5434**.
