# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""A star import can prove an AMBIGUITY. It can never prove a BINDING.

Adversarial regression suite for three I5 violations found by probing the
resolver rather than by reading it. Each one produced a RESOLVED ``consumes``
edge to a declaration that the annotation site cannot actually name:

  A. ``__all__``.  ``from lib import *`` binds ``lib.__all__`` and nothing else
     when ``lib`` defines it.  ``__all__`` is a bare module-level assignment,
     which ``parse.py`` deliberately does not record, so ``typegraph`` cannot
     see it -- and 85 files in this repository declare one.  The edge pointed at
     a name that is a ``NameError`` where it was used.
  B. The leading underscore.  With no ``__all__`` a star never binds a name
     beginning with ``_``.  81 files here declare such a type.
  C. A star whose module is not in this repo.  Its contents are unknowable, so
     "the one visible star supplies this name" is a fact about the environment,
     not about the source -- the identical argument that already refuses the
     ``try``/``except ImportError`` pair.

The fix is in ``_Resolver._resolve``: star candidates are still generated (two
stars that both declare the name is a provable ambiguity, and naming the
candidates makes the refusal actionable), but a candidate reached ONLY through a
star can never be the single winner.

THE PROBE IS NOT VACUOUS.  ``PositiveControls`` asserts that the ordinary
explicit-binding paths still resolve, so "refuse everything" cannot pass this
file, and ``TheBlastRadiusIsMeasured`` records that closing the hole costs
``daedalus/`` exactly zero edges -- no file in it uses ``import *``.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from daedalus.structcore import index as index_mod           # noqa: E402
from daedalus.structcore import typegraph as tg              # noqa: E402
from daedalus.structcore.parse import python_type_facts      # noqa: E402


def _build(files: dict[str, str]) -> tuple[Path, dict]:
    root = Path(tempfile.mkdtemp(prefix="tgstar-"))
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    index_mod._INDEX_CACHE.clear()
    index_mod._RESOLVER_CACHE.clear()
    return root, index_mod.build_index(root, types=True)


def _members(idx: dict, relation: str) -> list[tuple[str, str, str]]:
    """(source, target, resolved member name) for one relation layer."""
    return sorted(
        (row["source"], row["target"], str(row["attributes"].get("member", "")))
        for row in idx["type_edges"][relation]
    )


class _Case(unittest.TestCase):
    FILES: dict[str, str] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.root, cls.idx = _build(cls.FILES)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def targets_of(self, member: str, relation: str = tg.REL_CONSUMES):
        return [row for row in _members(self.idx, relation) if row[2] == member]


class AStarDoesNotBindWhatAllExcludes(_Case):
    FILES = {
        "lib.py": "__all__ = ['Public']\n\n\nclass Public:\n    pass\n\n\n"
                  "class Hidden:\n    pass\n",
        "user.py": "from lib import *\n\n\n"
                   "def f(a: Public, b: Hidden) -> None:\n    return None\n",
    }

    def test_the_excluded_name_produces_no_edge(self):
        self.assertEqual(self.targets_of("Hidden"), [])

    def test_the_refusal_is_counted_and_named(self):
        cov = self.idx["types"]["coverage"]
        self.assertGreater(cov["ambiguous"] + cov["unresolved"], 0)
        named = {row["name"] for row in cov["ambiguous_sample"]}
        named |= {row["name"] for row in cov["unresolved_sample"]}
        self.assertIn("Hidden", named)

    def test_the_declaration_still_exists_as_a_node(self):
        """The refusal is about the EDGE, not about the declaration: ``Hidden``
        is really declared in ``lib.py`` and is really a node.  Deleting the
        node too would hide a fact rather than decline to guess at one."""
        self.assertIn(tg.type_node_id("lib.py", "Hidden"),
                      {node["id"] for node in self.idx["type_nodes"]})


