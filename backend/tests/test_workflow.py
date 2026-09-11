from __future__ import annotations

import pytest

from autoresearch_api.schemas import WorkflowDefinition
from autoresearch_api.workflow import WorkflowError, compile_recipe, topological_order


def research_recipe(
    *,
    edges: list[dict] | None = None,
    extra_nodes: list[dict] | None = None,
    drop_node_id: str | None = None,
) -> WorkflowDefinition:
    nodes = [
        {
            "id": "hypothesis",
            "type": "hypothesis",
            "name": "H",
            "position": {"x": 0, "y": 0},
            "config": {"max_hypotheses": 3, "max_retries": 2},
        },
        {
            "id": "execution",
            "type": "execution",
            "name": "E",
            "position": {"x": 1, "y": 0},
            "config": {"command": ["python", "train.py"], "allowed_paths": ["train.py"]},
        },
        {
            "id": "eval_script",
            "type": "eval_script",
            "name": "S",
            "position": {"x": 1, "y": 1},
            "config": {"command": ["python", "eval.py"]},
        },
        {
            "id": "evaluation",
            "type": "evaluation",
            "name": "A",
            "position": {"x": 2, "y": 0},
            "config": {},
        },
        {
            "id": "gate",
            "type": "metric_gate",
            "name": "G",
            "position": {"x": 3, "y": 0},
            "config": {"metric": "score", "direction": "minimize", "baseline": 5},
        },
        {
            "id": "decision",
            "type": "git_decision",
            "name": "D",
            "position": {"x": 4, "y": 0},
            "config": {},
        },
    ]
    if drop_node_id:
        nodes = [node for node in nodes if node["id"] != drop_node_id]
    if extra_nodes:
        nodes.extend(extra_nodes)
    if edges is None:
        edges = [
            {"id": "h-e", "source": "hypothesis", "target": "execution"},
            {"id": "e-s", "source": "execution", "target": "eval_script"},
            {"id": "e-a", "source": "execution", "target": "evaluation"},
            {"id": "s-a", "source": "eval_script", "target": "evaluation"},
            {"id": "a-g", "source": "evaluation", "target": "gate"},
            {"id": "g-d", "source": "gate", "target": "decision"},
            {"id": "e-h", "source": "execution", "target": "hypothesis"},
            {"id": "d-h", "source": "decision", "target": "hypothesis"},
        ]
    known = {node["id"] for node in nodes}
    edges = [
        edge
        for edge in edges
        if edge["source"] in known and edge["target"] in known
    ]
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "1",
            "id": "test-flow",
            "name": "Test",
            "nodes": nodes,
            "edges": edges,
        }
    )


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


def test_compile_recipe_accepts_starter_graph() -> None:
    compiled = compile_recipe(research_recipe())
    assert [node.type for node in compiled.post_trial] == [
        "eval_script",
        "evaluation",
        "metric_gate",
        "git_decision",
    ]
    assert compiled.max_hypotheses == 3
    assert compiled.max_retries == 2
    assert compiled.allowed_paths == ["train.py"]
    assert compiled.has_self_heal
    assert compiled.has_feedback


def test_compile_recipe_rejects_disconnected_gate() -> None:
    edges = [
        {"id": "h-e", "source": "hypothesis", "target": "execution"},
        {"id": "e-s", "source": "execution", "target": "eval_script"},
        {"id": "e-a", "source": "execution", "target": "evaluation"},
        {"id": "s-a", "source": "eval_script", "target": "evaluation"},
        # gate and decision isolated
        {"id": "e-h", "source": "execution", "target": "hypothesis"},
    ]
    with pytest.raises(WorkflowError, match="evaluation → metric_gate"):
        compile_recipe(research_recipe(edges=edges))


def test_compile_recipe_rejects_duplicate_hypothesis() -> None:
    with pytest.raises(WorkflowError, match="only one hypothesis"):
        compile_recipe(
            research_recipe(
                extra_nodes=[
                    {
                        "id": "hypothesis-2",
                        "type": "hypothesis",
                        "name": "H2",
                        "position": {"x": 0, "y": 2},
                        "config": {},
                    }
                ]
            )
        )


def test_compile_recipe_rejects_missing_execution_to_eval_path() -> None:
    edges = [
        {"id": "h-e", "source": "hypothesis", "target": "execution"},
        {"id": "s-a", "source": "eval_script", "target": "evaluation"},
        {"id": "a-g", "source": "evaluation", "target": "gate"},
        {"id": "g-d", "source": "gate", "target": "decision"},
    ]
    with pytest.raises(WorkflowError, match="execution must connect"):
        compile_recipe(research_recipe(edges=edges))


def test_compile_recipe_rejects_illegal_edge() -> None:
    edges = [
        {"id": "h-e", "source": "hypothesis", "target": "execution"},
        {"id": "e-s", "source": "execution", "target": "eval_script"},
        {"id": "e-a", "source": "execution", "target": "evaluation"},
        {"id": "s-a", "source": "eval_script", "target": "evaluation"},
        {"id": "a-g", "source": "evaluation", "target": "gate"},
        {"id": "g-d", "source": "gate", "target": "decision"},
        {"id": "bad", "source": "hypothesis", "target": "gate"},
    ]
    with pytest.raises(WorkflowError, match="illegal edge"):
        compile_recipe(research_recipe(edges=edges))


def test_compile_recipe_ignores_database_viewer() -> None:
    compiled = compile_recipe(
        research_recipe(
            extra_nodes=[
                {
                    "id": "database",
                    "type": "database",
                    "name": "DB",
                    "position": {"x": 2, "y": 2},
                    "config": {},
                }
            ]
        )
    )
    assert "database" not in {node.type for node in compiled.post_trial}


def test_compile_recipe_rejects_missing_required_node() -> None:
    with pytest.raises(WorkflowError, match="metric_gate"):
        compile_recipe(research_recipe(drop_node_id="gate"))
