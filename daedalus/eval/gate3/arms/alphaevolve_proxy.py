"""alphaevolve_proxy.py -- baseline C11: a TRANSPARENT AlphaEvolve-like proxy.

Plan §11 Gate 3, sentence 2 requires "a transparent AlphaEvolve-like proxy"
among the eleven frozen baselines. Plan §11 Gate 5 is explicit about the limit
on what such a proxy may ever support:

    AlphaEvolve is closed, so a broad framework comparison is not
    scientifically available. "Beats AlphaEvolve" is permitted only for
    directly comparable public artifact scores under budget-equal
    measurements; otherwise state the narrower proxy/task result.

"Transparent" is made a TESTABLE ARTIFACT here, not a docstring promise: see
``PROXY_DECLARATION`` below and ``tests/eval/gate3/test_arm_alphaevolve_proxy.py::
test_arm_alphaevolve_proxy_is_transparent``. Every reader of a result row from
this arm can load the declaration and see, in structured form, exactly what
was and was not reproduced, without trusting prose.

WHAT THIS ARM ACTUALLY IS: a small, self-contained genetic-programming-style
search loop over token-sequence "candidates" -- population, mutation,
recombination, evaluator-scored selection, elite retention across
generations. That loop is a real and common structural analogue of published
AlphaEvolve-style evolutionary coding systems. It is NOT a reimplementation of
AlphaEvolve's actual generation, evaluation, or distribution mechanics, which
are not public in reproducible detail (hence "proxy").

MODEL-FREE BY DESIGN, NOT BY OMISSION: this packet does not wire an optional
LLM mutation operator. AlphaEvolve's real operator is an LLM; the honest proxy
choice was either (a) fake an LLM call behind a flag that is never exercised
by any test, which is exactly the "temporary production path" AGENTS.md
forbids, or (b) be explicit that the mutation/recombination operator here is
a deterministic stand-in and that no LLM path exists in this packet's scope.
This module takes (b). A future packet may add a real provider-backed
operator as reviewed, tested work; until then, claiming one exists here would
itself be a transparency defect of the kind this baseline exists to avoid.

BUDGET RULE (R1, packet G3-BASE-01 §3): the arm receives ONE ``ArmBudget`` and
never calls ``ArmBudget.split()``. The budget is not divided into fixed
per-population-member shares up front. Instead every generation draws from the
SAME shared ``evaluator.calls`` counter and the same wall-clock budget, so the
number of generations that actually run is whatever the shared budget affords
-- a slow evaluator or an unlucky early generation naturally leaves fewer
calls for later generations, exactly like a real search budget, rather than
each of (population_size) candidates being pre-allocated budget/population_size
calls it may not need. This is the distinction the s08 defect
(``docs/GATE2_FOREST_V2_TRIAGE.md``) violated for a *composite* arm splitting
across sibling indices; here the split-that-must-not-happen is across
*generations* of ONE arm, and the fix is the same: never divide, let
consumption happen over time against one shared counter.

EVALUATOR ACCESS: exactly the ``SealedEvaluator`` capability -- ``.score()``
and read-only ``.calls`` -- nothing else is read or held.

DETERMINISM: all randomness is drawn from a single ``random.Random(seed)``
built inside ``run()``; the module never calls the ``random`` module's global
functions, so two arms running concurrently under different seeds cannot
observe or perturb each other's sequence.

SUCCESS CONVENTION: ``ArmOutcome.success`` is defined here as
``best_score > 0.0``. This is a DECLARED threshold, not something derived from
task semantics (the arm never sees gold labels), and a caller comparing raw
``score`` across arms should read ``score`` directly rather than relying on
``success`` alone when evaluator scales differ.
"""
from __future__ import annotations

import random
import time
from typing import Sequence

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

