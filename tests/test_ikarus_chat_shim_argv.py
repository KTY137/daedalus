"""Packet G1-SEC-02 -- the CHAT path's CLI argv must never be re-parsed by a shell.

The sibling of ``tests/test_codex_shim_argv.py`` (packet G1-SEC-01), one layer
closer to the user: that one covers ``providers/codex_cli.py``, the agentic
offload lane; this one covers ``ikarus_os._codex``/``_claude``/``_ollama_cli``,
which is what a chat turn takes.

WHY A STUB SHIM AND NOT A MOCK
------------------------------
``subprocess.run`` is mocked everywhere else in this suite (tests/test_wires.py),
and a mock CANNOT see this defect: the reinterpretation happens inside Windows'
``CreateProcess`` -> ``cmd.exe`` relay, after Python hands over the command line
and before the child parses argv. ``run.call_args`` shows an innocent list
either way. So these tests spawn a real child through the real chat spawn path
-- but the child is a STUB written into a temp dir, never a real ``codex`` or
``claude``. No model is called, nothing is billed, no network is touched.

WHAT THE BRIEF EXPECTED, AND WHAT WAS ACTUALLY MEASURED
-------------------------------------------------------
The packet was opened on the theory that ``args.append(prompt)`` shipped the
user's chat MESSAGE into the relay, single-line and straight in. Measured on
this box, that is NOT reachable: :func:`daedalus.ikarus_os._claude_prompt`
returns ``f"{SYSTEM}...\\n\\nUser: {message}"``, so the message is never on line
one, and ``cmd.exe`` truncates the argument at the first newline. Pre-fix the
child received the SYSTEM paragraph and nothing else.

The truncation is not a defence, it is a second defect, and the argv element
that IS reachable sits right beside it:

* FUNCTIONAL -- the user's turn, and the whole distilled context slice, never
  reached codex at all. Pinned by :meth:`...test_the_user_turn_reaches_the_child`.
* SECURITY -- ``--model`` is single-line, has no SYSTEM prefix, and arrives
  unscreened from ``POST /api/ikarus/ask``'s request body
  (daedalus/interfaces/http/effects.py: ``model = body.get("model")`` ->
  ``ikarus_os.ask(model=...)`` -> ``_llm`` -> ``_codex`` -> ``args += ["--model",
  model]``). MEASURED 2026-09-02, stub ``.cmd``, CPython 3.13.5, shell=False:
  ``'gpt-5" & echo pwned > <path> & rem '`` CREATED THE CANARY FILE, and
  ``'gpt-5-%USERNAME%'`` reached the child as ``'gpt-5-Administrator'``.

TWO LAYERS, AND THE DIFFERENCE MATTERS
--------------------------------------
:class:`RelayMechanicsTests` measures the PLATFORM with the pre-fix argv shape.
It passes before and after the fix: it is the falsifiable premise the fix rests
on, so if a future CPython or Windows changes the relay it goes red and says so
instead of the reason for this code quietly evaporating.

:class:`ChatSpawnTests` and :class:`ShimGuardedSinksTests` measure OUR code.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus import ikarus_os
from daedalus.ikarus_os import ProviderStartRefused

# Records exactly what the child was given, then plays the CLI well enough for
# _codex to finish: writes the --output-last-message file it was pointed at.
_CAPTURE = '''\
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
argv = sys.argv[1:]
(here / "argv.json").write_text(json.dumps(argv), encoding="utf-8")
try:
    raw = sys.stdin.buffer.read()
except Exception as exc:  # noqa: BLE001 -- a stub, and we want the reason
    raw = ("<stdin unreadable: %s>" % exc).encode("utf-8")
(here / "stdin.txt").write_bytes(raw)
if "--output-last-message" in argv:
    Path(argv[argv.index("--output-last-message") + 1]).write_text(
        "stub chat reply", encoding="utf-8")
'''


class _Shim:
    """A fake vendor CLI on disk, plus the files it records what it received in.

    ``.cmd`` on Windows -- the npm shim shape verbatim -- and the equivalent
    ``sh`` script elsewhere, so the same assertions run everywhere. They simply
    cannot fail off Windows, because there is no ``cmd.exe`` to reinterpret
    anything; the guard's own suffix test is what covers that case.
    """

    def __init__(self, stem: str = "codex") -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="g1sec02-shim-")
        self.box = Path(self._tmp.name)
        (self.box / "capture.py").write_text(_CAPTURE, encoding="utf-8")
        self.canary = self.box / "canary.txt"
        if os.name == "nt":
            self.path = self.box / f"{stem}.cmd"
            self.path.write_text(
                f'@echo off\r\n"{sys.executable}" "%~dp0capture.py" %*\r\n',
                encoding="utf-8")
        else:
            self.path = self.box / stem
            self.path.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/capture.py" "$@"\n',
                encoding="utf-8")
            self.path.chmod(self.path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)

    def cleanup(self) -> None:
        self._tmp.cleanup()

    @property
    def spawned(self) -> bool:
        return (self.box / "argv.json").exists()

    def argv(self) -> list[str]:
        return json.loads((self.box / "argv.json").read_text(encoding="utf-8"))

    def stdin_text(self) -> str:
        return (self.box / "stdin.txt").read_bytes().decode("utf-8")


class _ShimCase(unittest.TestCase):
    """Common setup: a stub CLI, and a ledger of this test's own.

    The ledger pin is not decoration. These tests perform REAL spawns, and the
    budget interposer reserves a worst-case $2 per vendor spawn against the
    $5 period ceiling, so without a private ledger the third spawning test in
    the file is refused by the budget rather than by its subject (MEASURED
    2026-09-02: "committed $4.0000 of $5.0000, 2 calls recorded", from the
    scratch spike in runs/analysis/g1-chatprompt/).
    """

    STEM = "codex"

    def setUp(self) -> None:
        from daedalus import budget

        self.shim = _Shim(self.STEM)
        self.addCleanup(self.shim.cleanup)
        ledger_dir = tempfile.TemporaryDirectory(prefix="g1sec02-ledger-")
        self.addCleanup(ledger_dir.cleanup)
        previous = os.environ.get("DAEDALUS_BUDGET_LEDGER")
        os.environ["DAEDALUS_BUDGET_LEDGER"] = str(
            Path(ledger_dir.name) / "ledger.json")
        budget.reset_default_ledger()

        def _restore() -> None:
            if previous is None:
                os.environ.pop("DAEDALUS_BUDGET_LEDGER", None)
            else:
                os.environ["DAEDALUS_BUDGET_LEDGER"] = previous
            budget.reset_default_ledger()

        self.addCleanup(_restore)

    def resolved(self):
        """Point the chat path's runtime resolver at the stub."""
        return patch("daedalus.runtime_registry.resolve_runtime_command",
                     return_value=str(self.shim.path))


