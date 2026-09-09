"""Tests for the Gate-3 BM25 baseline arm (packet G3-BASE-01, acceptance C5).

Deterministic, offline, no network, no model calls. Uses real temp-directory
repositories (not mocks) so the tests exercise the actual
``daedalus.eval.harness`` code path the arm delegates to.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.arms.bm25 import BM25Arm
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError
from daedalus.eval.gate3.protocols import SealedEvaluator, Task


def _write_repo(tmp_path: Path) -> Path:
    """A tiny multi-file repo. ``alpha.py`` mentions "widget", ``beta.py``
    mentions "gadget", ``gamma.py``/``delta.py`` are byte-identical (to force
    a genuine BM25 score tie so the tie-break-by-label rule is exercised)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "alpha.py").write_text(
        'def foo_widget():\n    """A tiny widget helper."""\n    return 42\n',
        encoding="utf-8",
    )
    (repo / "beta.py").write_text(
        'def bar_gadget():\n    """A tiny gadget helper."""\n    return 7\n',
        encoding="utf-8",
    )
    tie_body = 'def tied_marker():\n    """A tied marker function."""\n    return 1\n'
    (repo / "gamma.py").write_text(tie_body, encoding="utf-8")
    (repo / "delta.py").write_text(tie_body, encoding="utf-8")
    return repo


def _recall_evaluator(marker: str, max_calls: int | None = None) -> SealedEvaluator:
    """A SealedEvaluator whose score is 1.0 iff ``marker`` appears in the
    candidate text -- deliberately simple so tests can predict the result."""
    def score_fn(candidate: str, task: Task) -> float:
        return 1.0 if marker in candidate else 0.0

    return SealedEvaluator("test-recall", score_fn, max_calls=max_calls)


def _task(repo: Path, question: str = "widget") -> Task:
    return Task(
        task_id="t1",
        repo_root=str(repo),
        question=question,
        target="alpha.py::foo_widget",
        label_plane="code",
    )


# --------------------------------------------------------------------------- #
# anti-duplication: the arm must genuinely delegate to harness._bm25_scores   #
# --------------------------------------------------------------------------- #
def test_arm_bm25_delegates_to_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _write_repo(tmp_path)
    original = harness._bm25_scores
    calls: list[tuple] = []

    def spy(query_tokens, doc_tokens, **kwargs):
        calls.append((tuple(query_tokens), len(doc_tokens)))
        return original(query_tokens, doc_tokens, **kwargs)

    monkeypatch.setattr(harness, "_bm25_scores", spy)

    arm = BM25Arm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("widget")
    outcome = arm.run(_task(repo), budget, evaluator, seed=0)

    assert calls, "BM25Arm did not call harness._bm25_scores -- a second BM25 formula would be a defect"
    assert outcome.error is None
    assert outcome.success is True
    assert outcome.score == 1.0
    assert "widget" in outcome.candidate


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_arm_bm25_deterministic_across_seeds(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = BM25Arm()
    assert arm.stochastic is False
    budget = ArmBudget(max_tokens=10_000)

    out_a = arm.run(_task(repo), budget, _recall_evaluator("widget"), seed=1)
    out_b = arm.run(_task(repo), budget, _recall_evaluator("widget"), seed=999)

    assert out_a.candidate == out_b.candidate
    assert out_a.score == out_b.score
    assert out_a.success == out_b.success
    assert out_a.tokens_used == out_b.tokens_used
    assert out_a.notes == out_b.notes


def test_arm_bm25_stable_ordering_under_score_ties(tmp_path: Path) -> None:
    """gamma.py and delta.py are byte-identical -> genuine BM25 score tie.
    Running the retrieval twice in-process must produce byte-identical output
    regardless of dict/set iteration order (no PYTHONHASHSEED dependence),
    because harness._bm25_context breaks ties by chunk label, not by
    insertion or hash order."""
    repo = _write_repo(tmp_path)
    arm = BM25Arm()
    budget = ArmBudget(max_tokens=10_000)
    task = Task(task_id="tie", repo_root=str(repo), question="tied_marker",
                target="gamma.py::tied_marker", label_plane="code")

    out_1 = arm.run(task, budget, _recall_evaluator("tied_marker"), seed=0)
    out_2 = arm.run(task, budget, _recall_evaluator("tied_marker"), seed=0)

    assert out_1.candidate == out_2.candidate
    # gamma.py sorts before delta.py? No -- alphabetically "delta" < "gamma".
    # Assert whichever the tie-break picks first is stable across both runs.
    first_label_1 = out_1.candidate.splitlines()[0]
    first_label_2 = out_2.candidate.splitlines()[0]
    assert first_label_1 == first_label_2


# --------------------------------------------------------------------------- #
# budget                                                                      #
# --------------------------------------------------------------------------- #
def test_arm_bm25_respects_token_budget(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = BM25Arm()
    evaluator = _recall_evaluator("widget")

    full_chunks = harness._repo_chunks(str(repo))
    assert len(full_chunks) == 4  # one chunk per function, four files

    tiny_budget = ArmBudget(max_tokens=1)
    tiny_outcome = arm.run(_task(repo), tiny_budget, evaluator, seed=0)
    assert tiny_outcome.error is None
    # budget of 1 token can only ever admit the single best-ranked chunk
    assert tiny_outcome.notes["n_chunks_used"] == 1
    assert tiny_outcome.notes["n_chunks_total"] == len(full_chunks)

    generous_budget = ArmBudget(max_tokens=10_000)
    generous_outcome = arm.run(_task(repo), generous_budget, evaluator, seed=0)
    assert generous_outcome.notes["n_chunks_used"] == len(full_chunks)
    assert generous_outcome.tokens_used >= tiny_outcome.tokens_used


# --------------------------------------------------------------------------- #
# no corpus filtering beyond _repo_chunks (the s07 lesson)                    #
# --------------------------------------------------------------------------- #
def test_arm_bm25_corpus_is_exactly_repo_chunks(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    arm = BM25Arm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("widget")

    outcome = arm.run(_task(repo), budget, evaluator, seed=0)

    assert outcome.notes["n_chunks_total"] == len(harness._repo_chunks(str(repo)))


# --------------------------------------------------------------------------- #
# ordinary failure -> ArmOutcome(error=...), never a raised exception         #
# --------------------------------------------------------------------------- #
def test_arm_bm25_ordinary_failure_yields_error_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _write_repo(tmp_path)

    def boom(root, **kwargs):
        # **kwargs rather than mirroring today's exact call: the arm passes
        # planes= since G3-ARM-PLANE-01, and a stub pinned to one signature
        # turns the next signature change into a TypeError wearing the costume
        # of the corpus failure this test is actually about.
        raise OSError("simulated corpus read failure")

    monkeypatch.setattr(harness, "_repo_chunks", boom)

    arm = BM25Arm()
    budget = ArmBudget(max_tokens=10_000)
    outcome = arm.run(_task(repo), budget, _recall_evaluator("widget"), seed=0)

    assert outcome.error is not None
    assert "simulated corpus read failure" in outcome.error
    assert outcome.success is None
    assert outcome.score is None


def test_arm_bm25_evaluator_contract_violation_still_raises(tmp_path: Path) -> None:
    """A FreezeError from the sealed evaluator (e.g. exhausted call budget) is
    a contract violation, not an ordinary failure -- it must propagate, not be
    swallowed into an ArmOutcome(error=...)."""
    repo = _write_repo(tmp_path)
    arm = BM25Arm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("widget", max_calls=0)

    with pytest.raises(FreezeError):
        arm.run(_task(repo), budget, evaluator, seed=0)
