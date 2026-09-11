from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from autoresearch_api.database import get_session
from autoresearch_api.main import create_app

from .test_workflow import research_recipe


def _valid_workflow(workflow_id: str = "api-flow") -> dict:
    definition = research_recipe().model_dump(mode="json")
    definition["id"] = workflow_id
    definition["name"] = workflow_id
    return definition


def test_workflow_round_trip(session: Session) -> None:
    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    workflow = _valid_workflow()

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        saved = client.put("/api/workflows/api-flow", json=workflow)
        assert saved.status_code == 200
        assert saved.json()["id"] == "api-flow"

        loaded = client.get("/api/workflows/api-flow")
        assert loaded.status_code == 200
        assert loaded.json()["id"] == "api-flow"

        listing = client.get("/api/workflows")
        assert listing.status_code == 200
        assert listing.json()[0]["id"] == "api-flow"


def test_workflow_path_must_match_definition(session: Session) -> None:
    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    workflow = _valid_workflow("actual-id")

    with TestClient(app) as client:
        response = client.put("/api/workflows/wrong-id", json=workflow)

    assert response.status_code == 422
    assert response.json()["detail"] == "path id must match workflow id"


def test_save_rejects_disconnected_gate(session: Session) -> None:
    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    workflow = _valid_workflow("bad-gate")
    workflow["edges"] = [
        edge
        for edge in workflow["edges"]
        if edge["id"] not in {"a-g", "g-d"}
    ]

    with TestClient(app) as client:
        response = client.put("/api/workflows/bad-gate", json=workflow)

    assert response.status_code == 422
    assert "metric_gate" in response.json()["detail"]


def test_create_run_rejects_invalid_recipe(session: Session) -> None:
    from autoresearch_api.models import Workflow

    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    session.add(
        Workflow(
            id="broken-flow",
            name="broken",
            description="",
            definition={
                "schema_version": "1",
                "id": "broken-flow",
                "name": "broken",
                "nodes": [],
                "edges": [],
            },
        )
    )
    session.commit()

    with TestClient(app) as client:
        response = client.post("/api/runs", json={"workflow_id": "broken-flow"})

    assert response.status_code == 422
    assert "hypothesis" in response.json()["detail"]


def test_list_project_evaluations(session: Session) -> None:
    from datetime import UTC, datetime

    from autoresearch_api.models import NodeRun, Project, Run, Workflow

    project = Project(
        name="eval-proj",
        local_path="/tmp/eval-proj",
        pg_schema="proj_eval",
        status="active",
    )
    workflow = Workflow(
        id="eval-flow",
        name="eval-flow",
        description="",
        definition={"schema_version": "1", "id": "eval-flow", "name": "eval-flow", "nodes": [], "edges": []},
        project_id=None,
    )
    session.add(project)
    session.flush()
    workflow.project_id = project.id
    run = Run(workflow_id="eval-flow", project_id=project.id, status="succeeded")
    session.add_all([workflow, run])
    session.flush()
    session.add(
        NodeRun(
            run_id=run.id,
            node_id="evaluation",
            node_type="evaluation",
            status="succeeded",
            output={
                "schema_version": "2",
                "evaluation_id": "H0001/T001@aaaaaaaa",
                "trial_id": "H0001/T001",
                "hypothesis_id": "H0001",
                "run_id": run.id,
                "status": "passed",
                "metrics": {"score": 0.5},
                "champion_metrics": {"score": 1.0},
                "deltas": {"score": -0.5},
                "primary_metric": "score",
                "direction": "minimize",
                "summary": "score improved vs champion",
                "signals": {"improved": ["score"], "regressed": [], "unchanged": []},
                "recommendation": "accept",
                "rationale": "beat baseline",
                "risks": "noise",
                "evidence": {
                    "candidate_commit": "a" * 40,
                    "evaluator_commit": "b" * 40,
                    "duration_seconds": 1.0,
                },
                "model": "composer-2.5",
                "system_prompt_hash": "abc",
                "created_at": datetime.now(UTC).isoformat(),
            },
            stdout="score improved vs champion",
            stderr="",
        )
    )
    session.commit()

    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.get(f"/api/projects/{project.id}/evaluations")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["recommendation"] == "accept"
    assert rows[0]["trial_id"] == "H0001/T001"
    assert rows[0]["primary_metric"] == "score"
