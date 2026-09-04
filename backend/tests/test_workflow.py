from __future__ import annotations

import pytest

from autoresearch_api.schemas import WorkflowDefinition
from autoresearch_api.workflow import WorkflowError, topological_order


def definition(edges: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "1",
            "id": "test-flow",
            "name": "Test",
            "nodes": [
                {
                    "id": "a",
                    "type": "script",
                    "name": "A",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                },
                {
                    "id": "b",
                    "type": "evaluation",
                    "name": "B",
                    "position": {"x": 1, "y": 0},
                    "config": {},
                },
            ],
            "edges": edges,
        }
    )


def test_topological_order() -> None:
    workflow = definition([{"id": "a-b", "source": "a", "target": "b"}])
    assert [node.id for node in topological_order(workflow)] == ["a", "b"]


def test_cycle_is_rejected() -> None:
    workflow = definition(
        [
            {"id": "a-b", "source": "a", "target": "b"},
            {"id": "b-a", "source": "b", "target": "a"},
        ]
    )
    with pytest.raises(WorkflowError, match="acyclic"):
        topological_order(workflow)
