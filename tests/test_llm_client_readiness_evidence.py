from __future__ import annotations

from daedalus.orchestration.llm_client import IkarusLLMClient


def test_auto_skips_stale_positive_runtime_observation():
    def probe(runtime_id: str):
        if runtime_id == "claude_code_cli":
            return {
                "id": runtime_id,
                "available": True,
                "measured_age_s": 30.0,
            }
        if runtime_id == "ollama_http":
            return {
                "id": runtime_id,
                "available": True,
                "measured_age_s": 0.25,
            }
        return {"id": runtime_id, "available": False, "last_error": "off"}

    selection = IkarusLLMClient(environ={}, status_probe=probe).resolve(None)

    assert selection.provider == "ollama_http"
    assert selection.auto_selected is True
    assert "stale runtime observation" in selection.reason


def test_auto_does_not_treat_truthy_string_as_available_runtime():
    def probe(runtime_id: str):
        if runtime_id == "claude_code_cli":
            return {"id": runtime_id, "available": "false"}
        if runtime_id == "ollama_http":
            return {"id": runtime_id, "available": True}
        return {"id": runtime_id, "available": False, "last_error": "off"}

    selection = IkarusLLMClient(environ={}, status_probe=probe).resolve(None)

    assert selection.provider == "ollama_http"
    assert "'available' must be a boolean" in selection.reason


def test_auto_probe_exception_is_unavailable_not_chat_failure():
    def probe(runtime_id: str):
        if runtime_id == "claude_code_cli":
            raise RuntimeError("status source unreadable")
        if runtime_id == "ollama_http":
            return {"id": runtime_id, "available": True}
        return {"id": runtime_id, "available": False, "last_error": "off"}

    selection = IkarusLLMClient(environ={}, status_probe=probe).resolve(None)

    assert selection.provider == "ollama_http"
    assert "status source unreadable" in selection.reason


def test_auto_rejects_runtime_observation_for_wrong_identity():
    def probe(runtime_id: str):
        if runtime_id == "claude_code_cli":
            return {"id": "codex_cli", "available": True}
        if runtime_id == "ollama_http":
            return {"id": runtime_id, "available": True}
        return {"id": runtime_id, "available": False, "last_error": "off"}

    selection = IkarusLLMClient(environ={}, status_probe=probe).resolve(None)

    assert selection.provider == "ollama_http"
    assert "identity mismatch" in selection.reason


def test_voice_requests_its_own_freshness_ttl_from_runtime_registry(monkeypatch):
    from daedalus.orchestration import runtime_registry

    seen: list[tuple[str, float | None]] = []

    def cached(runtime_id: str, *, ttl_s: float | None = None):
        seen.append((runtime_id, ttl_s))
        return {
            "id": runtime_id,
            "available": False,
            "last_error": "not ready",
            "measured_age_s": 0.0,
        }

    monkeypatch.setattr(runtime_registry, "cached_runtime_status", cached)
    client = IkarusLLMClient(environ={})

    selection = client.resolve("claude")

    assert selection.provider is None
    assert seen == [("claude_code_cli", 30.0)]
