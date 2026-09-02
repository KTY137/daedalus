"""Packet G1-SEC-01 -- the Codex CLI prompt must never be re-parsed by a shell.

WHY A STUB SHIM AND NOT A MOCK
------------------------------
``subprocess.run`` is mocked everywhere else in this suite, and a mock cannot
see the defect these tests exist for: the reinterpretation happens INSIDE
Windows' ``CreateProcess`` -> ``cmd.exe`` relay, after Python has handed over
the command line and before the child parses argv. Asserting on
``run.call_args`` would show a perfectly innocent list either way. So these
tests spawn a real child through the provider's real spawn path -- but the
child is a STUB shim written into a temp dir, never the real ``codex``. No
model is called, nothing is billed, and no network is touched.

The stub is a ``.cmd`` forwarding ``%*`` to a Python capture script, which is
the npm shim shape verbatim. On non-Windows it is the equivalent ``sh`` script,
so the same assertions run everywhere -- they simply cannot fail there, because
there is no ``cmd.exe`` in the path to reinterpret anything.

TWO LAYERS, AND THE DIFFERENCE MATTERS
--------------------------------------
:class:`RelayMechanicsTests` measures the PLATFORM, not our code. It spawns the
stub with the pre-fix argv shape and asserts what Windows actually does:

* a single-line prompt argument containing ``"`` lets the following
  ``&``-separated tokens RUN AS COMMANDS -- the canary file is created, from
  prompt text alone, with ``shell=False``. CPython 3.13.5 does not escape this;
* a MULTI-LINE prompt argument is cut at its first newline.

Those tests pass before and after the fix: they are the falsifiable premise the
fix rests on, so if a future CPython or Windows changes the relay they go red
and say so, instead of the reason for this code quietly evaporating.

:class:`CodexShimSpawnTests` measures OUR code: the provider must not feed that
mechanism at all. MEASURED 2026-09-02 with the fix disabled in place, all five
go red -- the child received ``'Daedalus Bridge Protocol v1.'`` as its last
argv element and NOTHING on stdin, i.e. pre-fix the objective never reached
codex at all.

Honest scope note: through :func:`build_prompt`'s multi-line output the
truncation fires FIRST, so an objective payload sitting on line 3 was cut away
rather than executed. The arbitrary-execution half was one prompt-layout change
(or one single-line prompt) away from being live, which is why the mechanics are
pinned separately rather than folded into a single "it was exploitable" claim.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus.providers.codex_cli import (
    CMD_SHIM_METACHARACTERS,
    CodexCLIProvider,
    cmd_shim_refusal,
)

AGENT = {"name": "docs-dev", "call_name": "Sam", "model_tier": "sonnet"}

VALID_REPORT = json.dumps({
    "status": "done",
    "summary": "stub shim report",
    "files_changed": [],
    "tests_run": [],
    "risks": [],
    "todos": [],
    "handoff": {},
})

# Records exactly what the child was given, then plays codex well enough for the
# provider to finish: writes the --output-last-message file it was pointed at.
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
        __REPORT__, encoding="utf-8")
'''.replace("__REPORT__", repr(VALID_REPORT))


class _Shim:
    """A fake ``codex`` on disk, plus the files it records what it received in."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="g1sec01-shim-")
        self.box = Path(self._tmp.name)
        self.repo = self.box / "repo"
        self.repo.mkdir()
        (self.box / "capture.py").write_text(_CAPTURE, encoding="utf-8")
        self.canary = self.box / "canary.txt"
        if os.name == "nt":
            self.path = self.box / "codex.cmd"
            self.path.write_text(
                f'@echo off\r\n"{sys.executable}" "%~dp0capture.py" %*\r\n',
                encoding="utf-8")
        else:
            self.path = self.box / "codex"
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


class RelayMechanicsTests(unittest.TestCase):
    """What Windows does with a prompt in argv. The premise, not the product.

    These spawn the stub DIRECTLY in the pre-fix argv shape, so they keep
    holding after the provider is fixed. They are the reason the fix exists; if
    they ever go red, the platform changed and this file should be re-read
    before anything is loosened.
    """

    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("the cmd.exe relay exists only on Windows")
        self.shim = _Shim()
        self.addCleanup(self.shim.cleanup)

    def _spawn(self, prompt: str):
        import subprocess
        return subprocess.run(
            [str(self.shim.path), "exec", "--color", "never", prompt],
            cwd=str(self.shim.repo), text=True, capture_output=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            timeout=120, check=False)

    def test_a_quote_in_a_prompt_argument_yields_command_execution(self):
        # No quotes around the redirect target: CPython escapes an embedded `"`
        # as `\"`, which cmd.exe does not understand as an escape, so the
        # relay's outer quoting ends early and the rest is a command list.
        self._spawn(f'benign objective" & echo pwned > {self.shim.canary} & rem ')
        self.assertTrue(
            self.shim.canary.exists(),
            "the .cmd relay no longer executes an injected prompt argument -- "
            "verify against a current CPython before trusting argv again")
        self.assertIn("pwned", self.shim.canary.read_text(errors="replace"))
        # the child itself saw only the truncated head of the argument
        self.assertEqual(self.shim.argv()[-1], 'benign objective"')

    def test_a_multiline_prompt_argument_is_cut_at_the_first_newline(self):
        self._spawn("first line\nsecond line\nthird line")
        self.assertEqual(self.shim.argv()[-1], "first line")


