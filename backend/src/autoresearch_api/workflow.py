from __future__ import annotations

from collections import defaultdict, deque

from .schemas import WorkflowDefinition, WorkflowNode


class WorkflowError(ValueError):
    pass


def topological_order(workflow: WorkflowDefinition) -> list[WorkflowNode]:
    nodes = {node.id: node for node in workflow.nodes}
    indegree = {node_id: 0 for node_id in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in workflow.edges:
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
        raise WorkflowError("workflow must be acyclic")
    return ordered
