"""LLM evaluation agent: real interpretive judgments over trial metrics."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .evaluation_explainability import (
    ExplainabilitySchemaError,
    load_explainability_schema,
    prompt_fragment,
    schema_hash,
    validate_explainability,
)
from .llm_telemetry import LlmCallResult, cursor_prompt, openai_chat_json
from .observability import get_observability

PROMPT_NAME = "autoresearch/evaluation"

DEFAULT_SYSTEM_PROMPT = (
    "You are the AutoResearch evaluation agent. Interpret candidate metrics versus "
    "the champion with scientific honesty. Prefer reject or retry when gains are "
    "ambiguous, noisy, or unexplained. Accept only when the primary metric clearly "
    "beats the gate. Explain what the numbers imply about the hypothesis, not just "
    "that a number moved."
)


class EvaluationAgentError(RuntimeError):
    pass


def judge_evaluation(
    *,
    node_config: dict[str, Any],
    trial_id: str,
    hypothesis_id: str,
    hypothesis_title: str,
    hypothesis_description: str,
    what_changed: str,
    metrics: dict[str, float],
    champion_metrics: dict[str, float],
    deltas: dict[str, float],
    signals: dict[str, list[str]],
    primary_metric: str,
    direction: str,
    min_delta: float,
    stdout_excerpt: str,
    project_root: Path,
    model: str | None = None,
    observability_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return agent judgment fields: summary, recommendation, rationale, risks."""
    requested_model = str(model or node_config.get("model") or "composer-2.5")
    obs = get_observability()
    canvas_prompt = str(node_config.get("system_prompt") or "").strip()
    managed_prompt, prompt_version = obs.get_prompt(PROMPT_NAME, DEFAULT_SYSTEM_PROMPT)
    effective_system = canvas_prompt or managed_prompt
    node_config = {**node_config, "system_prompt": effective_system}
    link_prompt = bool(prompt_version) and not canvas_prompt

    try:
        explainability_schema = load_explainability_schema(node_config)
    except ExplainabilitySchemaError as exc:
        raise EvaluationAgentError(str(exc)) from exc

    prompt = _judgment_prompt(
        node_config=node_config,
        trial_id=trial_id,
        hypothesis_id=hypothesis_id,
        hypothesis_title=hypothesis_title,
        hypothesis_description=hypothesis_description,
        what_changed=what_changed,
        metrics=metrics,
        champion_metrics=champion_metrics,
        deltas=deltas,
        signals=signals,
        primary_metric=primary_metric,
        direction=direction,
        min_delta=min_delta,
        stdout_excerpt=stdout_excerpt,
        explainability_schema=explainability_schema,
    )

    call = _invoke_judge(prompt=prompt, model=requested_model, cwd=project_root)
    raw = call.text

    schema_valid = 1.0
    try:
        judgment = _parse_judgment_json(raw, explainability_schema=explainability_schema)
    except EvaluationAgentError:
        schema_valid = 0.0
        _record_call(
            obs,
            call=call,
            prompt=prompt,
            raw=raw,
            observability_meta=observability_meta,
            trial_id=trial_id,
            hypothesis_id=hypothesis_id,
            metrics=metrics,
            deltas=deltas,
            link_prompt=link_prompt,
            schema_valid=schema_valid,
            parse_error=True,
            recommendation=None,
        )
        raise

    generation = _record_call(
        obs,
        call=call,
        prompt=prompt,
        raw=raw,
        observability_meta=observability_meta,
        trial_id=trial_id,
        hypothesis_id=hypothesis_id,
        metrics=metrics,
        deltas=deltas,
        link_prompt=link_prompt,
        schema_valid=schema_valid,
        parse_error=False,
        recommendation=judgment["recommendation"],
    )
    gate_aligned = _gate_aligned(
        recommendation=judgment["recommendation"],
        metrics=metrics,
        champion_metrics=champion_metrics,
        primary_metric=primary_metric,
        direction=direction,
        min_delta=min_delta,
    )
    obs.score(
        trace_id=generation.trace_id,
        name="gate_aligned",
        value=gate_aligned,
        comment=f"recommendation={judgment['recommendation']}",
    )
    obs.flush()

    judgment["backend"] = call.provider
    judgment["model"] = call.model
    judgment["requested_model"] = requested_model
    judgment.update(generation.as_dict())
    if call.usage_details:
        judgment["usage_details"] = call.usage_details
    if call.cost_details:
        judgment["cost_details"] = call.cost_details
    if prompt_version and not canvas_prompt:
        judgment["prompt_version"] = prompt_version
    schema_digest = schema_hash(explainability_schema)
    if schema_digest:
        judgment["explainability_schema_hash"] = schema_digest
    return judgment


