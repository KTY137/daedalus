"""Canonical live-turn transport wiring, with no live model invocation."""
from __future__ import annotations

import threading
import time

import pytest

from daedalus.limit_policy import ExecutionLimitPolicy, MODE_UNBOUNDED_EXECUTION
from daedalus.orchestration.ikarus import shell
from daedalus.orchestration.ikarus.cancellation import CancellationSignal
from daedalus.providers import _ollama_native, ollama
from daedalus.providers._openai_compat import ProviderCancelled


@pytest.mark.parametrize("policy", [ExecutionLimitPolicy(), ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)])
def test_live_ollama_request_binds_residency_cancellation_and_effective_limits(monkeypatch, policy):
    signal = CancellationSignal("one-live-stream")
    calls = []
    starts = []
    def native(**kwargs):
        calls.append(kwargs)
        yield "answer"
    monkeypatch.setattr(_ollama_native, "native_chat_stream", native)
    monkeypatch.setattr(shell, "_provider_start", lambda *a, **k: starts.append((a,k)))
    monkeypatch.setattr(ollama, "warm_model_async", lambda *a, **k: pytest.fail("second transport"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    result = list(shell._ollama_stream("hello", "model", "low", timeout_s=None,
        limit_policy=policy, cancellation=signal))
    assert result == ["answer"]
    assert len(calls) == len(starts) == 1
    assert calls[0]["keep_alive"] == ollama.keep_alive_value()
    assert calls[0]["timeout_s"] is None
    assert (calls[0]["num_predict"] is not None) == policy.enforces("tokens")
    assert calls[0]["cancelled"]() is False
    signal.cancel()
    assert calls[0]["cancelled"]() is True


def test_precancelled_live_ollama_refuses_before_effect_admission(monkeypatch):
    signal = CancellationSignal("cancel-before-admission")
    signal.cancel()
    monkeypatch.setattr(shell, "_provider_start", lambda *a, **k: pytest.fail("effect reached"))
    with pytest.raises(ProviderCancelled):
        list(shell._ollama_stream("hello", "model", "low", cancellation=signal))


def test_stream_cancellation_never_persists_partial_provider_output(monkeypatch):
    signal_seen = []
    entered = threading.Event()
    def inner(*args, cancellation=None, **kwargs):
        signal_seen.append(cancellation)
        yield "start", {"intent": "chat"}
        entered.set()
        while not cancellation.cancelled():
            time.sleep(0.001)
        yield "final", {"intent": "chat", "assistant": "must not persist"}
    monkeypatch.setattr(shell, "_ask_stream_inner", inner)
    monkeypatch.setattr(shell, "_persist_turn", lambda *a, **k: pytest.fail("cancelled final persisted"))
    stream = shell.ask_stream("sample", "hello", conversation_id="cancel-turn")
    observed = []
    worker = threading.Thread(target=lambda: observed.extend(stream))
    worker.start()
    assert entered.wait(2)
    assert stream.cancel() == "requested"
    worker.join(2)
    assert not worker.is_alive()
    assert type(signal_seen[0]) is CancellationSignal
    assert signal_seen[0].cancelled()
    assert [event for event,_ in observed] == ["start"]
    assert stream.cancellation_status == "confirmed"
    assert stream.subprocess_stop_receipt is None
