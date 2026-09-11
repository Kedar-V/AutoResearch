from __future__ import annotations

from autoresearch_api.hypothesis_brief import build_hypothesis_brief, summarize_outcome


def test_brief_includes_recent_what_worked_and_what_did_not() -> None:
    title, description = build_hypothesis_brief(
        hypothesis_code="H0003",
        node_config={
            "title": "Lower val_bpb",
            "system_prompt": "Name exact train.py edits.",
            "description": "Operator wants focused experiments.",
        },
        recent_hypotheses=[
            {
                "id": "proj:H0002",
                "title": "H0002",
                "status": "rejected",
                "what_worked": "",
                "what_did_not": "Raised learning rate; val_bpb got worse.",
                "metrics": {"val_bpb": 3.1},
            },
            {
                "id": "proj:H0001",
                "title": "H0001",
                "status": "accepted",
                "what_worked": "Slightly longer training improved val_bpb.",
                "what_did_not": "",
                "metrics": {"val_bpb": 2.8},
            },
        ],
        recent_trials=[
            {
                "id": "proj:H0002/T001",
                "hypothesis_id": "proj:H0002",
                "outcome": "rejected",
                "error": "",
                "what_changed": "lr=1e-2",
                "metrics": {"val_bpb": 3.1},
            }
        ],
        context={"last_decision": "rejected", "last_metrics": {"val_bpb": 2.8}},
        allowed_paths=["train.py"],
        gate={"metric": "val_bpb", "direction": "minimize", "baseline": 2.8, "min_delta": 0.0001},
        history_window=10,
    )

    assert "New direction after setback" in title
    assert "H0003" in description
    assert "Name exact train.py edits." in description
    assert "Slightly longer training improved val_bpb." in description
    assert "Raised learning rate; val_bpb got worse." in description
    assert "`train.py`" in description
    assert "Do not repeat H0002" in description
    assert "Recent history" in description


def test_summarize_outcome_captures_accept_and_reject_lessons() -> None:
    worked, did_not = summarize_outcome(
        accepted=True,
        metrics={"score": 0.5},
        gate_metric="score",
        gate_baseline=1.0,
        trial_notes=[{"outcome": "ran", "what_changed": "decrement score", "error": ""}],
    )
    assert "Accepted on score=0.5" in worked
    assert "decrement score" in worked

    worked2, did_not2 = summarize_outcome(
        accepted=False,
        metrics={"score": 2.0},
        gate_metric="score",
        gate_baseline=1.0,
        trial_notes=[{"outcome": "failed", "error": "boom", "what_changed": "", "next_step": "retry"}],
    )
    assert worked2 == ""
    assert "Rejected on score=2.0" in did_not2
    assert "boom" in did_not2
