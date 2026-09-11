from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import ChatSummary, Project, utcnow


class ProjectError(RuntimeError):
    pass


MATH_SEED = {
    "score.txt": "5.0\n",
    "train.py": (
        "from pathlib import Path\n"
        "\n"
        "path = Path('score.txt')\n"
        "current = float(path.read_text(encoding='utf-8'))\n"
        "path.write_text(f'{max(current - 1, 0)}\\n', encoding='utf-8')\n"
    ),
    "eval.py": (
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "score = float(Path('score.txt').read_text(encoding='utf-8'))\n"
        "print(json.dumps({'metrics': {'score': score}}))\n"
    ),
    "README.md": "# AutoResearch project\n\nMinimize score.txt from 5.0 toward 0.\n",
}


def schema_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"
    return f"proj_{slug[:48]}"


def create_project(
    session: Session,
    *,
    name: str,
    runtime_root: Path,
    create_github: bool = True,
    github_owner: str = "Kedar-V",
) -> Project:
    if session.scalar(select(Project).where(Project.name == name)):
        raise ProjectError(f"project {name!r} already exists")

    local_path = (runtime_root / "projects" / name).resolve()
    if local_path.exists():
        raise ProjectError(f"local path already exists: {local_path}")
    local_path.mkdir(parents=True)

    github_url: str | None = None
    if create_github:
        github_url = _create_github_repo(name, owner=github_owner)

    _init_git_repo(local_path)
    for filename, contents in MATH_SEED.items():
        (local_path / filename).write_text(contents, encoding="utf-8")
    _git(local_path, "add", "-A")
    _git(local_path, "commit", "-m", "Initialize AutoResearch math fixture")
    if github_url:
        _git(local_path, "remote", "add", "origin", github_url)
        _git(local_path, "push", "-u", "origin", "master")

    pg_schema = schema_name(name)
    session.execute(update(Project).values(is_active=False))
    project = Project(
        name=name,
        github_url=github_url,
        local_path=str(local_path),
        pg_schema=pg_schema,
        status="active",
        is_active=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(project)
    session.flush()
    session.add(ChatSummary(project_id=project.id, summary=f"Created project {name}."))
    session.commit()
    session.refresh(project)

    # Best-effort Postgres schema isolation when connected to Postgres.
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(select(1))  # keep session alive
        session.connection().exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{pg_schema}"')
        session.commit()
    return project


def active_project(session: Session) -> Project | None:
    return session.scalar(select(Project).where(Project.is_active.is_(True)))


def set_active_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectError("project not found")
    session.execute(update(Project).values(is_active=False))
    project.is_active = True
    project.updated_at = utcnow()
    session.commit()
    session.refresh(project)
    return project


def _create_github_repo(name: str, *, owner: str = "Kedar-V") -> str:
    if shutil.which("gh") is None:
        raise ProjectError("GitHub CLI (gh) is not installed; run brew install gh")
    auth = subprocess.run(
        ["gh", "auth", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    if auth.returncode:
        raise ProjectError("GitHub CLI is not authenticated; run gh auth login")
    full_name = f"{owner}/{name}"
    result = subprocess.run(
        ["gh", "repo", "create", full_name, "--private", "--confirm"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        if "cannot create a repository for" in message.lower():
            raise ProjectError(
                f"GitHub CLI cannot create repos under {owner!r}. "
                f"Run `gh auth login` as {owner}, then retry."
            )
        raise ProjectError(f"could not create GitHub repo: {message}")
    url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not url.startswith("http"):
        url = f"https://github.com/{full_name}.git"
    return url if url.endswith(".git") else f"{url}.git"


def _init_git_repo(path: Path) -> None:
    _git(path, "init", "-b", "master")
    _git(path, "config", "user.name", "AutoResearch")
    _git(path, "config", "user.email", "autoresearch@local")


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ProjectError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()
