"""Center-relative Python dotted names (Defect A).

A declared ``center`` means "this subtree IS the project", so it is also the
PACKAGE ROOT. ``TCT_app/controller/danger_gate.py`` runs with ``TCT_app`` on
``sys.path``, so its siblings write ``from controller.danger_gate import ...``.
Naming it by the repo-root form matched nothing and the edge was dropped before
``resolve_python_imports`` ever reached its ``known`` lookup -- which left 87%
of project_tct's code map isolated.

What these tests hold down, in order of how much damage each prevents:

  1. center-relative imports RESOLVE (the fix does its job);
  2. a repo with NO center is byte-identical to the old behaviour -- asserted
     against a re-implementation of the OLD naming formula, not just "it still
     runs", and pinned across PYTHONHASHSEED;
  3. a SHELL file's eligibility never widens -- the dangerous half of this
     change is the membership gate, not the name;
  4. collisions are deterministic and REFUSE to bind rather than guess;
  5. a module with no internal imports stays isolated -- no invented edges.
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.index import _PyNaming, _py_dotted, build_index
from daedalus.structcore.ignore import ProjectScope, project_scope


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


class CenterRelativeResolutionTest(unittest.TestCase):
    """The defect itself: an app whose package root is the center."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        # An app laid out exactly like TCT_app: package root is app/, and its
        # sources import each other by package-relative name.
        _write(self.root, "app/controller/__init__.py", "")
        _write(self.root, "app/controller/danger_gate.py", "class DangerGate: pass\n")
        _write(self.root, "app/devices/bias.py", "class BiasChannel: pass\n")
        _write(self.root, "app/controller/arm.py",
               "from controller.danger_gate import DangerGate\n"
               "from devices.bias import BiasChannel\n")
        # A module that imports NOTHING internal. It must stay isolated.
        _write(self.root, "app/lonely.py", "import logging\nimport math\n")

    def _idx(self, **kw):
        return build_index(self.root, center=["app"], **kw)

    def test_center_relative_imports_resolve_to_real_files(self):
        idx = self._idx()
        self.assertEqual(
            idx["import_edges"].get("app/controller/arm.py"),
            ["app/controller/danger_gate.py", "app/devices/bias.py"],
        )

    def test_dotted_names_are_package_relative_not_repo_relative(self):
        idx = self._idx()
        deps = idx["dependencies"]
        self.assertIn("controller.arm", deps)
        self.assertNotIn("app.controller.arm", deps)
        self.assertEqual(deps["controller.arm"],
                         ["controller.danger_gate", "devices.bias"])

    def test_module_with_no_internal_imports_stays_isolated(self):
        """The failure mode worse than the bug: inventing edges to make the map
        look connected. ``lonely.py`` imports only stdlib and must have no edge
        in either direction."""
        idx = self._idx()
        self.assertNotIn("app/lonely.py", idx["import_edges"])
        self.assertNotIn("app/lonely.py", idx["import_edges_reverse"])

    def test_naming_mode_is_reported(self):
        idx = self._idx()
        self.assertEqual(idx["python_naming"]["mode"], "center-relative")
        self.assertEqual(idx["python_naming"]["package_roots"], ["app"])
        self.assertEqual(idx["python_naming"]["ambiguous_count"], 0)