class CodexShimSpawnTests(unittest.TestCase):
    """End-to-end through the provider's real spawn path, into a stub shim."""

    def setUp(self) -> None:
        self.shim = _Shim()
        self.addCleanup(self.shim.cleanup)

    def _run(self, objective: str, **overrides):
        kwargs = dict(objective=objective, repo_root=str(self.shim.repo),
                      paths=["docs/notes.md"], agent=AGENT, timeout_s=120)
        kwargs.update(overrides)
        with patch("daedalus.providers.codex_cli.shutil.which",
                   return_value=str(self.shim.path)):
            return CodexCLIProvider().run(**kwargs)

    def test_metacharacter_payload_does_not_execute(self):
        # The exact payload that created the canary pre-fix. The closing `rem`
        # swallows whatever the relay leaves after the injected command.
        payload = (f'benign objective" & echo pwned > {self.shim.canary} & rem ')
        out = self._run(payload)

        if self.shim.canary.exists():
            self.fail("COMMAND INJECTION: prompt text was executed by the shim "
                      "relay; canary says "
                      f"{self.shim.canary.read_text(errors='replace')!r}")
        self.assertTrue(self.shim.spawned, "the stub shim was never reached")
        # The payload is nowhere in argv -- not quoted, not escaped: absent.
        for index, element in enumerate(self.shim.argv()):
            self.assertNotIn("echo pwned", element,
                             f"payload leaked into argv element {index}")
        # ... and arrives whole, as data, on stdin.
        self.assertIn(payload, self.shim.stdin_text())
        self.assertEqual(out["report"]["status"], "done")

    def test_prompt_is_stdin_not_argv(self):
        self._run("Draft release notes")
        argv = self.shim.argv()
        # "-" is codex exec's documented "read the prompt from stdin" PROMPT.
        self.assertEqual(argv[-1], "-")
        self.assertIn("exec", argv)
        self.assertNotIn("Daedalus Bridge Protocol v1.", " ".join(argv))

    def test_multiline_prompt_arrives_whole(self):
        # Pre-fix the child received ONLY 'Daedalus Bridge Protocol v1.' -- the
        # prompt cut at its first newline by the .cmd relay (the 2026-07-28
        # council incident, unfixed on this path until now).
        self._run("Rename Event.voltage to bias_voltage")
        received = self.shim.stdin_text()
        self.assertIn("Rename Event.voltage to bias_voltage", received)
        self.assertIn("No prose around it.", received)   # the LAST prompt line
        self.assertGreater(len(received.splitlines()), 10)

    def test_percent_in_objective_is_not_expanded_by_the_relay(self):
        # %VAR% was expanded by cmd.exe BEFORE the child saw it, substituting
        # the process environment into text that then leaves the machine --
        # after classify_data already screened it.
        self._run("Explain the %USERNAME% and %PATH% variables")
        received = self.shim.stdin_text()
        self.assertIn("%USERNAME%", received)
        self.assertIn("%PATH%", received)
        self.assertNotIn(os.environ.get("USERNAME", "\0no-such-user\0"), received)

    def test_unsafe_model_refuses_before_spawning(self):
        # --model comes from $CODEX_MODEL; a shim-hostile value must refuse
        # rather than be reinterpreted.
        if os.name != "nt":
            self.skipTest("the shim guard only fires for a .cmd/.bat argv[0]")
        out = self._run("Draft release notes", model='gpt-5" & echo pwned & rem ')
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("Refused to spawn", out["report"]["summary"])
        self.assertFalse(self.shim.spawned, "refusal must precede the spawn")
        self.assertFalse(self.shim.canary.exists())


class CmdShimRefusalTests(unittest.TestCase):
    """The guard itself, independent of any spawn."""

    def test_native_executable_is_never_refused(self):
        argv = ["C:/tools/codex.exe", "exec", '--model', 'a"b&c%d']
        self.assertIsNone(cmd_shim_refusal(argv))
        self.assertIsNone(cmd_shim_refusal(["/usr/bin/codex", "exec", "a&b"]))

    def test_every_listed_metacharacter_is_refused_in_a_cmd_argv(self):
        # Enumerated, not asserted in prose: each character in the published
        # set must actually refuse, or the constant is decoration.
        for char in CMD_SHIM_METACHARACTERS:
            with self.subTest(char=char):
                why = cmd_shim_refusal(["C:/npm/codex.CMD", "exec", f"a{char}b"])
                self.assertIsNotNone(why, f"{char!r} is listed but not refused")
                self.assertIn("argv element 2", why)

    def test_refusal_names_the_position_not_the_value(self):
        why = cmd_shim_refusal(["C:/npm/codex.CMD", "exec", "--cd", 'C:/x"y'])
        self.assertIsNotNone(why)
        self.assertIn("argv element 3", why)
        self.assertNotIn("C:/x", why)   # the value itself is never echoed

    def test_case_insensitive_suffix_and_bat(self):
        self.assertIsNotNone(cmd_shim_refusal(["C:/npm/codex.CMD", 'a"b']))
        self.assertIsNotNone(cmd_shim_refusal(["C:/npm/codex.Bat", 'a"b']))

    def test_clean_argv_passes(self):
        self.assertIsNone(cmd_shim_refusal(
            ["C:/npm/codex.CMD", "exec", "--cd", "C:/repo", "--model", "gpt-5", "-"]))

    def test_empty_argv_is_not_a_crash(self):
        self.assertIsNone(cmd_shim_refusal([]))


if __name__ == "__main__":
    unittest.main()
