from __future__ import annotations

from typing import Any

from .protocol import GenerationRecord


class NoopObservability:
    """Default backend: core research loop works with zero vendor config."""

    @property
    def backend_name(self) -> str:
        return "noop"

    def get_prompt(self, name: str, fallback: str) -> tuple[str, str]:
        return fallback, ""

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
    ) -> GenerationRecord:
        extra: dict[str, Any] = {}
        if usage_details:
            extra["usage_details"] = usage_details
        if cost_details:
            extra["cost_details"] = cost_details
        return GenerationRecord(backend="noop", extra=extra)

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None
