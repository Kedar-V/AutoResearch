from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from autoresearch_api.executor import WorkflowExecutor
from autoresearch_api.git_service import GitService
from autoresearch_api.models import Project, Run, Workflow
from autoresearch_api.runner import LocalRunner

from .conftest import git


def workflow_definition(
    workflow_id: str,
    *,
    candidate_score: float | None = None,
    baseline: float,
    modify_evaluator: bool = False,
    max_retries: int = 1,
    max_hypotheses: int = 1,
    script: str | None = None,
) -> dict:
    if script is None:
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
            "config": {
                "title": f"Improve score to {candidate_score}",
                "max_retries": max_retries,
                "max_hypotheses": max_hypotheses,
                "history_window": 10,
                "system_prompt": (
                    "Produce a concrete score.txt change plan. "
                    "Use recent what_worked / what_did_not."
                ),
            },
        },
        {
            "id": "execution",
            "type": "execution",
            "name": "Change score",
            "position": {"x": 400, "y": 0},
            "config": {"command": [sys.executable, "-c", script]},
        },
        {
            "id": "eval_script",
            "type": "eval_script",
            "name": "Evaluate",
            "position": {"x": 400, "y": 180},
            "config": {"command": [sys.executable, "-c", evaluator]},
        },
        {
            "id": "evaluation",
            "type": "evaluation",
            "name": "Evaluation agent",
            "position": {"x": 600, "y": 0},
            "config": {"use_agent": False},
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
            {"id": "hypothesis-to-execution", "source": "hypothesis", "target": "execution"},
            {"id": "execution-to-eval-script", "source": "execution", "target": "eval_script"},
            {"id": "execution-to-evaluation", "source": "execution", "target": "evaluation"},
            {"id": "eval-to-evaluation", "source": "eval_script", "target": "evaluation"},
            {"id": "evaluation-to-gate", "source": "evaluation", "target": "gate"},
            {"id": "gate-to-decision", "source": "gate", "target": "decision"},
            {"id": "execution-to-hypothesis", "source": "execution", "target": "hypothesis"},
            {"id": "decision-to-hypothesis", "source": "decision", "target": "hypothesis"},
        ],
    }


def execute(
    session: Session,
    project_repo: Path,
    runtime_root: Path,
    definition: dict,
) -> Run:
    project = Project(
        name=f"proj-{definition['id']}",
        local_path=str(project_repo),
        pg_schema=f"proj_{definition['id'].replace('-', '_')}",
        is_active=True,
    )
    session.add(project)
    session.flush()
    workflow = Workflow(
        id=definition["id"],
        name=definition["name"],
        description="",
        definition=definition,
        project_id=project.id,
    )
    run = Run(workflow_id=workflow.id, project_id=project.id)
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

    evaluation_runs = [item for item in run.node_runs if item.node_type == "evaluation"]
    assert evaluation_runs
    output = evaluation_runs[0].output
    assert output["schema_version"] == "2"
    assert output["recommendation"] == "accept"
    assert output["primary_metric"] == "score"
    assert output["hypothesis_id"] == "H0001"
    note = GitService(project_repo, tmp_path / "runtime", "master").read_note(
        "research/evaluations", output["evidence"]["candidate_commit"]
    )
    assert note is not None
    assert note["schema_version"] == "2"
    assert note["recommendation"] == "accept"


