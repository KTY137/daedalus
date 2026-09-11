"""Tests for the Gate-3 evaluator-versioning module (packet G3-BASE-01,
freeze obligation #2 / acceptance tests A4 and E1-adjacent).

Deterministic, offline, no network, no model calls.
"""
from __future__ import annotations

import dataclasses
import functools

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.contracts import FreezeError
from daedalus.eval.gate3.evaluator import (
    evaluator_version,
    make_recall_evaluator,
    vacuous_label_guard,
)
from daedalus.eval.gate3.protocols import Task


def _task(task_id: str = "t1") -> Task:
    return Task(task_id=task_id, repo_root="/tmp/does-not-matter",
                question="q", target="mod.py::fn", label_plane="code")


# --------------------------------------------------------------------------- #
# A4 -- code_digest is bound to the scorer's ACTUAL SOURCE                    #
# --------------------------------------------------------------------------- #
def test_evaluator_version_binds_scoring_code_digest() -> None:
    def score_a(candidate: str, task) -> float:
        return 1.0 if "alpha" in candidate else 0.0

    def score_b(candidate: str, task) -> float:
        return 1.0 if "beta" in candidate else 0.0

    ev_a = evaluator_version("gate3-test", "1.0.0", score_a)
    ev_b = evaluator_version("gate3-test", "1.0.0", score_b)
    ev_a_again = evaluator_version("gate3-test", "1.0.0", score_a)

    assert ev_a.code_digest != ev_b.code_digest, (
        "two different scoring functions must not share a code_digest")
    assert ev_a.code_digest == ev_a_again.code_digest, (
        "the SAME function must produce a stable digest across calls")
    assert len(ev_a.code_digest) == 64


def test_editing_scorer_changes_digest_even_when_version_unchanged() -> None:
    """The exact trap this function exists to close: a human edits the scorer
    body and forgets to bump ``version``. The recorded identity must still
    move, because ``version`` alone is not the evaluator's identity."""
    def score_v1(candidate: str, task) -> float:
        return 1.0 if "needle" in candidate else 0.0

    def score_v1_edited(candidate: str, task) -> float:
        return 1.0 if "needle" in candidate.lower() else 0.0

    same_version = "1.0.0"
    ev_before = evaluator_version("gate3-test", same_version, score_v1)
    ev_after = evaluator_version("gate3-test", same_version, score_v1_edited)

    assert ev_before.version == ev_after.version == same_version
    assert ev_before.code_digest != ev_after.code_digest
    assert ev_before.digest != ev_after.digest


# --------------------------------------------------------------------------- #
# A4 -- inspect.getsource failure is refused loudly, never defaulted         #
# --------------------------------------------------------------------------- #
def test_getsource_failure_on_partial_is_refused_loudly() -> None:
    """functools.partial has no retrievable Python source (it is not a
    function, method, class, traceback, frame, or code object) -- the
    realistic 'C-implemented / non-introspectable callable' case."""
    def base(candidate: str, task, marker: str) -> float:
        return 1.0 if marker in candidate else 0.0

    wrapped = functools.partial(base, marker="x")

    with pytest.raises(FreezeError, match="inspect.getsource failed"):
        evaluator_version("gate3-test", "1.0.0", wrapped)


def test_getsource_failure_on_repl_defined_function_is_refused_loudly() -> None:
    """A function compiled from a string (the REPL/exec case) has a
    ``co_filename`` that resolves to no readable source file -- ``inspect.
    getsource`` raises ``OSError``, and that must propagate as a loud
    ``FreezeError``, never a silently substituted placeholder digest."""
    namespace: dict[str, object] = {}
    exec(
        "def _dynamic_score(candidate, task):\n    return 1.0\n",
        namespace,
    )
    dynamic_fn = namespace["_dynamic_score"]

    with pytest.raises(FreezeError, match="inspect.getsource failed"):
        evaluator_version("gate3-test", "1.0.0", dynamic_fn)


