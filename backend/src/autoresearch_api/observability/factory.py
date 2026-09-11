from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .noop import NoopObservability
from .protocol import AgentObservability

_CLOUD_HOST = "https://cloud.langfuse.com"
_SELFHOST_HOST = "http://localhost:3000"
_LANGFUSE_BACKENDS = {"langfuse", "langfuse-cloud", "langfuse-selfhost"}


def resolve_langfuse_host(backend: str, configured_host: str) -> str:
    """Pick host from mode. Explicit LANGFUSE_HOST always wins when non-empty and mode-generic."""
    host = (configured_host or "").strip()
    mode = backend.strip().lower()
    if mode == "langfuse-selfhost":
        if not host or "cloud.langfuse.com" in host:
            return _SELFHOST_HOST
        return host
    if mode == "langfuse-cloud":
        if not host or host in {_SELFHOST_HOST, "http://127.0.0.1:3000"}:
            return _CLOUD_HOST
        return host
    # Generic "langfuse": honor configured host, default cloud.
    return host or _CLOUD_HOST


@lru_cache
def get_observability() -> AgentObservability:
    """Return the configured observability backend (noop unless Langfuse is enabled)."""
    cfg = get_settings()
    backend = str(cfg.observability_backend or "noop").strip().lower()
    if backend in {"", "noop", "none", "off", "disabled"}:
        return NoopObservability()
    if backend in _LANGFUSE_BACKENDS:
        if not cfg.langfuse_public_key or not cfg.langfuse_secret_key:
            return NoopObservability()
        from .langfuse_adapter import LangfuseObservability

        return LangfuseObservability(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=resolve_langfuse_host(backend, cfg.langfuse_host),
        )
    return NoopObservability()


def reset_observability_cache() -> None:
    get_observability.cache_clear()