class ShellEligibilityUnchangedTest(unittest.TestCase):
    """The dangerous half. Stripping ``app/`` puts generic names like
    ``controller`` and ``data`` into a table; if that table were global, the two
    ``parse.py`` branches that gate on ``internal_tops`` with NO ``known`` check
    would let a vendored file's ``import data`` bind onto a center file and
    manufacture a false edge."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "app/data/store.py", "VALUE = 1\n")
        _write(self.root, "app/main.py", "from data.store import VALUE\n")
        # Vendored third-party code importing the REAL PyPI package named
        # `data`, which has nothing to do with app/data/.
        _write(self.root, "vendor/lib/thing.py",
               "import data\nfrom data.store import VALUE\n")

    def test_shell_file_does_not_bind_onto_center_names(self):
        idx = build_index(self.root, center=["app"])
        self.assertEqual(
            idx["import_edges"].get("app/main.py"), ["app/data/store.py"],
            "center file must resolve its package-relative import")
        self.assertNotIn(
            "vendor/lib/thing.py", idx["import_edges"],
            "a shell file must NOT resolve center-relative names -- that would "
            "be a false edge claiming vendored code depends on the app")

    def test_shell_view_is_the_unmodified_repo_root_table(self):
        scope = project_scope(self.root, ["app"], None)
        rels = ["app/data/store.py", "app/main.py", "vendor/lib/thing.py"]
        naming = _PyNaming(rels, scope)
        view = naming.tables_for("vendor/lib/thing.py")
        self.assertEqual(view.known, {_py_dotted(r) for r in rels})
        self.assertEqual(view.tops, {"app", "vendor"})
        self.assertNotIn("data", view.tops)
        self.assertEqual(view.canon, {}, "the shell view has no aliases")


class NoCenterIsUnchangedTest(unittest.TestCase):
    """A repo that never configures a center must get byte-identical output.

    Asserted against a re-implementation of the OLD formula rather than a
    recorded blob, so the guarantee is algebraic and cannot rot silently.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/a.py", "from pkg import b\n")
        _write(self.root, "pkg/b.py", "import pkg.c\n")
        _write(self.root, "pkg/c.py", "")
        _write(self.root, "top.py", "from pkg import a\n")

    def test_tables_equal_the_old_global_formula(self):
        rels = sorted(["pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/c.py",
                       "top.py"])
        naming = _PyNaming(rels, ProjectScope())
        # The pre-fix construction, verbatim.
        old_known = {_py_dotted(r) for r in rels}
        old_tops = {d.split(".")[0] for d in old_known}
        old_rel_by_dotted = {_py_dotted(r): r for r in rels}
        for rel in rels:
            view = naming.tables_for(rel)
            self.assertEqual(view.known, old_known)
            self.assertEqual(view.tops, old_tops)
            self.assertEqual(view.rel_by_dotted, old_rel_by_dotted)
            self.assertEqual(view.canon, {},
                             "no center means no alternate spellings at all")

    def test_no_center_names_are_repo_root(self):
        naming = _PyNaming(["pkg/a.py"], ProjectScope())
        self.assertEqual(naming.name("pkg/a.py"), "pkg.a")

    def test_index_omits_the_naming_block_entirely(self):
        """Additive keys are still a diff. With nothing to report the dict must
        be exactly what it always was."""
        idx = build_index(self.root)
        self.assertNotIn("python_naming", idx)

    def test_index_is_byte_identical_across_pythonhashseed(self):
        """Determinism is load-bearing: the index must not depend on hash
        ordering. Two child processes, two seeds, one JSON blob."""
        repo = str(Path(__file__).resolve().parents[1])
        script = (
            "import json, sys\n"
            "sys.path.insert(0, %r)\n"
            "from daedalus.structcore.index import build_index\n"
            "idx = build_index(%r)\n"
            "idx.pop('backend', None)\n"
            "print(json.dumps(idx, sort_keys=True, default=str))\n"
            % (repo, str(self.root))
        )
        out = []
        for seed in ("0", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r = subprocess.run([sys.executable, "-c", script], env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out.append(r.stdout)
        self.assertEqual(out[0], out[1])
        self.assertIn("pkg.a", json.loads(out[0])["dependencies"])


class CollisionPolicyTest(unittest.TestCase):
    """Two files claiming one dotted name. Deterministic, and never a guess."""

    def test_stub_does_not_shadow_its_real_module(self):
        """A ``.pyi`` DECLARES the module its ``.py`` defines; it is not a
        rival. The old dict-comp bound the name to whichever file os.walk
        reached last, which on project_tct meant 141 names bound to the STUB."""
        naming = _PyNaming(["p/m.py", "p/m.pyi"], ProjectScope())
        view = naming.tables_for("p/m.py")
        self.assertEqual(view.rel_by_dotted["p.m"], "p/m.py")
        self.assertEqual(naming.describe()["ambiguous_count"], 0)

    def test_separate_centers_do_not_collide_with_each_other(self):
        """Two centers both containing ``controller/`` is NOT an ambiguity, and
        the per-view design is why: a view strips only its OWN center, so from
        inside ``a`` the name ``controller.x`` means a's file and b's is still
        ``b.controller.x``. That mirrors the runtime -- ``a`` runs with ``a`` on
        sys.path, not ``b``. Recorded because the obvious single-global-table
        design DOES collide here, and would have to guess."""
        scope = ProjectScope(center=("a", "b"))
        naming = _PyNaming(["a/controller/x.py", "b/controller/x.py", "a/main.py"],
                           scope)
        view_a = naming.tables_for("a/main.py")
        self.assertEqual(view_a.rel_by_dotted["controller.x"], "a/controller/x.py")
        self.assertEqual(view_a.rel_by_dotted["b.controller.x"], "b/controller/x.py")
        view_b = naming.tables_for("b/controller/x.py")
        self.assertEqual(view_b.rel_by_dotted["controller.x"], "b/controller/x.py")
        self.assertEqual(naming.describe()["ambiguous_count"], 0)

    def test_center_name_shadowed_by_a_shell_module_refuses_to_bind(self):
        """The collision class that stripping actually creates: a center file
        named ``controller.x`` after the prefix comes off, and a SHELL tree that
        already owns ``controller/x.py`` at the repo root. Both are real
        modules, both claim one name inside center a's view. A wrong edge lies
        about what depends on what, so the FILE-level binding is dropped."""
        scope = ProjectScope(center=("a",))
        rels = ["a/controller/x.py", "controller/x.py", "a/main.py"]
        naming = _PyNaming(rels, scope)
        view = naming.tables_for("a/main.py")
        self.assertIn("controller.x", view.known,
                      "the NAME-level dependency is still true")
        self.assertNotIn("controller.x", view.rel_by_dotted,
                         "but which FILE it is cannot honestly be said")
        rep = naming.describe()
        self.assertEqual(rep["ambiguous_count"], 1)
        self.assertEqual(rep["ambiguous_sample"][0]["dotted"], "controller.x")
        self.assertEqual(rep["ambiguous_sample"][0]["candidates"],
                         ["a/controller/x.py", "controller/x.py"])
        # The SHELL view is untouched by the shadowing: from outside the center
        # `controller.x` unambiguously means the repo-root file.
        shell = naming.tables_for("controller/x.py")
        self.assertEqual(shell.rel_by_dotted["controller.x"], "controller/x.py")

    def test_refusal_is_independent_of_input_order(self):
        scope = ProjectScope(center=("a",))
        order = ["a/controller/x.py", "controller/x.py"]
        fwd = _PyNaming(order, scope)
        rev = _PyNaming(list(reversed(order)), scope)
        self.assertEqual(fwd.describe(), rev.describe())
        self.assertEqual(fwd.tables_for("a/controller/x.py").rel_by_dotted,
                         rev.tables_for("a/controller/x.py").rel_by_dotted)

    def test_ambiguity_is_surfaced_in_the_index(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "a/controller/x.py", "")
            _write(root, "controller/x.py", "")
            _write(root, "a/main.py", "from controller.x import Thing\n")
            idx = build_index(root, center=["a"])
            self.assertEqual(idx["python_naming"]["ambiguous_count"], 1)
            # The edge is withheld, not guessed.
            self.assertNotIn("a/main.py", idx["import_edges"])


class BothSpellingsResolveToOneIdentityTest(unittest.TestCase):
    """A center sits at one of two places in a real layout and the config
    cannot say which: it either IS the sys.path root (project_tct, whose files
    write ``from controller.x import ...``) or it is a PACKAGE on the parent
    path (whose files write ``from app.controller.x import ...``). Both name
    the same file, so both must resolve -- but the file keeps ONE dotted
    identity, or ``fan_in`` would count it twice."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "app/__init__.py", "")
        _write(self.root, "app/core.py", "def core_init():\n    return 1\n")
        # Package-on-parent-path spelling...
        _write(self.root, "app/via_package.py", "from app import core\n")
        # ...and package-root spelling, in the same tree.
        _write(self.root, "app/via_root.py", "import core\n")

    def test_both_spellings_resolve_to_the_same_file(self):
        idx = build_index(self.root, center=["app"])
        self.assertEqual(idx["import_edges"].get("app/via_package.py"),
                         ["app/core.py"])
        self.assertEqual(idx["import_edges"].get("app/via_root.py"),
                         ["app/core.py"])

    def test_target_has_one_canonical_name_so_fan_in_counts_once(self):
        idx = build_index(self.root, center=["app"])
        self.assertEqual(idx["dependencies"]["via_package"], ["core"],
                         "the alias spelling must be folded to the canonical name")
        self.assertNotIn("app.core", idx["fan_in"],
                         "a second identity here would double-count fan_in")
        self.assertEqual(idx["fan_in"]["core"], 2)

    def test_alias_never_displaces_a_real_module_of_that_name(self):
        """If some file genuinely owns the alias spelling in this view, the
        real module wins and the alias is dropped rather than shadowing it."""
        scope = ProjectScope(center=("app",))
        # A shell tree that really does contain app/core.py's spelling.
        naming = _PyNaming(["app/core.py", "app/main.py"], scope)
        view = naming.tables_for("app/main.py")
        self.assertEqual(view.canon.get("app.core"), "core")
        # Now a shell file legitimately owns "app.core" -- alias must yield.
        naming2 = _PyNaming(["app/core.py", "app/main.py", "app.py"],
                            ProjectScope(center=("app",)))
        view2 = naming2.tables_for("app/main.py")
        self.assertEqual(view2.rel_by_dotted["core"], "app/core.py")


class CenterOwnershipTest(unittest.TestCase):
    """``center_of`` -- one definition of "which package root owns this file"."""

    def test_no_center_owns_nothing(self):
        """Distinct from ``in_center``, which returns True for everything when
        no center is declared. Naming must not strip on an unconfigured repo."""
        scope = ProjectScope()
        self.assertTrue(scope.in_center("any/file.py"))
        self.assertIsNone(scope.center_of("any/file.py"))

    def test_longest_prefix_wins_for_nested_centers(self):
        scope = ProjectScope(center=("a", "a/b"))
        self.assertEqual(scope.center_of("a/b/c.py"), "a/b")
        self.assertEqual(scope.center_of("a/z.py"), "a")
        self.assertIsNone(scope.center_of("other/z.py"))

    def test_nested_center_names_against_the_inner_root(self):
        naming = _PyNaming(["a/b/c.py", "a/z.py"],
                           ProjectScope(center=("a", "a/b")))
        self.assertEqual(naming.name("a/b/c.py"), "c")
        self.assertEqual(naming.name("a/z.py"), "z")


class HotspotRankingIsIndependentOfNamingTest(unittest.TestCase):
    """Reassurance, pinned: this change moves edges and ``fan_in``, and must NOT
    move which modules the map displays. ``score_modules`` does not consume
    ``fan_in``; a future change must not quietly couple them."""

    def test_center_naming_does_not_change_module_heat(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "app/controller/danger.py", "class D: pass\n")
            _write(root, "app/arm.py", "from controller.danger import D\n")
            scoped = build_index(root, center=["app"])
            unscoped = build_index(root)
            self.assertEqual(
                [(h["module"], h["score"]) for h in scoped["module_heat"]],
                [(h["module"], h["score"]) for h in unscoped["module_heat"]])
            # ...while the edges genuinely differ, which is the whole point.
            self.assertIn("app/arm.py", scoped["import_edges"])
            self.assertNotIn("app/arm.py", unscoped["import_edges"])


if __name__ == "__main__":
    unittest.main()
