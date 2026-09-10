"""local_mutation.py -- Gate-3 baseline (C4): simple local search / hill-climbing.

Plan §11 Gate 3 requires "simple local mutation" as one of the eleven frozen
baselines. It exists to answer one question honestly: does a method smarter
than blind local search actually buy anything, at an EQUAL budget? For that
comparison to mean something, this arm must stay deliberately dumb.

ALGORITHM (declared here, not buried): single-start, single-neighbor hill
climbing over a bitmask "which repo chunks are in the candidate" search space.

    1. Build the candidate universe: every retrieval unit `daedalus.eval.
       harness._repo_chunks` extracts from `task.repo_root` (function/class
       chunks, else whole files) -- the SAME retrieval-unit definition the
       BM25 baseline (C5) uses, so C4 and C5 search/retrieve over the same
       universe and a later comparison is not an artifact of two different
       corpora.
    2. Pick one random initial subset of chunks (`random.Random(seed)`,
       50/50 per chunk) and render it to a candidate string.
    3. Score it once (`evaluator.score`).
    4. Loop: flip ONE randomly chosen chunk's membership (the smallest
       possible edit to the bitmask -- the "local mutation"), score the
       result, and keep it only if it scored STRICTLY better. Otherwise
       discard it and try another flip.
    5. Stop when the budget says stop (`ArmBudget.max_calls` /
       `max_wall_seconds` / `max_tokens`; each evaluator call is exactly one
       loop iteration, so `max_calls` bounds iterations directly). If NONE of
       the three axes is set, a documented safety valve
       (`_MAX_ITERATIONS_WHEN_UNBOUNDED`) still stops the loop -- an infinite
       arm is not "unbounded execution" (plan §4.1), it is a bug.

WHAT THIS ARM DELIBERATELY DOES NOT DO, so a comparison against it stays
honest (per packet instruction: "it must not be secretly smart"):

    * no restarts -- one initial point, chosen once from `seed`;
    * no population -- one candidate is alive at a time;
    * no simulated-annealing / acceptance-of-worse-moves schedule -- a
      mutation is kept iff it is strictly better, full stop;
    * no memory of previously tried flips (no tabu list);
    * no gradient, no domain knowledge of what makes a chunk "good".

`ArmOutcome.notes["algorithm"]` names this exact configuration
(`hill_climbing_single_flip_no_restarts_no_annealing`) so a report renders it
without re-deriving it from behaviour.

DISAMBIGUATION: `daedalus/eval/mutate.py` is NOT reused here, and reusing it
would be a category error. Reading it (module docstring, `generate()`,
`Mutant`, `trivially_equivalent`) shows it is a MUTATION-TESTING corpus
generator: given a repository, it produces AST-level defects (dropped calls,
inverted conditions, changed constants, ...) to check whether some OTHER tool
(a lint rule, a graph-delta detector) notices the defect. Its unit of work is
"one static, pre-computed corpus of broken programs", it has no scoring
feedback loop, no notion of "better", and no iteration budget -- it is a
fixture generator for a detector's recall, not a search operator that climbs
toward a goal. This arm instead needs a live accept/reject loop against a
`SealedEvaluator`, which `mutate.py` does not provide and was never designed
to provide. Building a second thing that happens to share the word "mutate"
is not "one canonical path" (plan §5) -- it is a different problem wearing the
same name, and conflating them would be the actual defect.

Only `daedalus.eval.harness.count_tokens` and `_repo_chunks` are reused here,
per the packet's explicit reuse instruction; no second BM25, tokenizer, or
retrieval-unit definition is introduced.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1. Not
Gate-3 baseline evidence until an owner seals the harness (see
`daedalus.eval.gate3.contracts.RunManifest`).
"""
from __future__ import annotations

import random
import time
from typing import Sequence

