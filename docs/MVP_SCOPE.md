# MVP scope

The MVP proves one complete research loop on a trusted local repository.

## Included

- Visual DAG with hypothesis, trial, script, evaluation, metric-gate, and Git-decision nodes
- Versioned workflow JSON shared by frontend and backend
- Hypothesis and trial branches created from the configured champion branch
- Dedicated Git worktrees for trial execution
- Trusted local subprocess execution with explicit environment and timeout controls
- Structured evaluator output and a maximize/minimize metric gate
- Git-backed hypothesis, evaluation, and decision records
- PostgreSQL-backed query projection, with SQLite available for tests
- Live run status and metric results in the browser

## Deferred

- Podman and execution of untrusted code
- Temporal and distributed workers
- Hermes-driven autonomous repair loops
- Multi-user authentication and real-time collaboration
- Remote GPU scheduling
- External artifact storage

Hermes integration is represented by a replaceable agent boundary in the MVP architecture, but autonomous hypothesis generation is added only after the deterministic execution loop is proven.
