"""Shared LLM call helpers that capture real usage/cost for observability."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LlmCallResult:
    """Outcome of one provider call with truthful telemetry (no estimates)."""

    text: str
    provider: str
    model: str
    usage_details: dict[str, int] = field(default_factory=dict)
    cost_details: dict[str, float] = field(default_factory=dict)
    duration_ms: int | None = None
    run_id: str = ""
    model_parameters: dict[str, Any] = field(default_factory=dict)

    def as_observability_kwargs(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "usage_details": dict(self.usage_details) if self.usage_details else None,
            "cost_details": dict(self.cost_details) if self.cost_details else None,
            "model_parameters": dict(self.model_parameters) if self.model_parameters else None,
        }
        return {key: value for key, value in payload.items() if value is not None}


def resolve_openai_model(model: str) -> str:
    openai_model = model.strip()
    if not openai_model or openai_model.startswith("composer") or openai_model == "auto":
        return os.environ.get("AUTORESEARCH_OPENAI_MODEL", "gpt-4.1")
    return openai_model


def usage_from_openai_body(body: dict[str, Any]) -> dict[str, int]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {}
    details: dict[str, int] = {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if isinstance(prompt, int):
        details["input"] = prompt
    if isinstance(completion, int):
        details["output"] = completion
    if isinstance(total, int):
        details["total"] = total
    # Newer OpenAI usage shapes
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, int) and cached:
            details["cache_read_input_tokens"] = cached
    return details


def usage_from_cursor_token_usage(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    details: dict[str, int] = {}
    for attr, key in (
        ("input_tokens", "input"),
        ("output_tokens", "output"),
        ("total_tokens", "total"),
        ("cache_read_tokens", "cache_read_input_tokens"),
        ("cache_write_tokens", "cache_creation_input_tokens"),
        ("reasoning_tokens", "output_reasoning"),
    ):
        value = getattr(usage, attr, None)
        if isinstance(value, int) and value:
            details[key] = value
    return details


def cost_from_cursor_usage_cost(cost: Any) -> dict[str, float]:
    """Convert Cursor UsageCost (float cents) to Langfuse USD cost_details."""
    if cost is None:
        return {}
    charged = getattr(cost, "charged_cents", None)
    raw = getattr(cost, "raw_cost_cents", None)
    details: dict[str, float] = {}
    if isinstance(charged, (int, float)):
        details["total"] = float(charged) / 100.0
    if isinstance(raw, (int, float)):
        details["raw_total"] = float(raw) / 100.0
    return details


def cursor_prompt(
    *,
    prompt: str,
    model: str,
    cwd: Path,
    mode: str | None = None,
    error_cls: type[Exception],
) -> LlmCallResult:
    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
    except ImportError as exc:
        raise error_cls("cursor-sdk is not installed") from exc

    model_id = model.strip() or "composer-2.5"
    options_kwargs: dict[str, Any] = {
        "api_key": os.environ.get("CURSOR_API_KEY"),
        "model": model_id,
        "local": LocalAgentOptions(cwd=str(cwd)),
    }
    if mode:
        options_kwargs["mode"] = mode

    agent = None
    try:
        agent = Agent.create(AgentOptions(**options_kwargs))
        result = agent.send(prompt).wait()
        if getattr(result, "status", None) == "error":
            raise error_cls(f"cursor agent run failed: {getattr(result, 'id', 'error')}")
        text = getattr(result, "result", None) or getattr(result, "text", None) or ""
        usage_details = usage_from_cursor_token_usage(getattr(result, "usage", None))
        cost_details: dict[str, float] = {}
        # Prefer billed totals from get_usage when the backend reports them.
        try:
            billed = agent.get_usage()
            if not usage_details:
                usage_details = usage_from_cursor_token_usage(getattr(billed, "usage", None))
            cost_details = cost_from_cursor_usage_cost(getattr(billed, "cost", None))
        except Exception:  # noqa: BLE001 — usage/cost optional; never invent
            pass
        actual_model = model_id
        model_sel = getattr(result, "model", None)
        if model_sel is not None:
            actual_model = str(
                getattr(model_sel, "id", None)
                or getattr(model_sel, "name", None)
                or model_id
            )
        return LlmCallResult(
            text=str(text),
            provider="cursor-sdk",
            model=actual_model,
            usage_details=usage_details,
            cost_details=cost_details,
            duration_ms=int(getattr(result, "duration_ms", 0) or 0) or None,
            run_id=str(getattr(result, "id", "") or ""),
        )
    except CursorAgentError as exc:
        raise error_cls(f"cursor agent failed: {exc}") from exc
    finally:
        if agent is not None:
            with_context = getattr(agent, "close", None)
            if callable(with_context):
                with_context()


def openai_chat_json(
    *,
    prompt: str,
    model: str,
    system: str,
    error_cls: type[Exception],
    temperature: float = 0.2,
) -> LlmCallResult:
    openai_model = resolve_openai_model(model)
    payload = {
        "model": openai_model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise error_cls(f"openai request failed: {exc.code} {detail[:500]}") from exc

    content = str(body["choices"][0]["message"]["content"])
    return LlmCallResult(
        text=content,
        provider="openai",
        model=str(body.get("model") or openai_model),
        usage_details=usage_from_openai_body(body),
        # Cost left empty: Langfuse prices known OpenAI models from usage_details.
        cost_details={},
        model_parameters={"temperature": temperature, "response_format": "json_object"},
    )
