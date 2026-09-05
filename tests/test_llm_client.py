from __future__ import annotations

import pytest

from daedalus.llm_client import IkarusLLMClient, LLMRequest, LLMResponse, LLMUnavailable


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


def test_environment_can_pin_auto_voice_to_deterministic_without_runtime_probes():
    seen = []

    def probe(runtime_id):
        seen.append(runtime_id)
        return {"available": True}

    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "deterministic"},
        status_probe=probe,
    )
    selection = client.resolve(None)

    assert selection.provider == "deterministic"
    assert selection.requested == "auto"
    assert selection.auto_selected is True
    assert selection.max_attempts == 1
    assert selection.reason == "configured deterministic Voice policy"
    assert seen == []


def test_environment_can_choose_available_voice_without_code_change():
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "codex", "DAEDALUS_IKARUS_TIMEOUT_S": "44"},
        status_probe=lambda runtime_id: {"available": runtime_id == "codex_cli", "last_error": "off"},
    )
    selection = client.resolve(None)
    assert selection.provider == "codex_cli"
    assert selection.timeout_s == 44
    assert selection.auto_selected is True
    assert selection.reason == "configured provider is available"


def test_auto_falls_back_when_configured_provider_is_unavailable():
    seen = []

    def probe(runtime_id):
        seen.append(runtime_id)
        if runtime_id == "claude_code_cli":
            return {"available": False, "last_error": "Claude execution refused: unsafe launcher"}
        return {"available": runtime_id == "ollama_http", "last_error": "off"}

    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude"},
        status_probe=probe,
    )
    selection = client.resolve(None)

    assert selection.provider == "ollama_http"
    assert selection.auto_selected is True
    assert seen.count("claude_code_cli") == 1
    assert "Claude execution refused" in selection.reason


def test_explicit_unavailable_provider_is_refused_before_transport_selection():
    client = IkarusLLMClient(
        environ={},
        status_probe=lambda runtime_id: {
            "available": False,
            "last_error": "Claude execution refused: Windows .cmd/.bat launchers reparse argv",
        },
    )
    selection = client.resolve("claude")

    assert selection.provider is None
    assert selection.auto_selected is False
    assert "Windows .cmd/.bat" in selection.reason


def test_complete_does_not_invoke_an_explicit_unavailable_provider():
    called = []
    client = IkarusLLMClient(
        environ={},
        status_probe=lambda _: {"available": False, "last_error": "not executable"},
    )

    with pytest.raises(LLMUnavailable, match="explicit provider is unavailable"):
        client.complete(
            LLMRequest("hello"),
            lambda provider, request, timeout: called.append(provider) or "should-not-run",
            requested="claude",
        )

    assert called == []


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


def test_complete_preserves_authoritative_refusal_without_retrying():
    class Refused(RuntimeError):
        def __init__(self):
            super().__init__("effect denied")
            self.receipt = {
                "verdict": "deny",
                "receipt_sha256": "deadbeef",
                "connected": False,
                "spawned": False,
            }

    calls = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude", "DAEDALUS_IKARUS_RETRIES": "2"},
        status_probe=lambda _: {"available": True},
    )

    def invoke(provider, request, timeout):
        calls.append(provider)
        raise Refused()

    with pytest.raises(Refused) as caught:
        client.complete(LLMRequest("hello"), invoke)

    assert calls == ["claude_code_cli"]
    assert caught.value.receipt["receipt_sha256"] == "deadbeef"
    assert caught.value.receipt["spawned"] is False


def test_complete_still_retries_non_authoritative_transport_errors_when_opted_in():
    calls = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude", "DAEDALUS_IKARUS_RETRIES": "1"},
        status_probe=lambda _: {"available": True},
    )

    def invoke(provider, request, timeout):
        calls.append(provider)
        if len(calls) == 1:
            raise RuntimeError("temporary transport failure")
        return "recovered"

    response = client.complete(LLMRequest("hello"), invoke)

    assert response.text == "recovered"
    assert response.attempts == 2
    assert calls == ["claude_code_cli", "claude_code_cli"]


def test_tool_shapes_are_data_not_implicit_execution():
    request = LLMRequest("plan", tools=({"name": "queue_task"},))
    called = []
    client = IkarusLLMClient(
        environ={"DAEDALUS_IKARUS_PROVIDER": "claude"},
        status_probe=lambda _: {"available": True},
    )
    response = client.complete(request, lambda provider, req, timeout: called.append(req.tools) or "proposal")
    assert response.text == "proposal"
    assert called == [({"name": "queue_task"},)]