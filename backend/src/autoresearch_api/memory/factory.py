from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .composite import CompositeMemory
from .noop import NoopMemory
from .protocol import AgentMemory

_SINGLE_BACKENDS = {"honcho", "hindsight"}


def _build_provider(name: str) -> AgentMemory | None:
    cfg = get_settings()
    key = name.strip().lower()
    if key == "honcho":
        if not cfg.honcho_api_key:
            return None
        from .honcho_adapter import HonchoMemory

        return HonchoMemory(
            api_key=cfg.honcho_api_key,
            workspace_id=cfg.honcho_workspace_id or "autoresearch",
            base_url=cfg.honcho_base_url,
        )
    if key == "hindsight":
        if not cfg.hindsight_api_key and not cfg.hindsight_api_url:
            return None
        from .hindsight_adapter import HindsightMemory

        return HindsightMemory(
            api_key=cfg.hindsight_api_key,
            api_url=cfg.hindsight_api_url,
            bank_prefix=cfg.hindsight_bank_prefix or "autoresearch",
        )
    return None


@lru_cache
def get_memory() -> AgentMemory:
    """Return configured memory backend (noop unless Honcho/Hindsight/composite)."""
    cfg = get_settings()
    backend = str(cfg.memory_backend or "noop").strip().lower()
    if backend in {"", "noop", "none", "off", "disabled"}:
        return NoopMemory()

    if backend == "composite":
        names = [
            part.strip().lower()
            for part in str(cfg.memory_providers or "").split(",")
            if part.strip()
        ]
        providers: list[AgentMemory] = []
        for name in names:
            provider = _build_provider(name)
            if provider is not None:
                providers.append(provider)
        if not providers:
            return NoopMemory()
        if len(providers) == 1:
            return providers[0]
        return CompositeMemory(providers)

    if backend in _SINGLE_BACKENDS:
        provider = _build_provider(backend)
        return provider if provider is not None else NoopMemory()

    return NoopMemory()


def reset_memory_cache() -> None:
    get_memory.cache_clear()
