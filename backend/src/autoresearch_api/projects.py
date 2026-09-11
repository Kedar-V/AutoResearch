from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
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


@dataclass(frozen=True)
class GitHubStatus:
    gh_installed: bool
    authenticated: bool
    login: str | None
    configured_owner: str | None
    resolved_owner: str | None
    hint: str


def schema_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "project"
    return f"proj_{slug[:48]}"


def github_status(*, configured_owner: str = "") -> GitHubStatus:
    """Report whether GitHub CLI is ready for optional private-repo creation."""
    configured = configured_owner.strip() or None
    if shutil.which("gh") is None:
        return GitHubStatus(
            gh_installed=False,
            authenticated=False,
            login=None,
            configured_owner=configured,
            resolved_owner=None,
            hint=(
                "Install GitHub CLI, then authenticate:\n"
                "  brew install gh   # or https://cli.github.com\n"
                "  gh auth login -h github.com -p https -w"
            ),
        )
    login = _gh_login()
    if login is None:
        return GitHubStatus(
            gh_installed=True,
            authenticated=False,
            login=None,
            configured_owner=configured,
            resolved_owner=None,
            hint=(
                "GitHub CLI is installed but not logged in. Connect your account:\n"
                "  gh auth login -h github.com -p https -w\n"
                "Then re-check status (or refresh New Project)."
            ),
        )
    owner = configured or login
    return GitHubStatus(
        gh_installed=True,
        authenticated=True,
        login=login,
        configured_owner=configured,
        resolved_owner=owner,
        hint=(
            f"Connected as {login}. "
            f"New private repos will use owner {owner!r}."
            + (
                f" (override with AUTORESEARCH_GITHUB_OWNER; currently {configured!r})"
                if configured and configured != login
                else ""
            )
        ),
    )


def resolve_github_owner(*, configured_owner: str = "", override: str | None = None) -> str:
    """Resolve the GitHub owner for repo creation.

    Prefer explicit override, then AUTORESEARCH_GITHUB_OWNER, then `gh` login.
    Never fall back to a hardcoded personal account.
    """
    for candidate in (override, configured_owner):
        if candidate and candidate.strip():
            return candidate.strip()
    status = github_status(configured_owner=configured_owner)
    if not status.gh_installed:
        raise ProjectError(status.hint)
    if not status.authenticated or not status.login:
        raise ProjectError(status.hint)
    return status.login


def create_project(
    session: Session,
    *,
    name: str,
    runtime_root: Path,
    source: str = "seed",
    create_github: bool = False,
    github_owner: str = "",
    github_owner_override: str | None = None,
    local_path: str | None = None,
    git_url: str | None = None,
    champion_branch: str = "master",
) -> Project:
    if session.scalar(select(Project).where(Project.name == name)):
        raise ProjectError(f"project {name!r} already exists")

    source = (source or "seed").strip().lower()
    if source not in {"seed", "local", "git"}:
        raise ProjectError("source must be one of: seed, local, git")

    if source == "seed":
        path = _create_seed_repo(runtime_root, name)
        github_url = None
        if create_github:
            owner = resolve_github_owner(
                configured_owner=github_owner,
                override=github_owner_override,
            )
            github_url = _create_github_repo(name, owner=owner)
            _git(path, "remote", "add", "origin", github_url)
            _git(path, "push", "-u", "origin", champion_branch)
    elif source == "local":
        if not local_path or not local_path.strip():
            raise ProjectError("local_path is required when source=local")
        path = _import_local_repo(Path(local_path.strip()), champion_branch=champion_branch)
        github_url = _origin_url(path)
        if create_github and not github_url:
            owner = resolve_github_owner(
                configured_owner=github_owner,
                override=github_owner_override,
            )
            github_url = _create_github_repo(name, owner=owner)
            _git(path, "remote", "add", "origin", github_url)
            _ensure_branch(path, champion_branch)
            _git(path, "push", "-u", "origin", champion_branch)
    elif source == "git":
        if not git_url or not git_url.strip():
            raise ProjectError("git_url is required when source=git")
        path = _clone_repo(runtime_root, name, git_url.strip(), champion_branch=champion_branch)
        github_url = git_url.strip()
        if create_github:
            raise ProjectError(
                "create_github is not used with source=git — the clone already has a remote"
            )
    else:  # pragma: no cover
        raise ProjectError(f"unsupported source {source!r}")

    return _register_project(
        session,
        name=name,
        local_path=path,
        github_url=github_url,
        summary=_creation_summary(name, source=source, github_url=github_url),
    )


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


