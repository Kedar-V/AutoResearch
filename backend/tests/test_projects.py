from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from autoresearch_api.projects import (
    ProjectError,
    create_project,
    github_status,
    resolve_github_owner,
)
from autoresearch_api.schemas import ProjectCreate

from .conftest import git


def test_resolve_github_owner_prefers_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("autoresearch_api.projects._gh_login", lambda: "cli-user")
    assert resolve_github_owner(configured_owner="env-user", override="req-user") == "req-user"
    assert resolve_github_owner(configured_owner="env-user", override=None) == "env-user"
    assert resolve_github_owner(configured_owner="", override=None) == "cli-user"


def test_resolve_github_owner_requires_gh_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("autoresearch_api.projects.shutil.which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr("autoresearch_api.projects._gh_login", lambda: None)
    with pytest.raises(ProjectError, match="gh auth login"):
        resolve_github_owner(configured_owner="")


def test_github_status_when_gh_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("autoresearch_api.projects.shutil.which", lambda _name: None)
    status = github_status(configured_owner="")
    assert status.gh_installed is False
    assert status.authenticated is False
    assert "brew install gh" in status.hint


def test_create_seed_project_local_only(session: Session, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    project = create_project(
        session,
        name="toy-seed",
        runtime_root=runtime,
        source="seed",
        create_github=False,
    )
    root = Path(project.local_path)
    assert project.github_url is None
    assert project.is_active is True
    assert (root / "score.txt").read_text(encoding="utf-8") == "5.0\n"
    assert git(root, "branch", "--show-current") == "master"


def test_create_seed_with_github_uses_gh_login(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "autoresearch_api.projects._create_github_repo",
        lambda name, *, owner: f"https://github.com/{owner}/{name}.git",
    )
    monkeypatch.setattr("autoresearch_api.projects._gh_login", lambda: "alice")
    monkeypatch.setattr("autoresearch_api.projects.shutil.which", lambda _name: "/usr/bin/gh")

    pushed: list[tuple[str, ...]] = []
    real_git = __import__("autoresearch_api.projects", fromlist=["_git"])._git

    def git_with_push_capture(path: Path, *args: str) -> str:
        if args and args[0] == "push":
            pushed.append(args)
            return ""
        return real_git(path, *args)

    monkeypatch.setattr("autoresearch_api.projects._git", git_with_push_capture)

    project = create_project(
        session,
        name="with-remote",
        runtime_root=tmp_path / "runtime",
        source="seed",
        create_github=True,
        github_owner="",
    )
    assert project.github_url == "https://github.com/alice/with-remote.git"
    assert any(args[0] == "push" for args in pushed)


def test_import_local_repository(session: Session, project_repo: Path, tmp_path: Path) -> None:
    project = create_project(
        session,
        name="imported",
        runtime_root=tmp_path / "runtime",
        source="local",
        local_path=str(project_repo),
        create_github=False,
    )
    assert Path(project.local_path).resolve() == project_repo.resolve()
    assert project.github_url is None


def test_import_local_rejects_non_git(session: Session, tmp_path: Path) -> None:
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    with pytest.raises(ProjectError, match="not a Git repository"):
        create_project(
            session,
            name="bad-local",
            runtime_root=tmp_path / "runtime",
            source="local",
            local_path=str(bare),
        )


def test_clone_git_repository(session: Session, project_repo: Path, tmp_path: Path) -> None:
    project = create_project(
        session,
        name="cloned",
        runtime_root=tmp_path / "runtime",
        source="git",
        git_url=str(project_repo),
        create_github=False,
    )
    root = Path(project.local_path)
    assert root.exists()
    assert root != project_repo
    assert (root / "score.txt").read_text(encoding="utf-8").strip() == "1"
    assert project.github_url == str(project_repo)


def test_project_create_schema_defaults() -> None:
    payload = ProjectCreate.model_validate({"name": "demo"})
    assert payload.source == "seed"
    assert payload.create_github is False
