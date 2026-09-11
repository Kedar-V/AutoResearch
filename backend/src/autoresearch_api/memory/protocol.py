from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from .types import MemoryScope

MemoryKind = Literal["preference", "lesson", "note", "outcome"]


@dataclass(frozen=True)
class MemoryHit:
    """One recalled memory item (vendor-neutral)."""

    text: str
    kind: str = "note"
    score: float | None = None
    backend: str = "noop"
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentMemory(Protocol):
    """Port used by brief / planner / outcome hooks. Implementations must soft-fail."""

    @property
    def backend_name(self) -> str: ...

    def recall(
        self,
        *,
        query: str,
        scope: MemoryScope,
        limit: int = 8,
    ) -> list[MemoryHit]: ...

    def retain(
        self,
        *,
        content: str,
        scope: MemoryScope,
        kind: MemoryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def flush(self) -> None: ...