class RelayMechanicsTests(_ShimCase):
    """What Windows does with a `--model` value in argv. The premise, not us.

    Spawned DIRECTLY in the pre-fix argv shape, so these keep holding after the
    chat path is fixed. If they go red, the platform changed and this file
    should be re-read before anything is loosened.
    """

    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("the cmd.exe relay exists only on Windows")
        super().setUp()

    def _spawn(self, model: str, prompt: str = "You are Ikarus.\n\nUser: hi"):
        return subprocess.run(
            [str(self.shim.path), "exec", "--color", "never",
             "--output-last-message", str(self.shim.box / "last.txt"),
             "--model", model, prompt],
            cwd=str(self.shim.box), text=True, capture_output=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=120, check=False)

    def test_a_quote_in_a_model_argument_yields_command_execution(self):
        # No quotes around the redirect target: CPython escapes an embedded `"`
        # as `\"`, which cmd.exe does not understand as an escape, so the
        # relay's outer quoting ends early and the rest is a command list.
        # (With a QUOTED target the redirect instead fails with a syntax error
        # -- measured, and the reason this variant is the one pinned.)
        self._spawn(f'gpt-5" & echo pwned > {self.shim.canary} & rem ')
        self.assertTrue(
            self.shim.canary.exists(),
            "the .cmd relay no longer executes an injected --model value -- "
            "verify against a current CPython before trusting argv again")
        self.assertIn("pwned", self.shim.canary.read_text(errors="replace"))
        self.assertEqual(self.shim.argv()[-1], 'gpt-5"')  # the rest was eaten

    def test_percent_in_a_model_argument_is_expanded_before_the_child(self):
        me = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if not me:
            self.skipTest("no USERNAME in this environment to substitute")
        self._spawn("gpt-5-%USERNAME%")
        self.assertEqual(self.shim.argv()[-2], f"gpt-5-{me}")

    def test_a_multiline_prompt_argument_is_cut_at_the_first_newline(self):
        # Why the chat MESSAGE never reached codex: _claude_prompt puts SYSTEM
        # on line one and "User: <message>" after a blank line.
        self._spawn("gpt-5", "SYSTEM framing\n\nUser: what is 2+2")
        self.assertEqual(self.shim.argv()[-1], "SYSTEM framing")


