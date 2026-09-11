from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from autoresearch_api.run_control import (
    RunCancelled,
    create_controller,
    remove_controller,
)
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


def test_runner_cancel_kills_long_command(tmp_path: Path) -> None:
    run_id = "cancel-test-run"
    controller = create_controller(run_id)
    try:

        def cancel_soon() -> None:
            time.sleep(0.3)
            controller.request_cancel()

        threading.Thread(target=cancel_soon, daemon=True).start()
        with pytest.raises(RunCancelled):
            LocalRunner(default_timeout_seconds=30).run(
                [sys.executable, "-c", "import time; time.sleep(20)"],
                tmp_path,
                run_id=run_id,
            )
    finally:
        remove_controller(run_id)


def test_controller_pause_and_resume() -> None:
    run_id = "pause-test-run"
    controller = create_controller(run_id)
    try:
        controller.request_pause()
        assert controller.is_pause_requested()

        def resume_soon() -> None:
            time.sleep(0.2)
            controller.request_resume()

        threading.Thread(target=resume_soon, daemon=True).start()
        assert controller.wait_while_paused(poll_seconds=0.05) == "running"
        assert not controller.is_pause_requested()
    finally:
        remove_controller(run_id)
