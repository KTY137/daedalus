from __future__ import annotations

"""One-shot migration for #292 on the canonical Ikarus line.

This file is intentionally removed by the workflow that runs it.  It exists only
so the connector can apply a small, reviewable source transformation without
replacing several large files through the Contents API.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.write_text(text, encoding="utf-8")


def _between(text: str, start: str, end: str, replacement: str, rel: str) -> str:
    try:
        i = text.index(start)
        j = text.index(end, i)
    except ValueError as exc:
        raise SystemExit(f"{rel}: expected patch anchor missing: {exc}") from exc
    return text[:i] + replacement + text[j:]


# 1) The native Ollama transport now owns blocking + streaming chat.  keep_alive
# rides on the SAME /api/chat request as the answer, so no second HTTP effect is
# needed merely to refresh residency.
rel = "daedalus/providers/_ollama_native.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
text = text.replace("from typing import Any\n", "from typing import Any, Iterator\n", 1)
start = "def native_chat(\n"
if start not in text:
    raise SystemExit(f"{rel}: native_chat anchor missing")
prefix = text[: text.index(start)]
new_tail = r'''def _native_chat_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    tools: list | None = None,
    force_json: object = False,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    think: bool | None = None,
    keep_alive: str | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Build the one native ``/api/chat`` request shape used by both modes.

    Keeping this in one helper is more than deduplication: options that affect
    correctness (``num_ctx``, constrained ``format``, ``think`` and especially
    ``keep_alive``) must not silently drift between blocking chat and streaming
    chat.  ``stream`` is the only transport-mode difference.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": _native_messages(messages),
        "stream": bool(stream),
        "options": {"num_ctx": num_ctx or num_ctx_value(), "temperature": temperature},
    }
    if num_predict is not None:
        body["options"]["num_predict"] = max(1, int(num_predict))
    if think is not None:
        body["think"] = bool(think)
    if force_json:
        body["format"] = force_json if isinstance(force_json, dict) else "json"
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    if tools:
        body["tools"] = tools
    return body


def _native_request(host: str, body: dict[str, Any]) -> tuple[str, urllib.request.Request]:
    url = host.rstrip("/") + "/api/chat"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    return url, request


def native_chat(
    *,
    host: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list | None = None,
    # bool keeps every existing caller byte-identical; a dict opts that call
    # into schema-constrained decoding.
    force_json: object = False,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    think: bool | None = None,
    keep_alive: str | None = None,
    timeout_s: float = 300.0,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """POST one non-streaming native ``/api/chat`` request.

    ``keep_alive`` belongs to this request itself.  Callers therefore do not
    need a second ``/api/generate`` warm-up transport to keep the model resident.
    Raises :class:`ProviderHTTPError` on transport/protocol failure.
    """
    body = _native_chat_body(
        model=model, messages=messages, stream=False, tools=tools,
        force_json=force_json, num_ctx=num_ctx, num_predict=num_predict,
        think=think, keep_alive=keep_alive, temperature=temperature,
    )
    url, request = _native_request(host, body)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ProviderHTTPError(
            f"request to {url} timed out after {timeout_s:g}s") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderHTTPError(f"invalid JSON response from {url}: {exc}") from exc

    message = payload.get("message")
    if not isinstance(message, dict):
        raise ProviderHTTPError(f"unexpected response shape: {payload}")
    return _adapt_message(message)


def native_chat_stream(
    *,
    host: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list | None = None,
    force_json: object = False,
    num_ctx: int | None = None,
    num_predict: int | None = None,
    think: bool | None = None,
    keep_alive: str | None = None,
    timeout_s: float = 300.0,
    temperature: float = 0.0,
) -> Iterator[str]:
    """Yield native Ollama text deltas from ONE ``/api/chat`` request.

    Ollama streams newline-delimited JSON.  The response context is owned by
    this generator, so closing/cancelling the consumer closes the HTTP response;
    there is no daemon warm-up thread that can outlive the chat turn.  Residency
    refresh is carried by ``keep_alive`` on this same authorized transport.
    """
    body = _native_chat_body(
        model=model, messages=messages, stream=True, tools=tools,
        force_json=force_json, num_ctx=num_ctx, num_predict=num_predict,
        think=think, keep_alive=keep_alive, temperature=temperature,
    )
    url, request = _native_request(host, body)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            for raw in resp:
                if not raw or not raw.strip():
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ProviderHTTPError(
                        f"invalid streaming frame from {url}: {exc}") from exc
                if payload.get("error"):
                    raise ProviderHTTPError(
                        f"Ollama stream error from {url}: {payload.get('error')}")
                message = payload.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        yield content
                if payload.get("done"):
                    break
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ProviderHTTPError(
            f"request to {url} timed out after {timeout_s:g}s") from exc
'''
_write(rel, prefix + new_tail)


# 2) Ikarus uses that native transport directly.  One _provider_start now maps
# to exactly one socket operation in blocking and streaming modes.
rel = "daedalus/ikarus_os.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
new_blocking = r'''def _ollama(message: str, model: str, effort: str | None,
            context: str = "", *, timeout_s: float = 150.0) -> str | None:
    """One guarded Ollama chat transport, with residency refresh in-band.

    The native ``/api/chat`` endpoint honors ``keep_alive`` while the OpenAI
    compatibility shim does not.  Carrying it on the answer request removes the
    former daemon ``/api/generate`` warm-up: one ``_provider_start`` now
    authorizes exactly one network-capable operation against the exact host.
    """
    from .providers._ollama_native import native_chat
    from .providers.ollama import DEFAULT_HOST, keep_alive_value

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    _provider_start("ollama", endpoint=host, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    try:
        msg = native_chat(
            host=host, model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": _with_context(message, context)}],
            keep_alive=keep_alive_value(), num_predict=_effort_cap(effort),
            temperature=0.3, timeout_s=timeout_s,
        )
        return (msg.get("content") or "").strip() or None
    except Exception:
        return None


'''
text = _between(text, "def _ollama(message: str, model: str, effort: str | None,\n",
                "def _deepseek(message: str, model: str, effort: str | None,\n",
                new_blocking, rel)
new_stream = r'''def _ollama_stream(message: str, model: str, effort: str | None, context: str = "", *, timeout_s: float = 150.0):
    """Yield Ollama deltas from one guarded native ``/api/chat`` transport.

    ``keep_alive`` is part of this same request.  Closing the generator closes
    the response, so cancellation cannot leave a second background warm-up
    socket running after the Voice turn has stopped.
    """
    from .providers._ollama_native import native_chat_stream
    from .providers.ollama import DEFAULT_HOST, keep_alive_value

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    _provider_start("ollama", endpoint=host, model=model)
    system = SYSTEM + ("\nKeep answers short and direct." if (effort or "low").lower() == "low" else "")
    yield from native_chat_stream(
        host=host, model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": _with_context(message, context)}],
        keep_alive=keep_alive_value(), num_predict=_effort_cap(effort),
        temperature=0.3, timeout_s=timeout_s,
    )


'''
text = _between(text, "def _ollama_stream(message: str, model: str, effort: str | None, context: str = \"\", *, timeout_s: float = 150.0):\n",
                "def _deepseek_stream(message: str, model: str, effort: str | None, context: str = \"\", *, timeout_s: float = 150.0):\n",
                new_stream, rel)
_write(rel, text)


# 3) Delete the independently callable warm-up HTTP path entirely.  There is no
# second public transport left that can bypass Ikarus endpoint admission.
rel = "daedalus/providers/ollama.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
text = _between(text, "def warm_model(host: str | None = None, model: str | None = None,\n",
                "def remote_endpoint_consented(host: str | None) -> bool:\n",
                "", rel)
_write(rel, text)


# 4) Update regression tests from the removed warm-up primitive to the single
# transport invariant, including generator-close lifecycle behavior.
rel = "tests/test_ikarus_stream.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
text = text.replace(
    "from daedalus.providers import ollama as ollama_mod\nfrom daedalus.providers._openai_compat import ProviderHTTPError, chat_stream\n",
    "from daedalus.providers import _ollama_native as native_mod\nfrom daedalus.providers import ollama as ollama_mod\nfrom daedalus.providers._openai_compat import ProviderHTTPError, chat_stream\n",
    1,
)
text = text.replace(
    "    def __exit__(self, *a):\n        return False\n",
    "    def __exit__(self, *a):\n        self.close()\n        return False\n",
    1,
)
new_keepalive = r'''class KeepAliveTest(unittest.TestCase):
    """Residency refresh must ride on the answer transport itself."""

    def test_blocking_native_chat_carries_keep_alive_on_same_request(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            resp = _Resp(json.dumps({
                "message": {"role": "assistant", "content": "hi"}
            }).encode("utf-8"))
            resp.status = 200
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen) as up:
            msg = native_mod.native_chat(
                host="http://127.0.0.1:11434", model="m7",
                messages=[{"role": "user", "content": "hello"}],
                keep_alive="30m")

        self.assertEqual(msg["content"], "hi")
        self.assertEqual(up.call_count, 1)
        self.assertTrue(captured["url"].endswith("/api/chat"))
        self.assertNotIn("/api/generate", captured["url"])
        self.assertIs(captured["body"]["stream"], False)
        self.assertEqual(captured["body"]["keep_alive"], "30m")
        self.assertEqual(captured["body"]["model"], "m7")

    def test_streaming_native_chat_carries_keep_alive_on_same_request(self):
        frames = (
            json.dumps({"message": {"role": "assistant", "content": "Hel"}, "done": False}) + "\n"
            + json.dumps({"message": {"role": "assistant", "content": "lo"}, "done": False}) + "\n"
            + json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
        ).encode("utf-8")
        resp = _Resp(frames)
        with mock.patch("urllib.request.urlopen", return_value=resp) as up:
            out = list(native_mod.native_chat_stream(
                host="http://127.0.0.1:11434", model="m7",
                messages=[{"role": "user", "content": "hello"}],
                keep_alive="2h"))
        self.assertEqual(out, ["Hel", "lo"])
        self.assertEqual(up.call_count, 1)
        body = json.loads(up.call_args[0][0].data.decode("utf-8"))
        self.assertIs(body["stream"], True)
        self.assertEqual(body["keep_alive"], "2h")

    def test_closing_stream_closes_the_only_http_response(self):
        frames = (
            json.dumps({"message": {"role": "assistant", "content": "first"}, "done": False}) + "\n"
            + json.dumps({"message": {"role": "assistant", "content": "second"}, "done": False}) + "\n"
        ).encode("utf-8")
        resp = _Resp(frames)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            stream = native_mod.native_chat_stream(
                host="http://127.0.0.1:11434", model="m7",
                messages=[{"role": "user", "content": "hello"}], keep_alive="30m")
            self.assertEqual(next(stream), "first")
            stream.close()
        self.assertTrue(resp.closed)

    def test_env_override(self):
        with mock.patch.dict("os.environ", {"OLLAMA_KEEP_ALIVE": "2h"}):
            self.assertEqual(ollama_mod.keep_alive_value(), "2h")

    def test_legacy_background_warmup_transport_is_gone(self):
        self.assertFalse(hasattr(ollama_mod, "warm_model"))
        self.assertFalse(hasattr(ollama_mod, "warm_model_async"))


'''
text = _between(text, "class KeepAliveTest(unittest.TestCase):\n",
                "class AskStreamTest(unittest.TestCase):\n",
                new_keepalive, rel)
old_blocking = r'''    def test_blocking_ollama_path_also_pins_residency(self):
        """The pin is a side effect only: same reply, but the next turn stays warm."""
        with mock.patch("daedalus.providers.ollama.warm_model_async") as warm, \
             mock.patch("daedalus.ikarus_os.chat_completion", return_value="  hi  "):
            out = ikarus_os._ollama("hello", "m7", "low")
        self.assertEqual(out, "hi")  # unchanged: still stripped text
        warm.assert_called_once()

    def test_blocking_ollama_still_returns_none_on_failure(self):
        with mock.patch("daedalus.providers.ollama.warm_model_async"), \
             mock.patch("daedalus.ikarus_os.chat_completion",
                        side_effect=RuntimeError("dead")):
            self.assertIsNone(ikarus_os._ollama("hello", "m7", "low"))

    def test_effort_caps_preserved(self):
        self.assertEqual(ikarus_os._effort_cap("low"), 300)
        self.assertEqual(ikarus_os._effort_cap("medium"), 700)
        self.assertEqual(ikarus_os._effort_cap("high"), 1400)
        self.assertEqual(ikarus_os._effort_cap(None), 300)
'''
new_blocking_tests = r'''    def test_blocking_ollama_is_one_guarded_native_transport(self):
        with mock.patch.object(ikarus_os, "_provider_start") as start, \
             mock.patch("daedalus.providers._ollama_native.native_chat",
                        return_value={"role": "assistant", "content": "  hi  "}) as chat:
            out = ikarus_os._ollama("hello", "m7", "low")
        self.assertEqual(out, "hi")
        start.assert_called_once_with("ollama", endpoint="http://127.0.0.1:11434", model="m7")
        chat.assert_called_once()
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["keep_alive"], ollama_mod.keep_alive_value())
        self.assertEqual(kwargs["num_predict"], 700)
        self.assertEqual(kwargs["host"], "http://127.0.0.1:11434")

    def test_streaming_ollama_is_one_guarded_native_transport(self):
        with mock.patch.object(ikarus_os, "_provider_start") as start, \
             mock.patch("daedalus.providers._ollama_native.native_chat_stream",
                        return_value=iter(["Hel", "lo"])) as chat:
            out = list(ikarus_os._ollama_stream("hello", "m7", "low"))
        self.assertEqual(out, ["Hel", "lo"])
        start.assert_called_once_with("ollama", endpoint="http://127.0.0.1:11434", model="m7")
        chat.assert_called_once()
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["keep_alive"], ollama_mod.keep_alive_value())
        self.assertEqual(kwargs["num_predict"], 700)

    def test_blocking_ollama_still_returns_none_on_failure(self):
        with mock.patch.object(ikarus_os, "_provider_start"), \
             mock.patch("daedalus.providers._ollama_native.native_chat",
                        side_effect=RuntimeError("dead")):
            self.assertIsNone(ikarus_os._ollama("hello", "m7", "low"))

    def test_effort_caps_preserved(self):
        self.assertEqual(ikarus_os._effort_cap("low"), 700)
        self.assertEqual(ikarus_os._effort_cap("medium"), 1400)
        self.assertEqual(ikarus_os._effort_cap("high"), 2800)
        self.assertEqual(ikarus_os._effort_cap(None), 700)
'''
if old_blocking not in text:
    raise SystemExit(f"{rel}: blocking Ollama regression block changed upstream")
text = text.replace(old_blocking, new_blocking_tests, 1)
_write(rel, text)


# Mechanical postconditions before pytest gets a chance to exercise behavior.
assert "def warm_model(" not in (ROOT / "daedalus/providers/ollama.py").read_text(encoding="utf-8")
assert "warm_model_async" not in (ROOT / "daedalus/ikarus_os.py").read_text(encoding="utf-8")
assert "native_chat_stream" in (ROOT / "daedalus/providers/_ollama_native.py").read_text(encoding="utf-8")
print("issue #292 source migration applied")
