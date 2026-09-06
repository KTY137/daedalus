"""map_elites.py -- Archive / MAP-Elites baseline arm (plan §11 Gate 3, arm C10).

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1. This
module produces no Gate-3 baseline evidence until the harness is sealed by the
owner (`daedalus/eval/gate3/contracts.py`: `RunManifest.sealed`).

DEPENDENCY DECISION: the master plan (§9.2) names ``pyribs`` as a PRIOR, not a
commitment, and it is NOT an installed dependency of this project (checked
against `pyproject.toml`/`uv.lock`; no match). Adding it here would violate the
packet's "touch only your two files" boundary (it is forbidden from editing
`pyproject.toml`) and the global rule against adding a dependency without a
measured, net-positive reason. This module is therefore a small,
self-contained MAP-Elites implementation with no new dependency.

WHAT MAP-ELITES MEANS HERE, MADE EXPLICIT (the plan calls unfalsifiable
"diversity" claims out by name -- G3-BASE-01 §3, rule R3/D7):

* A candidate is a whitespace-joined string built from a per-task vocabulary
  (the task's question and target text, plus a small fixed padding
  vocabulary so tiny tasks still have enough raw material to mutate).
* BEHAVIOUR DESCRIPTOR (2-D, declared, not incidental):
    dim 1 -- ``len(candidate)`` in characters, binned into
             ``LENGTH_BINS`` bins of width ``LENGTH_BIN_WIDTH``, clamped to
             the last bin above range;
    dim 2 -- number of UNIQUE words in the candidate, binned into
             ``UNIQUE_WORD_BINS`` bins of width ``UNIQUE_WORD_BIN_WIDTH``,
             clamped likewise.
  These two are chosen because they are computable from the candidate alone
  (never from the evaluator's verdict -- a descriptor derived from the score
  would collapse "behaviour" into "quality" and make the archive just a
  second scoreboard), and because mutation (insert/delete/swap/replace a
  word) visibly moves a candidate along both axes.
* ARCHIVE DIMENSIONS: ``ARCHIVE_DIMS = (LENGTH_BINS, UNIQUE_WORD_BINS)``.
  ``CELL_COUNT = LENGTH_BINS * UNIQUE_WORD_BINS`` (64 at the module defaults).
* COVERAGE (feeds measure D7, diversity): ``Archive.coverage`` is
  ``len(filled cells) / CELL_COUNT``, computed from the actual archive
  dict every time it is read -- never a constant and never structurally
  guaranteed to be non-zero. `docs/GATE2_FOREST_V2_TRIAGE.md:107` records the
  defect this guards against: a counter that could not have been zero is not
  a measurement. An arm that never gets a single successful evaluation
  reports ``coverage == 0.0`` truthfully via ``error=...`` (no archive built).

BUDGET RULE R1, MADE EXPLICIT: this arm receives the FULL declared
``ArmBudget`` and never calls ``budget.split()``. Iterations are bounded by
whichever of ``budget.max_calls`` / ``budget.max_wall_seconds`` is tightest
(see ``_resolve_iterations``); each iteration spends exactly one evaluator
call. Spreading that one shared iteration budget across many archive cells
OVER TIME is not a budget split in the R1 sense: R1 forbids dividing the
budget's total SIZE across an arm's internal components up front (the exact
s08 defect -- four indices each starved to a quarter of one shared hit
budget, `daedalus/eval/gate3/contracts.py` `ArmBudget.split`). Here every
iteration still competes for the one full, undivided budget; which cell a
given iteration's candidate happens to land in is an outcome of the search,
not a pre-allocated share. No cell is ever promised, reserved, or capped at
a fraction of the budget.

DETERMINISM: a private ``random.Random(seed)`` drives every random choice.
The module never touches the global ``random`` module, so two arms (or two
trials) running under different seeds cannot perturb each other via shared
global state, and the same seed reproduces the same archive bit-for-bit.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

from ..contracts import ArmBudget, FreezeError
from ..protocols import ArmOutcome, SealedEvaluator, Task

# --------------------------------------------------------------------------- #
# behaviour descriptor + archive                                              #
# --------------------------------------------------------------------------- #
LENGTH_BIN_WIDTH = 8
LENGTH_BINS = 8
UNIQUE_WORD_BIN_WIDTH = 2
UNIQUE_WORD_BINS = 8
ARCHIVE_DIMS = (LENGTH_BINS, UNIQUE_WORD_BINS)
CELL_COUNT = LENGTH_BINS * UNIQUE_WORD_BINS

# Used only when the caller's ArmBudget declares no max_calls and the arm was
# not constructed with an explicit max_iterations -- a last-resort finite
# bound so the arm cannot loop unboundedly. Any real comparison freezes
# max_calls in its ArmBudget (packet §5b, R1); this default never overrides
# a declared budget.
DEFAULT_MAX_ITERATIONS = 200

_PADDING_VOCAB = (
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
)


def behaviour_descriptor(candidate: str) -> tuple[int, int]:
    """Map a candidate string to its archive cell. See module docstring."""
    words = candidate.split()
    length_bin = min(len(candidate) // LENGTH_BIN_WIDTH, LENGTH_BINS - 1)
    unique_bin = min(len(set(words)) // UNIQUE_WORD_BIN_WIDTH, UNIQUE_WORD_BINS - 1)
    return (length_bin, unique_bin)


@dataclass(frozen=True)
class _Elite:
    candidate: str
    score: float


class Archive:
    """Cell -> best-elite map.

    Insertion is STRICTLY elitist: a cell's occupant is replaced only when the
    challenger's score is strictly greater. Equal-score challengers keep the
    incumbent, so a run of tied noise cannot silently rewrite the archive, and
    an occupant is NEVER replaced by a worse candidate -- this is asserted
    directly against this class in the test suite, independent of any run.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple[int, int], _Elite] = {}

    def try_insert(self, cell: tuple[int, int], candidate: str, score: float) -> bool:
        current = self._cells.get(cell)
        if current is None or score > current.score:
            self._cells[cell] = _Elite(candidate=candidate, score=score)
            return True
        return False

    def get(self, cell: tuple[int, int]) -> _Elite | None:
        return self._cells.get(cell)

    def __len__(self) -> int:
        return len(self._cells)

    def elites(self) -> list[_Elite]:
        return list(self._cells.values())

    @property
    def coverage(self) -> float:
        """MEASURED filled/total, computed from the live dict every call --
        never a constant, never assumed nonzero (see module docstring)."""
        return len(self._cells) / CELL_COUNT

    def best(self) -> _Elite | None:
        if not self._cells:
            return None
        return max(self._cells.values(), key=lambda e: e.score)


