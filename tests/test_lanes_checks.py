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
    # SECURITY REVIEW 2026-09-02, second round: five constructs that defeated
    # the FIRST fix, all by exploiting that the retype detector was
    # flow-insensitive and name-based while `_alias_target` got last-write-wins
    # discipline. Every one of these was ACCEPTED by the flow-insensitive
    # detector, and at runtime none of them serves a single forwarded name --
    # the module type ends up plain `module` (or a hookless class, or the
    # import crashes outright). Each must be judged LITERALLY.
    #
    # c1: the hook-bearing class is SHADOWED by a same-named hookless class
    # before the retype; at runtime the module wears the hookless one.
    "retype_hook_class_shadowed.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "class _F(ModuleType):\n"
        "    pass\n"
        "sys.modules[__name__].__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # c2 / the working end-to-end exploit: the slot is read into `_m`, `_m` is
    # REBOUND to a scratch module, and the scratch module is retyped. The dead
    # first line is what fooled the name-based detector; the real module's type
    # is never touched.
    "retype_holder_rebound.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        '_m = ModuleType("scratch")\n'
        "_m.__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # c3: the retype is written BEFORE the slot binding. At runtime this is a
    # NameError at import -- the module never loads at all.
    "retype_before_binding.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m.__class__ = _F\n"
        "_m = sys.modules[__name__]\n"
        "def real_func():\n"
        "    return 1\n"),
    # c4: chained targets, then the retyped NAME is rebound first.
    "retype_tuple_rebound.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_a = _b = sys.modules[__name__]\n"
        '_a = ModuleType("scratch")\n'
        "_a.__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # c5: the retype happens and is then UNDONE; the surviving type is plain.
    "retype_undone.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "_m.__class__ = ModuleType\n"
        "def real_func():\n"
        "    return 1\n"),
    # The complement: the retype reaches the module THROUGH a copied name, and
    # survives. At runtime the module really is hooked, so opacity is correct.
    "retype_via_copied_name.py": (
        "import sys\n"
        "from pkg import owner as _owner\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        "_m = sys.modules[__name__]\n"
        "_alias = _m\n"
        "_alias.__class__ = _F\n"),
    # And shadowing in the OTHER direction: hookless first, hook-bearing class
    # of the same name is the one that survives and is installed. Truly opaque.
    "retype_shadowed_to_hook.py": (
        "import sys\n"
        "from pkg import owner as _owner\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    pass\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        "sys.modules[__name__].__class__ = _F\n"),
    # c6, second review pass: the hook is DELETED inside the same class body.
    # At runtime the class ends hookless; the retype installs a mute facade.
    "retype_hook_deleted.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "    del __getattr__\n"
        "sys.modules[__name__].__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # An owner whose text the gate cannot parse: a UTF-8 BOM read as utf-8
    # leaves U+FEFF in front of the source and ast.parse refuses it. The
    # fail-open on importing such a file DIRECTLY is pre-existing (base
    # behavior, measured, not this packet's to fix); what must not happen is a
    # HOP inheriting it. The BOM is spelled explicitly so nobody's editor
    # silently strips an invisible character out of the fixture.
    "bom_owner.py": "\ufeffREAL_NAME = 1\n",
    "alias_to_bom.py": (
        "import sys as _sys\n"
        "from pkg import bom_owner as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    # A self-alias spelled in a different CASE. On this case-insensitive
    # filesystem `_module_path` resolves `pkg.Case_Self_Alias` to this very
    # file under another spelling, so a naive unresolved-Path comparison does
    # not see the cycle.
    "case_self_alias.py": (
        "import sys as _sys\n"
        "from pkg import Case_Self_Alias as _owner\n"
        "_sys.modules[__name__] = _owner\n"),
    # SECURITY REVIEW 2026-09-02, THIRD round -- the reviewer's own constructs,
    # verbatim in shape. Three root causes, all inside the flow-sensitive fix
    # itself, all one level deeper than round two: the class-body hook scan was
    # still flat; a class decorator can replace the class outright; and the
    # `hooked` flag was the one piece of state no unmodelled statement reset.
    # Every one of these was ACCEPTED at 3e212da8 and forwards nothing at
    # runtime (n1/n4/n5/n6/n7 end as plain `module`, n2 wears a hookless class,
    # n3 raises TypeError on any miss).
    #
    # n1: the decorator replaces the class with plain ModuleType; the BODY has
    # a hook, the surviving CLASS does not.
    "retype_decorated_class.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "def _strip(cls):\n"
        "    return ModuleType\n"
        "@_strip\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # n2: the hook is deleted inside a compound statement IN THE CLASS BODY --
    # invisible to a flat scan of class members.
    "retype_hook_del_under_if.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "    if 1:\n"
        "        del __getattr__\n"
        "sys.modules[__name__].__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # n3: the hook is overwritten with None under the same shape; at runtime
    # every attribute miss is a TypeError, not a forwarded name.
    "retype_hook_none_under_if.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "    if 1:\n"
        "        __getattr__ = None\n"
        "sys.modules[__name__].__class__ = _F\n"
        "def real_func():\n"
        "    return 1\n"),
    # n4/n5/n6: the retype is UNDONE inside a module-scope compound statement.
    # Round two's walk killed name BINDINGS on unmodelled shapes but never the
    # `hooked` flag itself -- the only output that matters.
    "retype_undone_in_if.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "if 1:\n"
        "    _m.__class__ = ModuleType\n"
        "def real_func():\n"
        "    return 1\n"),
    "retype_undone_in_for.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "for _ in range(1):\n"
        "    _m.__class__ = ModuleType\n"
        "def real_func():\n"
        "    return 1\n"),
    "retype_undone_in_try.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "try:\n"
        "    _m.__class__ = ModuleType\n"
        "finally:\n"
        "    pass\n"
        "def real_func():\n"
        "    return 1\n"),
    # n7 (found here, same third root cause): the undo reaches the module
    # through a container subscript the walk cannot attribute to the slot.
    "retype_undone_via_container.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "_x = [_m]\n"
        "_x[0].__class__ = ModuleType\n"
        "def real_func():\n"
        "    return 1\n"),
    # SECURITY REVIEW 2026-09-02, FOURTH round. The gap sat exactly between
    # round three's commit message ("closes the adjacent import-time-execution
    # family") and its dispatch table: `ast.Import` and `ast.ImportFrom` were
    # the two branches that never touched `hooked`, and an import statement
    # executes an ENTIRE MODULE BODY while containing ZERO Call nodes, so the
    # pre-dispatch Call reset did not fire either.
    #
    # Each helper reaches back through `sys.modules` and retypes the
    # partially-initialised importer to plain `ModuleType`. VERIFIED at
    # runtime, not assumed: every victim below ends as type `module`, its
    # `real_func` still works, and an invented name raises -- held to the bar
    # the reviewer set when it withdrew its own AnnAssign finding for
    # targeting the wrong module name.
    "h_undo1.py": (
        "import sys\n"
        "from types import ModuleType\n"
        'sys.modules["pkg.import_undo_plain"].__class__ = ModuleType\n'),
    "h_undo2.py": (
        "import sys\n"
        "from types import ModuleType\n"
        'sys.modules["pkg.import_undo_from"].__class__ = ModuleType\n'),
    "h_undo3.py": (
        "import sys\n"
        "from types import ModuleType\n"
        'sys.modules["pkg.import_undo_from_name"].__class__ = ModuleType\n'
        "marker = 1\n"),
    # r1: `import pkg.h_undo1` after the retype.
    "import_undo_plain.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "import pkg.h_undo1\n"
        "def real_func():\n"
        "    return 1\n"),
    # r2: `from pkg import h_undo2`.
    "import_undo_from.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "from pkg import h_undo2\n"
        "def real_func():\n"
        "    return 1\n"),
    # r3: `from pkg.h_undo3 import marker`.
    "import_undo_from_name.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "from pkg.h_undo3 import marker\n"
        "def real_func():\n"
        "    return 1\n"),
    # r4/r5: the "subscript bound" round three documented as an exotic corner,
    # WEAPONISED -- and the reviewer was right that it is the import hole
    # wearing a different hat, because an ImportFrom is what gets the
    # malicious object into scope at all. MEASURED: the import sits BEFORE the
    # retype, so resetting `hooked` at the import does NOT close these; only
    # refusing to trust a non-inert expression AFTER the retype does. r5 is
    # the same attack with an attribute load instead of a subscript, which is
    # why closing only subscripts would have been theatre.
    "h_evil_item.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _Evil:\n"
        "    def __getitem__(self, i):\n"
        '        sys.modules["pkg.load_undo_subscript"].__class__ = ModuleType\n'
        "        return 1\n"
        "EVIL = _Evil()\n"),
    "h_evil_attr.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "class _Evil:\n"
        "    def __getattr__(self, name):\n"
        '        sys.modules["pkg.load_undo_attribute"].__class__ = ModuleType\n'
        '        return "x"\n'
        "EVIL = _Evil()\n"),
    "load_undo_subscript.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg.h_evil_item import EVIL\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "_y = EVIL[0]\n"
        "def real_func():\n"
        "    return 1\n"),
    "load_undo_attribute.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg.h_evil_attr import EVIL\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        raise AttributeError(name)\n"
        "sys.modules[__name__].__class__ = _F\n"
        "_y = EVIL.__file__\n"
        "def real_func():\n"
        "    return 1\n"),
    # The shape the REAL facade uses, which the fix must keep opaque: a
    # machinery dunder read off a name bound to a genuine SUBMODULE, then
    # stored on the retyped module. `daedalus/spine/attempt.py` ends exactly
    # this way, and its 34 dependent files are the control census.
    "retype_then_module_dunder.py": (
        "import sys\n"
        "from types import ModuleType\n"
        "from pkg import owner as _owner\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        "_m = sys.modules[__name__]\n"
        "_m.__class__ = _F\n"
        "_m.__file__ = _owner.__file__\n"),
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

    # -- SECURITY REVIEW 2026-09-02, second round -------------------------
    # The retype detector must be flow-sensitive: opacity is granted only when
    # the hook-bearing retype is the SURVIVING module-scope state, mirroring
    # the last-write-wins discipline `_alias_target` already has. Each of the
    # six constructs below was ACCEPTED by the flow-insensitive first fix and
    # serves no forwarded name at runtime; each must refuse the invented name
    # and (where the module loads at all) pass the real one.

    def test_a_hook_class_shadowed_by_a_hookless_one_is_not_opaque(self):
        self.assertTrue(self.judge("retype_hook_class_shadowed", "INVENTED"))
        self.assertEqual(self.judge("retype_hook_class_shadowed", "real_func"), [])

    def test_a_rebound_holder_does_not_retype_this_module(self):
        """The working end-to-end exploit: the slot is read into a name, the
        name is rebound to a scratch module, the scratch module is retyped.
        The first line is dead and the real module's type is never touched."""
        self.assertTrue(self.judge("retype_holder_rebound", "INVENTED"))
        self.assertEqual(self.judge("retype_holder_rebound", "real_func"), [])

    def test_a_retype_before_the_slot_binding_is_not_opaque(self):
        """At runtime this module is a NameError at import -- it never loads.
        A reader that calls it opaque asserts a fact about a module that does
        not exist."""
        self.assertTrue(self.judge("retype_before_binding", "INVENTED"))

    def test_a_rebound_chained_target_does_not_retype_this_module(self):
        self.assertTrue(self.judge("retype_tuple_rebound", "INVENTED"))
        self.assertEqual(self.judge("retype_tuple_rebound", "real_func"), [])

    def test_an_undone_retype_is_not_opaque(self):
        """The surviving type is plain ``ModuleType``. Only the surviving
        state counts, exactly as it does for the swap."""
        self.assertTrue(self.judge("retype_undone", "INVENTED"))
        self.assertEqual(self.judge("retype_undone", "real_func"), [])

    def test_a_hook_deleted_in_the_class_body_is_not_a_hook(self):
        """c6: ``def __getattr__`` then ``del __getattr__`` in the same class
        body. The class the module ends up wearing has no hook."""
        self.assertTrue(self.judge("retype_hook_deleted", "INVENTED"))
        self.assertEqual(self.judge("retype_hook_deleted", "real_func"), [])

    # -- and the states that really DO survive ----------------------------
    def test_a_retype_through_a_copied_name_is_opaque(self):
        """The flow-sensitive detector must not lose the true positive: the
        slot reference copied through a second name still reaches the module,
        and the hook really is installed at runtime."""
        self.assertEqual(self.judge("retype_via_copied_name", "anything"), [])

    def test_a_hook_class_that_shadows_a_hookless_one_is_opaque(self):
        self.assertEqual(self.judge("retype_shadowed_to_hook", "anything"), [])

    # -- an unreadable owner must not hand its fail-open to a hop ----------
    def test_an_alias_to_an_unparsable_owner_refuses(self):
        """A UTF-8 BOM read as utf-8 leaves U+FEFF in the text and
        ``ast.parse`` refuses it, which makes the owner opaque when imported
        DIRECTLY -- a pre-existing fail-open this packet inherits and records
        rather than fixes. What a hop must not do is inherit it: an alias to
        an unparsable owner is judged on what is provable about the ALIAS
        file, which is its literal top level, which refuses."""
        self.assertTrue(self.judge("alias_to_bom", "ANYTHING"))

    def test_a_self_alias_in_a_different_case_refuses(self):
        """`pkg.Case_Self_Alias` resolves to `case_self_alias.py` on a
        case-insensitive filesystem, so an unresolved case-sensitive Path
        comparison does not see the cycle. The comparison must be on
        resolved, case-normalized paths -- and either way the terminal state
        is a refusal, never an accept."""
        self.assertTrue(self.judge("case_self_alias", "ANYTHING"))

    # -- SECURITY REVIEW 2026-09-02, THIRD round --------------------------
    # Same lesson one level deeper, three times: the class-body scan must be
    # as order- and scope-honest as the module walk; a decorator makes a
    # class statically unknowable; and the opacity flag itself must die on
    # any statement the walk does not model, not just the name bindings.

    def test_a_decorated_hook_class_is_not_trusted(self):
        """n1: the decorator replaces the class outright (here with plain
        ``ModuleType``); recording the BODY's hook state asserts a fact about
        a class object that never survives decoration."""
        self.assertTrue(self.judge("retype_decorated_class", "INVENTED"))
        self.assertEqual(self.judge("retype_decorated_class", "real_func"), [])

    def test_a_hook_deleted_inside_an_if_in_the_class_body_is_seen(self):
        """n2: round two fixed the flat scan at module scope and then wrote a
        new flat scan inside ``class_has_surviving_hook``."""
        self.assertTrue(self.judge("retype_hook_del_under_if", "INVENTED"))
        self.assertEqual(self.judge("retype_hook_del_under_if", "real_func"), [])

    def test_a_hook_overwritten_inside_an_if_in_the_class_body_is_seen(self):
        """n3: same shape, ``__getattr__ = None``. At runtime every attribute
        miss is a TypeError; nothing is forwarded."""
        self.assertTrue(self.judge("retype_hook_none_under_if", "INVENTED"))

    def test_an_undo_inside_an_if_kills_opacity(self):
        """n4: eight lines. `kill_bound_names` reset the ENV on unmodelled
        statements while `hooked` -- the only output that matters -- survived
        every one of them."""
        self.assertTrue(self.judge("retype_undone_in_if", "INVENTED"))
        self.assertEqual(self.judge("retype_undone_in_if", "real_func"), [])

    def test_an_undo_inside_a_for_kills_opacity(self):
        self.assertTrue(self.judge("retype_undone_in_for", "INVENTED"))
        self.assertEqual(self.judge("retype_undone_in_for", "real_func"), [])

    def test_an_undo_inside_a_try_kills_opacity(self):
        self.assertTrue(self.judge("retype_undone_in_try", "INVENTED"))
        self.assertEqual(self.judge("retype_undone_in_try", "real_func"), [])

    def test_an_undo_through_a_container_kills_opacity(self):
        """n7, same root cause as n4-n6: a ``__class__`` store whose holder
        the walk cannot attribute to the slot must still kill the flag --
        an unattributable retype is exactly the kind of statement that may
        have undone the one that was attributed."""
        self.assertTrue(self.judge("retype_undone_via_container", "INVENTED"))
        self.assertEqual(
            self.judge("retype_undone_via_container", "real_func"), [])

    # -- SECURITY REVIEW 2026-09-02, FOURTH round -------------------------
    # An import runs a whole module body and contains no Call node. Round
    # three's Call-based reset could not see it, and the Import/ImportFrom
    # branches were the only two that never touched `hooked`.

    def test_a_plain_import_after_a_retype_kills_opacity(self):
        self.assertTrue(self.judge("import_undo_plain", "INVENTED"))
        self.assertEqual(self.judge("import_undo_plain", "real_func"), [])

    def test_a_from_import_of_a_module_after_a_retype_kills_opacity(self):
        self.assertTrue(self.judge("import_undo_from", "INVENTED"))
        self.assertEqual(self.judge("import_undo_from", "real_func"), [])

    def test_a_from_import_of_a_name_after_a_retype_kills_opacity(self):
        self.assertTrue(self.judge("import_undo_from_name", "INVENTED"))
        self.assertEqual(self.judge("import_undo_from_name", "real_func"), [])

    def test_a_subscript_load_after_a_retype_kills_opacity(self):
        """r4. MEASURED: the ImportFrom that puts ``EVIL`` in scope sits
        BEFORE the retype, so resetting on imports alone does not close this.
        Only refusing to trust a non-inert expression after the retype
        does."""
        self.assertTrue(self.judge("load_undo_subscript", "INVENTED"))
        self.assertEqual(self.judge("load_undo_subscript", "real_func"), [])

    def test_an_attribute_load_after_a_retype_kills_opacity(self):
        """r5, the same attack one keystroke away from r4. Closing only
        subscripts would have been theatre: ``EVIL.__file__`` runs
        ``_Evil.__getattr__`` just as ``EVIL[0]`` runs ``__getitem__``."""
        self.assertTrue(self.judge("load_undo_attribute", "INVENTED"))
        self.assertEqual(self.judge("load_undo_attribute", "real_func"), [])

    def test_the_real_facade_shape_survives_the_inertness_rule(self):
        """The control that stops the fix from being a stone that always
        refuses. ``daedalus/spine/attempt.py`` ends with a machinery dunder
        read off a genuine submodule and stored on the retyped module; the
        34 files that import through it are the control census. If this goes
        red, the packet's primary claim dies with it."""
        self.assertEqual(self.judge("retype_then_module_dunder", "anything"), [])


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