def _creation_summary(name: str, *, source: str, github_url: str | None) -> str:
    if source == "seed":
        base = f"Created toy seed project {name}."
    elif source == "local":
        base = f"Imported local repository as project {name}."
    else:
        base = f"Cloned remote repository as project {name}."
    if github_url:
        return f"{base} Remote: {github_url}"
    return f"{base} Local only (no GitHub remote)."


def _register_project(
    session: Session,
    *,
    name: str,
    local_path: Path,
    github_url: str | None,
    summary: str,
) -> Project:
    pg_schema = schema_name(name)
    session.execute(update(Project).values(is_active=False))
    project = Project(
        name=name,
        github_url=github_url,
        local_path=str(local_path.resolve()),
        pg_schema=pg_schema,
        status="active",
        is_active=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(project)
    session.flush()
    session.add(ChatSummary(project_id=project.id, summary=summary))
    session.commit()
    session.refresh(project)

    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        session.execute(select(1))
        session.connection().exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{pg_schema}"')
        session.commit()
    return project


def _create_seed_repo(runtime_root: Path, name: str) -> Path:
    local_path = (runtime_root / "projects" / name).resolve()
    if local_path.exists():
        raise ProjectError(f"local path already exists: {local_path}")
    local_path.mkdir(parents=True)
    _init_git_repo(local_path)
    for filename, contents in MATH_SEED.items():
        (local_path / filename).write_text(contents, encoding="utf-8")
    _git(local_path, "add", "-A")
    _git(local_path, "commit", "-m", "Initialize AutoResearch math fixture")
    return local_path


def _import_local_repo(path: Path, *, champion_branch: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise ProjectError(f"local_path is not a directory: {resolved}")
    _verify_git_root(resolved)
    _ensure_branch(resolved, champion_branch)
    return resolved


def _clone_repo(
    runtime_root: Path,
    name: str,
    git_url: str,
    *,
    champion_branch: str,
) -> Path:
    local_path = (runtime_root / "projects" / name).resolve()
    if local_path.exists():
        raise ProjectError(f"local path already exists: {local_path}")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", git_url, str(local_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise ProjectError(f"git clone failed: {message}")
    _verify_git_root(local_path)
    _ensure_branch(local_path, champion_branch)
    return local_path


def _verify_git_root(path: Path) -> None:
    try:
        inside = _git(path, "rev-parse", "--is-inside-work-tree")
        toplevel = Path(_git(path, "rev-parse", "--show-toplevel")).resolve()
    except ProjectError as exc:
        raise ProjectError(f"{path} is not a Git repository: {exc}") from exc
    if inside != "true" or toplevel != path.resolve():
        raise ProjectError(
            f"{path} must be a Git repository root (found {toplevel}). "
            "Point local_path at the repo root, not a subdirectory."
        )


def _ensure_branch(path: Path, champion_branch: str) -> None:
    current = _git(path, "branch", "--show-current")
    branches = {
        line.lstrip("* ").strip()
        for line in _git(path, "branch", "--list").splitlines()
        if line.strip()
    }
    if champion_branch in branches:
        if current != champion_branch:
            _git(path, "checkout", champion_branch)
        return
    # Common rename: imported repos often use main.
    if champion_branch == "master" and "main" in branches:
        _git(path, "checkout", "main")
        _git(path, "branch", "-M", "master")
        return
    if champion_branch == "main" and "master" in branches:
        _git(path, "checkout", "master")
        _git(path, "branch", "-M", "main")
        return
    if current:
        _git(path, "branch", "-M", champion_branch)
        return
    raise ProjectError(
        f"repository has no {champion_branch!r} branch "
        f"(and no main/master to rename). Create one, then retry."
    )


def _origin_url(path: Path) -> str | None:
    try:
        url = _git(path, "remote", "get-url", "origin")
    except ProjectError:
        return None
    return url or None


def _create_github_repo(name: str, *, owner: str) -> str:
    if shutil.which("gh") is None:
        raise ProjectError(
            "GitHub CLI (gh) is not installed; run `brew install gh` "
            "then `gh auth login -h github.com -p https -w`"
        )
    auth = subprocess.run(
        ["gh", "auth", "status"],
        text=True,
        capture_output=True,
        check=False,
    )
    if auth.returncode:
        raise ProjectError(
            "GitHub CLI is not authenticated. Connect your account:\n"
            "  gh auth login -h github.com -p https -w"
        )
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
                f"Run `gh auth login` as that user/org, or set "
                f"AUTORESEARCH_GITHUB_OWNER to an account you can write to."
            )
        raise ProjectError(f"could not create GitHub repo: {message}")
    url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not url.startswith("http"):
        url = f"https://github.com/{full_name}.git"
    return url if url.endswith(".git") else f"{url}.git"


def _gh_login() -> str | None:
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    login = result.stdout.strip()
    return login or None


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
