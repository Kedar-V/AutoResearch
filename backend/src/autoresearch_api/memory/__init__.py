"""Vendor-agnostic agent memory port (preferences / soft lessons).

Git + Postgres remain the research system of record. Memory adapters must soft-fail
and never write champion code, gate math, or trial branches.
"""

from __future__ import annotations

from .composite import CompositeMemory
from .factory import get_memory, reset_memory_cache
from .helpers import format_memory_section, recall_for_research, retain_research_lesson
from .noop import NoopMemory
from .protocol import AgentMemory, MemoryHit, MemoryKind
from .types import MemoryScope

__all__ = [
    "AgentMemory",
    "CompositeMemory",
    "MemoryHit",
    "MemoryKind",
    "MemoryScope",
    "NoopMemory",
    "format_memory_section",
    "get_memory",
    "recall_for_research",
    "reset_memory_cache",
    "retain_research_lesson",
]
