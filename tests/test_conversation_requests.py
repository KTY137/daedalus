from __future__ import annotations

import threading
import time

import pytest

from daedalus import conversation
from daedalus import conversation_requests as requests


def _wait_for(manager: requests.ConversationRequestManager, request_id: int,
              states: set[str], timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(request_id)
        if status["state"] in states:
            return status
        time.sleep(0.01)
    raise AssertionError(f"request did not reach {states}: {manager.status(request_id)}")


@pytest.fixture()
def store(tmp_path):
    with conversation.ConversationStore(tmp_path / "spine.sqlite3") as opened:
        yield opened


def test_duplicate_client_request_returns_same_request_and_starts_provider_once(store):
    calls = []

    def stream(*args, **kwargs):
        calls.append((args, kwargs))
        yield "start", {"intent": "chat"}
        yield "final", {"intent": "chat", "assistant": "ok", "turn_id": 41}

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    first, created = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    second, duplicate_created = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")

    assert created is True
    assert duplicate_created is False
    assert second["request_id"] == first["request_id"]
    final = _wait_for(manager, first["request_id"], {"final"})
    assert final["turn_id"] == 41
    assert len(calls) == 1
    assert store.spine.open_intents(requests.KIND_GENERATION) == []


def test_same_client_id_with_different_input_refuses_without_second_start(store):
    gate = threading.Event()
    calls = []

    def stream(*args, **kwargs):
        calls.append(1)
        yield "start", {"intent": "chat"}
        gate.wait(1)
        yield "final", {"intent": "chat", "assistant": "ok"}

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    first, _ = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    with pytest.raises(requests.ConflictingConversationRequest):
        manager.create(
            conversation_id="conv_one", client_request_id="client-1",
            project="sample", message="different")
    gate.set()
    _wait_for(manager, first["request_id"], {"final"})
    assert calls == [1]


def test_observing_events_never_starts_or_restarts_work(store):
    release = threading.Event()
    calls = []

    def stream(*args, **kwargs):
        calls.append(1)
        yield "start", {"intent": "chat"}
        release.wait(1)
        yield "final", {"intent": "chat", "assistant": "ok"}

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    created, _ = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    first = manager.events(created["request_id"], after=0, wait_s=0.2)
    second = manager.events(created["request_id"], after=0, wait_s=0.2)
    assert first["events"][0]["event"] == "start"
    assert second["events"][0]["event"] == "start"
    assert calls == [1]
    release.set()
    _wait_for(manager, created["request_id"], {"final"})


def test_cancel_is_requested_then_confirmed_only_after_worker_stops(store):
    release = threading.Event()

    class CancellableStream:
        def __init__(self):
            self.step = 0
            self.cancelled = False

        def __iter__(self):
            return self

        def __next__(self):
            if self.step == 0:
                self.step += 1
                return "start", {"intent": "chat"}
            release.wait(1)
            if self.cancelled:
                raise StopIteration
            self.step += 1
            return "final", {"intent": "chat", "assistant": "should not arrive"}

        def cancel(self):
            self.cancelled = True
            release.set()

    def stream(*args, **kwargs):
        return CancellableStream()

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    created, _ = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    manager.events(created["request_id"], wait_s=0.2)

    cancellation = manager.cancel(
        created["request_id"], client_cancel_id="cancel-1")
    assert cancellation["status"] == "requested"
    assert manager.status(created["request_id"])["state"] in {
        "cancel_requested", "cancelled"}
    status = _wait_for(manager, created["request_id"], {"cancelled"})
    assert status["cancellation"]["status"] == "confirmed"
    observed = manager.events(created["request_id"])
    assert any(row["event"] == "cancelled" for row in observed["events"])
    assert not any(row["event"] == "final" for row in observed["events"])


def test_non_cancellable_provider_reports_not_supported_and_finishes(store):
    release = threading.Event()

    def stream(*args, **kwargs):
        yield "start", {"intent": "chat"}
        release.wait(1)
        yield "final", {"intent": "chat", "assistant": "done"}

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    created, _ = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    manager.events(created["request_id"], wait_s=0.2)

    cancellation = manager.cancel(
        created["request_id"], client_cancel_id="cancel-1")
    assert cancellation["status"] == "not_supported"
    assert manager.status(created["request_id"])["state"] == "streaming"
    release.set()
    assert _wait_for(manager, created["request_id"], {"final"})["state"] == "final"


def test_open_request_after_process_restart_is_unknown_and_not_replayed(store):
    payload = {
        "conversation_id": "conv_one", "client_request_id": "client-1",
        "project": "sample", "message": "hello", "provider": None,
        "model": None, "effort": None, "context_refs": [],
    }
    open_intent = store.spine.record_intent(
        requests.KIND_GENERATION, payload,
        effect_key="conv_one:client-1")
    calls = []
    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *a, **k: calls.append(1))

    status = manager.status(open_intent.id)
    assert status["state"] == "unknown"
    assert manager.events(open_intent.id)["terminal"] is True
    assert calls == []
    cancellation = manager.cancel(open_intent.id, client_cancel_id="cancel-1")
    assert cancellation["status"] == "unknown"


def test_cancellation_after_final_is_honestly_already_terminal(store):
    def stream(*args, **kwargs):
        yield "final", {"intent": "chat", "assistant": "done"}

    manager = requests.ConversationRequestManager(store, stream_factory=stream)
    created, _ = manager.create(
        conversation_id="conv_one", client_request_id="client-1",
        project="sample", message="hello")
    _wait_for(manager, created["request_id"], {"final"})

    cancellation = manager.cancel(
        created["request_id"], client_cancel_id="cancel-1")
    assert cancellation["status"] == "already_terminal"
