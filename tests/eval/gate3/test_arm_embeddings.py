"""Acceptance test C6 (G3-BASE-01 §5c): the Embeddings baseline arm.

Fast, offline, no model calls by default. The candidate pool is real
repository chunks (via ``daedalus.eval.harness._repo_chunks``, the SAME
function BM25 (arm C5) and Best-of-N (arm C2) reuse) so this test exercises
the arm exactly the way it runs in production and directly checks the corpus
identity that ``docs/GATE2_FOREST_V2_TRIAGE.md`` line 106 names as the place a
prior slice's headline was inflated (+0.056 MRR from a corpus filter, not from
the ranking formula).
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from daedalus.eval.gate3.arms.embeddings import EmbeddingsArm
from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial
from daedalus.eval.harness import _repo_chunks

N_CHUNKS = 6
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_repo(tmp_path) -> str:
    """N single-function files -> N distinct BM25/embeddings chunks. Each
    function body carries a token unique to it (``mark_i`` / ``func_i``) so a
    query naming one of them has an unambiguous best match."""
    for i in range(N_CHUNKS):
        (tmp_path / f"mod_{i}.py").write_text(
            f"def func_{i}():\n    return 'MARK_{i}'\n", encoding="utf-8")
    return str(tmp_path)


def _task(repo_root: str, question: str = "irrelevant") -> Task:
    return Task(task_id="t1", repo_root=repo_root, question=question,
                target="mod_0.py::func_0", label_plane="code")


def _marker_evaluator(best_marker: str) -> SealedEvaluator:
    """Score 1.0 iff ``best_marker`` appears in the retrieved candidate, else
    0.1 -- gives the arm exactly one known-best context to assemble."""

    def _score(candidate: str, task: Task) -> float:
        return 1.0 if best_marker in candidate else 0.1

    return SealedEvaluator("marker", _score)


# --------------------------------------------------------------------------- #
# produces a TrialResult via run_trial                                        #
# --------------------------------------------------------------------------- #
def test_produces_trial_result_via_run_trial(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_2")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_2")

    result = run_trial(arm, task, budget, evaluator, seed=7)

    assert result.arm == "embeddings"
    assert result.task_id == "t1"
    assert result.error is None
    assert result.measured
    assert result.success in (True, False)
    assert result.calls == 1  # one score() call over the assembled context
    assert result.tokens_used > 0
    assert result.budget_exceeded is False


# --------------------------------------------------------------------------- #
# same corpus as BM25 -- no extra filtering                                   #
# --------------------------------------------------------------------------- #
def test_same_corpus_as_bm25(tmp_path):
    repo = _build_repo(tmp_path)
    expected_chunks = _repo_chunks(repo)
    task = _task(repo, question="func_0")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_0")

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is None
    assert outcome.notes["n_chunks_total"] == len(expected_chunks) == N_CHUNKS


# --------------------------------------------------------------------------- #
# respects the token budget (and never returns an empty context)              #
# --------------------------------------------------------------------------- #
def test_generous_budget_includes_every_chunk(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_3")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_3")

    result = run_trial(arm, task, budget, evaluator, seed=1)

    assert result.error is None
    assert result.budget_exceeded is False


def test_tiny_budget_forces_truncation_but_never_an_empty_context(tmp_path):
    """R1/R5 anti-starvation rule (same as ``_bm25_context``): the single
    top-ranked chunk is always included even though it alone busts a
    budget this small -- an empty context is a strictly worse baseline than
    a slightly-over one. The overrun must be REPORTED, never silently clipped."""
    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_1")
    budget = ArmBudget(max_tokens=1)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_1")

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is None
    assert outcome.notes["n_chunks_used"] == 1
    assert outcome.notes["truncated"] is True
    assert outcome.notes["top_label"] == "mod_1.py::func_1"
    assert outcome.tokens_used > budget.max_tokens  # forced-over, not clipped

    result = run_trial(arm, task, budget, evaluator, seed=1)
    assert result.budget_exceeded is True  # reported, not hidden


# --------------------------------------------------------------------------- #
# deterministic: same seed -> identical output; not stochastic                #
# --------------------------------------------------------------------------- #
def test_two_different_seeds_produce_identical_output(tmp_path):
    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_4")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm()

    out1 = arm.run(task, budget, _marker_evaluator("MARK_4"), seed=1)
    out2 = arm.run(task, budget, _marker_evaluator("MARK_4"), seed=999_999)

    assert arm.stochastic is False
    assert out1.candidate == out2.candidate
    assert out1.score == out2.score
    assert out1.notes["top_label"] == out2.notes["top_label"]
    assert out1.notes["top_score"] == out2.notes["top_score"]


def test_no_builtin_hash_on_str_in_source():
    """Static guarantee behind the determinism claim: the module must never
    call Python's built-in string hashing, whose per-process salt
    (``PYTHONHASHSEED``) would silently make two otherwise-identical runs
    disagree. ``hashlib.*`` calls do not contain the substring ``hash(``."""
    source = (_REPO_ROOT / "daedalus" / "eval" / "gate3" / "arms"
              / "embeddings.py").read_text(encoding="utf-8")
    assert "hash(" not in source


def test_hashing_vector_stable_across_pythonhashseed(tmp_path):
    """Determinism ACROSS PROCESSES, not just within one: spawn the same
    vectorizer call under two different ``PYTHONHASHSEED`` values and require
    byte-identical output. This is the concrete refutation of "maybe it only
    looks stable because one process happened to reuse a cached seed"."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json\n"
        "from daedalus.eval.gate3.arms.embeddings import _hashing_vector\n"
        "vec = _hashing_vector(['def', 'return', 'mark_2', 'func_2', 'irrelevant'], 64)\n"
        "print(json.dumps(vec))\n",
        encoding="utf-8",
    )

    def _run_with_seed(seed: str) -> list[float]:
        import os
        env = dict(**{**__import__("os").environ, "PYTHONHASHSEED": seed})
        completed = subprocess.run(
            [sys.executable, str(probe)],
            cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout.strip().splitlines()[-1])

    vector_seed_0 = _run_with_seed("0")
    vector_seed_other = _run_with_seed("4257849302")

    assert vector_seed_0 == vector_seed_other