#: The transparency artifact. Machine-readable on purpose (dict, not prose) so
#: a test can assert its shape and content rather than trust a comment.
#: Every value is a non-empty tuple of strings; ``may_not_claim`` MUST mention
#: the "beats AlphaEvolve" restriction verbatim (plan §11 Gate 5).
PROXY_DECLARATION: dict[str, tuple[str, ...]] = {
    "mechanisms_reproduced": (
        "A population of candidate solutions maintained across generations.",
        "A mutation operator that perturbs a candidate (token swap, insert, "
        "delete, replace) as a stand-in for an LLM-driven code edit.",
        "A recombination/crossover operator that splices two elite parents.",
        "Evaluator-scored selection: every candidate is scored once through "
        "the same SealedEvaluator capability every other arm uses.",
        "Elite retention across generations (the top-K scorers of one "
        "generation survive unmutated into the next, so best-so-far is "
        "monotone non-decreasing by construction).",
        "A single shared execution budget consumed over time across "
        "generations, never split into fixed per-member shares (rule R1).",
    ),
    "mechanisms_not_reproduced": (
        "No LLM-driven mutation or recombination operator -- AlphaEvolve's "
        "published operator is an LLM; this proxy's operator is a "
        "deterministic, model-free text perturbation, by explicit design "
        "choice (see module docstring), not by an unadvertised placeholder.",
        "No island-model / multi-population distributed evolution.",
        "No automated prompt evolution or meta-learning over its own "
        "operator.",
        "No code-execution-based fitness (candidates here are opaque "
        "strings scored by an arbitrary SealedEvaluator, not compiled or "
        "run programs).",
        "No multi-objective Pareto archive (that mechanism is baseline C10, "
        "archive/MAP-Elites, and is deliberately kept separate rather than "
        "folded into this arm).",
        "No reproduction of AlphaEvolve's actual published task suite, "
        "compute scale, or reported results -- those are not independently "
        "reproducible from the public description.",
    ),
    "may_not_claim": (
        "No result produced by this arm may be used to support a 'beats "
        "AlphaEvolve' comparative claim. AlphaEvolve is closed (plan §11 "
        "Gate 5); this is a declared proxy, not a replication, and its "
        "numbers are only ever comparable to the OTHER ten frozen baselines "
        "in this same harness under the same budget -- never to any "
        "published AlphaEvolve figure.",
        "This arm's output is not Gate-3 baseline evidence until an owner "
        "seals the harness (plan §11 Gate 3; see RunManifest.sealed).",
        "A win against this proxy is not evidence of beating evolutionary "
        "program search in general -- only evidence against this one "
        "declared, model-free, single-population instantiation of it.",
    ),
}


def _non_empty(mapping: dict[str, tuple[str, ...]]) -> bool:
    return all(isinstance(v, tuple) and len(v) > 0 and all(v) for v in mapping.values())


assert _non_empty(PROXY_DECLARATION), "PROXY_DECLARATION must be fully populated"


