"""Langfuse adapter — only module allowed to import langfuse."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from .protocol import GenerationRecord

logger = logging.getLogger(__name__)


def _clean_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values so Langfuse UI is not littered with blanks."""
    cleaned: dict[str, Any] = {}
    for key, value in meta.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        cleaned[key] = value
    return cleaned


class LangfuseObservability:
    """Best-effort Langfuse backend. Never raises into the research loop."""

    def __init__(
        self,
        *,
        public_key: str,
        secret_key: str,
        host: str,
    ) -> None:
        self._public_key = public_key
        self._secret_key = secret_key
        self._host = host.rstrip("/")
        self._client: Any | None = None
        self._init_error: str | None = None
        self._ensure_client()

    @property
    def backend_name(self) -> str:
        return "langfuse"

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if self._init_error is not None:
            return None
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            self._init_error = f"langfuse package not installed: {exc}"
            logger.warning("observability langfuse unavailable: %s", self._init_error)
            return None
        try:
            self._client = Langfuse(
                public_key=self._public_key,
                secret_key=self._secret_key,
                host=self._host,
            )
        except Exception as exc:  # noqa: BLE001 — soft-fail vendor init
            self._init_error = str(exc)
            logger.warning("observability langfuse init failed: %s", exc)
            self._client = None
        return self._client

    def get_prompt(self, name: str, fallback: str) -> tuple[str, str]:
        client = self._ensure_client()
        if client is None:
            return fallback, ""
        try:
            prompt = client.get_prompt(name)
            text = prompt.compile() if hasattr(prompt, "compile") else str(
                getattr(prompt, "prompt", None) or prompt
            )
            if not isinstance(text, str) or not text.strip():
                text = fallback
            version = ""
            if hasattr(prompt, "version") and prompt.version is not None:
                version = str(prompt.version)
            return text, version
        except Exception as exc:  # noqa: BLE001
            logger.debug("langfuse get_prompt(%s) failed: %s", name, exc)
            return fallback, ""

    def record_generation(
        self,
        *,
        name: str,
        input_text: str,
        output_text: str,
        model: str,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        prompt_name: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
        model_parameters: dict[str, Any] | None = None,
    ) -> GenerationRecord:
        client = self._ensure_client()
        if client is None:
            return GenerationRecord(backend="langfuse")

        meta = _clean_metadata(dict(metadata or {}))
        prompt_version = ""
        prompt_obj = None
        # Only link a managed prompt when it actually exists in Langfuse.
        if prompt_name:
            try:
                prompt_obj = client.get_prompt(prompt_name)
                if hasattr(prompt_obj, "version") and prompt_obj.version is not None:
                    prompt_version = str(prompt_obj.version)
            except Exception:  # noqa: BLE001
                prompt_obj = None

        usage = {k: int(v) for k, v in (usage_details or {}).items() if isinstance(v, int)}
        costs = {
            k: float(v)
            for k, v in (cost_details or {}).items()
            if isinstance(v, (int, float))
        }
        params = _clean_metadata(dict(model_parameters or {}))

        try:
            if hasattr(client, "start_as_current_observation"):
                trace_id = self._record_via_observation(
                    client,
                    name=name,
                    input_text=input_text,
                    output_text=output_text,
                    model=model,
                    meta=meta,
                    session_id=session_id,
                    prompt_obj=prompt_obj,
                    usage_details=usage or None,
                    cost_details=costs or None,
                    model_parameters=params or None,
                )
            else:
                trace_id = self._record_via_legacy(
                    client,
                    name=name,
                    input_text=input_text,
                    output_text=output_text,
                    model=model,
                    meta=meta,
                    session_id=session_id,
                    prompt_obj=prompt_obj,
                    usage_details=usage or None,
                    cost_details=costs or None,
                    model_parameters=params or None,
                )
            extra: dict[str, Any] = {}
            if usage:
                extra["usage_details"] = usage
            if costs:
                extra["cost_details"] = costs
            return GenerationRecord(
                trace_id=trace_id or "",
                prompt_version=prompt_version,
                backend="langfuse",
                extra=extra,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("langfuse record_generation failed: %s", exc)
            return GenerationRecord(backend="langfuse")

    def _record_via_observation(
        self,
        client: Any,
        *,
        name: str,
        input_text: str,
        output_text: str,
        model: str,
        meta: dict[str, Any],
        session_id: str | None,
        prompt_obj: Any,
        usage_details: dict[str, int] | None,
        cost_details: dict[str, float] | None,
        model_parameters: dict[str, Any] | None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "as_type": "generation",
            "name": name,
            "input": input_text,
            "output": output_text,
            "model": model,
            "metadata": meta,
        }
        if prompt_obj is not None:
            kwargs["prompt"] = prompt_obj
        if usage_details:
            kwargs["usage_details"] = usage_details
        if cost_details:
            kwargs["cost_details"] = cost_details
        if model_parameters:
            kwargs["model_parameters"] = model_parameters
        with client.start_as_current_observation(**kwargs) as generation:
            if session_id and hasattr(client, "update_current_trace"):
                with contextlib.suppress(Exception):
                    client.update_current_trace(
                        name=name,
                        session_id=session_id,
                        metadata=meta,
                        tags=list(meta.get("tags") or []),
                        input=input_text,
                        output=output_text,
                    )
            # Also update generation if usage arrived late (already set via kwargs).
            if (usage_details or cost_details) and hasattr(generation, "update"):
                with contextlib.suppress(Exception):
                    generation.update(
                        usage_details=usage_details,
                        cost_details=cost_details,
                        model=model,
                        output=output_text,
                    )
            trace_id = ""
            if hasattr(client, "get_current_trace_id"):
                trace_id = str(client.get_current_trace_id() or "")
            if not trace_id and hasattr(generation, "trace_id"):
                trace_id = str(generation.trace_id or "")
            return trace_id

    def _record_via_legacy(
        self,
        client: Any,
        *,
        name: str,
        input_text: str,
        output_text: str,
        model: str,
        meta: dict[str, Any],
        session_id: str | None,
        prompt_obj: Any,
        usage_details: dict[str, int] | None,
        cost_details: dict[str, float] | None,
        model_parameters: dict[str, Any] | None,
    ) -> str:
        trace = client.trace(
            name=name,
            input=input_text,
            output=output_text,
            metadata=meta,
            session_id=session_id,
            tags=list(meta.get("tags") or []),
        )
        gen_kwargs: dict[str, Any] = {
            "name": name,
            "model": model,
            "input": input_text,
            "output": output_text,
            "metadata": meta,
        }
        if prompt_obj is not None:
            gen_kwargs["prompt"] = prompt_obj
        if usage_details:
            gen_kwargs["usage"] = usage_details
            gen_kwargs["usage_details"] = usage_details
        if cost_details:
            gen_kwargs["cost_details"] = cost_details
        if model_parameters:
            gen_kwargs["model_parameters"] = model_parameters
        generation = trace.generation(**gen_kwargs)
        if hasattr(generation, "end"):
            end_kwargs: dict[str, Any] = {"output": output_text}
            if usage_details:
                end_kwargs["usage_details"] = usage_details
            if cost_details:
                end_kwargs["cost_details"] = cost_details
            try:
                generation.end(**end_kwargs)
            except TypeError:
                generation.end()
        return str(getattr(trace, "id", "") or "")

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        if not trace_id:
            return
        client = self._ensure_client()
        if client is None:
            return
        try:
            kwargs: dict[str, Any] = {
                "trace_id": trace_id,
                "name": name,
                "value": float(value),
                "data_type": "NUMERIC",
            }
            if comment:
                kwargs["comment"] = comment
            if hasattr(client, "create_score"):
                client.create_score(**kwargs)
            elif hasattr(client, "score"):
                client.score(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("langfuse score failed: %s", exc)

    def flush(self) -> None:
        client = self._ensure_client()
        if client is None:
            return
        try:
            if hasattr(client, "flush"):
                client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.debug("langfuse flush failed: %s", exc)
