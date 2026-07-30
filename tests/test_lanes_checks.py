"""daedalus.lanes.checks -- the shared write-lane baseline.

MEASURED 2026-07-30: two guards (content substitution, invented first-party
imports) went into ``providers/deepseek.py`` and, within the same shift, not
into ``providers/ollama.py``. These tests pin the module both lanes now share,
so the same drift cannot happen silently again -- a lane that stops calling
``run_checks`` for its baseline loses test coverage here, not just in whichever
provider file happened to keep its own copy.
"""
from __future__ import annotations

import unittest

from daedalus.lanes.checks import (
    BASELINE_POLICY,
    CheckPolicy,
    WriteAttempt,
    imports_resolve,
    no_elision,
    not_substituted,
    not_truncated,
    parses,
    run_checks,
    toplevel_defs,
    unresolved_first_party_imports,
)

MODULE = '''\
"""Operator state for the working window."""
import json


class Shift:
    pass


class _ShiftLock:
    pass


def _write_atomic(path, text):
    return path


def _parse_until(text):
    return text


def load(root="."):
    return Shift()


def render(root="."):
    return ""
'''

TEST_MODULE_FOR_IT = '''\
"""Tests for shift.py"""
import unittest
from pathlib import Path


class TestShift(unittest.TestCase):
    def test_load(self):
        pass

    def test_render(self):
        pass
'''


def _attempt(rel="daedalus/shift.py", proposed=MODULE, original="",
            repo_root=".", creating=False):
    return WriteAttempt(rel=rel, proposed=proposed, repo_root=repo_root,
                        original=original, creating=creating)


class ToplevelDefsTests(unittest.TestCase):
    def test_names_top_level_only(self):
        defs = toplevel_defs(MODULE)
        self.assertEqual(defs, frozenset(
            {"Shift", "_ShiftLock", "_write_atomic", "_parse_until",
             "load", "render"}))

    def test_nested_helpers_not_counted(self):
        src = "def outer():\n    def inner():\n        pass\n    return inner\n"
        self.assertEqual(toplevel_defs(src), frozenset({"outer"}))

    def test_unparsable_is_none(self):
        self.assertIsNone(toplevel_defs("def broken(:\n"))


class NotTruncatedTests(unittest.TestCase):
    def test_half_or_more_survives(self):
        attempt = _attempt(proposed="x" * 50, original="x" * 100)
        self.assertEqual(not_truncated(attempt, BASELINE_POLICY), "")

    def test_under_half_refused(self):
        attempt = _attempt(proposed="x" * 40, original="x" * 100)
        reason = not_truncated(attempt, BASELINE_POLICY)
        self.assertIn("truncat", reason)

    def test_creating_never_truncated(self):
        attempt = _attempt(proposed="x", original="", creating=True)
        self.assertEqual(not_truncated(attempt, BASELINE_POLICY), "")


class NoElisionTests(unittest.TestCase):
    def test_new_marker_refused(self):
        policy = CheckPolicy(elision_markers=("rest of the file",))
        attempt = _attempt(proposed="code\n# ...rest of the file unchanged",
                           original="code\n")
        reason = no_elision(attempt, policy)
        self.assertIn("elision marker", reason)

    def test_preexisting_marker_not_refused(self):
        policy = CheckPolicy(elision_markers=("rest of the file",))
        attempt = _attempt(proposed="code\n# rest of the file\n",
                           original="code\n# rest of the file\n")
        self.assertEqual(no_elision(attempt, policy), "")

    def test_no_markers_configured_never_fires(self):
        attempt = _attempt(proposed="rest of the file", original="")
        self.assertEqual(no_elision(attempt, BASELINE_POLICY), "")


class ParsesTests(unittest.TestCase):
    def test_valid_python_passes(self):
        self.assertEqual(parses(_attempt(proposed=MODULE), BASELINE_POLICY), "")

    def test_broken_python_refused(self):
        attempt = _attempt(proposed="def broken(:\n", original=MODULE)
        reason = parses(attempt, BASELINE_POLICY)
        self.assertIn("does not parse", reason)

    def test_created_file_that_does_not_parse_is_refused(self):
        # This is the gap the shared module closes over the original
        # deepseek.py-only implementation: a CREATED file had no "original" to
        # fall back on, so nothing upstream of not_substituted caught it.
        attempt = _attempt(proposed="def broken(:\n", original="", creating=True)
        reason = parses(attempt, BASELINE_POLICY)
        self.assertIn("does not parse", reason)

    def test_non_python_never_checked(self):
        attempt = _attempt(rel="README.md", proposed="not python {{{", original="")
        self.assertEqual(parses(attempt, BASELINE_POLICY), "")


