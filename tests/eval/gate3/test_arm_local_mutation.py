"""Acceptance test C4 (docs/work-packets/G3-BASE-01_FROZEN_BASELINE_HARNESS.md
§5c): the simple local mutation baseline actually hill-climbs, respects its
budget, is deterministic under a fixed seed, and fails the way the protocol
requires (``ArmOutcome(error=...)``, never a raise).

Offline, deterministic, no network, no model calls.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.arms.local_mutation import LocalMutationArm
from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial

GOOD_MARKERS = ("GOOD_ALPHA", "GOOD_BETA", "GOOD_GAMMA", "GOOD_DELTA", "GOOD_EPSILON")
BAD_MARKERS = ("BAD_ALPHA", "BAD_BETA", "BAD_GAMMA", "BAD_DELTA", "BAD_EPSILON")


def _write_repo(tmp_path, good=GOOD_MARKERS, bad=BAD_MARKERS):
    """One tiny python function per marker -- each becomes one retrieval unit
    under ``_repo_chunks`` (function-level extraction), giving the arm a
    concrete, non-trivial chunk universe to search over."""
    for i, marker in enumerate(good):
        (tmp_path / f"good_{i}.py").write_text(
            f"def good_{i}():\n    return {marker!r}\n", encoding="utf-8")
    for i, marker in enumerate(bad):
        (tmp_path / f"bad_{i}.py").write_text(
            f"def bad_{i}():\n    return {marker!r}\n", encoding="utf-8")
    return tmp_path


def _linear_scorer(good=GOOD_MARKERS, bad=BAD_MARKERS):
    """+1 per good marker present, -1 per bad marker present. Perfectly
    separable (no interaction between markers), so the global optimum
    (all-good, no-bad) is also the ONLY local optimum reachable by single-flip
    hill climbing: every flip that adds a good marker or removes a bad one is
    a strict improvement, and no flip can look like an improvement without
    actually being one. This is the "scorer with a known local optimum" the
    acceptance matrix asks for, and its optimum is unambiguous: len(good)."""
    def score(candidate: str, task: Task) -> float:
        return float(sum(1 for m in good if m in candidate)
                      - sum(1 for m in bad if m in candidate))
    return score


def _make_task(repo_root) -> Task:
    return Task(task_id="t1", repo_root=str(repo_root),
                question="irrelevant to this arm", target="irrelevant")


def test_produces_trial_result_via_run_trial(tmp_path):
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=20)
    evaluator = SealedEvaluator("linear", _linear_scorer())
    arm = LocalMutationArm()

    result = run_trial(arm, task, budget, evaluator, seed=1)

    assert result.arm == "local_mutation"
    assert result.measured
    assert result.error is None
    assert result.success is True
    assert result.score is not None


def test_monotone_improvement_across_iterations(tmp_path):
    """Hill-climbing means the kept candidate's score never decreases. Read
    the trace back from ArmOutcome.notes rather than instrumenting the arm
    from outside, since the runner does not expose per-iteration state."""
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=30)
    evaluator = SealedEvaluator("linear", _linear_scorer())
    arm = LocalMutationArm()

    outcome = arm.run(task, budget, evaluator, seed=7)

    history = outcome.notes["score_history"]
    assert len(history) >= 2
    for earlier, later in zip(history, history[1:]):
        assert later >= earlier, f"score decreased: {history}"


def test_respects_max_calls(tmp_path):
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    max_calls = 4
    budget = ArmBudget(max_calls=max_calls)
    evaluator = SealedEvaluator("linear", _linear_scorer())
    arm = LocalMutationArm()

    result = run_trial(arm, task, budget, evaluator, seed=3)

    assert result.calls <= max_calls
    assert result.budget_exceeded is False


def test_same_seed_is_identical(tmp_path):
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=15)
    arm = LocalMutationArm()

    out_a = arm.run(task, budget, SealedEvaluator("linear", _linear_scorer()), seed=42)
    out_b = arm.run(task, budget, SealedEvaluator("linear", _linear_scorer()), seed=42)

    assert out_a.candidate == out_b.candidate
    assert out_a.score == out_b.score
    assert out_a.notes["score_history"] == out_b.notes["score_history"]


def test_different_seeds_differ(tmp_path):
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    # A tight budget keeps the result dominated by the seed-chosen starting
    # subset (10 chunks -> 1024 equally likely starts) rather than letting
    # both runs fully converge to the shared global optimum, which would make
    # two different seeds land on the identical best candidate by design, not
    # by coincidence.
    budget = ArmBudget(max_calls=2)
    arm = LocalMutationArm()

    out_1 = arm.run(task, budget, SealedEvaluator("linear", _linear_scorer()), seed=1)
    out_2 = arm.run(task, budget, SealedEvaluator("linear", _linear_scorer()), seed=2)

    assert (out_1.candidate, out_1.score) != (out_2.candidate, out_2.score)


def test_climbs_to_the_known_local_optimum(tmp_path):
    """Generous budget: the arm must actually reach the (unique, by
    construction) global/local optimum of all-good-no-bad, worth
    len(GOOD_MARKERS)."""
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=400)
    evaluator = SealedEvaluator("linear", _linear_scorer())
    arm = LocalMutationArm()

    outcome = arm.run(task, budget, evaluator, seed=11)

    assert outcome.score == pytest.approx(float(len(GOOD_MARKERS)))
    for marker in GOOD_MARKERS:
        assert marker in outcome.candidate
    for marker in BAD_MARKERS:
        assert marker not in outcome.candidate


def test_errored_run_has_no_success_or_score(tmp_path):
    _write_repo(tmp_path)
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=10)

    def _explode(candidate: str, task: Task) -> float:
        raise RuntimeError("scorer is broken on purpose")

    evaluator = SealedEvaluator("broken", _explode)
    arm = LocalMutationArm()

    outcome = arm.run(task, budget, evaluator, seed=1)
    assert outcome.error is not None
    assert outcome.success is None
    assert outcome.score is None

    result = run_trial(arm, task, budget, evaluator, seed=1)
    assert result.error is not None
    assert result.success is None
    assert result.score is None