def test_dirty_champion_blocks_accept_without_accepted_ledger(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    (project_repo / "wip.txt").write_text("uncommitted champion edit\n", encoding="utf-8")

    run = execute(
        session,
        project_repo,
        tmp_path / "runtime-dirty",
        workflow_definition("dirty-champion-flow", candidate_score=0.5, baseline=1.0),
    )

    assert run.status == "failed"
    assert "champion worktree must be clean before promotion" in (run.error or "")
    assert "wip.txt" in (run.error or "")
    assert git(project_repo, "tag", "--list", "accepted/*") == ""
    assert git(project_repo, "show", "master:score.txt") == "1"
    assert "Merge accepted AutoResearch trial" not in git(
        project_repo, "log", "--oneline", "-5"
    )


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
    assert "rejected/H0001-T001" in git(project_repo, "tag", "--list", "rejected/*")


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
    assert "protected" in (run.error or "").lower()
    assert git(project_repo, "show", "master:eval.py") == "trusted"
    assert git(project_repo, "show", "master:score.txt") == "1"


def test_score_descends_across_five_hypotheses(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    (project_repo / "score.txt").write_text("5.0\n", encoding="utf-8")
    git(project_repo, "add", "score.txt")
    git(project_repo, "commit", "-m", "reset score")

    script = (
        "from pathlib import Path; "
        "path = Path('score.txt'); "
        "current = float(path.read_text()); "
        "path.write_text(f'{max(current - 1, 0)}\\n')"
    )
    run = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition(
            "descent-flow",
            baseline=5.0,
            max_retries=1,
            max_hypotheses=5,
            script=script,
        ),
    )

    assert run.status == "succeeded"
    assert git(project_repo, "show", "master:score.txt") == "0.0"
    tags = git(project_repo, "tag", "--list", "accepted/*")
    for index in range(1, 6):
        assert f"accepted/H{index:04d}-T001" in tags


def test_failed_execution_retries_until_runnable(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    script = "\n".join(
        [
            "import os, sys",
            "from pathlib import Path",
            "if int(os.environ['AUTORESEARCH_TRIAL_NUMBER']) < 2:",
            "    sys.exit('boom')",
            "Path('score.txt').write_text('0.5\\n', encoding='utf-8')",
        ]
    )
    run = execute(
        session,
        project_repo,
        tmp_path / "runtime",
        workflow_definition(
            "retry-flow",
            candidate_score=0.5,
            baseline=1.0,
            max_retries=3,
            script=script,
        ),
    )

    assert run.status == "succeeded"
    assert run.trial_id == "H0001/T002"
    trials = [node_run for node_run in run.node_runs if node_run.node_type == "trial"]
    assert [trial.output.get("outcome") for trial in trials] == ["failed", "ran"]
    assert git(project_repo, "show", "master:score.txt") == "0.5"


def test_next_hypothesis_brief_includes_prior_lessons(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    from sqlalchemy import select

    from autoresearch_api.models import HypothesisRecord

    script = (
        "from pathlib import Path; "
        "path = Path('score.txt'); "
        "current = float(path.read_text()); "
        "path.write_text(f'{max(current - 0.5, 0)}\\n')"
    )
    (project_repo / "score.txt").write_text("2.0\n", encoding="utf-8")
    git(project_repo, "add", "score.txt")
    git(project_repo, "commit", "-m", "reset for multi hypo")

    run = execute(
        session,
        project_repo,
        tmp_path / "runtime-multi",
        workflow_definition(
            "history-multi",
            baseline=2.0,
            max_hypotheses=2,
            script=script,
        ),
    )
    assert run.status == "succeeded"

    hypos = list(
        session.scalars(
            select(HypothesisRecord)
            .where(HypothesisRecord.project_id == run.project_id)
            .order_by(HypothesisRecord.created_at.asc())
        )
    )
    assert len(hypos) == 2
    assert hypos[0].what_worked
    assert "Accepted on score=" in hypos[0].what_worked
    assert "H0001" in hypos[1].description
    assert hypos[0].what_worked in hypos[1].description
    assert "What worked" in hypos[1].description
    assert "Required plan checklist" in hypos[1].description
    assert "Produce a concrete score.txt change plan" in hypos[1].description
    briefs = sorted((tmp_path / "runtime-multi" / "briefs").glob("*.md"))
    assert any(hypos[0].what_worked in path.read_text(encoding="utf-8") for path in briefs)
    h2_brief = next(path for path in briefs if path.name.startswith("H0002-"))
    assert hypos[0].what_worked in h2_brief.read_text(encoding="utf-8")
    assert "What worked" in h2_brief.read_text(encoding="utf-8")
