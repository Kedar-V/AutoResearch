"""Build deterministic evaluation records for explainability and tracking."""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

_TRIAL_RE = re.compile(r"^(H\d{4,})/T\d{3,}$")


def hypothesis_id_from_trial(trial_id: str) -> str:
    match = _TRIAL_RE.match(trial_id)
    if match:
        return match.group(1)
    if trial_id.startswith("H") and "/" in trial_id:
        return trial_id.split("/", 1)[0]
    return trial_id or "H0000"


def evaluation_id_for(trial_id: str, candidate_commit: str) -> str:
    short = (candidate_commit or "unknown")[:8]
    return f"{trial_id}@{short}"


def prompt_hash(system_prompt: str) -> str:
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16]


def build_evaluation_record(
    *,
    trial_id: str,
    run_id: str,
    metrics: dict[str, Any],
    champion_metrics: dict[str, Any] | None,
    primary_metric: str,
    direction: str,
    min_delta: float = 0.0,
    candidate_commit: str = "",
    evaluator_commit: str = "",
    duration_seconds: float | None = None,
    stdout_excerpt: str = "",
    status: str = "passed",
    model: str = "",
    system_prompt: str = "",
    created_at: str | None = None,
    judgment: dict[str, Any] | None = None,
    agent_trace_id: str = "",
    prompt_version: str = "",
    observability_backend: str = "",
) -> dict[str, Any]:
    """Return a schema v2 evaluation record.

    Structural fields (metrics/deltas/signals) are computed. Narrative judgment
    fields come from ``judgment`` when provided (LLM agent); otherwise a
    deterministic fallback is used for offline tests.
    """
    numeric_metrics = {
        str(name): float(value)
        for name, value in metrics.items()
        if isinstance(value, (int, float))
    }
    champ = {
        str(name): float(value)
        for name, value in (champion_metrics or {}).items()
        if isinstance(value, (int, float))
    }
    direction = "maximize" if direction == "maximize" else "minimize"
    if primary_metric not in numeric_metrics and numeric_metrics:
        primary_metric = next(iter(numeric_metrics))

    deltas: dict[str, float] = {}
    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []
    for name, value in numeric_metrics.items():
        if name not in champ:
            unchanged.append(name)
            continue
        delta = value - champ[name]
        deltas[name] = delta
        if abs(delta) < 1e-12:
            unchanged.append(name)
        elif direction == "minimize":
            (improved if delta < 0 else regressed).append(name)
        else:
            (improved if delta > 0 else regressed).append(name)

    if judgment:
        recommendation = str(judgment.get("recommendation") or "retry")
        if recommendation not in {"accept", "reject", "retry"}:
            recommendation = "retry"
        rationale = (
            str(judgment.get("rationale") or "").strip() or "Agent judgment missing rationale."
        )
        risks = str(judgment.get("risks") or "").strip() or "Agent judgment missing risks."
        summary = str(judgment.get("summary") or "").strip() or "Agent judgment missing summary."
        model = str(judgment.get("model") or model)
    else:
        recommendation, rationale, risks, summary = _interpret(
            primary_metric=primary_metric,
            direction=direction,
            min_delta=min_delta,
            metrics=numeric_metrics,
            champion_metrics=champ,
            deltas=deltas,
            status=status,
        )

    evidence: dict[str, Any] = {
        "candidate_commit": candidate_commit or "",
        "evaluator_commit": evaluator_commit or "",
    }
    if duration_seconds is not None:
        evidence["duration_seconds"] = float(duration_seconds)
    if stdout_excerpt:
        evidence["stdout_excerpt"] = stdout_excerpt[:2000]

    hypothesis_id = hypothesis_id_from_trial(trial_id)
    # Prefer observability ids from the LLM judgment when present.
    if judgment:
        agent_trace_id = str(judgment.get("agent_trace_id") or agent_trace_id or "")
        prompt_version = str(judgment.get("prompt_version") or prompt_version or "")
        observability_backend = str(
            judgment.get("observability_backend") or observability_backend or ""
        )

    record: dict[str, Any] = {
        "schema_version": "2",
        "evaluation_id": evaluation_id_for(trial_id, candidate_commit),
        "trial_id": trial_id,
        "hypothesis_id": hypothesis_id,
        "run_id": run_id,
        "status": status if status in {"passed", "failed", "invalid"} else "invalid",
        "metrics": numeric_metrics,
        "champion_metrics": champ,
        "deltas": deltas,
        "primary_metric": primary_metric,
        "direction": direction,
        "summary": summary,
        "signals": {
            "improved": improved,
            "regressed": regressed,
            "unchanged": unchanged,
        },
        "recommendation": recommendation,
        "rationale": rationale,
        "risks": risks,
        "evidence": evidence,
        "model": model,
        "system_prompt_hash": prompt_hash(system_prompt) if system_prompt else "",
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }
    if agent_trace_id:
        record["agent_trace_id"] = agent_trace_id
    if prompt_version:
        record["prompt_version"] = prompt_version
    if observability_backend:
        record["observability_backend"] = observability_backend
    if judgment:
        explainability = judgment.get("explainability")
        if isinstance(explainability, dict):
            record["explainability"] = explainability
        schema_digest = str(judgment.get("explainability_schema_hash") or "").strip()
        if schema_digest:
            record["explainability_schema_hash"] = schema_digest
    return record


