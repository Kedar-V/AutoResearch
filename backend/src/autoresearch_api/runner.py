from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV")


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class LocalRunner:
    def __init__(self, default_timeout_seconds: int = 300) -> None:
        self.default_timeout_seconds = default_timeout_seconds

    def run(
        self,
        command: list[str],
        cwd: Path,
        *,
        environment: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise RunnerError("command must be a non-empty list of strings")
        env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
        env.update(environment or {})
        started = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=cwd.resolve(),
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds or self.default_timeout_seconds,
                check=False,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"command timed out after {exc.timeout} seconds") from exc
        return CommandResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=time.monotonic() - started,
        )

    @staticmethod
    def parse_evaluation(result: CommandResult) -> dict[str, float]:
        if result.returncode:
            raise RunnerError(f"evaluator failed with exit code {result.returncode}")
        try:
            payload: dict[str, Any] = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RunnerError("evaluator stdout must be one JSON object") from exc
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise RunnerError("evaluator output must contain a non-empty metrics object")
        if not all(
            isinstance(name, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            for name, value in metrics.items()
        ):
            raise RunnerError("metric names must be strings and values must be numbers")
        return {name: float(value) for name, value in metrics.items()}
