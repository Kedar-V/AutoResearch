from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .database import SessionLocal, get_session
from .evaluation_record import build_evaluation_record
from .executor import WorkflowExecutor
from .git_service import GitService
from .models import (
    ChatMessage,
    ChatSummary,
    FrontierPointRecord,
    HypothesisRecord,
    Metric,
    NodeRun,
    Project,
    Run,
    TrialRecord,
    Workflow,
    utcnow,
)
from .project_reset import (
    ProjectResetError,
    resolve_restart_workflow_id,
    upsert_restart_chat_summary,
    wipe_local_git_experiments,
    wipe_project_database,
    wipe_remote_git_experiments,
    wiped_payload,
)
from .projects import (
    ProjectError,
    active_project,
    create_project,
    github_status,
    set_active_project,
)
from .run_control import ensure_controller, get_controller, remove_controller
from .runner import LocalRunner
from .schemas import (
    DiffRead,
    EvaluationEvidence,
    EvaluationRead,
    EvaluationSignals,
    FrontierPointRead,
    FrontierRead,
    FrontierSelect,
    FrontierSelectRead,
    GitHubStatusRead,
    HandoffRead,
    HypothesisRead,
    NodeTypeDefinition,
    ProjectCreate,
    ProjectRead,
    ProjectRestartRead,
    ProjectRestartWiped,
    RunCreate,
    RunRead,
    TrialRead,
    WorkflowDefinition,
    WorkflowSummary,
)
from .workflow import WorkflowError, compile_recipe

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


def _require_valid_recipe(definition: WorkflowDefinition) -> None:
    try:
        compile_recipe(definition)
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


