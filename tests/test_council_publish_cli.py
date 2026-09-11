"""The council's PR channel is REACHABLE: `daedalus council --publish-pr` works.

WHAT WAS WRONG
--------------
``daedalus/council/publish.py`` is 763 lines carrying an egress gate, a status
vocabulary and a whole markdown renderer. MEASURED 2026-07-29 with
``daedalus/mapping/reach.py``: classification ``island``, zero production
callers, ``tests/test_council_publish.py`` its only importer.

The reason is worth naming, because it is not laziness. The module's entry
points took a live ``CouncilRecord``, and ``.claude/skills/council/SKILL.md``
told agents to hand-write ``from daedalus.council.publish import publish_to_pr``
in an ad-hoc snippet. So the code was exercised -- by tests, and occasionally by
an agent typing an import -- while no command a human could run ever reached it,
and the secret floor inside it guarded a path nobody could take.

WHAT THESE TESTS PIN
--------------------
Every test drives ``daedalus.interfaces.cli.entry.main`` with a real argv. None of them imports
``publish_to_pr`` and calls it: a guard verified only through its own function
is not verified, and proving the function works was never the open question --
proving something REACHES it was. Delete the CLI flags and every test in this
file goes red at argparse.

The runner is faked at ``publish._subprocess_runner`` so ``gh`` is never
launched. That is the ONLY fake: the argv construction, the egress gate, the
transcript loading, the quorum derivation and the rendering all run for real.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from daedalus.interfaces.cli import entry
from daedalus.council import publish as cp

# One roster record, two vendors that spoke, one that did not. The degraded
# quorum is deliberate: it is the fact the renderer must not round up.
TRANSCRIPT = [
    {"record": "roster", "council_id": "council-TEST", "entry_sha": "a" * 64,
     "participants": [{"vendor": "anthropic"}, {"vendor": "openai"},
                      {"vendor": "local"}]},
    {"record": "turn", "council_id": "council-TEST", "vendor": "anthropic",
     "status": "spoke", "role": "falsifier", "entry_sha": "b" * 64,
     "content": "CLAIM: the lane guard is the only thing holding here."},
    {"record": "turn", "council_id": "council-TEST", "vendor": "openai",
     "status": "unavailable", "reason": "not_on_path", "entry_sha": "c" * 64,
     "content": ""},
    {"record": "turn", "council_id": "council-TEST", "vendor": "local",
     "status": "spoke", "role": "maintainer", "entry_sha": "d" * 64,
     "content": "CLAIM: a dry run must still run the gate."},
]


class _Recorder:
    """A fake runner. Records the call instead of launching gh."""

    def __init__(self, returncode=0, stdout="https://github.com/o/r/pull/7#c1"):
        self.calls: list[tuple[list[str], str | None]] = []
        self._rc = returncode
        self._out = stdout

    def __call__(self, argv, stdin_text=None, timeout_s=None):
        self.calls.append((list(argv), stdin_text))
        return cp.RunResult(self._rc, self._out, "")


class _CliCase(unittest.TestCase):
    """Drives the real CLI. ``gh`` is replaced; nothing else is."""

    RECORDS = TRANSCRIPT

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "council-TEST.jsonl"
        self.store.write_text(
            "\n".join(json.dumps(r) for r in self.RECORDS) + "\n",
            encoding="utf-8")
        self.runner = _Recorder()
        # A launch attempt would be a real subprocess; make it impossible.
        p = patch.object(cp, "_subprocess_runner", self.runner)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv) -> tuple[str, int]:
        """(stdout, exit code). Exit 0 when the command returned normally."""
        buf = io.StringIO()
        code = 0
        with patch.object(sys, "argv", ["daedalus", *argv]):
            try:
                with redirect_stdout(buf):
                    entry.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return buf.getvalue(), code


class PublishReachesTheModuleTests(_CliCase):

    def test_publish_pr_dry_run_renders_the_council_through_the_cli(self):
        """THE WIRING TEST. Remove the flags and argparse exits 2 here."""
        out, code = self.run_cli("council", "--publish-pr", "7",
                                 "--transcript", str(self.store))

        self.assertEqual(code, 0, msg=out)
        self.assertIn(cp.STATUS_DRY_RUN, out)
        self.assertIn("# Council verdict", out)
        self.assertIn("ADVISORY ONLY", out)
        self.assertEqual(self.runner.calls, [], "gh was invoked on a dry run")

    def test_a_dry_run_still_reports_the_degraded_quorum_honestly(self):
        """Two of three vendors spoke. Counting seats instead of answers would
        print a full roster over a half-empty council."""
        out, _ = self.run_cli("council", "--publish-pr", "7",
                              "--transcript", str(self.store))

        self.assertIn(cp.DEGRADED_QUORUM_MARKER, out)
        self.assertIn("2 of 3", out)
        self.assertIn("openai", out)

    def test_a_bare_council_id_resolves_against_runs_council(self):
        """The id is what convene prints, so it has to be accepted."""
        out, code = self.run_cli("council", "--publish-pr", "7",
                                 "--transcript", "no-such-council-id")

        self.assertEqual(code, 1)
        self.assertIn("no such council transcript", out)

    def test_live_actually_invokes_gh_with_the_body_on_stdin(self):
        """The send path, pinned end to end: one gh call, the PR in argv, and
        the deliberation on STDIN rather than in the command line."""
        out, code = self.run_cli("council", "--publish-pr", "7", "--live",
                                 "--repo", "owner/name",
                                 "--transcript", str(self.store))

        self.assertEqual(code, 0, msg=out)
        self.assertEqual(len(self.runner.calls), 1)
        argv, stdin_text = self.runner.calls[0]
        self.assertEqual(argv[:3], ["gh", "pr", "comment"])
        self.assertEqual(argv[-2:], ["--", "7"])
        self.assertIn("--body-file", argv)
        self.assertIn("--repo", argv)
        self.assertIn("owner/name", argv)
        self.assertIn("# Council verdict", stdin_text or "")
        self.assertIn(cp.STATUS_PUBLISHED, out)

    def test_without_live_nothing_leaves_the_machine(self):
        """Fail closed. Publishing is egress, so it is opt-in exactly like
        convening is."""
        self.run_cli("council", "--publish-pr", "7",
                     "--transcript", str(self.store))

        self.assertEqual(self.runner.calls, [])

    def test_publish_pr_without_a_transcript_is_refused(self):
        out, code = self.run_cli("council", "--publish-pr", "7")

        self.assertEqual(code, 2, msg=out)
        self.assertEqual(self.runner.calls, [])


class SecretFloorOnTheCliPathTests(_CliCase):
    """The gate is the reason this module exists, and until now no command
    could reach it. A refusal must exit non-zero AND withhold the body."""

    RECORDS = TRANSCRIPT + [
        {"record": "turn", "council_id": "council-TEST", "vendor": "local",
         "status": "spoke", "entry_sha": "e" * 64,
         "content": "here is the key: AKIAIOSFODNN7EXAMPLE and it must not ship"},
    ]

    def test_a_secret_in_the_deliberation_is_refused_before_gh(self):
        out, code = self.run_cli("council", "--publish-pr", "7", "--live",
                                 "--transcript", str(self.store))

        self.assertEqual(code, 1, msg=out)
        self.assertIn(cp.STATUS_REFUSED_SECRET, out)
        self.assertEqual(self.runner.calls, [], "gh ran despite the refusal")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out,
                         "the refused body was echoed to stdout")


class ReadThreadReachesTheModuleTests(_CliCase):

    def test_read_thread_prints_turns_and_says_they_bind_nothing(self):
        self.runner._out = json.dumps({"comments": [
            {"author": {"login": "someone"}, "createdAt": "2026-07-29T00:00:00Z",
             "body": "the gate should also cover X", "url": "http://x/1"},
        ]})

        out, code = self.run_cli("council", "--read-thread", "7")

        self.assertEqual(code, 0, msg=out)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0][0][:3], ["gh", "pr", "view"])
        self.assertEqual(self.runner.calls[0][0][-2:], ["--", "7"])
        self.assertIn("someone", out)
        self.assertIn("the gate should also cover X", out)
        self.assertIn("Nothing above is authoritative", out)

    def test_a_gh_failure_is_a_status_and_a_non_zero_exit(self):
        self.runner._rc = 1
        self.runner._out = ""

        out, code = self.run_cli("council", "--read-thread", "7")

        self.assertEqual(code, 1)
        self.assertNotIn(cp.STATUS_READ_OK, out)


if __name__ == "__main__":
    unittest.main()
