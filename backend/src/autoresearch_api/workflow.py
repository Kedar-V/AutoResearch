from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .schemas import WorkflowDefinition, WorkflowEdge, WorkflowNode


class WorkflowError(ValueError):
    pass


# Node types that participate in the research recipe spine.
REQUIRED_TYPES = (
    "hypothesis",
    "execution",
    "eval_script",
    "evaluation",
    "metric_gate",
    "git_decision",
)

# Allowed directed edges by (source_type, target_type).
LEGAL_EDGE_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("hypothesis", "execution"),
        ("execution", "eval_script"),
        ("execution", "evaluation"),
        ("eval_script", "evaluation"),
        ("evaluation", "metric_gate"),
        ("metric_gate", "git_decision"),
        ("execution", "hypothesis"),  # self-heal
        ("git_decision", "hypothesis"),  # outer feedback
    }
)

VIEWER_TYPES = frozenset({"database", "trial"})
ANNOTATION_TYPES = frozenset({"script"})  # allow-list only (legacy)


@dataclass(frozen=True)
class CompiledLoop:
    """Validated research recipe derived from a workflow graph."""

    hypothesis: WorkflowNode
    execution: WorkflowNode
    eval_script: WorkflowNode
    evaluation: WorkflowNode
    metric_gate: WorkflowNode
    git_decision: WorkflowNode
    post_trial: tuple[WorkflowNode, ...]
    allowed_paths: list[str] | None
    max_hypotheses: int
    max_retries: int
    has_self_heal: bool
    has_feedback: bool


def is_feedback_edge(edge: WorkflowEdge, nodes: dict[str, WorkflowNode]) -> bool:
    source = nodes.get(edge.source)
    target = nodes.get(edge.target)
    if source is None or target is None:
        return False
    if target.type != "hypothesis":
        return False
    return source.type in {"execution", "git_decision"}


def executable_edges(workflow: WorkflowDefinition) -> list[WorkflowEdge]:
    nodes = {node.id: node for node in workflow.nodes}
    return [edge for edge in workflow.edges if not is_feedback_edge(edge, nodes)]


def normalize_node(node: WorkflowNode) -> WorkflowNode:
    """Map legacy script/evaluation shapes onto the new loop types."""
    if node.type == "script" and isinstance(node.config.get("command"), list):
        return node.model_copy(update={"type": "execution"})
    if node.type == "evaluation" and isinstance(node.config.get("command"), list):
        return node.model_copy(update={"type": "eval_script"})
    return node