def _invoke_judge(*, prompt: str, model: str, cwd: Path) -> LlmCallResult:
    if os.environ.get("CURSOR_API_KEY"):
        return cursor_prompt(
            prompt=prompt + "\n\nReturn ONLY the JSON object. No markdown fences. No file edits.",
            model=model,
            cwd=cwd,
            mode="ask",
            error_cls=EvaluationAgentError,
        )
    if os.environ.get("OPENAI_API_KEY"):
        return openai_chat_json(
            prompt=prompt,
            model=model,
            system=(
                "Return only valid JSON for an AutoResearch evaluation judgment "
                "with summary, recommendation, rationale, risks, and explainability "
                "when a custom schema is provided."
            ),
            error_cls=EvaluationAgentError,
        )
    raise EvaluationAgentError(
        "evaluation agent needs CURSOR_API_KEY or OPENAI_API_KEY "
        "to author a real judgment"
    )


def _record_call(
    obs: Any,
    *,
    call: LlmCallResult,
    prompt: str,
    raw: str,
    observability_meta: dict[str, Any] | None,
    trial_id: str,
    hypothesis_id: str,
    metrics: dict[str, float],
    deltas: dict[str, float],
    link_prompt: bool,
    schema_valid: float,
    parse_error: bool,
    recommendation: str | None,
) -> Any:
    generation = obs.record_generation(
        name="evaluation_agent",
        input_text=prompt,
        output_text=raw,
        metadata=_meta(
            observability_meta,
            trial_id=trial_id,
            hypothesis_id=hypothesis_id,
            metrics=metrics,
            deltas=deltas,
            recommendation=recommendation,
            llm_provider=call.provider,
            cursor_run_id=call.run_id,
        ),
        session_id=_session_id(observability_meta),
        prompt_name=PROMPT_NAME if link_prompt else None,
        **call.as_observability_kwargs(),
    )
    obs.score(
        trace_id=generation.trace_id,
        name="schema_valid",
        value=schema_valid,
        comment="evaluation JSON parse failed" if parse_error else None,
    )
    if parse_error:
        obs.flush()
    return generation


def _gate_aligned(
    *,
    recommendation: str,
    metrics: dict[str, float],
    champion_metrics: dict[str, float],
    primary_metric: str,
    direction: str,
    min_delta: float,
) -> float:
    if primary_metric not in metrics:
        return 1.0 if recommendation == "retry" else 0.0
    value = float(metrics[primary_metric])
    baseline = champion_metrics.get(primary_metric)
    if baseline is None:
        return 1.0 if recommendation in {"accept", "retry"} else 0.0
    baseline_f = float(baseline)
    if direction == "minimize":
        clears = value <= baseline_f - min_delta
    else:
        clears = value >= baseline_f + min_delta
    if clears:
        return 1.0 if recommendation == "accept" else 0.0
    if abs(value - baseline_f) < max(min_delta, 1e-12):
        return 1.0 if recommendation in {"reject", "retry"} else 0.0
    return 1.0 if recommendation == "reject" else 0.0


def _meta(
    observability_meta: dict[str, Any] | None,
    **extra: Any,
) -> dict[str, Any]:
    payload = dict(observability_meta or {})
    payload.update({key: value for key, value in extra.items() if value is not None})
    payload.setdefault("tags", ["autoresearch", "evaluation_agent"])
    return payload


def _session_id(observability_meta: dict[str, Any] | None) -> str | None:
    if not observability_meta:
        return None
    run_id = observability_meta.get("run_id")
    return str(run_id) if run_id else None


