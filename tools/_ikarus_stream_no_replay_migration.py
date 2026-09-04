from __future__ import annotations

from pathlib import Path

BRANCH = "g1/ikarus-runtime-invocation-binding-07d3"
SHELL = Path("daedalus/ikarus_os.py")
TESTS = Path("tests/test_ikarus_stream.py")
PACKET = Path("docs/work-packets/G1-IKARUS-14_STREAM_INTERRUPTION_NO_REPLAY.md")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def migrate_shell() -> None:
    text = SHELL.read_text(encoding="utf-8")

    old_doc = '''    Fail-closed: any streaming failure (unsupported flag, dead runtime, mid-\n    stream error) degrades to the blocking path rather than erroring the chat.\n'''
    new_doc = '''    Fail-closed: once a provider stream has been entered, an empty or failed\n    stream is terminal and is never silently replayed through the blocking path.\n    The blocking path remains only the capability fallback when the selected\n    provider has no verified streaming transport.\n'''
    text = replace_once(text, old_doc, new_doc, label="stream doc contract")

    old_failure = '''    except Exception:\n        failed = True  # fall through to the blocking path\n'''
    new_failure = '''    except Exception:\n        # The request may already have reached the provider.  Preserve an\n        # interrupted outcome below instead of issuing an invisible second call.\n        failed = True\n'''
    text = replace_once(text, old_failure, new_failure, label="stream failure comment")

    old_empty = '''    if not text:\n        yield "final", _reconcile_final(\n            route, _chat(project, message, p or provider, model, effort,\n                         conversation_id=conversation_id))\n        return\n'''
    new_empty = '''    if not text:\n        # A selected streamer has already been entered, so an empty result is an\n        # unknown delivery outcome.  Re-entering _chat here can duplicate spend\n        # or a remotely completed turn.  Halt loudly and require an explicit\n        # user retry instead.  The earlier `streamer is None` branch remains the\n        # only safe blocking capability fallback because no stream was attempted.\n        block = _ctx_envelope_block(ctx)\n        extra = {"context": block} if block else {}\n        yield "final", _reconcile_final(route, core.envelope(\n            project, intent="chat", shell=SHELL_VOICE,\n            assistant=("The response stream ended without a complete answer. "\n                       "The request was not automatically retried."),\n            provider_used=p, model_used=model_used, stream_interrupted=True,\n            **extra))\n        return\n'''
    text = replace_once(text, old_empty, new_empty, label="empty-stream replay seam")

    if "The request was not automatically retried." not in text:
        raise SystemExit("no-replay final was not installed")
    SHELL.write_text(text, encoding="utf-8")


def migrate_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")

    old_mid = '''    def test_midstream_error_keeps_partial_text_and_marks_interrupted(self):\n        def boom():\n            yield "partial"\n            raise RuntimeError("stream died")\n\n        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()):\n            evs = self._events(self.PROJECT, "hello there", provider="ollama")\n        self.assertEqual(evs[-1][1]["assistant"], "partial")\n        self.assertTrue(evs[-1][1]["stream_interrupted"])\n        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")\n\n'''
    new_mid = '''    def test_midstream_error_keeps_partial_text_and_marks_interrupted(self):\n        def boom():\n            yield "partial"\n            raise RuntimeError("stream died")\n\n        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=boom()), \\\n             mock.patch.object(ikarus_os, "_chat") as blocking:\n            evs = self._events(self.PROJECT, "hello there", provider="ollama")\n        blocking.assert_not_called()\n        self.assertEqual(evs[-1][1]["assistant"], "partial")\n        self.assertTrue(evs[-1][1]["stream_interrupted"])\n        self.assertEqual(evs[-1][1]["provider_used"], "ollama_http")\n\n'''
    text = replace_once(text, old_mid, new_mid, label="midstream no-replay test")

    old_empty = '''    def test_empty_stream_falls_back_to_resolved_blocking_voice(self):\n        fallback = {"assistant": "fallback", "intent": "chat", "provider_used": "ollama_http"}\n        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \\\n             mock.patch.object(ikarus_os, "_chat", return_value=fallback) as blocking:\n            evs = self._events(self.PROJECT, "hello there", provider="ollama")\n        blocking.assert_called_once()\n        self.assertEqual(evs[-1][1]["assistant"], "fallback")\n\n'''
    new_empty = '''    def test_empty_stream_halts_without_replaying_provider(self):\n        with mock.patch.object(ikarus_os, "_ollama_stream", return_value=iter([])), \\\n             mock.patch.object(ikarus_os, "_chat") as blocking:\n            evs = self._events(self.PROJECT, "hello there", provider="ollama")\n        blocking.assert_not_called()\n        final = evs[-1][1]\n        self.assertEqual(final["intent"], "chat")\n        self.assertEqual(final["provider_used"], "ollama_http")\n        self.assertTrue(final["stream_interrupted"])\n        self.assertIn("not automatically retried", final["assistant"])
        self.assertNotIn("delta", [event for event, _ in evs])\n\n'''
    text = replace_once(text, old_empty, new_empty, label="empty-stream no-replay test")

    TESTS.write_text(text, encoding="utf-8")


def write_packet() -> None:
    if PACKET.exists():
        existing = PACKET.read_text(encoding="utf-8")
        if "empty provider stream" not in existing.lower():
            raise SystemExit("existing G1-IKARUS-14 packet has unexpected content")
        return
    PACKET.write_text(
        '''# G1-IKARUS-14 — Stream interruption without provider replay\n\n## Scope\n\nThis bounded Gate-1 reliability slice closes the server-side half of the Ikarus\nstream no-replay contract on the canonical `g1/ikarus-runtime-invocation-binding-07d3`\nline. The browser half is already present: an interrupted stream is rendered as\nhalted and is not retried through the blocking POST path.\n\nOnce `_ask_stream_inner(...)` has entered a real provider streamer, an empty or\nfailed stream is an unknown delivery outcome. The provider request may already\nhave committed remotely, so Ikarus must not invisibly call `_chat(...)` again.\nThe existing `streamer is None` branch remains a capability fallback for providers\nwithout a verified streaming transport because no streaming request was attempted.\n\n## Acceptance\n\n- Mid-stream provider failure retains partial text, marks `stream_interrupted=true`,\n  and never calls the blocking provider path.\n- An empty provider stream emits a halted/interrupted final and never calls `_chat`.\n- The final says the request was not automatically retried.\n- Existing Ollama single-transport `keep_alive` semantics remain intact.\n- No new provider, executor, queue, authority, or action path is introduced.\n\n## Non-claims\n\nThis packet does not claim provider cancellation propagation, sealed broker cutover\non this branch, Hermes superiority, or a Gate transition. It removes one duplicate-\nexecution ambiguity from the conversational transport only.\n''',
        encoding="utf-8",
    )


def verify_source() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    bug = '''if not text:\n        yield "final", _reconcile_final(\n            route, _chat('''
    if bug in shell:
        raise SystemExit("empty-stream provider replay seam still present")
    if shell.count("The request was not automatically retried.") != 1:
        raise SystemExit("expected exactly one explicit no-replay final")
    tests = TESTS.read_text(encoding="utf-8")
    if "test_empty_stream_halts_without_replaying_provider" not in tests:
        raise SystemExit("empty-stream no-replay regression is missing")
    if "blocking.assert_not_called()" not in tests:
        raise SystemExit("tests do not mechanically exclude provider replay")


def main() -> None:
    migrate_shell()
    migrate_tests()
    write_packet()
    verify_source()
    print("Ikarus stream no-replay migration applied and source-verified")


if __name__ == "__main__":
    main()
