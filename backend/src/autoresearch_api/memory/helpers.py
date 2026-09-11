"""Helpers for brief injection and outcome retention."""

from __future__ import annotations

import logging
from typing import Any

from .factory import get_memory
from .protocol import MemoryHit, MemoryKind
from .types import MemoryScope

logger = logging.getLogger(__name__)


def scope_from_context(context: dict[str, Any] | None) -> MemoryScope:
    ctx = context or {}
    return MemoryScope(
        project_id=str(ctx.get("project_id") or ""),
        run_id=str(ctx.get("run_id") or ""),
        peer_id=str(ctx.get("memory_peer_id") or "operator"),
        hypothesis_id=str(ctx.get("hypothesis_id") or ""),
        trial_id=str(ctx.get("trial_id") or ""),
    )


def recall_for_research(
    *,
    query: str,
    context: dict[str, Any] | None = None,
    limit: int = 6,
) -> list[MemoryHit]:
    try:
        return get_memory().recall(
            query=query,
            scope=scope_from_context(context),
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory recall failed: %s", exc)
        return []


def retain_research_lesson(
    *,
    content: str,
    kind: MemoryKind = "lesson",
    context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    text = (content or "").strip()
    if not text:
        return
    try:
        get_memory().retain(
            content=text,
            scope=scope_from_context(context),
            kind=kind,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory retain failed: %s", exc)


def format_memory_section(hits: list[MemoryHit]) -> str:
    if not hits:
        return ""
    lines = [
        "## Agent memory (preferences / soft lessons)",
        "Vendor memory is advisory only — Git/Postgres remain the research ledger.",
    ]
    for hit in hits:
        backend = hit.backend or "memory"
        kind = hit.kind or "note"
        lines.append(f"- [{backend}/{kind}] {hit.text.strip()}")
    return "\n".join(lines)
