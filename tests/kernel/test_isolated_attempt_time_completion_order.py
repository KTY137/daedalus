"""Council CHECK (c): measure the clock's completion-order window, do not deny it.

``AttemptLifecycleClock.now`` allocates its timestamp inside ``_lock`` and
returns after releasing it. Allocation order is therefore strictly increasing
and unique, but *completion* order -- the order in which concurrent ``now()``
calls actually return to their callers -- is not synchronized with allocation.
The first test builds the council's harness (a controlled lock that parks the
first caller after release and lets the second overtake it) and proves the
window exists: timestamps CAN arrive at their consumers out of order, while the
allocated values themselves stay unambiguous. This is a documenting test; any
consumer that needs ordering must order by the allocated value, never by
call-return order.

The second test measures the council's other open point: a ``begin()`` refused
at the ``started_at > created_ts`` inversion has already persisted its intent
row, so the refusal is durable, receipt-free, and -- because the single-start
index retains the poisoned row -- permanent for that attempt id.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempt_clock import AttemptLifecycleClock
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptStateError,
    IsolatedAttemptCoordinator,
)
from daedalus.schemas import AttemptContract, ContractProvenance, ResourceBudget

REVISION = "a" * 40
FIXTURE_TIME = "2026-08-03T22:00:00+00:00"
FUTURE = "2099-01-01T00:00:00+00:00"
TASK_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
POLICY_SHA = "3" * 64
_WAIT_SECONDS = 10.0


class _OvertakingLock:
    """The council's harness: park the first releaser until the second returns.

    ``__enter__`` takes the real lock, so allocation stays serialized exactly as
    in production. ``__exit__`` releases the real lock first (no deadlock) and
    then parks the FIRST caller until the second caller has completely finished
    its ``now()`` call -- which forces the completion order to invert relative
    to the allocation order.
    """

    def __init__(self, inner: threading.Lock) -> None:
        self._inner = inner
        self._meta = threading.Lock()
        self._exits = 0
        self.first_allocated = threading.Event()
        self.second_completed = threading.Event()

    def __enter__(self) -> "_OvertakingLock":
        self._inner.acquire()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._inner.release()
        with self._meta:
            self._exits += 1
            position = self._exits
        if position == 1:
            self.first_allocated.set()
            assert self.second_completed.wait(_WAIT_SECONDS), (
                "harness stalled: the second caller never completed"
            )
        return False


def test_completion_order_can_invert_while_allocation_stays_unambiguous() -> None:
    clock = AttemptLifecycleClock()
    control = _OvertakingLock(clock._lock)
    clock._lock = control  # type: ignore[assignment]

    completion_order: list[tuple[str, str]] = []
    failures: list[BaseException] = []

    def first_caller() -> None:
        try:
            stamp = clock.now()
            completion_order.append(("first", stamp))
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)

    def second_caller() -> None:
        try:
            assert control.first_allocated.wait(_WAIT_SECONDS)
            stamp = clock.now()
            completion_order.append(("second", stamp))
        except BaseException as exc:  # pragma: no cover - surfaced via failures
            failures.append(exc)
        finally:
            control.second_completed.set()

    threads = [
        threading.Thread(target=first_caller, name="clock-first"),
        threading.Thread(target=second_caller, name="clock-second"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_WAIT_SECONDS)
        assert not thread.is_alive(), "harness deadlocked"
    assert failures == []

    callers = [name for name, _ in completion_order]
    stamps_in_completion_order = [stamp for _, stamp in completion_order]
    allocated_first = dict(completion_order)["first"]
    allocated_second = dict(completion_order)["second"]

    # Allocation order is unambiguous: the first caller allocated the strictly
    # smaller stamp, and the two stamps are distinct. Anyone ordering by the
    # allocated value reconstructs the true sequence.
    assert allocated_first < allocated_second

    # Completion order inverted: the second caller returned first, so a
    # consumer recording stamps in call-return order observed a DECREASING
    # sequence. This is the documented window, not a defect of the clock: the
    # clock promises nondecreasing *allocation*, and makes no promise about the
    # order in which concurrent callers get to look at their result.
    assert callers == ["second", "first"]
    assert stamps_in_completion_order == sorted(stamps_in_completion_order, reverse=True)
    assert stamps_in_completion_order[0] > stamps_in_completion_order[1]


def _environment(tmp_path: Path):
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "work.py").write_text("value = 1\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")
    captured = store.capture_tree(
        primary,
        tree_id="input-clock-window",
        source_revision=REVISION,
        origin="tests.attempt-clock-window-input",
        created_at=FIXTURE_TIME,
    )
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    # Gate-0 admission requires the deployment-owned workspace root to already
    # exist; provision it here instead of extending the legacy conftest list.
    (tmp_path / "workspaces").mkdir(exist_ok=True)
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=tmp_path / "workspaces",
        source_store=store,
        ledger=ledger,
    )
    attempt = AttemptContract(
        attempt_id="attempt-clock-window",
        mission_id="mission-clock-window",
        task_id="task-clock-window",
        instruction="Operate only in the isolated workspace.",
        base_revision=REVISION,
        task_sha256=TASK_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        policy_decision_sha256=POLICY_SHA,
        budget=ResourceBudget(max_wall_time_s=30),
        provenance=ContractProvenance(
            origin="tests.attempt-clock-window",
            source_revision=REVISION,
            created_at=FIXTURE_TIME,
            input_digests=(POLICY_SHA, RUNTIME_SHA, TASK_SHA),
        ),
        writable_paths=("work.py",),
        gate_names=("pytest",),
    )
    return store, captured, ledger, coordinator, attempt


def test_begin_refused_at_time_inversion_leaves_a_durable_receipt_free_intent(
    tmp_path: Path,
) -> None:
    """Measured: the inversion refusal is durable, receipt-free, and permanent.

    ``begin()`` takes its trusted start time BEFORE it records the intent, and
    the ``started_at > created_ts`` guard runs on the decoded row AFTER the
    record is durable. A refusal at that guard therefore does not roll the row
    back. What this measures, and what it means:

    * exactly one ``attempt.lifecycle`` intent row remains -- the refused start
      is retained as inspectable evidence (the provenance invariant), it is not
      silently deleted;
    * its only lifecycle event is ``INTENDED`` -- no terminal receipt was
      invented for a start the guard refused, mirroring the broker's
      started-unreconciled discipline;
    * every later ``begin()`` for the same attempt id re-reads the poisoned row
      and fails closed with the same refusal, even under a fresh, healthy
      clock. The single-start slot is durably consumed: a refused-at-inversion
      attempt id can never be restarted and recovery requires a new attempt id.

    That last point is the sharp edge this test documents: the refusal is not
    effect-free. Nothing here proves an invariant violation -- retention plus
    fail-closed replay is the constitution's own discipline -- so there is no
    xfail; the assertions pin the measured behavior so any future change to it
    is a conscious one.
    """

    store, captured, ledger, coordinator, attempt = _environment(tmp_path)

    # Poison the trusted clock the way a persisted future minimum would after a
    # host wall-clock rollback: the next allocation lands beyond the wall time
    # the Event Store will stamp on the row.
    ledger._clock.now(minimum=FUTURE)

    with pytest.raises(AttemptStateError, match="follows its Event-Store start event"):
        coordinator.prepare(attempt, captured, start_id="start-clock-window")

    with sqlite3.connect(ledger.path) as connection:
        intents = connection.execute(
            "SELECT id, payload FROM intents WHERE kind = 'attempt.lifecycle'"
        ).fetchall()
        assert len(intents) == 1, "the refused begin left exactly one intent row"
        events = connection.execute(
            "SELECT state FROM intent_events WHERE intent_id = ?",
            (intents[0][0],),
        ).fetchall()
    assert [row[0] for row in events] == ["INTENDED"]
    assert FUTURE.replace("+00:00", "") in intents[0][1] or "2099" in intents[0][1]

    # A retry on the same ledger fails closed on the persisted row. Measured
    # nuance: the retry is refused by a DIFFERENT guard layer than the first
    # call -- the reader-side record check ("... follows its Event-Store
    # transition") instead of the decoder ("... follows its Event-Store start
    # event") -- so the wedge holds even if one of the two layers regressed.
    with pytest.raises(AttemptStateError, match="follows its Event-Store"):
        coordinator.prepare(attempt, captured, start_id="start-clock-window")

    # So does a completely fresh ledger with a healthy clock over the same
    # spine: the wedge is durable, not a property of the poisoned process.
    fresh = AttemptLedger(ledger.spine, store)
    assert fresh._clock is not ledger._clock
    with pytest.raises(AttemptStateError, match="follows its Event-Store"):
        fresh.begin(
            attempt,
            captured,
            start_id="start-clock-window",
            workspace_parent_sha256="4" * 64,
            workspace_relative_path="attempts/attempt-clock-window",
        )
