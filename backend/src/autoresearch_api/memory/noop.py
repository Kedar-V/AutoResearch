from __future__ import annotations

from typing import Any

from .protocol import MemoryHit, MemoryKind
from .types import MemoryScope


class NoopMemory:
    """Default backend: research loop works with zero vendor memory config."""

    @property
    def backend_name(self) -> str:
        return "noop"

    def recall(
        self,
        *,
        query: str,
        scope: MemoryScope,
        limit: int = 8,
    ) -> list[MemoryHit]:
        return []

    def retain(
        self,
        *,
        content: str,
        scope: MemoryScope,
        kind: MemoryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None
