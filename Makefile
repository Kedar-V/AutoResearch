.PHONY: contracts backend-install backend-test backend-dev frontend-install frontend-test frontend-dev test check postgres-up postgres-down postgres-logs langfuse-selfhost-up langfuse-selfhost-down langfuse-selfhost-logs

contracts:
	python3 scripts/validate_contracts.py

backend-install:
	uv sync --project backend --extra dev --extra postgres --extra observability

backend-test:
	uv run --project backend ruff check backend/src backend/tests
	uv run --project backend pytest -q backend/tests

backend-dev:
	uv run --project backend uvicorn autoresearch_api.main:app --reload --reload-dir backend --port 8000

frontend-install:
	npm install --prefix frontend

frontend-test:
	npm run test --prefix frontend

frontend-dev:
	npm run dev --prefix frontend

# Preferred SoR Postgres (Docker). Host :5432 — not Langfuse :5434.
postgres-up:
	docker compose -f ops/postgres/docker-compose.yml up -d
	@echo ""
	@echo "AutoResearch Postgres: localhost:5432 / db=autoresearch user=autoresearch"
	@echo "Set backend/.env:"
	@echo "  AUTORESEARCH_DATABASE_URL=postgresql+psycopg://autoresearch:autoresearch@localhost:5432/autoresearch"
	@echo "Then restart make backend-dev (tables create on startup)."

postgres-down:
	docker compose -f ops/postgres/docker-compose.yml down

postgres-logs:
	docker compose -f ops/postgres/docker-compose.yml logs -f

# Optional Langfuse OSS (self-host). Does not start with backend-dev.
langfuse-selfhost-up:
	@test -f ops/langfuse/.env || cp ops/langfuse/.env.example ops/langfuse/.env
	docker compose -f ops/langfuse/docker-compose.yml --env-file ops/langfuse/.env up -d
	@echo ""
	@echo "Langfuse UI: http://localhost:3000"
	@echo "Login (first boot): admin@autoresearch.local / changeme-langfuse-admin"
	@echo "Set backend/.env:"
	@echo "  AUTORESEARCH_OBSERVABILITY_BACKEND=langfuse-selfhost"
	@echo "  AUTORESEARCH_LANGFUSE_PUBLIC_KEY=pk-lf-autoresearch-local"
	@echo "  AUTORESEARCH_LANGFUSE_SECRET_KEY=sk-lf-autoresearch-local-dev-secret"
	@echo "  AUTORESEARCH_LANGFUSE_HOST=http://localhost:3000"
	@echo "Then restart make backend-dev."

langfuse-selfhost-down:
	docker compose -f ops/langfuse/docker-compose.yml --env-file ops/langfuse/.env down

langfuse-selfhost-logs:
	docker compose -f ops/langfuse/docker-compose.yml --env-file ops/langfuse/.env logs -f

test: contracts backend-test frontend-test
	@true

check: contracts backend-test
	python3 -m unittest discover -s tests -p 'test_*.py'
	npm run lint --prefix frontend
	npm run test --prefix frontend
	npm run build --prefix frontend
	git diff --check
