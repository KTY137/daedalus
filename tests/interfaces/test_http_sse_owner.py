"""G1-IFACE-HTTP-03 contracts for the hierarchical SSE delivery owner."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from daedalus.interfaces.http import web_api
from daedalus.interfaces.http import sse
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "interfaces" / "http" / "web_api.py"
OWNER = ROOT / "daedalus" / "interfaces" / "http" / "sse.py"
REGISTRY_SHA256 = "615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752"


class _Wire:
    def __init__(self, *, disconnect: bool = False) -> None:
        self.chunks: list[bytes] = []
        self.disconnect = disconnect
        self.write_calls = 0
        self.flush_calls = 0

    def write(self, chunk: bytes) -> None:
        self.write_calls += 1
        if self.disconnect:
            raise BrokenPipeError("client closed")
        self.chunks.append(chunk)

    def flush(self) -> None:
        self.flush_calls += 1


class _Handler:
    def __init__(self, *, disconnect: bool = False) -> None:
        self.wfile = _Wire(disconnect=disconnect)
        self.responses: list[int] = []
        self.headers: list[tuple[str, str]] = []
        self.headers_ended = 0
        self.close_connection = False

    def send_response(self, status: int) -> None:
        self.responses.append(status)

    def send_header(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def end_headers(self) -> None:
        self.headers_ended += 1


def _frame(chunk: bytes) -> tuple[str, Any]:
    lines = chunk.decode("utf-8").splitlines()
    event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
    data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    return event, json.loads(data)


def _snapshot(
        *,
        queue_depth: int,
        in_flight: int,
        reports_total: int,
        latest_report: dict[str, Any] | None,
        watcher_state: str = "alive",
) -> dict[str, Any]:
    return {
        "queue_depth": queue_depth,
        "in_flight": in_flight,
        "unread_count": reports_total,
        "quarantined_count": 0,
        "watcher_state": watcher_state,
        "reports_total": reports_total,
        "latest_report": latest_report,
    }


def test_stream_loop_keeps_project_filter_and_additive_field_types() -> None:
    alpha_1 = {"name": "alpha-1.report.json", "project": "alpha"}
    alpha_2 = {"name": "alpha-2.report.json", "project": "alpha"}
    states = {
        "alpha": [
            _snapshot(
                queue_depth=0,
                in_flight=0,
                reports_total=1,
                latest_report=alpha_1,
            ),
            _snapshot(
                queue_depth=2,
                in_flight=1,
                reports_total=2,
                latest_report=alpha_2,
                watcher_state="busy",
            ),
        ],
        "beta": [
            _snapshot(
                queue_depth=9,
                in_flight=1,
                reports_total=99,
                latest_report={"name": "beta.report.json", "project": "beta"},
            )
        ],
    }
    projects: list[str | None] = []

    def stream_state(project: str | None) -> dict[str, Any]:
        projects.append(project)
        return states[str(project)].pop(0)

    now = 0.0

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    handler = _Handler()
    sse.stream_events(
        handler,
        "alpha",
        stream_state=stream_state,
        clock=clock,
        sleep=sleep,
        max_s=1.0,
        keep_alive_s=1.0,
    )

    assert projects == ["alpha", "alpha"]
    assert states["beta"][0]["latest_report"]["project"] == "beta"
    frames = [_frame(chunk) for chunk in handler.wfile.chunks[:-1]]
    assert [name for name, _ in frames] == ["hello", "report", "queue", "heartbeat"]
    assert frames[0][1]["latest_report"] == alpha_1
    assert frames[1][1] == alpha_2
    assert frames[2][1] == {"queue_depth": 2}
    assert frames[3][1] == {"watcher_state": "busy", "in_flight": 1}
    assert type(frames[0][1]["queue_depth"]) is int
    assert type(frames[0][1]["in_flight"]) is int
    assert type(frames[2][1]["queue_depth"]) is int
    assert type(frames[3][1]["in_flight"]) is int
    assert handler.wfile.chunks[-1] == b": keep-alive\n\n"


def test_unrelated_report_projection_does_not_emit_report() -> None:
    alpha = {"name": "alpha.report.json", "project": "alpha"}
    previous = _snapshot(
        queue_depth=0,
        in_flight=0,
        reports_total=1,
        latest_report=alpha,
    )
    after_unrelated_report = dict(previous)

    assert sse.event_changes(previous, after_unrelated_report) == ()


def test_shared_encoder_preserves_legacy_sse_bytes_and_sequence() -> None:
    assert sse.encode_event("queue", {"queue_depth": 2}) == (
        b'event: queue\ndata: {"queue_depth": 2}\n\n'
    )
    assert sse.encode_event("state", {"ok": True}, 7) == (
        b'id: 7\nevent: state\ndata: {"ok": true}\n\n'
    )


def test_disconnect_stops_stream_without_snapshot_replay() -> None:
    projects: list[str | None] = []

    def stream_state(project: str | None) -> dict[str, Any]:
        projects.append(project)
        return _snapshot(
            queue_depth=0,
            in_flight=0,
            reports_total=0,
            latest_report=None,
        )

    handler = _Handler(disconnect=True)
    sse.handle_events(handler, "alpha", stream_state=stream_state)

    assert projects == ["alpha"]
    assert handler.responses == [200]
    assert ("Content-Type", "text/event-stream") in handler.headers
    assert ("Connection", "keep-alive") in handler.headers
    assert handler.headers_ended == 1
    assert handler.wfile.write_calls == 1
    assert handler.wfile.flush_calls == 0


def test_facade_resolves_stream_state_monkeypatch_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = object()
    captured: dict[str, Any] = {}

    def delegated(handler: Any, project: str | None, *, stream_state: Any) -> None:
        captured.update(
            handler=handler,
            project=project,
            stream_state=stream_state,
        )

    monkeypatch.setattr(web_api, "stream_state", replacement)
    monkeypatch.setattr(sse, "handle_events", delegated)
    handler = object()

    web_api.DaedalusHandler._handle_events(handler, "alpha")

    assert captured == {
        "handler": handler,
        "project": "alpha",
        "stream_state": replacement,
    }


def test_sse_responsibilities_are_directed_and_root_timings_are_retired() -> None:
    owner_tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    facade_tree = ast.parse(FACADE.read_text(encoding="utf-8"), filename=str(FACADE))
    functions = {
        node.name: node
        for node in owner_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {
        "snapshot_events",
        "event_changes",
        "encode_event",
        "_open_stream",
        "_write_frame",
        "stream_events",
        "handle_events",
    } <= functions.keys()

    imports: set[str] = set()
    for node in ast.walk(owner_tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    assert not any(name.endswith("web_api") for name in imports)
    assert not any(name.endswith("file_bridge") for name in imports)

    stream_source = ast.unparse(functions["stream_events"])
    encoder_source = ast.unparse(functions["encode_event"])
    writer_source = ast.unparse(functions["_write_frame"])
    assert "snapshot_events" in stream_source
    assert "event_changes" in stream_source
    assert "json.dumps" not in stream_source
    assert ".wfile" not in stream_source
    assert "json.dumps" in encoder_source
    assert ".wfile" not in encoder_source
    assert ".wfile" in writer_source
    assert "json.dumps" not in writer_source

    facade_names = {
        node.id
        for node in ast.walk(facade_tree)
        if isinstance(node, ast.Name)
    }
    assert "_TASK_EVENTS_MAX_S" not in facade_names
    assert "_TASK_EVENTS_GRACE_S" not in facade_names
    assert "_TASK_EVENTS_PERIOD_S" not in facade_names
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "_task_snapshot"
        for node in facade_tree.body
    )
    assert sse.EVENT_STREAM_MAX_S == 300
    assert sse.EVENT_STREAM_PERIOD_S == 1.0
    assert sse.EVENT_STREAM_KEEP_ALIVE_S == 15
    assert sse.TASK_EVENTS_MAX_S == 1800
    assert sse.TASK_EVENTS_GRACE_S == 10.0
    assert sse.TASK_EVENTS_PERIOD_S == 3.0


def test_effect_registry_digest_is_unchanged() -> None:
    assert registry_sha256() == REGISTRY_SHA256
