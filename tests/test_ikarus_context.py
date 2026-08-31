"""BOOTSTRAP — Ikarus's brain gets a GATED distilled slice as project context.

The freeform brain (Claude + local Ollama, both TRUSTED lanes) is injected with a
distilled slice of the file the user referenced. Each rule below is a Momus
objection made permanent:

  * no file token / ambiguous filename  -> NO slice (byte-identical neutral prompt),
    never a guessed egress;
  * the ONLY content source is the already-gated ``semantic_slice`` -- a planted
    secret neighbour's bytes never reach any model's prompt, even the local one;
  * the withheld/trimmed metadata is surfaced to the USER in the chat envelope.

No real LLM/CLI runs here: the CLI subprocess and the HTTP client are mocked, so
prompt assembly is asserted directly.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import ikarus_os


FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Target resolution — ambiguity-aware, path-boundary matching.                #
# --------------------------------------------------------------------------- #
class ResolveTargetTest(unittest.TestCase):
    def test_no_token_returns_none_not_ambiguous(self):
        idx = {"modules": {"pkg/a.py": {}}}
        self.assertEqual(ikarus_os._resolve_target("hello there", idx), (None, False))

    def test_exact_path_is_unambiguous(self):
        idx = {"modules": {"pkg/a.py": {}, "pkg/sub/a.py": {}}}
        self.assertEqual(ikarus_os._resolve_target("open pkg/a.py", idx), ("pkg/a.py", False))

    def test_boundary_match_not_suffix_match(self):
        # "slice.py" must resolve to .../slice.py, NOT snag test_..._slice.py.
        idx = {"modules": {"pkg/slice.py": {}, "tests/test_x_slice.py": {}}}
        self.assertEqual(ikarus_os._resolve_target("explain slice.py", idx),
                         ("pkg/slice.py", False))

    def test_same_basename_collision_is_ambiguous(self):
        idx = {"modules": {"a/thing.py": {}, "b/thing.py": {}, "c/other.py": {}}}
        target, ambiguous = ikarus_os._resolve_target("look at thing.py", idx)
        self.assertIsNone(target)
        self.assertTrue(ambiguous)


# --------------------------------------------------------------------------- #
# Prompt assembly — inert without a filename, byte-identical to pre-BOOTSTRAP. #
# --------------------------------------------------------------------------- #
class PromptAssemblyTest(unittest.TestCase):
    def test_claude_prompt_no_context_is_neutral(self):
        self.assertEqual(
            ikarus_os._claude_prompt("hi", "low", ""),
            f"{ikarus_os.SYSTEM}{ikarus_os._LOW_EFFORT_STYLE}\n\nUser: hi")

    def test_claude_prompt_injects_context_between_system_and_user(self):
        p = ikarus_os._claude_prompt("hi", "low", "CTX-BLOCK")
        self.assertEqual(
            p,
            f"{ikarus_os.SYSTEM}{ikarus_os._LOW_EFFORT_STYLE}\n\nCTX-BLOCK\n\nUser: hi",
        )

    def test_ollama_with_context_prepends_to_user_turn(self):
        self.assertEqual(ikarus_os._with_context("hi", ""), "hi")
        self.assertEqual(ikarus_os._with_context("hi", "CTX"), "CTX\n\nhi")


# --------------------------------------------------------------------------- #
# _project_context — the gate, end to end, over a real temp repo.             #
# --------------------------------------------------------------------------- #
class ProjectContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/store.py", "def save(v):\n    return v\n")
        _write(self.root, "proj/keys.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        _write(self.root, "proj/widget.py",
               "from proj import store\nfrom proj import keys\n\n\n"
               "def build():\n    return store.save(keys.load())\n")
        self._patch = mock.patch.object(ikarus_os, "resolve_repo_root",
                                        return_value=str(self.root))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_no_file_message_is_empty_and_never_indexes(self):
        # No dotted token -> _EMPTY_CTX WITHOUT resolving/indexing the repo.
        with mock.patch("daedalus.structcore.index.cached_index") as idx:
            ctx = ikarus_os._project_context("p", "hello, who are you?")
        self.assertEqual(ctx.text, "")
        self.assertFalse(ctx.ambiguous)
        idx.assert_not_called()

    def test_file_message_injects_gated_slice(self):
        ctx = ikarus_os._project_context("p", "explain build() in widget.py")
        self.assertEqual(ctx.focus_file, "proj/widget.py")
        self.assertTrue(ctx.text.startswith(ikarus_os._CONTEXT_FRAMING))
        self.assertIn("# ===== FOCUS: proj/widget.py =====", ctx.text)
        self.assertIn("def build():", ctx.text)
        # store is a clean dep -> present; keys is a secret dep -> withheld.
        self.assertIn("proj/store.py", ctx.text)
        self.assertGreaterEqual(ctx.withheld_count, 1)
        self.assertIn("# ===== WITHHELD (egress gate) =====", ctx.text)
        self.assertIn("proj/keys.py", ctx.text)

    def test_secret_neighbour_bytes_never_egress(self):
        # THERMOMETER: the planted private key must not reach the brain context.
        ctx = ikarus_os._project_context("p", "explain widget.py")
        self.assertNotIn("BEGIN RSA PRIVATE KEY", ctx.text)
        self.assertNotIn("PRIVATE = ", ctx.text)

    def test_ambiguous_filename_injects_no_slice(self):
        # Two modules ending the same name -> refuse to guess which file to egress.
        _write(self.root, "proj/alpha/__init__.py", "")
        _write(self.root, "proj/beta/__init__.py", "")
        _write(self.root, "proj/alpha/dup.py", "def a():\n    return 1\n")
        _write(self.root, "proj/beta/dup.py",
               "SECRET_TOKEN = 'ghp_" + "a" * 36 + "'\n")
        # fresh repo root so cached_index re-indexes with the new files
        with tempfile.TemporaryDirectory() as d2:
            root2 = Path(d2)
            _write(root2, "proj/__init__.py", "")
            _write(root2, "proj/alpha/__init__.py", "")
            _write(root2, "proj/beta/__init__.py", "")
            _write(root2, "proj/alpha/dup.py", "def a():\n    return 1\n")
            _write(root2, "proj/beta/dup.py", "def b():\n    return 2\n")
            with mock.patch.object(ikarus_os, "resolve_repo_root", return_value=str(root2)):
                ctx = ikarus_os._project_context("p", "walk me through dup.py")
        self.assertTrue(ctx.ambiguous)
        self.assertEqual(ctx.text, "")
        self.assertIsNone(ctx.focus_file)

    def test_ambiguous_never_calls_semantic_slice(self):
        # Proves no file content is even assembled on the ambiguous path.
        idx = {"modules": {"a/dup.py": {}, "b/dup.py": {}}}
        with mock.patch("daedalus.structcore.index.cached_index", return_value=idx), \
             mock.patch("daedalus.structcore.slice.semantic_slice") as sl:
            ctx = ikarus_os._project_context("p", "explain dup.py")
        self.assertTrue(ctx.ambiguous)
        sl.assert_not_called()

    def test_over_budget_message_reports_trimmed(self):
        # A 1-token cap forces the degrade; metadata must report it to the user.
        with mock.patch.object(ikarus_os, "_CONTEXT_MAX_TOKENS", 1):
            ctx = ikarus_os._project_context("p", "explain widget.py")
        self.assertGreater(ctx.trimmed_count, 0)
        self.assertIn("CONTEXT TRIMMED", ctx.text)
        self.assertIn("# ===== FOCUS: proj/widget.py =====", ctx.text)  # focus kept


# --------------------------------------------------------------------------- #
# Both lanes get the context; the metadata reaches the chat envelope.         #
# --------------------------------------------------------------------------- #
class BrainLaneContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/store.py", "def save(v):\n    return v\n")
        _write(self.root, "proj/keys.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        _write(self.root, "proj/widget.py",
               "from proj import store\nfrom proj import keys\n\n\n"
               "def build():\n    return store.save(keys.load())\n")
        self._patch = mock.patch.object(ikarus_os, "resolve_repo_root",
                                        return_value=str(self.root))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_claude_lane_prompt_carries_gated_slice(self):
        captured = {}

        def fake_run(args, **kw):
            captured["input"] = kw.get("input")
            m = mock.MagicMock()
            m.stdout = "ok"
            return m

        with mock.patch("daedalus.runtime_registry.resolve_runtime_command",
                        return_value="claude"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            reply, mdl, ctx = ikarus_os._llm("claude", "explain widget.py", None, "low", "p")

        self.assertEqual(reply, "ok")
        self.assertEqual(ctx.focus_file, "proj/widget.py")
        self.assertIn(ikarus_os._CONTEXT_FRAMING, captured["input"])
        self.assertIn("# ===== FOCUS: proj/widget.py =====", captured["input"])
        self.assertNotIn("BEGIN RSA PRIVATE KEY", captured["input"])  # secret withheld

    def test_ollama_lane_user_turn_carries_gated_slice(self):
        captured = {}

        def fake_chat(*a, **kw):
            captured["user"] = kw.get("user")
            return "ok"

        def fake_warm(*a, **kw):
            return

        with mock.patch("daedalus.providers.ollama.warm_model_async", side_effect=fake_warm), \
             mock.patch("daedalus.ikarus_os.chat_completion", side_effect=fake_chat):
            reply, mdl, ctx = ikarus_os._llm("ollama", "explain widget.py", None, "low", "p")

        self.assertEqual(reply, "ok")
        self.assertIn(ikarus_os._CONTEXT_FRAMING, captured["user"])
        self.assertIn("# ===== FOCUS: proj/widget.py =====", captured["user"])
        self.assertNotIn("BEGIN RSA PRIVATE KEY", captured["user"])  # secret withheld

    def test_no_file_claude_prompt_is_byte_identical_neutral(self):
        captured = {}

        def fake_run(args, **kw):
            captured["input"] = kw.get("input")
            m = mock.MagicMock()
            m.stdout = "ok"
            return m

        # "hello there" has no dotted token -> _project_context short-circuits.
        with mock.patch("daedalus.runtime_registry.resolve_runtime_command",
                        return_value="claude"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            reply, mdl, ctx = ikarus_os._llm("claude", "hello there", None, "low", "p")

        self.assertEqual(ctx.text, "")
        self.assertEqual(captured["input"],
                         f"{ikarus_os.SYSTEM}{ikarus_os._LOW_EFFORT_STYLE}\n\nUser: hello there")
        self.assertNotIn("FOCUS", captured["input"])


class EnvelopeContextBlockTest(unittest.TestCase):
    def test_chat_envelope_carries_context_block(self):
        ctx = ikarus_os._Ctx("some slice", withheld_count=2, focus_file="proj/w.py",
                             included_count=3, trimmed_count=1, ambiguous=False)
        with mock.patch.object(ikarus_os, "_llm", return_value=("hi", "m7", ctx)):
            res = ikarus_os._chat("p", "explain w.py", "ollama")
        self.assertEqual(res["context"], {
            "focus_file": "proj/w.py", "included": 3,
            "withheld_count": 2, "trimmed": 1, "ambiguous": False})

    def test_chat_envelope_has_no_block_for_plain_message(self):
        with mock.patch.object(ikarus_os, "_llm",
                               return_value=("hi", "m7", ikarus_os._EMPTY_CTX)):
            res = ikarus_os._chat("p", "hello", "ollama")
        self.assertNotIn("context", res)

    def test_chat_envelope_reports_ambiguous(self):
        amb = ikarus_os._Ctx("", 0, None, 0, 0, True)
        with mock.patch.object(ikarus_os, "_llm", return_value=("hi", "m7", amb)):
            res = ikarus_os._chat("p", "explain dup.py", "ollama")
        self.assertTrue(res["context"]["ambiguous"])
        self.assertIsNone(res["context"]["focus_file"])


class StreamEnvelopeContextTest(unittest.TestCase):
    def test_stream_threads_context_and_final_envelope_carries_it(self):
        ctx = ikarus_os._Ctx("CTX-TEXT", 1, "proj/widget.py", 2, 0, False)
        streamer = mock.MagicMock(return_value=iter(["Hel", "lo"]))
        with mock.patch.object(ikarus_os, "_project_context", return_value=ctx), \
             mock.patch.object(ikarus_os, "_ollama_stream", streamer):
            evs = list(ikarus_os.ask_stream("p", "explain widget.py", provider="ollama"))

        # context text was threaded into the streamer (4th positional arg)
        streamer.assert_called_once()
        self.assertEqual(streamer.call_args[0][3], "CTX-TEXT")
        # final envelope surfaces the metadata to the user
        final = evs[-1][1]
        self.assertEqual(final["context"]["focus_file"], "proj/widget.py")
        self.assertEqual(final["context"]["withheld_count"], 1)
        self.assertEqual(final["assistant"], "Hello")


if __name__ == "__main__":
    unittest.main()
