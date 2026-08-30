# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The guard that catches a rewrite returning the WRONG FILE.

MEASURED 2026-07-30, and the reason this file exists. Ten write-capable DeepSeek
agents ran against an isolated worktree. Five modules came back modified, and
THREE of them had been destroyed: the module file contained the contents meant
for a different file. ``daedalus/shift.py`` held the test module written for it,
``daedalus/arch_memory.py`` the same, and ``daedalus/eval/mutate.py`` held the
contents of ``daedalus/eval/preserve.py``. Every one reported ``status: done``.

The mechanism was a prompt, not a model defect. A change request naming two
files is sent once PER FILE, and the model answered the REQUEST instead of the
FILE. Both existing guards were blind to it by construction:

* the truncation guard compares SIZE, and a substituted file is a normal size --
  the test module that replaced ``shift.py`` was in fact 39% LARGER;
* the elision-marker guard looks for a model admitting it omitted something, and
  nothing was omitted. A complete, valid, well-formed file arrived. It was
  simply the wrong one.

So these tests pin the only question that separates the two cases: does the
result still contain the thing that was sent?
"""
from __future__ import annotations

import unittest
from pathlib import Path

from daedalus.providers.deepseek import (
    _MIN_SYMBOLS_TO_JUDGE, _substitution_reason, _toplevel_defs,
    _unresolved_first_party_imports, _REWRITE_SYSTEM, MAX_NOTES_PER_FILE)

# The real shape of the measured failure, reduced to its essentials: a module
# with several top-level definitions, replaced by a test module for it. Note
# that the replacement is LONGER than the original -- that is what made the
# size-based guard useless here.
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


class TestShiftLock(unittest.TestCase):
    def test_lock_is_a_separate_file(self):
        self.assertTrue(True)

    def test_lock_released_on_exit(self):
        self.assertTrue(True)


class TestParseUntil(unittest.TestCase):
    def test_parses_hh_mm(self):
        self.assertTrue(True)

    def test_window_crossing_midnight(self):
        self.assertTrue(True)


class TestShiftArithmetic(unittest.TestCase):
    def test_boundaries(self):
        self.assertTrue(True)


def _make_state(tmp):
    return tmp
'''


class TheMeasuredFailure(unittest.TestCase):
    def test_a_module_replaced_by_its_own_test_module_is_refused(self):
        reason = _substitution_reason("daedalus/shift.py", MODULE, TEST_MODULE_FOR_IT)
        self.assertTrue(reason, "the exact failure observed in the lab must be caught")
        self.assertIn("substitution", reason)

    def test_the_refusal_names_what_disappeared(self):
        """A refusal that does not say WHAT was lost cannot be triaged: the
        operator has to re-derive the diff to find out whether it mattered."""
        reason = _substitution_reason("daedalus/shift.py", MODULE, TEST_MODULE_FOR_IT)
        self.assertIn("Shift", reason)

    def test_the_size_guard_would_not_have_caught_it(self):
        """Pins the premise. If the substitute were merely small, the existing
        truncation check would already have refused it and this guard would be
        redundant -- so the test asserts the substitute is BIGGER."""
        self.assertGreater(len(TEST_MODULE_FOR_IT), 0.5 * len(MODULE))
        self.assertGreater(len(TEST_MODULE_FOR_IT), len(MODULE) * 0.9)


class OrdinaryEditsSurvive(unittest.TestCase):
    """The guard is worthless if it fires on real work. A refused good change
    costs twice: the work is lost AND the task escalates to a paid lane."""

    def test_adding_a_function_is_not_a_substitution(self):
        edited = MODULE + "\n\ndef save(mem, root='.'):\n    return root\n"
        self.assertEqual(_substitution_reason("daedalus/shift.py", MODULE, edited), "")

    def test_renaming_one_of_several_is_not_a_substitution(self):
        edited = MODULE.replace("def render(", "def render_delta(")
        self.assertEqual(_substitution_reason("daedalus/shift.py", MODULE, edited), "")

    def test_rewriting_bodies_wholesale_is_not_a_substitution(self):
        edited = MODULE.replace("return path", "raise NotImplementedError")
        self.assertEqual(_substitution_reason("daedalus/shift.py", MODULE, edited), "")

    def test_a_small_file_is_never_judged(self):
        """Below a few definitions the survival ratio is noise: losing one of
        two functions is an ordinary edit, and calling it a substitution would
        make the guard fire on exactly the small files it cannot reason about."""
        tiny = "def a():\n    return 1\n"
        self.assertLess(len(_toplevel_defs(tiny)), _MIN_SYMBOLS_TO_JUDGE)
        self.assertEqual(_substitution_reason("x.py", tiny, "def b():\n    return 2\n"), "")


class RefusesToJudgeWhatItCannotRead(unittest.TestCase):
    def test_a_non_python_file_is_not_judged(self):
        """The check needs a parser to mean anything. Guessing at other
        languages would either fire on ordinary edits or hand out false
        assurance for files it cannot actually read."""
        self.assertEqual(_substitution_reason("README.md", "# A\n\n# B\n\n# C\n", "totally different"), "")

    def test_an_unparsable_original_is_not_judged(self):
        self.assertEqual(_substitution_reason("x.py", "def (:::", MODULE), "")

    def test_an_unparsable_rewrite_is_refused(self):
        """The original parsed and the replacement does not. Whatever that is,
        landing it breaks the import for every consumer of the module."""
        reason = _substitution_reason("daedalus/shift.py", MODULE, "def (:::")
        self.assertIn("does not parse", reason)


class InventedImports(unittest.TestCase):
    """The second hole the same night opened, and the same shape of failure.

    Twenty agents wrote test modules against source files they had been given,
    and three of seven imported things that do not exist: ``daedalus.linting``
    (it is ``daedalus.gui.lint``), ``ShiftManager`` from ``daedalus.shift``
    (the class is ``Shift``), and ``daedalus.wiki_vault`` (it is
    ``daedalus.wiki.vault``). All valid Python, so a syntax gate passes them.
    All reported ``status: done``. Not one of the 26 tests written that night
    passed.
    """

    def setUp(self):
        self.root = str(Path(__file__).resolve().parents[1])

    def test_an_invented_module_is_caught(self):
        bad = _unresolved_first_party_imports(
            "from daedalus.wiki_vault import vault_rel\n", self.root)
        self.assertTrue(bad)
        self.assertIn("daedalus.wiki_vault", bad[0])

    def test_an_invented_name_in_a_real_module_is_caught(self):
        bad = _unresolved_first_party_imports(
            "from daedalus.shift import ShiftManager\n", self.root)
        self.assertTrue(bad)
        self.assertIn("ShiftManager", bad[0])

    def test_a_real_import_is_left_alone(self):
        self.assertEqual(
            _unresolved_first_party_imports(
                "from daedalus.shift import Shift\n", self.root), [])

    def test_importing_a_submodule_by_name_is_valid(self):
        """`from daedalus import shift` binds a SUBMODULE and is never named in
        the package's __init__.py. Measured: without this case the check fired
        on 40 of 223 real files -- a rate that would have made the gate useless
        and taught everyone to ignore it."""
        self.assertEqual(
            _unresolved_first_party_imports("from daedalus import shift\n",
                                            self.root), [])

    def test_third_party_imports_are_not_judged(self):
        """A missing third-party package is an environment question. Judging it
        here would refuse good code on a machine with a lean virtualenv."""
        self.assertEqual(
            _unresolved_first_party_imports(
                "import numpy\nfrom pandas import DataFrame\n", self.root), [])

    def test_relative_imports_are_not_judged(self):
        self.assertEqual(
            _unresolved_first_party_imports("from . import shift\n", self.root), [])

    def test_unparsable_content_is_left_to_another_guard(self):
        self.assertEqual(_unresolved_first_party_imports("def (:::", self.root), [])

    def test_no_false_positives_across_the_real_tree(self):
        """The control that decides whether this gate can be switched on at all.
        A gate with false positives costs twice: the work is discarded AND the
        task escalates to a paid lane."""
        root = Path(self.root)
        files = [p for p in root.joinpath("daedalus").rglob("*.py")
                 if "__pycache__" not in str(p)]
        files += list(root.joinpath("tests").glob("test_*.py"))
        offenders = []
        for p in files:
            bad = _unresolved_first_party_imports(
                p.read_text(encoding="utf-8", errors="replace"), self.root)
            if bad:
                offenders.append((p.name, bad[:2]))
        self.assertEqual(offenders, [], "this gate must never refuse real repo code")
        self.assertGreater(len(files), 200, "control set must be large enough to mean something")


class TheWritableLaneCanSpeak(unittest.TestCase):
    """A writable run used to have no way to report anything.

    MEASURED 2026-07-30: eight agents were sent to REVIEW code with
    ``writable=True`` and returned zero findings between them. Not because they
    found nothing -- because ``_run_rewrite`` parsed the reply for ``content``
    alone and hard-coded ``risks`` and ``todos`` to empty lists. Whatever they
    observed was discarded before it could reach the caller.

    That made ``writable=True`` a MODE SWITCH rather than an added capability:
    it silently replaced the advisory path, and the caller was not told. These
    tests pin the side channel that gives the lane its voice back.
    """

    def test_the_rewrite_prompt_offers_a_notes_channel(self):
        self.assertIn("notes", _REWRITE_SYSTEM)

    def test_the_prompt_says_notes_never_change_what_is_written(self):
        """The separation is the whole point. A note is an observation, not an
        instruction to the writer, and a model that thinks otherwise would start
        smuggling edits through the reporting channel."""
        self.assertIn("never affect what is written", _REWRITE_SYSTEM)

    def test_an_empty_notes_list_is_explicitly_blessed(self):
        """Without this a model pads. A manufactured finding is worse than
        silence because someone has to read it to discover it says nothing."""
        self.assertIn("never pad", _REWRITE_SYSTEM)

    def test_notes_are_capped(self):
        self.assertGreater(MAX_NOTES_PER_FILE, 0)
        self.assertLessEqual(MAX_NOTES_PER_FILE, 10)

    def test_the_report_no_longer_hard_codes_empty_risks(self):
        """The regression that matters. If someone re-hard-codes `risks` to []
        the lane goes mute again and nothing else would notice."""
        import inspect

        from daedalus.providers.deepseek import DeepSeekProvider
        src = inspect.getsource(DeepSeekProvider._run_rewrite)
        self.assertIn('"risks": notes', src)
        self.assertNotIn('"risks": [],', src)


class ToplevelOnly(unittest.TestCase):
    def test_nested_definitions_are_not_counted(self):
        """A rewrite is free to reorganise inner helpers. Counting them would
        make ordinary refactors look like substitutions."""
        src = "def outer():\n    def inner():\n        return 1\n    return inner\n"
        self.assertEqual(_toplevel_defs(src), frozenset({"outer"}))

    def test_unparsable_source_returns_none_rather_than_empty(self):
        """None and 'no definitions' must stay distinguishable -- an empty set
        would read as 'nothing survived' and refuse every rewrite of a file that
        merely failed to parse."""
        self.assertIsNone(_toplevel_defs("def (:::"))
        self.assertEqual(_toplevel_defs("x = 1\n"), frozenset())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
