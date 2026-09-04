.PHONY: contracts backend-install backend-test backend-dev frontend-install frontend-test frontend-dev test check

contracts:
	python3 scripts/validate_contracts.py

backend-install:
	uv sync --project backend --extra dev --extra postgres

backend-test:
	uv run --project backend ruff check backend/src backend/tests
	uv run --project backend pytest -q backend/tests

backend-dev:
	uv run --project backend uvicorn autoresearch_api.main:app --reload --port 8000

frontend-install:
	npm install --prefix frontend

frontend-test:
	npm run test --prefix frontend

frontend-dev:
	npm run dev --prefix frontend

test: contracts backend-test frontend-test
	@true

check: contracts backend-test
	python3 -m unittest discover -s tests -p 'test_*.py'
	npm run lint --prefix frontend
	npm run test --prefix frontend
	npm run build --prefix frontend
	git diff --check
