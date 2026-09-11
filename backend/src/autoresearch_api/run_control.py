"""In-process run control plane for cancel / pause / resume.

Soft pause finishes the current node, then parks the worker until resume or cancel.
Hard cancel kills the active subprocess group (if any) and stops the run.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Literal


class RunCancelled(Exception):
    """Raised when a run is cancelled by the operator."""


class RunPausedExit(Exception):
    """Internal: pause wait was aborted by cancel."""


WaitResult = Literal["running", "cancelled"]


@dataclass
class RunController:
    run_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    resume_event: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _process: subprocess.Popen[str] | None = None
    _pgid: int | None = None

    def request_cancel(self) -> None:
        self.cancel_event.set()
        self.pause_event.clear()
        self.resume_event.set()
        self.kill_process()

    def request_pause(self) -> None:
        if self.cancel_event.is_set():
            return
        self.pause_event.set()
        self.resume_event.clear()

    def request_resume(self) -> None:
        if self.cancel_event.is_set():
            return
        self.pause_event.clear()
        self.resume_event.set()

    def is_cancel_requested(self) -> bool:
        return self.cancel_event.is_set()

    def is_pause_requested(self) -> bool:
        return self.pause_event.is_set() and not self.cancel_event.is_set()

    def register_process(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = process
            try:
                self._pgid = os.getpgid(process.pid)
            except (ProcessLookupError, OSError):
                self._pgid = process.pid

    def clear_process(self, process: subprocess.Popen[str] | None = None) -> None:
        with self._lock:
            if process is not None and self._process is not process:
                return
            self._process = None
            self._pgid = None

    def kill_process(self) -> None:
        with self._lock:
            process = self._process
            pgid = self._pgid
        if process is None and pgid is None:
            return
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        self.clear_process(process)

    def wait_while_paused(self, poll_seconds: float = 0.5) -> WaitResult:
        """Block while pause is set. Returns when resumed or cancelled."""
        while self.is_pause_requested():
            if self.cancel_event.wait(timeout=poll_seconds):
                return "cancelled"
            if self.resume_event.is_set() and not self.pause_event.is_set():
                break
        if self.cancel_event.is_set():
            return "cancelled"
        return "running"


_REGISTRY: dict[str, RunController] = {}
_REGISTRY_LOCK = threading.Lock()


def get_controller(run_id: str) -> RunController | None:
    with _REGISTRY_LOCK:
        return _REGISTRY.get(run_id)


def remove_controller(run_id: str) -> None:
    with _REGISTRY_LOCK:
        _REGISTRY.pop(run_id, None)


def ensure_controller(run_id: str) -> RunController:
    """Return existing controller or create one (preserves early cancel/pause flags)."""
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(run_id)
        if existing is not None:
            return existing
        controller = RunController(run_id=run_id)
        _REGISTRY[run_id] = controller
        return controller


def create_controller(run_id: str) -> RunController:
    return ensure_controller(run_id)