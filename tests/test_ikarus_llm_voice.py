from __future__ import annotations

import inspect

from daedalus import ikarus_os
from daedalus.limit_policy import ExecutionLimitPolicy
from daedalus.orchestration.llm_client import LLMSelection


class _FakeClient:
    def __init__(self, provider="claude_code_cli"):
        self.provider = provider
    def resolve(self, requested=None):
        return LLMSelection(self.provider, "auto", True, 33.0, 1, "test")


def _parameter_contract(func):
    return [(p.name, p.kind) for p in inspect.signature(func).parameters.values()]


def _assert_mirrors_real_llm(stub) -> None:
    """Refuse a double that no longer matches the function it stands in for.

    A stale double is how this guard went blind: the product grew an
    ``additional_context`` keyword, the stubs kept the older contract, and both
    tests died in a ``TypeError`` inside ``_chat`` before reaching a single
    policy assertion.  Comparing the parameter contract of the double against
    the real ``ikarus_os._llm`` means the next signature change fails here,
    naming the drift, instead of silently disarming the assertions below.
    """

    assert _parameter_contract(stub) == _parameter_contract(ikarus_os._llm)


def test_chat_auto_route_uses_llm_client_and_records_resolved_provider(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient())
    seen = {}
    def fake_llm(provider, message, model=None, effort=None, project=None, *,
                 conversation_id=None, timeout_s=150.0, limit_policy=None,
                 additional_context=""):
        seen.update(provider=provider, conversation_id=conversation_id,
                    timeout_s=timeout_s, limit_policy=limit_policy)
        return "hello from model", "claude-test", ikarus_os._EMPTY_CTX
    _assert_mirrors_real_llm(fake_llm)
    monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
    out = ikarus_os._chat("project", "hello", None, conversation_id="conv_test")
    assert out["assistant"] == "hello from model"
    assert out["provider_used"] == "claude_code_cli"
    assert out["model_used"] == "claude-test"
    assert seen["provider"] == "claude_code_cli"
    assert seen["conversation_id"] == "conv_test"
    assert seen["timeout_s"] == 33.0
    assert seen["limit_policy"].mode == "bounded"


def test_chat_without_available_llm_is_loud_not_fake_deterministic(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient(provider=None))
    out = ikarus_os._chat("project", "hello", None)
    assert out["intent"] == "error"
    assert out["provider_used"] == "unavailable"
    assert "LLM" in out["assistant"]


def test_chat_unbounded_policy_removes_attempt_timeout_and_token_caps(monkeypatch):
    policy = ExecutionLimitPolicy(mode="unbounded_execution")

    class UnboundedClient:
        limit_policy = policy

        def resolve(self, requested=None):
            return LLMSelection(
                "claude_code_cli", "auto", True, None, None, "test"
            )

    calls = []

    def fake_llm(provider, message, model=None, effort=None, project=None, *,
                 conversation_id=None, timeout_s=150.0, limit_policy=None,
                 additional_context=""):
        calls.append((timeout_s, limit_policy))
        if len(calls) < 4:
            return None, "claude-test", ikarus_os._EMPTY_CTX
        return "fourth attempt", "claude-test", ikarus_os._EMPTY_CTX

    _assert_mirrors_real_llm(fake_llm)
    monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
    out = ikarus_os._chat(
        "project", "hello", None, voice_client=UnboundedClient()
    )

    assert out["assistant"] == "fourth attempt"
    assert out["llm"]["attempts"] == 4
    assert out["llm"]["max_attempts"] is None
    assert out["llm"]["timeout_s"] is None
    assert all(timeout is None for timeout, _ in calls)
    assert all(captured is policy for _, captured in calls)
    assert ikarus_os._generation_extra("high", policy) is None
