from __future__ import annotations

from collections import defaultdict, deque

from .schemas import WorkflowDefinition, WorkflowEdge, WorkflowNode


class WorkflowError(ValueError):
    pass


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
    for node in workflow.nodes:
        if node.type != "script":
            continue
        if isinstance(node.config.get("command"), list):
            continue
        paths = node.config.get("allowed_paths")
        if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
            return paths
    return None
