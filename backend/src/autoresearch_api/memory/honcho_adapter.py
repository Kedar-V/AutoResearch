"""Honcho adapter — preferences / dialectic / session memory.

Vendor import stays in this module. Soft-fails when SDK or keys are unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import MemoryHit, MemoryKind
from .types import MemoryScope

logger = logging.getLogger(__name__)


class HonchoMemory:
    """Best-effort Honcho backend. Never raises into the research loop."""

    def __init__(
        self,
        *,
        api_key: str,
        workspace_id: str = "autoresearch",
        base_url: str = "",
    ) -> None:
        self._api_key = api_key
        self._workspace_id = workspace_id or "autoresearch"
        self._base_url = (base_url or "").strip()
        self._client: Any | None = None
        self._init_error: str | None = None
        self._ensure_client()

    @property
    def backend_name(self) -> str:
        return "honcho"

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._init_error is not None:
            return None
        try:
            from honcho import Honcho  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            self._init_error = f"honcho-ai unavailable: {exc}"
            logger.warning("observability memory honcho: %s", self._init_error)
            return None
        try:
            kwargs: dict[str, Any] = {
                "workspace_id": self._workspace_id,
                "api_key": self._api_key,
            }
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = Honcho(**kwargs)
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._init_error = str(exc)
            logger.warning("memory honcho init failed: %s", exc)
            return None

    def _session(self, scope: MemoryScope) -> Any | None:
        client = self._ensure_client()
        if client is None:
            return None
        session_id = scope.session_key()
        try:
            if hasattr(client, "session"):
                return client.session(session_id)
            if hasattr(client, "get_or_create_session"):
                return client.get_or_create_session(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory honcho session failed: %s", exc)
        return None

    def recall(
        self,
        *,
        query: str,
        scope: MemoryScope,
        limit: int = 8,
    ) -> list[MemoryHit]:
        session = self._session(scope)
        if session is None:
            return []
        try:
            results: Any = None
            if hasattr(session, "search"):
                results = session.search(query, limit=limit)
            elif hasattr(session, "context"):
                ctx = session.context()
                if hasattr(ctx, "to_openai"):
                    # Fall back to dumping recent context as text hits.
                    messages = ctx.to_openai()
                    hits: list[MemoryHit] = []
                    for message in messages[-limit:] if isinstance(messages, list) else []:
                        content = (
                            message.get("content")
                            if isinstance(message, dict)
                            else getattr(message, "content", "")
                        )
                        text = str(content or "").strip()
                        if text:
                            hits.append(
                                MemoryHit(text=text, kind="note", backend="honcho")
                            )
                    return hits
            if results is None:
                return []
            hits = []
            for item in list(results)[:limit]:
                text = _honcho_item_text(item)
                if text:
                    hits.append(
                        MemoryHit(
                            text=text,
                            kind="note",
                            score=_honcho_item_score(item),
                            backend="honcho",
                            metadata={"session": scope.session_key()},
                        )
                    )
            return hits
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory honcho recall failed: %s", exc)
            return []

    def retain(
        self,
        *,
        content: str,
        scope: MemoryScope,
        kind: MemoryKind = "note",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        text = (content or "").strip()
        if not text:
            return
        client = self._ensure_client()
        session = self._session(scope)
        if client is None or session is None:
            return
        peer_id = scope.peer_id or "operator"
        payload = f"[{kind}] {text}"
        meta = {"kind": kind, **(metadata or {})}
        try:
            peer = None
            if hasattr(client, "peer"):
                peer = client.peer(peer_id)
            message = {
                "peer_id": peer_id,
                "content": payload,
                "metadata": meta,
            }
            if hasattr(session, "add_messages"):
                session.add_messages([message])
            elif hasattr(session, "add_message"):
                session.add_message(**message)
            elif peer is not None and hasattr(peer, "chat"):
                # Last resort: dialectic-style write is not ideal; skip rather than invent.
                logger.debug("memory honcho: no add_messages API; skipping retain")
            else:
                logger.debug("memory honcho: no retain API; skipping")
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory honcho retain failed: %s", exc)

    def flush(self) -> None:
        return None


def _honcho_item_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("content", "text", "message", "body"):
            value = item.get(key)
            if value:
                return str(value).strip()
        return ""
    for attr in ("content", "text", "message"):
        value = getattr(item, attr, None)
        if value:
            return str(value).strip()
    return str(item).strip()


def _honcho_item_score(item: Any) -> float | None:
    if isinstance(item, dict):
        score = item.get("score")
        return float(score) if isinstance(score, (int, float)) else None
    score = getattr(item, "score", None)
    return float(score) if isinstance(score, (int, float)) else None
