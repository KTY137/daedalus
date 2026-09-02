"""Wiring codex_cli and deepseek into ikarus_os's freeform 'brain' (`_llm`).

No real subprocesses and no real network egress happen here: `subprocess.run`,
the portable runtime resolver and `chat_completion`/`chat_stream` are mocked
in every case.
Covers three things a silent-degrade bug could hide:

  1. An UNCONFIGURED codex/deepseek answers with a CLEAR, honest message under
     its OWN `provider_used` -- never a crash, and never silently relabelled
     as "deterministic" (which would look identical to a user asking nothing
     at all, or worse, be mistaken for a different brain's real answer).
  2. A CONFIGURED codex/deepseek actually answers, reusing the existing
     provider abstractions (`_openai_compat.chat_completion`/`chat_stream`
     for DeepSeek; the same `--output-last-message` CLI convention
     `codex_cli.py` uses for Codex) -- no new HTTP client, no new subprocess
     protocol invented here.
  3. SAFETY: both are EXTERNAL, NOT-trusted-with-IP lanes
     (daedalus/providers/__init__.py `trusted_with_ip=False` for both), so
     their brain context MUST be built with `lane="untrusted"` (the stricter
     default-deny gate) -- never `"trusted"` like Ollama/Claude get. A wrong
     "trusted" here would be a silent egress-gate downgrade.

NOTE: wiring codex_cli intentionally supersedes the "unwired provider falls
back to deterministic" assertions that used `provider="codex_cli"` as their
example in tests/test_ikarus_os.py::AskTest::test_unwired_provider_falls_back_safely
and tests/test_ikarus_stream.py::AskStreamTest::test_unwired_provider_degrades_to_deterministic.
Those two files are outside this task's file ownership, so they are left
unedited here and will need a follow-up to point at a still-actually-unwired
provider (this file's StillUnwiredProviderTest does that with "gemini").
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from daedalus import ikarus_os


def _fake_codex_run(reply_text: str):
    """A `subprocess.run` stand-in for `codex exec`: writes `reply_text` to
    whatever path follows `--output-last-message`, exactly like a real codex
    process would via that flag -- so `_codex()`'s read-back sees real content
    without a real CLI ever spawning."""

    def _run(args, **kwargs):
        idx = args.index("--output-last-message")
        Path(args[idx + 1]).write_text(reply_text, encoding="utf-8")
        return mock.MagicMock(returncode=0, stdout="", stderr="")

    return _run


class DeepSeekUnitTest(unittest.TestCase):
    def test_reuses_openai_compat_client_no_v1_suffix(self):
        # DeepSeekProvider.run() (providers/deepseek.py) uses the base_url
        # AS-IS, no "/v1" appended -- the chat brain must match exactly, or a
        # request would 404 against the real API.
        captured = {}

        def fake(**kw):
            captured.update(kw)
            return "  hi  "

        # The egress gate runs BEFORE the (mocked) call and reads the key as
        # the declared consent for the deepseek lane; without one the refusal
        # is correct and this unit test never reaches its subject (measured in
        # every clean clone). A dummy key declares consent; no egress happens,
        # chat_completion is mocked.
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-test-dummy"}),              mock.patch.object(ikarus_os, "chat_completion", side_effect=fake):
            out = ikarus_os._deepseek("hello", "deepseek-v4-flash", "low")
        self.assertEqual(out, "hi")
        self.assertEqual(captured["base_url"], "https://api.deepseek.com")
        self.assertEqual(captured["model"], "deepseek-v4-flash")
        self.assertEqual(captured["api_key"], "unit-test-dummy")

    def test_returns_none_on_failure(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-test-dummy"}),              mock.patch.object(ikarus_os, "chat_completion", side_effect=RuntimeError("dead")):
            self.assertIsNone(ikarus_os._deepseek("hello", "m", "low"))


class CodexUnitTest(unittest.TestCase):
    def test_missing_cli_returns_none(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value=None):
            self.assertIsNone(ikarus_os._codex("hello"))

    def test_uses_read_only_sandbox_and_neutral_cwd(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured["args"] = args
            return _fake_codex_run("hi from codex")(args, **kwargs)

        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value="codex"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            out = ikarus_os._codex("hello")
        self.assertEqual(out, "hi from codex")
        args = captured["args"]
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        self.assertEqual(args[args.index("--cd") + 1], ikarus_os._neutral_cwd())
        self.assertIn("--skip-git-repo-check", args)
        self.assertNotIn("--output-schema", args)  # freeform chat -> plain text, not a report schema

    def test_spawn_failure_returns_none(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value="codex"), \
             mock.patch("subprocess.run", side_effect=OSError("no exec")):
            self.assertIsNone(ikarus_os._codex("hello"))


class UnconfiguredBrainTest(unittest.TestCase):
    """The footgun this task closes: an unreachable brain must say so under
    its OWN name, never quietly wear "deterministic" instead."""

    PROJECT = "sunny_garden"

    def test_deepseek_without_key_gives_clear_message(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            res = ikarus_os.ask(self.PROJECT, "hello there", provider="deepseek")
        self.assertEqual(res["provider_used"], "deepseek")
        self.assertNotEqual(res["provider_used"], "deterministic")
        self.assertIn("DEEPSEEK_API_KEY", res["assistant"])

    def test_codex_without_cli_gives_clear_message(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value=None):
            res = ikarus_os.ask(self.PROJECT, "hello there", provider="codex_cli")
        self.assertEqual(res["provider_used"], "codex_cli")
        self.assertNotEqual(res["provider_used"], "deterministic")
        self.assertIn("Codex CLI", res["assistant"])

    def test_unconfigured_reply_never_crashes_the_turn(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value=None):
            res = ikarus_os.ask(self.PROJECT, "hello", provider="codex_cli")
        self.assertTrue(res["ok"])
        # Intent remains the user's classified request; provider availability
        # is reported honestly in the assistant text and provider_used field.
        self.assertEqual(res["intent"], "chat")


class ConfiguredBrainAnswersTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def test_deepseek_configured_returns_reply(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}), \
             mock.patch.object(ikarus_os, "chat_completion", return_value=" hi from deepseek "):
            res = ikarus_os.ask(self.PROJECT, "hello there", provider="deepseek")
        self.assertEqual(res["provider_used"], "deepseek")
        self.assertEqual(res["assistant"], "hi from deepseek")

    def test_codex_configured_returns_reply(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value="codex"), \
             mock.patch("subprocess.run", side_effect=_fake_codex_run("hi from codex")):
            res = ikarus_os.ask(self.PROJECT, "hello there", provider="codex_cli")
        self.assertEqual(res["provider_used"], "codex_cli")
        self.assertEqual(res["assistant"], "hi from codex")


class LaneSafetyTest(unittest.TestCase):
    """SAFETY-CRITICAL: DeepSeek and Codex are NOT trusted with IP -- their
    brain context must go through the stricter "untrusted" egress lane, never
    "trusted". A regression here would silently widen what leaves the machine
    to an external API."""

    PROJECT = "sunny_garden"

    def _capture_lane(self, captured):
        def fake_ctx(project, message, lane="trusted", **_kwargs):
            captured["lane"] = lane
            return ikarus_os._EMPTY_CTX
        return fake_ctx

    def test_deepseek_uses_untrusted_lane(self):
        captured = {}
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}), \
             mock.patch.object(ikarus_os, "_project_context", side_effect=self._capture_lane(captured)), \
             mock.patch.object(ikarus_os, "chat_completion", return_value="ok"):
            ikarus_os.ask(self.PROJECT, "hello", provider="deepseek")
        self.assertEqual(captured["lane"], "untrusted")

    def test_codex_uses_untrusted_lane(self):
        captured = {}
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value="codex"), \
             mock.patch.object(ikarus_os, "_project_context", side_effect=self._capture_lane(captured)), \
             mock.patch("subprocess.run", side_effect=_fake_codex_run("ok")):
            ikarus_os.ask(self.PROJECT, "hello", provider="codex_cli")
        self.assertEqual(captured["lane"], "untrusted")

    def test_ollama_still_uses_trusted_lane(self):
        # Regression guard: the new branches must not have disturbed the
        # existing trusted-lane wiring for the local/Claude lanes.
        captured = {}
        with mock.patch.object(ikarus_os, "_project_context", side_effect=self._capture_lane(captured)), \
             mock.patch.object(ikarus_os, "chat_completion", return_value="ok"), \
             mock.patch("daedalus.providers.ollama.warm_model_async"):
            ikarus_os.ask(self.PROJECT, "hello", provider="ollama")
        self.assertEqual(captured["lane"], "trusted")


class DeepSeekStreamTest(unittest.TestCase):
    PROJECT = "sunny_garden"

    def test_streams_when_configured(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}), \
             mock.patch.object(ikarus_os, "_deepseek_stream", return_value=iter(["He", "llo"])):
            evs = list(ikarus_os.ask_stream(self.PROJECT, "hi", provider="deepseek"))
        self.assertEqual([e for e, _ in evs], ["start", "delta", "delta", "final"])
        self.assertEqual(evs[-1][1]["assistant"], "Hello")
        self.assertEqual(evs[-1][1]["provider_used"], "deepseek")

    def test_without_key_falls_back_to_blocking_with_clear_message(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            evs = list(ikarus_os.ask_stream(self.PROJECT, "hi", provider="deepseek"))
        self.assertNotIn("delta", [e for e, _ in evs])
        self.assertIn("DEEPSEEK_API_KEY", evs[-1][1]["assistant"])

    def test_codex_never_streams_but_still_answers_via_blocking_fallback(self):
        with mock.patch("daedalus.orchestration.runtime_registry.resolve_runtime_command", return_value="codex"), \
             mock.patch("subprocess.run", side_effect=_fake_codex_run("hi from codex")):
            evs = list(ikarus_os.ask_stream(self.PROJECT, "hi", provider="codex_cli"))
        self.assertNotIn("delta", [e for e, _ in evs])
        self.assertEqual(evs[-1][1]["assistant"], "hi from codex")


class StillUnwiredProviderTest(unittest.TestCase):
    """A genuinely-not-yet-wired provider slot must still degrade safely to
    the deterministic layer. Uses "gemini" (never implemented anywhere in
    daedalus/providers/) instead of "codex_cli" -- codex_cli is exactly what
    this task wires up, so it can no longer serve as the "unwired" example."""

    PROJECT = "sunny_garden"

    def test_ask_fails_closed(self):
        res = ikarus_os.ask(self.PROJECT, "hello there", provider="gemini")
        self.assertEqual(res["provider_used"], "unavailable")
        self.assertEqual(res["intent"], "error")

    def test_ask_stream_fails_closed(self):
        evs = list(ikarus_os.ask_stream(self.PROJECT, "hello there", provider="gemini"))
        self.assertEqual(evs[-1][1]["provider_used"], "unavailable")
        self.assertEqual(evs[-1][1]["intent"], "error")
        self.assertNotIn("delta", [e for e, _ in evs])


if __name__ == "__main__":
    unittest.main()
