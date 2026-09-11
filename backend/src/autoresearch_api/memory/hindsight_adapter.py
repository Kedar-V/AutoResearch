"""Hindsight adapter — retain / recall over a memory bank.

Independent vendor behind the same AgentMemory Protocol (not a Honcho fork).
Soft-fails when the client SDK or credentials are unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import MemoryHit, MemoryKind
from .types import MemoryScope

logger = logging.getLogger(__name__)


class HindsightMemory:
    """Best-effort Hindsight backend. Never raises into the research loop."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_url: str = "",
        bank_prefix: str = "autoresearch",
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._api_url = (api_url or "").strip()
        self._bank_prefix = bank_prefix or "autoresearch"
        self._client: Any | None = None
        self._init_error: str | None = None
        self._ensure_client()

    @property
    def backend_name(self) -> str:
        return "hindsight"

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._init_error is not None:
            return None
        client_cls = None
        try:
            from hindsight_client import HindsightClient  # type: ignore[import-not-found]

            client_cls = HindsightClient
        except Exception:
            try:
                from hindsight import Client as HindsightClient  # type: ignore[import-not-found]

                client_cls = HindsightClient
            except Exception as exc:  # noqa: BLE001
                self._init_error = f"hindsight client unavailable: {exc}"
                logger.warning("memory hindsight: %s", self._init_error)
                return None
        try:
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_url:
                kwargs["api_url"] = self._api_url
                # Some SDKs use base_url / hindsight_api_url
                kwargs["base_url"] = self._api_url
                kwargs["hindsight_api_url"] = self._api_url
            self._client = client_cls(**_filter_kwargs(client_cls, kwargs))
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._init_error = str(exc)
            logger.warning("memory hindsight init failed: %s", exc)
            return None

    def recall(
        self,
        *,
        query: str,
        scope: MemoryScope,
        limit: int = 8,
    ) -> list[MemoryHit]:
        client = self._ensure_client()
        if client is None:
            return []
        bank_id = scope.bank_id(self._bank_prefix)
        try:
            results: Any = None
            if hasattr(client, "recall"):
                results = client.recall(bank_id=bank_id, query=query, limit=limit)
            elif hasattr(client, "arecall"):
                # Sync path only; skip async-only clients without a runner.
                logger.debug("memory hindsight: async-only recall; skipping")
                return []
            if results is None:
                return []
            hits: list[MemoryHit] = []
            for item in list(results)[:limit]:
                text = _item_text(item)
                if text:
                    hits.append(
                        MemoryHit(
                            text=text,
                            kind="lesson",
                            score=_item_score(item),
                            backend="hindsight",
                            metadata={"bank_id": bank_id},
                        )
                    )
            return hits
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory hindsight recall failed: %s", exc)
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
        if client is None:
            return
        bank_id = scope.bank_id(self._bank_prefix)
        payload = f"[{kind}] {text}"
        meta = {"kind": kind, **(metadata or {})}
        try:
            if hasattr(client, "retain"):
                client.retain(
                    bank_id=bank_id,
                    content=payload,
                    metadata=meta,
                )
            elif hasattr(client, "aretain"):
                logger.debug("memory hindsight: async-only retain; skipping")
            else:
                logger.debug("memory hindsight: no retain API; skipping")
        except TypeError:
            # Older SDKs may use different kw names
            try:
                client.retain(bank_id, payload)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                logger.warning("memory hindsight retain failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory hindsight retain failed: %s", exc)

    def flush(self) -> None:
        return None


def _filter_kwargs(cls: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Pass only kwargs the constructor appears to accept (best-effort)."""
    try:
        import inspect

        params = inspect.signature(cls).parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return kwargs
        return {key: value for key, value in kwargs.items() if key in params}
    except Exception:  # noqa: BLE001
        return kwargs


def _item_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("text", "content", "memory", "observation", "fact"):
            value = item.get(key)
            if value:
                return str(value).strip()
        return ""
    for attr in ("text", "content", "memory"):
        value = getattr(item, attr, None)
        if value:
            return str(value).strip()
    return str(item).strip()


def _item_score(item: Any) -> float | None:
    if isinstance(item, dict):
        score = item.get("score")
        return float(score) if isinstance(score, (int, float)) else None
    score = getattr(item, "score", None)
    return float(score) if isinstance(score, (int, float)) else None
