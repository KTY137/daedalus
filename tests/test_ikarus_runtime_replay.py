"""Replay regressions over the canonical runtime event projection."""
from __future__ import annotations
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
import pytest
from daedalus.orchestration.ikarus.runtime_events import (
    RuntimeEventProjection, RuntimeEventProjectionError, RuntimeEventProjector,
    RuntimeToolEvent, RuntimeToolPlanEntry, RuntimeToolProjectionRow,
)
from tests.test_ikarus_runtime_events import _plan, OBS_A, OBS_B, CANCEL



def _started() -> RuntimeEventProjector:
    projector = RuntimeEventProjector(_plan())
    projector.start(plan_entry_id="read-left", call_id="call-left", tool_name="read_file")
    return projector


def _finished(outcome: str = "succeeded") -> RuntimeEventProjector:
    projector = _started()
    projector.finish(call_id="call-left", tool_name="read_file", outcome=outcome,
                     observation_sha256=OBS_A)
    return projector


def _resign(payload: dict) -> dict:
    """An attacker can recompute a plain hash; semantics must still refuse."""
    body = {key: value for key, value in payload.items() if key != "projection_sha256"}
    payload["projection_sha256"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return payload


@pytest.mark.parametrize("status", ["running", "succeeded", "failed"])
def test_rows_cannot_claim_work_without_history(status: str) -> None:
    row = RuntimeToolProjectionRow("task", "read_file", status, "call-task",
                                   None if status == "running" else OBS_A)
    with pytest.raises(RuntimeEventProjectionError, match="history"):
        RuntimeEventProjection((row,), (), False)


def test_empty_projection_cannot_masquerade_as_completed_work() -> None:
    with pytest.raises(RuntimeEventProjectionError, match="empty"):
        RuntimeEventProjection((), (), False)


def test_snapshot_detaches_mutable_lists_and_serialized_output() -> None:
    source = _finished().snapshot()
    rows, events = list(source.rows), list(source.events)
    snapshot = RuntimeEventProjection(rows, events, False)
    before = snapshot.to_dict()
    rows.clear()
    events.clear()
    wire = snapshot.to_dict()
    wire["rows"].clear()
    wire["events"][0]["call_id"] = "tampered"
    assert type(snapshot.rows) is tuple
    assert type(snapshot.events) is tuple
    assert snapshot.to_dict() == before
    assert snapshot.digest == source.digest


@pytest.mark.parametrize("field", ["rows", "events"])
@pytest.mark.parametrize("value", [None, "", {}, set(), 42])
def test_snapshot_requires_ordered_materialized_sequences(field: str, value) -> None:
    snapshot = _started().snapshot()
    with pytest.raises(RuntimeEventProjectionError):
        replace(snapshot, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("status", "failed"),
    ("call_id", "different-call"),
    ("terminal_observation_sha256", OBS_B),
    ("tool_name", "different-tool"),
    ("plan_entry_id", "different-plan"),
])
def test_history_rejects_tampered_completed_row(field: str, value: str) -> None:
    snapshot = _finished().snapshot()
    rows = (replace(snapshot.rows[0], **{field: value}), *snapshot.rows[1:])
    with pytest.raises(RuntimeEventProjectionError):
        replace(snapshot, rows=rows)


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_terminal_history_requires_a_start(outcome: str) -> None:
    event = RuntimeToolEvent(0, "tool_" + outcome, "read-left", "call-left",
                             "read_file", OBS_A)
    with pytest.raises(RuntimeEventProjectionError, match="never started"):
        RuntimeEventProjector.from_events(_plan(), (event,))


@pytest.mark.parametrize("defect", ["duplicate_start", "duplicate_finish", "wrong_plan",
                                   "wrong_tool", "wrong_call", "gap", "reordered"])
def test_replay_refuses_impossible_history(defect: str) -> None:
    events = list(_finished().snapshot().events)
    if defect == "duplicate_start":
        events = [events[0], replace(events[0], sequence=1)]
    elif defect == "duplicate_finish":
        events.append(replace(events[1], sequence=2))
    elif defect == "wrong_plan":
        events[1] = replace(events[1], plan_entry_id="read-right")
    elif defect == "wrong_tool":
        events[1] = replace(events[1], tool_name="run_tests")
    elif defect == "wrong_call":
        events[1] = replace(events[1], call_id="unknown-call")
    elif defect == "gap":
        events[1] = replace(events[1], sequence=3)
    else:
        events.reverse()
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjector.from_events(_plan(), events)


def test_replay_then_continue_equals_uninterrupted_callbacks() -> None:
    original = _started()
    saved = original.snapshot()
    resumed = RuntimeEventProjector.from_projection(_plan(), saved)
    for projector in (original, resumed):
        projector.start(plan_entry_id="read-right", call_id="call-right", tool_name="read_file")
        projector.finish(call_id="call-right", tool_name="read_file", outcome="failed",
                         observation_sha256=OBS_B)
        projector.finish(call_id="call-left", tool_name="read_file", outcome="succeeded",
                         observation_sha256=OBS_A)
        projector.cancel(reason_sha256=CANCEL)
    assert original.snapshot() == resumed.snapshot()
    assert original.snapshot().digest == resumed.snapshot().digest
    assert saved.rows[0].status == "running"
    assert len(saved.events) == 1


