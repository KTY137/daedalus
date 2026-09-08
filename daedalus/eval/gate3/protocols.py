"""protocols.py -- the one shape every Gate-3 baseline arm implements.

Eleven baselines are required (plan §11 Gate 3): Random Search, Best-of-N, a
single-LLM loop, simple local mutation, BM25, embeddings, code-only graph, four
separate indices, evaluator-only selection, archive/MAP-Elites, and a
transparent AlphaEvolve-like proxy. They only mean something if they run under
ONE protocol with ONE budget rule -- eleven arms each with its own harness is
eleven incomparable numbers.

Two families, one protocol:

* RETRIEVAL arms (BM25, embeddings, code-only graph, four separate indices)
  spend their budget assembling context and are scored on what they retrieved.
* SEARCH arms (Random Search, Best-of-N, single-LLM loop, local mutation,
  MAP-Elites, AlphaEvolve proxy) spend their budget proposing candidates and
  are scored on the best candidate found.

Both consume an ``ArmBudget`` and a ``SealedEvaluator`` and emit ``TrialResult``.
``evaluator-only selection`` is the deliberate degenerate case: an arm that does
no retrieval and no search, only asks the evaluator. It exists so a gain can be
attributed to a method rather than to evaluator access.

EXPERIMENT (packet G3-BASE-01), Gate-3 prework while the active gate is 1.
"""
from __future__ import annotations

import copy as _copy
import time
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import ArmBudget, FreezeError, TrialResult

# Backing state for SealedEvaluator, kept OFF the instance so that ordinary
# attribute lookup fails and __getattr__ actually fires. Keyed by id(); a
# weakref.finalize removes the entry when the evaluator is collected, because
# CPython reuses id() values and a stale entry could otherwise be served to a
# brand-new evaluator that happened to land at the same address.
_REGISTRY: dict[int, dict[str, Any]] = {}


@dataclass(frozen=True)
class Task:
    """One unit of work an arm is measured on.

    Deliberately thin. An arm receives the task and the repository root; it does
    NOT receive the gold labels (``must_include`` and friends live with the
    evaluator, not with the arm) -- plan §4 invariant 3: a candidate cannot
    access its evaluator, and handing an arm the answer key is the most direct
    possible violation.
    """

    task_id: str
    repo_root: str
    question: str
    target: str
    label_plane: str = "code"


