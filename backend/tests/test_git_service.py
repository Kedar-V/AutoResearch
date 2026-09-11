from __future__ import annotations

from pathlib import Path

import pytest

from autoresearch_api.git_service import GitError, GitService


def test_merge_trial_includes_porcelain_paths_when_dirty(
    project_repo: Path, tmp_path: Path
) -> None:
    service = GitService(project_repo, tmp_path / "runtime", "master")
    hypothesis_branch, base = service.create_hypothesis(
        "H0001",
        "Bump score",
        "Change score.txt",
        files={"score.txt": "0.5\n"},
    )
    workspace = service.create_trial("H0001", 1, hypothesis_branch)

    (project_repo / "wip.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(GitError, match=r"(?s)champion worktree must be clean.*wip\.txt") as exc:
        service.merge_trial(workspace.trial_branch, base)

    assert "wip.txt" in str(exc.value)
