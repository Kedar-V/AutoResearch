from __future__ import annotations

import pytest

from autoresearch_api.evaluation_agent import (
    EvaluationAgentError,
    _parse_judgment_json,
    judge_evaluation,
)


def test_parse_judgment_json_accepts_fenced_payload() -> None:
    raw = """```json
{
  "summary": "val_bpb dropped enough to clear the gate.",
  "recommendation": "accept",
  "rationale": "Primary metric improved by more than min_delta.",
  "risks": "Single-seed noise."
}
```"""
    judgment = _parse_judgment_json(raw)
    assert judgment["recommendation"] == "accept"
    assert "val_bpb" in judgment["summary"]


def test_parse_judgment_json_rejects_bad_recommendation() -> None:
    with pytest.raises(EvaluationAgentError, match="recommendation"):
        _parse_judgment_json(
            '{"summary":"x","recommendation":"maybe","rationale":"y","risks":"z"}'
        )


def test_judge_evaluation_requires_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EvaluationAgentError, match="CURSOR_API_KEY|OPENAI_API_KEY"):
        judge_evaluation(
            node_config={},
            trial_id="H0001/T001",
            hypothesis_id="H0001",
            hypothesis_title="tie weights",
            hypothesis_description="Tie embeddings",
            what_changed="train.py weight tying",
            metrics={"val_bpb": 3.5},
            champion_metrics={"val_bpb": 3.6},
            deltas={"val_bpb": -0.1},
            signals={"improved": ["val_bpb"], "regressed": [], "unchanged": []},
            primary_metric="val_bpb",
            direction="minimize",
            min_delta=0.0001,
            stdout_excerpt='{"metrics":{"val_bpb":3.5}}',
            project_root=tmp_path,
        )