class ChatSpawnTests(_ShimCase):
    """End-to-end through ``ikarus_os._codex``'s real spawn path, into a stub."""

    def test_unsafe_model_refuses_before_spawning(self):
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        payload = f'gpt-5" & echo pwned > {self.shim.canary} & rem '
        refusal = None
        with self.resolved():
            try:
                ikarus_os._codex("what is 2+2", model=payload, timeout_s=120)
            except ProviderStartRefused as exc:
                refusal = exc
        # The INJECTION is asserted before the refusal, so a red run names the
        # defect rather than the missing guard: with the fix disabled in place
        # this line is what fires (MEASURED 2026-09-02).
        if self.shim.canary.exists():
            self.fail("COMMAND INJECTION: the --model value was executed by "
                      "the shim relay; canary says "
                      f"{self.shim.canary.read_text(errors='replace')!r}")
        self.assertIsNotNone(refusal, "the unsafe --model value was not refused")
        self.assertFalse(self.shim.spawned, "refusal must precede the spawn")
        receipt = refusal.receipt
        self.assertEqual(receipt["contract"], "provider.argv_shim")
        self.assertEqual(receipt["verdict"], "deny")
        self.assertIs(receipt["spawned"], False)
        self.assertIs(receipt["connected"], False)
        # The value is caller-supplied; an argument echoed into a receipt is an
        # argument that can leak.
        self.assertNotIn("echo pwned", receipt["reason"])

    def test_percent_in_model_refuses_before_spawning(self):
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        with self.resolved():
            with self.assertRaises(ProviderStartRefused):
                ikarus_os._codex("what is 2+2", model="gpt-5-%USERNAME%",
                                 timeout_s=120)
        self.assertFalse(self.shim.spawned)

    def test_prompt_is_stdin_not_argv(self):
        with self.resolved():
            out = ikarus_os._codex("what is 2+2", timeout_s=120)
        self.assertEqual(out, "stub chat reply")
        argv = self.shim.argv()
        # "-" is codex exec's documented "read the prompt from stdin" PROMPT.
        self.assertEqual(argv[-1], "-")
        self.assertIn("exec", argv)
        self.assertNotIn("You are Ikarus", " ".join(argv))
        self.assertNotIn("what is 2+2", " ".join(argv))

    def test_the_user_turn_reaches_the_child(self):
        # THE FUNCTIONAL REGRESSION. Pre-fix the child received exactly one
        # line -- the SYSTEM paragraph -- with no user turn and no context.
        with self.resolved():
            ikarus_os._codex("what is 2+2", context="CONTEXT SLICE MARKER",
                             timeout_s=120)
        received = self.shim.stdin_text()
        self.assertIn("User: what is 2+2", received)
        self.assertIn("CONTEXT SLICE MARKER", received)
        self.assertIn("You are Ikarus", received)
        self.assertGreater(len(received.splitlines()), 1,
                           "the prompt arrived truncated to its first line")

    def test_percent_in_a_chat_message_is_not_expanded_by_the_relay(self):
        me = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        with self.resolved():
            ikarus_os._codex("explain %USERNAME% and %PATH%", timeout_s=120)
        received = self.shim.stdin_text()
        self.assertIn("%USERNAME%", received)
        self.assertIn("%PATH%", received)
        if me:
            self.assertNotIn(f"explain {me}", received)

    def test_a_refused_turn_is_spoken_not_swallowed(self):
        """A refusal the user cannot see is a silent degradation.

        ``_codex`` returns ``None`` for every ordinary failure, and ``None``
        falls through to the deterministic help text -- indistinguishable from
        having asked nothing. The shim refusal therefore raises instead, into
        the refusal envelope ``ask`` already owns.
        """
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        with self.resolved():
            envelope = ikarus_os.ask("sunny_garden", "what is 2+2",
                                     provider="codex_cli",
                                     model='gpt-5" & echo pwned & rem ')
        self.assertEqual(envelope["intent"], "error")
        self.assertEqual(envelope["refusal"]["contract"], "provider.argv_shim")
        self.assertIn("didn't make that call", envelope["assistant"])
        self.assertFalse(self.shim.spawned)
        self.assertFalse(self.shim.canary.exists())

    def test_a_refused_turn_is_spoken_on_the_STREAMING_path_too(self):
        """The cockpit's route, and the one the blocking test cannot cover.

        ``_ask_stream_inner`` has a ``streamer is None`` fallback into
        ``_chat`` for exactly the providers with no verified token-frame
        parser -- codex is the whole reason that branch exists -- and it was
        the ONLY provider branch with no ``ProviderStartRefused`` handler. A
        refusal raised out of the generator reached
        ``interfaces/http/sse.py``'s generic ``except Exception`` and was
        rendered as "I hit a snag: ...": the deterministic-fallback sentence,
        with no contract, no endpoint and no receipt. That is the silent
        degradation this whole packet exists to avoid, one route over.
        """
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        with self.resolved():
            events = list(ikarus_os.ask_stream(
                "sunny_garden", "what is 2+2", provider="codex_cli",
                model='gpt-5" & echo pwned & rem '))
        finals = [payload for event, payload in events if event == "final"]
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["intent"], "error")
        self.assertEqual(finals[0]["refusal"]["contract"], "provider.argv_shim")
        self.assertNotIn("I hit a snag", finals[0]["assistant"])
        self.assertFalse(self.shim.spawned)
        self.assertFalse(self.shim.canary.exists())


