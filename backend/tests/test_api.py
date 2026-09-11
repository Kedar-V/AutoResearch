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
