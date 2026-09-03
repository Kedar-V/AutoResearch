from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal["hypothesis", "trial", "script", "evaluation", "metric_gate", "git_decision"]


class Position(BaseModel):
    x: float
    y: float


class WorkflowNode(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    type: NodeType
    name: str = Field(min_length=1, max_length=120)
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    source_port: str = "output"
    target_port: str = "input"


class WorkflowDefinition(BaseModel):
    schema_version: Literal["1"] = "1"
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowDefinition:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node ids must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.id} references an unknown node")
            if edge.source == edge.target:
                raise ValueError(f"edge {edge.id} cannot connect a node to itself")
        return self


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    workflow_id: str


class NodeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_id: str
    node_type: str
    status: str
    output: dict[str, Any]
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime | None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    status: str
    hypothesis_id: str | None
    trial_id: str | None
    branch: str | None
    error: str | None
    context: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    node_runs: list[NodeRunRead] = Field(default_factory=list)


class NodeTypeDefinition(BaseModel):
    type: NodeType
    label: str
    description: str
    config_schema: dict[str, Any]
