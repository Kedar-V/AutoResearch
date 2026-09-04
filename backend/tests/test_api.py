from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from autoresearch_api.database import get_session
from autoresearch_api.main import create_app


def test_workflow_round_trip(session: Session) -> None:
    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    workflow = {
        "schema_version": "1",
        "id": "api-flow",
        "name": "API flow",
        "description": "Round-trip test",
        "nodes": [],
        "edges": [],
    }

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        saved = client.put("/api/workflows/api-flow", json=workflow)
        assert saved.status_code == 200
        assert saved.json() == workflow

        loaded = client.get("/api/workflows/api-flow")
        assert loaded.status_code == 200
        assert loaded.json() == workflow

        listing = client.get("/api/workflows")
        assert listing.status_code == 200
        assert listing.json()[0]["id"] == "api-flow"


def test_workflow_path_must_match_definition(session: Session) -> None:
    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    workflow = {
        "schema_version": "1",
        "id": "actual-id",
        "name": "Mismatch",
        "nodes": [],
        "edges": [],
    }

    with TestClient(app) as client:
        response = client.put("/api/workflows/wrong-id", json=workflow)

    assert response.status_code == 422
    assert response.json()["detail"] == "path id must match workflow id"