class SealedEvaluator:
    """The truth boundary (plan §4 invariant 4) as a capability handle.

    An arm gets one capability: ask "how good is this?" and receive a float.
    The scoring function and the gold labels are held in a CLOSURE, not in an
    instance attribute, so there is no ``ev._fn`` / ``ev.labels`` to read and no
    attribute an arm can rebind. Call accounting lives here rather than in the
    arm, because an arm must not be able to under-report how often it consulted
    its grader -- that count is what makes "evaluator access" a budgetable,
    comparable quantity instead of an invisible advantage.

    WHAT THIS DOES NOT DO -- stated plainly, because `AGENTS.md` makes "a hook
    or instruction advertised as a complete security guarantee" a
    release-blocking defect, and the plan itself says no local mechanism is a
    security boundary:

    * This is NOT a sandbox. Same-process Python offers no hard isolation. A
      determined arm can still reach the scorer by walking ``gc.get_objects()``
      or by importing this module and reading ``_REGISTRY``. Nothing here
      prevents that, and claiming otherwise would be the exact defect this
      package exists to detect.
    * It DOES stop the realistic failure: an arm that accidentally or casually
      reads its evaluator, mutates it, or resets its own call count. Those are
      the mistakes that silently corrupt a comparison.
    * Real isolation for an adversarial candidate is the kernel's job
      (capability-bounded execution, plan §4 invariant 3), not this handle's.

    So: a correctness boundary against accident, not a security boundary
    against an adversary.

    IMPLEMENTATION NOTE, recorded because two earlier attempts were cosmetic:
    the state lives in a module-level ``WeakValueDictionary``-style registry
    keyed by ``id(self)``, and the instance has ``__slots__ = ()`` -- it carries
    NO attributes at all. Both earlier versions stored the scorer (v1) or the
    scoring closure (v2) in ``__slots__``, where ordinary attribute lookup
    succeeds and ``__getattr__`` -- which only fires on lookup FAILURE -- never
    ran. ``ev._fn`` and later ``ev._score_impl.__closure__[3].cell_contents``
    both returned the raw scorer. An independent reviewer found v2; the smoke
    test found v1.
    """

    __slots__ = ("__weakref__",)

    def __init__(self, name: str, score_fn: Callable[[str, Task], float],
                 max_calls: int | None = None) -> None:
        calls = [0]

        def _invoke(candidate: str, task: Task) -> float:
            if max_calls is not None and calls[0] >= max_calls:
                raise FreezeError(
                    f"evaluator {name!r} call budget exhausted ({max_calls}); "
                    "an arm may not exceed its declared evaluator access "
                    "(plan §4 invariant 9: hidden budget asymmetry)")
            calls[0] += 1
            return float(score_fn(candidate, task))

        key = id(self)
        _REGISTRY[key] = {"name": name, "invoke": _invoke,
                          "read_calls": lambda: calls[0]}
        weakref.finalize(self, _REGISTRY.pop, key, None)

    def score(self, candidate: str, task: Task) -> float:
        """The ONLY capability an arm has. Counts every call."""
        return _REGISTRY[id(self)]["invoke"](candidate, task)

    @property
    def calls(self) -> int:
        """Read-only. An arm may know its own consumption; it may not reset it."""
        return _REGISTRY[id(self)]["read_calls"]()

    def __getattr__(self, item: str):
        # Dunder lookups must raise AttributeError, not FreezeError: Python
        # probes for optional protocol hooks (__copy__, __reduce__,
        # __deepcopy__, ...) and expects a plain miss. Turning those probes
        # into a contract violation would make the seal break ordinary
        # operations instead of the one thing it exists to stop.
        if item.startswith("__") and item.endswith("__"):
            raise AttributeError(item)
        raise FreezeError(
            f"evaluator attribute {item!r} is sealed: an arm may call .score() "
            "and read .calls, nothing else. Reading the evaluator's internals "
            "would let a candidate see its own grader (plan §4 invariant 3).")

    def __setattr__(self, key: str, value: object) -> None:
        raise FreezeError(
            f"evaluator is immutable to arms; refused write to {key!r} "
            "(plan §4 invariant 3: a candidate cannot modify its evaluator).")

    def __delattr__(self, key: str) -> None:
        raise FreezeError(f"evaluator is immutable to arms; refused delete of {key!r}")

    _NOT_COPYABLE = (
        "a SealedEvaluator is not copyable: a copy would carry its own call "
        "counter, letting an arm reset its evaluator budget by copying. "
        "Build a fresh one per trial instead (see run_arm_over_tasks).")

    def __copy__(self):
        raise FreezeError(self._NOT_COPYABLE)

    def __deepcopy__(self, memo):
        # Distinct signature on purpose: `__deepcopy__ = __copy__` looks tidy
        # but takes the memo dict as a second positional argument and dies with
        # a bare TypeError, so the refusal fired by accident under the wrong
        # exception type. An independent reviewer caught that.
        raise FreezeError(self._NOT_COPYABLE)

    def __reduce__(self):
        raise FreezeError(self._NOT_COPYABLE)

    def __repr__(self) -> str:  # no internals leaked
        entry = _REGISTRY.get(id(self))
        name = entry["name"] if entry else "<dead>"
        calls = entry["read_calls"]() if entry else 0
        return f"<SealedEvaluator {name!r} calls={calls}>"


@runtime_checkable
class Arm(Protocol):
    """What each of the eleven baselines implements.

    ``name`` is the arm id used in ``TrialResult.arm`` and in the manifest's
    budget map, so it must be stable across runs.

    ``stochastic`` decides seed handling: a stochastic arm is run under the full
    ``SeedPolicy`` (>= 5 seeds, plan §14); a deterministic one runs once. An arm
    that lies here understates its own variance, so the acceptance matrix tests
    determinism directly (same seed -> same result) rather than trusting the
    flag.
    """

    name: str
    stochastic: bool

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator,
            seed: int) -> "ArmOutcome":
        """Do the work. Return what was produced and what it cost.

        MUST NOT raise for an ordinary failure -- return an ``ArmOutcome`` with
        ``error`` set. Raising is reserved for a contract violation (a sealed
        evaluator breach, a refused budget split), which should be loud.
        """
        ...


