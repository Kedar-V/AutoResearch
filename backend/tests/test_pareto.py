from __future__ import annotations

from autoresearch_api.pareto import (
    FrontierPoint,
    HardGateSpec,
    ObjectiveSpec,
    epsilon_dominates,
    hard_gates_ok,
    update_frontier,
)


OBJ = [
    ObjectiveSpec("loss", "minimize", 0.01),
    ObjectiveSpec("vram", "minimize", 10),
]


def test_epsilon_dominates_when_better_on_one_and_not_worse() -> None:
    assert epsilon_dominates({"loss": 1.0, "vram": 100}, {"loss": 1.1, "vram": 100}, OBJ)
    assert not epsilon_dominates({"loss": 1.0, "vram": 120}, {"loss": 1.1, "vram": 100}, OBJ)


def test_tradeoff_neither_dominates() -> None:
    a = {"loss": 1.0, "vram": 200}
    b = {"loss": 1.2, "vram": 80}
    assert not epsilon_dominates(a, b, OBJ)
    assert not epsilon_dominates(b, a, OBJ)


def test_epsilon_noise_does_not_strictly_dominate() -> None:
    # Within ε on both axes → no strict improvement → not dominates
    assert not epsilon_dominates({"loss": 1.005, "vram": 100}, {"loss": 1.0, "vram": 100}, OBJ)


def test_update_frontier_keep_and_prune_dominated() -> None:
    frontier = [
        FrontierPoint("a" * 40, "H0001/T001", {"loss": 1.2, "vram": 100}),
        FrontierPoint("b" * 40, "H0002/T001", {"loss": 1.0, "vram": 50}),
    ]
    candidate = FrontierPoint("c" * 40, "H0003/T001", {"loss": 0.9, "vram": 100})
    kept, next_frontier = update_frontier(frontier, candidate, OBJ)
    assert kept is True
    commits = {point.commit for point in next_frontier}
    assert "c" * 40 in commits
    assert "a" * 40 not in commits  # dominated on both
    assert "b" * 40 in commits  # tradeoff remains (better vram)


def test_update_frontier_discard_when_dominated() -> None:
    frontier = [FrontierPoint("a" * 40, "H0001/T001", {"loss": 1.0, "vram": 100})]
    candidate = FrontierPoint("c" * 40, "H0003/T001", {"loss": 1.2, "vram": 120})
    kept, next_frontier = update_frontier(frontier, candidate, OBJ)
    assert kept is False
    assert len(next_frontier) == 1


def test_hard_gates_kill_nan_and_threshold() -> None:
    ok, reason = hard_gates_ok(
        {"loss": float("nan"), "ok": 1},
        [HardGateSpec("loss", finite=True), HardGateSpec("ok", equals=1.0)],
    )
    assert ok is False
    assert "not finite" in reason

    ok, _ = hard_gates_ok({"loss": 1.0, "ok": 1}, [HardGateSpec("ok", equals=1.0)])
    assert ok is True

    ok, reason = hard_gates_ok({"ok": 0}, [HardGateSpec("ok", equals=1.0)])
    assert ok is False


def test_near_duplicates_within_epsilon_can_both_remain() -> None:
    # Classic coarsened ε-dominance: neither strictly dominates within ε
    frontier = [FrontierPoint("a" * 40, "H0001/T001", {"loss": 1.0, "vram": 100})]
    twin = FrontierPoint("b" * 40, "H0002/T001", {"loss": 1.005, "vram": 105})
    kept, next_frontier = update_frontier(frontier, twin, OBJ)
    assert kept is True
    assert len(next_frontier) == 2
