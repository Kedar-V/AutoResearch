"""Generate a concrete hypothesis experiment plan via Cursor or OpenAI."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .hypothesis_brief import (
    DEFAULT_SYSTEM_PROMPT,
    _editable_surfaces,
    _history_section,
    _success_criteria,
    _text,
)
from .llm_telemetry import LlmCallResult, cursor_prompt, openai_chat_json
from .observability import get_observability

PROMPT_NAME = "autoresearch/hypothesis"


class HypothesisPlanError(RuntimeError):
    pass


def plan_hypothesis(
    *,
    hypothesis_code: str,
    node_config: dict[str, Any],
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
    context: dict[str, Any],
    allowed_paths: list[str] | None,
    gate: dict[str, Any] | None,
    project_root: Path,
    history_window: int,
    observability_meta: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Return (title, detailed plan markdown, raw plan dict)."""
    requested_model = str(node_config.get("model") or "composer-2.5")
    obs = get_observability()
    canvas_prompt = str(node_config.get("system_prompt") or "").strip()
    managed_prompt, prompt_version = obs.get_prompt(PROMPT_NAME, DEFAULT_SYSTEM_PROMPT)
    effective_system = canvas_prompt or managed_prompt
    node_config = {**node_config, "system_prompt": effective_system}
    link_prompt = bool(prompt_version) and not canvas_prompt

    prompt = _planner_prompt(
        hypothesis_code=hypothesis_code,
        node_config=node_config,
        recent_hypotheses=recent_hypotheses,
        recent_trials=recent_trials,
        context=context,
        allowed_paths=allowed_paths,
        gate=gate,
        project_root=project_root,
        history_window=history_window,
    )

    call = _invoke_planner(prompt=prompt, model=requested_model, cwd=project_root)
    raw = call.text

    schema_valid = 1.0
    try:
        plan = _parse_plan_json(raw)
    except HypothesisPlanError:
        schema_valid = 0.0
        _record_call(
            obs,
            call=call,
            prompt=prompt,
            raw=raw,
            observability_meta=observability_meta,
            hypothesis_code=hypothesis_code,
            link_prompt=link_prompt,
            schema_valid=schema_valid,
            parse_error=True,
        )
        raise

    title = _text(plan.get("title")) or f"{hypothesis_code} focused experiment"
    title = re.sub(r"\s+", " ", title).strip()[:160]
    description = _render_plan_markdown(
        hypothesis_code=hypothesis_code,
        plan=plan,
        recent_hypotheses=recent_hypotheses,
        recent_trials=recent_trials,
        context=context,
        allowed_paths=allowed_paths,
        gate=gate,
        history_window=history_window,
        system_prompt=effective_system,
    )
    generation = _record_call(
        obs,
        call=call,
        prompt=prompt,
        raw=raw,
        observability_meta=observability_meta,
        hypothesis_code=hypothesis_code,
        link_prompt=link_prompt,
        schema_valid=schema_valid,
        parse_error=False,
    )

    meta = {
        "backend": call.provider,
        "model": call.model,
        "requested_model": requested_model,
        "plan": plan,
        **generation.as_dict(),
    }
    if call.usage_details:
        meta["usage_details"] = call.usage_details
    if call.cost_details:
        meta["cost_details"] = call.cost_details
    if prompt_version and not canvas_prompt:
        meta["prompt_version"] = prompt_version
    return title, description, meta


def _invoke_planner(*, prompt: str, model: str, cwd: Path) -> LlmCallResult:
    if os.environ.get("CURSOR_API_KEY"):
        return cursor_prompt(
            prompt=prompt + "\n\nReturn ONLY the JSON object. No markdown fences. No file edits.",
            model=model,
            cwd=cwd,
            mode="ask",
            error_cls=HypothesisPlanError,
        )
    if os.environ.get("OPENAI_API_KEY"):
        return openai_chat_json(
            prompt=prompt,
            model=model,
            system="Return only valid JSON for a concrete AutoResearch experiment plan.",
            error_cls=HypothesisPlanError,
        )
    raise HypothesisPlanError(
        "hypothesis planner needs CURSOR_API_KEY or OPENAI_API_KEY "
        "to author a detailed experiment plan"
    )