@pytest.mark.parametrize("outcome", ["planned", "running", "succeeded", "failed", "cancelled"])
def test_wire_round_trip_preserves_every_lifecycle(outcome: str) -> None:
    if outcome == "planned":
        projector = RuntimeEventProjector(_plan())
    elif outcome == "running":
        projector = _started()
    elif outcome == "cancelled":
        projector = _finished("failed")
        projector.cancel(reason_sha256=CANCEL)
    else:
        projector = _finished(outcome)
    snapshot = projector.snapshot()
    wire = json.loads(json.dumps(snapshot.to_dict()))
    restored = RuntimeEventProjection.from_dict(wire)
    assert restored == snapshot
    assert restored.to_dict() == wire
    assert RuntimeEventProjector.from_projection(_plan(), restored).snapshot() == snapshot


def test_decode_does_not_retain_caller_owned_data() -> None:
    snapshot = _finished().snapshot()
    payload = snapshot.to_dict()
    restored = RuntimeEventProjection.from_dict(payload)
    payload["rows"][0]["status"] = "failed"
    payload["events"].clear()
    assert restored == snapshot


@pytest.mark.parametrize("defect", ["schema", "missing", "extra", "bool", "digest", "rows_type",
                                   "events_type", "row_extra", "event_extra", "row_missing",
                                   "event_missing", "row_item", "event_item"])
def test_decode_rejects_malformed_payload(defect: str) -> None:
    wire = _finished().snapshot().to_dict()
    if defect == "schema":
        wire["schema"] = "daedalus-ikarus-runtime-event-projection/2"
    elif defect == "missing":
        del wire["cancelled"]
    elif defect == "extra":
        wire["authorized"] = True
    elif defect == "bool":
        wire["cancelled"] = 0
    elif defect == "digest":
        wire["projection_sha256"] = OBS_B
    elif defect == "rows_type":
        wire["rows"] = tuple(wire["rows"])
    elif defect == "events_type":
        wire["events"] = None
    elif defect == "row_extra":
        wire["rows"][0]["verified"] = True
    elif defect == "event_extra":
        wire["events"][0]["approved"] = True
    elif defect == "row_missing":
        del wire["rows"][0]["call_id"]
    elif defect == "event_missing":
        del wire["events"][0]["sequence"]
    elif defect == "row_item":
        wire["rows"][0] = None
    else:
        wire["events"][0] = "started"
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjection.from_dict(wire)


@pytest.mark.parametrize("defect", ["without_events", "wrong_digest", "wrong_status", "wrong_plan"])
def test_recomputed_hash_does_not_authorize_false_status(defect: str) -> None:
    payload = _finished().snapshot().to_dict()
    if defect == "without_events":
        payload["events"] = []
    elif defect == "wrong_digest":
        payload["rows"][0]["terminal_observation_sha256"] = OBS_B
    elif defect == "wrong_status":
        payload["rows"][0]["status"] = "failed"
    else:
        payload["events"][1]["plan_entry_id"] = "read-right"
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjection.from_dict(_resign(payload))


@pytest.mark.parametrize("defect", ["omitted", "extra", "reordered", "renamed", "tool_changed"])
def test_recovery_requires_external_exact_plan(defect: str) -> None:
    snapshot = _finished().snapshot()
    plan = list(_plan())
    if defect == "omitted":
        plan.pop()
    elif defect == "extra":
        plan.append(RuntimeToolPlanEntry("extra", "read_file"))
    elif defect == "reordered":
        plan.reverse()
    elif defect == "renamed":
        plan[-1] = RuntimeToolPlanEntry("new-id", "run_tests")
    else:
        plan[-1] = RuntimeToolPlanEntry("verify", "different-tool")
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjector.from_projection(plan, snapshot)


def test_self_consistent_snapshot_cannot_drop_an_unstarted_task_on_recovery() -> None:
    payload = _finished().snapshot().to_dict()
    payload["rows"].pop()  # No event references this not-yet-started task.
    snapshot = RuntimeEventProjection.from_dict(_resign(payload))
    with pytest.raises(RuntimeEventProjectionError, match="declared plan"):
        RuntimeEventProjector.from_projection(_plan(), snapshot)


def test_valid_digest_is_not_authentication_or_task_verification() -> None:
    # Retained limitation: an attacker can forge a fully consistent history.
    # Trusted kernel/CAS provenance MUST be checked outside this value projector.
    payload = _finished().snapshot().to_dict()
    payload["rows"][0]["terminal_observation_sha256"] = OBS_B
    payload["events"][1]["observation_sha256"] = OBS_B
    accepted = RuntimeEventProjection.from_dict(_resign(payload))
    assert accepted.rows[0].terminal_observation_sha256 == OBS_B
    assert "verified" not in accepted.to_dict()
    assert "authorized" not in accepted.to_dict()