class AlphaEvolveProxyArm:
    """Baseline C11. See module docstring and ``PROXY_DECLARATION``."""

    name = "alphaevolve_proxy"
    stochastic = True

    POPULATION_SIZE = 6
    ELITE_COUNT = 2
    #: Hard proxy safety cap so an uncapped ``ArmBudget`` (max_calls=None)
    #: cannot spin forever; a capped budget will usually stop first via
    #: ``evaluator.calls``.
    MAX_GENERATIONS = 25

    # -- vocabulary / genome ------------------------------------------------
    def _vocabulary(self, task: Task) -> list[str]:
        """The token alphabet mutation/crossover draw from.

        Built ONLY from ``task.question``/``task.target``/``task.task_id`` --
        fields the arm is entitled to on the ``Task`` it was handed (plan §4
        invariant 3: an arm never reads its evaluator's gold labels).
        """
        vocab = task.question.split()
        if not vocab and task.target:
            vocab = task.target.split()
        if not vocab:
            vocab = [task.task_id or "candidate"]
        return vocab

    def _seed_candidate(self, vocab: Sequence[str], rng: random.Random) -> str:
        k = rng.randint(1, min(5, len(vocab)))
        start = rng.randint(0, len(vocab) - k)
        chosen = list(vocab[start:start + k])
        rng.shuffle(chosen)
        return " ".join(chosen)

    def _mutate(self, candidate: str, vocab: Sequence[str], rng: random.Random) -> str:
        tokens = candidate.split() or [rng.choice(vocab)]
        op = rng.choice(("swap", "insert", "delete", "replace"))
        if op == "swap" and len(tokens) >= 2:
            i, j = rng.sample(range(len(tokens)), 2)
            tokens[i], tokens[j] = tokens[j], tokens[i]
        elif op == "insert":
            tokens.insert(rng.randint(0, len(tokens)), rng.choice(vocab))
        elif op == "delete" and len(tokens) > 1:
            tokens.pop(rng.randrange(len(tokens)))
        elif op == "replace":
            tokens[rng.randrange(len(tokens))] = rng.choice(vocab)
        else:
            # chosen op was inapplicable (e.g. "swap" on a 1-token candidate)
            # -- a mutation must still do something observable.
            tokens.append(rng.choice(vocab))
        return " ".join(tokens)

    def _crossover(self, parent_a: str, parent_b: str, rng: random.Random) -> str:
        a = parent_a.split() or [parent_a]
        b = parent_b.split() or [parent_b]
        cut_a = rng.randint(0, len(a))
        cut_b = rng.randint(0, len(b))
        child = a[:cut_a] + b[cut_b:]
        if not child:
            child = [rng.choice(a + b)]
        return " ".join(child)

    def _next_generation(self, elites: Sequence[str], vocab: Sequence[str],
                          rng: random.Random) -> list[str]:
        # Elitism: elites survive unmutated -- this is what makes best-so-far
        # monotone non-decreasing without needing to remember prior generations.
        children: list[str] = list(elites)
        while len(children) < self.POPULATION_SIZE:
            if len(elites) >= 2 and rng.random() < 0.5:
                parent_a, parent_b = rng.sample(list(elites), 2)
                children.append(self._crossover(parent_a, parent_b, rng))
            else:
                parent = rng.choice(list(elites))
                children.append(self._mutate(parent, vocab, rng))
        return children

    def _diversity(self, population: Sequence[str]) -> float:
        """Declared diversity measure: fraction of the final population that
        is lexically unique. A simple, stated definition (plan §11 Gate 3
        expects one, with limitations noted) -- it says nothing about
        semantic diversity between distinct-but-similar candidates."""
        if not population:
            return 0.0
        return len(set(population)) / len(population)

    # -- the loop -------------------------------------------------------- #
    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        rng = random.Random(seed)
        vocab = self._vocabulary(task)
        max_calls = budget.max_calls
        max_wall = budget.max_wall_seconds
        started = time.perf_counter()

        population = [self._seed_candidate(vocab, rng)
                      for _ in range(self.POPULATION_SIZE)]
        best_candidate: str | None = None
        best_score = float("-inf")
        best_so_far_history: list[float] = []
        tokens_used = 0
        generation = 0

        def budget_exhausted() -> bool:
            if max_calls is not None and evaluator.calls >= max_calls:
                return True
            if max_wall is not None and (time.perf_counter() - started) >= max_wall:
                return True
            return False

        while generation < self.MAX_GENERATIONS and not budget_exhausted():
            scored: list[tuple[float, str]] = []
            for candidate in population:
                if budget_exhausted():
                    break
                try:
                    score = evaluator.score(candidate, task)
                except FreezeError:
                    raise  # contract violation: never swallowed (packet E1)
                except Exception as exc:  # ordinary failure -> ArmOutcome(error=...)
                    return ArmOutcome(
                        error=f"{type(exc).__name__}: {exc}",
                        tokens_used=tokens_used,
                        notes={
                            "generations_run": generation,
                            "failed_at_candidate": candidate,
                        },
                    )
                tokens_used += len(candidate.split())
                scored.append((float(score), candidate))

            if not scored:
                break  # no budget left to evaluate anything this generation

            scored.sort(key=lambda pair: pair[0], reverse=True)
            gen_best_score, gen_best_candidate = scored[0]
            if best_candidate is None or gen_best_score > best_score:
                best_score = gen_best_score
                best_candidate = gen_best_candidate
            best_so_far_history.append(best_score)

            elites = [c for _, c in scored[:self.ELITE_COUNT]] or [gen_best_candidate]
            population = self._next_generation(elites, vocab, rng)
            generation += 1

        if best_candidate is None:
            return ArmOutcome(
                error="alphaevolve_proxy: exhausted budget before any "
                      "evaluator call could complete",
                tokens_used=tokens_used,
                notes={"generations_run": generation},
            )

        diversity = self._diversity(population)
        return ArmOutcome(
            candidate=best_candidate,
            score=best_score,
            success=best_score > 0.0,
            tokens_used=tokens_used,
            notes={
                "generations_run": generation,
                "final_population_diversity": diversity,
                "best_so_far_history": tuple(best_so_far_history),
                "population_size": self.POPULATION_SIZE,
                "elite_count": self.ELITE_COUNT,
                "budget_note": (
                    "full ArmBudget consumed across generations over time; "
                    "never split into per-member shares (rule R1)"
                ),
                "proxy_declaration_ref":
                    "daedalus.eval.gate3.arms.alphaevolve_proxy.PROXY_DECLARATION",
            },
        )
