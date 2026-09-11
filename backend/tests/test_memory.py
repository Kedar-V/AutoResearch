from __future__ import annotations

from autoresearch_api.memory import (
    MemoryHit,
    MemoryScope,
    format_memory_section,
    get_memory,
    recall_for_research,
    reset_memory_cache,
    retain_research_lesson,
)
from autoresearch_api.memory.composite import CompositeMemory
from autoresearch_api.memory.factory import _build_provider
from autoresearch_api.memory.noop import NoopMemory as NoopMemoryImpl


class FakeMemory:
    def __init__(self, name: str, hits: list[MemoryHit] | None = None) -> None:
        self.name = name
        self.hits = hits or []
        self.retained: list[tuple[str, str]] = []

    @property
    def backend_name(self) -> str:
        return self.name

    def recall(self, *, query: str, scope: MemoryScope, limit: int = 8) -> list[MemoryHit]:
        return list(self.hits)[:limit]

    def retain(self, *, content: str, scope: MemoryScope, kind: str = "note", metadata=None) -> None:
        self.retained.append((kind, content))

    def flush(self) -> None:
        return None


def test_default_memory_backend_is_noop(monkeypatch) -> None:
    reset_memory_cache()
    monkeypatch.setenv("AUTORESEARCH_MEMORY_BACKEND", "noop")
    from autoresearch_api import config as config_mod

    config_mod.get_settings.cache_clear()
    mem = get_memory()
    assert isinstance(mem, NoopMemoryImpl)
    assert mem.recall(query="x", scope=MemoryScope(project_id="p1")) == []
    reset_memory_cache()
    config_mod.get_settings.cache_clear()


def test_composite_merges_and_dedupes() -> None:
    a = FakeMemory(
        "honcho",
        [MemoryHit(text="Prefer small diffs", kind="preference", backend="honcho")],
    )
    b = FakeMemory(
        "hindsight",
        [
            MemoryHit(text="Prefer small diffs", kind="lesson", backend="hindsight"),
            MemoryHit(text="Avoid dropout bumps", kind="lesson", backend="hindsight"),
        ],
    )
    composite = CompositeMemory([a, b])  # type: ignore[arg-type]
    hits = composite.recall(query="style", scope=MemoryScope(project_id="p"), limit=8)
    assert len(hits) == 2
    assert hits[0].text == "Prefer small diffs"
    assert hits[1].text == "Avoid dropout bumps"
    assert composite.backend_name == "composite:honcho+hindsight"

    composite.retain(content="lesson", scope=MemoryScope(project_id="p"), kind="outcome")
    assert a.retained and b.retained


def test_format_memory_section() -> None:
    section = format_memory_section(
        [MemoryHit(text="Keep train.py edits minimal", kind="preference", backend="honcho")]
    )
    assert "Agent memory" in section
    assert "honcho/preference" in section
    assert format_memory_section([]) == ""


def test_honcho_without_key_falls_back_to_noop(monkeypatch) -> None:
    reset_memory_cache()
    monkeypatch.setenv("AUTORESEARCH_MEMORY_BACKEND", "honcho")
    monkeypatch.delenv("AUTORESEARCH_HONCHO_API_KEY", raising=False)
    from autoresearch_api import config as config_mod

    config_mod.get_settings.cache_clear()
    assert isinstance(get_memory(), NoopMemoryImpl)
    reset_memory_cache()
    config_mod.get_settings.cache_clear()


def test_build_provider_hindsight_requires_credentials(monkeypatch) -> None:
    monkeypatch.setenv("AUTORESEARCH_HINDSIGHT_API_KEY", "")
    monkeypatch.setenv("AUTORESEARCH_HINDSIGHT_API_URL", "")
    from autoresearch_api import config as config_mod

    config_mod.get_settings.cache_clear()
    assert _build_provider("hindsight") is None
    config_mod.get_settings.cache_clear()


def test_brief_includes_memory_section(monkeypatch) -> None:
    from autoresearch_api.hypothesis_brief import build_hypothesis_brief

    fake = FakeMemory(
        "honcho",
        [MemoryHit(text="Operator prefers one-knob changes", kind="preference", backend="honcho")],
    )
    monkeypatch.setattr(
        "autoresearch_api.memory.helpers.get_memory",
        lambda: fake,
    )
    _title, description = build_hypothesis_brief(
        hypothesis_code="H0001",
        node_config={"title": "Bump lr"},
        recent_hypotheses=[],
        recent_trials=[],
        context={"project_id": "proj-1", "run_id": "run-1"},
        allowed_paths=["train.py"],
        gate={"metric": "val_bpb", "direction": "minimize", "baseline": 3.0, "min_delta": 0.01},
    )
    assert "Agent memory" in description
    assert "Operator prefers one-knob changes" in description


def test_retain_research_lesson_soft_fails(monkeypatch) -> None:
    class Boom:
        backend_name = "boom"

        def retain(self, **kwargs):
            raise RuntimeError("down")

        def recall(self, **kwargs):
            return []

        def flush(self):
            return None

    monkeypatch.setattr("autoresearch_api.memory.helpers.get_memory", lambda: Boom())
    retain_research_lesson(content="x", context={"project_id": "p"})  # must not raise
    assert recall_for_research(query="q", context={"project_id": "p"}) == []
