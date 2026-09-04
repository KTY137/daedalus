"""ikarus_os streaming brain + Ollama VRAM residency pin.

No real LLM calls and no real subprocesses: every lane is mocked. Covers the
branches added for the chat-latency fix — SSE delta parsing, the stream-json
frame shape, the fail-closed fallbacks, and the keep_alive pin that must go to
the NATIVE Ollama API (the /v1 shim silently drops it).
"""
import io
import json
import unittest
from unittest import mock

from daedalus import ikarus_os
from daedalus.providers import _ollama_native as native_mod
from daedalus.providers import ollama as ollama_mod
from daedalus.providers._openai_compat import ProviderHTTPError, chat_stream


def _sse(chunks):
    """Build an OpenAI-style streaming body from text pieces."""
    lines = []
    for piece in chunks:
        frame = {"choices": [{"index": 0, "delta": {"content": piece}}]}
        lines.append(f"data: {json.dumps(frame)}\n\n")
    lines.append("data: [DONE]\n\n")
    return io.BytesIO("".join(lines).encode("utf-8"))


class _Resp(io.BytesIO):
    """Context-manager wrapper so urlopen(...) can be used in a `with`."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _resp(chunks):
    return _Resp(_sse(chunks).getvalue())


class ChatStreamTest(unittest.TestCase):
    def test_yields_text_deltas_in_order(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp(["Hel", "lo ", "world"])):
            out = list(chat_stream(base_url="http://x/v1", model="m",
                                   system="s", user="u"))
        self.assertEqual(out, ["Hel", "lo ", "world"])

    def test_stream_true_is_sent(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp(["a"])) as up:
            list(chat_stream(base_url="http://x/v1", model="m", system="s", user="u"))
        body = json.loads(up.call_args[0][0].data.decode("utf-8"))
        self.assertIs(body["stream"], True)

    def test_tolerates_malformed_and_empty_frames(self):
        raw = (b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
               b'\n'
               b': keep-alive\n\n'
               b'data: {not json}\n\n'
               b'data: [DONE]\n\n')
        with mock.patch("urllib.request.urlopen", return_value=_Resp(raw)):
            out = list(chat_stream(base_url="http://x/v1", model="m",
                                   system="s", user="u"))
        self.assertEqual(out, ["ok"])  # bad frames skipped, not fatal

    def test_unreachable_host_raises_provider_error(self):
        import urllib.error

        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")):
            with self.assertRaises(ProviderHTTPError):
                list(chat_stream(base_url="http://x/v1", model="m",
                                 system="s", user="u"))


class KeepAliveTest(unittest.TestCase):
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


class AskStreamTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def _events(self, *a, **kw):
        return list(ikarus_os.ask_stream(*a, **kw))

    def test_deterministic_intent_emits_start_and_final_only(self):
        evs = self._events(self.PROJECT, "what's running?", provider=None)
        names = [e for e, _ in evs]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "final")
        self.assertNotIn("delta", names)
        self.assertEqual(evs[-1][1]["intent"], "status")

    def test_enqueue_still_only_proposes_when_streamed(self):
        evs = self._events(self.PROJECT, "build a login page", provider=None)
        final = evs[-1][1]
        self.assertEqual(final["intent"], "enqueue")
        self.assertTrue(final["action"]["requires_confirmation"])
        self.assertEqual(final["action"]["args"]["lane"], "local_only")

    def test_local_lane_streams_deltas_then_final(self):
        with mock.patch.object(ikarus_os, "_ollama_stream",
                               return_value=iter(["Hel", "lo"])):
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        self.assertEqual([e for e, _ in evs], ["start", "delta", "delta", "final"])
        self.assertEqual([p["text"] for e, p in evs if e == "delta"], ["Hel", "lo"])
        self.assertEqual(evs[-1][1]["assistant"], "Hello")
        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")

    def test_midstream_error_keeps_partial_text_and_marks_interrupted(self):
        def boom():
            yield "partial"
            raise RuntimeError("stream died")

        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()):
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        self.assertEqual(evs[-1][1]["assistant"], "partial")
        self.assertTrue(evs[-1][1]["stream_interrupted"])
        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")

    def test_empty_stream_falls_back_to_resolved_blocking_voice(self):
        fallback = {"assistant": "fallback", "intent": "chat", "provider_used": "ollama_http"}
        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \
             mock.patch.object(ikarus_os, "_chat", return_value=fallback) as blocking:
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        blocking.assert_called_once()
        self.assertEqual(evs[-1][1]["assistant"], "fallback")

    def test_unwired_provider_degrades_to_deterministic(self):
        # codex_cli gained a real chat branch; "gemini" remains genuinely unwired.
        evs = self._events(self.PROJECT, "hello there", provider="gemini")
        self.assertEqual(evs[-1][1]["provider_used"], "unavailable")
        self.assertEqual(evs[-1][1]["intent"], "error")
        self.assertNotIn("delta", [e for e, _ in evs])

    def test_empty_message_is_safe(self):
        evs = self._events(self.PROJECT, "   ", provider="ollama")
        self.assertEqual(evs[-1][0], "final")


class ClaudeStreamFrameTest(unittest.TestCase):
    """Frame shape verified against the installed CLI (2.1.201)."""

    def _fake_proc(self, lines):
        proc = mock.MagicMock()
        proc.stdout = iter(lines)
        proc.stdin = mock.MagicMock()
        proc.poll.return_value = 0
        return proc

    def test_parses_text_deltas_and_ignores_other_frames(self):
        lines = [
            json.dumps({"type": "system", "subtype": "init"}) + "\n",
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_start", "index": 0}}) + "\n",
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hi"}}}) + "\n",
            json.dumps({"type": "stream_event", "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": " there"}}}) + "\n",
            json.dumps({"type": "result", "result": "Hi there"}) + "\n",
        ]
        with mock.patch("shutil.which", return_value="claude"), \
             mock.patch("subprocess.Popen", return_value=self._fake_proc(lines)):
            out = list(ikarus_os._claude_stream("hello"))
        self.assertEqual(out, ["Hi", " there"])

    def test_uses_stream_json_flags(self):
        with mock.patch("shutil.which", return_value="claude"), \
             mock.patch("subprocess.Popen", return_value=self._fake_proc([])) as pop:
            list(ikarus_os._claude_stream("hello"))
        args = pop.call_args[0][0]
        self.assertIn("--output-format", args)
        self.assertIn("stream-json", args)
        self.assertIn("--include-partial-messages", args)
        self.assertIn("--verbose", args)  # required with stream-json in -p mode

    def test_missing_cli_yields_nothing(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(list(ikarus_os._claude_stream("hello")), [])

    def test_spawn_failure_yields_nothing(self):
        with mock.patch("shutil.which", return_value="claude"), \
             mock.patch("subprocess.Popen", side_effect=OSError("no exec")):
            self.assertEqual(list(ikarus_os._claude_stream("hello")), [])


class NonStreamingUnchangedTest(unittest.TestCase):
    """The blocking path must keep working exactly as before."""

    def test_ask_without_an_available_voice_fails_loud_instead_of_silent_fallback(self):
        res = ikarus_os.ask("sunny_garden", "hello there", provider=None)
        self.assertEqual(res["provider_used"], "unavailable")
        self.assertEqual(res["intent"], "error")
        self.assertIn("no available LLM voice", res["assistant"])

    def test_blocking_ollama_is_one_guarded_native_transport(self):
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


if __name__ == "__main__":
    unittest.main()
