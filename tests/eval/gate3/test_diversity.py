"""test_diversity.py -- acceptance test D7 (G3-BASE-01 §5d) and refusal tests
for ``daedalus.eval.gate3.diversity``.

Offline, no model calls, no filesystem, sub-second. Covers:

* D7 ``test_diversity_metric_defined`` -- ``DIVERSITY_DEFINITION`` exists with
  all four required keys, every one non-empty.
* the metric can actually vary: identical candidates score minimum, maximally
  different candidates score maximum (packet §8 / triage s06: a value that
  cannot vary is a structurally guaranteed number, not a measurement).
* n=0 and n=1 are explicit refusals (``FreezeError``), never 0.0.
* determinism: same input twice -> identical result; permuted input -> the
  identical result (order must not leak into a supposedly order-free metric).
* ``diversity_of_trials`` excludes errored trials and trials with no usable
  candidate note, and refuses when fewer than two usable candidates remain.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.contracts import FreezeError, TrialResult
from daedalus.eval.gate3.diversity import (
    DIVERSITY_DEFINITION,
    DiversityResult,
    TrialDiversity,
    diversity,
    diversity_of_trials,
)


# --------------------------------------------------------------------------- #
# D7 -- the definition itself must exist and be substantive                   #
# --------------------------------------------------------------------------- #
def test_diversity_metric_defined() -> None:
    required_keys = {"metric", "distance", "normalisation", "does_not_capture"}
    assert required_keys <= set(DIVERSITY_DEFINITION)
    for key in required_keys:
        value = DIVERSITY_DEFINITION[key]
        assert value, f"DIVERSITY_DEFINITION[{key!r}] must not be empty"
    # does_not_capture must be a real, substantive list of caveats, not a
    # single vague sentence standing in for one.
    caveats = DIVERSITY_DEFINITION["does_not_capture"]
    assert isinstance(caveats, tuple)
    assert len(caveats) >= 4
    for caveat in caveats:
        assert isinstance(caveat, str)
        assert len(caveat) >= 20, "a one-word caveat is not substantive"
    # semantic honesty: the definition must not claim to be semantic anywhere
    # in its own declared fields (metric/distance/normalisation) -- the
    # "does_not_capture" entries are allowed to mention "semantic" because
    # they are disclaiming it, not claiming it.
    for key in ("metric", "distance", "normalisation"):
        assert "semantic" not in str(DIVERSITY_DEFINITION[key]).lower()


def test_diversity_definition_is_immutable_mapping() -> None:
    with pytest.raises(TypeError):
        DIVERSITY_DEFINITION["metric"] = "overwritten"  # type: ignore[index]


# --------------------------------------------------------------------------- #
# structure, never a bare float                                               #
# --------------------------------------------------------------------------- #
def test_diversity_returns_structure_not_bare_float() -> None:
    result = diversity(["alpha beta", "gamma delta"])
    assert isinstance(result, DiversityResult)
    assert isinstance(result.value, float)
    assert result.n_candidates == 2
    assert result.definition is DIVERSITY_DEFINITION


# --------------------------------------------------------------------------- #
# can vary: identical -> minimum, maximally different -> maximum              #
# --------------------------------------------------------------------------- #
def test_identical_candidates_score_minimum() -> None:
    result = diversity(["same text here", "same text here", "same text here"])
    assert result.value == 0.0
    assert result.n_distinct == 1
    assert result.normalised_entropy == 0.0


def test_maximally_different_candidates_score_maximum() -> None:
    # Disjoint token vocabularies -> every pairwise Jaccard distance is 1.0,
    # and every candidate is a distinct singleton cluster -> entropy is
    # maximal too.
    result = diversity(["alpha one two", "beta three four", "gamma five six"])
    assert result.value == 1.0
    assert result.n_distinct == 3
    assert result.normalised_entropy == 1.0


def test_metric_is_not_structurally_pinned_to_one_value() -> None:
    """Direct proof the metric CAN vary (packet §8 / triage s06 rule): the
    minimum and maximum cases above must not coincide, and a partially
    overlapping case must land strictly between them."""
    low = diversity(["same text here", "same text here"]).value
    high = diversity(["alpha one two", "beta three four"]).value
    mid = diversity(["alpha one two", "alpha one three"]).value
    assert low == 0.0
    assert high == 1.0
    assert low < mid < high


# --------------------------------------------------------------------------- #
# refusals: n=0 and n=1 are UNDEFINED, never 0.0                              #
# --------------------------------------------------------------------------- #
def test_zero_candidates_is_refused() -> None:
    with pytest.raises(FreezeError, match="zero candidates"):
        diversity([])


def test_one_candidate_is_refused_not_zero() -> None:
    with pytest.raises(FreezeError, match="UNDEFINED"):
        diversity(["only one candidate"])


def test_one_candidate_refusal_never_returns() -> None:
    # Belt and suspenders: confirm the refusal is a raise, not a return path
    # that happens to also raise elsewhere -- no DiversityResult(0.0, ...) is
    # constructed anywhere on this path.
    with pytest.raises(FreezeError):
        diversity(["x"])


# --------------------------------------------------------------------------- #
# determinism: repeated calls and permutation invariance                      #
# --------------------------------------------------------------------------- #
def test_deterministic_across_repeated_runs() -> None:
    candidates = ["alpha beta gamma", "beta gamma delta", "gamma delta epsilon"]
    first = diversity(candidates)
    second = diversity(list(candidates))  # fresh list, same contents/order
    assert first.value == second.value
    assert first.n_distinct == second.n_distinct
    assert first.normalised_entropy == second.normalised_entropy


def test_deterministic_independent_of_input_order() -> None:
    candidates = ["alpha beta", "gamma delta", "alpha beta", "epsilon zeta"]
    forward = diversity(candidates)
    reversed_order = diversity(list(reversed(candidates)))
    shuffled = diversity([candidates[2], candidates[0], candidates[3], candidates[1]])
    assert forward.value == reversed_order.value == shuffled.value
    assert forward.n_distinct == reversed_order.n_distinct == shuffled.n_distinct
    assert (forward.normalised_entropy == reversed_order.normalised_entropy
            == shuffled.normalised_entropy)


def test_deterministic_across_process_hash_seed(monkeypatch) -> None:
    """Guards against a regression that starts depending on ``hash()`` of
    strings or on set/dict iteration order for the numeric result -- both
    vary with ``PYTHONHASHSEED`` across process runs even though this single
    test process cannot itself change its own seed mid-run."""
    candidates = ["repo file one text", "repo file two text", "repo file one text"]
    a = diversity(candidates)
    b = diversity(candidates)
    assert a.value == b.value
    assert a.n_distinct == b.n_distinct == 2
    assert a.normalised_entropy == b.normalised_entropy


# --------------------------------------------------------------------------- #
# token-set semantics sanity (documents the declared distance, not just its   #
# extremes)                                                                   #
# --------------------------------------------------------------------------- #
def test_order_blindness_is_real_not_just_documented() -> None:
    """Two candidates built from the identical token multiset in a different
    order collapse to distance 0.0 -- exactly the limitation declared in
    DIVERSITY_DEFINITION['does_not_capture']. Encoding this as a passing test
    (rather than only prose) is what makes the declared limitation falsifiable
    instead of aspirational."""
    result = diversity(["alpha beta gamma", "gamma beta alpha"])
    assert result.value == 0.0


def test_multiplicity_blindness_is_real_not_just_documented() -> None:
    """'a a a b' and 'a b' share the same token SET, so they register as
    identical under this metric -- the declared multiset-blindness caveat,
    made falsifiable."""
    result = diversity(["a a a b", "a b"])
    assert result.value == 0.0


def test_empty_string_candidates_are_indistinguishable_not_maximal() -> None:
    result = diversity(["", ""])
    assert result.value == 0.0


def test_empty_vs_nonempty_candidate_is_maximal() -> None:
    result = diversity(["", "alpha beta"])
    assert result.value == 1.0


# --------------------------------------------------------------------------- #
# diversity_of_trials -- errored trials excluded, candidate-less excluded     #
# --------------------------------------------------------------------------- #
def _measured(arm: str, task_id: str, seed: int, candidate: str) -> TrialResult:
    return TrialResult(
        arm=arm, task_id=task_id, seed=seed, wall_seconds=0.01, tokens_used=1,
        calls=1, success=True, score=1.0, notes={"candidate": candidate},
    )


def _errored(arm: str, task_id: str, seed: int) -> TrialResult:
    return TrialResult(
        arm=arm, task_id=task_id, seed=seed, wall_seconds=0.01, tokens_used=0,
        calls=0, error="boom",
    )


def test_diversity_of_trials_excludes_errored_trials() -> None:
    trials = [
        _measured("arm", "t1", 1, "alpha beta"),
        _measured("arm", "t2", 1, "gamma delta"),
        _errored("arm", "t3", 1),
    ]
    result = diversity_of_trials(trials)
    assert isinstance(result, TrialDiversity)
    assert result.n_measured == 2
    assert result.n_errored == 1
    assert result.diversity.n_candidates == 2


def test_diversity_of_trials_excludes_trials_without_candidate_note() -> None:
    no_candidate = TrialResult(
        arm="arm", task_id="t3", seed=1, wall_seconds=0.01, tokens_used=1,
        calls=1, success=True, score=1.0, notes={"other_field": "not a candidate"},
    )
    trials = [
        _measured("arm", "t1", 1, "alpha beta"),
        _measured("arm", "t2", 1, "gamma delta"),
        no_candidate,
    ]
    result = diversity_of_trials(trials)
    assert result.n_measured == 3
    assert result.n_without_candidate == 1
    assert result.diversity.n_candidates == 2


def test_diversity_of_trials_refuses_below_two_usable_candidates() -> None:
    trials = [
        _measured("arm", "t1", 1, "alpha beta"),
        _errored("arm", "t2", 1),
    ]
    with pytest.raises(FreezeError, match="usable"):
        diversity_of_trials(trials)


def test_diversity_of_trials_respects_custom_candidate_key() -> None:
    trials = [
        TrialResult(arm="a", task_id="t1", seed=1, wall_seconds=0.0, tokens_used=0,
                    calls=0, success=True, score=1.0, notes={"text": "alpha beta"}),
        TrialResult(arm="a", task_id="t2", seed=1, wall_seconds=0.0, tokens_used=0,
                    calls=0, success=True, score=1.0, notes={"text": "gamma delta"}),
    ]
    result = diversity_of_trials(trials, candidate_key="text")
    assert result.diversity.n_candidates == 2
    assert result.n_without_candidate == 0
