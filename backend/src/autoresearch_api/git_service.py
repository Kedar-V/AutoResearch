from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
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

    def _git(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.project_root,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            input=input_text,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip()
            raise GitError(f"git {' '.join(args)} failed: {message}")
        return result.stdout.strip()

    def verify_repository(self) -> None:
        if self._git("rev-parse", "--is-inside-work-tree") != "true":
            raise GitError(f"{self.project_root} is not a Git worktree")
        toplevel = Path(self._git("rev-parse", "--show-toplevel")).resolve()
        if toplevel != self.project_root:
            raise GitError(
                f"{self.project_root} is not a Git repository root (found {toplevel}). "
                "Initialize the target project with its own .git."
            )
        self._git("rev-parse", "--verify", self.champion_branch)

    def head(self, ref: str = "HEAD", cwd: Path | None = None) -> str:
        return self._git("rev-parse", ref, cwd=cwd)

    def is_clean(self, cwd: Path | None = None) -> bool:
        return not self._git("status", "--porcelain", cwd=cwd)

    def create_hypothesis(
        self,
        hypothesis_id: str,
        title: str,
        description: str,
        *,
        files: dict[str, str] | None = None,
        base_commit: str | None = None,
    ) -> tuple[str, str]:
        slug = self._slug(title)
        branch = f"hypothesis/{hypothesis_id}-{slug}"
        base_commit = base_commit or self.head(self.champion_branch)
        tree = (
            self._write_tree_with_files(base_commit, files)
            if files
            else self._git("rev-parse", f"{base_commit}^{{tree}}")
        )
        hypothesis_commit = self._git(
            "commit-tree",
            tree,
            "-p",
            base_commit,
            "-m",
            f"research(hypothesis): {title}",
        )
        self._delete_branch_if_present(branch)
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

    def _write_tree_with_files(self, base_commit: str, files: dict[str, str]) -> str:
        """Create a tree from base_commit with additional/overwritten blob paths."""
        with tempfile.NamedTemporaryFile(prefix="autoresearch-index-", delete=False) as handle:
            index_path = Path(handle.name)
        env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
        try:
            self._git("read-tree", base_commit, env=env)
            for relative_path, contents in files.items():
                path = relative_path.strip("/")
                if not path or path.startswith("../") or "/../" in f"/{path}/":
                    raise GitError(f"invalid hypothesis file path: {relative_path}")
                blob = self._git("hash-object", "-w", "--stdin", input_text=contents)
                self._git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{path}",
                    env=env,
                )
            return self._git("write-tree", env=env)
        finally:
            index_path.unlink(missing_ok=True)

    def create_trial(
        self, hypothesis_id: str, trial_number: int, hypothesis_branch: str
    ) -> TrialWorkspace:
        trial_id = f"{hypothesis_id}/T{trial_number:03d}"
        trial_branch = f"trial/{hypothesis_id}/T{trial_number:03d}"
        path = self.runtime_root / "worktrees" / hypothesis_id / f"T{trial_number:03d}"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_worktree_if_present(path)
        self._delete_branch_if_present(trial_branch)
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

    def tag_frontier(self, trial_id: str, commit: str) -> str:
        safe_trial = trial_id.replace("/", "-")
        tag = f"frontier/{safe_trial}"
        self._git("tag", "-f", tag, commit)
        return tag

    def delete_frontier_tag(self, trial_id: str) -> None:
        safe_trial = trial_id.replace("/", "-")
        with contextlib.suppress(GitError):
            self._git("tag", "-d", f"frontier/{safe_trial}")

    def write_frontier_manifest(self, points: list[dict[str, Any]]) -> None:
        """Overwrite frontier note on champion tip (list of non-dominated points)."""
        tip = self.head(self.champion_branch)
        record = {
            "schema_version": "1",
            "points": points,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.add_note("research/frontier", tip, record)

    def merge_trial(self, trial_branch: str, hypothesis_base_commit: str) -> str:
        current_branch = self._git("branch", "--show-current")
        if current_branch != self.champion_branch:
            raise GitError(
                f"project root must be on {self.champion_branch!r}, found {current_branch!r}"
            )
        if not self.is_clean():
            dirty = self._git("status", "--porcelain").strip()
            detail = f":\n{dirty}" if dirty else ""
            raise GitError(f"champion worktree must be clean before promotion{detail}")
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

    def has_origin(self) -> bool:
        remotes = self._git("remote")
        return "origin" in remotes.splitlines()

    def push_research_to_origin(self) -> dict[str, Any]:
        """Push champion, hypothesis/trial branches, and decision tags to origin."""
        if not self.has_origin():
            return {"pushed": False, "reason": "no origin remote"}
        refs = [self.champion_branch]
        listed = self._git(
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads/hypothesis",
            "refs/heads/trial",
        )
        refs.extend(branch for branch in listed.splitlines() if branch)
        for ref in refs:
            self._git("push", "-u", "origin", ref)
        with contextlib.suppress(GitError):
            self._git("push", "origin", "--tags")
        with contextlib.suppress(GitError):
            self._git("push", "origin", "refs/notes/*")
        return {"pushed": True, "refs": refs}

    def diff(self, base_commit: str, candidate_commit: str) -> str:
        return self._git("diff", "--no-color", base_commit, candidate_commit)

    def assert_only_allowed_paths_changed(
        self, base_commit: str, candidate_commit: str, allowed_paths: list[str]
    ) -> None:
        if not allowed_paths:
            return
        changed = self._git("diff", "--name-only", base_commit, candidate_commit)
        if not changed:
            return
        illegal = [
            path
            for path in changed.splitlines()
            if not any(
                path == allowed or path.startswith(f"{allowed.rstrip('/')}/")
                for allowed in allowed_paths
            )
        ]
        if illegal:
            raise GitError(f"candidate modified paths outside allow-list: {', '.join(illegal)}")

    def _remove_worktree_if_present(self, path: Path) -> None:
        if path.exists():
            with contextlib.suppress(GitError):
                self._git("worktree", "remove", "--force", str(path))
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def _delete_branch_if_present(self, branch: str) -> None:
        with contextlib.suppress(GitError):
            self._git("branch", "-D", branch)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return (slug or "idea")[:48]
