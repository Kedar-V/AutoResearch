"""User-defined explainability schemas for the evaluation agent only.

Core loop fields (recommendation, metrics, gate) stay fixed. Custom fields live
under ``explainability`` and are validated against an optional JSON Schema on
the evaluation node. Hypothesis/execution agents must not import this module.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class ExplainabilitySchemaError(ValueError):
    """Raised when an explainability schema or payload is invalid."""


def load_explainability_schema(node_config: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalized object schema from node config, or None if unset."""
    raw = node_config.get("explainability_schema")
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExplainabilitySchemaError(
                f"explainability_schema is not valid JSON: {exc}"
            ) from exc
    if not isinstance(raw, dict):
        raise ExplainabilitySchemaError("explainability_schema must be a JSON object")
    if not raw:
        return None
    schema_type = raw.get("type", "object")
    if schema_type != "object":
        raise ExplainabilitySchemaError(
            "explainability_schema.type must be 'object' (or omitted)"
        )
    properties = raw.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise ExplainabilitySchemaError("explainability_schema.properties must be an object")
    required = raw.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ExplainabilitySchemaError(
                "explainability_schema.required must be an array of strings"
            )
    return raw


def schema_hash(schema: dict[str, Any] | None) -> str:
    if not schema:
        return ""
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def prompt_fragment(schema: dict[str, Any] | None) -> str:
    """Instruction block for the evaluation agent prompt."""
    if not schema:
        return ""
    return (
        "\n### Custom explainability schema\n"
        "Also include an \"explainability\" object that matches this JSON Schema "
        "exactly (required keys must be present):\n"
        f"{json.dumps(schema, indent=2)}\n"
        "Put explainability beside summary/recommendation/rationale/risks — "
        "do not invent core metrics. Custom fields express your judgment criteria "
        "and narrative structure only.\n"
    )


def validate_explainability(
    payload: Any,
    schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate ``explainability`` against the user schema.

    Returns the validated object, or None when no schema is configured.
    """
    if schema is None:
        if payload is None:
            return None
        if isinstance(payload, dict):
            return payload
        raise ExplainabilitySchemaError(
            "explainability must be an object when present without a schema"
        )

    if payload is None:
        raise ExplainabilitySchemaError(
            "evaluation judgment missing explainability required by explainability_schema"
        )
    if not isinstance(payload, dict):
        raise ExplainabilitySchemaError("explainability must be a JSON object")

    _validate_against_schema(payload, schema, path="explainability")
    return payload


def _validate_against_schema(value: Any, schema: dict[str, Any], *, path: str) -> None:
    expected = schema.get("type")
    if expected == "object" or (expected is None and "properties" in schema):
        if not isinstance(value, dict):
            raise ExplainabilitySchemaError(f"{path} must be an object")
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise ExplainabilitySchemaError(f"{path} schema properties must be an object")
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ExplainabilitySchemaError(
                    f"{path} has unexpected keys: {', '.join(sorted(unknown))}"
                )
        required = schema.get("required") or []
        if isinstance(required, list):
            missing = [key for key in required if key not in value]
            if missing:
                raise ExplainabilitySchemaError(
                    f"{path} missing required keys: {', '.join(missing)}"
                )
        for key, child_schema in properties.items():
            if key not in value:
                continue
            if not isinstance(child_schema, dict):
                continue
            _validate_against_schema(value[key], child_schema, path=f"{path}.{key}")
        return

    if expected == "array":
        if not isinstance(value, list):
            raise ExplainabilitySchemaError(f"{path} must be an array")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_against_schema(item, item_schema, path=f"{path}[{index}]")
        return

    if expected == "string":
        if not isinstance(value, str):
            raise ExplainabilitySchemaError(f"{path} must be a string")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            raise ExplainabilitySchemaError(f"{path} shorter than minLength {min_length}")
        return

    if expected == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ExplainabilitySchemaError(f"{path} must be a number")
        _check_numeric_bounds(value, schema, path=path)
        return

    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ExplainabilitySchemaError(f"{path} must be an integer")
        _check_numeric_bounds(value, schema, path=path)
        return

    if expected == "boolean":
        if not isinstance(value, bool):
            raise ExplainabilitySchemaError(f"{path} must be a boolean")
        return

    if expected is None:
        return

    raise ExplainabilitySchemaError(f"{path} uses unsupported schema type {expected!r}")


def _check_numeric_bounds(value: float, schema: dict[str, Any], *, path: str) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, (int, float)) and value < float(minimum):
        raise ExplainabilitySchemaError(f"{path} below minimum {minimum}")
    if isinstance(maximum, (int, float)) and value > float(maximum):
        raise ExplainabilitySchemaError(f"{path} above maximum {maximum}")


EXAMPLE_EXPLAINABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["confidence", "attribution"],
    "properties": {
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "How confident the judgment is (0-1)",
        },
        "attribution": {
            "type": "string",
            "description": "What change likely caused the metric movement",
        },
        "failure_modes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ways this reading could be misleading",
        },
    },
}