NODE_TYPES = [
    NodeTypeDefinition(
        type="hypothesis",
        label="Hypothesis",
        description="Propose the next idea from inbound context.",
        config_schema={
            "title": "string",
            "description": "string",
            "system_prompt": "string",
            "model": "string",
            "max_retries": "integer",
            "max_hypotheses": "integer",
            "history_window": "integer",
            "use_planner": "boolean",
        },
    ),
    NodeTypeDefinition(
        type="script",
        label="Script",
        description="Optional allow-list of editable paths.",
        config_schema={"allowed_paths": "string[]"},
    ),
    NodeTypeDefinition(
        type="execution",
        label="Execution",
        description="Run the candidate in a trial worktree.",
        config_schema={
            "command": "string[]",
            "timeout_seconds": "integer",
            "commit_message": "string",
            "use_agent": "boolean",
            "model": "string",
        },
    ),
    NodeTypeDefinition(
        type="eval_script",
        label="Eval script",
        description="Trusted evaluator that prints metrics JSON.",
        config_schema={
            "command": "string[]",
            "timeout_seconds": "integer",
            "protected_paths": "string[]",
        },
    ),
    NodeTypeDefinition(
        type="evaluation",
        label="Evaluation agent",
        description="Interpret metrics from eval script + execution.",
        config_schema={
            "system_prompt": "string",
            "model": "string",
            "use_agent": "boolean",
            "explainability_schema": "object|null",
        },
    ),
    NodeTypeDefinition(
        type="metric_gate",
        label="Metric gate",
        description="Scalar champion compare (default) or opt-in ε-Pareto frontier policy.",
        config_schema={
            "policy": "scalar|pareto",
            "metric": "string",
            "baseline": "number",
            "min_delta": "number",
            "direction": "maximize|minimize",
            "objectives": "[{metric, direction, epsilon}]",
            "hard_gates": "[{metric, finite?, equals?, min?, max?}]",
        },
    ),
    NodeTypeDefinition(
        type="git_decision",
        label="Git decision",
        description="Scalar: merge accepted trials. Pareto: tag KEEP/DISCARD without auto-merge.",
        config_schema={},
    ),
    NodeTypeDefinition(
        type="database",
        label="DB",
        description="Browse project database tables.",
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
    _require_valid_recipe(definition)
    workflow = session.get(Workflow, workflow_id)
    now = datetime.now(UTC)
    project = active_project(session)
    if workflow is None:
        workflow = Workflow(
            id=definition.id,
            name=definition.name,
            description=definition.description,
            definition=definition.model_dump(mode="json"),
            project_id=project.id if project else None,
            created_at=now,
            updated_at=now,
        )
        session.add(workflow)
    else:
        workflow.name = definition.name
        workflow.description = definition.description
        workflow.definition = definition.model_dump(mode="json")
        workflow.updated_at = now
        if project:
            workflow.project_id = project.id
    session.commit()
    return workflow.definition


def _git_for_session(session: Session) -> GitService:
    settings = get_settings()
    project = active_project(session)
    root = Path(project.local_path) if project else settings.project_root
    return GitService(root, settings.runtime_root, settings.champion_branch)


def _execute_run(run_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as session:
        git = _git_for_session(session)
        executor = WorkflowExecutor(
            git,
            LocalRunner(settings.script_timeout_seconds),
            settings.protected_path_list,
        )
        executor.execute(session, run_id)


@router.post("/runs", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> Run:
    workflow = session.get(Workflow, payload.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        definition = WorkflowDefinition.model_validate(workflow.definition)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid workflow definition: {exc}") from exc
    _require_valid_recipe(definition)
    project = active_project(session)
    run = Run(
        workflow_id=payload.workflow_id,
        project_id=project.id if project else None,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    ensure_controller(run.id)
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


def _load_run(session: Session, run_id: str) -> Run:
    statement = select(Run).where(Run.id == run_id).options(selectinload(Run.node_runs))
    run = session.scalar(statement)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
def cancel_run(run_id: str, session: SessionDep) -> Run:
    run = _load_run(session, run_id)
    if run.status not in {"queued", "running", "paused"}:
        raise HTTPException(
            status_code=409,
            detail=f"cannot cancel run in status {run.status}",
        )
    controller = ensure_controller(run.id)
    controller.request_cancel()
    if run.status in {"queued", "paused"}:
        run.status = "cancelled"
        run.error = "Cancelled by operator"
        run.finished_at = datetime.now(UTC)
        for node_run in run.node_runs:
            if node_run.status == "running":
                node_run.status = "cancelled"
                node_run.stderr = "Cancelled by operator"
                node_run.finished_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
    return run


@router.post("/runs/{run_id}/pause", response_model=RunRead)
def pause_run(run_id: str, session: SessionDep) -> Run:
    run = _load_run(session, run_id)
    if run.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"cannot pause run in status {run.status}",
        )
    controller = get_controller(run.id)
    if controller is None:
        raise HTTPException(status_code=409, detail="run worker is not active")
    controller.request_pause()
    return run


@router.post("/runs/{run_id}/resume", response_model=RunRead)
def resume_run(run_id: str, session: SessionDep) -> Run:
    run = _load_run(session, run_id)
    if run.status != "paused":
        raise HTTPException(
            status_code=409,
            detail=f"cannot resume run in status {run.status}",
        )
    controller = get_controller(run.id)
    if controller is None:
        raise HTTPException(
            status_code=409,
            detail="run worker is not active; cannot resume after API restart",
        )
    controller.request_resume()
    return run


@router.get("/github/status", response_model=GitHubStatusRead)
def get_github_status() -> GitHubStatusRead:
    settings = get_settings()
    status = github_status(configured_owner=settings.github_owner)
    return GitHubStatusRead(
        gh_installed=status.gh_installed,
        authenticated=status.authenticated,
        login=status.login,
        configured_owner=status.configured_owner,
        resolved_owner=status.resolved_owner,
        hint=status.hint,
    )


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/projects/active", response_model=ProjectRead | None)
def get_active_project(session: SessionDep) -> Project | None:
    return active_project(session)


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def post_project(payload: ProjectCreate, session: SessionDep) -> Project:
    settings = get_settings()
    try:
        return create_project(
            session,
            name=payload.name,
            runtime_root=settings.runtime_root,
            source=payload.source,
            create_github=payload.create_github,
            github_owner=settings.github_owner,
            github_owner_override=payload.github_owner,
            local_path=payload.local_path,
            git_url=payload.git_url,
            champion_branch=settings.champion_branch,
        )
    except ProjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/{project_id}/activate", response_model=ProjectRead)
def activate_project(project_id: str, session: SessionDep) -> Project:
    try:
        return set_active_project(session, project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/restart", response_model=ProjectRestartRead)
def restart_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> ProjectRestartRead:
    """Wipe experiment ledger/refs (keep champion), then start a fresh run."""
    settings = get_settings()
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    active_runs = list(
        session.scalars(
            select(Run)
            .where(
                Run.project_id == project_id,
                Run.status.in_(("queued", "running", "paused")),
            )
            .options(selectinload(Run.node_runs))
        )
    )
    now = datetime.now(UTC)
    for run in active_runs:
        controller = get_controller(run.id)
        if controller is not None:
            controller.request_cancel()
        run.status = "cancelled"
        run.error = "Cancelled by project restart"
        run.finished_at = now
        for node_run in run.node_runs:
            if node_run.status in {"running", "queued"}:
                node_run.status = "cancelled"
                node_run.stderr = "Cancelled by project restart"
                node_run.finished_at = now
        remove_controller(run.id)
    session.commit()

    repo = Path(project.local_path)
    try:
        local_stats = wipe_local_git_experiments(
            repo,
            champion_branch=settings.champion_branch,
            runtime_root=settings.runtime_root,
        )
        remote_stats = wipe_remote_git_experiments(repo)
    except ProjectResetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    runs_removed = wipe_project_database(session, project_id)
    upsert_restart_chat_summary(session, project)
    try:
        set_active_project(session, project_id)
        workflow_id = resolve_restart_workflow_id(session, project)
    except (ProjectError, ProjectResetError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    local_stats.runs = runs_removed
    wiped = wiped_payload(local_stats)
    wiped["branches"] = list(dict.fromkeys([*wiped["branches"], *remote_stats.branches]))
    wiped["tags"] = list(dict.fromkeys([*wiped["tags"], *remote_stats.tags]))

    if session.get(Workflow, workflow_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"workflow {workflow_id!r} not found after reset",
        )

    workflow_row = session.get(Workflow, workflow_id)
    assert workflow_row is not None
    try:
        definition = WorkflowDefinition.model_validate(workflow_row.definition)
        compile_recipe(definition)
    except WorkflowError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"cannot restart with invalid research recipe: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"cannot restart with invalid workflow definition: {exc}",
        ) from exc

    run = Run(workflow_id=workflow_id, project_id=project.id)
    session.add(run)
    session.commit()
    session.refresh(run)
    session.refresh(project)
    ensure_controller(run.id)
    background_tasks.add_task(_execute_run, run.id)

    # Reload with node_runs for response shape
    run = _load_run(session, run.id)
    return ProjectRestartRead(
        project=ProjectRead.model_validate(project),
        run=RunRead.model_validate(run),
        wiped=ProjectRestartWiped.model_validate(wiped),
    )


def _public_id(value: str) -> str:
    return value.split(":", 1)[-1]


def _hypothesis_read(row: HypothesisRecord) -> HypothesisRead:
    return HypothesisRead(
        id=_public_id(row.id),
        title=row.title,
        description=row.description,
        branch=row.branch,
        base_commit=row.base_commit,
        status=row.status,
        what_worked=row.what_worked,
        what_did_not=row.what_did_not,
        metrics=row.metrics,
        created_at=row.created_at,
    )


def _trial_read(row: TrialRecord) -> TrialRead:
    return TrialRead(
        id=_public_id(row.id),
        hypothesis_id=_public_id(row.hypothesis_id),
        branch=row.branch,
        candidate_commit=row.candidate_commit,
        outcome=row.outcome,
        error=row.error,
        next_step=row.next_step,
        what_changed=row.what_changed,
        metrics=row.metrics,
        created_at=row.created_at,
    )


def _evaluation_read(payload: dict[str, Any]) -> EvaluationRead:
    signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    created_raw = payload.get("created_at")
    if isinstance(created_raw, datetime):
        created_at = created_raw
    else:
        created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
    return EvaluationRead(
        schema_version="2",
        evaluation_id=str(payload.get("evaluation_id") or ""),
        trial_id=str(payload.get("trial_id") or ""),
        hypothesis_id=str(payload.get("hypothesis_id") or ""),
        run_id=str(payload.get("run_id") or ""),
        status=payload.get("status")
        if payload.get("status") in {"passed", "failed", "invalid"}
        else "invalid",
        metrics={
            str(k): float(v)
            for k, v in (payload.get("metrics") or {}).items()
            if isinstance(v, (int, float))
        },
        champion_metrics={
            str(k): float(v)
            for k, v in (payload.get("champion_metrics") or {}).items()
            if isinstance(v, (int, float))
        },
        deltas={
            str(k): float(v)
            for k, v in (payload.get("deltas") or {}).items()
            if isinstance(v, (int, float))
        },
        primary_metric=str(payload.get("primary_metric") or "score"),
        direction="maximize" if payload.get("direction") == "maximize" else "minimize",
        summary=str(payload.get("summary") or ""),
        signals=EvaluationSignals(
            improved=[str(x) for x in signals.get("improved") or []],
            regressed=[str(x) for x in signals.get("regressed") or []],
            unchanged=[str(x) for x in signals.get("unchanged") or []],
        ),
        recommendation=payload.get("recommendation")
        if payload.get("recommendation") in {"accept", "reject", "retry"}
        else "retry",
        rationale=str(payload.get("rationale") or ""),
        risks=str(payload.get("risks") or ""),
        evidence=EvaluationEvidence(
            candidate_commit=str(evidence.get("candidate_commit") or ""),
            evaluator_commit=str(evidence.get("evaluator_commit") or ""),
            duration_seconds=(
                float(evidence["duration_seconds"])
                if isinstance(evidence.get("duration_seconds"), (int, float))
                else None
            ),
            stdout_excerpt=(
                str(evidence["stdout_excerpt"])
                if evidence.get("stdout_excerpt") is not None
                else None
            ),
        ),
        model=str(payload.get("model") or ""),
        system_prompt_hash=str(payload.get("system_prompt_hash") or ""),
        agent_trace_id=str(payload.get("agent_trace_id") or ""),
        prompt_version=str(payload.get("prompt_version") or ""),
        observability_backend=str(payload.get("observability_backend") or ""),
        explainability=(
            dict(payload["explainability"])
            if isinstance(payload.get("explainability"), dict)
            else {}
        ),
        explainability_schema_hash=str(payload.get("explainability_schema_hash") or ""),
        created_at=created_at,
    )


def _list_project_evaluations(session: Session, project_id: str) -> list[EvaluationRead]:
    rows = list(
        session.scalars(
            select(NodeRun)
            .join(Run)
            .where(Run.project_id == project_id)
            .where(NodeRun.node_type.in_(("evaluation", "eval_script")))
            .order_by(NodeRun.started_at.desc())
        )
    )
    by_key: dict[str, EvaluationRead] = {}
    for row in rows:
        output = row.output if isinstance(row.output, dict) else {}
        parsed: EvaluationRead | None = None
        if row.node_type == "evaluation" and output.get("schema_version") == "2":
            record = dict(output)
            record.setdefault("run_id", row.run_id)
            parsed = _evaluation_read(record)
        elif row.node_type == "eval_script" and isinstance(output.get("metrics"), dict):
            run = session.get(Run, row.run_id)
            trial_id = str((run.trial_id if run else None) or output.get("trial_id") or "")
            if not trial_id:
                continue
            built = build_evaluation_record(
                trial_id=trial_id,
                run_id=row.run_id,
                metrics=output["metrics"],
                champion_metrics={},
                primary_metric=str(next(iter(output["metrics"]), "score")),
                direction="minimize",
                candidate_commit=str(output.get("candidate_commit") or ""),
                evaluator_commit=str(output.get("evaluator_commit") or ""),
                status="passed" if row.status == "succeeded" else "failed",
                created_at=row.started_at.isoformat(),
            )
            parsed = _evaluation_read(built)
        if parsed is None:
            continue
        key = f"{parsed.trial_id}:{parsed.evidence.candidate_commit}"
        # Newest first; evaluation agent rows appear before eval_script for the same trial.
        if key not in by_key:
            by_key[key] = parsed
    return list(by_key.values())


@router.get("/projects/{project_id}/handoff", response_model=HandoffRead)
def project_handoff(project_id: str, session: SessionDep) -> HandoffRead:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    summary = session.scalar(select(ChatSummary).where(ChatSummary.project_id == project_id))
    hypotheses = list(
        session.scalars(
            select(HypothesisRecord)
            .where(HypothesisRecord.project_id == project_id)
            .order_by(HypothesisRecord.created_at.asc())
        )
    )
    trials = list(
        session.scalars(
            select(TrialRecord)
            .where(TrialRecord.project_id == project_id)
            .order_by(TrialRecord.created_at.asc())
        )
    )
    champion_metrics: dict[str, float] = {}
    for hypo in reversed(hypotheses):
        if hypo.status == "accepted" and isinstance(hypo.metrics, dict) and hypo.metrics:
            champion_metrics = {
                key: float(value)
                for key, value in hypo.metrics.items()
                if isinstance(value, (int, float))
            }
            break
    return HandoffRead(
        project=ProjectRead.model_validate(project),
        summary=summary.summary if summary else "",
        champion_metrics=champion_metrics,
        hypotheses=[_hypothesis_read(item) for item in hypotheses],
        trials=[_trial_read(item) for item in trials],
    )


@router.get("/projects/{project_id}/hypotheses", response_model=list[HypothesisRead])
def list_hypotheses(project_id: str, session: SessionDep) -> list[HypothesisRead]:
    rows = list(
        session.scalars(
            select(HypothesisRecord)
            .where(HypothesisRecord.project_id == project_id)
            .order_by(HypothesisRecord.created_at.asc())
        )
    )
    return [_hypothesis_read(row) for row in rows]


@router.get("/projects/{project_id}/trials", response_model=list[TrialRead])
def list_trials(project_id: str, session: SessionDep) -> list[TrialRead]:
    rows = list(
        session.scalars(
            select(TrialRecord)
            .where(TrialRecord.project_id == project_id)
            .order_by(TrialRecord.created_at.asc())
        )
    )
    return [_trial_read(row) for row in rows]


@router.get("/projects/{project_id}/frontier", response_model=FrontierRead)
def get_frontier(project_id: str, session: SessionDep) -> FrontierRead:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    rows = list(
        session.scalars(
            select(FrontierPointRecord)
            .where(FrontierPointRecord.project_id == project_id)
            .order_by(FrontierPointRecord.created_at.asc())
        )
    )
    return FrontierRead(
        points=[
            FrontierPointRead(
                commit=row.commit,
                trial_id=row.trial_id,
                metrics={k: float(v) for k, v in (row.metrics or {}).items()},
                created_at=row.created_at,
            )
            for row in rows
        ],
        preferred_base_commit=project.preferred_base_commit,
    )


@router.post("/projects/{project_id}/frontier/select", response_model=FrontierSelectRead)
def select_frontier_point(
    project_id: str, payload: FrontierSelect, session: SessionDep
) -> FrontierSelectRead:
    """Seed next hypotheses from a frontier commit; optionally promote onto champion."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    point = None
    if len(payload.commit) >= 40:
        point = session.scalar(
            select(FrontierPointRecord).where(
                FrontierPointRecord.project_id == project_id,
                FrontierPointRecord.commit == payload.commit,
            )
        )
    else:
        matches = list(
            session.scalars(
                select(FrontierPointRecord).where(
                    FrontierPointRecord.project_id == project_id,
                    FrontierPointRecord.commit.startswith(payload.commit),
                )
            )
        )
        if len(matches) > 1:
            raise HTTPException(status_code=400, detail="ambiguous frontier commit prefix")
        point = matches[0] if matches else None
    if point is None:
        raise HTTPException(status_code=404, detail="frontier commit not found")

    champion_commit: str | None = None
    promoted = False
    if payload.promote:
        trial = session.get(TrialRecord, f"{project_id}:{point.trial_id}")
        if trial is None or not trial.branch:
            raise HTTPException(
                status_code=400, detail="trial branch missing for frontier point; cannot promote"
            )
        hypo = session.get(HypothesisRecord, trial.hypothesis_id)
        if hypo is None or not hypo.base_commit:
            raise HTTPException(
                status_code=400, detail="hypothesis base missing for frontier point; cannot promote"
            )
        try:
            settings = get_settings()
            git = GitService(Path(project.local_path), settings.runtime_root, settings.champion_branch)
            champion_commit = git.merge_trial(trial.branch, hypo.base_commit)
            git.record_champion(
                champion_commit,
                {
                    "schema_version": "1",
                    "trial_id": point.trial_id,
                    "candidate_commit": point.commit,
                    "champion_commit": champion_commit,
                    "metrics": point.metrics or {},
                    "created_at": datetime.now(UTC).isoformat(),
                    "source": "frontier_select",
                },
            )
            promoted = True
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    project.preferred_base_commit = champion_commit or point.commit
    project.updated_at = utcnow()
    session.commit()
    session.refresh(project)
    return FrontierSelectRead(
        project=ProjectRead.model_validate(project),
        preferred_base_commit=project.preferred_base_commit or point.commit,
        promoted=promoted,
        champion_commit=champion_commit,
    )


@router.get("/projects/{project_id}/evaluations", response_model=list[EvaluationRead])
def list_evaluations(project_id: str, session: SessionDep) -> list[EvaluationRead]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return _list_project_evaluations(session, project_id)


@router.get("/projects/{project_id}/tables/{table_name}")
def project_table(project_id: str, table_name: str, session: SessionDep) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    loaders = {
        "hypotheses": lambda: [
            _hypothesis_read(row).model_dump(mode="json")
            for row in session.scalars(
                select(HypothesisRecord).where(HypothesisRecord.project_id == project_id)
            )
        ],
        "trials": lambda: [
            _trial_read(row).model_dump(mode="json")
            for row in session.scalars(
                select(TrialRecord).where(TrialRecord.project_id == project_id)
            )
        ],
        "evaluations": lambda: [
            item.model_dump(mode="json") for item in _list_project_evaluations(session, project_id)
        ],
        "metrics": lambda: [
            {"id": row.id, "name": row.name, "value": row.value, "run_id": row.run_id}
            for row in session.scalars(select(Metric).where(Metric.project_id == project_id))
        ],
        "runs": lambda: [
            {
                "id": row.id,
                "status": row.status,
                "hypothesis_id": row.hypothesis_id,
                "trial_id": row.trial_id,
                "error": row.error,
            }
            for row in session.scalars(select(Run).where(Run.project_id == project_id))
        ],
        "node_runs": lambda: [
            {
                "id": row.id,
                "run_id": row.run_id,
                "node_id": row.node_id,
                "node_type": row.node_type,
                "status": row.status,
            }
            for row in session.scalars(
                select(NodeRun).join(Run).where(Run.project_id == project_id)
            )
        ],
        "chat_summaries": lambda: [
            {"id": row.id, "summary": row.summary, "updated_at": row.updated_at.isoformat()}
            for row in session.scalars(
                select(ChatSummary).where(ChatSummary.project_id == project_id)
            )
        ],
        "chat_messages": lambda: [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            }
            for row in session.scalars(
                select(ChatMessage).where(ChatMessage.project_id == project_id)
            )
        ],
    }
    if table_name not in loaders:
        raise HTTPException(status_code=404, detail="unknown table")
    return {"table": table_name, "rows": loaders[table_name]()}


@router.get(
    "/projects/{project_id}/trials/{trial_id:path}/diff",
    response_model=DiffRead,
)
def trial_diff(project_id: str, trial_id: str, session: SessionDep) -> DiffRead:
    trial = session.get(TrialRecord, f"{project_id}:{trial_id}")
    hypo = session.get(HypothesisRecord, trial.hypothesis_id) if trial else None
    if trial is None or hypo is None or trial.project_id != project_id:
        raise HTTPException(status_code=404, detail="trial not found")
    if not trial.candidate_commit:
        raise HTTPException(status_code=404, detail="trial has no candidate commit")
    git = _git_for_session(session)
    try:
        diff = git.diff(hypo.base_commit, trial.candidate_commit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return DiffRead(
        trial_id=trial_id,
        base_commit=hypo.base_commit,
        candidate_commit=trial.candidate_commit,
        diff=diff or "No file changes.",
    )
