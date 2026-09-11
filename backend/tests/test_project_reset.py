from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from autoresearch_api.database import get_session
from autoresearch_api.main import create_app
from autoresearch_api.models import (
    ChatSummary,
    HypothesisRecord,
    Project,
    Run,
    TrialRecord,
    Workflow,
)
from autoresearch_api.project_reset import wipe_local_git_experiments

from .conftest import git


def _seed_experiment_repo(repo: Path) -> None:
    git(repo, "checkout", "-b", "hypothesis/H0001-bump")
    (repo / "score.txt").write_text("0.5\n", encoding="utf-8")
    git(repo, "add", "score.txt")
    git(repo, "commit", "-m", "hypo")
    git(repo, "checkout", "-b", "trial/H0001/T001")
    git(repo, "checkout", "master")
    git(repo, "tag", "accepted/H0001-T001")
    git(
        repo,
        "notes",
        "--ref=research/hypotheses",
        "add",
        "-m",
        '{"id":"H0001"}',
        "HEAD",
    )
    (repo / "wip.txt").write_text("dirty\n", encoding="utf-8")


def test_wipe_local_git_keeps_champion_tip(project_repo: Path, tmp_path: Path) -> None:
    _seed_experiment_repo(project_repo)
    champion_before = git(project_repo, "rev-parse", "master")
    assert git(project_repo, "show", "master:score.txt") == "1"

    stats = wipe_local_git_experiments(
        project_repo,
        champion_branch="master",
        runtime_root=tmp_path / "runtime",
    )

    assert "hypothesis/H0001-bump" in stats.branches
    assert "trial/H0001/T001" in stats.branches
    assert "accepted/H0001-T001" in stats.tags
    assert git(project_repo, "rev-parse", "master") == champion_before
    assert git(project_repo, "show", "master:score.txt") == "1"
    assert git(project_repo, "branch", "--show-current") == "master"
    assert git(project_repo, "status", "--porcelain") == ""
    branches = git(project_repo, "branch")
    assert "hypothesis/" not in branches
    assert "trial/" not in branches
    assert git(project_repo, "tag", "-l", "accepted/*") == ""


def test_restart_project_endpoint_wipes_and_starts_run(
    session: Session, project_repo: Path, tmp_path: Path, monkeypatch
) -> None:
    from autoresearch_api.config import get_settings

    _seed_experiment_repo(project_repo)
    workflow_path = project_repo / "research-loop.json"
    from .test_workflow import research_recipe

    workflow_def = research_recipe().model_dump(mode="json")
    workflow_def["id"] = "bench-loop"
    workflow_def["name"] = "bench loop"
    workflow_path.write_text(json.dumps(workflow_def), encoding="utf-8")
    git(project_repo, "add", "research-loop.json")
    git(project_repo, "commit", "-m", "add loop")

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "briefs").mkdir()
    (runtime / "briefs" / "H0001-T001.md").write_text("brief\n", encoding="utf-8")
    (runtime / "worktrees" / "H0001" / "T001").mkdir(parents=True)

    project = Project(
        name="bench",
        local_path=str(project_repo),
        pg_schema="proj_bench",
        status="active",
        is_active=True,
    )
    session.add(project)
    session.flush()
    session.add(
        HypothesisRecord(
            id=f"{project.id}:H0001",
            project_id=project.id,
            title="bump",
            description="d",
            branch="hypothesis/H0001-bump",
            status="open",
        )
    )
    session.add(
        TrialRecord(
            id=f"{project.id}:H0001/T001",
            project_id=project.id,
            hypothesis_id=f"{project.id}:H0001",
            branch="trial/H0001/T001",
            outcome="accepted",
        )
    )
    old_run = Run(workflow_id="bench-loop", project_id=project.id, status="failed")
    session.add(
        Workflow(
            id="bench-loop",
            name="bench loop",
            description="",
            definition=workflow_def,
            project_id=project.id,
        )
    )
    session.add(old_run)
    session.add(ChatSummary(project_id=project.id, summary="old"))
    session.commit()

    get_settings.cache_clear()
    monkeypatch.setenv("AUTORESEARCH_RUNTIME_ROOT", str(runtime))
    monkeypatch.setenv("AUTORESEARCH_CHAMPION_BRANCH", "master")
    get_settings.cache_clear()

    app = create_app()

    def override_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_session
    # Background worker uses SessionLocal (separate engine); skip real execution here.
    monkeypatch.setattr("autoresearch_api.api._execute_run", lambda _run_id: None)

    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project.id}/restart")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project"]["id"] == project.id
    assert payload["run"]["workflow_id"] == "bench-loop"
    assert payload["run"]["status"] == "queued"
    assert payload["wiped"]["runs"] >= 1
    assert any(b.startswith("hypothesis/") for b in payload["wiped"]["branches"])

    session.expire_all()
    assert session.scalars(select(HypothesisRecord)).all() == []
    assert session.scalars(select(TrialRecord)).all() == []
    runs = list(session.scalars(select(Run).where(Run.project_id == project.id)))
    assert len(runs) == 1
    assert runs[0].id == payload["run"]["id"]
    summary = session.scalar(select(ChatSummary).where(ChatSummary.project_id == project.id))
    assert summary is not None
    assert "Restarted" in summary.summary
    assert git(project_repo, "show", "master:score.txt") == "1"
    assert not (runtime / "briefs" / "H0001-T001.md").exists()
    assert not (runtime / "worktrees" / "H0001").exists()
