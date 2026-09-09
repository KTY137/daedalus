"""Tests for the Gate-3 evaluator-only baseline arm (packet G3-BASE-01,
acceptance C9 -- the degenerate control).

Deterministic, offline, no network, no model calls. Uses real temp-directory
repositories (not mocks) so the tests exercise the actual candidate
enumeration this arm performs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.arms.evaluator_only import (
    EvaluatorOnlyArm,
    enumerate_candidates,
)
from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial


def _write_repo(tmp_path: Path) -> Path:
    """A tiny multi-file repo with a fixed, predictable enumeration order:
    ``os.walk`` + lexicographic sort visits ``a_noise.py`` before
    ``b_gold.py`` before ``c_noise.md``. ``b_gold.py`` carries three
    blank-line-delimited paragraphs; the gold marker sits in the middle one,
    so it is reachable only once at least 4 candidates have been examined
    (2 from a_noise.py + 1 leading paragraph in b_gold.py + the gold one)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a_noise.py").write_text(
        "def noise_one():\n    return 1\n"
        "\n\n"
        "def noise_two():\n    return 2\n",
        encoding="utf-8",
    )
    (repo / "b_gold.py").write_text(
        "# irrelevant leading paragraph\n"
        "\n\n"
        "GOLD_ANSWER lives right here\n"
        "\n\n"
        "# irrelevant trailing paragraph\n",
        encoding="utf-8",
    )
    (repo / "c_noise.md").write_text(
        "# doc\n\nsome unrelated documentation text\n", encoding="utf-8",
    )
    return repo


def _score_fn(candidate: str, task: Task) -> float:
    """1.0 for the gold paragraph, 0.3 for any other "noise" paragraph, 0.0
    otherwise -- deliberately simple so every test can predict the result."""
    if "GOLD_ANSWER" in candidate:
        return 1.0
    if "noise" in candidate:
        return 0.3
    return 0.0


def _evaluator(max_calls: int | None = None) -> SealedEvaluator:
    return SealedEvaluator("test-evaluator-only", _score_fn, max_calls=max_calls)


def _task(repo: Path) -> Task:
    return Task(
        task_id="t1",
        repo_root=str(repo),
        question="where does GOLD_ANSWER live?",
        target="b_gold.py",
        label_plane="code",
    )


# --------------------------------------------------------------------------- #
# basic contract: run_trial produces a TrialResult                            #
# --------------------------------------------------------------------------- #
def test_run_trial_produces_trial_result(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = EvaluatorOnlyArm()
    assert arm.name == "evaluator_only"
    assert arm.stochastic is False

    budget = ArmBudget(max_calls=100)
    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=100), seed=1)

    assert result.arm == "evaluator_only"
    assert result.error is None
    assert result.success is True
    assert result.score == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# no retrieval: BM25 must never be touched                                    #
# --------------------------------------------------------------------------- #
def test_no_retrieval_bm25_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "evaluator_only must perform NO retrieval -- it may not call "
            "harness._bm25_scores or harness._bm25_context")

    monkeypatch.setattr(harness, "_bm25_scores", _explode)
    monkeypatch.setattr(harness, "_bm25_context", _explode)

    repo = _write_repo(tmp_path)
    arm = EvaluatorOnlyArm()
    budget = ArmBudget(max_calls=100)
    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=100), seed=1)

    # If the arm had touched either patched function, the AssertionError above
    # would have propagated out of arm.run() as an ordinary failure and landed
    # in result.error -- so a clean, successful result is the proof.
    assert result.error is None
    assert result.success is True


