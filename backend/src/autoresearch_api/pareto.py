"""ε-Pareto frontier helpers for multi-objective promotion.

Scalar single-metric gates remain the default elsewhere. This module is pure
policy math: hard gates → ε-dominance → KEEP/DISCARD. No LLM judges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ObjectiveSpec:
    metric: str
    direction: Literal["minimize", "maximize"] = "minimize"
    epsilon: float = 0.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> ObjectiveSpec:
        metric = str(raw.get("metric") or "").strip()
        if not metric:
            raise ValueError("objective requires metric")
        direction = str(raw.get("direction") or "minimize").lower()
        if direction not in {"minimize", "maximize"}:
            raise ValueError(f"invalid objective direction: {direction}")
        epsilon = float(raw.get("epsilon") or 0)
        if epsilon < 0:
            raise ValueError("epsilon must be >= 0")
        return cls(metric=metric, direction=direction, epsilon=epsilon)  # type: ignore[arg-type]


@dataclass(frozen=True)
class HardGateSpec:
    metric: str
    finite: bool = False
    equals: float | None = None
    min_value: float | None = None
    max_value: float | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> HardGateSpec:
        metric = str(raw.get("metric") or "").strip()
        if not metric:
            raise ValueError("hard gate requires metric")
        equals = raw.get("equals")
        min_value = raw.get("min")
        max_value = raw.get("max")
        return cls(
            metric=metric,
            finite=bool(raw.get("finite")),
            equals=float(equals) if equals is not None else None,
            min_value=float(min_value) if min_value is not None else None,
            max_value=float(max_value) if max_value is not None else None,
        )


@dataclass(frozen=True)
class FrontierPoint:
    commit: str
    trial_id: str
    metrics: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "trial_id": self.trial_id,
            "metrics": dict(self.metrics),
        }


def parse_objectives(raw: Any) -> list[ObjectiveSpec]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("pareto policy requires a non-empty objectives list")
    return [ObjectiveSpec.from_mapping(item) for item in raw if isinstance(item, dict)]


def parse_hard_gates(raw: Any) -> list[HardGateSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("hard_gates must be a list")
    return [HardGateSpec.from_mapping(item) for item in raw if isinstance(item, dict)]


def _metric_value(metrics: dict[str, Any], name: str) -> float:
    if name not in metrics:
        raise KeyError(name)
    value = float(metrics[name])
    return value


def hard_gates_ok(metrics: dict[str, Any], gates: list[HardGateSpec]) -> tuple[bool, str]:
    """Return (ok, reason). Fail closed on missing/non-finite when required."""
    for gate in gates:
        if gate.metric not in metrics:
            return False, f"hard gate missing metric {gate.metric!r}"
        try:
            value = float(metrics[gate.metric])
        except (TypeError, ValueError):
            return False, f"hard gate metric {gate.metric!r} is not numeric"
        if gate.finite and not _is_finite(value):
            return False, f"hard gate metric {gate.metric!r} is not finite"
        if gate.equals is not None and value != gate.equals:
            return False, f"hard gate {gate.metric!r} != {gate.equals}"
        if gate.min_value is not None and value < gate.min_value:
            return False, f"hard gate {gate.metric!r} < {gate.min_value}"
        if gate.max_value is not None and value > gate.max_value:
            return False, f"hard gate {gate.metric!r} > {gate.max_value}"
    return True, ""


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _better_or_equal(value: float, other: float, *, direction: str, epsilon: float) -> bool:
    """True if value is at least as good as other within epsilon (coarsened)."""
    if direction == "minimize":
        return value <= other + epsilon
    return value >= other - epsilon


def _strictly_better(value: float, other: float, *, direction: str, epsilon: float) -> bool:
    if direction == "minimize":
        return value < other - epsilon
    return value > other + epsilon


def epsilon_dominates(
    left: dict[str, Any],
    right: dict[str, Any],
    objectives: list[ObjectiveSpec],
) -> bool:
    """True if left ε-dominates right: <= on all (w.r.t. direction), < on at least one."""
    all_at_least = True
    any_strict = False
    for objective in objectives:
        lv = _metric_value(left, objective.metric)
        rv = _metric_value(right, objective.metric)
        if not _better_or_equal(lv, rv, direction=objective.direction, epsilon=objective.epsilon):
            all_at_least = False
            break
        if _strictly_better(lv, rv, direction=objective.direction, epsilon=objective.epsilon):
            any_strict = True
    return all_at_least and any_strict


def is_dominated(
    candidate: dict[str, Any],
    frontier: list[FrontierPoint],
    objectives: list[ObjectiveSpec],
) -> bool:
    for point in frontier:
        if epsilon_dominates(point.metrics, candidate, objectives):
            return True
    return False


def update_frontier(
    frontier: list[FrontierPoint],
    candidate: FrontierPoint,
    objectives: list[ObjectiveSpec],
) -> tuple[bool, list[FrontierPoint]]:
    """KEEP if not ε-dominated; drop points the candidate ε-dominates.

    Near-duplicates within ε of each other may both remain (coarsened ε-dominance).
    """
    for objective in objectives:
        if objective.metric not in candidate.metrics:
            raise KeyError(objective.metric)
        float(candidate.metrics[objective.metric])

    if is_dominated(candidate.metrics, frontier, objectives):
        return False, list(frontier)

    kept = [
        point
        for point in frontier
        if not epsilon_dominates(candidate.metrics, point.metrics, objectives)
    ]
    # Replace same commit if re-evaluated
    kept = [point for point in kept if point.commit != candidate.commit]
    kept.append(candidate)
    return True, kept