def topological_order(workflow: WorkflowDefinition) -> list[WorkflowNode]:
    nodes = {
        node.id: normalize_node(node)
        for node in workflow.nodes
        if node.type not in {"trial", "database"}
    }
    indegree = {node_id: 0 for node_id in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in executable_edges(workflow):
        if edge.source not in nodes or edge.target not in nodes:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    ready = deque(node_id for node_id in nodes if indegree[node_id] == 0)
    ordered: list[WorkflowNode] = []
    while ready:
        node_id = ready.popleft()
        ordered.append(nodes[node_id])
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if len(ordered) != len(nodes):
        raise WorkflowError("workflow must be acyclic after removing feedback edges")
    return ordered


def find_node(workflow: WorkflowDefinition, node_type: str) -> WorkflowNode | None:
    for node in workflow.nodes:
        if normalize_node(node).type == node_type:
            return normalize_node(node)
    return None


def allowed_paths_from_workflow(workflow: WorkflowDefinition) -> list[str] | None:
    """Prefer execution.allowed_paths; fall back to legacy script allow-list node."""
    for node in workflow.nodes:
        normalized = normalize_node(node)
        if normalized.type == "execution":
            paths = normalized.config.get("allowed_paths")
            if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
                return paths
    for node in workflow.nodes:
        if node.type != "script":
            continue
        if isinstance(node.config.get("command"), list):
            continue
        paths = node.config.get("allowed_paths")
        if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
            return paths
    return None


def _int_config(node: WorkflowNode, key: str, default: int) -> int:
    raw = node.config.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _by_type(workflow: WorkflowDefinition) -> dict[str, list[WorkflowNode]]:
    grouped: dict[str, list[WorkflowNode]] = defaultdict(list)
    for node in workflow.nodes:
        grouped[normalize_node(node).type].append(normalize_node(node))
    return grouped


def _require_edge(
    edges_by_pair: dict[tuple[str, str], list[WorkflowEdge]],
    source_type: str,
    target_type: str,
    *,
    message: str | None = None,
) -> WorkflowEdge:
    matches = edges_by_pair.get((source_type, target_type), [])
    if not matches:
        raise WorkflowError(
            message
            or f"missing required edge {source_type} → {target_type}"
        )
    return matches[0]


def compile_recipe(workflow: WorkflowDefinition) -> CompiledLoop:
    """Compile a workflow graph into a validated research loop recipe.

    The canvas is a constrained recipe editor, not a general DAG engine.
    Exactly one node of each required type must be present, and edges must
    form the research grammar. Viewers (database) and legacy allow-list
    script nodes are ignored for execution order.
    """
    by_type = _by_type(workflow)
    nodes_by_id = {node.id: normalize_node(node) for node in workflow.nodes}

    for node_type in REQUIRED_TYPES:
        matches = by_type.get(node_type, [])
        if len(matches) == 0:
            raise WorkflowError(f"recipe requires exactly one {node_type} node")
        if len(matches) > 1:
            raise WorkflowError(
                f"recipe allows only one {node_type} node; found {len(matches)}"
            )

    for node in workflow.nodes:
        normalized = normalize_node(node)
        if normalized.type in REQUIRED_TYPES:
            continue
        if normalized.type in VIEWER_TYPES:
            continue
        if normalized.type in ANNOTATION_TYPES:
            # Allow-list-only script nodes are annotations; command scripts are
            # normalized to execution above and would already be counted.
            if isinstance(node.config.get("command"), list):
                raise WorkflowError(
                    "script nodes with a command must be typed as execution"
                )
            continue
        raise WorkflowError(
            f"unsupported node type {normalized.type!r} on the research recipe"
        )

    edges_by_pair: dict[tuple[str, str], list[WorkflowEdge]] = defaultdict(list)
    for edge in workflow.edges:
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None or target is None:
            raise WorkflowError(f"edge {edge.id} references an unknown node")
        pair = (source.type, target.type)
        if pair not in LEGAL_EDGE_PAIRS:
            raise WorkflowError(
                f"illegal edge {source.type} → {target.type} "
                f"(edge {edge.id}); not part of the research recipe grammar"
            )
        edges_by_pair[pair].append(edge)

    _require_edge(edges_by_pair, "hypothesis", "execution")
    _require_edge(edges_by_pair, "eval_script", "evaluation")
    _require_edge(edges_by_pair, "evaluation", "metric_gate")
    _require_edge(edges_by_pair, "metric_gate", "git_decision")

    has_exec_to_eval = bool(edges_by_pair.get(("execution", "evaluation")))
    has_exec_to_eval_script = bool(edges_by_pair.get(("execution", "eval_script")))
    if not has_exec_to_eval and not has_exec_to_eval_script:
        raise WorkflowError(
            "execution must connect to eval_script or evaluation "
            "(metrics path after a successful trial)"
        )

    hypothesis = by_type["hypothesis"][0]
    execution = by_type["execution"][0]
    eval_script = by_type["eval_script"][0]
    evaluation = by_type["evaluation"][0]
    metric_gate = by_type["metric_gate"][0]
    git_decision = by_type["git_decision"][0]

    # post_trial order: eval_script → evaluation → gate → decision (topo among them)
    post_nodes = {
        eval_script.id: eval_script,
        evaluation.id: evaluation,
        metric_gate.id: metric_gate,
        git_decision.id: git_decision,
    }
    indegree = {node_id: 0 for node_id in post_nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
        if edge.source not in post_nodes or edge.target not in post_nodes:
            continue
        outgoing[edge.source].append(edge.target)
        indegree[edge.target] += 1

    ready = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ordered_ids: list[str] = []
    while ready:
        node_id = ready.popleft()
        ordered_ids.append(node_id)
        for target in outgoing[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
        ready = deque(sorted(ready))

    if len(ordered_ids) != len(post_nodes):
        raise WorkflowError(
            "eval_script → evaluation → metric_gate → git_decision path has a cycle "
            "or is disconnected"
        )

    expected = [eval_script.id, evaluation.id, metric_gate.id, git_decision.id]
    if ordered_ids != expected:
        raise WorkflowError(
            "post-trial spine must be eval_script → evaluation → metric_gate → "
            f"git_decision; compiled order was {[post_nodes[i].type for i in ordered_ids]}"
        )

    return CompiledLoop(
        hypothesis=hypothesis,
        execution=execution,
        eval_script=eval_script,
        evaluation=evaluation,
        metric_gate=metric_gate,
        git_decision=git_decision,
        post_trial=tuple(post_nodes[node_id] for node_id in ordered_ids),
        allowed_paths=allowed_paths_from_workflow(workflow),
        max_hypotheses=_int_config(hypothesis, "max_hypotheses", 5),
        max_retries=_int_config(hypothesis, "max_retries", 3),
        has_self_heal=bool(edges_by_pair.get(("execution", "hypothesis"))),
        has_feedback=bool(edges_by_pair.get(("git_decision", "hypothesis"))),
    )
