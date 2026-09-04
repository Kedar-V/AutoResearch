from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrialWorkspace:
    hypothesis_id: str
    trial_id: str
    hypothesis_branch: str
    trial_branch: str
    path: Path


class GitService:
    def __init__(self, project_root: Path, runtime_root: Path, champion_branch: str) -> None:
        self.project_root = project_root.resolve()
        self.runtime_root = runtime_root.resolve()
        self.champion_branch = champion_branch

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.project_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip()
            raise GitError(f"git {' '.join(args)} failed: {message}")
        return result.stdout.strip()

    def verify_repository(self) -> None:
        if self._git("rev-parse", "--is-inside-work-tree") != "true":
            raise GitError(f"{self.project_root} is not a Git worktree")
        self._git("rev-parse", "--verify", self.champion_branch)

    def head(self, ref: str = "HEAD", cwd: Path | None = None) -> str:
        return self._git("rev-parse", ref, cwd=cwd)

    def is_clean(self, cwd: Path | None = None) -> bool:
        return not self._git("status", "--porcelain", cwd=cwd)

    def create_hypothesis(
        self, hypothesis_id: str, title: str, description: str
    ) -> tuple[str, str]:
        slug = self._slug(title)
        branch = f"hypothesis/{hypothesis_id}-{slug}"
        base_commit = self.head(self.champion_branch)
        tree = self._git("rev-parse", f"{base_commit}^{{tree}}")
        hypothesis_commit = self._git(
            "commit-tree",
            tree,
            "-p",
            base_commit,
            "-m",
            f"research(hypothesis): {title}",
        )
        self._git("branch", branch, hypothesis_commit)
        record = {
            "schema_version": "1",
            "id": hypothesis_id,
            "title": title,
            "description": description,
            "base_commit": base_commit,
            "branch": branch,
            "hypothesis_commit": hypothesis_commit,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.add_note("research/hypotheses", hypothesis_commit, record)
        return branch, base_commit

    def create_trial(
        self, hypothesis_id: str, trial_number: int, hypothesis_branch: str
    ) -> TrialWorkspace:
        trial_id = f"{hypothesis_id}/T{trial_number:03d}"
        trial_branch = f"trial/{hypothesis_id}/T{trial_number:03d}"
        path = self.runtime_root / "worktrees" / hypothesis_id / f"T{trial_number:03d}"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-b", trial_branch, str(path), hypothesis_branch)
        return TrialWorkspace(
            hypothesis_id=hypothesis_id,
            trial_id=trial_id,
            hypothesis_branch=hypothesis_branch,
            trial_branch=trial_branch,
            path=path,
        )

    def commit_changes(self, workspace: TrialWorkspace, message: str) -> str:
        self._git("add", "-A", cwd=workspace.path)
        if self.is_clean(workspace.path):
            return self.head(cwd=workspace.path)
        self._git("commit", "-m", message, cwd=workspace.path)
        return self.head(cwd=workspace.path)

    def add_note(self, ref: str, commit: str, record: dict[str, Any]) -> None:
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        self._git("notes", f"--ref={ref}", "add", "-f", "-m", payload, commit)

    def read_note(self, ref: str, commit: str) -> dict[str, Any] | None:
        try:
            payload = self._git("notes", f"--ref={ref}", "show", commit)
        except GitError:
            return None
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise GitError(f"note {ref} on {commit} must contain a JSON object")
        return value

    def assert_paths_unchanged(
        self, base_commit: str, candidate_commit: str, protected_paths: list[str]
    ) -> None:
        if not protected_paths:
            return
        changed = self._git(
            "diff",
            "--name-only",
            base_commit,
            candidate_commit,
            "--",
            *protected_paths,
        )
        if changed:
            raise GitError(f"candidate modified protected paths: {', '.join(changed.splitlines())}")

    def record_champion(self, commit: str, record: dict[str, Any]) -> None:
        self.add_note("research/champions", commit, record)

    def tag_decision(self, outcome: str, trial_id: str, commit: str) -> str:
        safe_trial = trial_id.replace("/", "-")
        tag = f"{outcome}/{safe_trial}"
        self._git("tag", "-f", tag, commit)
        return tag

    def merge_trial(self, trial_branch: str, hypothesis_base_commit: str) -> str:
        current_branch = self._git("branch", "--show-current")
        if current_branch != self.champion_branch:
            raise GitError(
                f"project root must be on {self.champion_branch!r}, found {current_branch!r}"
            )
        if not self.is_clean():
            raise GitError("champion worktree must be clean before promotion")
        if self.head(self.champion_branch) != hypothesis_base_commit:
            raise GitError("champion advanced; candidate must be rebased and re-evaluated")
        self._git(
            "merge",
            "--no-ff",
            trial_branch,
            "-m",
            f"Merge accepted AutoResearch trial {trial_branch}",
        )
        return self.head(self.champion_branch)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return (slug or "idea")[:48]