# --------------------------------------------------------------------------- #
# candidate generation                                                        #
# --------------------------------------------------------------------------- #
def _vocabulary(task: Task) -> list[str]:
    words: set[str] = set()
    for text in (task.question, task.target):
        for raw in text.split():
            w = raw.strip(".,!?;:\"'()[]{}")
            if w:
                words.add(w)
    words.update(_PADDING_VOCAB)
    return sorted(words)


def _seed_candidate(rng: random.Random, vocab: list[str]) -> str:
    n = rng.randint(1, 5)
    return " ".join(rng.choice(vocab) for _ in range(n))


def _mutate(rng: random.Random, candidate: str, vocab: list[str]) -> str:
    words = candidate.split() or [rng.choice(vocab)]
    ops = ["insert", "replace"]
    if len(words) > 1:
        ops += ["delete", "swap"]
    op = rng.choice(ops)
    if op == "insert":
        words.insert(rng.randint(0, len(words)), rng.choice(vocab))
    elif op == "delete":
        del words[rng.randrange(len(words))]
    elif op == "swap":
        i, j = rng.sample(range(len(words)), 2)
        words[i], words[j] = words[j], words[i]
    else:  # replace
        words[rng.randrange(len(words))] = rng.choice(vocab)
    return " ".join(words)


# --------------------------------------------------------------------------- #
# the arm                                                                     #
# --------------------------------------------------------------------------- #
class MapElitesArm:
    """Archive / MAP-Elites baseline (plan §11 Gate 3, arm C10).

    Each iteration selects a random elite from the archive (or seeds one from
    scratch when the archive is empty), mutates it, spends exactly one
    evaluator call, and inserts the result into its behaviour cell if it beats
    that cell's current occupant (see ``Archive.try_insert``). The returned
    ``ArmOutcome`` reports the single best candidate found across the whole
    archive, and ``notes`` carries the declared descriptor, dimensions, cell
    count and the measured final coverage -- see module docstring for what
    each of those means and why.
    """

    name = "map_elites"
    stochastic = True

    def __init__(self, success_threshold: float = 0.0,
                 max_iterations: int | None = None) -> None:
        self._success_threshold = success_threshold
        self._max_iterations = max_iterations

    def _resolve_iterations(self, budget: ArmBudget) -> int:
        caps = []
        if budget.max_calls is not None:
            caps.append(budget.max_calls)
        if self._max_iterations is not None:
            caps.append(self._max_iterations)
        if not caps:
            caps.append(DEFAULT_MAX_ITERATIONS)
        return min(caps)

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> ArmOutcome:
        rng = random.Random(seed)  # private RNG -- never global random
        vocab = _vocabulary(task)
        archive = Archive()
        max_iterations = self._resolve_iterations(budget)

        t0 = time.perf_counter()
        tokens_used = 0
        evaluations = 0
        try:
            for _ in range(max_iterations):
                if (budget.max_wall_seconds is not None
                        and time.perf_counter() - t0 >= budget.max_wall_seconds):
                    break
                elites = archive.elites()
                if elites:
                    parent = rng.choice(elites)
                    candidate = _mutate(rng, parent.candidate, vocab)
                else:
                    candidate = _seed_candidate(rng, vocab)

                score = evaluator.score(candidate, task)
                evaluations += 1
                tokens_used += len(candidate.split())
                archive.try_insert(behaviour_descriptor(candidate), candidate, score)

                if budget.max_calls is not None and evaluator.calls >= budget.max_calls:
                    break
        except FreezeError:
            raise  # contract violation -- never swallowed (protocols.py precedent)
        except Exception as exc:  # ordinary arm failure -> an errored outcome
            return ArmOutcome(error=f"{type(exc).__name__}: {exc}",
                               tokens_used=tokens_used)

        best = archive.best()
        if best is None:
            return ArmOutcome(
                error="map_elites completed zero evaluations "
                      "(budget too small to run even one iteration)",
                tokens_used=tokens_used,
            )

        return ArmOutcome(
            candidate=best.candidate,
            score=best.score,
            success=best.score > self._success_threshold,
            tokens_used=tokens_used,
            notes={
                "behaviour_descriptor": (
                    "(len(candidate) chars, count(unique words in candidate))"
                ),
                "archive_dims": ARCHIVE_DIMS,
                "cell_count": CELL_COUNT,
                "cells_filled": len(archive),
                "coverage": archive.coverage,
                "evaluations": evaluations,
            },
        )
