from __future__ import annotations

import pytest

from autoresearch_api.evaluation_agent import EvaluationAgentError, _parse_judgment_json
from autoresearch_api.evaluation_explainability import (
    EXAMPLE_EXPLAINABILITY_SCHEMA,
    ExplainabilitySchemaError,
    load_explainability_schema,
    schema_hash,
    validate_explainability,
)
from autoresearch_api.evaluation_record import build_evaluation_record


def test_load_explainability_schema_none_when_absent() -> None:
    assert load_explainability_schema({}) is None
    assert load_explainability_schema({"explainability_schema": None}) is None
    assert load_explainability_schema({"explainability_schema": {}}) is None


def test_load_explainability_schema_from_object() -> None:
    schema = load_explainability_schema(
        {"explainability_schema": EXAMPLE_EXPLAINABILITY_SCHEMA}
    )
    assert schema is not None
    assert schema["required"] == ["confidence", "attribution"]
    assert schema_hash(schema)


def test_validate_explainability_pass_and_fail() -> None:
    schema = EXAMPLE_EXPLAINABILITY_SCHEMA
    ok = validate_explainability(
        {"confidence": 0.9, "attribution": "dropout change", "failure_modes": ["seed"]},
        schema,
    )
    assert ok is not None
    assert ok["confidence"] == 0.9

    with pytest.raises(ExplainabilitySchemaError, match="missing required"):
        validate_explainability({"confidence": 0.5}, schema)

    with pytest.raises(ExplainabilitySchemaError, match="unexpected keys"):
        validate_explainability(
            {"confidence": 0.5, "attribution": "x", "extra": 1},
            schema,
        )


def test_parse_judgment_requires_explainability_when_schema_set() -> None:
    raw = """{
      "summary": "Clear improvement.",
      "recommendation": "accept",
      "rationale": "Primary metric cleared min_delta.",
      "risks": "Noise."
    }"""
    with pytest.raises(EvaluationAgentError, match="explainability"):
        _parse_judgment_json(raw, explainability_schema=EXAMPLE_EXPLAINABILITY_SCHEMA)


def test_parse_judgment_keeps_valid_explainability() -> None:
    raw = """{
      "summary": "Clear improvement.",
      "recommendation": "accept",
      "rationale": "Primary metric cleared min_delta.",
      "risks": "Noise.",
      "explainability": {
        "confidence": 0.75,
        "attribution": "Tied embeddings",
        "failure_modes": ["single seed"]
      }
    }"""
    judgment = _parse_judgment_json(
        raw, explainability_schema=EXAMPLE_EXPLAINABILITY_SCHEMA
    )
    assert judgment["explainability"]["confidence"] == 0.75
    assert judgment["recommendation"] == "accept"


def test_build_evaluation_record_preserves_explainability() -> None:
    record = build_evaluation_record(
        trial_id="H0002/T001",
        run_id="run-2",
        metrics={"score": 0.4},
        champion_metrics={"score": 1.0},
        primary_metric="score",
        direction="minimize",
        candidate_commit="c" * 40,
        evaluator_commit="d" * 40,
        judgment={
            "summary": "Win.",
            "recommendation": "accept",
            "rationale": "Gate cleared.",
            "risks": "Noise.",
            "explainability": {"confidence": 0.8, "attribution": "edit"},
            "explainability_schema_hash": "deadbeefcafebabe",
        },
    )
    assert record["explainability"]["attribution"] == "edit"
    assert record["explainability_schema_hash"] == "deadbeefcafebabe"
    # Gate-facing core fields unchanged
    assert record["recommendation"] == "accept"
    assert record["metrics"]["score"] == 0.4
