"""random_search.py -- baseline (a): Random Search (plan §11 Gate 3, sentence 2).

Random Search is the weakest reasonable search baseline every other search arm
(Best-of-N, single-LLM loop, local mutation, MAP-Elites, AlphaEvolve proxy)
must beat to justify its own complexity. It spends its budget assembling
uniformly-random candidate contexts from the repository's chunks (see
``daedalus.eval.harness._repo_chunks`` -- one chunk per extractable function/
class, else the whole file) and keeps the best-scoring one it found.

Determinism: GIVEN A SEED. Uses ``random.Random(seed)``, never the
module-level ``random`` -- a shared global generator would let one arm's
sampling perturb another "independent" trial's draw, the same category of
hidden state leak packet rules R1/R2 exist to prevent, just for the RNG
instead of the budget.

Budget discipline (packet G3-BASE-01 rule R1): the FULL declared
``ArmBudget`` is used for this arm's one and only search loop --
``budget.split()`` is never called and never needed here; there is nothing to
split it across. ``max_calls`` bounds the number of evaluator calls
(candidates tried); this arm enforces that bound itself, in addition to
whatever cap the evaluator was independently constructed with, so a
mismatched pair of caps still cannot let it overspend. ``max_tokens`` bounds
each individual candidate's size, assembled the same "never split a chunk
mid-way" way ``harness._bm25_context`` builds arm C's context: the first
(here, first-drawn) chunk is always included even if it alone exceeds the
budget, and any overage is reported honestly via ``tokens_used`` for
``run_trial`` to flag as ``budget_exceeded`` -- never silently clipped inside
a chunk.

Ordinary failure (no repository chunks to sample, an unreadable target) is
returned as ``ArmOutcome(error=...)`` -- never raised. A contract violation
(the evaluator's own call budget exhausted, a sealed-evaluator breach) is a
``FreezeError`` and is allowed to propagate, per ``protocols.Arm.run``'s
contract.
"""
from __future__ import annotations

import random

from daedalus.eval.harness import _RETRIEVABLE_PLANES, _repo_chunks
# count_tokens is reached through the module rather than imported by name:
# harness does not DEFINE it -- it imports it from daedalus.structcore.tokens
# inside a try/except with a chars/4 fallback, so a from-import re-exports
# another module's name. tests/test_deepseek_substitution_guard.py refuses
# that, and the sibling arms (bm25, separate_indices) already use this form.
from daedalus.eval import harness as _harness

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: Trial count used only when the comparison leaves the evaluator-call axis
#: uncapped (``ArmBudget.max_calls is None``). Search must still terminate in
#: finite, deterministic time; this is a declared default, never a hidden one.
_DEFAULT_TRIALS_WHEN_UNCAPPED = 10


def _assemble_candidate(chunks: list[tuple[str, str]], order: list[int],
                         max_tokens: int | None) -> tuple[str, int]:
    """Concatenate ``chunks`` in the draw order ``order`` (a list of chunk
    indices) until adding the next chunk would exceed ``max_tokens``.

    Mirrors ``daedalus.eval.harness._bm25_context``: a chunk is never split
    mid-way, and the first chunk drawn is always included even if it alone
    exceeds budget -- an empty candidate is a strictly worse baseline than a
    slightly-over one. Returns ``(text, tokens)``.
    """
    picked: list[int] = []
    total = 0
    for i in order:
        label, text = chunks[i]
        block = f"# ===== {label} =====\n{text}\n"
        t = _harness.count_tokens(block)
        if max_tokens is not None and picked and total + t > max_tokens:
            break
        picked.append(i)
        total += t
    combined = "".join(f"# ===== {chunks[i][0]} =====\n{chunks[i][1]}\n" for i in picked)
    return combined, _harness.count_tokens(combined)


class RandomSearchArm:
    """Baseline (a): uniform random sampling over repository chunks.

    ``name``/``stochastic`` are the ``Arm`` protocol's stable identity fields
    (see ``protocols.Arm``). This arm IS genuinely stochastic -- the
    acceptance matrix tests that directly (same seed -> same result,
    different seeds -> results actually differ) rather than trusting the flag.
    """

    name = "random_search"
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
        try:
            return self._run(task, budget, evaluator, seed)
        except FreezeError:
            raise  # contract violation: never swallowed (protocols.Arm.run)
        except Exception as exc:  # ordinary failure -> an errored outcome
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}")

    def _run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
              seed: int) -> ArmOutcome:
        chunks = _repo_chunks(task.repo_root, planes=_RETRIEVABLE_PLANES)
        if not chunks:
            return ArmOutcome(
                error=f"random_search: no repository chunks found under "
                      f"{task.repo_root!r} to sample from")

        rng = random.Random(seed)
        n = len(chunks)
        n_trials = (budget.max_calls if budget.max_calls is not None
                    else _DEFAULT_TRIALS_WHEN_UNCAPPED)

        best_candidate: str | None = None
        best_score: float | None = None
        best_tokens = 0
        calls_made = 0

        for _ in range(n_trials):
            if budget.max_calls is not None and calls_made >= budget.max_calls:
                break  # R1: never exceed the declared evaluator-call budget
            k = rng.randint(1, n)
            order = rng.sample(range(n), k)
            candidate, tokens = _assemble_candidate(chunks, order, budget.max_tokens)
            if not candidate:
                continue
            score = evaluator.score(candidate, task)
            calls_made += 1
            if best_score is None or score > best_score:
                best_candidate, best_score, best_tokens = candidate, score, tokens

        if best_candidate is None:
            return ArmOutcome(
                error=f"random_search: produced no scorable candidate in "
                      f"{n_trials} trial(s) over {n} chunk(s)")
        return ArmOutcome(
            candidate=best_candidate,
            score=best_score,
            success=True,
            tokens_used=best_tokens,
            notes={"n_trials": calls_made, "n_chunks": n, "seed": seed},
        )