def _interpret(
    *,
    primary_metric: str,
    direction: str,
    min_delta: float,
    metrics: dict[str, float],
    champion_metrics: dict[str, float],
    deltas: dict[str, float],
    status: str,
) -> tuple[str, str, str, str]:
    if status == "failed":
        return (
            "retry",
            "Eval script failed; metrics may be missing or invalid.",
            "Do not trust gate decisions until eval completes cleanly.",
            "Evaluation failed — recommend a retry with a smaller patch.",
        )
    if status == "invalid":
        return (
            "retry",
            "Evaluation output was invalid.",
            "Parsed metrics may not reflect a real training run.",
            "Invalid evaluation — recommend fixing the evaluator or trial.",
        )
    if primary_metric not in metrics:
        return (
            "retry",
            f"Primary metric {primary_metric!r} was not emitted.",
            "Gate cannot decide without the configured metric.",
            f"Missing primary metric {primary_metric}; recommend retry.",
        )

    value = metrics[primary_metric]
    baseline = champion_metrics.get(primary_metric)
    if baseline is None:
        summary = (
            f"{primary_metric}={value:.6g} with no champion baseline yet; "
            "treat as establishing measurement."
        )
        return (
            "accept",
            "No prior champion metric; first measured candidate can seed the ledger.",
            "Without a baseline, improvement is not yet proven across trials.",
            summary,
        )

    delta = deltas.get(primary_metric, value - baseline)
    improved = (
        value <= baseline - min_delta
        if direction == "minimize"
        else value >= baseline + min_delta
    )
    if improved:
        recommendation = "accept"
        rationale = (
            f"{primary_metric} moved from {baseline:.6g} to {value:.6g} "
            f"(delta {delta:+.6g}), meeting min_delta={min_delta:g} for {direction}."
        )
        risks = (
            "Single-eval noise or data-prep variance could reverse on a re-run; "
            "confirm protected paths were unchanged."
        )
        summary = (
            f"{primary_metric} improved vs champion ({baseline:.6g} → {value:.6g}); "
            "advisory recommendation: accept."
        )
    else:
        recommendation = "reject"
        rationale = (
            f"{primary_metric} did not beat champion {baseline:.6g} by min_delta={min_delta:g} "
            f"(got {value:.6g}, delta {delta:+.6g})."
        )
        risks = (
            "A near-miss may still be directionally useful; consider retrying a smaller "
            "or orthogonal change rather than compounding edits."
        )
        summary = (
            f"{primary_metric} did not improve vs champion ({baseline:.6g} → {value:.6g}); "
            "advisory recommendation: reject."
        )
    return recommendation, rationale, risks, summary


def record_from_node_output(output: dict[str, Any], *, run_id: str = "") -> dict[str, Any] | None:
    """Normalize a stored node_runs.output into a v2-shaped dict when possible."""
    if not isinstance(output, dict):
        return None
    if output.get("schema_version") == "2" and output.get("evaluation_id"):
        record = dict(output)
        if run_id and not record.get("run_id"):
            record["run_id"] = run_id
        return record
    metrics = output.get("metrics")
    if not isinstance(metrics, dict):
        return None
    trial_id = str(output.get("trial_id") or "")
    if not trial_id:
        return None
    return build_evaluation_record(
        trial_id=trial_id,
        run_id=str(output.get("run_id") or run_id or ""),
        metrics=metrics,
        champion_metrics=output.get("champion_metrics")
        if isinstance(output.get("champion_metrics"), dict)
        else {},
        primary_metric=str(output.get("primary_metric") or next(iter(metrics), "score")),
        direction=str(output.get("direction") or "minimize"),
        candidate_commit=str(
            (output.get("evidence") or {}).get("candidate_commit")
            if isinstance(output.get("evidence"), dict)
            else output.get("candidate_commit") or ""
        ),
        evaluator_commit=str(
            (output.get("evidence") or {}).get("evaluator_commit")
            if isinstance(output.get("evidence"), dict)
            else output.get("evaluator_commit") or ""
        ),
        duration_seconds=(
            float((output.get("evidence") or {}).get("duration_seconds"))
            if isinstance(output.get("evidence"), dict)
            and isinstance((output.get("evidence") or {}).get("duration_seconds"), (int, float))
            else None
        ),
        status=str(output.get("status") or "passed"),
        created_at=str(output.get("created_at") or datetime.now(UTC).isoformat()),
    )