class AStarDoesNotBindAnUnderscoreName(_Case):
    FILES = {
        "lib2.py": "class Public2:\n    pass\n\n\nclass _Private:\n    pass\n",
        "user2.py": "from lib2 import *\n\n\n"
                    "def g(a: _Private) -> None:\n    return None\n",
    }

    def test_the_underscore_name_produces_no_edge(self):
        self.assertEqual(self.targets_of("_Private"), [])

    def test_nothing_at_all_was_resolved_through_the_star(self):
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            with self.subTest(relation=relation):
                self.assertEqual(
                    [row for row in _members(self.idx, relation)
                     if row[0] == "user2.py"], [])


class AnInvisibleStarMakesTheAnswerEnvironmental(_Case):
    """Only ONE of the two stars is a module we can see.  Whether the visible
    one supplies the name depends on what the other one exports, which is not a
    property of this source tree."""

    FILES = {
        "alpha.py": "class Result:\n    pass\n",
        "userc.py": "from alpha import *\nfrom some_external_pkg import *\n\n\n"
                    "def h(r: Result) -> None:\n    return None\n",
    }

    def test_no_edge_to_the_visible_candidate(self):
        self.assertEqual(self.targets_of("Result"), [])

    def test_the_visible_candidate_is_still_reported(self):
        """Refusing is not the same as being silent: the candidate we DID find
        is named in the sample, so the gap is actionable."""
        cov = self.idx["types"]["coverage"]
        rows = [row for row in cov["ambiguous_sample"] if row["name"] == "Result"]
        self.assertTrue(rows)
        self.assertIn(tg.type_node_id("alpha.py", "Result"),
                      rows[0]["candidates"])


class AStarThatDisagreesWithAnExplicitBinding(_Case):
    """An explicit ``from`` binding AND a star that reaches a DIFFERENT
    declaration of the same name.  Which wins is statement order plus the star
    module's ``__all__``; neither is readable here, so the answer is refused."""

    FILES = {
        "one.py": "class Thing:\n    pass\n",
        "two.py": "class Thing:\n    pass\n",
        "userd.py": "from one import Thing\nfrom two import *\n\n\n"
                    "def d(t: Thing) -> None:\n    return None\n",
    }

    def test_the_disagreement_produces_no_edge(self):
        self.assertEqual(self.targets_of("Thing"), [])

    def test_both_candidates_are_named(self):
        cov = self.idx["types"]["coverage"]
        rows = [row for row in cov["ambiguous_sample"] if row["name"] == "Thing"]
        self.assertTrue(rows)
        self.assertEqual(sorted(rows[0]["candidates"]),
                         [tg.type_node_id("one.py", "Thing"),
                          tg.type_node_id("two.py", "Thing")])


class PositiveControls(_Case):
    """"Refuse everything" must not be able to pass this file."""

    FILES = {
        "m1.py": "class User:\n    pass\n",
        "m2.py": "from m1 import User\n\n\n"
                 "def p(u: User) -> User:\n    return u\n",
        "m3.py": "from typing import TYPE_CHECKING\nfrom m1 import User\n"
                 "if TYPE_CHECKING:\n    from m1 import User\n\n\n"
                 "def q(u: User) -> None:\n    return None\n",
        "m4.py": "class Local:\n    pass\n\n\n"
                 "def r(x: Local) -> Local:\n    return x\n",
    }

    def test_an_explicit_cross_module_binding_still_resolves(self):
        user = tg.type_node_id("m1.py", "User")
        self.assertIn(("m2.py", user, "User"), _members(self.idx, tg.REL_CONSUMES))
        self.assertIn(("m2.py", user, "User"), _members(self.idx, tg.REL_PRODUCES))

    def test_an_agreeing_type_checking_duplicate_still_resolves(self):
        self.assertIn(("m3.py", tg.type_node_id("m1.py", "User"), "User"),
                      _members(self.idx, tg.REL_CONSUMES))

    def test_a_same_file_declaration_still_resolves(self):
        local = tg.type_node_id("m4.py", "Local")
        self.assertIn(("m4.py", local, "Local"), _members(self.idx, tg.REL_CONSUMES))

    def test_nothing_was_refused_here(self):
        cov = self.idx["types"]["coverage"]
        self.assertEqual(cov["ambiguous"], 0)
        self.assertGreater(cov["resolved"], 0)


