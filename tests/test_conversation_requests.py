from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from daedalus.orchestration import conversation
from daedalus.orchestration import conversation_requests as requests
from daedalus.orchestration.ikarus import shell as ikarus_os
from daedalus.interfaces.http import effects as http_effects


def _wait_for(manager: requests.ConversationRequestManager, request_id: int,
              states: set[str], timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(request_id)
        if status["state"] in states:
            return status
        time.sleep(0.01)
    raise AssertionError(f"request did not reach {states}: {manager.status(request_id)}")


def _wait_for_cancellation(
    manager: requests.ConversationRequestManager,
    request_id: int,
    statuses: set[str],
    timeout: float = 2.0,
):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.status(request_id)
        cancellation = status["cancellation"]
        if cancellation is not None and cancellation["status"] in statuses:
            return status
        time.sleep(0.01)
    raise AssertionError(
        f"cancellation did not reach {statuses}: {manager.status(request_id)}"
    )


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
    assert store.project_binding("conv_one") == conversation.ConversationProjectBinding(
        "conv_one", conversation.BINDING_BOUND, "sample", 1
    )
    assert store.spine.open_intents(requests.KIND_GENERATION) == []


def test_project_conflict_is_specific_and_refuses_before_provider_start(store):
    store.append_turn(
        "conv_bound",
        user_message="A",
        intent="chat",
        status=conversation.STATUS_ANSWERED,
        project="alpha",
    )
    calls = []
    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *_args, **_kwargs: calls.append(1) or ()
    )

    with pytest.raises(requests.ConflictingConversationProject):
        manager.create(
            conversation_id="conv_bound",
            client_request_id="client-1",
            project="beta",
            message="do not start",
        )

    assert calls == []
    assert manager._runtime == {}
    assert store.spine.open_intents(requests.KIND_GENERATION) == []


def test_project_conflict_is_http_409_before_provider_start(store, monkeypatch):
    store.append_turn(
        "conv_http_bound",
        user_message="A",
        intent="chat",
        status=conversation.STATUS_ANSWERED,
        project="alpha",
    )
    calls = []
    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *_args, **_kwargs: calls.append(1) or ()
    )
    monkeypatch.setattr(requests, "default_manager", lambda: manager)
    captured: dict = {}
    handler = SimpleNamespace(path="/api/conversations/conv_http_bound/turns")
    handler._send_json = lambda payload, status=200: captured.update(
        payload=payload, status=status
    )
    ports = http_effects.EffectPorts(
        read_body=lambda _handler: {
            "client_request_id": "client-http",
            "project": "beta",
            "message": "do not start",
        },
        structure_index=lambda *_args, **_kwargs: {},
        resolve_repo_root=lambda *_args, **_kwargs: None,
        resolve_registered_project_root=lambda *_args, **_kwargs: None,
        register_project=lambda *_args, **_kwargs: {},
        genesis_run=lambda *_args, **_kwargs: {},
        ariadne_run=lambda *_args, **_kwargs: {},
    )

    http_effects.handle_post(handler, ports=ports)

    assert captured["status"] == 409
    assert "bound" in captured["payload"]["error"]
    assert calls == []
    assert manager._runtime == {}


def test_request_and_direct_turn_first_claim_have_one_atomic_winner(store):
    other = conversation.ConversationStore(store.path)
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []
    provider_calls: list[int] = []
    manager = requests.ConversationRequestManager(
        store,
        stream_factory=lambda *_args, **_kwargs: provider_calls.append(1) or (),
    )

    def create_request() -> None:
        barrier.wait(timeout=5)
        try:
            manager.create(
                conversation_id="conv_cross_kind",
                client_request_id="client-1",
                project="alpha",
                message="request",
            )
            outcomes.append(("request", "created"))
        except requests.ConflictingConversationProject:
            outcomes.append(("request", "conflict"))

    def append_direct() -> None:
        barrier.wait(timeout=5)
        try:
            other.append_turn(
                "conv_cross_kind",
                user_message="direct",
                intent="chat",
                status=conversation.STATUS_ANSWERED,
                project="beta",
            )
            outcomes.append(("turn", "created"))
        except conversation.ConversationProjectConflict:
            outcomes.append(("turn", "conflict"))

    threads = [
        threading.Thread(target=create_request),
        threading.Thread(target=append_direct),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    try:
        assert sorted(result for _, result in outcomes) == ["conflict", "created"]
        winner = next(kind for kind, result in outcomes if result == "created")
        binding = store.project_binding("conv_cross_kind")
        assert binding.state == conversation.BINDING_BOUND
        assert binding.project == ("alpha" if winner == "request" else "beta")
        if winner == "turn":
            assert provider_calls == []
        else:
            deadline = time.time() + 2
            while not provider_calls and time.time() < deadline:
                time.sleep(0.01)
            assert provider_calls == [1]
    finally:
        other.close()


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
    status = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "confirmed"
    observed = manager.events(created["request_id"])
    assert any(row["event"] == "cancelled" for row in observed["events"])
    assert not any(row["event"] == "final" for row in observed["events"])


def test_default_ask_stream_cancel_stops_local_delivery_and_persistence(
    store, monkeypatch
):
    provider_blocked = threading.Event()
    release_provider = threading.Event()
    persisted = []

    def inner(*_args, **_kwargs):
        yield "start", {"intent": "chat"}
        provider_blocked.set()
        release_provider.wait(1)
        yield "delta", {"text": "must be dropped"}
        yield "final", {"intent": "chat", "assistant": "must not persist"}

    monkeypatch.setattr(ikarus_os, "_ask_stream_inner", inner)
    monkeypatch.setattr(
        ikarus_os, "_persist_turn", lambda *_args, **_kwargs: persisted.append(1)
    )
    manager = requests.ConversationRequestManager(store)
    created, _ = manager.create(
        conversation_id="conv_default_cancel",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    manager.events(created["request_id"], wait_s=0.2)
    assert provider_blocked.wait(1)

    first = manager.cancel(created["request_id"], client_cancel_id="cancel-1")
    duplicate = manager.cancel(created["request_id"], client_cancel_id="cancel-1")
    assert first["status"] == "requested"
    assert duplicate == first
    assert manager.status(created["request_id"])["state"] == "cancel_requested"
    assert persisted == []

    release_provider.set()
    status = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "confirmed"
    assert manager.cancel(
        created["request_id"], client_cancel_id="cancel-1"
    )["status"] == "confirmed"
    observed = manager.events(created["request_id"])["events"]
    assert [row["event"] for row in observed] == ["start", "cancelled"]
    cancellation_event = observed[-1]["data"]
    assert cancellation_event["scope"] == "local_generation_delivery_persistence"
    assert cancellation_event["provider_process_terminated"] is None
    assert persisted == []


def test_cancel_before_stream_binding_is_applied_when_default_stream_arrives(
    store, monkeypatch
):
    factory_entered = threading.Event()
    bind_stream = threading.Event()
    persisted = []

    monkeypatch.setattr(
        ikarus_os,
        "_ask_stream_inner",
        lambda *_args, **_kwargs: iter([
            ("final", {"intent": "chat", "assistant": "must not persist"})
        ]),
    )
    monkeypatch.setattr(
        ikarus_os, "_persist_turn", lambda *_args, **_kwargs: persisted.append(1)
    )

    def delayed_stream(*args, **kwargs):
        factory_entered.set()
        bind_stream.wait(1)
        return ikarus_os.ask_stream(*args, **kwargs)

    manager = requests.ConversationRequestManager(
        store, stream_factory=delayed_stream
    )
    created, _ = manager.create(
        conversation_id="conv_prebind",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    assert factory_entered.wait(1)

    cancellation = manager.cancel(
        created["request_id"], client_cancel_id="cancel-prebind"
    )
    assert cancellation["status"] == "requested"
    bind_stream.set()

    status = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "confirmed"
    assert persisted == []
    assert not any(
        row["event"] == "final"
        for row in manager.events(created["request_id"])["events"]
    )


def test_exception_after_requested_cancel_confirms_local_stop(store, monkeypatch):
    provider_blocked = threading.Event()
    release_provider = threading.Event()

    def failing_inner(*_args, **_kwargs):
        yield "start", {"intent": "chat"}
        provider_blocked.set()
        release_provider.wait(1)
        raise RuntimeError("provider failed while cancellation was pending")

    monkeypatch.setattr(ikarus_os, "_ask_stream_inner", failing_inner)
    manager = requests.ConversationRequestManager(store)
    created, _ = manager.create(
        conversation_id="conv_cancel_error",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    manager.events(created["request_id"], wait_s=0.2)
    assert provider_blocked.wait(1)
    assert manager.cancel(
        created["request_id"], client_cancel_id="cancel-error"
    )["status"] == "requested"
    release_provider.set()

    status = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "confirmed"
    assert not any(
        row["event"] == "error"
        for row in manager.events(created["request_id"])["events"]
    )


def test_cancel_seam_exception_stays_unknown_and_does_not_fake_confirmation(store):
    release = threading.Event()

    class BrokenCancelStream:
        def __init__(self):
            self.step = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self.step == 0:
                self.step += 1
                return "start", {"intent": "chat"}
            release.wait(1)
            raise StopIteration

        def cancel(self):
            raise RuntimeError("provider cancellation outcome is unknown")

    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *_args, **_kwargs: BrokenCancelStream()
    )
    created, _ = manager.create(
        conversation_id="conv_unknown_cancel",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    manager.events(created["request_id"], wait_s=0.2)

    cancellation = manager.cancel(
        created["request_id"], client_cancel_id="cancel-unknown"
    )
    assert cancellation["status"] == "unknown"
    assert manager.status(created["request_id"])["state"] == "streaming"
    release.set()
    _wait_for(manager, created["request_id"], {"error"})
    assert manager.status(created["request_id"])["cancellation"]["status"] == (
        "unknown"
    )


def test_durable_terminal_race_is_not_relabelled_as_confirmed_cancellation(store):
    provider_blocked = threading.Event()
    release_provider = threading.Event()

    class CancellableStream:
        def __init__(self):
            self.step = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self.step == 0:
                self.step += 1
                return "start", {"intent": "chat"}
            provider_blocked.set()
            release_provider.wait(1)
            raise StopIteration

        def cancel(self):
            return "requested"

    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *_args, **_kwargs: CancellableStream()
    )
    created, _ = manager.create(
        conversation_id="conv_terminal_race",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    manager.events(created["request_id"], wait_s=0.2)
    assert provider_blocked.wait(1)
    assert manager.cancel(
        created["request_id"], client_cancel_id="cancel-race"
    )["status"] == "requested"

    store.spine.mark_completed(
        created["request_id"],
        effect_id="external-terminal-race",
        result={"assistant": "external terminal"},
    )
    release_provider.set()

    deadline = time.time() + 2
    while time.time() < deadline:
        status = manager.status(created["request_id"])
        if status["cancellation"]["status"] == "already_terminal":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("terminal cancellation race was not resolved")
    assert status["state"] == "final"
    assert status["cancellation"]["status"] == "already_terminal"
    assert not any(
        row["event"] == "cancelled"
        for row in manager.events(created["request_id"])["events"]
    )


def test_later_cancel_id_cannot_regress_confirmed_generation(store):
    release = threading.Event()
    provider_blocked = threading.Event()

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
            provider_blocked.set()
            release.wait(1)
            if self.cancelled:
                raise StopIteration
            return "final", {"intent": "chat", "assistant": "too late"}

        def cancel(self):
            self.cancelled = True
            release.set()
            return "requested"

    manager = requests.ConversationRequestManager(
        store, stream_factory=lambda *_args, **_kwargs: CancellableStream()
    )
    created, _ = manager.create(
        conversation_id="conv_multi_cancel",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    assert provider_blocked.wait(1)
    assert manager.cancel(
        created["request_id"], client_cancel_id="cancel-first"
    )["status"] == "requested"
    first_terminal = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert first_terminal["state"] == "cancelled"
    assert first_terminal["cancellation"]["status"] == "confirmed"

    later = manager.cancel(
        created["request_id"], client_cancel_id="cancel-later"
    )
    projected = manager.status(created["request_id"])

    assert later["status"] == "already_terminal"
    assert projected["state"] == "cancelled"
    assert projected["cancellation"]["status"] == "already_terminal"
    assert manager.cancel(
        created["request_id"], client_cancel_id="cancel-first"
    )["status"] == "confirmed"


def test_all_registered_cancel_ids_confirm_and_later_id_cannot_regress(store):
    provider_blocked = threading.Event()
    release_provider = threading.Event()

    def inner(*_args, **_kwargs):
        yield "start", {"intent": "chat"}
        provider_blocked.set()
        release_provider.wait(1)
        yield "final", {"intent": "chat", "assistant": "must be dropped"}

    manager = requests.ConversationRequestManager(
        store,
        stream_factory=lambda *args, **kwargs: ikarus_os._CancellableAskStream(
            iter(inner(*args, **kwargs)), lambda payload: payload
        ),
    )
    created, _ = manager.create(
        conversation_id="conv_many_cancel_ids",
        client_request_id="client-1",
        project="sample",
        message="hello",
    )
    assert provider_blocked.wait(1)

    cancel_ids = ["cancel-a", "cancel-b", "cancel-c"]
    requested = [
        manager.cancel(created["request_id"], client_cancel_id=cancel_id)
        for cancel_id in cancel_ids
    ]
    assert [row["status"] for row in requested] == ["requested"] * 3
    release_provider.set()

    terminal = _wait_for_cancellation(
        manager, created["request_id"], {"confirmed"}
    )
    assert terminal["state"] == "cancelled"
    for cancel_id in cancel_ids:
        row = store.spine.intents_by_effect_key(
            f"generation:{created['request_id']}:cancel:{cancel_id}",
            kind=requests.KIND_CANCELLATION,
            limit=1,
        )[0]
        assert row.result == {"status": "confirmed"}

    later = manager.cancel(
        created["request_id"], client_cancel_id="cancel-after-stop"
    )
    assert later["status"] == "already_terminal"
    assert manager.status(created["request_id"])["state"] == "cancelled"


def test_cancel_rereads_durable_terminal_after_liveness_snapshot(store):
    payload = {
        "conversation_id": "conv_stale",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION, payload, effect_key="conv_stale:client-1"
    )
    manager = requests.ConversationRequestManager(store)

    class CompletesBeforeReturningDead:
        completed = False

        def is_alive(self):
            if not self.completed:
                store.spine.mark_completed(
                    generation.id,
                    effect_id="completed-during-liveness-check",
                    result={"assistant": "done"},
                )
                self.completed = True
            return False

    runtime = requests._Runtime(generation.id)
    runtime.worker = CompletesBeforeReturningDead()
    with manager._lock:
        manager._runtime[generation.id] = runtime

    cancellation = manager.cancel(
        generation.id, client_cancel_id="cancel-after-snapshot"
    )

    assert store.spine.get(generation.id).state == "COMPLETED"
    assert cancellation["status"] == "already_terminal"


def test_cancel_does_not_infer_confirmation_from_external_cancelled_state(
    store, monkeypatch
):
    payload = {
        "conversation_id": "conv_external_cancel",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_external_cancel:client-1",
    )
    manager = requests.ConversationRequestManager(store)

    class LiveWorker:
        live = True

        def is_alive(self):
            return self.live

    worker = LiveWorker()
    runtime = requests._Runtime(generation.id)
    runtime.worker = worker
    with manager._lock:
        manager._runtime[generation.id] = runtime

    original_record_intent = store.spine.record_intent

    def cancel_then_external_failure(kind, *args, **kwargs):
        recorded = original_record_intent(kind, *args, **kwargs)
        if kind == requests.KIND_CANCELLATION:
            store.spine.mark_failed(generation.id, "cancelled_by_user")
        return recorded

    monkeypatch.setattr(
        store.spine, "record_intent", cancel_then_external_failure
    )
    cancellation = manager.cancel(
        generation.id, client_cancel_id="cancel-external-race"
    )

    assert cancellation["status"] == "requested"
    recorded = store.spine.get(cancellation["cancellation_id"])
    assert recorded.state == "INTENDED"
    worker.live = False
    with runtime.condition:
        runtime.terminal = True

    status = manager.status(generation.id)
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "unknown"
    assert store.spine.get(recorded.id).state == "INTENDED"


def test_restart_projects_open_cancellation_unknown_and_get_is_read_only(
    store, monkeypatch
):
    payload = {
        "conversation_id": "conv_restart_open",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_restart_open:client-1",
    )
    cancellation = store.spine.record_intent(
        requests.KIND_CANCELLATION,
        {"request_id": generation.id, "client_cancel_id": "cancel-open"},
        effect_key=f"generation:{generation.id}:cancel:cancel-open",
    )
    restarted = requests.ConversationRequestManager(store)

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("GET projection attempted a ledger write")

    changes_before_get = store.spine._conn.total_changes
    with monkeypatch.context() as guarded:
        guarded.setattr(store.spine, "record_intent", unexpected_write)
        guarded.setattr(store.spine, "record_fact", unexpected_write)
        guarded.setattr(store.spine, "mark_completed", unexpected_write)
        guarded.setattr(store.spine, "mark_failed", unexpected_write)
        status = restarted.status(generation.id)
        events = restarted.events(generation.id)

    assert store.spine._conn.total_changes == changes_before_get
    assert status["state"] == "unknown"
    assert status["cancellation"]["status"] == "unknown"
    assert status["cancellation"]["resolved_at"] is None
    assert events["terminal"] is True
    assert events["status"]["cancellation"]["status"] == "unknown"
    assert store.spine.get(cancellation.id).state == "INTENDED"

    duplicate = restarted.cancel(
        generation.id, client_cancel_id="cancel-open"
    )
    assert duplicate["status"] == "unknown"
    assert store.spine.get(cancellation.id).state == "COMPLETED"


def test_restart_reconciles_open_cancel_against_durable_final(store):
    payload = {
        "conversation_id": "conv_restart_final",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_restart_final:client-1",
    )
    cancellation = store.spine.record_intent(
        requests.KIND_CANCELLATION,
        {"request_id": generation.id, "client_cancel_id": "cancel-final"},
        effect_key=f"generation:{generation.id}:cancel:cancel-final",
    )
    store.spine.mark_completed(
        generation.id,
        effect_id="final-before-restart",
        result={"assistant": "done"},
    )
    restarted = requests.ConversationRequestManager(store)

    status = restarted.status(generation.id)
    assert status["state"] == "final"
    assert status["cancellation"]["status"] == "already_terminal"
    assert store.spine.get(cancellation.id).state == "INTENDED"

    duplicate = restarted.cancel(
        generation.id, client_cancel_id="cancel-final"
    )
    assert duplicate["status"] == "already_terminal"
    assert store.spine.get(cancellation.id).state == "COMPLETED"


def test_restart_keeps_cancelled_generation_without_faking_confirmation(store):
    payload = {
        "conversation_id": "conv_restart_cancelled",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_restart_cancelled:client-1",
    )
    cancellation = store.spine.record_intent(
        requests.KIND_CANCELLATION,
        {"request_id": generation.id, "client_cancel_id": "cancel-crash"},
        effect_key=f"generation:{generation.id}:cancel:cancel-crash",
    )
    store.spine.mark_failed(generation.id, "cancelled_by_user")
    restarted = requests.ConversationRequestManager(store)

    status = restarted.status(generation.id)
    assert status["state"] == "cancelled"
    assert status["cancellation"]["status"] == "unknown"
    assert store.spine.get(cancellation.id).state == "INTENDED"

    duplicate = restarted.cancel(
        generation.id, client_cancel_id="cancel-crash"
    )
    assert duplicate["status"] == "unknown"
    assert store.spine.get(cancellation.id).result == {"status": "unknown"}
    assert restarted.status(generation.id)["state"] == "cancelled"


def test_requested_requires_live_worker_ownership_of_exact_cancel_id(store):
    payload = {
        "conversation_id": "conv_unowned_cancel",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_unowned_cancel:client-1",
    )
    cancellation = store.spine.record_intent(
        requests.KIND_CANCELLATION,
        {"request_id": generation.id, "client_cancel_id": "cancel-unowned"},
        effect_key=f"generation:{generation.id}:cancel:cancel-unowned",
    )
    manager = requests.ConversationRequestManager(store)

    class LiveWorker:
        @staticmethod
        def is_alive():
            return True

    runtime = requests._Runtime(generation.id)
    runtime.worker = LiveWorker()
    runtime.cancel.set()
    # The worker owns a different request, not this durable cancellation.
    runtime.cancel_intent_ids.append(cancellation.id + 1)
    with manager._lock:
        manager._runtime[generation.id] = runtime

    status = manager.status(generation.id)
    assert status["state"] == "streaming"
    assert status["cancellation"]["status"] == "unknown"

    duplicate = manager.cancel(
        generation.id, client_cancel_id="cancel-unowned"
    )
    assert duplicate["status"] == "unknown"
    assert store.spine.get(cancellation.id).result == {"status": "unknown"}


def test_status_snapshot_never_pairs_confirmed_with_cancel_requested(
    store, monkeypatch
):
    payload = {
        "conversation_id": "conv_status_race",
        "client_request_id": "client-1",
        "project": "sample",
        "message": "hello",
        "provider": None,
        "model": None,
        "effort": None,
        "context_refs": [],
    }
    generation = store.spine.record_intent(
        requests.KIND_GENERATION,
        payload,
        effect_key="conv_status_race:client-1",
    )
    cancellation = store.spine.record_intent(
        requests.KIND_CANCELLATION,
        {"request_id": generation.id, "client_cancel_id": "cancel-race"},
        effect_key=f"generation:{generation.id}:cancel:cancel-race",
    )
    manager = requests.ConversationRequestManager(store)
    other_spine = type(store.spine)(store.path)

    class LiveWorker:
        @staticmethod
        def is_alive():
            return True

    runtime = requests._Runtime(generation.id)
    runtime.worker = LiveWorker()
    runtime.cancel.set()
    runtime.cancel_intent_ids.append(cancellation.id)
    with manager._lock:
        manager._runtime[generation.id] = runtime

    # Commit the terminal pair through another SQLite connection after the
    # generation SELECT has established this connection's read snapshot, but
    # before its cancellation SELECT. A compound read must return the wholly
    # pre-transition view; the next request returns the wholly terminal view.
    original_hydrate = store.spine._hydrate
    transitioned = False

    def transition_between_selects(row):
        nonlocal transitioned
        hydrated = original_hydrate(row)
        if int(row["id"]) == generation.id and not transitioned:
            other_spine.mark_failed(generation.id, "cancelled_by_user")
            other_spine.mark_completed(
                cancellation.id,
                effect_id=str(generation.id),
                result={"status": "confirmed"},
            )
            transitioned = True
        return hydrated

    monkeypatch.setattr(store.spine, "_hydrate", transition_between_selects)
    try:
        before = manager.status(generation.id)
        after = manager.status(generation.id)
    finally:
        other_spine.close()

    assert before["state"] == "cancel_requested"
    assert before["cancellation"]["status"] == "requested"
    assert after["state"] == "cancelled"
    assert after["cancellation"]["status"] == "confirmed"
    assert not (
        after["state"] in {"streaming", "cancel_requested"}
        and after["cancellation"]["status"] == "confirmed"
    )


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
