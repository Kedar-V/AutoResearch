"""Build detailed, history-aware hypothesis briefs."""
from __future__ import annotations

from typing import Any

DEFAULT_HISTORY_WINDOW = 10

DEFAULT_SYSTEM_PROMPT = """You are the research agent for this repository.

Produce a concrete next experiment — not a vague goal like "improve the metric".

Your hypothesis must specify:
1. Objective — which metric moves, in which direction, and why this attempt should beat the champion.
2. Exact edits — files you will change (only allowed paths), functions/hyperparameters/logic touched, and the intended behavioral effect of each edit.
3. Rationale — how this differs from the last N hypotheses; explicitly reuse what worked and avoid what failed.
4. Risks — what could break training/eval, and how you will detect failure quickly.
5. Success check — the numeric gate condition that counts as acceptance.

Never restate the research brief alone. Never propose "try something" without naming the change.
Prefer one focused change over many simultaneous edits unless history shows a compound change is required.
"""


def build_hypothesis_brief(
    *,
    hypothesis_code: str,
    node_config: dict[str, Any],
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
    context: dict[str, Any],
    allowed_paths: list[str] | None,
    gate: dict[str, Any] | None,
    history_window: int = DEFAULT_HISTORY_WINDOW,
) -> tuple[str, str]:
    """Return (title, detailed markdown description)."""
    system_prompt = str(node_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    base_title = str(node_config.get("title") or "Research hypothesis").strip()
    seed_description = str(node_config.get("description") or "").strip()

    worked = [h for h in recent_hypotheses if _text(h.get("what_worked"))]
    failed = [
        h
        for h in recent_hypotheses
        if _text(h.get("what_did_not")) or h.get("status") in {"rejected", "failed"}
    ]
    title = _next_title(base_title, hypothesis_code, recent_hypotheses, context)

    sections: list[str] = [
        f"# Hypothesis {hypothesis_code}",
        "",
        "## Agent instructions",
        system_prompt,
        "",
        "## Concrete assignment",
        "Write and execute a detailed experiment plan. Do not stop at a generic metric goal.",
        "Name the exact code/config changes, why they should help, and how they differ from recent attempts.",
    ]
    if seed_description:
        sections.extend(["", "### Operator seed notes", seed_description])

    sections.extend(
        [
            "",
            "## Success criteria",
            _success_criteria(gate, context),
            "",
            "## Editable surfaces",
            _editable_surfaces(allowed_paths),
            "",
            f"## Recent history (last {min(history_window, len(recent_hypotheses))} of {history_window} max)",
            _history_section(recent_hypotheses, recent_trials),
            "",
            "## What worked (carry forward)",
            _bullet_list(
                [
                    f"{_public_id(h.get('id'))}: {_text(h.get('what_worked'))}"
                    for h in worked
                ]
                or ["No accepted lessons yet — establish a careful baseline or first focused change."]
            ),
            "",
            "## What did not work (do not repeat)",
            _bullet_list(
                [
                    f"{_public_id(h.get('id'))} [{h.get('status')}]: "
                    f"{_text(h.get('what_did_not')) or 'rejected/failed without notes'}"
                    for h in failed
                ]
                or ["No negative lessons yet."]
            ),
            "",
            "## Required plan checklist",
            _bullet_list(
                [
                    "State the single primary change under test.",
                    "List every file path you will modify and the before→after intent.",
                    "Call out which prior hypotheses you are extending vs deliberately avoiding.",
                    "Define the abort condition (crash, NaN, metric regression, timeout).",
                    "Keep the change minimal enough to attribute metric movement.",
                ]
            ),
            "",
            "## Proposed direction for this hypothesis",
            _proposed_direction(recent_hypotheses, recent_trials, context, gate),
        ]
    )

    return title, "\n".join(sections).strip() + "\n"


def summarize_outcome(
    *,
    accepted: bool,
    metrics: dict[str, Any],
    gate_metric: str | None,
    gate_baseline: Any,
    trial_notes: list[dict[str, Any]],
    evaluation_summary: str | None = None,
) -> tuple[str, str]:
    """Return (what_worked, what_did_not) for a finished hypothesis."""
    metric_name = gate_metric or "metric"
    metric_value = metrics.get(metric_name, metrics)
    failures = [
        t
        for t in trial_notes
        if t.get("outcome") in {"failed", "rejected"} or _text(t.get("error"))
    ]
    changes = [_text(t.get("what_changed")) for t in trial_notes if _text(t.get("what_changed"))]
    errors = [_text(t.get("error")) for t in trial_notes if _text(t.get("error"))]
    next_steps = [_text(t.get("next_step")) for t in trial_notes if _text(t.get("next_step"))]

    if accepted:
        worked_bits = [
            f"Accepted on {metric_name}={metric_value} (prior baseline {gate_baseline}).",
        ]
        if changes:
            worked_bits.append("Changes: " + "; ".join(changes[:3]))
        if evaluation_summary and "Candidate metrics" not in evaluation_summary:
            worked_bits.append(evaluation_summary.strip()[:300])
        did_not = ""
        if failures:
            did_not = "Earlier attempts in this hypothesis failed before accept: " + "; ".join(
                errors[:2] or [str(t.get("outcome")) for t in failures[:2]]
            )
        return " ".join(worked_bits), did_not

    did_not_bits = [
        f"Rejected on {metric_name}={metric_value} vs baseline {gate_baseline}.",
    ]
    if errors:
        did_not_bits.append("Errors: " + "; ".join(errors[:3]))
    if changes:
        did_not_bits.append("Tried: " + "; ".join(changes[:3]))
    if next_steps:
        did_not_bits.append("Next: " + next_steps[-1])
    if evaluation_summary and "Candidate metrics" not in evaluation_summary:
        did_not_bits.append(evaluation_summary.strip()[:300])
    return "", " ".join(did_not_bits)


def _next_title(
    base_title: str,
    hypothesis_code: str,
    recent_hypotheses: list[dict[str, Any]],
    context: dict[str, Any],
) -> str:
    last = recent_hypotheses[0] if recent_hypotheses else None
    decision = str(context.get("last_decision") or (last or {}).get("status") or "").lower()
    # Keep hypothesis_code out of the slug base; branch names already include it.
    if decision == "accepted" or (last and last.get("status") == "accepted"):
        return f"Extend accepted direction — {base_title}"
    if decision in {"rejected", "failed"} or (last and last.get("status") in {"rejected", "failed"}):
        return f"New direction after setback — {base_title}"
    if not recent_hypotheses:
        return f"Establish detailed baseline experiment — {base_title}"
    return f"Focused follow-up — {base_title}"


def _success_criteria(gate: dict[str, Any] | None, context: dict[str, Any]) -> str:
    if not gate and not context.get("last_metrics"):
        return "Improve the champion metric enough to pass the configured metric gate."
    metric = str((gate or {}).get("metric") or context.get("gate_metric") or "metric")
    direction = str((gate or {}).get("direction") or "minimize")
    baseline = context.get("gate_baseline", (gate or {}).get("baseline"))
    min_delta = (gate or {}).get("min_delta", 0)
    champion = context.get("last_metrics") or {}
    return (
        f"Primary metric `{metric}` must {direction} vs baseline `{baseline}` "
        f"(min_delta={min_delta}). Current champion metrics: {champion or '{}'}."
    )


def _editable_surfaces(allowed_paths: list[str] | None) -> str:
    if not allowed_paths:
        return "No script allow-list is attached — only change paths the workflow permits."
    return "Only modify: " + ", ".join(f"`{path}`" for path in allowed_paths)


def _history_section(
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
) -> str:
    if not recent_hypotheses:
        return "No prior hypotheses in this project yet."
    trials_by_hypo: dict[str, list[dict[str, Any]]] = {}
    for trial in recent_trials:
        key = str(trial.get("hypothesis_id") or "")
        trials_by_hypo.setdefault(key, []).append(trial)

    blocks: list[str] = []
    for hypo in recent_hypotheses:
        hypo_id = str(hypo.get("id") or "")
        public = _public_id(hypo_id)
        metrics = hypo.get("metrics") or {}
        lines = [
            f"### {public} — {hypo.get('status', 'unknown')}",
            f"- Title: {hypo.get('title') or '—'}",
            f"- Metrics: {metrics or '{}'}",
            f"- What worked: {_text(hypo.get('what_worked')) or '—'}",
            f"- What did not: {_text(hypo.get('what_did_not')) or '—'}",
        ]
        linked = trials_by_hypo.get(hypo_id, [])
        if linked:
            lines.append("- Trials:")
            for trial in linked[:5]:
                tid = _public_id(trial.get("id"))
                outcome = trial.get("outcome") or "unknown"
                err = _text(trial.get("error"))
                changed = _text(trial.get("what_changed"))
                detail = err or changed or str(trial.get("metrics") or "")
                lines.append(f"  - {tid} [{outcome}] {detail or '—'}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _proposed_direction(
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
    context: dict[str, Any],
    gate: dict[str, Any] | None,
) -> str:
    if not recent_hypotheses:
        return (
            "1. Inspect the current champion training/eval path end-to-end.\n"
            "2. Choose one minimal, measurable change in an allowed file.\n"
            "3. Document the expected metric movement before running the trial."
        )

    last = recent_hypotheses[0]
    last_id = _public_id(last.get("id"))
    status = last.get("status")
    failed_trials = [
        t
        for t in recent_trials
        if str(t.get("hypothesis_id")) == str(last.get("id"))
        and (t.get("outcome") == "failed" or _text(t.get("error")))
    ]

    if failed_trials:
        err = _text(failed_trials[-1].get("error")) or "execution failure"
        return (
            f"1. Diagnose and fix the failure mode from {last_id}: {err}\n"
            "2. Re-run with the smallest patch that restores a clean eval.\n"
            "3. Only after a green run, consider an additional metric-seeking change."
        )
    if status == "accepted":
        worked = _text(last.get("what_worked")) or "the previous accepted change"
        return (
            f"1. Treat {last_id} as the new base; keep {worked}.\n"
            "2. Propose one adjacent improvement that does not undo that win.\n"
            "3. State how the new edit compounds the accepted mechanism."
        )
    if status == "rejected":
        avoided = _text(last.get("what_did_not")) or "the rejected approach"
        metric = str((gate or {}).get("metric") or context.get("gate_metric") or "metric")
        return (
            f"1. Do not repeat {last_id}'s rejected approach: {avoided}\n"
            f"2. Pick a different lever aimed at `{metric}`.\n"
            "3. Explain why the new lever should move the gate when the last one did not."
        )
    return (
        f"1. Review {last_id} outcome `{status}` and its trial notes.\n"
        "2. Form a single-change experiment that is distinguishable from that attempt.\n"
        "3. Encode the change plan explicitly before editing."
    )


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _public_id(value: Any) -> str:
    text = str(value or "")
    return text.split(":", 1)[-1] if text else "—"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
