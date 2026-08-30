from __future__ import annotations

from daedalus.llm_client import IkarusLLMClient, LLMRequest, LLMResponse, LLMUnavailable
from daedalus.limit_policy import ExecutionLimitPolicy, MODE_UNBOUNDED_EXECUTION


def test_auto_selects_first_available_model_not_deterministic():
    seen = []
    def probe(runtime_id):
        seen.append(runtime_id)
        return {"available": runtime_id == "ollama_http", "last_error": "off"}
    client = IkarusLLMClient(environ={}, status_probe=probe)
    selection = client.resolve(None)
    assert selection.provider == "ollama_http"
    assert selection.auto_selected is True
    assert "deterministic" not in seen


def test_explicit_deterministic_is_still_possible_but_never_auto():
    client = IkarusLLMClient(environ={}, status_probe=lambda _: {"available": False})
    explicit = client.resolve("deterministic")
    automatic = client.resolve(None)
    assert explicit.provider == "deterministic"
    assert explicit.auto_selected is False
    assert automatic.provider is None


def test_environment_can_choose_voice_without_code_change():
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "codex", "DAEDALUS_IKARUS_TIMEOUT_S": "44"},
        status_probe=lambda _: {"available": False},
    )
    selection = client.resolve(None)
    assert selection.provider == "codex_cli"
    assert selection.timeout_s == 44
    assert selection.auto_selected is True


def test_complete_retries_only_when_operator_opted_in():
    calls = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude", "DAEDALUS_IKARUS_RETRIES": "1"},
        status_probe=lambda _: {"available": True},
    )
    def invoke(provider, request, timeout):
        calls.append((provider, timeout))
        if len(calls) == 1:
            return None
        return LLMResponse("ok", provider, "model")
    response = client.complete(LLMRequest("hello"), invoke)
    assert response.text == "ok"
    assert response.attempts == 2
    assert len(calls) == 2


def test_tool_shapes_are_data_not_implicit_execution():
    request = LLMRequest("plan", tools=({"name": "queue_task"},))
    called = []
    client = IkarusLLMClient(environ={"DAEDALUS_IKARUS_PROVIDER": "claude"})
    response = client.complete(request, lambda provider, req, timeout: called.append(req.tools) or "proposal")
    assert response.text == "proposal"
    assert called == [({"name": "queue_task"},)]


def test_unbounded_policy_removes_wall_time_and_retry_caps_without_a_sentinel():
    calls = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude"},
        status_probe=lambda _: {"available": True},
        limit_policy=ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION),
    )

    def invoke(provider, request, timeout):
        calls.append((provider, timeout))
        return "eventual answer" if len(calls) == 4 else None

    selection = client.resolve()
    response = client.complete(LLMRequest("keep trying"), invoke)

    assert selection.timeout_s is None
    assert selection.max_attempts is None
    assert response.text == "eventual answer"
    assert response.attempts == 4
    assert calls == [("claude_code_cli", None)] * 4
