"""Apply hypothesis edits inside a trial worktree via Cursor or OpenAI."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .llm_telemetry import (
    LlmCallResult,
    cursor_prompt,
    resolve_openai_model,
    usage_from_openai_body,
)
from .observability import get_observability

PROMPT_NAME = "autoresearch/execution"


class CodeAgentError(RuntimeError):
    pass


def apply_hypothesis_edits(
    *,
    worktree: Path,
    brief: str,
    allowed_paths: list[str],
    model: str,
    title: str = "",
    observability_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not allowed_paths:
        raise CodeAgentError("execution agent requires a script allow-list of editable paths")
    worktree = worktree.resolve()
    obs = get_observability()
    _managed, prompt_version = obs.get_prompt(PROMPT_NAME, "")
    link_prompt = bool(prompt_version)
    prompt = _build_prompt(brief=brief, allowed_paths=allowed_paths, worktree=worktree, title=title)

    if os.environ.get("CURSOR_API_KEY"):
        call = cursor_prompt(
            prompt=prompt,
            model=model,
            cwd=worktree,
            mode=None,
            error_cls=CodeAgentError,
        )
        result = {"stdout": call.text, "stderr": ""}
    elif os.environ.get("OPENAI_API_KEY"):
        call, result = _via_openai(
            worktree=worktree,
            prompt=prompt,
            model=model,
            allowed_paths=allowed_paths,
        )
    else:
        raise CodeAgentError(
            "execution agent needs CURSOR_API_KEY (preferred for composer-2.5) "
            "or OPENAI_API_KEY to edit candidate files"
        )

    changed = _changed_allowed_files(worktree, allowed_paths)
    output_text = str(result.get("stdout") or "")
    if result.get("stderr"):
        output_text = f"{output_text}\n{result.get('stderr')}".strip()
    # Prefer real file-change summary over empty model chatter when listing output.
    if not output_text.strip() and changed:
        output_text = json.dumps({"changed_paths": changed})

    generation = obs.record_generation(
        name="execution_agent",
        input_text=prompt,
        output_text=output_text,
        metadata=_meta(
            observability_meta,
            changed_paths=changed,
            llm_provider=call.provider,
            cursor_run_id=call.run_id,
        ),
        session_id=_session_id(observability_meta),
        prompt_name=PROMPT_NAME if link_prompt else None,
        **call.as_observability_kwargs(),
    )
    edited = 1.0 if changed else 0.0
    obs.score(
        trace_id=generation.trace_id,
        name="edited_allowlist",
        value=edited,
        comment=", ".join(changed) if changed else "no allow-listed files changed",
    )
    obs.flush()

    if not changed:
        raise CodeAgentError(
            "execution agent finished without modifying any allow-listed files "
            f"({', '.join(allowed_paths)})"
        )
    payload = {
        "backend": call.provider,
        "model": call.model,
        "requested_model": model,
        "changed_paths": changed,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        **generation.as_dict(),
    }
    if call.usage_details:
        payload["usage_details"] = call.usage_details
    if call.cost_details:
        payload["cost_details"] = call.cost_details
    if prompt_version:
        payload["prompt_version"] = prompt_version
    return payload


def summarize_diff(diff: str, *, limit: int = 12) -> str:
    if not diff.strip():
        return "No file changes."
    files = re.findall(r"^diff --git a/(.+?) b/(.+)$", diff, flags=re.MULTILINE)
    names = [right for _left, right in files]
    if not names:
        return "Code changes committed."
    shown = ", ".join(names[:limit])
    extra = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return f"Modified {shown}{extra}."


def _meta(
    observability_meta: dict[str, Any] | None,
    *,
    changed_paths: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = dict(observability_meta or {})
    payload.update({key: value for key, value in extra.items() if value not in ("", None)})
    payload.setdefault("tags", ["autoresearch", "execution_agent"])
    if changed_paths is not None:
        payload["changed_paths"] = changed_paths
    return payload


def _session_id(observability_meta: dict[str, Any] | None) -> str | None:
    if not observability_meta:
        return None
    run_id = observability_meta.get("run_id")
    return str(run_id) if run_id else None


def _build_prompt(*, brief: str, allowed_paths: list[str], worktree: Path, title: str) -> str:
    file_sections: list[str] = []
    for relative in allowed_paths:
        path = worktree / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        file_sections.append(f"### {relative}\n```\n{content}\n```")
    allow = ", ".join(f"`{path}`" for path in allowed_paths)
    return f"""You are the AutoResearch execution agent.

Implement the hypothesis below by editing ONLY these files: {allow}.
Do not create new files outside that allow-list.
Do not modify evaluators, data prep, lockfiles, or docs.
Make one focused, attributable change that matches the hypothesis.
Prefer concrete code/hyperparameter edits.

Hypothesis title: {title or '(untitled)'}

## Hypothesis brief
{brief.strip() or '(empty brief)'}

## Current allow-listed file contents
{chr(10).join(file_sections) or '(none found on disk)'}

After editing, stop. Do not run long training yourself;
the trusted evaluator will run training next.
"""


def _via_openai(
    *,
    worktree: Path,
    prompt: str,
    model: str,
    allowed_paths: list[str],
) -> tuple[LlmCallResult, dict[str, str]]:
    openai_model = resolve_openai_model(model)
    temperature = 0.2
    system = (
        "Return ONLY valid JSON with shape "
        '{"files": {"relative/path": "full new file contents"}}. '
        "Include every file you change. Paths must be from the allow-list. "
        "No markdown fences."
    )
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
        raise CodeAgentError(f"openai request failed: {exc.code} {detail[:500]}") from exc

    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    files = parsed.get("files")
    if not isinstance(files, dict) or not files:
        raise CodeAgentError("openai agent returned no files to write")

    allow = set(allowed_paths)
    written: list[str] = []
    for relative, text in files.items():
        path = str(relative).strip().lstrip("./")
        if path not in allow:
            raise CodeAgentError(f"openai agent attempted illegal path: {path}")
        if not isinstance(text, str):
            raise CodeAgentError(f"openai agent file content for {path} must be a string")
        target = worktree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(path)

    call = LlmCallResult(
        text=json.dumps({"written": written}),
        provider="openai",
        model=str(body.get("model") or openai_model),
        usage_details=usage_from_openai_body(body),
        model_parameters={"temperature": temperature, "response_format": "json_object"},
    )
    return call, {"stdout": call.text, "stderr": ""}


def _changed_allowed_files(worktree: Path, allowed_paths: list[str]) -> list[str]:
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *allowed_paths],
        cwd=worktree,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return []
    changed: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path in allowed_paths:
            changed.append(path)
    return changed
