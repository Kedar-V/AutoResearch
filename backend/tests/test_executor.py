from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from autoresearch_api.executor import WorkflowExecutor
from autoresearch_api.git_service import GitService
from autoresearch_api.models import Run, Workflow
from autoresearch_api.runner import LocalRunner

from .conftest import git


def workflow_definition(
    workflow_id: str,
    *,
    candidate_score: float,
    baseline: float,
    modify_evaluator: bool = False,
) -> dict:
    script = (
        "from pathlib import Path; "
        f"Path('score.txt').write_text('{candidate_score}\\n', encoding='utf-8')"
    )
    if modify_evaluator:
        script += "; Path('eval.py').write_text('tampered\\n', encoding='utf-8')"
    evaluator = (
        "import json; from pathlib import Path; "
        "score=float(Path('score.txt').read_text()); "
        "print(json.dumps({'metrics': {'score': score}}))"
    )
    nodes = [
        {
            "id": "hypothesis",
            "type": "hypothesis",
            "name": "Improve score",
            "position": {"x": 0, "y": 0},
            "config": {"title": f"Improve score to {candidate_score}"},
        },
        {
            "id": "trial",
            "type": "trial",
            "name": "Trial",
            "position": {"x": 200, "y": 0},
            "config": {"number": 1},
        },
        {
            "id": "script",
            "type": "script",
            "name": "Change score",
            "position": {"x": 400, "y": 0},
            "config": {"command": [sys.executable, "-c", script]},
        },
        {
            "id": "evaluation",
            "type": "evaluation",
            "name": "Evaluate",
            "position": {"x": 600, "y": 0},
            "config": {"command": [sys.executable, "-c", evaluator]},
        },
        {
            "id": "gate",
            "type": "metric_gate",
            "name": "Gate",
            "position": {"x": 800, "y": 0},
            "config": {
                "metric": "score",
                "direction": "minimize",
                "baseline": baseline,
                "min_delta": 0.01,
            },
        },
        {
            "id": "decision",
            "type": "git_decision",
            "name": "Decide",
            "position": {"x": 1000, "y": 0},
            "config": {},
        },
    ]
    return {
        "schema_version": "1",
        "id": workflow_id,
        "name": workflow_id,
        "nodes": nodes,
        "edges": [
            {"id": f"edge-{index}", "source": source, "target": target}
            for index, (source, target) in enumerate(
                zip(
                    ["hypothesis", "trial", "script", "evaluation", "gate"],
                    ["trial", "script", "evaluation", "gate", "decision"],
                    strict=True,
                )
            )
        ],
    }


def execute(
    session: Session,
    project_repo: Path,
    runtime_root: Path,
    definition: dict,
) -> Run:
    workflow = Workflow(
        id=definition["id"],
        name=definition["name"],
        description="",
        definition=definition,
    )
    run = Run(workflow_id=workflow.id)
    session.add_all([workflow, run])
    session.commit()
    executor = WorkflowExecutor(
        GitService(project_repo, runtime_root, "master"),
        LocalRunner(default_timeout_seconds=10),
    )
    return executor.execute(session, run.id)


def test_accepted_trial_merges_and_records_champion(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    run = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition("accepted-flow", candidate_score=0.5, baseline=1.0),
    )

    assert run.status == "succeeded"
    assert run.hypothesis_id == "H0001"
    assert run.trial_id == "H0001/T001"
    assert git(project_repo, "show", "master:score.txt") == "0.5"
    champion = GitService(project_repo, tmp_path / "runtime", "master").read_note(
        "research/champions", git(project_repo, "rev-parse", "master")
    )
    assert champion is not None
    assert champion["metrics"] == {"score": 0.5}
    assert git(project_repo, "tag", "--list", "accepted/*") == "accepted/H0001-T001"


def test_current_champion_metric_overrides_stale_configured_baseline(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    first = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition("first-flow", candidate_score=0.5, baseline=1.0),
    )
    assert first.status == "succeeded"

    second = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition("second-flow", candidate_score=0.75, baseline=10.0),
    )

    assert second.status == "succeeded"
    assert git(project_repo, "show", "master:score.txt") == "0.5"
    assert git(project_repo, "tag", "--list", "rejected/*") == "rejected/H0002-T001"


def test_candidate_cannot_modify_protected_evaluator(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    (project_repo / "eval.py").write_text("trusted\n", encoding="utf-8")
    git(project_repo, "add", "eval.py")
    git(project_repo, "commit", "-m", "add evaluator")

    run = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition(
            "protected-flow",
            candidate_score=0.5,
            baseline=1.0,
            modify_evaluator=True,
        ),
    )

    assert run.status == "failed"
    assert "modified protected paths: eval.py" in (run.error or "")
    assert git(project_repo, "show", "master:eval.py") == "trusted"
