from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus_runtime_events import (
    RUNTIME_EVENT_PROJECTION_SCHEMA,
    RuntimeEventProjectionError,
    RuntimeEventProjector,
    RuntimeToolPlanEntry,
)


OBS_A = "a" * 64
OBS_B = "b" * 64
CANCEL = "c" * 64


def _plan() -> tuple[RuntimeToolPlanEntry, ...]:
    return (
        RuntimeToolPlanEntry("read-left", "read_file"),
        RuntimeToolPlanEntry("read-right", "read_file"),
        RuntimeToolPlanEntry("verify", "run_tests"),
    )


def test_parallel_same_name_calls_correlate_by_call_id() -> None:
    projector = RuntimeEventProjector(_plan())
    projector.start(
        plan_entry_id="read-left",
        call_id="call-left",
        tool_name="read_file",
    )
    projector.start(
        plan_entry_id="read-right",
        call_id="call-right",
        tool_name="read_file",
    )

    # Terminal callbacks arrive in the opposite order. The tool name is
    # intentionally identical, so only exact call identity can correlate them.
    projector.finish(
        call_id="call-right",
        tool_name="read_file",
        outcome="failed",
        observation_sha256=OBS_B,
    )
    projector.finish(
        call_id="call-left",
        tool_name="read_file",
        outcome="succeeded",
        observation_sha256=OBS_A,
    )

    snapshot = projector.snapshot()
    assert [(row.plan_entry_id, row.status, row.call_id) for row in snapshot.rows] == [
        ("read-left", "succeeded", "call-left"),
        ("read-right", "failed", "call-right"),
        ("verify", "planned", None),
    ]
    assert [event.kind for event in snapshot.events] == [
        "tool_started",
        "tool_started",
        "tool_failed",
        "tool_succeeded",
    ]
    assert [event.sequence for event in snapshot.events] == [0, 1, 2, 3]


def test_call_id_collision_refuses_without_mutating_projection() -> None:
    projector = RuntimeEventProjector(_plan())
    projector.start(
        plan_entry_id="read-left",
        call_id="same-call",
        tool_name="read_file",
    )
    before = projector.snapshot()

    with pytest.raises(RuntimeEventProjectionError, match="already bound"):
        projector.start(
            plan_entry_id="read-right",
            call_id="same-call",
            tool_name="read_file",
        )

    after = projector.snapshot()
    assert after == before
    assert after.digest == before.digest


def test_terminal_callback_never_falls_back_to_tool_name() -> None:
    projector = RuntimeEventProjector(_plan())
    projector.start(
        plan_entry_id="read-left",
        call_id="call-left",
        tool_name="read_file",
    )

    with pytest.raises(RuntimeEventProjectionError, match="never started"):
        projector.finish(
            call_id="some-other-call",
            tool_name="read_file",
            outcome="succeeded",
            observation_sha256=OBS_A,
        )

    assert projector.snapshot().rows[0].status == "running"


def test_tool_name_substitution_is_refused_before_state_change() -> None:
    projector = RuntimeEventProjector(_plan())
    before = projector.snapshot()

    with pytest.raises(RuntimeEventProjectionError, match="declared plan"):
        projector.start(
            plan_entry_id="verify",
            call_id="call-tests",
            tool_name="read_file",
        )

    assert projector.snapshot() == before


def test_cancel_retains_running_and_not_started_plan_entries() -> None:
    projector = RuntimeEventProjector(_plan())
    projector.start(
        plan_entry_id="read-left",
        call_id="call-left",
        tool_name="read_file",
    )
    projector.finish(
        call_id="call-left",
        tool_name="read_file",
        outcome="succeeded",
        observation_sha256=OBS_A,
    )
    projector.start(
        plan_entry_id="read-right",
        call_id="call-right",
        tool_name="read_file",
    )

    projector.cancel(reason_sha256=CANCEL)
    snapshot = projector.snapshot()

    assert snapshot.cancelled is True
    assert [(row.status, row.call_id) for row in snapshot.rows] == [
        ("succeeded", "call-left"),
        ("cancelled", "call-right"),
        ("cancelled", None),
    ]
    assert snapshot.events[-1].kind == "run_cancelled"
    assert snapshot.events[-1].observation_sha256 == CANCEL
    assert snapshot.to_dict()["schema"] == RUNTIME_EVENT_PROJECTION_SCHEMA
    assert snapshot.to_dict()["projection_sha256"] == snapshot.digest


def test_cancelled_projection_is_frozen() -> None:
    projector = RuntimeEventProjector(_plan())
    projector.cancel(reason_sha256=CANCEL)
    frozen = projector.snapshot()

    with pytest.raises(RuntimeEventProjectionError, match="closed by cancellation"):
        projector.start(
            plan_entry_id="read-left",
            call_id="late-call",
            tool_name="read_file",
        )
    with pytest.raises(RuntimeEventProjectionError, match="closed by cancellation"):
        projector.cancel(reason_sha256=CANCEL)

    assert projector.snapshot() == frozen


def test_same_logical_callback_sequence_has_same_digest() -> None:
    projections = []
    for _ in range(2):
        projector = RuntimeEventProjector(_plan())
        projector.start(
            plan_entry_id="read-left",
            call_id="call-left",
            tool_name="read_file",
        )
        projector.finish(
            call_id="call-left",
            tool_name="read_file",
            outcome="succeeded",
            observation_sha256=OBS_A,
        )
        projector.cancel(reason_sha256=CANCEL)
        projections.append(projector.snapshot())

    assert projections[0] == projections[1]
    assert projections[0].digest == projections[1].digest


@pytest.mark.parametrize(
    "bad_digest",
    ["", "A" * 64, "a" * 63, "g" * 64],
)
def test_terminal_observation_requires_lowercase_sha256(bad_digest: str) -> None:
    projector = RuntimeEventProjector(_plan())
    projector.start(
        plan_entry_id="read-left",
        call_id="call-left",
        tool_name="read_file",
    )
    before = projector.snapshot()

    with pytest.raises(RuntimeEventProjectionError, match="lowercase SHA-256"):
        projector.finish(
            call_id="call-left",
            tool_name="read_file",
            outcome="succeeded",
            observation_sha256=bad_digest,
        )

    assert projector.snapshot() == before


def test_module_stays_projection_only() -> None:
    source = Path("daedalus/orchestration/ikarus_runtime_events.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    imported_roots = set()
    forbidden_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue
            if name in {
                "open",
                "run",
                "Popen",
                "system",
                "connect",
                "urlopen",
            }:
                forbidden_calls.append(name)

    assert imported_roots.isdisjoint(
        {"subprocess", "socket", "sqlite3", "requests", "httpx", "pathlib"}
    )
    assert forbidden_calls == []
