from __future__ import annotations

"""Align stale Ikarus stream/boundary assertions with the current runtime client.

Runs after ``_ikarus_issue292_migration.py`` and is removed in the verified
commit.  These are contract corrections exposed by running the previously
unexercised full stream file, not product behavior changes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, rel: str) -> str:
    if old not in text:
        raise SystemExit(f"{rel}: expected fixup anchor missing: {old[:100]!r}")
    return text.replace(old, new, 1)


rel = "tests/test_ikarus_stream.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        self.assertEqual(evs[-1][1]["provider_used"], "ollama")\n',
    '        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")\n',
    rel,
)
old = '''    def test_midstream_error_falls_back_to_blocking(self):
        def boom():
            yield "partial"
            raise RuntimeError("stream died")

        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()), \\
             mock.patch.object(ikarus_os, "ask",
                               return_value={"assistant": "fallback", "intent": "chat"}) as blocking:
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        blocking.assert_called_once()
        self.assertEqual(evs[-1][1]["assistant"], "fallback")
'''
new = '''    def test_midstream_error_keeps_partial_text_and_marks_interrupted(self):
        def boom():
            yield "partial"
            raise RuntimeError("stream died")

        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()):
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        self.assertEqual(evs[-1][1]["assistant"], "partial")
        self.assertTrue(evs[-1][1]["stream_interrupted"])
        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")
'''
text = replace_once(text, old, new, rel)
old = '''    def test_empty_stream_falls_back_to_blocking(self):
        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \\
             mock.patch.object(ikarus_os, "ask",
                               return_value={"assistant": "fallback", "intent": "chat"}):
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        self.assertEqual(evs[-1][1]["assistant"], "fallback")
'''
new = '''    def test_empty_stream_falls_back_to_resolved_blocking_voice(self):
        fallback = {"assistant": "fallback", "intent": "chat", "provider_used": "ollama_http"}
        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \\
             mock.patch.object(ikarus_os, "_chat", return_value=fallback) as blocking:
            evs = self._events(self.PROJECT, "hello there", provider="ollama")
        blocking.assert_called_once()
        self.assertEqual(evs[-1][1]["assistant"], "fallback")
'''
text = replace_once(text, old, new, rel)
text = replace_once(
    text,
    '        self.assertEqual(evs[-1][1]["provider_used"], "deterministic")\n        self.assertNotIn("delta", [e for e, _ in evs])\n',
    '        self.assertEqual(evs[-1][1]["provider_used"], "unavailable")\n        self.assertEqual(evs[-1][1]["intent"], "error")\n        self.assertNotIn("delta", [e for e, _ in evs])\n',
    rel,
)
old = '''    def test_ask_still_answers_deterministically(self):
        res = ikarus_os.ask("sunny_garden", "hello there", provider=None)
        self.assertEqual(res["provider_used"], "deterministic")
        self.assertIn("Ikarus", res["assistant"])
'''
new = '''    def test_ask_without_an_available_voice_fails_loud_instead_of_silent_fallback(self):
        res = ikarus_os.ask("sunny_garden", "hello there", provider=None)
        self.assertEqual(res["provider_used"], "unavailable")
        self.assertEqual(res["intent"], "error")
        self.assertIn("no available LLM voice", res["assistant"])
'''
text = replace_once(text, old, new, rel)
path.write_text(text, encoding="utf-8")


rel = "tests/test_ikarus_os_boundary.py"
path = ROOT / rel
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        "chat_completion", "chat_stream", "socket.create_connection",\n',
    '        "chat_completion", "chat_stream", "native_chat", "native_chat_stream",\n'
    '        "socket.create_connection",\n',
    rel,
)
path.write_text(text, encoding="utf-8")
print("current stream/boundary contracts aligned")
