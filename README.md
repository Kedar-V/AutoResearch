# AutoResearch

AutoResearch is a Git-native platform for running closed-loop research from a visual workflow canvas.

Researchers compose agents, scripts, evaluators, metric gates, MCP tools, and Git operations as nodes on a whiteboard. The platform executes the graph, records every hypothesis and trial in Git, and promotes only measurable improvements to the project’s champion branch.

## What we are building

The system turns an autonomous research loop into a visible, reproducible workflow:

1. An agent proposes a hypothesis.
2. The platform branches the hypothesis from the latest champion.
3. One or more trial branches attempt the idea or repair failures.
4. Scripts run in isolated Git worktrees and containers.
5. A protected evaluator emits structured metrics.
6. A metric gate accepts or rejects the candidate.
7. Accepted candidates are rebased, re-evaluated, and merged into `main`.
8. The next hypothesis starts from the improved `main`.

## Product principles

- **Git is the research ledger.** Code, lineage, metrics, decisions, and promotion history are reproducible from the repository.
- **SQL is a projection.** PostgreSQL makes the UI responsive but can be rebuilt from Git.
- **The canvas is executable.** Nodes represent real scripts or services; typed edges represent data flow.
- **Evaluation is protected.** A candidate cannot silently change the evaluator that judges it.
- **Promotion is evidence-based.** Only candidates that beat the current champion under the configured policy reach `main`.
- **The agent is replaceable.** Hermes is the initial research agent, connected through explicit APIs and MCP contracts.
- **The stack is self-hostable.** Core components are free and open source.

## Proposed stack

- React, TypeScript, Vite, and React Flow for the workflow canvas
- FastAPI, Pydantic, SQLAlchemy, and Alembic for the control plane
- PostgreSQL for the rebuildable query projection
- Temporal for durable workflow execution, retries, and cancellation
- Git CLI and Git worktrees for hypotheses and trials
- Podman for isolated script execution
- Hermes Agent and AutoResearchClaw for research behavior
- Model Context Protocol for tool nodes and workflow interoperability
- Forgejo when a self-hosted Git collaboration layer is needed

## Initial node catalog

- Agent
- Create Hypothesis
- Create Trial
- Python Script
- Shell Script
- Evaluation Script
- MCP Tool
- Condition / Metric Gate
- Loop / Retry
- Git Commit
- Accept / Reject
- Merge Champion
- Artifact
- Human Approval

Every node input and output is described with JSON Schema. The editor permits a connection only when its source and destination schemas are compatible.

## Repository status

The project is currently in the architecture and foundation phase. The first implementation milestone is a local, single-user vertical slice:

```text
canvas -> hypothesis branch -> trial worktree -> script -> evaluator
       -> metric gate -> Git decision record -> accept/reject
```

See the [High-Level Design](docs/HIGH_LEVEL_DESIGN.md) for component boundaries, Git semantics, data ownership, and the delivery plan.

## Branching convention

The target convention is:

```text
main
├── hypothesis/H0001-short-description
│   ├── trial/H0001/T001
│   └── trial/H0001/T002
└── hypothesis/H0002-short-description
    └── trial/H0002/T001
```

The repository currently uses `master` as its default branch. It will be migrated to `main` before implementation work begins so the repository matches the promotion model described above.

## License

No project license has been selected yet. Until a license file is added, the repository is source-visible but should not be assumed to grant open-source usage rights.
