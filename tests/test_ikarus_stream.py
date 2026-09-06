"""ikarus_os streaming brain + Ollama VRAM residency pin.

No real LLM calls and no real subprocesses: every lane is mocked. Covers the
branches added for the chat-latency fix — SSE delta parsing, the stream-json
frame shape, the fail-closed fallbacks, and the keep_alive pin that must go to
the NATIVE Ollama API (the /v1 shim silently drops it).
"""
import io
import json
import threading
import time
import unittest
from unittest import mock

from daedalus.orchestration.ikarus import shell as ikarus_os
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
    """The measured trap: /v1/chat/completions DROPS keep_alive, so the pin has
    to hit the native /api/generate endpoint or residency never changes."""

    def test_pin_targets_native_api_with_keep_alive(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            resp = _Resp(b"{}")
            resp.status = 200
            return resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = ollama_mod.warm_model(host="http://127.0.0.1:11434", model="m7")

        self.assertTrue(ok)
        self.assertTrue(captured["url"].endswith("/api/generate"))
        self.assertNotIn("/v1/", captured["url"])
        self.assertEqual(ollama_mod.DEFAULT_KEEP_ALIVE, "30m")
        self.assertEqual(
            captured["body"]["keep_alive"], ollama_mod.DEFAULT_KEEP_ALIVE
        )
        self.assertEqual(captured["body"]["model"], "m7")

    def test_env_override(self):
        with mock.patch.dict("os.environ", {"OLLAMA_KEEP_ALIVE": "2h"}):
            self.assertEqual(ollama_mod.keep_alive_value(), "2h")

    def test_zero_disables_pin_without_calling_out(self):
        with mock.patch("urllib.request.urlopen") as up:
            self.assertFalse(ollama_mod.warm_model(keep_alive="0"))
        up.assert_not_called()

    def test_pin_failure_is_never_fatal(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertFalse(ollama_mod.warm_model(model="m"))


class AskStreamTest(unittest.TestCase):
    PROJECT = "sunny_garden"
    ANALYSIS_PROMPT = (
        "Schau dir den aktuellen Projektzustand an. Nenne die drei wichtigsten "
        "nächsten Schritte und erkläre kurz, warum."
    )

    def _events(self, *a, **kw):
        return list(ikarus_os.ask_stream(*a, **kw))

    def test_deterministic_intent_emits_start_and_final_only(self):
        evs = self._events(self.PROJECT, "what's running?", provider=None)
        names = [e for e, _ in evs]
        self.assertEqual(names[0], "start")
        self.assertEqual(names[-1], "final")
        self.assertNotIn("delta", names)
        self.assertEqual(evs[-1][1]["intent"], "status")
        self.assertEqual(evs[-1][1]["delivery_mode"], "stream")
        self.assertIs(evs[-1][1]["stream_interrupted"], False)

    def test_enqueue_still_only_proposes_when_streamed(self):
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "local_only"}):
            evs = self._events(self.PROJECT, "build a login page", provider=None)
        final = evs[-1][1]
        self.assertEqual(final["intent"], "enqueue")
        self.assertTrue(final["action"]["requires_confirmation"])
        self.assertEqual(final["action"]["args"]["lane"], "local_only")

    def test_answer_shaped_german_analysis_uses_the_selected_voice(self):
        with mock.patch.object(ikarus_os, "_ollama_stream",
                               return_value=iter(["Drei", " Schritte"])) as voice:
            evs = self._events(
                self.PROJECT, self.ANALYSIS_PROMPT, provider="ollama")
        voice.assert_called_once()
        self.assertEqual(
            [event for event, _ in evs],
            ["start", "delta", "delta", "final"],
        )
        final = evs[-1][1]
        self.assertEqual(final["intent"], "chat")
        self.assertEqual(final["shell"], ikarus_os.SHELL_VOICE)
        self.assertEqual(final["assistant"], "Drei Schritte")
        self.assertNotIn("action", final)
        self.assertNotIn("act_offer", final)

    def test_explicit_mutation_with_explanation_stays_confirm_gated(self):
        message = (
            "Prüf die Tests und fix den Fehler. "
            "Erklär danach warum."
        )
        with mock.patch.object(ikarus_os.core, "team_config",
                               return_value={"default_lane": "local_only"}), \
             mock.patch.object(ikarus_os, "_ollama_stream") as voice:
            evs = self._events(self.PROJECT, message, provider="ollama")
        voice.assert_not_called()
        final = evs[-1][1]
        self.assertEqual(final["intent"], "enqueue")
        self.assertEqual(final["shell"], ikarus_os.SHELL_HAND)
        self.assertTrue(final["action"]["requires_confirmation"])

    def test_local_lane_streams_deltas_then_final(self):
        with mock.patch.object(ikarus_os, "_ollama_stream",
                               return_value=iter(["Hel", "lo"])):
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        self.assertEqual([e for e, _ in evs], ["start", "delta", "delta", "final"])
        self.assertEqual([p["text"] for e, p in evs if e == "delta"], ["Hel", "lo"])
        self.assertEqual(evs[-1][1]["assistant"], "Hello")
        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")

    def test_cancel_before_first_iteration_is_supported_and_never_persists(self):
        class TrackableInner:
            def __init__(self):
                self.next_calls = 0
                self.close_calls = 0

            def __iter__(self):
                return self

            def __next__(self):
                self.next_calls += 1
                return "final", {"intent": "chat", "assistant": "too late"}

            def close(self):
                self.close_calls += 1

        inner = TrackableInner()
        with mock.patch.object(ikarus_os, "_ask_stream_inner", return_value=inner), \
                mock.patch.object(ikarus_os, "_persist_turn") as persist:
            stream = ikarus_os.ask_stream(
                self.PROJECT, "hello", conversation_id="conv_cancel"
            )
            self.assertIs(iter(stream), stream)
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_REQUESTED)
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_REQUESTED)
            self.assertEqual(list(stream), [])
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_CONFIRMED)

        self.assertEqual(inner.next_calls, 0)
        self.assertEqual(inner.close_calls, 1)
        persist.assert_not_called()

    def test_cancel_after_delta_drops_final_and_closes_locally(self):
        inner = iter([
            ("start", {"intent": "chat"}),
            ("delta", {"text": "partial"}),
            ("final", {"intent": "chat", "assistant": "partial done"}),
        ])
        with mock.patch.object(ikarus_os, "_ask_stream_inner", return_value=inner), \
                mock.patch.object(ikarus_os, "_persist_turn") as persist:
            stream = ikarus_os.ask_stream(
                self.PROJECT, "hello", conversation_id="conv_cancel"
            )
            self.assertEqual(next(stream)[0], "start")
            self.assertEqual(next(stream), ("delta", {"text": "partial"}))
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_REQUESTED)
            self.assertEqual(list(stream), [])

        persist.assert_not_called()

    def test_cancel_wins_a_blocked_final_race_without_claiming_hard_kill(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingFinal:
            def __init__(self):
                self.close_calls = 0

            def __iter__(self):
                return self

            def __next__(self):
                entered.set()
                release.wait(1)
                return "final", {"intent": "chat", "assistant": "too late"}

            def close(self):
                self.close_calls += 1

        inner = BlockingFinal()
        delivered = []
        failures = []
        with mock.patch.object(ikarus_os, "_ask_stream_inner", return_value=inner), \
                mock.patch.object(ikarus_os, "_persist_turn") as persist:
            stream = ikarus_os.ask_stream(
                self.PROJECT, "hello", conversation_id="conv_cancel"
            )

            def drive():
                try:
                    delivered.extend(stream)
                except Exception as exc:  # pragma: no cover - assertion capture
                    failures.append(exc)

            worker = threading.Thread(target=drive)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_REQUESTED)
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_REQUESTED)
            self.assertEqual(inner.close_calls, 1)
            release.set()
            worker.join(1)

            self.assertFalse(worker.is_alive())
            self.assertEqual(stream.cancel(), ikarus_os.STREAM_CANCEL_CONFIRMED)

        self.assertEqual(delivered, [])
        self.assertEqual(failures, [])
        persist.assert_not_called()

    def test_final_commit_wins_the_race_atomically(self):
        persist_entered = threading.Event()
        release_persist = threading.Event()
        delivered = []
        cancel_outcomes = []

        def persist(*_args, **_kwargs):
            persist_entered.set()
            release_persist.wait(1)

        with mock.patch.object(
            ikarus_os,
            "_ask_stream_inner",
            return_value=iter([
                ("final", {"intent": "chat", "assistant": "committed"})
            ]),
        ), mock.patch.object(ikarus_os, "_persist_turn", side_effect=persist) as saved:
            stream = ikarus_os.ask_stream(
                self.PROJECT, "hello", conversation_id="conv_final"
            )
            worker = threading.Thread(target=lambda: delivered.append(next(stream)))
            worker.start()
            self.assertTrue(persist_entered.wait(1))
            canceller = threading.Thread(
                target=lambda: cancel_outcomes.append(stream.cancel())
            )
            canceller.start()
            time.sleep(0.02)
            self.assertTrue(canceller.is_alive())
            release_persist.set()
            worker.join(1)
            canceller.join(1)

        self.assertEqual(delivered[0][0], "final")
        self.assertEqual(
            cancel_outcomes, [ikarus_os.STREAM_CANCEL_ALREADY_TERMINAL]
        )
        saved.assert_called_once()

    def test_midstream_error_keeps_partial_without_blocking_retry(self):
        def boom():
            yield "partial"
            raise RuntimeError("stream died")

        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()), \
             mock.patch.object(ikarus_os, "_chat",
                               return_value={"assistant": "fallback", "intent": "chat"}) as blocking:
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        blocking.assert_not_called()
        self.assertEqual(evs[-1][1]["assistant"], "partial")
        self.assertTrue(evs[-1][1]["stream_interrupted"])
        self.assertEqual(evs[-1][1]["delivery_mode"], "stream")

    def test_empty_stream_is_interrupted_without_blocking_retry(self):
        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \
             mock.patch.object(ikarus_os, "_chat",
                               return_value={"assistant": "fallback", "intent": "chat"}) as blocking:
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        blocking.assert_not_called()
        self.assertNotEqual(evs[-1][1]["assistant"], "fallback")
        self.assertTrue(evs[-1][1]["stream_interrupted"])
        self.assertIn("not automatically retried", evs[-1][1]["assistant"])

    def test_unwired_provider_fails_closed(self):
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
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command",
                        return_value="claude"), \
             mock.patch("subprocess.Popen", return_value=self._fake_proc(lines)):
            out = list(ikarus_os._claude_stream("hello"))
        self.assertEqual(out, ["Hi", " there"])

    def test_uses_stream_json_flags(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command",
                        return_value="claude"), \
             mock.patch("subprocess.Popen", return_value=self._fake_proc([])) as pop:
            list(ikarus_os._claude_stream("hello"))
        args = pop.call_args[0][0]
        self.assertIn("--output-format", args)
        self.assertIn("stream-json", args)
        self.assertIn("--include-partial-messages", args)
        self.assertIn("--verbose", args)  # required with stream-json in -p mode

    def test_missing_cli_yields_nothing(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command",
                        return_value=None), \
             mock.patch.object(ikarus_os, "_provider_start") as provider_start, \
             mock.patch("subprocess.Popen") as popen:
            self.assertEqual(list(ikarus_os._claude_stream("hello")), [])
        provider_start.assert_not_called()
        popen.assert_not_called()

    def test_spawn_failure_yields_nothing(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command",
                        return_value="claude"), \
             mock.patch("subprocess.Popen", side_effect=OSError("no exec")):
            self.assertEqual(list(ikarus_os._claude_stream("hello")), [])


