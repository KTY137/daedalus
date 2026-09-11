"""Acceptance test C2 (G3-BASE-01 §5c): the Best-of-N baseline arm.

Fast, offline, no model calls. The candidate pool is real repository chunks
(via ``daedalus.eval.harness._repo_chunks``, the same function BM25 reuses) so
the arm is exercised exactly the way it runs in production, not against a
fake candidate source.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.arms.best_of_n import BestOfNArm
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial

N_CHUNKS = 6


def _build_repo(tmp_path) -> str:
    """N single-function files -> N distinct BM25/Best-of-N chunks."""
    for i in range(N_CHUNKS):
        (tmp_path / f"mod_{i}.py").write_text(
            f"def func_{i}():\n    return 'MARK_{i}'\n", encoding="utf-8")
    return str(tmp_path)


def _task(repo_root: str) -> Task:
    return Task(task_id="t1", repo_root=repo_root, question="irrelevant",
                target="mod_0.py::func_0", label_plane="code")


def _marker_evaluator(best_marker: str, max_calls: int | None = None) -> SealedEvaluator:
    """Score 1.0 iff ``best_marker`` appears in the candidate, else 0.1 --
    gives every trial exactly one known-best candidate to find."""

    def _score(candidate: str, task: Task) -> float:
        return 1.0 if best_marker in candidate else 0.1

    return SealedEvaluator("marker", _score, max_calls=max_calls)


def test_produces_trial_result_via_run_trial(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_2", max_calls=budget.max_calls)

    result = run_trial(arm, task, budget, evaluator, seed=7)

    assert result.arm == "best_of_n"
    assert result.task_id == "t1"
    assert result.error is None
    assert result.measured
    assert result.success in (True, False)
    assert result.calls == 3
    assert result.tokens_used > 0
    assert result.budget_exceeded is False


def test_n_scales_with_declared_call_budget(tmp_path):
    """budget 3 -> at most 3 evaluator calls, even though 6 chunks exist."""
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_0", max_calls=None)  # uncapped counter, arm self-limits

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is None
    assert evaluator.calls == 3
    assert outcome.notes["n_sampled"] == 3
    assert outcome.notes["n_candidates_available"] == N_CHUNKS
    assert outcome.notes["n_default_used"] is False


def test_returns_the_argmax(tmp_path):
    """Full-coverage budget (N == pool size) guarantees the known-best chunk
    is sampled regardless of seed; the arm must still pick it as the argmax."""
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=N_CHUNKS)
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_4", max_calls=budget.max_calls)

    outcome = arm.run(task, budget, evaluator, seed=99)

    assert outcome.error is None
    assert outcome.score == 1.0
    assert "MARK_4" in outcome.candidate
    assert outcome.success is True


def test_same_seed_is_identical(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()

    ev1 = _marker_evaluator("MARK_5", max_calls=budget.max_calls)
    ev2 = _marker_evaluator("MARK_5", max_calls=budget.max_calls)
    out1 = arm.run(task, budget, ev1, seed=42)
    out2 = arm.run(task, budget, ev2, seed=42)

    assert out1.candidate == out2.candidate
    assert out1.score == out2.score
    assert out1.notes["best_label"] == out2.notes["best_label"]


def test_different_seeds_sample_differently(tmp_path):
    """stochastic=True must be truthful: distinct seeds over a pool larger
    than N must (for these fixed, checked-in seed values) sample a different
    subset. A scorer that discriminates by label surfaces this as a different
    winning chunk or a different score whenever the known-best chunk is only
    sometimes in the sample."""
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()

    labels_by_seed = {}
    for seed in range(5):
        ev = _marker_evaluator("MARK_3", max_calls=budget.max_calls)
        outcome = arm.run(task, budget, ev, seed=seed)
        labels_by_seed[seed] = outcome.notes["best_label"]

    assert arm.stochastic is True
    # Not every one of 5 distinct seeds sampled the exact same winning chunk.
    assert len(set(labels_by_seed.values())) > 1, (
        f"all seeds produced the same winner: {labels_by_seed!r}")


def test_arm_never_exceeds_declared_call_budget(tmp_path):
    """The evaluator's own FreezeError guard must never need to fire: the arm
    stops sampling at N == budget.max_calls on its own. A 4th manual call
    proves the cap was exactly 3, not generously under-used."""
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_1", max_calls=3)

    outcome = arm.run(task, budget, evaluator, seed=3)

    assert outcome.error is None
    assert evaluator.calls == 3
    with pytest.raises(FreezeError):
        evaluator.score("anything", task)


def test_ordinary_failure_returns_error_outcome_not_raise(tmp_path):
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    task = _task(str(empty_repo))
    budget = ArmBudget(max_calls=3)
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_0", max_calls=budget.max_calls)

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is not None
    assert outcome.success is None


def test_default_n_used_and_recorded_when_budget_uncapped(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget()  # max_calls=None: not capped for this comparison
    arm = BestOfNArm()
    evaluator = _marker_evaluator("MARK_0", max_calls=None)

    outcome = arm.run(task, budget, evaluator, seed=5)

    assert outcome.error is None
    assert outcome.notes["n_default_used"] is True
    # N_CHUNKS (6) < DEFAULT_N_WHEN_UNCAPPED (8), so the pool caps it.
    assert outcome.notes["n_sampled"] == N_CHUNKS
    assert evaluator.calls == N_CHUNKS
