"""Wipe experiment ledger/Git refs for a project while keeping champion code."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .models import (
    ChatMessage,
    ChatSummary,
    HypothesisRecord,
    Metric,
    NodeRun,
    Project,
    Run,
    TrialRecord,
    Workflow,
    utcnow,
)
from .schemas import WorkflowDefinition


class ProjectResetError(RuntimeError):
    pass


@dataclass
class WipeStats:
    branches: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    runs: int = 0


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise ProjectResetError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.strip()


def wipe_local_git_experiments(repo: Path, *, champion_branch: str, runtime_root: Path) -> WipeStats:
    """Remove worktrees, experiment branches/tags/notes; leave champion tip intact."""
    stats = WipeStats()
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise ProjectResetError(f"not a git repository: {repo}")

    # Linked worktrees (except the champion root)
    listed = _git(repo, "worktree", "list", "--porcelain", check=False)
    for line in listed.splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.split(" ", 1)[1])
        if path.resolve() == repo:
            continue
        with contextlib.suppress(ProjectResetError):
            _git(repo, "worktree", "remove", "--force", str(path))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    _git(repo, "worktree", "prune", check=False)

    # Runtime worktrees + briefs (shared runtime root)
    wt_root = runtime_root / "worktrees"
    if wt_root.exists():
        for child in wt_root.glob("H*"):
            shutil.rmtree(child, ignore_errors=True)
    briefs = runtime_root / "briefs"
    if briefs.exists():
        for path in briefs.glob("H*.md"):
            path.unlink(missing_ok=True)

    branches = _git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads/hypothesis",
        "refs/heads/trial",
        check=False,
    )
    for branch in [b for b in branches.splitlines() if b]:
        with contextlib.suppress(ProjectResetError):
            _git(repo, "branch", "-D", branch)
            stats.branches.append(branch)

    tags = _git(repo, "tag", "-l", "accepted/*", "rejected/*", "failed/*", check=False)
    for tag in [t for t in tags.splitlines() if t]:
        with contextlib.suppress(ProjectResetError):
            _git(repo, "tag", "-d", tag)
            stats.tags.append(tag)

    for ref in (
        "research/hypotheses",
        "research/decisions",
        "research/evaluations",
        "research/champions",
    ):
        notes = _git(repo, "notes", f"--ref={ref}", "list", check=False)
        for line in notes.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            commit = parts[1]
            _git(repo, "notes", f"--ref={ref}", "remove", "--ignore-missing", commit, check=False)

    # Champion working tree: keep current tip, drop dirt
    current = _git(repo, "branch", "--show-current", check=False)
    if current != champion_branch:
        _git(repo, "checkout", champion_branch)
    _git(repo, "reset", "--hard", "HEAD")
    _git(repo, "clean", "-fd")
    return stats


def wipe_remote_git_experiments(repo: Path) -> WipeStats:
    """Best-effort delete of remote hypothesis/trial branches and decision tags."""
    stats = WipeStats()
    remotes = _git(repo, "remote", check=False)
    if "origin" not in remotes.splitlines():
        return stats
    _git(repo, "fetch", "origin", "--prune", check=False)

    heads = _git(repo, "ls-remote", "--heads", "origin", "hypothesis/*", "trial/*", check=False)
    for line in heads.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        if not ref.startswith("refs/heads/"):
            continue
        branch = ref.removeprefix("refs/heads/")
        result = subprocess.run(
            ["git", "push", "origin", "--delete", branch],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            stats.branches.append(branch)

    tags = _git(
        repo, "ls-remote", "--tags", "origin", "accepted/*", "rejected/*", "failed/*", check=False
    )
    seen: set[str] = set()
    for line in tags.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ref = parts[1].removesuffix("^{}")
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref.removeprefix("refs/tags/")
        if tag in seen:
            continue
        seen.add(tag)
        result = subprocess.run(
            ["git", "push", "origin", "--delete", f"refs/tags/{tag}"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            stats.tags.append(tag)

    # Drop any tags fetch recreated locally
    local_tags = _git(repo, "tag", "-l", "accepted/*", "rejected/*", "failed/*", check=False)
    for tag in [t for t in local_tags.splitlines() if t]:
        _git(repo, "tag", "-d", tag, check=False)
    return stats


def wipe_project_database(session: Session, project_id: str) -> int:
    """Delete project-scoped control-plane rows. Returns number of runs removed."""
    run_ids = list(session.scalars(select(Run.id).where(Run.project_id == project_id)))
    if run_ids:
        session.execute(delete(NodeRun).where(NodeRun.run_id.in_(run_ids)))
        session.execute(
            delete(Metric).where(
                or_(Metric.project_id == project_id, Metric.run_id.in_(run_ids))
            )
        )
    else:
        session.execute(delete(Metric).where(Metric.project_id == project_id))

    session.execute(delete(TrialRecord).where(TrialRecord.project_id == project_id))
    session.execute(delete(HypothesisRecord).where(HypothesisRecord.project_id == project_id))
    session.execute(delete(ChatMessage).where(ChatMessage.project_id == project_id))
    session.execute(delete(ChatSummary).where(ChatSummary.project_id == project_id))
    if run_ids:
        session.execute(delete(Run).where(Run.id.in_(run_ids)))
    return len(run_ids)


def upsert_restart_chat_summary(session: Session, project: Project) -> None:
    summary = session.scalar(
        select(ChatSummary).where(ChatSummary.project_id == project.id)
    )
    text = f"Restarted project {project.name}."
    if summary is None:
        session.add(ChatSummary(project_id=project.id, summary=text, updated_at=utcnow()))
    else:
        summary.summary = text
        summary.updated_at = utcnow()


def load_research_loop_workflow(project: Project) -> WorkflowDefinition | None:
    path = Path(project.local_path) / "research-loop.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowDefinition.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ProjectResetError(f"invalid research-loop.json: {exc}") from exc


def ensure_workflow_from_definition(
    session: Session, definition: WorkflowDefinition, project: Project
) -> Workflow:
    now = utcnow()
    workflow = session.get(Workflow, definition.id)
    payload = definition.model_dump(mode="json")
    if workflow is None:
        workflow = Workflow(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            definition=payload,
            project_id=project.id,
            created_at=now,
            updated_at=now,
        )
        session.add(workflow)
    else:
        workflow.name = definition.name
        workflow.description = definition.description
        workflow.definition = payload
        workflow.project_id = project.id
        workflow.updated_at = now
    session.flush()
    return workflow


def resolve_restart_workflow_id(session: Session, project: Project) -> str:
    """Prefer research-loop.json, else existing {name}-loop, else any project workflow."""
    definition = load_research_loop_workflow(project)
    if definition is not None:
        ensure_workflow_from_definition(session, definition, project)
        return definition.id

    preferred = f"{project.name}-loop"
    if session.get(Workflow, preferred) is not None:
        return preferred

    existing = session.scalar(
        select(Workflow).where(Workflow.project_id == project.id).order_by(Workflow.updated_at.desc())
    )
    if existing is not None:
        return existing.id
    raise ProjectResetError(
        f"no workflow found for project {project.name!r}; "
        "add research-loop.json or save a workflow first"
    )


def merge_wipe_stats(*parts: WipeStats) -> WipeStats:
    merged = WipeStats()
    for part in parts:
        merged.branches.extend(part.branches)
        merged.tags.extend(part.tags)
        merged.runs += part.runs
    return merged


def wiped_payload(stats: WipeStats) -> dict[str, Any]:
    return {
        "branches": list(stats.branches),
        "tags": list(stats.tags),
        "runs": stats.runs,
    }
