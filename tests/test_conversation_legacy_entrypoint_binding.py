"""Legacy assistant entrypoints may resume only an exactly bound thread."""
from __future__ import annotations

from email.message import Message
from types import SimpleNamespace

import pytest

from daedalus import budget, progress
from daedalus.interfaces.http import effects, sse
from daedalus.orchestration import conversation
from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.spine import effect_boundary
from daedalus.spine import ledger as spine_ledger


_ABSENT = object()
_BOUND_HOST = "127.0.0.1"
_BOUND_PORT = 8765


def _sse_handler() -> SimpleNamespace:
    headers = Message()
    headers["Origin"] = f"http://{_BOUND_HOST}:{_BOUND_PORT}"
    headers["Sec-Fetch-Site"] = "same-origin"
    return SimpleNamespace(
        close_connection=False,
        headers=headers,
        server=SimpleNamespace(server_address=(_BOUND_HOST, _BOUND_PORT)),
    )


def _legacy_turn(
    ledger: spine_ledger.SpineLedger,
    effect_conversation_id: str,
    *,
    payload_conversation_id: str | None = None,
    project: object = _ABSENT,
) -> None:
    payload = {
        "conversation_id": (
            effect_conversation_id
            if payload_conversation_id is None
            else payload_conversation_id
        ),
        "user_message": "legacy",
        "intent": "chat",
        "status": conversation.STATUS_ANSWERED,
    }
    if project is not _ABSENT:
        payload["project"] = project
    ledger.record_fact(
        conversation.KIND_TURN,
        payload,
        effect_key=conversation.conversation_effect_key(
            effect_conversation_id
        ),
        effect_id=effect_conversation_id,
        result={"status": conversation.STATUS_ANSWERED, "intent": "chat"},
    )


@pytest.fixture()
def legacy_store(tmp_path):
    db_path = tmp_path / "spine.sqlite3"
    ledger = spine_ledger.SpineLedger(db_path)
    try:
        _legacy_turn(ledger, "conv_bound", project="A")
        _legacy_turn(ledger, "conv_unscoped")
        _legacy_turn(ledger, "conv_mixed", project="A")
        _legacy_turn(ledger, "conv_mixed", project="B")
        _legacy_turn(
            ledger,
            "conv_corrupt",
            payload_conversation_id="another-conversation",
            project="A",
        )
    finally:
        ledger.close()
    with conversation.ConversationStore(db_path) as opened:
        yield opened


def _ports(body: dict) -> effects.EffectPorts:
    return effects.EffectPorts(
        read_body=lambda _handler: body,
        structure_index=lambda *_args, **_kwargs: {},
        resolve_repo_root=lambda *_args, **_kwargs: None,
        resolve_registered_project_root=lambda *_args, **_kwargs: None,
        register_project=lambda *_args, **_kwargs: {},
        genesis_run=lambda *_args, **_kwargs: {},
        ariadne_run=lambda *_args, **_kwargs: {},
    )


def _post_ask(body: dict) -> dict:
    captured: dict = {}
    handler = SimpleNamespace(path="/api/ikarus/ask")
    handler._send_json = lambda payload, status=200: captured.update(
        payload=payload, status=status
    )
    effects.handle_post(handler, ports=_ports(body))
    return captured


