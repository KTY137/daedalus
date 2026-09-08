"""test_measures.py -- acceptance tests D1-D5 (G3-BASE-01 §5d) for
``daedalus.eval.gate3.measures``: success rate, best-so-far AUC, wall time,
tokens, compute. The other four measures (variance, diversity, regressions,
human intervention) belong to sibling modules and are not tested here.

Offline, no model calls, no filesystem beyond ``tmp_path`` where a fixture
happens to need one -- these tests build ``TrialResult`` fixtures directly,
per the packet instruction, rather than running a real arm end to end.
"""
from __future__ import annotations

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.contracts import FreezeError, TrialResult
from daedalus.eval.gate3.measures import (
    ComputeProxy,
    SuccessRate,
    TokenUsage,
    WallTime,
    best_so_far_auc,
    best_so_far_curve,
    compute,
    success_rate,
    token_usage,
    wall_time,
)


def _ok(arm: str, task_id: str, seed: int, *, wall_seconds: float = 1.0,
        tokens_used: int = 10, calls: int = 1, success: bool = True,
        score: float | None = None) -> TrialResult:
    return TrialResult(arm=arm, task_id=task_id, seed=seed,
                        wall_seconds=wall_seconds, tokens_used=tokens_used,
                        calls=calls, success=success, score=score)


def _err(arm: str, task_id: str, seed: int, *, wall_seconds: float = 1.0,
         tokens_used: int = 0, calls: int = 0,
         error: str = "boom") -> TrialResult:
    return TrialResult(arm=arm, task_id=task_id, seed=seed,
                        wall_seconds=wall_seconds, tokens_used=tokens_used,
                        calls=calls, error=error)


# --------------------------------------------------------------------------- #
# D1 -- success rate                                                          #
# --------------------------------------------------------------------------- #
def test_measure_success_rate():
    """Plain case: 2 of 3 measured trials succeed, denominator is reported."""
    trials = [
        _ok("arm", "t1", 1, success=True),
        _ok("arm", "t2", 2, success=False),
        _ok("arm", "t3", 3, success=True),
    ]

    result = success_rate(trials)

    assert isinstance(result, SuccessRate)
    assert result.n_measured == 3
    assert result.n_errored == 0
    assert result.n_total == 3
    assert result.n_success == 2
    assert result.rate == pytest.approx(2 / 3)


def test_measure_success_rate_excludes_errored_from_numerator_and_denominator():
    """THE DENOMINATOR IS THE WHOLE POINT (packet §D1). 1 success, 1 failure,
    2 errors: a wrongly-inflated implementation that counted errors as
    measured-and-failed would report 1/4 == 0.25; a wrongly-inflated
    implementation that silently dropped the errors from the denominator
    while still not counting them as failures would coincidentally also
    report 1/2 == 0.5 here IF it happened to count them right, so this test
    also pins the exact n_measured/n_errored split, not just the rate, so a
    denominator bug cannot hide behind a rate that looks plausible."""
    trials = [
        _ok("arm", "t1", 1, success=True),
        _ok("arm", "t2", 2, success=False),
        _err("arm", "t3", 3),
        _err("arm", "t4", 4),
    ]

    result = success_rate(trials)

    assert result.n_measured == 2
    assert result.n_errored == 2
    assert result.n_total == 4
    assert result.n_success == 1
    assert result.rate == pytest.approx(0.5)


def test_measure_success_rate_all_errored_is_absent_not_zero():
    trials = [_err("arm", "t1", 1), _err("arm", "t2", 2)]

    result = success_rate(trials)

    assert result.n_measured == 0
    assert result.n_errored == 2
    assert result.rate is None, (
        "a rate with zero measured trials must be None (absent), never a "
        "bare 0.0 that looks like 'measured and failed everything'")


def test_measure_success_rate_refuses_empty_input():
    with pytest.raises(FreezeError):
        success_rate([])


