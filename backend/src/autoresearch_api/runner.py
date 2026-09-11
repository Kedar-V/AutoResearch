from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .run_control import RunCancelled, get_controller

# Intentionally omit VIRTUAL_ENV so project commands use their own .venv
# (e.g. via `uv run`) instead of the API server's environment.
SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "USER", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")


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
        run_id: str | None = None,
    ) -> CommandResult:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise RunnerError("command must be a non-empty list of strings")
        env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
        env.update(environment or {})
        started = time.monotonic()
        timeout = self.default_timeout_seconds if timeout_seconds is None else timeout_seconds
        controller = get_controller(run_id) if run_id else None
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd.resolve(),
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise RunnerError(f"failed to start command: {exc}") from exc

        if controller is not None:
            controller.register_process(process)

        stdout = ""
        stderr = ""
        try:
            while True:
                if controller is not None and controller.is_cancel_requested():
                    controller.kill_process()
                    raise RunCancelled("Cancelled by operator")
                elapsed = time.monotonic() - started
                if timeout is not None and elapsed >= timeout:
                    if controller is not None:
                        controller.kill_process()
                    else:
                        _kill_popen(process)
                    raise RunnerError(f"command timed out after {timeout} seconds")
                poll = 0.5
                if timeout is not None:
                    poll = min(poll, max(0.05, timeout - elapsed))
                try:
                    stdout, stderr = process.communicate(timeout=poll)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if controller is not None and controller.is_cancel_requested():
                raise RunCancelled("Cancelled by operator")
            return CommandResult(
                command=command,
                returncode=process.returncode if process.returncode is not None else -1,
                stdout=stdout or "",
                stderr=stderr or "",
                duration_seconds=time.monotonic() - started,
            )
        finally:
            if controller is not None:
                controller.clear_process(process)

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


def _kill_popen(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), 15)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), 9)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass
