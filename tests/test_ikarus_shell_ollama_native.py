"""G1-IKARUS-31: schema-constrained Ollama calls take the native path, cancellable.

Measured 2026-09-05 (G1-IKARUS-26, G1-KERNEL-02): the computer planner reached
Ollama through ``shell._ollama`` -> ``_openai_compat.chat_completion`` on ``/v1``,
where Ollama 0.33.3 ignores ``keep_alive`` (expires +5m), pins ``context_length``
4096 and evicts a natively warmed instance, so every planner call paid the cold
load. ``_ollama_native.native_chat`` honours ``format`` (a JSON schema),
``keep_alive`` and ``options.num_ctx``. Codex (room, 21:56): option B, keep
``num_ctx_value()``, carry the output cap as ``num_predict``, drop the extra
warm-up in the native branch, pass ``ProviderCancelled`` through, and add a
barrier test that a cancelled call sends zero requests.

These tests stand up a loopback fake Ollama that records every request.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from daedalus.kernel.policy.limits import ExecutionLimitPolicy
from daedalus.orchestration.ikarus import shell
from daedalus.providers._ollama_native import num_ctx_value
from daedalus.providers._openai_compat import ProviderCancelled
from daedalus.providers.ollama import keep_alive_value

SCHEMA = {"type": "object", "properties": {"type": {"const": "finish"}, "summary": {"type": "string"}},
          "required": ["type", "summary"], "additionalProperties": False}


class _FakeOllama:
    """Answers /api/chat, /v1/chat/completions and /api/generate; records bodies."""

    def __init__(self, *, delay_s: float = 0.0):
        self.requests: list[tuple[str, dict]] = []
        self.delay_s = delay_s
        self.release = threading.Event()
        self.release.set()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D401 - silence
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append((self.path, body))
                if outer.delay_s:
                    time.sleep(outer.delay_s)
                outer.release.wait()
                if self.path == "/api/chat":
                    payload = {"message": {"role": "assistant", "content": json.dumps({"type": "finish", "summary": "native"})},
                               "done": True}
                elif self.path == "/v1/chat/completions":
                    payload = {"choices": [{"message": {"role": "assistant", "content": "v1 reply"}}]}
                else:
                    payload = {"done": True}
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]


@pytest.fixture
def fake(monkeypatch):
    server = _FakeOllama()
    monkeypatch.setenv("OLLAMA_HOST", server.host)
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    # the warm-up thread of the /v1 branch must not race the assertions
    monkeypatch.setattr(shell, "_provider_start", lambda *a, **k: None)
    try:
        yield server
    finally:
        server.close()


def test_a_schema_call_takes_the_native_path_with_keep_alive_num_ctx_and_the_output_cap(fake):
    reply = shell._ollama("plan", "qwen2.5-coder:7b", "medium", "", timeout_s=30,
                          response_schema=SCHEMA)
    assert json.loads(reply) == {"type": "finish", "summary": "native"}
    assert fake.paths() == ["/api/chat"], fake.paths()
    body = fake.requests[0][1]
    assert body["format"] == SCHEMA
    assert body["keep_alive"] == keep_alive_value()
    assert body["options"]["num_ctx"] == num_ctx_value()
    assert body["options"]["num_predict"] == shell._EFFORT_CAP["medium"]
    assert body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_the_native_branch_sends_no_separate_warm_up_request(fake):
    shell._ollama("plan", "qwen2.5-coder:7b", "low", "", timeout_s=30, response_schema=SCHEMA)
    time.sleep(0.3)  # a stray warm_model_async thread would land here
    assert "/api/generate" not in fake.paths(), fake.paths()


def test_a_disabled_token_axis_sends_no_num_predict(fake):
    policy = ExecutionLimitPolicy(mode="unbounded_execution")
    shell._ollama("plan", "qwen2.5-coder:7b", "high", "", timeout_s=None,
                  limit_policy=policy, response_schema=SCHEMA)
    body = fake.requests[0][1]
    assert "num_predict" not in body["options"]
    assert body["options"]["num_ctx"] == num_ctx_value()


def test_a_schema_less_call_still_takes_the_v1_route_with_max_tokens(fake):
    reply = shell._ollama("hello", "qwen2.5-coder:7b", "low", "", timeout_s=30)
    assert reply == "v1 reply"
    time.sleep(0.3)  # let the warm-up thread land before counting
    paths = fake.paths()
    assert "/v1/chat/completions" in paths, paths
    assert "/api/chat" not in paths, paths
    v1 = next(body for path, body in fake.requests if path == "/v1/chat/completions")
    assert v1["max_tokens"] == shell._EFFORT_CAP["low"]


def test_a_probe_that_fires_during_a_hanging_native_call_raises_provider_cancelled(monkeypatch):
    server = _FakeOllama()
    server.release.clear()  # the reply never comes until we say so
    monkeypatch.setenv("OLLAMA_HOST", server.host)
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.setattr(shell, "_provider_start", lambda *a, **k: None)
    fired = threading.Event()
    threading.Timer(0.4, fired.set).start()
    started = time.monotonic()
    try:
        with pytest.raises(ProviderCancelled):
            shell._ollama("plan", "qwen2.5-coder:7b", "low", "", timeout_s=None,
                          response_schema=SCHEMA, cancelled=fired.is_set)
        assert time.monotonic() - started < 5.0, "the caller waited for the peer instead of the probe"
        assert server.paths() == ["/api/chat"], "the request was sent exactly once"
    finally:
        server.close()


def test_an_already_cancelled_call_sends_zero_requests(fake):
    with pytest.raises(ProviderCancelled):
        shell._ollama("plan", "qwen2.5-coder:7b", "low", "", timeout_s=30,
                      response_schema=SCHEMA, cancelled=lambda: True)
    time.sleep(0.2)
    assert fake.requests == [], fake.paths()


def test_llm_forwards_the_probe_to_the_ollama_route(monkeypatch):
    seen = {}

    def fake_ollama(message, model, effort, context="", **kwargs):
        seen.update(kwargs)
        return "ok"

    monkeypatch.setattr(shell, "_ollama", fake_ollama)
    monkeypatch.setattr(shell, "_project_context", lambda *a, **k: shell._EMPTY_CTX)
    monkeypatch.setattr(shell, "_conversation_context", lambda *a, **k: "")
    monkeypatch.setattr(shell, "_merge_model_context", lambda *a, **k: "")
    probe = lambda: False  # noqa: E731
    text, _model, _ctx = shell._llm("ollama_http", "plan", model="m", effort="low", project=None,
                                    timeout_s=5, response_schema=SCHEMA, cancelled=probe)
    assert text == "ok"
    assert seen["cancelled"] is probe
    assert seen["response_schema"] == SCHEMA
