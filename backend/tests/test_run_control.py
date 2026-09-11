from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from autoresearch_api.executor import WorkflowExecutor
from autoresearch_api.git_service import GitService
from autoresearch_api.models import Project, Run, Workflow
from autoresearch_api.run_control import get_controller
from autoresearch_api.runner import LocalRunner

from .test_executor import workflow_definition


def _start_run(
    session: Session,
    project_repo: Path,
    runtime_root: Path,
    definition: dict,
) -> tuple[WorkflowExecutor, str]:
    project = Project(
        name=f"proj-{definition['id']}",
        local_path=str(project_repo),
        pg_schema=f"proj_{definition['id'].replace('-', '_')}",
        is_active=True,
    )
    session.add(project)
    session.flush()
    workflow = Workflow(
        id=definition["id"],
        name=definition["name"],
        description="",
        definition=definition,
        project_id=project.id,
    )
    run = Run(workflow_id=workflow.id, project_id=project.id)
    session.add_all([workflow, run])
    session.commit()
    executor = WorkflowExecutor(
        GitService(project_repo, runtime_root, "master"),
        LocalRunner(default_timeout_seconds=10),
    )
    return executor, run.id


def test_cancel_stops_run(session: Session, project_repo: Path, tmp_path: Path) -> None:
    definition = workflow_definition(
        "cancel-flow",
        candidate_score=0.5,
        baseline=1.0,
        script=(
            "import time; from pathlib import Path; "
            "time.sleep(8); Path('score.txt').write_text('0.5\\n', encoding='utf-8')"
        ),
    )
    executor, run_id = _start_run(session, project_repo, tmp_path / "runtime", definition)
    engine = session.get_bind()
    result: list[Run] = []

    def worker() -> None:
        with Session(engine) as worker_session:
            result.append(executor.execute(worker_session, run_id))

    thread = threading.Thread(target=worker)
    thread.start()
    for _ in range(50):
        controller = get_controller(run_id)
        if controller is not None:
            time.sleep(0.4)
            controller.request_cancel()
            break
        time.sleep(0.1)
    thread.join(timeout=20)
    assert result, "executor did not finish"
    assert result[0].status == "cancelled"


def test_pause_and_resume_between_nodes(
    session: Session, project_repo: Path, tmp_path: Path
) -> None:
    definition = workflow_definition(
        "pause-flow",
        candidate_score=0.5,
        baseline=1.0,
        max_hypotheses=2,
    )
    executor, run_id = _start_run(session, project_repo, tmp_path / "runtime", definition)
    engine = session.get_bind()
    result: list[Run] = []
    saw_paused = threading.Event()

    def worker() -> None:
        with Session(engine) as worker_session:
            result.append(executor.execute(worker_session, run_id))

    thread = threading.Thread(target=worker)
    thread.start()

    for _ in range(100):
        controller = get_controller(run_id)
        if controller is not None:
            controller.request_pause()
            break
        time.sleep(0.05)

    for _ in range(100):
        with Session(engine) as check:
            current = check.get(Run, run_id)
            if current is not None and current.status == "paused":
                saw_paused.set()
                break
        time.sleep(0.1)

    assert saw_paused.is_set(), "run never entered paused state"
    controller = get_controller(run_id)
    assert controller is not None
    controller.request_resume()
    thread.join(timeout=30)
    assert result, "executor did not finish"
    assert result[0].status == "succeeded"
