from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class GenerationRecord:
    """Vendor-neutral result of recording one agent generation."""

    trace_id: str = ""
    prompt_version: str = ""
    backend: str = "noop"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent_trace_id": self.trace_id,
            "prompt_version": self.prompt_version,
            "observability_backend": self.backend,
        }
        if self.extra:
            payload["observability_extra"] = self.extra
        return {key: value for key, value in payload.items() if value not in ("", None, {})}


@runtime_checkable
class AgentObservability(Protocol):
    """Port used by planner / code / eval agents. Implementations must soft-fail."""

    @property
    def backend_name(self) -> str: ...

    def get_prompt(self, name: str, fallback: str) -> tuple[str, str]:
        """Return (prompt_text, prompt_version). Version may be empty."""
        ...

    def record_generation(
        self,
        *,
        name: str,
        input_text: str,
        output_text: str,
        model: str,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        prompt_name: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
        model_parameters: dict[str, Any] | None = None,
    ) -> GenerationRecord: ...

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None: ...

    def flush(self) -> None: ...
