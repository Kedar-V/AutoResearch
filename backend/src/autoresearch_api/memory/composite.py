from __future__ import annotations

import logging
from typing import Any

from .protocol import AgentMemory, MemoryHit, MemoryKind
from .types import MemoryScope

logger = logging.getLogger(__name__)


class CompositeMemory:
    """Fan-out retain; merge/dedupe recall across providers."""

    def __init__(self, providers: list[AgentMemory]) -> None:
        if not providers:
            raise ValueError("CompositeMemory requires at least one provider")
        self._providers = providers

    @property
    def backend_name(self) -> str:
        names = "+".join(provider.backend_name for provider in self._providers)
        return f"composite:{names}"

    def recall(
        self,
        *,
        query: str,
        scope: MemoryScope,
        limit: int = 8,
    ) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        seen: set[str] = set()
        for provider in self._providers:
            try:
                for hit in provider.recall(query=query, scope=scope, limit=limit):
                    key = hit.text.strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    hits.append(hit)
                    if len(hits) >= limit:
                        return hits
            except Exception as exc:  # noqa: BLE001 — soft-fail per provider
                logger.warning(
                    "memory composite recall failed for %s: %s",
                    provider.backend_name,
                    exc,
                )
        return hits

    def retain(
        self,
        *,
        content: str,
        scope: MemoryScope,
        kind: MemoryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        for provider in self._providers:
            try:
                provider.retain(
                    content=content, scope=scope, kind=kind, metadata=metadata
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "memory composite retain failed for %s: %s",
                    provider.backend_name,
                    exc,
                )

    def flush(self) -> None:
        for provider in self._providers:
            try:
                provider.flush()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "memory composite flush failed for %s: %s",
                    provider.backend_name,
                    exc,
                )
