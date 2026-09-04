# AutoResearch contracts

These JSON Schemas are the stable boundary between the canvas, API, workers, Git ledger, and SQL projector.

Rules:

- Schemas use JSON Schema Draft 2020-12.
- Each schema has a unique, versioned `$id`.
- Records persisted to Git include their `schema_version`.
- Breaking changes require a new schema version and an explicit migration.
- The frontend and backend must validate the same workflow contract.