class NonStreamingUnchangedTest(unittest.TestCase):
    """The blocking path must keep working exactly as before."""

    def test_ask_still_answers_deterministically(self):
        res = ikarus_os.ask(
            "sunny_garden", "hello there", provider="deterministic"
        )
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertIn("Ikarus", res["assistant"])
        self.assertEqual(res["delivery_mode"], "blocking")
        self.assertIs(res["stream_interrupted"], False)

    def test_blocking_ollama_path_also_pins_residency(self):
        """The pin is a side effect only: same reply, but the next turn stays warm."""
        with mock.patch("daedalus.providers.ollama.warm_model_async") as warm, \
             mock.patch("daedalus.orchestration.ikarus.shell.chat_completion", return_value="  hi  "):
            out = ikarus_os._ollama("hello", "m7", "low")
        self.assertEqual(out, "hi")  # unchanged: still stripped text
        warm.assert_called_once()

    def test_blocking_ollama_still_returns_none_on_failure(self):
        with mock.patch("daedalus.providers.ollama.warm_model_async"), \
             mock.patch("daedalus.orchestration.ikarus.shell.chat_completion",
                        side_effect=RuntimeError("dead")):
            self.assertIsNone(ikarus_os._ollama("hello", "m7", "low"))

    def test_effort_caps_preserved(self):
        self.assertEqual(ikarus_os._effort_cap("low"), 700)
        self.assertEqual(ikarus_os._effort_cap("medium"), 1400)
        self.assertEqual(ikarus_os._effort_cap("high"), 2800)
        self.assertEqual(ikarus_os._effort_cap(None), 700)


if __name__ == "__main__":
    unittest.main()
