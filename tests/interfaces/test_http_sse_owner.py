"""G1-IFACE-HTTP-03 contracts for the hierarchical SSE delivery owner."""
from __future__ import annotations

import ast
import json
from email.message import Message
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from threading import Thread
from typing import Any
import urllib.error
import urllib.request

import pytest

from daedalus import progress
from daedalus.interfaces.http import web_api
from daedalus.interfaces.http import sse
from daedalus.orchestration import conversation
from daedalus.runtimes import computer as computer_runtime
from daedalus.spine import effect_boundary
from daedalus.spine import ledger as spine_ledger
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "interfaces" / "http" / "web_api.py"
OWNER = ROOT / "daedalus" / "interfaces" / "http" / "sse.py"
REGISTRY_SHA256 = "7a8fc9442be4d1fff8f576fa951036788ef146c779c5c1145bce21f471f3c605"
BOUND_HOST = "127.0.0.1"
BOUND_PORT = 8765
BOUND_ORIGIN = f"http://{BOUND_HOST}:{BOUND_PORT}"


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


def _request_headers(
    *,
    origins: tuple[str, ...] = (BOUND_ORIGIN,),
    fetch_sites: tuple[str, ...] = ("same-origin",),
) -> Message:
    headers = Message()
    for origin in origins:
        headers["Origin"] = origin
    for fetch_site in fetch_sites:
        headers["Sec-Fetch-Site"] = fetch_site
    return headers


def _ikarus_handler(
    headers: Message,
    *,
    server_address: tuple[str, int] = (BOUND_HOST, BOUND_PORT),
) -> tuple[SimpleNamespace, list[tuple[int, Any]]]:
    responses: list[tuple[int, Any]] = []
    handler = SimpleNamespace(
        headers=headers,
        server=SimpleNamespace(server_address=server_address),
        close_connection=False,
    )
    handler._send_json = lambda payload, status=200: responses.append(
        (status, payload)
    )
    return handler, responses


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


@pytest.mark.parametrize(
    ("origins", "fetch_sites"),
    (
        ((BOUND_ORIGIN, BOUND_ORIGIN), ("same-origin",)),
        (("http://[::1",), ("same-origin",)),
        ((f"http://{BOUND_HOST}:{BOUND_PORT + 1}",), ("same-origin",)),
        ((f"http://localhost:{BOUND_PORT}",), ("same-origin",)),
        ((f"http://[::ffff:{BOUND_HOST}]:{BOUND_PORT}",), ("same-origin",)),
        (("https://evil.example",), ("cross-site",)),
        ((BOUND_ORIGIN,), ()),
        ((BOUND_ORIGIN,), ("same-origin", "same-origin")),
        ((BOUND_ORIGIN,), ("same-site",)),
    ),
)
def test_ikarus_stream_rejects_unbound_browser_metadata_before_every_effect(
    monkeypatch: pytest.MonkeyPatch,
    origins: tuple[str, ...],
    fetch_sites: tuple[str, ...],
) -> None:
    effect_calls: list[str] = []
    handler, responses = _ikarus_handler(
        _request_headers(origins=origins, fetch_sites=fetch_sites)
    )
    monkeypatch.setattr(
        progress, "open_unit", lambda *_args, **_kwargs: effect_calls.append("progress")
    )
    monkeypatch.setattr(
        sse, "_open_stream", lambda *_args, **_kwargs: effect_calls.append("sse")
    )
    monkeypatch.setattr(
        sse.ikarus_os,
        "ask_stream",
        lambda *_args, **_kwargs: effect_calls.append("ask_stream"),
    )
    monkeypatch.setattr(
        computer_runtime,
        "setup_computer",
        lambda *_args, **_kwargs: effect_calls.append("setup_computer"),
    )
    monkeypatch.setattr(
        conversation,
        "default_store",
        lambda: effect_calls.append("conversation_store"),
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *_args, **_kwargs: effect_calls.append("begin_effect"),
    )
    monkeypatch.setattr(
        spine_ledger.SpineLedger,
        "record_intent",
        lambda *_args, **_kwargs: effect_calls.append("ledger_intent"),
    )
    monkeypatch.setattr(
        spine_ledger.SpineLedger,
        "record_fact",
        lambda *_args, **_kwargs: effect_calls.append("ledger_fact"),
    )

    sse.handle_ikarus_stream(
        handler,
        {
            "project": ["fixture"],
            "message": ["/computer setup"],
            "conversation_id": ["must-not-be-read"],
        },
    )

    assert responses[0][0] == 403
    assert "exact numeric bound Origin" in responses[0][1]["error"]
    assert handler.close_connection is True
    assert effect_calls == []


@pytest.mark.parametrize(
    ("server_address", "origins"),
    (
        ((BOUND_HOST, BOUND_PORT), ()),
        ((BOUND_HOST, BOUND_PORT), (BOUND_ORIGIN,)),
        (("::1", BOUND_PORT), ()),
        (("::1", BOUND_PORT), (f"http://[::1]:{BOUND_PORT}",)),
    ),
)
def test_exact_same_origin_eventsource_reaches_stream_once(
    monkeypatch: pytest.MonkeyPatch,
    server_address: tuple[str, int],
    origins: tuple[str, ...],
) -> None:
    calls: list[Any] = []
    handler, responses = _ikarus_handler(
        _request_headers(origins=origins), server_address=server_address
    )
    monkeypatch.setattr(
        progress,
        "open_unit",
        lambda *_args, **_kwargs: calls.append("progress") or None,
    )
    monkeypatch.setattr(
        sse,
        "_open_stream",
        lambda *_args, **_kwargs: calls.append("sse") or True,
    )
    monkeypatch.setattr(
        sse.ikarus_os,
        "ask_stream",
        lambda *_args, **kwargs: calls.append(("ask_stream", kwargs))
        or [("final", {"ok": True})],
    )
    monkeypatch.setattr(
        sse,
        "_send_event",
        lambda _handler, event, payload: calls.append((event, payload)),
    )

    sse.handle_ikarus_stream(
        handler,
        {"project": ["fixture"], "message": ["hello"]},
    )

    assert responses == []
    assert calls == [
        "progress",
        "sse",
        (
            "ask_stream",
            {
                "provider": None,
                "model": None,
                "effort": None,
                "conversation_id": None,
            },
        ),
        ("final", {"ok": True}),
    ]
    assert handler.close_connection is True


def test_live_legacy_get_refuses_cross_origin_then_serves_same_origin_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(progress, "open_unit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sse.ikarus_os,
        "ask_stream",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or [("final", {"ok": True})],
    )
    server = ThreadingHTTPServer((BOUND_HOST, 0), web_api.DaedalusHandler)
    server.daedalus_auth_token = ""
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{BOUND_HOST}:{server.server_address[1]}"
    route = "/api/ikarus/stream?project=fixture&message=hello"
    try:
        rejected = urllib.request.Request(
            base + route,
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as refusal:
            urllib.request.urlopen(rejected, timeout=10)
        assert refusal.value.code == 403
        assert calls == []

        accepted = urllib.request.Request(
            base + route,
            headers={"Origin": base, "Sec-Fetch-Site": "same-origin"},
        )
        with urllib.request.urlopen(accepted, timeout=10) as response:
            body = response.read()
        assert response.status == 200
        assert b"event: final" in body
        assert json.loads(body.split(b"data: ", 1)[1].splitlines()[0]) == {
            "ok": True
        }
        assert len(calls) == 1
        assert calls[0][0] == ("fixture", "hello")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


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
