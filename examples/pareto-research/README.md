# Pareto research example

Toy loop that emits two minimize objectives (`score`, `cost`) and uses
`metric_gate.policy: "pareto"`.

- Hard gate: `ok == 1` and finite score/cost
- KEEP: tag/note frontier member; **no** auto-merge to `master`
- Pick next hypothesis base in the UI Frontier panel or
  `POST /api/projects/{id}/frontier/select` with `{ "commit": "…" }`
- Optional promote: `{ "commit": "…", "promote": true }` merges onto champion

Import this folder as a local project (or copy `research-loop.json` into a bench).