class ShimGuardedSinksTests(_ShimCase):
    """Every CLI-spawning sink in ikarus_os, not just the one that was live.

    ``claude`` and ``ollama`` resolve to native ``.exe`` on this box (MEASURED
    2026-09-02), so the guard is dormant there -- a per-host accident, not a
    guard. Pointed at a ``.cmd`` they must refuse exactly like ``_codex``, or
    an npm install of either CLI reopens the same hole with no code change.
    """

    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        super().setUp()

    def test_claude_refuses_an_unsafe_model(self):
        with self.resolved():
            with self.assertRaises(ProviderStartRefused) as caught:
                ikarus_os._claude("hi", model='sonnet" & echo pwned & rem ',
                                  timeout_s=120)
        self.assertEqual(caught.exception.receipt["contract"], "provider.argv_shim")
        self.assertFalse(self.shim.spawned)

    def test_claude_stream_refuses_an_unsafe_model(self):
        with self.resolved():
            stream = ikarus_os._claude_stream(
                "hi", model='sonnet" & echo pwned & rem ', timeout_s=120)
            with self.assertRaises(ProviderStartRefused):
                next(stream)
        self.assertFalse(self.shim.spawned)

    def test_ollama_cli_refuses_an_unsafe_prompt(self):
        # _ollama_cli still carries its prompt as an argv element (its stdin
        # move is a separate packet), so on a .cmd-shimmed Ollama the guard is
        # the whole defence -- and it must REFUSE, never reinterpret.
        with self.resolved():
            with self.assertRaises(ProviderStartRefused) as caught:
                ikarus_os._ollama_cli(
                    f'hi" & echo pwned > {self.shim.canary} & rem ',
                    "llama3", None, timeout_s=120)
        self.assertEqual(caught.exception.receipt["contract"], "provider.argv_shim")
        self.assertFalse(self.shim.spawned)
        self.assertFalse(self.shim.canary.exists())

    def test_a_clean_turn_through_a_cmd_shim_still_runs(self):
        # The guard must not cost an ordinary turn anything: a fail-closed
        # check that refuses everything is indistinguishable from a broken CLI.
        with self.resolved():
            out = ikarus_os._codex("what is 2+2", model="gpt-5", timeout_s=120)
        self.assertEqual(out, "stub chat reply")
        self.assertTrue(self.shim.spawned)
        self.assertEqual(self.shim.argv()[-3:], ["--model", "gpt-5", "-"])


class GuardWiringTests(unittest.TestCase):
    """The guard is the ONE from packet G1-SEC-01, not a second copy."""

    def test_helper_is_the_providers_one(self):
        import daedalus.providers.codex_cli as provider

        source = Path(ikarus_os.__file__).read_text(encoding="utf-8")
        self.assertIn("from .providers.codex_cli import cmd_shim_refusal", source)
        # ...and no local re-definition of the character set or the check.
        self.assertNotIn("CMD_SHIM_METACHARACTERS: str", source)
        self.assertNotIn("def cmd_shim_refusal", source)
        self.assertTrue(callable(provider.cmd_shim_refusal))

    def test_every_cli_sink_calls_the_guard(self):
        """Enumerated, not asserted in prose.

        A new CLI-spawning sink that forgets the guard is exactly how this
        defect survived the first packet, so the set is written down and its
        size is checked.
        """
        import ast

        source = Path(ikarus_os.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        expected = {"_ollama_cli", "_claude", "_codex", "_claude_stream"}
        guarded = set()
        spawning = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                f"{getattr(c.func.value, 'id', '')}.{c.func.attr}"
                if isinstance(c.func, ast.Attribute) else
                getattr(c.func, "id", "")
                for c in ast.walk(node) if isinstance(c, ast.Call)
            }
            if {"subprocess.run", "subprocess.Popen"} & calls:
                spawning.add(node.name)
            if "_refuse_cmd_shim" in calls:
                guarded.add(node.name)
        self.assertEqual(spawning, expected, "a CLI sink appeared or vanished")
        self.assertEqual(guarded, expected)
        self.assertEqual(len(guarded), 4)


if __name__ == "__main__":
    unittest.main()