# --------------------------------------------------------------------------- #
# D2 -- best-so-far AUC / curve                                               #
# --------------------------------------------------------------------------- #
def test_best_so_far_curve_is_monotone_and_correct():
    trials = [
        _ok("arm", "t1", 1, score=0.2),
        _ok("arm", "t2", 2, score=0.9),
        _ok("arm", "t3", 3, score=0.5),
        _ok("arm", "t4", 4, score=0.9),
        _ok("arm", "t5", 5, score=1.0),
    ]

    curve = best_so_far_curve(trials)

    assert curve == [0.2, 0.9, 0.9, 0.9, 1.0]
    for a, b in zip(curve, curve[1:]):
        assert b >= a, "best-so-far curve regressed -- not monotone"


def test_best_so_far_auc_is_monotone():
    """Test D2. A curve built from a non-monotone score sequence must still
    yield a monotone best-so-far curve, and the AUC must fall strictly
    between the first and last curve values for a genuinely improving run."""
    trials = [
        _ok("arm", "t1", 1, score=0.1),
        _ok("arm", "t2", 2, score=0.3),
        _ok("arm", "t3", 3, score=0.1),
        _ok("arm", "t4", 4, score=0.8),
        _ok("arm", "t5", 5, score=0.2),
    ]

    curve = best_so_far_curve(trials)
    for a, b in zip(curve, curve[1:]):
        assert b >= a

    auc = best_so_far_auc(trials)
    assert auc is not None
    assert curve[0] <= auc <= curve[-1]


def test_best_so_far_auc_normalises_across_different_lengths():
    """A flat curve at the same value must yield (approximately) the same
    AUC whether it has 2 points or 20 -- the whole point of rescaling the
    x-axis onto [0, 1] rather than leaving it in raw trial-count units."""
    short = [_ok("arm", f"t{i}", i, score=0.7) for i in range(2)]
    long_ = [_ok("arm", f"t{i}", i, score=0.7) for i in range(20)]

    assert best_so_far_auc(short) == pytest.approx(0.7)
    assert best_so_far_auc(long_) == pytest.approx(0.7)


def test_best_so_far_auc_single_trial():
    trials = [_ok("arm", "t1", 1, score=0.42)]
    assert best_so_far_auc(trials) == pytest.approx(0.42)


def test_best_so_far_auc_all_errored_is_absent():
    trials = [_err("arm", "t1", 1), _err("arm", "t2", 2)]
    assert best_so_far_curve(trials) == []
    assert best_so_far_auc(trials) is None


def test_best_so_far_uses_success_flag_when_score_is_absent():
    trials = [
        _ok("arm", "t1", 1, success=False, score=None),
        _ok("arm", "t2", 2, success=True, score=None),
    ]
    assert best_so_far_curve(trials) == [0.0, 1.0]


# --------------------------------------------------------------------------- #
# D3 -- wall time excludes setup                                              #
# --------------------------------------------------------------------------- #
def test_wall_time_excludes_setup():
    """Mirrors ``protocols.run_trial``'s own contract: the clock starts
    immediately before ``arm.run`` and stops immediately after -- index
    building and other per-repo setup are the CALLER's cost, never charged to
    the arm. This test proves ``wall_time`` does not add any such setup cost
    of its own: it only ever sums the ``wall_seconds`` already recorded on
    each ``TrialResult``, so a large out-of-band setup time (simulated here
    as a value that is NOT present on any TrialResult at all) cannot leak in."""
    trials = [
        _ok("arm", "t1", 1, wall_seconds=1.5),
        _ok("arm", "t2", 2, wall_seconds=2.5),
    ]
    setup_time_not_part_of_any_trial = 1000.0  # never passed to wall_time

    result = wall_time(trials)

    assert isinstance(result, WallTime)
    assert result.total_seconds == pytest.approx(4.0)
    assert result.total_seconds < setup_time_not_part_of_any_trial
    assert result.mean_seconds == pytest.approx(2.0)
    assert result.n_trials == 2


def test_wall_time_includes_errored_trials():
    """An errored trial still consumed real wall-clock time inside
    ``arm.run`` before it raised; excluding it would under-report spend."""
    trials = [
        _ok("arm", "t1", 1, wall_seconds=1.0),
        _err("arm", "t2", 2, wall_seconds=3.0),
    ]

    result = wall_time(trials)

    assert result.total_seconds == pytest.approx(4.0)
    assert result.n_trials == 2