from daedalus.eval.harness import _RETRIEVABLE_PLANES, _repo_chunks
# count_tokens is reached through the module rather than imported by name:
# harness does not DEFINE it -- it imports it from daedalus.structcore.tokens
# inside a try/except with a chars/4 fallback, so a from-import re-exports
# another module's name. tests/test_deepseek_substitution_guard.py refuses
# that, and the sibling arms (bm25, separate_indices) already use this form.
from daedalus.eval import harness as _harness

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Safety valve when NO budget axis is set at all (all three of max_calls,
#: max_wall_seconds, max_tokens are None). This is not a secret extra budget:
#: it only ever fires in the degenerate case where the caller declared no
#: limit whatsoever, and its purpose is solely to stop an infinite loop.
_MAX_ITERATIONS_WHEN_UNBOUNDED = 500


class LocalMutationArm:
    """Gate-3 baseline C4. See module docstring for the exact algorithm."""

    name = "local_mutation"
    stochastic = True
    #: Repaired 2026-09-10 (G3-ARM-PLANE-01): this arm now requests
    #: ``planes=_RETRIEVABLE_PLANES`` instead of inheriting the code-only
    #: default, so it retrieves data and knowledge documents as well. Declared
    #: here so ``gate3.coverage`` can admit a cross-plane comparison, and
    #: checked against behaviour by
    #: ``test_real_arm_declarations_match_what_they_retrieve`` rather than
    #: trusted.
    retrieved_planes = ("code", "data", "knowledge")

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        """Hill-climb a chunk-subset candidate. Never raises for an ordinary
        failure (e.g. an unreadable repo, a scorer that throws) -- those come
        back as ``ArmOutcome(error=...)``. A ``FreezeError`` (contract
        violation, e.g. the sealed evaluator's own call budget) is not an
        ordinary failure and is left to propagate.
        """
        try:
            return self._run(task, budget, evaluator, seed)
        except FreezeError:
            raise
        except Exception as exc:  # ordinary failure -> reported, not raised
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

    def _run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
              seed: int) -> ArmOutcome:
        rng = random.Random(seed)  # never the global random module
        chunks: Sequence[tuple[str, str]] = _repo_chunks(task.repo_root, planes=_RETRIEVABLE_PLANES)
        n = len(chunks)
        calls_before = evaluator.calls
        t0 = time.perf_counter()

        def render(selection: tuple[bool, ...]) -> str:
            return "\n".join(chunks[i][1] for i in range(n) if selection[i])

        def budget_left(tokens_spent: int) -> bool:
            calls_made = evaluator.calls - calls_before
            if budget.max_calls is not None and calls_made >= budget.max_calls:
                return False
            if (budget.max_wall_seconds is not None
                    and (time.perf_counter() - t0) >= budget.max_wall_seconds):
                return False
            if budget.max_tokens is not None and tokens_spent >= budget.max_tokens:
                return False
            return True

        selected = tuple(rng.random() < 0.5 for _ in range(n))
        candidate = render(selected)
        tokens_spent = _harness.count_tokens(candidate) if candidate else 0
        score = evaluator.score(candidate, task)
        score_history = [score]
        iterations = 0
        unbounded = (budget.max_calls is None and budget.max_wall_seconds is None
                     and budget.max_tokens is None)

        while n > 0 and budget_left(tokens_spent):
            if unbounded and iterations >= _MAX_ITERATIONS_WHEN_UNBOUNDED:
                break
            flip = rng.randrange(n)
            mutated_selection = (
                selected[:flip] + (not selected[flip],) + selected[flip + 1:]
            )
            mutated_candidate = render(mutated_selection)
            tokens_spent += _harness.count_tokens(mutated_candidate) if mutated_candidate else 0
            mutated_score = evaluator.score(mutated_candidate, task)
            iterations += 1
            if mutated_score > score:  # strictly better only -- no sideways moves
                selected, candidate, score = mutated_selection, mutated_candidate, mutated_score
            score_history.append(score)

        return ArmOutcome(
            candidate=candidate,
            score=score,
            success=True,
            tokens_used=tokens_spent,
            notes={
                "algorithm": "hill_climbing_single_flip_no_restarts_no_annealing",
                "iterations": iterations,
                "n_chunks": n,
                "score_history": tuple(score_history),
            },
        )