@pytest.mark.parametrize("invalid", [None, [], {}, True, 7])
def test_invalid_enum_shapes_raise_domain_error(invalid) -> None:
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeToolEvent(0, invalid)
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeToolProjectionRow("a", "read_file", invalid)
    projector = _started()
    before = projector.snapshot()
    with pytest.raises(RuntimeEventProjectionError):
        projector.finish(call_id="call-left", tool_name="read_file", outcome=invalid,
                         observation_sha256=OBS_A)
    assert projector.snapshot() == before


@pytest.mark.parametrize("sequence", [True, -1, 0.5, "0", None])
def test_event_sequence_is_exact_nonnegative_integer(sequence) -> None:
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeToolEvent(sequence, "tool_started", "read-left", "call-left", "read_file")


def test_cancelled_replay_stays_closed_and_retains_failure() -> None:
    original = _finished("failed")
    original.cancel(reason_sha256=CANCEL)
    restored = RuntimeEventProjector.from_events(_plan(), original.snapshot().events)
    assert [row.status for row in restored.snapshot().rows] == ["failed", "cancelled", "cancelled"]
    with pytest.raises(RuntimeEventProjectionError, match="closed"):
        restored.start(plan_entry_id="verify", call_id="late-call", tool_name="run_tests")
    assert restored.snapshot() == original.snapshot()


@pytest.mark.parametrize("kind", ["tool_started", "tool_succeeded", "run_cancelled"])
def test_no_callback_is_replayed_after_cancellation(kind: str) -> None:
    original = _started()
    original.cancel(reason_sha256=CANCEL)
    events = list(original.snapshot().events)
    if kind == "run_cancelled":
        late = RuntimeToolEvent(2, kind, observation_sha256=CANCEL)
    elif kind == "tool_started":
        late = RuntimeToolEvent(2, kind, "read-right", "call-right", "read_file")
    else:
        late = RuntimeToolEvent(2, kind, "read-left", "call-left", "read_file", OBS_A)
    with pytest.raises(RuntimeEventProjectionError, match="closed"):
        RuntimeEventProjector.from_events(_plan(), [*events, late])


def test_parallel_duplicate_start_has_exactly_one_winner() -> None:
    projector = RuntimeEventProjector(_plan())
    barrier = Barrier(8)
    def start(index: int) -> bool:
        barrier.wait(timeout=10)
        try:
            projector.start(plan_entry_id="read-left", call_id=f"call-{index}", tool_name="read_file")
            return True
        except RuntimeEventProjectionError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(start, range(8)))
    assert sum(results) == 1
    snapshot = projector.snapshot()
    assert len(snapshot.events) == 1
    assert RuntimeEventProjector.from_events(_plan(), snapshot.events).snapshot() == snapshot


def test_finish_cancel_race_has_replayable_state() -> None:
    projector = _started()
    barrier = Barrier(2)
    def finish() -> None:
        barrier.wait(timeout=10)
        try:
            projector.finish(call_id="call-left", tool_name="read_file", outcome="succeeded",
                             observation_sha256=OBS_A)
        except RuntimeEventProjectionError:
            pass  # Cancellation won; late terminal callback is deliberately refused.
    def cancel() -> None:
        barrier.wait(timeout=10)
        projector.cancel(reason_sha256=CANCEL)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish), pool.submit(cancel)]
        for future in futures:
            future.result(timeout=10)
    snapshot = projector.snapshot()
    assert snapshot.cancelled
    assert snapshot.rows[0].status in {"cancelled", "succeeded"}
    assert RuntimeEventProjector.from_events(_plan(), snapshot.events).snapshot() == snapshot


@pytest.mark.parametrize("events", [None, "", {}, set(), ["tool_started"]])
def test_replay_rejects_non_event_sequences(events) -> None:
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjector.from_events(_plan(), events)


@pytest.mark.parametrize("plan", [None, "", {}, set()])
def test_recovery_rejects_unordered_or_absent_plan(plan) -> None:
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjector.from_events(plan, ())


def test_replay_refuses_more_events_than_plan_can_produce() -> None:
    start = _started().snapshot().events[0]
    events = tuple(replace(start, sequence=index) for index in range(8))
    with pytest.raises(RuntimeEventProjectionError, match="event count"):
        RuntimeEventProjector.from_events(_plan(), events)


@pytest.mark.parametrize("payload", [None, [], "{}", 42])
def test_decode_rejects_non_object_payload(payload) -> None:
    with pytest.raises(RuntimeEventProjectionError):
        RuntimeEventProjection.from_dict(payload)


def test_recovery_requires_typed_snapshot_not_a_wire_dictionary() -> None:
    with pytest.raises(RuntimeEventProjectionError, match="exact projection type"):
        RuntimeEventProjector.from_projection(_plan(), _finished().snapshot().to_dict())
