"""evaluator.py -- Gate-3 freeze obligation #2: evaluator versioning and the
concrete recall scoring function (packet G3-BASE-01).

Plan §4 invariant 4: "Models and embeddings may propose; deterministic or
independently controlled evaluators decide whether evidence is valid." The
evaluator is the truth boundary. A truth boundary whose identity does not
change when its code changes is not one -- that is the entire point of
``evaluator_version``'s ``code_digest``.

Three pieces, matching the packet's ask:

* ``evaluator_version`` -- binds an ``EvaluatorVersion`` to the ACTUAL SOURCE
  of a scoring function (``inspect.getsource``, not the ``version`` string a
  human may forget to bump). Refuses loudly when the source cannot be
  retrieved (REPL-defined lambda, C-implemented callable, ``functools.partial``)
  rather than substituting a placeholder digest, which would make the binding
  cosmetic.
* ``make_recall_evaluator`` -- a factory (one fresh ``SealedEvaluator`` per
  call, matching ``protocols.run_arm_over_tasks``'s ``evaluator_factory``
  contract) that DELEGATES scoring to ``daedalus.eval.harness._recall``. It
  never reimplements recall (plan §5 / packet §2 forbid a second scorer). Gold
  labels are captured in THIS module's closure and handed only to the
  ``SealedEvaluator`` -- never attached to the ``Task`` an arm receives
  (plan §4 invariant 3: a candidate cannot access its evaluator).
* ``vacuous_label_guard`` -- refuses an empty ``must_include`` list before it
  can enter a comparison. ``harness._recall`` returns 1.0 vacuously for an
  empty label list; ``harness._correctness_task_row`` already documents this
  exact trap for a task "graded by running tests, not by slice recall": a task
  that cannot fail must never inflate a go/no-go number with a measurement
  that never happened.

Deterministic, offline, no network, no model calls.
"""
from __future__ import annotations

import hashlib
import inspect
from typing import Callable, Mapping, Sequence

from daedalus.eval import harness

from .contracts import EvaluatorVersion, FreezeError
from .protocols import SealedEvaluator, Task


def _source_digest(scoring_fn: Callable[..., float]) -> str:
    """sha256 hex digest of ``scoring_fn``'s literal source text.

    ``inspect.getsource`` fails -- and is left to fail -- for a callable with
    no retrievable Python source: a lambda/def compiled from a string (the
    REPL case), a C-implemented builtin, or a ``functools.partial`` wrapper.
    Those are refused with a ``FreezeError`` naming the exact reason, never
    silently given a placeholder digest -- a placeholder would sever the very
    binding this function exists to create (plan §4 invariant 4).
    """
    try:
        source = inspect.getsource(scoring_fn)
    except (OSError, TypeError) as exc:
        raise FreezeError(
            f"cannot bind EvaluatorVersion to {scoring_fn!r}: "
            f"inspect.getsource failed ({type(exc).__name__}: {exc}). A "
            "scorer with no retrievable source (REPL-defined, C-implemented, "
            "or a functools.partial) cannot be digest-bound; substituting a "
            "placeholder digest would make the evaluator-identity binding "
            "cosmetic instead of real (plan §4 invariant 4)."
        ) from exc
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def evaluator_version(name: str, version: str,
                       scoring_fn: Callable[..., float]) -> EvaluatorVersion:
    """Bind an ``EvaluatorVersion`` to ``scoring_fn``'s actual source.

    ``code_digest`` changes the instant the scoring function's source text
    changes, whether or not ``version`` was bumped -- that is test A4 and the
    entire reason this function exists rather than a bare
    ``EvaluatorVersion(name, version, "some digest")`` call site.
    """
    return EvaluatorVersion(name=name, version=version,
                             code_digest=_source_digest(scoring_fn))


def vacuous_label_guard(labels: Sequence[str]) -> None:
    """Refuse an empty ``must_include`` list.

    ``harness._recall`` returns ``(1.0, [])`` vacuously when handed an empty
    label list -- a task that cannot fail. ``harness._correctness_task_row``
    already names this trap for correctness tasks; this guard makes the same
    refusal available to any Gate-3 arm/task pairing before it is scored.
    """
    if not labels:
        raise FreezeError(
            "empty must_include list refused: daedalus.eval.harness._recall "
            "returns 1.0 vacuously for an empty label list, which would enter "
            "a task that cannot fail into a baseline comparison -- the exact "
            "trap documented in harness._correctness_task_row "
            "('inflating the go/no-go number with a measurement that never "
            "happened')."
        )


def make_recall_evaluator(
    labels_by_task: Mapping[str, Sequence[str]],
    *, max_calls: int | None = None,
) -> Callable[[], SealedEvaluator]:
    """Return a zero-argument factory producing a FRESH ``SealedEvaluator`` per
    call -- the exact shape ``protocols.run_arm_over_tasks`` requires for its
    ``evaluator_factory`` argument, so call budgets never leak across trials.

    ``labels_by_task`` (task_id -> must_include list) is captured in THIS
    closure. It is read by the returned evaluator's scoring function and by
    nothing else: the ``Task`` object an arm receives (see ``protocols.Task``)
    carries no label field at all, so there is no attribute path from an arm
    to its own answer key (plan §4 invariant 3).

    Every label list is checked with ``vacuous_label_guard`` up front (not
    lazily on first score), so a vacuous task is refused at factory
    construction rather than silently scoring 1.0 partway through a run.

    Scoring DELEGATES to ``daedalus.eval.harness._recall`` -- no second recall
    implementation is written here (plan §5, packet §2).
    """
    labels_by_task = {task_id: tuple(labels)
                       for task_id, labels in labels_by_task.items()}
    for task_id, labels in labels_by_task.items():
        try:
            vacuous_label_guard(labels)
        except FreezeError as exc:
            raise FreezeError(f"task {task_id!r}: {exc}") from exc

    def score_fn(candidate: str, task: Task) -> float:
        try:
            labels = labels_by_task[task.task_id]
        except KeyError as exc:
            raise FreezeError(
                f"no gold labels registered for task {task.task_id!r} -- "
                "an arm was scored against a task make_recall_evaluator was "
                "never told about"
            ) from exc
        recall, _missed = harness._recall(candidate, list(labels))
        return recall

    def factory() -> SealedEvaluator:
        return SealedEvaluator("gate3-recall", score_fn, max_calls=max_calls)

    return factory
