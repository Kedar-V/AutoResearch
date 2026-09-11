from __future__ import annotations

from typing import TypedDict


class ObservabilityMetadata(TypedDict, total=False):
    project_id: str
    run_id: str
    node_id: str
    node_type: str
    hypothesis_id: str
    trial_id: str
    tags: list[str]