def _judgment_prompt(
    *,
    node_config: dict[str, Any],
    trial_id: str,
    hypothesis_id: str,
    hypothesis_title: str,
    hypothesis_description: str,
    what_changed: str,
    metrics: dict[str, float],
    champion_metrics: dict[str, float],
    deltas: dict[str, float],
    signals: dict[str, list[str]],
    primary_metric: str,
    direction: str,
    min_delta: float,
    stdout_excerpt: str,
    explainability_schema: dict[str, Any] | None = None,
) -> str:
    system_prompt = str(node_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    explainability_block = prompt_fragment(explainability_schema)
    shape = """{
  "summary": "1-3 sentence judgment of what happened and what it means",
  "recommendation": "accept" | "reject" | "retry",
  "rationale": "why that recommendation, citing primary metric vs champion and min_delta",
  "risks": "what could make this reading misleading (noise, confounders, incomplete run)"
}"""
    if explainability_schema is not None:
        shape = """{
  "summary": "1-3 sentence judgment of what happened and what it means",
  "recommendation": "accept" | "reject" | "retry",
  "rationale": "why that recommendation, citing primary metric vs champion and min_delta",
  "risks": "what could make this reading misleading (noise, confounders, incomplete run)",
  "explainability": { /* must match the custom explainability schema below */ }
}"""
    return f"""You are the AutoResearch evaluation agent for trial {trial_id}.

Write a REAL scientific judgment of this candidate — not a template restating the numbers.
Decide whether to accept, reject, or retry based on the gate and the evidence.
The metric gate still decides promotion; your recommendation is advisory but must be honest.

Return ONLY valid JSON with this shape:
{shape}
{explainability_block}
### Agent system prompt
{system_prompt}

### Trial
- hypothesis_id: {hypothesis_id}
- trial_id: {trial_id}
- title: {hypothesis_title or "(none)"}
- what_changed: {what_changed or "(unknown)"}

### Hypothesis brief (truncated)
{(hypothesis_description or "")[:2500]}

### Gate
- primary_metric: {primary_metric}
- direction: {direction}
- min_delta: {min_delta}

### Metrics
- candidate: {json.dumps(metrics, sort_keys=True)}
- champion: {json.dumps(champion_metrics, sort_keys=True)}
- deltas (candidate - champion): {json.dumps(deltas, sort_keys=True)}
- signals: {json.dumps(signals, sort_keys=True)}

### Eval stdout excerpt
```
{(stdout_excerpt or "")[:1500]}
```

Rules:
- If primary metric clearly beats champion by min_delta in the right direction → accept.
- If it clearly fails → reject, and say what the next experiment should avoid.
- If eval looks noisy, incomplete, or the gain is within noise / unexplained → retry.
- Do not invent metrics. Do not claim improvement when deltas show regression.
- Return ONLY the JSON object. No markdown fences.
"""


def _parse_judgment_json(
    raw: str,
    *,
    explainability_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise EvaluationAgentError("evaluation agent returned empty judgment")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationAgentError(f"evaluation agent returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationAgentError("evaluation judgment JSON must be an object")

    recommendation = str(payload.get("recommendation") or "").strip().lower()
    if recommendation not in {"accept", "reject", "retry"}:
        raise EvaluationAgentError(
            "evaluation judgment must set recommendation to accept|reject|retry"
        )
    summary = str(payload.get("summary") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    risks = str(payload.get("risks") or "").strip()
    if not summary or not rationale:
        raise EvaluationAgentError("evaluation judgment missing summary/rationale")
    result: dict[str, Any] = {
        "summary": summary[:2000],
        "recommendation": recommendation,
        "rationale": rationale[:4000],
        "risks": risks[:2000] or "Agent did not list residual risks.",
    }
    try:
        explainability = validate_explainability(
            payload.get("explainability"),
            explainability_schema,
        )
    except ExplainabilitySchemaError as exc:
        raise EvaluationAgentError(str(exc)) from exc
    if explainability is not None:
        result["explainability"] = explainability
    return result