# --------------------------------------------------------------------------- #
# E1-adjacent -- the arm-facing Task carries no gold labels                   #
# --------------------------------------------------------------------------- #
def test_task_carries_no_gold_labels() -> None:
    field_names = {f.name for f in dataclasses.fields(Task)}
    forbidden = {"must_include", "labels", "gold", "gold_labels", "answer",
                 "answers"}
    assert not (field_names & forbidden), (
        f"Task must not carry a label field; found {field_names & forbidden} "
        f"in {sorted(field_names)}")
    task = _task()
    assert not hasattr(task, "must_include")
    assert not hasattr(task, "labels")


# --------------------------------------------------------------------------- #
# delegation -- no second recall implementation                              #
# --------------------------------------------------------------------------- #
def test_sealed_evaluator_delegates_to_harness_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []
    original = harness._recall

    def spy(slice_text: str, must_include: list[str]):
        calls.append((slice_text, list(must_include)))
        return original(slice_text, must_include)

    monkeypatch.setattr(harness, "_recall", spy)

    factory = make_recall_evaluator({"t1": ["needle"]})
    evaluator = factory()
    score = evaluator.score("text with needle inside", _task("t1"))

    assert calls, "make_recall_evaluator's scorer did not call harness._recall"
    assert calls[0] == ("text with needle inside", ["needle"])
    assert score == 1.0


def test_recall_scorer_reports_partial_and_zero_recall(
) -> None:
    factory = make_recall_evaluator({"t1": ["alpha", "beta"]})
    evaluator = factory()

    assert evaluator.score("has alpha only", _task("t1")) == 0.5
    assert evaluator.score("has neither", _task("t1")) == 0.0
    assert evaluator.score("has alpha and beta", _task("t1")) == 1.0


def test_recall_scorer_refuses_unregistered_task() -> None:
    factory = make_recall_evaluator({"t1": ["alpha"]})
    evaluator = factory()

    with pytest.raises(FreezeError, match="no gold labels registered"):
        evaluator.score("anything", _task("unknown-task"))


# --------------------------------------------------------------------------- #
# vacuous label guard                                                        #
# --------------------------------------------------------------------------- #
def test_vacuous_label_guard_refuses_empty_list() -> None:
    with pytest.raises(FreezeError, match="vacuously"):
        vacuous_label_guard([])


def test_vacuous_label_guard_accepts_nonempty_list() -> None:
    vacuous_label_guard(["alpha"])  # must not raise


def test_make_recall_evaluator_refuses_vacuous_task_at_construction() -> None:
    """A task with an empty must_include list must be refused when the
    factory is BUILT, not silently allowed to score a vacuous 1.0 partway
    through a run."""
    with pytest.raises(FreezeError, match="vacuously"):
        make_recall_evaluator({"t1": ["alpha"], "t2": []})


def test_harness_recall_is_genuinely_vacuous_for_empty_labels() -> None:
    """Documents WHY the guard exists: harness._recall really does return a
    vacuous 1.0 for an empty label list."""
    recall, missed = harness._recall("literally anything", [])
    assert recall == 1.0
    assert missed == []


# --------------------------------------------------------------------------- #
# fresh evaluator per trial -- no call-count leakage                         #
# --------------------------------------------------------------------------- #
def test_fresh_evaluator_per_trial_does_not_leak_call_counts() -> None:
    factory = make_recall_evaluator({"t1": ["alpha"]})

    first = factory()
    first.score("alpha here", _task("t1"))
    first.score("alpha here again", _task("t1"))
    assert first.calls == 2

    second = factory()
    assert second.calls == 0, (
        "a fresh evaluator from the same factory must not inherit the "
        "previous trial's call count")

    second.score("alpha here", _task("t1"))
    assert second.calls == 1
    assert first.calls == 2, "scoring the second evaluator must not affect the first"


def test_factory_produces_distinct_evaluator_instances() -> None:
    factory = make_recall_evaluator({"t1": ["alpha"]})
    assert factory() is not factory()