class NotSubstitutedTests(unittest.TestCase):
    """MEASURED 2026-07-30: asked to rewrite daedalus/shift.py, the model
    returned tests/test_shift.py -- a complete, valid, normally-sized file that
    was simply the wrong one. This is the guard that caught it on replay."""

    def test_real_substitution_caught(self):
        attempt = _attempt(proposed=TEST_MODULE_FOR_IT, original=MODULE)
        reason = not_substituted(attempt, BASELINE_POLICY)
        self.assertIn("content substitution", reason)

    def test_genuine_edit_passes(self):
        edited = MODULE.replace("return path", "return str(path)")
        attempt = _attempt(proposed=edited, original=MODULE)
        self.assertEqual(not_substituted(attempt, BASELINE_POLICY), "")

    def test_creating_never_flagged(self):
        attempt = _attempt(proposed=TEST_MODULE_FOR_IT, original="", creating=True)
        self.assertEqual(not_substituted(attempt, BASELINE_POLICY), "")

    def test_too_few_symbols_to_judge(self):
        tiny = "def one():\n    pass\n"
        self.assertLess(len(toplevel_defs(tiny)), BASELINE_POLICY.min_symbols_to_judge)
        attempt = _attempt(proposed="def two():\n    pass\n", original=tiny)
        self.assertEqual(not_substituted(attempt, BASELINE_POLICY), "")

    def test_non_python_never_checked(self):
        attempt = _attempt(rel="README.md", proposed="anything", original="other")
        self.assertEqual(not_substituted(attempt, BASELINE_POLICY), "")


class UnresolvedImportsTests(unittest.TestCase):
    """MEASURED 2026-07-30: three of seven agent-written files imported a
    first-party name that does not exist under the guessed path."""

    def test_missing_module_flagged(self):
        content = "import daedalus.linting\n"
        bad = unresolved_first_party_imports(content, ".")
        self.assertTrue(any("daedalus.linting" in b for b in bad))

    def test_missing_name_flagged(self):
        content = "from daedalus.providers.deepseek import DeepSeekProviderXYZ\n"
        bad = unresolved_first_party_imports(content, ".")
        self.assertTrue(any("DeepSeekProviderXYZ" in b for b in bad))

    def test_real_import_passes(self):
        content = "from daedalus.providers.deepseek import MAX_NOTES_PER_FILE\n"
        self.assertEqual(unresolved_first_party_imports(content, "."), [])

    def test_submodule_import_not_a_false_positive(self):
        # `from daedalus import shift` binds a SUBMODULE and is not named in
        # __init__.py -- measured to false-positive on 40/223 real files
        # before this exclusion existed.
        content = "from daedalus import shift\n"
        self.assertEqual(unresolved_first_party_imports(content, "."), [])

    def test_third_party_ignored(self):
        content = "import numpy\nfrom totally.made.up.package import thing\n"
        self.assertEqual(unresolved_first_party_imports(content, "."), [])

    def test_relative_import_ignored(self):
        content = "from . import shift\nfrom .. import offload\n"
        self.assertEqual(unresolved_first_party_imports(content, "."), [])


class RunChecksTests(unittest.TestCase):
    def test_clean_write_passes(self):
        attempt = _attempt(proposed=MODULE.replace("return path", "return str(path)"),
                           original=MODULE)
        self.assertEqual(run_checks(attempt, BASELINE_POLICY), "")

    def test_first_refusal_wins_cheapest_first(self):
        # Truncated AND would-be-substituted: truncation is checked first and
        # its message is the one that should come back.
        attempt = _attempt(proposed="x", original=MODULE)
        reason = run_checks(attempt, BASELINE_POLICY)
        self.assertIn("truncat", reason)

    def test_a_raising_check_refuses_rather_than_propagating(self):
        def _boom(attempt, policy):
            raise RuntimeError("boom")
        attempt = _attempt(proposed=MODULE, original=MODULE.replace("json", "os"))
        reason = run_checks(attempt, BASELINE_POLICY, extra=(_boom,))
        self.assertIn("boom", reason)
        self.assertIn("refusing the write", reason)

    def test_extra_checks_run_after_baseline(self):
        calls = []

        def _tracker(attempt, policy):
            calls.append(attempt.rel)
            return ""

        attempt = _attempt(proposed=MODULE.replace("json", "os"), original=MODULE)
        run_checks(attempt, BASELINE_POLICY, extra=(_tracker,))
        self.assertEqual(calls, [attempt.rel])

    def test_lane_cannot_disable_baseline_by_construction(self):
        # There is no parameter that removes a baseline check -- only `extra`,
        # which ADDS. Pinned as a signature assertion rather than behaviour: if
        # this starts failing because a `disable=` kwarg was added, that is
        # exactly the regression to catch.
        import inspect
        sig = inspect.signature(run_checks)
        self.assertEqual(set(sig.parameters), {"attempt", "policy", "extra"})


if __name__ == "__main__":
    unittest.main()
