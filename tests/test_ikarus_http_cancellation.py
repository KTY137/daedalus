"""Upstream Stop acceptance through the canonical durable conversation API.

The process-local /api/ikarus/cancel proposal is superseded. Cancellation
identity, idempotency, terminal proof and restart projection belong to the
existing ConversationRequestManager and its canonical spine receipts.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from daedalus.orchestration.ikarus import cancellation as ikarus_cancellation
from daedalus.interfaces.http import web_api
from daedalus.orchestration import conversation, conversation_requests
from daedalus.orchestration.ikarus import shell


def _post(monkeypatch, manager, conversation_id, request_id, body):
    handler = object.__new__(web_api.DaedalusHandler)
    handler.path = f"/api/conversations/{conversation_id}/turns/{request_id}/cancel-requests"
    handler._send_json = mock.Mock()
    monkeypatch.setattr(web_api, "_read_body", lambda _: body)
    monkeypatch.setattr(conversation_requests, "default_manager", lambda: manager)
    web_api.DaedalusHandler._handle_post(handler)
    return handler._send_json


def _wait(manager, request_id, wanted):
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = manager.status(request_id)
        if status.get("cancellation", {}).get("status") == wanted:
            return status
        time.sleep(0.01)
    raise AssertionError(manager.status(request_id))


@pytest.fixture
def live_request(tmp_path):
    store = conversation.ConversationStore(tmp_path / "spine.sqlite3")
    entered = threading.Event()
    holder = {}
    signal = ikarus_cancellation.CancellationSignal("owned-child")
    def frames():
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        holder["process"] = proc
        try:
            yield "start", {"intent": "chat"}
            entered.set()
            while not signal.cancelled():
                time.sleep(0.002)
            ikarus_cancellation.terminate_owned_subprocess(signal, proc, grace_s=0.1)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
    stream = shell._CancellableAskStream(frames(), lambda value: value,
        signal._event, signal)
    manager = conversation_requests.ConversationRequestManager(store,
        stream_factory=lambda *args, **kwargs: stream)
    created, _ = manager.create(conversation_id="conv-stop", client_request_id="request-1",
        project="sample", message="hello")
    assert entered.wait(3.0)
    try:
        yield manager, created["request_id"], holder, store
    finally:
        stream.cancel()
        worker = manager._runtime_for(created["request_id"]).worker
        worker.join(timeout=3.0)
        proc = holder.get("process")
        if proc is not None and proc.poll() is None:
            proc.kill(); proc.wait(timeout=2)
        store.close()


def test_cancel_endpoint_surfaces_owned_cli_process_exit_evidence(live_request, monkeypatch):
    manager, request_id, holder, store = live_request
    send = _post(monkeypatch, manager, "conv-stop", request_id,
                 {"client_cancel_id": "stop-1"})
    assert send.call_args.kwargs["status"] == 202
    status = _wait(manager, request_id, "confirmed")
    cancellation = status["cancellation"]
    child = cancellation["subprocess"]
    assert child["request_id"] == request_id
    assert child["cancellation_requested"] is True
    assert child["was_running"] is True
    assert child["terminate_sent"] is True
    assert child["process_exited"] is True
    assert child["returncode"] is not None
    assert cancellation["provider_process_terminated"] is True
    assert holder["process"].poll() is not None
    events = manager.events(request_id)["events"]
    stopped = next(row["data"] for row in events if row["event"] == "cancelled")
    assert stopped["subprocess"] == child
    # Same canonical cancellation replays its exact proof after manager restart.
    resumed = conversation_requests.ConversationRequestManager(store)
    replay = resumed.cancel(request_id, client_cancel_id="stop-1")
    assert replay["subprocess"] == child
    assert replay["cancellation_id"] == cancellation["cancellation_id"]
    assert replay["status"] == "confirmed"


def test_cancel_endpoint_rejects_foreign_conversation_before_signalling(live_request, monkeypatch):
    manager, request_id, holder, _ = live_request
    send = _post(monkeypatch, manager, "foreign", request_id,
                 {"client_cancel_id": "stop-foreign"})
    assert send.call_args.kwargs["status"] == 404
    assert holder["process"].poll() is None
    assert manager.status(request_id)["cancellation"] is None


def test_cancel_endpoint_rejects_malformed_identity_without_provider_effect(live_request, monkeypatch):
    manager, _, holder, _ = live_request
    send = _post(monkeypatch, manager, "conv-stop", "bad", {"client_cancel_id": "stop-bad"})
    assert send.call_args.kwargs["status"] == 404
    assert holder["process"].poll() is None


def test_durable_observation_keeps_identity_without_replaying_or_stopping_provider(live_request):
    manager, request_id, holder, _ = live_request
    first = manager.events(request_id)
    second = manager.events(request_id)
    assert first["status"]["request_id"] == request_id
    assert first["events"] == second["events"]
    assert manager.status(request_id)["cancellation"] is None
    assert holder["process"].poll() is None
