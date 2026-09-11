from __future__ import annotations

from types import SimpleNamespace

from autoresearch_api.llm_telemetry import (
    cost_from_cursor_usage_cost,
    resolve_openai_model,
    usage_from_cursor_token_usage,
    usage_from_openai_body,
)
from autoresearch_api.observability import (
    GenerationRecord,
    get_observability,
    reset_observability_cache,
    resolve_langfuse_host,
)
from autoresearch_api.observability.noop import NoopObservability


def test_default_backend_is_noop(monkeypatch) -> None:
    reset_observability_cache()
    monkeypatch.setenv("AUTORESEARCH_OBSERVABILITY_BACKEND", "noop")
    from autoresearch_api import config as config_mod

    config_mod.get_settings.cache_clear()
    obs = get_observability()
    assert isinstance(obs, NoopObservability)
    record = obs.record_generation(
        name="hypothesis_planner",
        input_text="in",
        output_text="out",
        model="gpt-4.1",
        usage_details={"input": 10, "output": 4, "total": 14},
        cost_details={"total": 0.001},
    )
    assert isinstance(record, GenerationRecord)
    assert record.extra["usage_details"]["total"] == 14
    reset_observability_cache()
    config_mod.get_settings.cache_clear()


def test_resolve_langfuse_host_by_mode() -> None:
    assert resolve_langfuse_host("langfuse-selfhost", "") == "http://localhost:3000"
    assert resolve_langfuse_host("langfuse-cloud", "") == "https://cloud.langfuse.com"


def test_usage_from_openai_body() -> None:
    assert usage_from_openai_body(
        {"usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}
    ) == {"input": 12, "output": 3, "total": 15}
    assert usage_from_openai_body({}) == {}


def test_usage_and_cost_from_cursor() -> None:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=5,
        cache_write_tokens=0,
        total_tokens=125,
        reasoning_tokens=2,
    )
    assert usage_from_cursor_token_usage(usage)["input"] == 100
    assert usage_from_cursor_token_usage(usage)["output_reasoning"] == 2
    cost = SimpleNamespace(raw_cost_cents=12.5, charged_cents=10.0)
    assert cost_from_cursor_usage_cost(cost) == {"total": 0.1, "raw_total": 0.125}


def test_resolve_openai_model_maps_composer(monkeypatch) -> None:
    monkeypatch.setenv("AUTORESEARCH_OPENAI_MODEL", "gpt-4.1-mini")
    assert resolve_openai_model("composer-2.5") == "gpt-4.1-mini"
    assert resolve_openai_model("gpt-4.1") == "gpt-4.1"


def test_evaluation_record_includes_observability_fields() -> None:
    from autoresearch_api.evaluation_record import build_evaluation_record

    record = build_evaluation_record(
        trial_id="H0001/T001",
        run_id="run-1",
        metrics={"score": 0.5},
        champion_metrics={"score": 1.0},
        primary_metric="score",
        direction="minimize",
        candidate_commit="a" * 40,
        evaluator_commit="b" * 40,
        judgment={
            "summary": "Clear improvement.",
            "recommendation": "accept",
            "rationale": "Beat champion by min_delta.",
            "risks": "Single seed.",
            "agent_trace_id": "trace-xyz",
            "prompt_version": "2",
            "observability_backend": "langfuse",
        },
    )
    assert record["agent_trace_id"] == "trace-xyz"
