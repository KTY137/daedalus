"""best_of_n.py -- the Best-of-N Gate-3 baseline arm (plan §11 Gate 3, C2).

THE POINT OF THIS ARM: Best-of-N is the baseline that isolates how much of any
gain is just "more evaluator calls". It proposes N candidates and returns
whichever one the evaluator scores highest -- no retrieval cleverness, no
mutation, no model. Any method this arm ties or beats has not shown it does
anything smarter than sampling harder. Because the whole method IS evaluator
consumption, this is the arm where evaluator-call budgeting matters most: an
arm that quietly samples more than its declared budget allows would manufacture
its own advantage, which is exactly the "hidden budget asymmetry" plan §4
invariant 9 forbids.

Candidate source (offline, no model, no network): the task's own repository,
chunked by ``daedalus.eval.harness._repo_chunks`` -- the SAME retrieval-unit
function BM25 (arm C5) uses, reused rather than forked per the packet's
"extend, never duplicate" rule (G3-BASE-01 §2). Each chunk is one function/
class body, or a whole file when nothing is extractable. Best-of-N's
"candidates" are therefore existing source units of the target repository,
sampled without replacement by a seeded RNG -- a model-free stand-in for "N
things a generator might have proposed", honest about carrying no generative
capability of its own.

N is DERIVED from the declared budget, never hardcoded:

    N = budget.max_calls                     when max_calls is set
    N = BestOfNArm.DEFAULT_N (documented)     when max_calls is None

and additionally capped at the number of candidates actually available, since
sampling more than exist would require replacement and silently inflate
apparent diversity. Every trial calls ``evaluator.score`` at most N times --
never more, so the evaluator's own budget guard (``SealedEvaluator``, plan §4
invariant 9) never needs to fire to keep this arm honest.

``success`` follows this repository's existing recall convention (see
``daedalus.eval.harness._recall``): a score of ``1.0`` means the gold labels
were fully satisfied. Best-of-N reports success only when its best candidate
reached that ceiling; anything less is an honest partial result, not silently
rounded up.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from daedalus.eval.harness import _repo_chunks
# count_tokens is reached through the module rather than imported by name:
# harness does not DEFINE it -- it imports it from daedalus.structcore.tokens
# inside a try/except with a chars/4 fallback, so a from-import re-exports
# another module's name. tests/test_deepseek_substitution_guard.py refuses
# that, and the sibling arms (bm25, separate_indices) already use this form.
from daedalus.eval import harness as _harness

from ..contracts import ArmBudget
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Applied only when the caller declares no ``max_calls`` at all -- an
#: uncapped comparison is not this packet's default posture (every other axis
#: in ``ArmBudget`` defaults to ``None`` meaning "not capped for this
#: comparison", but Best-of-N's *entire* mechanism is "how many samples", so an
#: undeclared call budget still needs a stated, non-hardcoded-per-run number
#: to sample a finite N from. Recorded in ``ArmOutcome.notes`` whenever used,
#: so a report never mistakes it for a measured budget.
DEFAULT_N_WHEN_UNCAPPED = 8

#: This repository's recall convention (``daedalus.eval.harness._recall``):
#: 1.0 means every gold label was found. Best-of-N adopts the same ceiling for
#: its own success verdict rather than inventing a second scale.
SUCCESS_SCORE = 1.0


@dataclass
class BestOfNArm:
    """Sample N repository chunks, score each, keep the best.

    ``name``/``stochastic`` satisfy the ``Arm`` protocol (``protocols.py``).
    Stateless aside from those two fields -- ``run`` takes everything else as
    arguments, so one instance may be reused across tasks/seeds safely.
    """

    name: str = "best_of_n"
    stochastic: bool = True

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        try:
            chunks = _repo_chunks(task.repo_root)
        except OSError as exc:
            return ArmOutcome(error=f"OSError reading {task.repo_root!r}: {exc}")

        if not chunks:
            return ArmOutcome(
                error=f"no candidate chunks found under {task.repo_root!r}")

        used_default = budget.max_calls is None
        declared_n = budget.max_calls if budget.max_calls is not None \
            else DEFAULT_N_WHEN_UNCAPPED
        n = min(declared_n, len(chunks))

        rng = random.Random(seed)
        sampled = rng.sample(chunks, n)

        best_label: str | None = None
        best_candidate: str | None = None
        best_score: float | None = None
        tokens_used = 0
        for label, text in sampled:
            score = evaluator.score(text, task)
            tokens_used += _harness.count_tokens(text)
            if best_score is None or score > best_score:
                best_score = score
                best_candidate = text
                best_label = label

        success = best_score is not None and best_score >= SUCCESS_SCORE
        return ArmOutcome(
            candidate=best_candidate,
            score=best_score,
            success=success,
            tokens_used=tokens_used,
            notes={
                "n_sampled": n,
                "n_candidates_available": len(chunks),
                "n_default_used": used_default,
                "best_label": best_label,
            },
        )
