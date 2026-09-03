#!/usr/bin/env python3
"""Perform dependency-free structural checks on repository JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def main() -> None:
    schema_ids: set[str] = set()
    paths = sorted(CONTRACTS.glob("*.schema.json"))
    if not paths:
        raise SystemExit("No contract schemas found")

    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise SystemExit(f"{path}: expected JSON Schema Draft 2020-12")
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise SystemExit(f"{path}: missing $id")
        if schema_id in schema_ids:
            raise SystemExit(f"{path}: duplicate $id {schema_id}")
        schema_ids.add(schema_id)
        if schema.get("type") != "object":
            raise SystemExit(f"{path}: root type must be object")

    print(f"Validated {len(paths)} contract schemas")


if __name__ == "__main__":
    main()
