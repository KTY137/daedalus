"""Acceptance tests for baseline C11 -- the transparent AlphaEvolve-like proxy.

Packet G3-BASE-01. Fast, offline, deterministic given a seed. No model calls,
no network. See ``daedalus/eval/gate3/arms/alphaevolve_proxy.py`` for the
arm's own docstring and ``PROXY_DECLARATION``.
"""
from __future__ import annotations

import socket
import urllib.request

import pytest

from daedalus.eval.gate3.arms.alphaevolve_proxy import (
    PROXY_DECLARATION,
    AlphaEvolveProxyArm,
)
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError, TrialResult
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial

GOOD_WORDS = {"alpha", "beta", "gamma"}


def _scorer(candidate: str, task: Task) -> float:
    """Deterministic, offline scorer: fraction of tokens that are 'good'.

    Rewards candidates that concentrate on {alpha, beta, gamma}, which gives
    the evolutionary loop something real to climb (mutation/crossover can
    both increase and decrease this), while remaining a pure function of
    (candidate, task) -- no I/O, no randomness, no reference to gold labels
    stored anywhere but this closure.
    """
    words = candidate.split()
    if not words:
        return 0.0
    return sum(1 for w in words if w in GOOD_WORDS) / len(words)


def _raising_scorer(candidate: str, task: Task) -> float:
    raise ValueError("scorer is broken (simulated ordinary failure)")


def _make_task(tmp_path) -> Task:
    return Task(
        task_id="g3-base-01-c11-t1",
        repo_root=str(tmp_path),
        question="alpha beta gamma delta epsilon zeta eta theta iota kappa",
        target="alpha beta gamma",
        label_plane="code",
    )


def _make_evaluator(scorer=_scorer, max_calls: int | None = None) -> SealedEvaluator:
    return SealedEvaluator("c11-test-evaluator", scorer, max_calls=max_calls)


def _generous_budget() -> ArmBudget:
    return ArmBudget(max_calls=200, max_wall_seconds=30.0)


# --------------------------------------------------------------------------- #
# transparency (the packet's headline requirement)                           #
# --------------------------------------------------------------------------- #
def test_arm_alphaevolve_proxy_is_transparent():
    assert isinstance(PROXY_DECLARATION, dict)
    required_keys = {"mechanisms_reproduced", "mechanisms_not_reproduced", "may_not_claim"}
    assert required_keys <= set(PROXY_DECLARATION)

    for key in required_keys:
        value = PROXY_DECLARATION[key]
        assert isinstance(value, tuple), f"{key} must be a tuple of strings"
        assert len(value) > 0, f"{key} must be non-empty"
        assert all(isinstance(item, str) and item.strip() for item in value), (
            f"{key} must contain only non-empty strings"
        )

    claim_text = " ".join(PROXY_DECLARATION["may_not_claim"])
    assert "beats AlphaEvolve" in claim_text, (
        "the 'may not claim' entry must explicitly name the forbidden "
        "'beats AlphaEvolve' claim (plan §11 Gate 5)"
    )


# --------------------------------------------------------------------------- #
# basic contract                                                              #
# --------------------------------------------------------------------------- #
def test_arm_name_and_stochastic_flag():
    arm = AlphaEvolveProxyArm()
    assert arm.name == "alphaevolve_proxy"
    assert arm.stochastic is True


def test_produces_a_trial_result_via_run_trial(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()
    evaluator = _make_evaluator()

    result = run_trial(arm, task, budget, evaluator, seed=1)

    assert isinstance(result, TrialResult)
    assert result.arm == "alphaevolve_proxy"
    assert result.task_id == task.task_id
    assert result.error is None
    assert result.success is not None
    assert result.score is not None
    assert result.wall_seconds >= 0.0


# --------------------------------------------------------------------------- #
# elitism / monotone best-so-far                                             #
# --------------------------------------------------------------------------- #
def test_elitism_best_so_far_is_monotone_non_decreasing(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()
    evaluator = _make_evaluator()

    outcome = arm.run(task, budget, evaluator, seed=7)

    assert outcome.error is None
    history = outcome.notes["best_so_far_history"]
    assert len(history) >= 2, "budget should allow multiple generations"
    for earlier, later in zip(history, history[1:]):
        assert later >= earlier, f"best-so-far regressed: {earlier} -> {later}"
    assert outcome.notes["generations_run"] >= 1
    assert 0.0 <= outcome.notes["final_population_diversity"] <= 1.0


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_same_seed_is_identical(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()

    outcome_a = arm.run(task, budget, _make_evaluator(), seed=42)
    outcome_b = arm.run(task, budget, _make_evaluator(), seed=42)

    assert outcome_a.candidate == outcome_b.candidate
    assert outcome_a.score == outcome_b.score
    assert outcome_a.notes["best_so_far_history"] == outcome_b.notes["best_so_far_history"]


def test_different_seeds_differ(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()

    outcomes = [arm.run(task, budget, _make_evaluator(), seed=s) for s in (1, 2, 3, 4, 5)]
    candidates = {o.candidate for o in outcomes}
    histories = {o.notes["best_so_far_history"] for o in outcomes}

    assert len(candidates) > 1 or len(histories) > 1, (
        "five different seeds produced an identical trajectory -- "
        "randomness is not actually seed-dependent"
    )


# --------------------------------------------------------------------------- #
# budget                                                                      #
# --------------------------------------------------------------------------- #
def test_respects_max_calls(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = ArmBudget(max_calls=5)
    evaluator = _make_evaluator(max_calls=5)

    result = run_trial(arm, task, budget, evaluator, seed=3)

    assert result.calls <= 5
    assert evaluator.calls <= 5


def test_budget_split_is_never_called_and_stays_refused(tmp_path):
    # Not a call the arm makes (R1) -- pin the contract's own refusal so a
    # future edit that starts calling split() fails loudly here too.
    budget = ArmBudget(max_calls=10)
    with pytest.raises(FreezeError):
        budget.split(2)


# --------------------------------------------------------------------------- #
# no network by default                                                       #
# --------------------------------------------------------------------------- #
def test_no_network_call_by_default(tmp_path, monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("alphaevolve_proxy made a network call by default")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)

    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()
    evaluator = _make_evaluator()

    outcome = arm.run(task, budget, evaluator, seed=9)

    assert outcome.error is None


# --------------------------------------------------------------------------- #
# ordinary failure                                                            #
# --------------------------------------------------------------------------- #
def test_errored_run_has_error_and_no_success_or_score(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()
    evaluator = _make_evaluator(scorer=_raising_scorer)

    result = run_trial(arm, task, budget, evaluator, seed=11)

    assert result.error is not None
    assert "scorer is broken" in result.error
    assert result.success is None
    assert result.score is None


def test_evaluator_freeze_violation_is_never_swallowed(tmp_path):
    arm = AlphaEvolveProxyArm()
    task = _make_task(tmp_path)
    budget = _generous_budget()
    # max_calls=0 is refused by ArmBudget itself; use the evaluator's own
    # call ceiling instead so the FIRST score() call already raises FreezeError.
    evaluator = _make_evaluator(max_calls=0)

    with pytest.raises(FreezeError):
        arm.run(task, budget, evaluator, seed=13)