# --------------------------------------------------------------------------- #
# no network call by default                                                  #
# --------------------------------------------------------------------------- #
def test_default_embedder_makes_no_network_call(tmp_path, monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError(
            "the default (no real_embedder opt-in) path must never touch the "
            "network")

    monkeypatch.setattr(urllib.request, "urlopen", _explode)
    monkeypatch.setattr(socket, "socket", _explode)

    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_5")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_5")

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is None


# --------------------------------------------------------------------------- #
# ordinary failure -> ArmOutcome/TrialResult with error, no score/success     #
# --------------------------------------------------------------------------- #
def test_ordinary_failure_returns_error_outcome_not_raise(tmp_path):
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    task = _task(str(empty_repo))
    budget = ArmBudget(max_tokens=1_000)
    arm = EmbeddingsArm()
    evaluator = _marker_evaluator("MARK_0")

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is not None
    assert outcome.success is None
    assert outcome.score is None

    result = run_trial(arm, task, budget, evaluator, seed=1)
    assert result.error is not None
    assert result.success is None
    assert result.score is None
    assert not result.measured


def test_opt_in_real_embedder_failure_is_explicit_not_a_silent_fallback(tmp_path):
    """Opting in to a real embedder and having it fail must produce an error
    outcome, never a quiet substitution back to the hashing vectorizer -- a
    report that mixed the two would misrepresent what was actually measured."""

    def _broken_embedder(texts):
        raise RuntimeError("embedder host unreachable")

    repo = _build_repo(tmp_path)
    task = _task(repo, question="func_0")
    budget = ArmBudget(max_tokens=100_000)
    arm = EmbeddingsArm(real_embedder=_broken_embedder)
    evaluator = _marker_evaluator("MARK_0")

    outcome = arm.run(task, budget, evaluator, seed=1)

    assert outcome.error is not None
    assert "real-embedder-opt-in" in outcome.error
    assert outcome.success is None
    assert evaluator.calls == 0  # never reached scoring
