from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .code_agent import CodeAgentError, apply_hypothesis_edits, summarize_diff
from .evaluation_agent import EvaluationAgentError, judge_evaluation
from .evaluation_record import build_evaluation_record
from .git_service import GitError, GitService, TrialWorkspace
from .hypothesis_brief import (
    DEFAULT_HISTORY_WINDOW,
    DEFAULT_SYSTEM_PROMPT,
    build_hypothesis_brief,
    summarize_outcome,
)
from .hypothesis_planner import HypothesisPlanError, plan_hypothesis
from .models import (
    ChatSummary,
    HypothesisRecord,
    Metric,
    NodeRun,
    Project,
    Run,
    TrialRecord,
    Workflow,
)
from .run_control import RunCancelled, create_controller, get_controller, remove_controller
from .runner import LocalRunner, RunnerError
from .schemas import WorkflowDefinition, WorkflowNode
from .workflow import allowed_paths_from_workflow, find_node, topological_order


class ExecutionError(RuntimeError):
    pass


class WorkflowExecutor:
    def __init__(
        self,
        git: GitService,
        runner: LocalRunner,
        protected_paths: list[str] | None = None,
    ) -> None:
        self.git = git
        self.runner = runner
        self.protected_paths = protected_paths or ["eval.py", "tests", ".research"]

    def execute(self, session: Session, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise ExecutionError(f"run {run_id} not found")
        workflow_row = session.get(Workflow, run.workflow_id)
        if workflow_row is None:
            raise ExecutionError(f"workflow {run.workflow_id} not found")

        controller = create_controller(run_id)
        context: dict[str, Any] = {}
        try:
            if run.status == "cancelled" or controller.is_cancel_requested():
                run.status = "cancelled"
                run.error = run.error or "Cancelled by operator"
                run.finished_at = datetime.now(UTC)
                session.commit()
                session.refresh(run)
                return run

            run.status = "running"
            run.started_at = datetime.now(UTC)
            run.finished_at = None
            session.commit()
            try:
                workflow = WorkflowDefinition.model_validate(workflow_row.definition)
                self.git.verify_repository()
                ordered = topological_order(workflow)
                hypothesis = find_node(workflow, "hypothesis")
                if hypothesis is None:
                    for node in ordered:
                        self._checkpoint(session, run)
                        self._execute_node(session, run, node, context, workflow)
                else:
                    self._run_outer_loop(session, run, workflow, hypothesis, context)
                run.status = "succeeded"
                self._upsert_chat_summary(session, run)
            except RunCancelled as exc:
                run.status = "cancelled"
                run.error = str(exc) or "Cancelled by operator"
                self._mark_open_node_runs(session, run, "cancelled", run.error)
            except Exception as exc:
                run.status = "failed"
                run.error = str(exc)
            finally:
                run.context = self._serializable_context(context)
                if run.status != "paused":
                    run.finished_at = datetime.now(UTC)
                session.commit()
                session.refresh(run)
            return run
        finally:
            remove_controller(run_id)

    def _checkpoint(self, session: Session, run: Run) -> None:
        """Honor cancel immediately; soft-pause after the current node finishes."""
        controller = get_controller(run.id)
        if controller is None:
            return
        if controller.is_cancel_requested():
            raise RunCancelled("Cancelled by operator")
        if not controller.is_pause_requested():
            return
        run.status = "paused"
        session.commit()
        if controller.wait_while_paused() == "cancelled":
            raise RunCancelled("Cancelled by operator")
        run.status = "running"
        session.commit()

    @staticmethod
    def _mark_open_node_runs(
        session: Session, run: Run, status: str, message: str
    ) -> None:
        for node_run in run.node_runs:
            if node_run.status == "running":
                node_run.status = status
                node_run.stderr = message
                node_run.finished_at = datetime.now(UTC)
        session.flush()

    def _run_outer_loop(
        self,
        session: Session,
        run: Run,
        workflow: WorkflowDefinition,
        hypothesis: WorkflowNode,
        context: dict[str, Any],
    ) -> None:
        max_hypotheses = self._int_config(hypothesis, "max_hypotheses", 5)
        for _ in range(max_hypotheses):
            self._checkpoint(session, run)
            context.pop("gate_passed", None)
            self._execute_node(session, run, hypothesis, context, workflow)
            self._checkpoint(session, run)
            runnable = self._run_trial_attempts(session, run, hypothesis, workflow, context)
            if not runnable:
                break
            for node_type in ("eval_script", "evaluation", "metric_gate", "git_decision"):
                node = find_node(workflow, node_type)
                if node is None and node_type == "eval_script":
                    node = find_node(workflow, "evaluation")
                if node is None:
                    continue
                if node_type == "evaluation" and node.type == "eval_script":
                    continue
                self._checkpoint(session, run)
                self._execute_node(session, run, node, context, workflow)
            self._finalize_hypothesis(session, run, context)
            # Outer loop continues; next hypothesis branches from current champion HEAD.

    def _run_trial_attempts(
        self,
        session: Session,
        run: Run,
        hypothesis: WorkflowNode,
        workflow: WorkflowDefinition,
        context: dict[str, Any],
    ) -> bool:
        max_retries = self._int_config(hypothesis, "max_retries", 3)
        execution = find_node(workflow, "execution") or find_node(workflow, "script")
        if execution is None:
            raise ExecutionError("workflow requires an execution node")
        for attempt in range(1, max_retries + 1):
            self._checkpoint(session, run)
            trial_run = self._start_trial(session, run, context, attempt)
            try:
                self._execute_node(session, run, execution, context, workflow)
                trial_run.status = "succeeded"
                trial_run.output = {**trial_run.output, "outcome": "ran"}
                trial_run.finished_at = datetime.now(UTC)
                self._update_trial_record(
                    session,
                    context,
                    outcome="ran",
                    candidate_commit=str(context.get("candidate_commit") or ""),
                )
                session.commit()
                return True
            except RunCancelled:
                trial_run.status = "cancelled"
                trial_run.stderr = "Cancelled by operator"
                trial_run.output = {**trial_run.output, "outcome": "cancelled"}
                trial_run.finished_at = datetime.now(UTC)
                session.commit()
                raise
            except Exception as exc:
                trial_run.status = "failed"
                trial_run.stderr = str(exc)
                trial_run.output = {**trial_run.output, "outcome": "failed"}
                trial_run.finished_at = datetime.now(UTC)
                self._update_trial_record(
                    session,
                    context,
                    outcome="failed",
                    error=str(exc),
                    next_step=self._next_step_hint(str(exc), attempt, max_retries),
                )
                session.commit()
                self._tag_failed_trial(context)
                if attempt == max_retries:
                    return False
            self._reset_trial_context(context)
        return False

    def _execute_node(
        self,
        session: Session,
        run: Run,
        node: WorkflowNode,
        context: dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> None:
        self._checkpoint(session, run)
        node_run = NodeRun(run_id=run.id, node_id=node.id, node_type=node.type, status="running")
        session.add(node_run)
        session.commit()
        try:
            output, stdout, stderr = self._dispatch(session, run, node, context, workflow)
            node_run.status = "succeeded"
            node_run.output = output
            node_run.stdout = stdout
            node_run.stderr = stderr
        except RunCancelled as exc:
            node_run.status = "cancelled"
            node_run.stderr = str(exc) or "Cancelled by operator"
            node_run.finished_at = datetime.now(UTC)
            session.commit()
            raise
        except Exception as exc:
            node_run.status = "failed"
            node_run.stderr = str(exc)
            node_run.finished_at = datetime.now(UTC)
            session.commit()
            raise
        node_run.finished_at = datetime.now(UTC)
        session.commit()

    def _dispatch(
        self,
        session: Session,
        run: Run,
        node: WorkflowNode,
        context: dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> tuple[dict[str, Any], str, str]:
        if node.type == "hypothesis":
            return self._dispatch_hypothesis(session, run, node, context, workflow)
        if node.type == "trial":
            return self._dispatch_legacy_trial(session, run, node, context)
        if node.type in {"execution", "script"}:
            return self._dispatch_execution(session, run, node, context, workflow)
        if node.type in {"eval_script", "evaluation"} and isinstance(
            node.config.get("command"), list
        ):
            return self._dispatch_eval_script(session, run, node, context)
        if node.type == "evaluation":
            return self._dispatch_evaluation(session, run, node, context, workflow)
        if node.type == "metric_gate":
            return self._dispatch_metric_gate(context, node)
        if node.type == "git_decision":
            return self._dispatch_git_decision(session, run, context)
        if node.type == "database":
            return {"skipped": True}, "", ""
        raise ExecutionError(f"unsupported node type {node.type}")

    def _dispatch_hypothesis(
        self,
        session: Session,
        run: Run,
        node: WorkflowNode,
        context: dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> tuple[dict[str, Any], str, str]:
        project_id = run.project_id or self._ensure_default_project(session, run)
        existing = list(
            session.scalars(
                select(HypothesisRecord)
                .where(HypothesisRecord.project_id == project_id)
                .order_by(HypothesisRecord.created_at.asc())
            )
        )
        hypothesis_code = f"H{len(existing) + 1:04d}"
        history_window = self._int_config(node, "history_window", DEFAULT_HISTORY_WINDOW)
        recent = list(reversed(existing[-history_window:]))
        recent_ids = [row.id for row in recent]
        recent_trials: list[TrialRecord] = []
        if recent_ids:
            recent_trials = list(
                session.scalars(
                    select(TrialRecord)
                    .where(TrialRecord.hypothesis_id.in_(recent_ids))
                    .order_by(TrialRecord.created_at.desc())
                )
            )

        allowed = allowed_paths_from_workflow(workflow)
        gate_node = find_node(workflow, "metric_gate")
        gate_config = dict(gate_node.config) if gate_node is not None else None
        hypo_payload = [self._hypothesis_dict(row) for row in recent]
        trial_payload = [self._trial_dict(row) for row in recent_trials]
        node_config = {
            **node.config,
            "system_prompt": node.config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT,
        }

        planner_meta: dict[str, Any] = {}
        if bool(node.config.get("use_planner", False)):
            try:
                title, description, planner_meta = plan_hypothesis(
                    hypothesis_code=hypothesis_code,
                    node_config=node_config,
                    recent_hypotheses=hypo_payload,
                    recent_trials=trial_payload,
                    context=context,
                    allowed_paths=allowed,
                    gate=gate_config,
                    project_root=self.git.project_root,
                    history_window=history_window,
                    observability_meta=self._observability_meta(
                        run,
                        node,
                        hypothesis_id=hypothesis_code,
                    ),
                )
            except HypothesisPlanError as exc:
                raise ExecutionError(f"hypothesis planner failed: {exc}") from exc
        else:
            title, description = build_hypothesis_brief(
                hypothesis_code=hypothesis_code,
                node_config=node_config,
                recent_hypotheses=hypo_payload,
                recent_trials=trial_payload,
                context=context,
                allowed_paths=allowed,
                gate=gate_config,
                history_window=history_window,
            )

        branch, base_commit = self.git.create_hypothesis(
            hypothesis_code,
            title,
            description,
        )
        context.update(
            hypothesis_id=hypothesis_code,
            hypothesis_branch=branch,
            hypothesis_base_commit=base_commit,
            project_id=project_id,
            history_window=history_window,
            hypothesis_brief=description,
            hypothesis_plan=planner_meta.get("plan"),
        )
        run.hypothesis_id = hypothesis_code
        run.branch = branch
        session.add(
            HypothesisRecord(
                id=f"{project_id}:{hypothesis_code}",
                project_id=project_id,
                title=title,
                description=description,
                branch=branch,
                base_commit=base_commit,
                champion_commit_at_start=base_commit,
                status="open",
            )
        )
        session.commit()
        return {
            "hypothesis_id": hypothesis_code,
            "branch": branch,
            "title": title,
            "history_window": history_window,
            "brief_chars": len(description),
            "planner": planner_meta.get("backend"),
            **{
                key: planner_meta[key]
                for key in ("agent_trace_id", "prompt_version", "observability_backend")
                if planner_meta.get(key)
            },
        }, description, ""

    def _dispatch_legacy_trial(
        self, session: Session, run: Run, node: WorkflowNode, context: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str]:
        self._require(context, "hypothesis_id", "hypothesis_branch")
        workspace = self.git.create_trial(
            context["hypothesis_id"],
            int(node.config.get("number", 1)),
            context["hypothesis_branch"],
        )
        context.update(
            trial=workspace,
            trial_id=workspace.trial_id,
            trial_branch=workspace.trial_branch,
            trial_number=int(node.config.get("number", 1)),
        )
        run.trial_id = workspace.trial_id
        run.branch = workspace.trial_branch
        session.commit()
        return (
            {
                "trial_id": workspace.trial_id,
                "branch": workspace.trial_branch,
                "worktree": str(workspace.path),
            },
            "",
            "",
        )

    def _dispatch_execution(
        self,
        session: Session,
        run: Run,
        node: WorkflowNode,
        context: dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> tuple[dict[str, Any], str, str]:
        workspace = self._workspace(context)
        allowed = allowed_paths_from_workflow(workflow)
        use_agent = self._wants_execution_agent(node)
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        agent_meta: dict[str, Any] = {}
        train_meta: dict[str, Any] = {}

        if use_agent:
            brief = str(context.get("hypothesis_brief") or "")
            if not brief and context.get("hypothesis_brief_path"):
                brief_path = Path(str(context["hypothesis_brief_path"]))
                if brief_path.is_file():
                    brief = brief_path.read_text(encoding="utf-8")
            try:
                agent_meta = apply_hypothesis_edits(
                    worktree=workspace.path,
                    brief=brief,
                    allowed_paths=allowed or [],
                    model=str(node.config.get("model") or "composer-2.5"),
                    title=str(context.get("hypothesis_id") or ""),
                    observability_meta=self._observability_meta(
                        run,
                        node,
                        hypothesis_id=str(context.get("hypothesis_id") or ""),
                        trial_id=str(context.get("trial_id") or workspace.trial_id),
                    ),
                )
            except CodeAgentError as exc:
                raise ExecutionError(str(exc)) from exc
            if agent_meta.get("stdout"):
                stdout_parts.append(str(agent_meta["stdout"]))
            if agent_meta.get("stderr"):
                stderr_parts.append(str(agent_meta["stderr"]))
            # Commit code edits before training so run artifacts stay out of the candidate.
            candidate_commit = self.git.commit_changes(
                workspace, str(node.config.get("commit_message") or f"trial: {node.name}")
            )
            if allowed is not None:
                self.git.assert_only_allowed_paths_changed(
                    context["hypothesis_base_commit"], candidate_commit, allowed
                )
            diff_text = self.git.diff(context["hypothesis_base_commit"], candidate_commit)
            if not diff_text.strip():
                raise ExecutionError(
                    "execution agent produced no committed diff against the hypothesis base"
                )
        else:
            candidate_commit = ""
            diff_text = ""

        command = node.config.get("command")
        if isinstance(command, list) and command:
            environment = node.config.get("environment", {})
            if not isinstance(environment, dict):
                raise ExecutionError("environment must be an object")
            environment = {
                **{str(key): str(value) for key, value in environment.items()},
                "AUTORESEARCH_HYPOTHESIS_ID": str(context.get("hypothesis_id", "")),
                "AUTORESEARCH_TRIAL_ID": workspace.trial_id,
                "AUTORESEARCH_TRIAL_NUMBER": str(context.get("trial_number", 1)),
                "AUTORESEARCH_HYPOTHESIS_BRIEF_PATH": str(
                    context.get("hypothesis_brief_path") or ""
                ),
            }
            result = self.runner.run(
                command,
                workspace.path,
                environment=environment,
                timeout_seconds=int(node.config.get("timeout_seconds", 0)) or None,
                run_id=run.id,
            )
            if result.returncode:
                raise RunnerError(
                    f"command failed with exit code {result.returncode}: {result.stderr}"
                )
            stdout_parts.append(result.stdout)
            stderr_parts.append(result.stderr)
            train_meta = {
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
                "trained": True,
            }
        elif not use_agent:
            raise ExecutionError("execution node requires command as a string array")

        if not use_agent:
            candidate_commit = self.git.commit_changes(
                workspace, str(node.config.get("commit_message") or f"trial: {node.name}")
            )
            if allowed is not None:
                self.git.assert_only_allowed_paths_changed(
                    context["hypothesis_base_commit"], candidate_commit, allowed
                )
            diff_text = self.git.diff(context["hypothesis_base_commit"], candidate_commit)

        change_summary = summarize_diff(diff_text)
        context["candidate_commit"] = candidate_commit
        context["candidate_diff"] = diff_text
        self._update_trial_record(
            session,
            context,
            candidate_commit=candidate_commit,
            what_changed=change_summary,
        )
        return (
            {
                **agent_meta,
                **train_meta,
                "candidate_commit": candidate_commit,
                "what_changed": change_summary,
                "diff_chars": len(diff_text),
                "use_agent": use_agent,
            },
            "\n".join(part for part in stdout_parts if part),
            "\n".join(part for part in stderr_parts if part),
        )

    @staticmethod
    def _wants_execution_agent(node: WorkflowNode) -> bool:
        if "use_agent" in node.config:
            return bool(node.config.get("use_agent"))
        command = node.config.get("command")
        if isinstance(command, list):
            joined = " ".join(str(part) for part in command)
            if "candidate committed" in joined:
                return True
        return False

    def _dispatch_eval_script(
        self, session: Session, run: Run, node: WorkflowNode, context: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str]:
        workspace = self._workspace(context)
        command = node.config.get("command")
        if not isinstance(command, list):
            raise ExecutionError("eval_script node requires command as a string array")
        candidate_commit = context.get("candidate_commit") or self.git.head(cwd=workspace.path)
        configured_paths = node.config.get("protected_paths", self.protected_paths)
        if not isinstance(configured_paths, list) or not all(
            isinstance(path, str) for path in configured_paths
        ):
            raise ExecutionError("protected_paths must be a string array")
        self.git.assert_paths_unchanged(
            context["hypothesis_base_commit"], candidate_commit, configured_paths
        )
        environment = {
            "AUTORESEARCH_HYPOTHESIS_ID": str(context.get("hypothesis_id", "")),
            "AUTORESEARCH_TRIAL_ID": workspace.trial_id,
            "AUTORESEARCH_TRIAL_NUMBER": str(context.get("trial_number", 1)),
        }
        result = self.runner.run(
            command,
            workspace.path,
            environment=environment,
            timeout_seconds=int(node.config.get("timeout_seconds", 0)) or None,
            run_id=run.id,
        )
        if result.returncode:
            raise RunnerError(
                f"command failed with exit code {result.returncode}: {result.stderr}"
            )
        metrics = self.runner.parse_evaluation(result)
        evaluator_commit = self.git.head(self.git.champion_branch)
        context["candidate_commit"] = candidate_commit
        context["metrics"] = metrics
        context["eval_duration_seconds"] = result.duration_seconds
        context["eval_stdout"] = result.stdout
        context["evaluator_commit"] = evaluator_commit
        for name, value in metrics.items():
            session.add(Metric(run_id=run.id, project_id=run.project_id, name=name, value=value))
        self._update_trial_record(session, context, metrics=metrics)
        return {"metrics": metrics}, result.stdout, result.stderr

    def _dispatch_evaluation(
        self,
        session: Session,
        run: Run,
        node: WorkflowNode,
        context: dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> tuple[dict[str, Any], str, str]:
        metrics = context.get("metrics")
        if not isinstance(metrics, dict):
            raise ExecutionError("evaluation agent requires metrics from eval script")
        trial_id = str(context.get("trial_id") or "")
        if not trial_id:
            raise ExecutionError("evaluation agent requires trial_id")

        gate = find_node(workflow, "metric_gate")
        gate_config = gate.config if gate is not None else {}
        primary_metric = str(gate_config.get("metric") or "score")
        direction = str(gate_config.get("direction") or "maximize")
        min_delta = float(gate_config.get("min_delta", 0) or 0)

        champion_metrics: dict[str, Any] = {}
        evaluator_commit = str(
            context.get("evaluator_commit") or self.git.head(self.git.champion_branch)
        )
        champion = self.git.read_note("research/champions", evaluator_commit)
        if champion and isinstance(champion.get("metrics"), dict):
            champion_metrics = champion["metrics"]
        elif isinstance(gate_config.get("baseline"), (int, float)) and primary_metric:
            champion_metrics = {primary_metric: float(gate_config["baseline"])}

        candidate_commit = str(context.get("candidate_commit") or "")
        stdout = str(context.get("eval_stdout") or "")
        duration = context.get("eval_duration_seconds")
        system_prompt = str(node.config.get("system_prompt") or "")
        model = str(node.config.get("model") or "composer-2.5")

        # Structural record first (metrics/deltas/signals), then LLM judgment overlays narrative.
        structural = build_evaluation_record(
            trial_id=trial_id,
            run_id=run.id,
            metrics=metrics,
            champion_metrics=champion_metrics,
            primary_metric=primary_metric,
            direction=direction,
            min_delta=min_delta,
            candidate_commit=candidate_commit,
            evaluator_commit=evaluator_commit,
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
            stdout_excerpt=stdout.strip()[:2000],
            status="passed",
            model=model,
            system_prompt=system_prompt,
        )

        hypothesis_title = ""
        hypothesis_description = ""
        what_changed = ""
        project_id = run.project_id
        if project_id:
            hypo_id = f"{project_id}:{structural['hypothesis_id']}"
            trial_row_id = f"{project_id}:{trial_id}"
            hypo = session.get(HypothesisRecord, hypo_id)
            trial = session.get(TrialRecord, trial_row_id)
            if hypo is not None:
                hypothesis_title = hypo.title
                hypothesis_description = hypo.description
            if trial is not None:
                what_changed = trial.what_changed

        require_agent = bool(node.config.get("use_agent", True))
        judgment: dict[str, Any] | None = None
        try:
            judgment = judge_evaluation(
                node_config=node.config,
                trial_id=trial_id,
                hypothesis_id=str(structural["hypothesis_id"]),
                hypothesis_title=hypothesis_title,
                hypothesis_description=hypothesis_description,
                what_changed=what_changed,
                metrics=structural["metrics"],
                champion_metrics=structural["champion_metrics"],
                deltas=structural["deltas"],
                signals=structural["signals"],
                primary_metric=primary_metric,
                direction=direction,
                min_delta=min_delta,
                stdout_excerpt=stdout.strip()[:2000],
                project_root=self.git.project_root,
                model=model,
                observability_meta=self._observability_meta(
                    run,
                    node,
                    hypothesis_id=str(structural["hypothesis_id"]),
                    trial_id=trial_id,
                ),
            )
        except EvaluationAgentError as exc:
            if require_agent:
                raise ExecutionError(str(exc)) from exc
            # Offline / no-key tests keep deterministic narrative.

        record = (
            build_evaluation_record(
                trial_id=trial_id,
                run_id=run.id,
                metrics=metrics,
                champion_metrics=champion_metrics,
                primary_metric=primary_metric,
                direction=direction,
                min_delta=min_delta,
                candidate_commit=candidate_commit,
                evaluator_commit=evaluator_commit,
                duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
                stdout_excerpt=stdout.strip()[:2000],
                status="passed",
                model=model,
                system_prompt=system_prompt,
                judgment=judgment,
            )
            if judgment is not None
            else structural
        )
        context["evaluation_summary"] = record["summary"]
        context["evaluation_record"] = record
        if candidate_commit:
            self.git.add_note("research/evaluations", candidate_commit, record)
        return record, record["summary"], ""

    def _dispatch_metric_gate(
        self, context: dict[str, Any], node: WorkflowNode
    ) -> tuple[dict[str, Any], str, str]:
        metrics = context.get("metrics")
        if not isinstance(metrics, dict):
            raise ExecutionError("metric gate requires evaluation metrics")
        metric = str(node.config.get("metric") or "score")
        if metric not in metrics:
            raise ExecutionError(f"metric {metric!r} was not emitted")
        champion_commit = self.git.head(self.git.champion_branch)
        champion = self.git.read_note("research/champions", champion_commit)
        if champion and isinstance(champion.get("metrics"), dict):
            baseline_value = champion["metrics"].get(metric)
        else:
            baseline_value = node.config.get("baseline")
        if baseline_value is None:
            raise ExecutionError(
                f"metric gate has no champion value or configured baseline for {metric!r}"
            )
        baseline = float(baseline_value)
        min_delta = float(node.config.get("min_delta", 0))
        direction = str(node.config.get("direction", "maximize"))
        value = float(metrics[metric])
        accepted = (
            value >= baseline + min_delta
            if direction == "maximize"
            else value <= baseline - min_delta
        )
        context.update(gate_passed=accepted, gate_metric=metric, gate_baseline=baseline)
        return (
            {
                "accepted": accepted,
                "metric": metric,
                "value": value,
                "baseline": baseline,
                "direction": direction,
            },
            "",
            "",
        )

    def _dispatch_git_decision(
        self, session: Session, run: Run, context: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str]:
        workspace = self._workspace(context)
        self._require(context, "candidate_commit", "hypothesis_base_commit", "gate_passed")
        accepted = bool(context["gate_passed"])
        outcome = "accepted" if accepted else "rejected"
        reason = (
            f"metric gate passed for {context.get('gate_metric')}"
            if accepted
            else f"metric gate failed for {context.get('gate_metric')}"
        )
        record = {
            "schema_version": "1",
            "trial_id": workspace.trial_id,
            "candidate_commit": context["candidate_commit"],
            "baseline_commit": context["hypothesis_base_commit"],
            "outcome": outcome,
            "reason": reason,
            "metrics": context.get("metrics", {}),
            "created_at": datetime.now(UTC).isoformat(),
        }
        output: dict[str, Any] = {"outcome": outcome}
        if accepted:
            # Merge before note/tag so a dirty or advanced champion cannot leave an
            # accepted ledger without promoting the trial onto the champion branch.
            champion_commit = self.git.merge_trial(
                workspace.trial_branch, context["hypothesis_base_commit"]
            )
            self.git.record_champion(
                champion_commit,
                {
                    "schema_version": "1",
                    "trial_id": workspace.trial_id,
                    "candidate_commit": context["candidate_commit"],
                    "champion_commit": champion_commit,
                    "metrics": context.get("metrics", {}),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            output["champion_commit"] = champion_commit
        self.git.add_note("research/decisions", context["candidate_commit"], record)
        tag = self.git.tag_decision(outcome, workspace.trial_id, context["candidate_commit"])
        output["tag"] = tag
        try:
            output["remote"] = self.git.push_research_to_origin()
        except GitError as exc:
            output["remote"] = {"pushed": False, "error": str(exc)}
        context["last_decision"] = outcome
        context["last_metrics"] = context.get("metrics", {})
        prior_change = ""
        trial_id = context.get("trial_id")
        project_id = context.get("project_id")
        if trial_id and project_id:
            existing = session.get(TrialRecord, f"{project_id}:{trial_id}")
            if existing is not None:
                prior_change = existing.what_changed or ""
        change_note = prior_change if prior_change and not prior_change.startswith("metric gate") else ""
        if not change_note:
            change_note = summarize_diff(str(context.get("candidate_diff") or ""))
        self._update_trial_record(
            session,
            context,
            outcome=outcome,
            next_step=(
                "Merged into champion; next hypothesis uses new master."
                if accepted
                else "Rejected; next hypothesis uses last stable master."
            ),
            what_changed=f"{change_note} ({reason})" if change_note else reason,
        )
        return output, "", ""

    def _start_trial(
        self, session: Session, run: Run, context: dict[str, Any], attempt: int
    ) -> NodeRun:
        self._require(context, "hypothesis_id", "hypothesis_branch", "project_id")
        node_run = NodeRun(
            run_id=run.id,
            node_id=f"trial-T{attempt:03d}",
            node_type="trial",
            status="running",
        )
        session.add(node_run)
        session.commit()
        try:
            workspace = self.git.create_trial(
                context["hypothesis_id"], attempt, context["hypothesis_branch"]
            )
            context.update(
                trial=workspace,
                trial_id=workspace.trial_id,
                trial_branch=workspace.trial_branch,
                trial_number=attempt,
            )
            run.trial_id = workspace.trial_id
            run.branch = workspace.trial_branch
            brief = str(context.get("hypothesis_brief") or "")
            brief_path = ""
            if brief:
                briefs_dir = self.git.runtime_root / "briefs"
                briefs_dir.mkdir(parents=True, exist_ok=True)
                brief_file = briefs_dir / f"{workspace.trial_id.replace('/', '-')}.md"
                brief_file.write_text(brief, encoding="utf-8")
                brief_path = str(brief_file)
                context["hypothesis_brief_path"] = brief_path
            node_run.output = {
                "trial_id": workspace.trial_id,
                "branch": workspace.trial_branch,
                "worktree": str(workspace.path),
                "number": attempt,
                "brief_path": brief_path or None,
            }
            session.merge(
                TrialRecord(
                    id=f"{context['project_id']}:{workspace.trial_id}",
                    project_id=context["project_id"],
                    hypothesis_id=f"{context['project_id']}:{context['hypothesis_id']}",
                    branch=workspace.trial_branch,
                    worktree_path=str(workspace.path),
                    outcome="running",
                )
            )
            session.commit()
            return node_run
        except Exception as exc:
            node_run.status = "failed"
            node_run.stderr = str(exc)
            node_run.finished_at = datetime.now(UTC)
            session.commit()
            raise

    def _finalize_hypothesis(self, session: Session, run: Run, context: dict[str, Any]) -> None:
        hypothesis_id = context.get("hypothesis_id")
        project_id = context.get("project_id")
        if not hypothesis_id or not project_id:
            return
        record = session.get(HypothesisRecord, f"{project_id}:{hypothesis_id}")
        if record is None:
            return
        accepted = bool(context.get("gate_passed"))
        trial_rows = list(
            session.scalars(
                select(TrialRecord).where(
                    TrialRecord.hypothesis_id == f"{project_id}:{hypothesis_id}"
                )
            )
        )
        what_worked, what_did_not = summarize_outcome(
            accepted=accepted,
            metrics=context.get("metrics") or {},
            gate_metric=str(context.get("gate_metric") or "") or None,
            gate_baseline=context.get("gate_baseline"),
            trial_notes=[self._trial_dict(row) for row in trial_rows],
            evaluation_summary=str(context.get("evaluation_summary") or "") or None,
        )
        record.status = "accepted" if accepted else "rejected"
        record.metrics = context.get("metrics") or {}
        record.what_worked = what_worked
        record.what_did_not = what_did_not
        record.updated_at = datetime.now(UTC)
        session.commit()

    @staticmethod
    def _hypothesis_dict(row: HypothesisRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title,
            "description": row.description,
            "status": row.status,
            "what_worked": row.what_worked,
            "what_did_not": row.what_did_not,
            "metrics": row.metrics or {},
        }

    @staticmethod
    def _trial_dict(row: TrialRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "hypothesis_id": row.hypothesis_id,
            "outcome": row.outcome,
            "error": row.error,
            "next_step": row.next_step,
            "what_changed": row.what_changed,
            "metrics": row.metrics or {},
        }

    def _update_trial_record(
        self,
        session: Session,
        context: dict[str, Any],
        *,
        outcome: str | None = None,
        error: str | None = None,
        next_step: str | None = None,
        what_changed: str | None = None,
        candidate_commit: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        trial_id = context.get("trial_id")
        project_id = context.get("project_id")
        if not trial_id or not project_id:
            return
        record = session.get(TrialRecord, f"{project_id}:{trial_id}")
        if record is None:
            return
        if outcome is not None:
            record.outcome = outcome
        if error is not None:
            record.error = error
        if next_step is not None:
            record.next_step = next_step
        if what_changed is not None:
            record.what_changed = what_changed
        if candidate_commit is not None:
            record.candidate_commit = candidate_commit
        if metrics is not None:
            record.metrics = metrics
        record.updated_at = datetime.now(UTC)

    def _upsert_chat_summary(self, session: Session, run: Run) -> None:
        if not run.project_id:
            return
        summary = session.scalar(
            select(ChatSummary).where(ChatSummary.project_id == run.project_id)
        )
        text = (
            f"Run {run.id[:8]} finished with status {run.status}. "
            f"Latest hypothesis {run.hypothesis_id}, trial {run.trial_id}."
        )
        if summary is None:
            session.add(ChatSummary(project_id=run.project_id, summary=text))
        else:
            summary.summary = text
            summary.updated_at = datetime.now(UTC)
        session.commit()

    def _ensure_default_project(self, session: Session, run: Run) -> str:
        project = session.scalar(select(Project).where(Project.is_active.is_(True)))
        if project is None:
            project = Project(
                name="default",
                local_path=str(self.git.project_root),
                pg_schema="proj_default",
                is_active=True,
                status="active",
            )
            session.add(project)
            session.commit()
        run.project_id = project.id
        session.commit()
        return project.id

    @staticmethod
    def _observability_meta(
        run: Run,
        node: WorkflowNode,
        *,
        hypothesis_id: str = "",
        trial_id: str = "",
    ) -> dict[str, Any]:
        return {
            "project_id": str(run.project_id or ""),
            "run_id": str(run.id),
            "node_id": str(node.id),
            "node_type": str(node.type),
            "hypothesis_id": hypothesis_id,
            "trial_id": trial_id,
            "tags": ["autoresearch", str(node.type)],
        }

    @staticmethod
    def _int_config(node: WorkflowNode, key: str, default: int) -> int:
        raw = node.config.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ExecutionError(f"hypothesis {key} must be an integer") from exc
        if value < 1:
            raise ExecutionError(f"hypothesis {key} must be >= 1")
        return value

    @staticmethod
    def _next_step_hint(error: str, attempt: int, max_retries: int) -> str:
        if "protected paths" in error:
            return "Do not modify protected evaluator paths; adjust the candidate only."
        if attempt < max_retries:
            return f"Retry as T{attempt + 1:03d} under the same hypothesis."
        return "Retries exhausted; start a new hypothesis from last stable master."

    def _tag_failed_trial(self, context: dict[str, Any]) -> None:
        workspace = context.get("trial")
        if not isinstance(workspace, TrialWorkspace):
            return
        try:
            commit = context.get("candidate_commit") or self.git.head(cwd=workspace.path)
            self.git.tag_decision("failed", workspace.trial_id, str(commit))
        except Exception:
            return

    @staticmethod
    def _reset_trial_context(context: dict[str, Any]) -> None:
        for key in (
            "trial",
            "trial_id",
            "trial_branch",
            "trial_number",
            "candidate_commit",
            "metrics",
            "gate_passed",
            "gate_metric",
            "gate_baseline",
        ):
            context.pop(key, None)

    @staticmethod
    def _require(context: dict[str, Any], *keys: str) -> None:
        missing = [key for key in keys if key not in context]
        if missing:
            raise ExecutionError(f"missing workflow context: {', '.join(missing)}")

    @staticmethod
    def _workspace(context: dict[str, Any]) -> TrialWorkspace:
        workspace = context.get("trial")
        if not isinstance(workspace, TrialWorkspace):
            raise ExecutionError("node requires a trial worktree")
        return workspace

    @staticmethod
    def _serializable_context(context: dict[str, Any]) -> dict[str, Any]:
        serialized = dict(context)
        workspace = serialized.pop("trial", None)
        if isinstance(workspace, TrialWorkspace):
            serialized["worktree"] = str(workspace.path)
        return serialized