def _record_call(
    obs: Any,
    *,
    call: LlmCallResult,
    prompt: str,
    raw: str,
    observability_meta: dict[str, Any] | None,
    hypothesis_code: str,
    link_prompt: bool,
    schema_valid: float,
    parse_error: bool,
) -> Any:
    generation = obs.record_generation(
        name="hypothesis_planner",
        input_text=prompt,
        output_text=raw,
        metadata=_meta(
            observability_meta,
            hypothesis_code=hypothesis_code,
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
        comment="planner JSON parse failed" if parse_error else None,
    )
    obs.flush()
    return generation


def _meta(
    observability_meta: dict[str, Any] | None,
    **extra: Any,
) -> dict[str, Any]:
    payload = dict(observability_meta or {})
    payload.update({key: value for key, value in extra.items() if value not in ("", None)})
    payload.setdefault("tags", ["autoresearch", "hypothesis_planner"])
    return payload


def _session_id(observability_meta: dict[str, Any] | None) -> str | None:
    if not observability_meta:
        return None
    run_id = observability_meta.get("run_id")
    return str(run_id) if run_id else None


def _planner_prompt(
    *,
    hypothesis_code: str,
    node_config: dict[str, Any],
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
    context: dict[str, Any],
    allowed_paths: list[str] | None,
    gate: dict[str, Any] | None,
    project_root: Path,
    history_window: int,
) -> str:
    allow = allowed_paths or []
    file_sections: list[str] = []
    for relative in allow:
        path = project_root / relative
        if path.is_file():
            file_sections.append(f"### {relative}\n```\n{path.read_text(encoding='utf-8')}\n```")

    system_prompt = str(node_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip()
    seed = _text(node_config.get("description"))
    return f"""You are the AutoResearch hypothesis planner for {hypothesis_code}.

Author ONE concrete experiment plan. Do not write vague goals like "improve the metric"
or "extend accepted direction". Name the exact change.

Return ONLY valid JSON with this shape:
{{
  "title": "short specific title naming the actual change",
  "objective": "metric + direction + why this should beat the champion",
  "exact_edits": [
    {{
      "path": "train.py",
      "change": "what to change (symbols/hyperparams/logic)",
      "why": "expected effect"
    }}
  ],
  "rationale": "how this uses what worked and avoids what failed from recent history",
  "risks": "failure modes and how we detect them",
  "success_check": "numeric gate condition",
  "implementation_steps": ["step 1", "step 2", "step 3"]
}}

Constraints:
- Edit only: {', '.join(allow) if allow else '(none configured)'}
- Prefer one focused change
- Do not modify evaluators/data/deps
- Do not restate generic instructions; be specific to the current code and history

Operator system prompt:
{system_prompt}

Operator seed notes:
{seed or '(none)'}

Success criteria:
{_success_criteria(gate, context)}

Editable surfaces:
{_editable_surfaces(allow)}

Recent history (last {min(history_window, len(recent_hypotheses))} / {history_window}):
{_history_section(recent_hypotheses, recent_trials)}

Current allow-listed files:
{chr(10).join(file_sections) or '(none on disk)'}
"""


def _render_plan_markdown(
    *,
    hypothesis_code: str,
    plan: dict[str, Any],
    recent_hypotheses: list[dict[str, Any]],
    recent_trials: list[dict[str, Any]],
    context: dict[str, Any],
    allowed_paths: list[str] | None,
    gate: dict[str, Any] | None,
    history_window: int,
    system_prompt: str,
) -> str:
    edits = plan.get("exact_edits") or []
    edit_lines: list[str] = []
    if isinstance(edits, list):
        for item in edits:
            if not isinstance(item, dict):
                continue
            edit_lines.append(
                f"- `{_text(item.get('path'))}`: {_text(item.get('change'))} "
                f"(why: {_text(item.get('why'))})"
            )
    steps = plan.get("implementation_steps") or []
    step_lines = [f"{idx}. {_text(step)}" for idx, step in enumerate(steps, start=1) if _text(step)]

    sections = [
        f"# Hypothesis {hypothesis_code}: {_text(plan.get('title'))}",
        "",
        "## Objective",
        _text(plan.get("objective")) or "(missing)",
        "",
        "## Exact edits",
        "\n".join(edit_lines) or "- (no edits listed)",
        "",
        "## Implementation steps",
        "\n".join(step_lines) or "1. Apply the exact edits above in allow-listed files only.",
        "",
        "## Rationale from recent history",
        _text(plan.get("rationale")) or "(missing)",
        "",
        "## Risks",
        _text(plan.get("risks")) or "(missing)",
        "",
        "## Success check",
        _text(plan.get("success_check")) or _success_criteria(gate, context),
        "",
        "## Constraints",
        _editable_surfaces(allowed_paths),
        "",
        "## Gate context",
        _success_criteria(gate, context),
        "",
        f"## Recent history (last {min(history_window, len(recent_hypotheses))}"
        f" of {history_window} max)",
        _history_section(recent_hypotheses, recent_trials),
        "",
        "## Execution instructions",
        "Implement THIS plan exactly. Do not invent a different experiment "
        "unless the plan is impossible.",
        "Keep changes confined to the listed paths. Prefer the stated single primary change.",
        "",
        "### Planner system prompt (reference)",
        system_prompt,
    ]
    return "\n".join(sections).strip() + "\n"


def _parse_plan_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise HypothesisPlanError("planner returned empty plan")
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
        raise HypothesisPlanError(f"planner returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise HypothesisPlanError("planner JSON must be an object")
    if not _text(payload.get("title")) or not _text(payload.get("objective")):
        raise HypothesisPlanError("planner JSON missing title/objective")
    edits = payload.get("exact_edits")
    if not isinstance(edits, list) or not edits:
        raise HypothesisPlanError("planner JSON must include exact_edits")
    return payload
