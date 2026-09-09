"""evaluator_only.py -- the degenerate control: no retrieval, no search (C9).

WHY THIS ARM EXISTS
--------------------
Plan §11 Gate 3, sentence 2 requires "evaluator-only selection" as one of the
eleven mandatory baselines. Plan §14 lists a kill criterion in the same
breath: "graph-conditioned prioritization does not beat random or
evaluator-only choice". Together these make this arm the answer to one
question, asked of every other arm in this harness: *is the clever method
actually doing anything, or is the evaluator doing all the work?*

This arm performs NO retrieval (no BM25, no embeddings, no graph traversal)
and NO search (no mutation, no population, no LLM proposal loop). It
enumerates candidates in a fixed, declared order and asks the sealed
evaluator to score each one, spending nothing but evaluator calls. If a
sophisticated arm cannot beat this one at an EQUAL evaluator-call budget
(packet rule R1 -- the full budget, never split), the sophistication
contributed nothing measurable.

This arm must therefore be implemented HONESTLY and not handicapped. A
deliberately weakened control is a recorded defect in this repository:
`docs/GATE2_FOREST_V2_TRIAGE.md` line 105 -- slice s02 claimed "+55.6 pp"
against a strawman control ("Strohmann-Kontrolle"); against the natural
baseline the gain was 0.12 pp. A control that is artificially handicapped
manufactures the appearance of a finding out of the handicap, not the method.
This module's non-handicap test (`test_matches_naive_full_scan_at_equal_budget`
in the paired test file) exists precisely to catch that failure mode here.

CANDIDATE ENUMERATION ORDER (declared, fixed, deterministic -- packet rule
R4: the denominator/order is fixed before the run, never chosen to flatter a
result):

  1. Walk every regular file under ``task.repo_root`` with ``os.walk``,
     sorting ``dirnames`` and ``filenames`` lexicographically at every level
     (mirrors the ignore-directory hygiene of ``daedalus.eval.harness``, but
     imports nothing from it -- this arm is retrieval-free by construction,
     not by convention).
  2. Within a file, split the decoded UTF-8 text on blank-line boundaries
     into non-empty paragraph chunks, in file order. A file that cannot be
     decoded as UTF-8 is skipped, not treated as an enumeration failure.
  3. The candidate stream is exactly this (file, chunk) sequence in that
     fixed order. No heuristic reorders it: no BM25 score, no embedding
     similarity, no length or frequency sort.

SELECTION RULE: score every candidate in that fixed order via
``evaluator.score``, stopping once ``budget.max_calls`` scores have been
spent (or the stream is exhausted -- an uncapped ``max_calls`` scores every
candidate), and return the highest-scoring candidate observed. That is the
entirety of the method: argmax over a fixed enumeration under one shared,
un-split budget (packet rule R1 -- ``ArmBudget.split`` is never called).

``success`` is declared ``True`` when the best observed score is ``>= 1.0``,
matching the "recall == 1.0" full-match convention already used by
``daedalus.eval.harness`` (Tier 1 slice-recall). Any positive-but-partial
score is a scored miss, not a success -- this arm does not lower its own bar.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
Not Gate-3 baseline evidence until an owner seals the harness (see
``daedalus.eval.gate3.contracts.RunManifest``).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..contracts import ArmBudget
from ..protocols import ArmOutcome, SealedEvaluator, Task

# Mirrors daedalus.eval.harness._IGNORE_DIRS for walk hygiene only -- a plain
# frozenset, not an import, so this module stays retrieval-free by
# construction and cannot accidentally pick up BM25 or any other retrieval
# helper through a shared dependency.
_IGNORE_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
})

_BLANK_LINE = re.compile(r"\n\s*\n")

ENUMERATION_ORDER_DECLARATION = (
    "os.walk(repo_root) with dirnames and filenames sorted lexicographically "
    "at every level (ignoring _IGNORE_DIRS); within each file, blank-line-"
    "delimited paragraph chunks in file order. No retrieval heuristic reorders "
    "this stream."
)


def _iter_repo_files(repo_root: str) -> Iterator[str]:
    """Every regular file under ``repo_root``, in fixed lexicographic order."""
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORE_DIRS)
        for filename in sorted(filenames):
            yield os.path.join(dirpath, filename)


def _split_paragraphs(text: str) -> Iterator[str]:
    for para in _BLANK_LINE.split(text):
        para = para.strip()
        if para:
            yield para


def enumerate_candidates(repo_root: str) -> Iterator[str]:
    """The declared, fixed-order candidate stream (see module docstring).

    Public so a test (or an independent naive competitor) can consume the
    exact same stream this arm consumes -- that identity is what makes the
    non-handicap test meaningful rather than a restatement of the arm's own
    internals.
    """
    for path in _iter_repo_files(repo_root):
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or non-text file: skipped, not a failure
        yield from _split_paragraphs(text)


@dataclass
class EvaluatorOnlyArm:
    """The evaluator-only degenerate control (plan §11 Gate 3; §14 kill
    criterion). See module docstring for the full justification and the
    declared enumeration order.
    """

    name: str = field(default="evaluator_only")
    stochastic: bool = field(default=False)

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
             seed: int) -> ArmOutcome:
        del seed  # deterministic arm: the fixed enumeration never depends on it

        try:
            candidates = list(enumerate_candidates(task.repo_root))
        except OSError as exc:
            return ArmOutcome(
                error=f"could not enumerate candidates under {task.repo_root!r}: {exc}")
        if not candidates:
            return ArmOutcome(
                error=f"no candidates found under {task.repo_root!r}")

        max_calls = budget.max_calls
        best_candidate: str | None = None
        best_score: float | None = None
        examined = 0
        for candidate in candidates:
            if max_calls is not None and examined >= max_calls:
                break
            score = evaluator.score(candidate, task)
            examined += 1
            if best_score is None or score > best_score:
                best_score, best_candidate = score, candidate

        if best_candidate is None or best_score is None:
            return ArmOutcome(
                error=(f"evaluator call budget ({max_calls}) allowed zero of "
                       f"{len(candidates)} available candidates to be scored"))

        return ArmOutcome(
            candidate=best_candidate,
            score=best_score,
            success=best_score >= 1.0,
            tokens_used=max(1, len(best_candidate) // 4),
            notes={
                "enumeration_order": ENUMERATION_ORDER_DECLARATION,
                "candidates_available": len(candidates),
                "candidates_examined": examined,
                "retrieval": "none",
                "search": "none",
                "selection_rule": ("argmax(evaluator.score) over the fixed-order "
                                    "candidate stream, truncated to budget.max_calls"),
                "candidate": best_candidate,
            },
        )
