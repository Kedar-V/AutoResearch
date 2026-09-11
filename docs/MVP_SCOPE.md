# MVP scope

The MVP proves one complete research loop on a trusted local repository.

## Included

- **Locked research recipe** canvas (not a freeform DAG): exactly one Hypothesis, Execution, Eval script, Evaluation agent, Metric gate, and Git decision; optional DB viewer; typed ports; required nodes undeletable
- Shared recipe compiler (`compile_recipe` / `compileRecipe` → `CompiledLoop`) in UI + API + executor; illegal graphs rejected on save/run/restart (HTTP 422)
- Closed outer loop: Git decision → Hypothesis; Execution→Hypothesis self-heal; post-trial spine `eval_script → evaluation → metric_gate → git_decision`
- Versioned workflow JSON in SQL (shared contracts under `contracts/`)
- Hypothesis and trial branches from the configured champion branch (`master` by default)
- Dedicated Git worktrees for trial execution; `allowed_paths` on the execution node
- Trusted local subprocess execution with explicit environment and timeout controls
- Structured evaluator output and a maximize/minimize **scalar** metric gate by default (`metric` + `direction` + `min_delta`); eval JSON may include extra metrics for display/agents
- Opt-in **ε-Pareto** gate (`policy: "pareto"` + `objectives` + optional `hard_gates`): KEEP non-dominated trials on a frontier (no auto-merge); human picks next hypothesis base via API/UI
- Git-backed hypothesis, evaluation, decision, champions, and frontier notes + decision/frontier tags
- PostgreSQL as preferred SoR (projects, workflows, runs, hypotheses, trials, chat handoff); SQLite for tests
- Optional Cursor/OpenAI agents: planner (`use_planner`), execution edits (`use_agent`), evaluation judgments (`use_agent` + optional explainability schema)
- Optional Langfuse observability via `AgentObservability` (`noop` | `langfuse-*`)
- Optional agent memory via `AgentMemory` (`noop` | `honcho` | `hindsight` | `composite`)
- Project Restart: wipe experiment ledger/refs, keep champion tip, auto-start a fresh run
- Run controls: cancel / pause / resume; Reset recipe layout
- Agent/hypothesis/trial slide-over, evaluation slide-over, and DB explorer
- New Project: private GitHub repo + math seed + `proj_<slug>` schema registration
- Live run status and metric staircases in the browser

## Deferred

- Freeform / general-purpose DAG editors
- Podman and execution of untrusted code
- Temporal and distributed workers
- Hermes / AutoResearchClaw as the agent runtime
- MCP tool nodes
- Automatic rebase → re-eval → merge when the champion advances underfoot
- Configurable trial ancestry (`sibling` / `chained` / `last_runnable`)
- Auto-pick utility over the frontier, judge-in-platform scores, archive crowding/pruning, threshold-with-tolerance, or statistical-significance gate policies
- Multi-user authentication and real-time collaboration
- Remote GPU scheduling
- External content-addressed artifact storage
- OpenTelemetry / Prometheus service stack

Agents today are Cursor SDK / OpenAI modules behind replaceable boundaries. Hermes remains a deferred alternative runtime, not the shipped path.