@dataclass(frozen=True)
class ArmOutcome:
    """What an arm produced, before the runner adds timing and bookkeeping.

    Separate from ``TrialResult`` on purpose: the arm reports what it did, the
    runner reports what it cost. An arm cannot write its own wall time or its
    own evaluator call count, so it cannot flatter either.
    """

    candidate: str | None = None
    score: float | None = None
    success: bool | None = None
    tokens_used: int = 0
    human_interventions: int = 0
    error: str | None = None
    notes: Mapping[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            object.__setattr__(self, "notes", {})
        if self.tokens_used < 0:
            raise FreezeError("ArmOutcome.tokens_used cannot be negative")


def run_trial(arm: Arm, task: Task, budget: ArmBudget,
              evaluator: SealedEvaluator, seed: int) -> TrialResult:
    """Run one arm on one task under one seed and produce a ``TrialResult``.

    The runner -- not the arm -- measures wall time and reads the evaluator's
    call count, so neither can be under-reported by an arm that would look
    better with a smaller number.

    Wall time EXCLUDES nothing here except this function's own bookkeeping: the
    clock starts immediately before ``arm.run`` and stops immediately after
    (packet test D3). Index building and other setup belong to the caller and
    are timed separately, because charging one arm for a cache another arm
    warmed is the same starvation defect as splitting a budget.

    A budget overrun is REPORTED (``budget_exceeded=True``), never clipped: an
    arm that needed more than its share is a finding about the arm.
    """
    calls_before = evaluator.calls
    t0 = time.perf_counter()
    try:
        outcome = arm.run(task, budget, evaluator, seed)
    except FreezeError:
        raise  # contract violation: never swallowed
    except Exception as exc:  # ordinary arm failure -> an errored row
        elapsed = time.perf_counter() - t0
        return TrialResult(
            arm=arm.name, task_id=task.task_id, seed=seed,
            wall_seconds=elapsed, tokens_used=0,
            calls=evaluator.calls - calls_before,
            error=f"{type(exc).__name__}: {exc}",
        )
    elapsed = time.perf_counter() - t0
    calls = evaluator.calls - calls_before

    exceeded = False
    if budget.max_tokens is not None and outcome.tokens_used > budget.max_tokens:
        exceeded = True
    if budget.max_wall_seconds is not None and elapsed > budget.max_wall_seconds:
        exceeded = True
    if budget.max_calls is not None and calls > budget.max_calls:
        exceeded = True

    if outcome.error is not None:
        return TrialResult(
            arm=arm.name, task_id=task.task_id, seed=seed,
            wall_seconds=elapsed, tokens_used=outcome.tokens_used, calls=calls,
            budget_exceeded=exceeded, error=outcome.error,
            human_interventions=outcome.human_interventions,
            notes=_copy.deepcopy(dict(outcome.notes)),
        )
    if outcome.success is None:
        raise FreezeError(
            f"arm {arm.name!r} returned neither success nor error for "
            f"{task.task_id!r} -- an unmeasured trial must say so explicitly")
    return TrialResult(
        arm=arm.name, task_id=task.task_id, seed=seed,
        wall_seconds=elapsed, tokens_used=outcome.tokens_used, calls=calls,
        success=outcome.success, score=outcome.score,
        # Carried, not dropped. An earlier version discarded the candidate,
        # which left the diversity measure -- whose whole job is comparing
        # candidates -- nothing to read; it had to fall back to a notes
        # convention most arms do not populate.
        candidate=outcome.candidate,
        budget_exceeded=exceeded,
        human_interventions=outcome.human_interventions,
        notes=_copy.deepcopy(dict(outcome.notes)),
    )


def run_arm_over_tasks(arm: Arm, tasks: Sequence[Task], budget: ArmBudget,
                       evaluator_factory: Callable[[], SealedEvaluator],
                       seeds: Sequence[int]) -> list[TrialResult]:
    """Every (task, seed) for one arm.

    A FRESH evaluator per trial (``evaluator_factory()``): a shared one would
    let call budgets leak across tasks and would let an arm's later trials
    benefit from state its earlier trials created -- a subtle way to give one
    arm more than its declared budget.
    """
    if not seeds:
        raise FreezeError(f"arm {arm.name!r} was given no seeds to run under")
    out: list[TrialResult] = []
    for task in tasks:
        for seed in seeds:
            out.append(run_trial(arm, task, budget, evaluator_factory(), seed))
    return out
