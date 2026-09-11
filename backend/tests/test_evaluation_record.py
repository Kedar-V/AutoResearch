from __future__ import annotations

from autoresearch_api.evaluation_record import build_evaluation_record, evaluation_id_for


def test_build_evaluation_record_recommends_accept_when_minimize_improves() -> None:
    record = build_evaluation_record(
        trial_id="H0001/T001",
        run_id="run-1",
        metrics={"score": 0.5},
        champion_metrics={"score": 1.0},
        primary_metric="score",
        direction="minimize",
        min_delta=0.01,
        candidate_commit="a" * 40,
        evaluator_commit="b" * 40,
        duration_seconds=1.25,
        stdout_excerpt='{"metrics":{"score":0.5}}',
        model="composer-2.5",
        system_prompt="judge carefully",
    )

    assert record["schema_version"] == "2"
    assert record["evaluation_id"] == evaluation_id_for("H0001/T001", "a" * 40)
    assert record["hypothesis_id"] == "H0001"
    assert record["recommendation"] == "accept"
    assert record["deltas"]["score"] == -0.5
    assert "score" in record["signals"]["improved"]
    assert record["evidence"]["duration_seconds"] == 1.25
    assert record["system_prompt_hash"]


def test_build_evaluation_record_uses_agent_judgment_when_provided() -> None:
    record = build_evaluation_record(
        trial_id="H0003/T001",
        run_id="run-3",
        metrics={"score": 0.4},
        champion_metrics={"score": 1.0},
        primary_metric="score",
        direction="minimize",
        candidate_commit="e" * 40,
        evaluator_commit="f" * 40,
        judgment={
            "summary": "Clear win from the score drop; attributable to the hypothesized edit.",
            "recommendation": "accept",
            "rationale": "Agent reasoning about the trial change and gate clearance.",
            "risks": "Still a single seed.",
            "model": "composer-2.5",
        },
    )
    assert record["summary"].startswith("Clear win")
    assert record["rationale"].startswith("Agent reasoning")
    assert record["recommendation"] == "accept"
    assert record["model"] == "composer-2.5"
    assert "explainability" not in record