# --------------------------------------------------------------------------- #
# argmax under a call budget that reaches the gold candidate                  #
# --------------------------------------------------------------------------- #
def test_selects_argmax_under_budget(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = EvaluatorOnlyArm()
    # a_noise.py contributes 2 candidates, b_gold.py's gold paragraph is the
    # 4th candidate in fixed order (2 + 1 leading + gold) -- budget of 4
    # reaches it exactly.
    budget = ArmBudget(max_calls=4)
    outcome = arm.run(_task(repo), budget, _evaluator(max_calls=4), seed=0)

    assert outcome.error is None
    assert outcome.score == pytest.approx(1.0)
    assert outcome.success is True
    assert "GOLD_ANSWER" in outcome.notes["candidate"]
    assert outcome.notes["candidates_examined"] == 4
    assert outcome.notes["retrieval"] == "none"
    assert outcome.notes["search"] == "none"


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_deterministic_across_seeds(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = EvaluatorOnlyArm()
    budget = ArmBudget(max_calls=100)

    out_a = arm.run(_task(repo), budget, _evaluator(max_calls=100), seed=1)
    out_b = arm.run(_task(repo), budget, _evaluator(max_calls=100), seed=999999)

    assert out_a.candidate == out_b.candidate
    assert out_a.score == out_b.score
    assert out_a.success == out_b.success
    assert out_a.notes == out_b.notes


# --------------------------------------------------------------------------- #
# evaluator-call budget is honored, never exceeded                            #
# --------------------------------------------------------------------------- #
def test_uses_no_more_calls_than_budget(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = EvaluatorOnlyArm()
    # Only 2 of the >=6 available candidates are admitted; the gold paragraph
    # (candidate #4) is unreachable, proving the cap is actually enforced.
    budget = ArmBudget(max_calls=2)
    evaluator = _evaluator(max_calls=2)

    result = run_trial(arm, _task(repo), budget, evaluator, seed=0)

    assert evaluator.calls <= budget.max_calls
    assert result.calls <= budget.max_calls
    assert result.error is None
    assert result.score == pytest.approx(0.3)  # noise, gold not yet reached
    assert result.success is False


# --------------------------------------------------------------------------- #
# non-handicap: matches an independent naive full scan at equal budget        #
# --------------------------------------------------------------------------- #
def test_matches_naive_full_scan_at_equal_budget(tmp_path: Path) -> None:
    """The strawman-control defect this arm must not repeat
    (docs/GATE2_FOREST_V2_TRIAGE.md line 105: slice s02's "+55.6 pp" collapsed
    to "0.12 pp" against the natural baseline) is a handicapped control that
    manufactures an artificial gap. Prove there is no such gap here: an
    independent "naive competitor" that scores the IDENTICAL declared
    candidate stream, in the same fixed order, under the same call budget and
    an independently-counted evaluator, must find a best score no better than
    (and here, identical to) what EvaluatorOnlyArm reports. If the arm were
    silently examining fewer candidates, skipping some, or reordering the
    stream to its disadvantage, this would diverge."""
    repo = _write_repo(tmp_path)
    task = _task(repo)
    budget = ArmBudget(max_calls=4)

    arm = EvaluatorOnlyArm()
    arm_outcome = arm.run(task, budget, _evaluator(max_calls=4), seed=7)

    # Independent competitor: same declared enumeration, same budget, its own
    # evaluator instance (so call counts cannot leak between the two).
    naive_evaluator = _evaluator(max_calls=4)
    naive_candidates = list(enumerate_candidates(task.repo_root))[: budget.max_calls]
    naive_best = max(naive_evaluator.score(c, task) for c in naive_candidates)

    assert arm_outcome.error is None
    assert arm_outcome.score == pytest.approx(naive_best)


# --------------------------------------------------------------------------- #
# ordinary failure -> ArmOutcome/TrialResult(error=...), never a raised       #
# exception, and never a success/score alongside it                          #
# --------------------------------------------------------------------------- #
def test_errored_run_has_no_success_or_score(tmp_path: Path) -> None:
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    arm = EvaluatorOnlyArm()
    budget = ArmBudget(max_calls=10)

    result = run_trial(arm, _task(empty_repo), budget, _evaluator(max_calls=10), seed=0)

    assert result.error is not None
    assert "no candidates found" in result.error
    assert result.success is None
    assert result.score is None
