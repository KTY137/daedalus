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


#: A scratch package carrying every shape of "this module is not what its own
#: top level says it is" that the reader must tell apart. Kept as source text so
#: the fixture and the construct it stands for are the same thing.
_ALIAS_FIXTURE = {
    "__init__.py": "",
    "owner.py": "REAL_NAME = 1\n\n\ndef real_func():\n    return REAL_NAME\n",
    # the construct in daedalus/spine/{envelope,ledger,durability}.py
    "alias_ok.py": (
        "import sys as _sys\n"
        "from pkg import owner as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    "alias_from_sys_modules.py": (
        "from sys import modules as _m\n"
        "from pkg import owner as _owner\n"
        "_m[__name__] = _owner\n"),
    "alias_in_function.py": (
        "import sys as _sys\n"
        "from pkg import owner as _owner\n"
        "def install():\n"
        "    _sys.modules[__name__] = _owner\n"),
    "alias_conditional.py": (
        "import sys as _sys\n"
        "from pkg import owner as _owner\n"
        "if _sys.version_info >= (3, 0):\n"
        "    _sys.modules[__name__] = _owner\n"),
    "alias_other_slot.py": (
        "import sys as _sys\n"
        "from pkg import owner as _owner\n"
        '_sys.modules["pkg.something_else"] = _owner\n'),
    "alias_missing_target.py": (
        "import sys as _sys\n"
        "from pkg import nothing_provides_this as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    "cycle_a.py": (
        "import sys as _sys\n"
        "from pkg import cycle_b as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    "cycle_b.py": (
        "import sys as _sys\n"
        "from pkg import cycle_a as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    "self_alias.py": (
        "import sys as _sys\n"
        "from pkg import self_alias as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    "ns_alias.py": (
        "import sys as _sys\n"
        "from pkg import nsdir as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    # chain_1 -> ... -> chain_5 -> owner is five aliasing hops, one past the
    # budget; short_1 -> ... -> short_4 -> owner is exactly four and must work.
    **{f"chain_{n}.py": (
        "import sys as _sys\n"
        f"from pkg import {'chain_%d' % (n + 1) if n < 5 else 'owner'} as _owner\n"
        "_sys.modules[__name__] = _owner\n") for n in range(1, 6)},
    **{f"short_{n}.py": (
        "import sys as _sys\n"
        f"from pkg import {'short_%d' % (n + 1) if n < 4 else 'owner'} as _owner\n"
        "_sys.modules[__name__] = _owner\n") for n in range(1, 5)},
    # the construct in daedalus/spine/attempt.py
    "retype_ok.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg import owner as _owner\n"
        "class _Facade(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        "_module = sys.modules[__name__]\n"
        "_module.__class__ = _Facade\n"),
    "retype_in_function.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg import owner as _owner\n"
        "class _Facade(ModuleType):\n"
        "    pass\n"
        "def install():\n"
        "    m = sys.modules[__name__]\n"
        "    m.__class__ = _Facade\n"),
    "retype_other_object.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg import owner as _owner\n"
        "class _Facade(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        '_other = sys.modules["pkg.owner"]\n'
        "_other.__class__ = _Facade\n"),
    # ADVERSARIAL REVIEW 2026-09-02: an ordinary, working module wearing two
    # lines that used to switch the reader off. `_Facade` forwards NOTHING.
    "retype_without_a_hook.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _Facade(ModuleType):\n"
        "    pass\n"
        "def real_func():\n"
        "    return 1\n"
        "sys.modules[__name__].__class__ = _Facade\n"),
    "retype_to_object.py": (
        "import sys\n"
        "def real_func():\n"
        "    return 1\n"
        "sys.modules[__name__].__class__ = object\n"),
}

#: A namespace package (PEP 420): a directory with a ``.py`` file and no
#: ``__init__.py``. ``_module_path`` resolves an import of it, and ``_exports``
#: cannot read it -- which is why an alias POINTING at one must not be followed.
_ALIAS_FIXTURE_NAMESPACE_DIR = {"nsdir/leaf.py": "NS_LEAF = 1\n"}


