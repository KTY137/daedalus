"""bm25.py -- Gate-3 baseline (e): BM25 retrieval, wired to the existing harness.

Packet G3-BASE-01, acceptance test C5 (``test_arm_bm25_delegates_to_harness``).
This module is deliberately thin: it is an *adapter* from the ``Arm`` protocol
(``daedalus.eval.gate3.protocols``) to the Okapi BM25 implementation that
already lives in ``daedalus.eval.harness`` -- ``_bm25_tokenize``,
``_bm25_scores`` (k1=1.2, b=0.75, deterministic tie-break by chunk label) and
``_bm25_context`` (budget-bounded top-k assembly). It contains NO scoring
formula of its own. Plan §5 ("one canonical path per responsibility") and
packet §2 ("Extend, never duplicate") both name a second BM25 implementation
as a release-blocking defect, and this module exists specifically to avoid
being that defect.

CORPUS, STATED EXPLICITLY (the lesson this docstring exists to carry forward):
docs/GATE2_FOREST_V2_TRIAGE.md:106 records that a previous BM25 slice (s07)
survived an independent reimplementation of the FORMULA byte-for-byte, but its
CORPUS FILTER inflated the headline result by +0.056 MRR -- the formula was
never the defect, which documents to include was. This arm therefore retrieves
over EXACTLY the document universe ``daedalus.eval.harness._repo_chunks``
already defines for arm C of the existing A/B/C comparison: one chunk per
extractable function/class unit, or the whole file when nothing is
extractable, walked over every source file under the task's repo root (minus
the harness's own build/VCS ignore list). This module adds NO further filter --
no de-duplication, no relevance pre-screen, no plane restriction, no exclusion
list of its own. If a future change filters the corpus for this arm, that is a
defect against this docstring's stated invariant, not an optimization.

BUDGET (packet rule R1): the arm receives ``budget.max_tokens`` as its full,
undivided retrieval budget -- passed straight through to
``harness._bm25_context``'s own budget-bounded top-k selection. ``ArmBudget``
has no internal components to split for a single-index retriever, so R1's
"never call ``budget.split()``" is trivially satisfied here; it does not apply
to a second, composite arm the way it would to the four-separate-indices arm.
An unset (``None``) token budget means this comparison declared no token cap;
this arm then retrieves the entire corpus in ranked order rather than
inventing a hidden ceiling.

DETERMINISM: ``stochastic = False``. BM25 over a fixed corpus, fixed query and
fixed budget produces byte-identical output on every call, independent of the
run's seed and independent of ``PYTHONHASHSEED`` -- ``_repo_chunks`` walks
sorted directory and file names, and ``_bm25_context`` breaks score ties by
chunk label rather than by dict/set iteration order. This arm's ``seed``
parameter is accepted (the ``Arm`` protocol requires it) and otherwise unused.

SCORING: the arm has exactly one capability, ``evaluator.score(candidate,
task)`` (plan §4 invariant 3 -- it may not read task.must_include or any other
gold label directly). ``success`` is declared here as "the evaluator scored
this retrieval at least as high as its own maximum for a fully-successful
retrieval, 1.0" -- the same threshold ``daedalus.eval.harness`` already uses
for a perfect ``_recall`` (``c_beats_a``, ``recall_C >= 1.0`` style checks).
This is a declared convention of this arm, not a universal law of the
``Arm`` protocol; a different arm may define success differently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from daedalus.eval import harness

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Recall/score value that counts as a fully successful retrieval. Matches
#: ``daedalus.eval.harness``'s own convention that a perfect ``_recall`` is
#: exactly 1.0 (see ``eval_task_arms``'s ``c_beats_a``docstring).
_SUCCESS_THRESHOLD = 1.0


@dataclass
class BM25Arm:
    """Gate-3 baseline (e): Okapi BM25 top-k retrieval, full budget, no LLM.

    Delegates every scoring decision to ``daedalus.eval.harness``; see the
    module docstring for the corpus and budget invariants this wiring must not
    violate.
    """

    name: str = "bm25"
    stochastic: bool = False

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        del seed  # deterministic arm; accepted only to satisfy the Arm protocol
        try:
            chunks = harness._repo_chunks(task.repo_root)
            query = (task.question or "").strip() or harness._target_query(task.target)
            budget_tokens = budget.max_tokens if budget.max_tokens is not None else math.inf
            retrieval = harness._bm25_context(chunks, query, budget_tokens=budget_tokens)
        except FreezeError:
            raise  # contract violation: never swallowed (protocols.Arm docstring)
        except Exception as exc:  # ordinary failure -> an errored outcome, not a crash
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

        candidate = retrieval["text"]
        try:
            score = evaluator.score(candidate, task)
        except FreezeError:
            raise
        except Exception as exc:
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

        return ArmOutcome(
            candidate=candidate,
            score=score,
            success=score >= _SUCCESS_THRESHOLD,
            tokens_used=retrieval["tokens"],
            notes={
                "n_chunks_total": retrieval["n_chunks_total"],
                "n_chunks_used": retrieval["n_chunks_used"],
                "truncated": retrieval["truncated"],
                "query": query,
            },
        )
