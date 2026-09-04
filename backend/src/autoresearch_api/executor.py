from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .git_service import GitService, TrialWorkspace
from .models import Metric, NodeRun, Run, Workflow
from .runner import LocalRunner, RunnerError
from .schemas import WorkflowDefinition, WorkflowNode
from .workflow import topological_order


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

        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()
        context: dict[str, Any] = {}
        try:
            workflow = WorkflowDefinition.model_validate(workflow_row.definition)
            self.git.verify_repository()
            for node in topological_order(workflow):
                self._execute_node(session, run, node, context)
            run.status = "succeeded"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
        finally:
            run.context = self._serializable_context(context)
            run.finished_at = datetime.now(UTC)
            session.commit()
            session.refresh(run)
        return run

    def _execute_node(
        self, session: Session, run: Run, node: WorkflowNode, context: dict[str, Any]
    ) -> None:
        node_run = NodeRun(run_id=run.id, node_id=node.id, node_type=node.type, status="running")
        session.add(node_run)
        session.commit()
        try:
            output, stdout, stderr = self._dispatch(session, run, node, context)
            node_run.status = "succeeded"
            node_run.output = output
            node_run.stdout = stdout
            node_run.stderr = stderr
        except Exception as exc:
            node_run.status = "failed"
            node_run.stderr = str(exc)
            node_run.finished_at = datetime.now(UTC)
            session.commit()
            raise
        node_run.finished_at = datetime.now(UTC)
        session.commit()

    def _dispatch(
        self, session: Session, run: Run, node: WorkflowNode, context: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str]:
        if node.type == "hypothesis":
            number = session.scalar(select(func.count(Run.hypothesis_id))) or 0
            hypothesis_id = f"H{number + 1:04d}"
            title = str(node.config.get("title") or node.name)
            description = str(node.config.get("description") or title)
            branch, base_commit = self.git.create_hypothesis(hypothesis_id, title, description)
            context.update(
                hypothesis_id=hypothesis_id,
                hypothesis_branch=branch,
                hypothesis_base_commit=base_commit,
            )
            run.hypothesis_id = hypothesis_id
            run.branch = branch
            session.commit()
            return {"hypothesis_id": hypothesis_id, "branch": branch}, "", ""

        if node.type == "trial":
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

        if node.type in {"script", "evaluation"}:
            workspace = self._workspace(context)
            command = node.config.get("command")
            if not isinstance(command, list):
                raise ExecutionError(f"{node.type} node requires command as a string array")
            environment = node.config.get("environment", {})
            if not isinstance(environment, dict):
                raise ExecutionError("environment must be an object")
            candidate_commit = context.get("candidate_commit") or self.git.head(cwd=workspace.path)
            if node.type == "evaluation":
                configured_paths = node.config.get("protected_paths", self.protected_paths)
                if not isinstance(configured_paths, list) or not all(
                    isinstance(path, str) for path in configured_paths
                ):
                    raise ExecutionError("protected_paths must be a string array")
                self.git.assert_paths_unchanged(
                    context["hypothesis_base_commit"], candidate_commit, configured_paths
                )
            result = self.runner.run(
                command,
                workspace.path,
                environment={str(key): str(value) for key, value in environment.items()},
                timeout_seconds=int(node.config.get("timeout_seconds", 0)) or None,
            )
            if result.returncode:
                raise RunnerError(
                    f"command failed with exit code {result.returncode}: {result.stderr}"
                )
            output: dict[str, Any] = {
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
            }
            if node.type == "script":
                candidate_commit = self.git.commit_changes(
                    workspace, str(node.config.get("commit_message") or f"trial: {node.name}")
                )
                context["candidate_commit"] = candidate_commit
                output["candidate_commit"] = candidate_commit
            else:
                metrics = self.runner.parse_evaluation(result)
                context["candidate_commit"] = candidate_commit
                context["metrics"] = metrics
                for name, value in metrics.items():
                    session.add(Metric(run_id=run.id, name=name, value=value))
                record = {
                    "schema_version": "1",
                    "trial_id": workspace.trial_id,
                    "candidate_commit": candidate_commit,
                    "evaluator_commit": self.git.head(self.git.champion_branch),
                    "status": "passed",
                    "metrics": metrics,
                    "duration_seconds": result.duration_seconds,
                    "created_at": datetime.now(UTC).isoformat(),
                }
                self.git.add_note("research/evaluations", candidate_commit, record)
                output["metrics"] = metrics
            return output, result.stdout, result.stderr

        if node.type == "metric_gate":
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

        if node.type == "git_decision":
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
            self.git.add_note("research/decisions", context["candidate_commit"], record)
            tag = self.git.tag_decision(outcome, workspace.trial_id, context["candidate_commit"])
            output: dict[str, Any] = {"outcome": outcome, "tag": tag}
            if accepted:
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
            return output, "", ""

        raise ExecutionError(f"unsupported node type {node.type}")

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