@pytest.mark.parametrize(
    ("conversation_id", "project"),
    [
        ("conv_missing", "A"),
        ("conv_unscoped", "A"),
        ("conv_mixed", "A"),
        ("conv_corrupt", "A"),
        ("conv_bound", "B"),
    ],
)
def test_legacy_blocking_http_conflicts_before_assistant_or_ledger_effect(
    legacy_store, monkeypatch, conversation_id, project
):
    calls: list[str] = []
    monkeypatch.setattr(conversation, "default_store", lambda: legacy_store)
    monkeypatch.setattr(
        effects.ikarus_os,
        "ask",
        lambda *_args, **_kwargs: calls.append("ask"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_conversation_context",
        lambda *_args, **_kwargs: calls.append("context"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_voice_client",
        lambda: calls.append("provider"),
    )
    changes_before = legacy_store.spine._conn.total_changes

    captured = _post_ask(
        {
            "project": project,
            "message": "do not run",
            "conversation_id": conversation_id,
        }
    )

    assert captured["status"] == 409
    assert captured["payload"]["code"] == "conversation_project_conflict"
    assert calls == []
    assert legacy_store.spine._conn.total_changes == changes_before


@pytest.mark.parametrize(
    ("conversation_id", "project"),
    [
        ("conv_missing", "A"),
        ("conv_unscoped", "A"),
        ("conv_mixed", "A"),
        ("conv_corrupt", "A"),
        ("conv_bound", "B"),
    ],
)
def test_legacy_sse_conflicts_before_progress_headers_frames_or_assistant(
    legacy_store, monkeypatch, conversation_id, project
):
    calls: list[str] = []
    captured: dict = {}
    handler = _sse_handler()
    handler._send_json = lambda payload, status=200: captured.update(
        payload=payload, status=status
    )
    monkeypatch.setattr(conversation, "default_store", lambda: legacy_store)
    monkeypatch.setattr(
        progress,
        "open_unit",
        lambda *_args, **_kwargs: calls.append("progress"),
    )
    monkeypatch.setattr(
        sse,
        "_open_stream",
        lambda *_args, **_kwargs: calls.append("sse"),
    )
    monkeypatch.setattr(
        sse.ikarus_os,
        "ask_stream",
        lambda *_args, **_kwargs: calls.append("ask_stream"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_conversation_context",
        lambda *_args, **_kwargs: calls.append("context"),
    )
    changes_before = legacy_store.spine._conn.total_changes

    sse.handle_ikarus_stream(
        handler,
        {
            "project": [project],
            "message": ["do not run"],
            "conversation_id": [conversation_id],
        },
    )

    assert captured["status"] == 409
    assert captured["payload"]["code"] == "conversation_project_conflict"
    assert handler.close_connection is False
    assert calls == []
    assert legacy_store.spine._conn.total_changes == changes_before


def test_legacy_blocking_http_allows_exact_binding(legacy_store, monkeypatch):
    received: list[dict] = []
    monkeypatch.setattr(conversation, "default_store", lambda: legacy_store)
    monkeypatch.setattr(
        effects.ikarus_os,
        "ask",
        lambda *_args, **kwargs: received.append(kwargs) or {"ok": True},
    )

    captured = _post_ask(
        {
            "project": "A",
            "message": "continue",
            "conversation_id": "conv_bound",
        }
    )

    assert captured == {"payload": {"ok": True}, "status": 200}
    assert received[0]["conversation_id"] == "conv_bound"


def test_legacy_blocking_http_stays_stateless_without_id(monkeypatch):
    received: list[dict] = []
    monkeypatch.setattr(
        conversation,
        "default_store",
        lambda: pytest.fail("stateless ask read conversation binding"),
    )
    monkeypatch.setattr(
        effects.ikarus_os,
        "ask",
        lambda *_args, **kwargs: received.append(kwargs) or {"ok": True},
    )

    captured = _post_ask({"project": "A", "message": "stateless"})

    assert captured["status"] == 200
    assert received[0]["conversation_id"] is None


@pytest.mark.parametrize("with_conversation", [False, True])
def test_legacy_sse_allows_stateless_or_exact_bound_request(
    legacy_store, monkeypatch, with_conversation
):
    calls: list[object] = []
    handler = _sse_handler()
    handler._send_json = lambda *_args, **_kwargs: pytest.fail(
        "allowed stream returned JSON"
    )
    if with_conversation:
        monkeypatch.setattr(conversation, "default_store", lambda: legacy_store)
    else:
        monkeypatch.setattr(
            conversation,
            "default_store",
            lambda: pytest.fail("stateless stream read conversation binding"),
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
        lambda *_args, **kwargs: calls.append(kwargs) or [
            ("final", {"ok": True})
        ],
    )
    monkeypatch.setattr(
        sse,
        "_send_event",
        lambda _handler, event, payload: calls.append((event, payload)),
    )
    query = {"project": ["A"], "message": ["continue"]}
    if with_conversation:
        query["conversation_id"] = ["conv_bound"]

    sse.handle_ikarus_stream(handler, query)

    assert calls[0:2] == ["progress", "sse"]
    ask_kwargs = next(item for item in calls if isinstance(item, dict))
    assert ask_kwargs["conversation_id"] == (
        "conv_bound" if with_conversation else None
    )
    assert calls[-1] == ("final", {"ok": True})


@pytest.mark.parametrize("streaming", [False, True])
def test_non_http_legacy_entrypoints_fail_closed_before_context_provider_or_turn(
    legacy_store, monkeypatch, streaming
):
    calls: list[str] = []
    monkeypatch.setattr(conversation, "default_store", lambda: legacy_store)
    monkeypatch.setattr(
        budget, "process_guard_boundary_decision", lambda: object()
    )
    monkeypatch.setattr(
        effect_boundary, "begin_effect", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        ikarus_os,
        "classify",
        lambda *_args, **_kwargs: calls.append("classify"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_conversation_context",
        lambda *_args, **_kwargs: calls.append("context"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_voice_client",
        lambda: calls.append("provider"),
    )
    monkeypatch.setattr(
        ikarus_os,
        "_persist_turn",
        lambda *_args, **_kwargs: calls.append("turn"),
    )
    changes_before = legacy_store.spine._conn.total_changes

    if streaming:
        events = list(
            ikarus_os.ask_stream(
                "B", "do not run", conversation_id="conv_bound"
            )
        )
        result = events[-1][1]
        assert [event for event, _payload in events] == ["start", "final"]
    else:
        result = ikarus_os.ask(
            "B", "do not run", conversation_id="conv_bound"
        )

    assert result["intent"] == "error"
    assert result["conversation_project_conflict"] is True
    assert calls == []
    assert legacy_store.spine._conn.total_changes == changes_before