class AliasedModuleTests(unittest.TestCase):
    """A module whose own top level is not what an importer of it gets.

    MEASURED 2026-09-01 at 4efa2a53, the reason this class exists. Three modules
    in this repository end with ``sys.modules[__name__] = _owner`` and a fourth
    installs a forwarding ``ModuleType`` subclass on itself. Reading those files
    literally, ``unresolved_first_party_imports`` refused 134 real committed
    files -- 100 of them for the swap, 34 for the facade -- with messages like
    ``'daedalus.spine.envelope' does not define 'canonical_json'`` for a name
    that resolves perfectly at runtime. A gate with that false-positive rate is
    worse than no gate, because it teaches its readers to ignore it.

    The other half of the class is the part worth not losing: a reader taught to
    follow an alias can be taught to follow too much, so every case below that
    expects a REFUSAL is pinning a hop the reader must NOT take.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        pkg = Path(cls.root) / "pkg"
        pkg.mkdir()
        for name, text in _ALIAS_FIXTURE.items():
            (pkg / name).write_text(text, encoding="utf-8")
        for rel, text in _ALIAS_FIXTURE_NAMESPACE_DIR.items():
            target = pkg / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        assert not (pkg / "nsdir" / "__init__.py").exists()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def judge(self, module, name):
        return unresolved_first_party_imports(
            f"from pkg.{module} import {name}\n", self.root, ("pkg",))

    # -- the alias is followed -------------------------------------------
    def test_a_swapped_module_resolves_through_its_owner(self):
        self.assertEqual(self.judge("alias_ok", "REAL_NAME"), [])
        self.assertEqual(self.judge("alias_ok", "real_func"), [])

    def test_the_from_sys_import_modules_spelling_is_recognised(self):
        self.assertEqual(self.judge("alias_from_sys_modules", "REAL_NAME"), [])

    def test_an_invented_name_is_still_refused_through_the_alias(self):
        """The red proof for the whole rule. Following the alias must buy
        PRECISION, not silence: if the owner does not define it, the fact that
        it was reached through a legacy locator changes nothing."""
        bad = self.judge("alias_ok", "INVENTED")
        self.assertTrue(bad)
        self.assertIn("INVENTED", bad[0])

    def test_an_invented_name_is_refused_through_the_other_spelling(self):
        self.assertTrue(self.judge("alias_from_sys_modules", "INVENTED"))

    # -- hops the reader must NOT take -----------------------------------
    def test_a_swap_inside_a_function_is_not_an_alias(self):
        """A swap that only happens when someone calls the function has not
        happened. Reading the file literally is the correct answer."""
        self.assertTrue(self.judge("alias_in_function", "REAL_NAME"))

    def test_a_swap_inside_an_if_is_not_followed(self):
        """Deliberately strict, and the one case where strictness costs a false
        positive: a conditional swap MIGHT run. No module in this tree spells it
        that way (measured 2026-09-01: three swaps, all unconditional, at module
        scope). If one ever appears, widening this rule is a decision to take
        on purpose rather than a hole to discover."""
        self.assertTrue(self.judge("alias_conditional", "REAL_NAME"))

    def test_writing_another_modules_slot_is_not_an_alias_for_this_one(self):
        self.assertTrue(self.judge("alias_other_slot", "REAL_NAME"))

    def test_retyping_another_module_does_not_make_this_one_opaque(self):
        self.assertTrue(self.judge("retype_other_object", "REAL_NAME"))

    def test_a_retype_inside_a_function_does_not_make_this_one_opaque(self):
        self.assertTrue(self.judge("retype_in_function", "REAL_NAME"))

    # -- what an unfollowable alias must NOT buy --------------------------
    # ADVERSARIAL REVIEW 2026-09-02 broke the first version of these rules three
    # ways, all cheap, all in the permissive direction: every "I cannot follow
    # this owner" answered `opaque`, which accepted every invented name behind
    # it. A guard whose job is to refuse must not fail open on what it cannot
    # follow. Each case below is one of those three, and each must REFUSE.

    def test_an_alias_to_a_target_that_does_not_exist_is_not_followed(self):
        self.assertTrue(self.judge("alias_missing_target", "anything"))

    def test_an_alias_to_a_namespace_package_is_not_followed(self):
        """``pkg/nsdir/`` has a ``.py`` file and no ``__init__.py``, so
        ``_module_path`` resolves it and ``_exports`` cannot read it. This
        repository really has two such directories (``tools`` and ``tests``),
        which is what made this the cheapest of the three bypasses: aliasing to
        one needed no fake class and no chain."""
        self.assertTrue(self.judge("ns_alias", "anything"))

    def test_an_alias_cycle_terminates_and_refuses(self):
        self.assertTrue(self.judge("cycle_a", "anything"))
        self.assertTrue(self.judge("cycle_b", "anything"))
        self.assertTrue(self.judge("self_alias", "anything"))

    def test_a_chain_past_the_hop_budget_refuses_and_one_within_it_resolves(self):
        """The boundary is exact and was measured, not assumed: four aliasing
        hops reach the owner and judge normally; five exhaust the budget one
        hop before a perfectly readable terminal."""
        self.assertEqual(self.judge("short_1", "REAL_NAME"), [])
        self.assertTrue(self.judge("short_1", "INVENTED"))
        self.assertTrue(self.judge("chain_1", "REAL_NAME"))
        self.assertTrue(self.judge("chain_1", "INVENTED"))

    # -- opacity costs a forwarder, exactly as PEP 562 does ---------------
    def test_a_module_that_installs_a_forwarding_type_is_opaque(self):
        """Same concession this module already makes for the eleven PEP 562
        modules in the tree that define a module-level ``__getattr__``: a type
        in control of attribute lookup can answer with names no reader of the
        file can enumerate. Only the spelling differs."""
        self.assertEqual(self.judge("retype_ok", "anything"), [])

    def test_retyping_without_an_attribute_hook_is_not_opaque(self):
        """The adversarial review's most serious finding, pinned.

        A ``ModuleType`` subclass with no ``__getattr__`` forwards NOTHING: the
        module imports cleanly, ``real_func`` works, and importing an invented
        name from it raises ``ImportError`` at runtime. The first version of the
        rule read the two-line retype alone as "unjudgeable" and accepted every
        invented import from an otherwise ordinary module."""
        self.assertTrue(self.judge("retype_without_a_hook", "INVENTED"))
        self.assertEqual(self.judge("retype_without_a_hook", "real_func"), [])

    def test_retyping_to_a_class_this_file_does_not_define_is_not_opaque(self):
        """``__class__ = object`` does not even survive import. Nothing about
        it says a reader should stop reading."""
        self.assertTrue(self.judge("retype_to_object", "INVENTED"))


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
