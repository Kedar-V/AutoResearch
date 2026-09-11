# MVP scope

The MVP proves one complete research loop on a trusted local repository.

## Included

- Visual DAG with Hypothesis, Execution, Eval script, Evaluation agent, Metric gate, Git decision, optional Script allow-list, and DB viewer; trials are Hypothesis children from the inner retry loop
- Closed outer loop: Git decision feeds Hypothesis; Execution→Hypothesis is the self-heal cycle
- Versioned workflow JSON shared by frontend and backend
- Hypothesis and trial branches created from the configured champion branch
- Dedicated Git worktrees for trial execution
- Trusted local subprocess execution with explicit environment and timeout controls
- Structured evaluator output and a maximize/minimize metric gate
- Git-backed hypothesis, evaluation, and decision records
- PostgreSQL as preferred SoR (projects, hypotheses, trials, chat handoff); SQLite for tests
- Agent/hypothesis/trial slide-over and DB explorer
- New Project: private GitHub repo + math seed + project schema registration
- Live run status and metric results in the browser

## Deferred

- Podman and execution of untrusted code
- Temporal and distributed workers
- Hermes-driven autonomous repair loops
- Multi-user authentication and real-time collaboration
- Remote GPU scheduling
- External artifact storage

Hermes integration is represented by a replaceable agent boundary in the MVP architecture, but autonomous hypothesis generation is added only after the deterministic execution loop is proven.
