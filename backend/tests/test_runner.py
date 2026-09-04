from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autoresearch_api.runner import LocalRunner, RunnerError


def test_runner_captures_output(tmp_path: Path) -> None:
    result = LocalRunner().run([sys.executable, "-c", "print('hello')"], tmp_path)
    assert result.returncode == 0
    assert result.stdout == "hello\n"


def test_evaluation_parser() -> None:
    runner = LocalRunner()
    result = runner.run(
        [sys.executable, "-c", 'print(\'{"metrics": {"score": 1.25}}\')'], Path.cwd()
    )
    assert runner.parse_evaluation(result) == {"score": 1.25}


def test_evaluation_parser_rejects_non_json() -> None:
    runner = LocalRunner()
    result = runner.run([sys.executable, "-c", "print('nope')"], Path.cwd())
    with pytest.raises(RunnerError, match="JSON"):
        runner.parse_evaluation(result)