def test_wall_time_refuses_empty_input():
    with pytest.raises(FreezeError):
        wall_time([])


# --------------------------------------------------------------------------- #
# D4 -- tokens use the declared tokenizer                                     #
# --------------------------------------------------------------------------- #
def test_tokens_use_declared_tokenizer():
    trials = [
        _ok("arm", "t1", 1, tokens_used=100),
        _ok("arm", "t2", 2, tokens_used=300),
    ]

    result = token_usage(trials, tokenizer="fake-tokenizer-v1")

    assert isinstance(result, TokenUsage)
    assert result.tokenizer == "fake-tokenizer-v1"
    assert result.total_tokens == 400
    assert result.mean_tokens == pytest.approx(200.0)


def test_tokens_default_to_harness_declared_tokenizer():
    """No explicit tokenizer -> falls back to the SAME tokenizer identity
    ``daedalus.eval.harness`` already stamps onto every result row, reused
    rather than re-derived (packet §2)."""
    trials = [_ok("arm", "t1", 1, tokens_used=50)]

    result = token_usage(trials)

    assert result.tokenizer == harness.tokenizer_name()
    assert result.tokenizer  # non-empty


def test_tokens_two_tokenizers_are_not_silently_comparable():
    """Two token_usage results carrying different declared tokenizers must
    never be mistaken for the same unit -- this test pins that the tokenizer
    identity actually changes the recorded field, not just accepted and
    ignored."""
    trials = [_ok("arm", "t1", 1, tokens_used=100)]

    a = token_usage(trials, tokenizer="tok-a")
    b = token_usage(trials, tokenizer="tok-b")

    assert a.tokenizer != b.tokenizer
    assert a.total_tokens == b.total_tokens  # same raw counts, different unit label


def test_token_usage_refuses_empty_tokenizer_label():
    with pytest.raises(FreezeError):
        TokenUsage(total_tokens=1, mean_tokens=1.0, tokenizer="   ", n_trials=1)


def test_token_usage_refuses_empty_input():
    with pytest.raises(FreezeError):
        token_usage([])


# --------------------------------------------------------------------------- #
# D5 -- compute is a labelled proxy, never fabricated FLOPs                   #
# --------------------------------------------------------------------------- #
def test_compute_recorded():
    """Packet §8 expected failure #3: 'expect a declared proxy, explicitly
    labelled, not a fabricated FLOP count.' This test asserts the LABEL is
    present and machine-checkable, not merely documented in a docstring a
    caller might not read."""
    trials = [
        _ok("arm", "t1", 1, calls=2, wall_seconds=1.5),
        _ok("arm", "t2", 2, calls=3, wall_seconds=2.5),
    ]

    result = compute(trials)

    assert isinstance(result, ComputeProxy)
    assert result.is_proxy is True
    assert "proxy" in result.label
    assert "flop" not in result.label.lower()
    assert "NOT FLOPs" in result.note
    assert result.total_evaluator_calls == 5
    assert result.total_wall_seconds == pytest.approx(4.0)
    assert result.proxy_value == pytest.approx(9.0)


def test_compute_includes_errored_trials():
    trials = [
        _ok("arm", "t1", 1, calls=1, wall_seconds=1.0),
        _err("arm", "t2", 2, calls=1, wall_seconds=1.0),
    ]

    result = compute(trials)

    assert result.total_evaluator_calls == 2
    assert result.total_wall_seconds == pytest.approx(2.0)


def test_compute_proxy_cannot_be_constructed_as_non_proxy():
    """The label is not a caller-settable escape hatch: constructing a
    ComputeProxy that claims ``is_proxy=False`` is refused outright."""
    with pytest.raises(FreezeError):
        ComputeProxy(total_evaluator_calls=1, total_wall_seconds=1.0,
                     proxy_value=2.0, is_proxy=False)


def test_compute_refuses_empty_input():
    with pytest.raises(FreezeError):
        compute([])
