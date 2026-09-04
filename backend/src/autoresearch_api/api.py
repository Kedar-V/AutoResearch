from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import SessionLocal, get_session
from .executor import WorkflowExecutor
from .git_service import GitService
from .models import Run, Workflow
from .runner import LocalRunner
from .schemas import (
    NodeTypeDefinition,
    RunCreate,
    RunRead,
    WorkflowDefinition,
    WorkflowSummary,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


NODE_TYPES = [
    NodeTypeDefinition(
        type="hypothesis",
        label="Hypothesis",
        description="Create a new idea branch from the champion.",
        config_schema={"title": "string", "description": "string"},
    ),
    NodeTypeDefinition(
        type="trial",
        label="Trial",
        description="Create a trial branch and worktree.",
        config_schema={"number": "integer"},
    ),
    NodeTypeDefinition(
        type="script",
        label="Script",
        description="Run a trusted command and commit its changes.",
        config_schema={"command": "string[]", "timeout_seconds": "integer"},
    ),
    NodeTypeDefinition(
        type="evaluation",
        label="Evaluation",
        description="Run a command that prints a metrics JSON object.",
        config_schema={
            "command": "string[]",
            "timeout_seconds": "integer",
            "protected_paths": "string[]",
        },
    ),
    NodeTypeDefinition(
        type="metric_gate",
        label="Metric gate",
        description="Compare one emitted metric with a baseline.",
        config_schema={
            "metric": "string",
            "baseline": "number",
            "min_delta": "number",
            "direction": "maximize|minimize",
        },
    ),
    NodeTypeDefinition(
        type="git_decision",
        label="Git decision",
        description="Record and tag the decision, then merge an accepted trial.",
        config_schema={},
    ),
]


@router.get("/node-types", response_model=list[NodeTypeDefinition])
def list_node_types() -> list[NodeTypeDefinition]:
    return NODE_TYPES


@router.get("/workflows", response_model=list[WorkflowSummary])
def list_workflows(session: SessionDep) -> list[Workflow]:
    return list(session.scalars(select(Workflow).order_by(Workflow.updated_at.desc())))


@router.get("/workflows/{workflow_id}", response_model=WorkflowDefinition)
def get_workflow(workflow_id: str, session: SessionDep) -> dict:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return workflow.definition


@router.put("/workflows/{workflow_id}", response_model=WorkflowDefinition)
def save_workflow(
    workflow_id: str,
    definition: WorkflowDefinition,
    session: SessionDep,
) -> dict:
    if workflow_id != definition.id:
        raise HTTPException(status_code=422, detail="path id must match workflow id")
    workflow = session.get(Workflow, workflow_id)
    now = datetime.now(UTC)
    if workflow is None:
        workflow = Workflow(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            definition=definition.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        session.add(workflow)
    else:
        workflow.name = definition.name
        workflow.description = definition.description
        workflow.definition = definition.model_dump(mode="json")
        workflow.updated_at = now
    session.commit()
    return workflow.definition


def _execute_run(run_id: str) -> None:
    settings = get_settings()
    executor = WorkflowExecutor(
        GitService(settings.project_root, settings.runtime_root, settings.champion_branch),
        LocalRunner(settings.script_timeout_seconds),
        settings.protected_path_list,
    )
    with SessionLocal() as session:
        executor.execute(session, run_id)


@router.post("/runs", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> Run:
    if session.get(Workflow, payload.workflow_id) is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    run = Run(workflow_id=payload.workflow_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    background_tasks.add_task(_execute_run, run.id)
    return run


@router.get("/runs", response_model=list[RunRead])
def list_runs(session: SessionDep) -> list[Run]:
    statement = select(Run).options(selectinload(Run.node_runs)).order_by(Run.created_at.desc())
    return list(session.scalars(statement))


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: str, session: SessionDep) -> Run:
    statement = select(Run).where(Run.id == run_id).options(selectinload(Run.node_runs))
    run = session.scalar(statement)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
