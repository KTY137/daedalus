"""test_arm_map_elites.py -- acceptance test C10 for packet G3-BASE-01.

Covers: `test_arm_map_elites_archive` (packet §5c) plus the elitism, coverage,
determinism, budget and failure-semantics obligations from the task brief.
Fast, offline, deterministic given a seed -- no network, no model calls.
"""
from __future__ import annotations

from daedalus.eval.gate3.arms.map_elites import (
    CELL_COUNT,
    Archive,
    MapElitesArm,
)
from daedalus.eval.gate3.contracts import ArmBudget, TrialResult
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial

QUESTION = (
    "rename Event.voltage to bias_voltage across the python markdown and csv "
    "sources without breaking the schema or the existing links"
)
TARGET = "bias_voltage"


def _task(tmp_path, task_id: str = "map-elites-task") -> Task:
    return Task(task_id=task_id, repo_root=str(tmp_path), question=QUESTION, target=TARGET)


def _score_fn(candidate: str, task: Task) -> float:
    """Deterministic, evaluator-side-only score: rewards lexical richness and
    length so mutation has a gradient to climb, without ever reading the
    candidate's archive cell (the descriptor and the score are independent,
    per the module's own design note)."""
    words = candidate.split()
    return float(len(set(words))) + 0.01 * len(candidate)


# --------------------------------------------------------------------------- #
# C10 -- the acceptance test named by the packet                              #
# --------------------------------------------------------------------------- #
def test_arm_map_elites_archive(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()
    assert arm.name == "map_elites"
    assert arm.stochastic is True

    budget = ArmBudget(max_calls=80)
    result = run_trial(arm, task, budget, SealedEvaluator("archive", _score_fn), seed=11)

    assert isinstance(result, TrialResult)
    assert result.error is None
    assert result.success is True
    assert result.notes["cell_count"] == CELL_COUNT
    assert result.notes["coverage"] == result.notes["cells_filled"] / CELL_COUNT
    assert result.notes["coverage"] > 0.0
    assert "behaviour_descriptor" in result.notes


# --------------------------------------------------------------------------- #
# elitism -- asserted directly against Archive, independent of any full run   #
# --------------------------------------------------------------------------- #
def test_elitism_cell_never_replaced_by_worse_candidate():
    archive = Archive()
    cell = (0, 0)

    assert archive.try_insert(cell, "first", 5.0) is True
    assert archive.get(cell).candidate == "first"

    # worse challenger: refused, incumbent unchanged
    assert archive.try_insert(cell, "worse", 3.0) is False
    assert archive.get(cell).candidate == "first"
    assert archive.get(cell).score == 5.0

    # tied challenger: also refused (ties keep the incumbent)
    assert archive.try_insert(cell, "tied", 5.0) is False
    assert archive.get(cell).candidate == "first"

    # strictly better challenger: accepted
    assert archive.try_insert(cell, "better", 9.0) is True
    assert archive.get(cell).candidate == "better"
    assert archive.get(cell).score == 9.0


# --------------------------------------------------------------------------- #
# coverage is measured, not constant                                         #
# --------------------------------------------------------------------------- #
def test_coverage_is_computed_from_archive_contents_not_hardcoded():
    sparse = Archive()
    sparse.try_insert((0, 0), "a", 1.0)
    sparse.try_insert((1, 1), "b", 1.0)
    assert sparse.coverage == 2 / CELL_COUNT

    denser = Archive()
    for i in range(10):
        denser.try_insert((i % 8, i // 8), f"c{i}", float(i))
    assert denser.coverage == 10 / CELL_COUNT

    # two different fixtures -> two different measured coverage values
    assert sparse.coverage != denser.coverage


def test_full_run_coverage_differs_between_budgets_and_matches_its_own_count(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()

    small = arm.run(task, ArmBudget(max_calls=5), SealedEvaluator("small", _score_fn), seed=7)
    large = arm.run(task, ArmBudget(max_calls=120), SealedEvaluator("large", _score_fn), seed=7)

    assert small.error is None and large.error is None
    # coverage is recomputed from the actual archive, so it must self-consist
    assert small.notes["coverage"] == small.notes["cells_filled"] / CELL_COUNT
    assert large.notes["coverage"] == large.notes["cells_filled"] / CELL_COUNT
    assert small.notes["coverage"] != large.notes["coverage"]


def test_archive_fills_and_coverage_increases_with_budget(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()

    small = arm.run(task, ArmBudget(max_calls=8), SealedEvaluator("s", _score_fn), seed=1)
    large = arm.run(task, ArmBudget(max_calls=150), SealedEvaluator("l", _score_fn), seed=1)

    assert small.notes["coverage"] > 0.0
    assert large.notes["coverage"] > small.notes["coverage"]


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_same_seed_is_reproducible_different_seed_differs(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()
    budget = ArmBudget(max_calls=60)

    r1 = arm.run(task, budget, SealedEvaluator("e1", _score_fn), seed=42)
    r2 = arm.run(task, budget, SealedEvaluator("e2", _score_fn), seed=42)
    assert r1.candidate == r2.candidate
    assert r1.score == r2.score
    assert r1.notes["coverage"] == r2.notes["coverage"]
    assert r1.notes["cells_filled"] == r2.notes["cells_filled"]

    r3 = arm.run(task, budget, SealedEvaluator("e3", _score_fn), seed=999)
    assert (r3.candidate, r3.notes["coverage"]) != (r1.candidate, r1.notes["coverage"])


# --------------------------------------------------------------------------- #
# budget                                                                      #
# --------------------------------------------------------------------------- #
def test_respects_max_calls(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()
    budget = ArmBudget(max_calls=6)
    evaluator = SealedEvaluator("cap", _score_fn)

    result = run_trial(arm, task, budget, evaluator, seed=3)

    assert result.error is None
    assert result.calls <= 6
    assert result.budget_exceeded is False


# --------------------------------------------------------------------------- #
# failure semantics                                                          #
# --------------------------------------------------------------------------- #
def test_errored_run_has_no_score_or_success(tmp_path):
    def _boom(candidate: str, task: Task) -> float:
        raise RuntimeError("boom")

    task = _task(tmp_path)
    arm = MapElitesArm()
    budget = ArmBudget(max_calls=5)
    evaluator = SealedEvaluator("boom", _boom)

    result = run_trial(arm, task, budget, evaluator, seed=1)

    assert result.error is not None
    assert result.success is None
    assert result.score is None


def test_produces_trial_result_via_run_trial(tmp_path):
    task = _task(tmp_path)
    arm = MapElitesArm()
    budget = ArmBudget(max_calls=20)
    evaluator = SealedEvaluator("basic", _score_fn)

    result = run_trial(arm, task, budget, evaluator, seed=5)

    assert isinstance(result, TrialResult)
    assert result.arm == "map_elites"
    assert result.error is None
    assert result.success is True