class TwoVisibleStarsAreStillTheOldAmbiguity(_Case):
    """The behaviour the fixture corpus already pinned must not have changed:
    two stars that BOTH declare the name were, and remain, ambiguous."""

    FILES = {
        "a1.py": "class R:\n    pass\n",
        "a2.py": "class R:\n    pass\n",
        "usere.py": "from a1 import *\nfrom a2 import *\n\n\n"
                    "def e(x: R) -> None:\n    return None\n",
    }

    def test_still_ambiguous_with_both_candidates(self):
        self.assertEqual(self.targets_of("R"), [])
        rows = [row for row in self.idx["types"]["coverage"]["ambiguous_sample"]
                if row["name"] == "R"]
        self.assertTrue(rows)
        self.assertEqual(sorted(rows[0]["candidates"]),
                         [tg.type_node_id("a1.py", "R"),
                          tg.type_node_id("a2.py", "R")])


class TheBlastRadiusIsMeasured(unittest.TestCase):
    """What the refusal costs, stated as a number rather than assumed to be
    small.  If a star import ever appears under ``daedalus/`` this test fails
    and the cost has to be re-argued rather than silently paid."""

    def test_no_file_under_daedalus_uses_a_star_import(self):
        offenders = []
        for path in sorted((REPO_ROOT / "daedalus").rglob("*.py")):
            rel = path.relative_to(REPO_ROOT / "daedalus").as_posix()
            facts = python_type_facts(
                rel, path.read_text(encoding="utf-8", errors="replace"))
            if any(alias.local == "*" for alias in facts.aliases):
                offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_a_dotted_name_never_consults_the_star_tables(self):
        """``import *`` binds bare names only, so the dotted path is unchanged
        by the fix and keeps resolving through the module binding."""
        root, idx = _build({
            "pkg/__init__.py": "",
            "pkg/inner.py": "class Deep:\n    pass\n",
            "userf.py": "import pkg.inner\nfrom pkg.inner import *\n\n\n"
                        "def f(d: pkg.inner.Deep) -> None:\n    return None\n",
        })
        try:
            self.assertIn(
                ("userf.py", tg.type_node_id("pkg/inner.py", "Deep"), "pkg.inner.Deep"),
                _members(idx, tg.REL_CONSUMES))
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TheInvariantsSurviveTheFix(unittest.TestCase):
    """The fix must not have bought I5 at the price of another invariant."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root, cls.idx = _build({
            "lib.py": "__all__ = ['P']\n\n\nclass P:\n    pass\n\n\n"
                      "class H:\n    pass\n",
            "user.py": "from lib import *\n\n\ndef f(a: P, b: H) -> None:\n"
                       "    return None\n",
        })

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_attempts_still_equals_the_sum_of_the_buckets(self):
        cov = self.idx["types"]["coverage"]
        self.assertEqual(
            cov["attempts"],
            sum(cov[name] for name in ("resolved", "unresolved", "ambiguous",
                                       "external", "builtin", "vocabulary")))

    def test_no_refused_site_produced_an_edge(self):
        cov = self.idx["types"]["coverage"]
        refused = {(row["module"], row["line"], row["name"])
                   for row in cov["ambiguous_sample"]}
        refused |= {(row["module"], row["line"], row["name"])
                    for row in cov["unresolved_sample"]}
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            for row in self.idx["type_edges"][relation]:
                site = (row["source"], row["attributes"]["line"],
                        row["attributes"].get("member"))
                with self.subTest(relation=relation, site=site):
                    self.assertNotIn(site, refused)

    def test_the_build_is_still_reproducible(self):
        second = index_mod.build_index(self.root, types=True)
        for key in ("type_nodes", "type_edges", "types"):
            with self.subTest(key=key):
                self.assertEqual(second[key], self.idx[key])


if __name__ == "__main__":
    unittest.main()
