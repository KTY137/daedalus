# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from daedalus import ikarus_os
from daedalus.llm_client import LLMSelection


class _FakeClient:
    def __init__(self, provider="claude_code_cli"):
        self.provider = provider
    def resolve(self, requested=None):
        return LLMSelection(self.provider, "auto", True, 33.0, 1, "test")


def test_chat_auto_route_uses_llm_client_and_records_resolved_provider(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient())
    seen = {}
    def fake_llm(provider, message, model=None, effort=None, project=None, conversation_id=None, timeout_s=None):
        seen.update(provider=provider, conversation_id=conversation_id, timeout_s=timeout_s)
        return "hello from model", "claude-test", ikarus_os._EMPTY_CTX
    monkeypatch.setattr(ikarus_os, "_llm", fake_llm)
    out = ikarus_os._chat("project", "hello", None, conversation_id="conv_test")
    assert out["assistant"] == "hello from model"
    assert out["provider_used"] == "claude_code_cli"
    assert out["model_used"] == "claude-test"
    assert seen == {"provider": "claude_code_cli", "conversation_id": "conv_test", "timeout_s": 33.0}


def test_chat_without_available_llm_is_loud_not_fake_deterministic(monkeypatch):
    monkeypatch.setattr(ikarus_os, "_voice_client", lambda: _FakeClient(provider=None))
    out = ikarus_os._chat("project", "hello", None)
    assert out["intent"] == "error"
    assert out["provider_used"] == "unavailable"
    assert "LLM" in out["assistant"]
