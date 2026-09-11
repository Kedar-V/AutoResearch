# AutoResearch Postgres (Docker)

Preferred system of record for the API control plane.

```sh
make postgres-up      # http://localhost:5432
make postgres-logs
make postgres-down
```

Connection (matches `backend/.env.example`):

```text
postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch
```

Tables are created on API startup via `ensure_schema()` (`create_all`).
Per-project `proj_<slug>` schemas are registered with `CREATE SCHEMA IF NOT EXISTS`
when creating a project; ORM rows remain in `public` scoped by `project_id`.

**Port map:** AutoResearch **5432**, Langfuse self-host Postgres **5434**.
Do not point `AUTORESEARCH_DATABASE_URL` at Langfuse.
