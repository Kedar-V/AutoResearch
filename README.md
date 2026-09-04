# AutoResearch

AutoResearch is a local, Git-native MVP for executable research workflows. Its React Flow whiteboard creates and connects hypothesis, trial, script, evaluation, metric-gate, and Git-decision nodes. The FastAPI control plane saves workflows in SQL and executes trusted local scripts sequentially in Git worktrees.

An improving candidate is committed on a trial branch, evaluated by a protected script, tagged, merged into the configured champion branch, and recorded as the new champion. Rejected and failed trials retain their branches, tags, and Git notes.

## Architecture

The MVP consists of the React Flow frontend, FastAPI/SQLAlchemy control plane, trusted local runner, native Git CLI/worktrees, contract schemas, and SQLite by default. See the [High-Level Design](docs/HIGH_LEVEL_DESIGN.md) for the full architecture and later milestones.

Git is authoritative for source, workflow lineage, hypothesis/evaluation/decision/champion notes, tags, and promotion history. SQL stores the queryable runtime projection: workflow definitions, runs, node runs, and metrics. SQLite is zero-setup; PostgreSQL remains supported for a production-shaped deployment.

## Branch Model

The configured champion branch defaults to `master` for this repository:

```text
master
├── hypothesis/H0001-improve-score
│   └── trial/H0001/T001
└── hypothesis/H0002-improve-score
    └── trial/H0002/T001
```

The system creates `accepted/H0001-T001`, `rejected/H0002-T001`, or `failed/...` tags and writes structured records to `refs/notes/research/*`.

## Prerequisites

- Python 3.11 or newer and `uv`
- Node.js 20 or newer and npm
- Git configured with a user name and email in every target repository

## Installation And Running

```sh
make backend-install
make frontend-install
make backend-dev
make frontend-dev
```

The API listens on `http://localhost:8000`; Vite serves the canvas at `http://localhost:5173`. Open the canvas, drag node types from the palette, connect ports, edit node JSON in the inspector, then save or run the workflow.

## Target Configuration

Set these before starting the API, pointing `AUTORESEARCH_PROJECT_ROOT` at a clean Git repository whose champion branch exists:

```sh
export AUTORESEARCH_DATABASE_URL='sqlite:///./autoresearch.db'
export AUTORESEARCH_PROJECT_ROOT="$PWD/examples/basic-research"
export AUTORESEARCH_RUNTIME_ROOT="$PWD/.autoresearch"
export AUTORESEARCH_CHAMPION_BRANCH='master'
export AUTORESEARCH_ALLOWED_ORIGINS='http://localhost:5173'
export AUTORESEARCH_SCRIPT_TIMEOUT_SECONDS='300'
export AUTORESEARCH_PROTECTED_PATHS='eval.py,tests,.research'
```

For PostgreSQL, use a SQLAlchemy PostgreSQL URL such as `postgresql+psycopg://user:password@localhost/autoresearch` and install the `postgres` extra through `make backend-install`. `AUTORESEARCH_ALLOWED_ORIGINS` and `AUTORESEARCH_PROTECTED_PATHS` accept comma-separated values.

## Example

[`examples/basic-research`](examples/basic-research) is a small target project. Initialize it as a Git repository on `master`, configure the target variables above, save [`research-loop.json`](examples/basic-research/research-loop.json) through the API or canvas, and run it. The included candidate changes `score.txt` from `1.0` to `0.5`; its minimize gate accepts it. Change `train.py` to write a worse value such as `1.5` to see a rejected trial that leaves `master` unchanged. The evaluator must print `{"metrics": {"score": <number>}}`.

## Testing

```sh
make contracts
make test
make check
```

`make check` validates contracts, backend lint/tests including the real-Git lifecycle smoke test, frontend lint/tests/build, root contract tests, and Git whitespace.

## Deferred Features

Hermes automation, Podman isolation, Temporal orchestration, distributed workers, MCP tool execution, parallel scheduling, and autonomous repair loops are deferred. The MVP runner is for trusted local scripts only; it is not a security sandbox.

## License

No project license has been selected yet. Until a license file is added, the repository is source-visible but should not be assumed to grant open-source usage rights.
