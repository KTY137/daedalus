# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""S1/S2 regression at the INDEX level, and where the two fixes meet scope.

The adjacent suites already cover the halves of this in isolation:
  * ``test_structcore_cnames.py``  -- S1 naming, unit-level, via ``extract_units``
    directly (every C/C++ shape, plus the Type-3 hold-out).
  * ``test_structcore_slice.py``   -- S2 neighborhood expansion for a C target.
  * ``test_structcore_ignore.py``  -- the center/shell boundary itself.

What none of them exercise, and what this file is for:

  1. S1's BLAST RADIUS rather than S1's mechanism. Naming was never the point --
     the point is the three things that were silently degraded by the missing
     name. Only one of them is a parse assertion. "file.cpp::SomeFunc" failing
     to resolve is invisible at the ``extract_units`` level because the whole
     file is returned and it LOOKS like a slice.
  2. Names surviving ``build_index``. The cnames suite calls ``extract_units``
     directly, so a regression in the cached/parallel per-file path -- the one
     that actually feeds every consumer -- would not be caught by it.
  3. S1 x scope. ``test_ignored_files_do_not_form_clone_clusters`` uses PYTHON
     files. Before S1 no C/C++ unit could carry a real name, so no C/C++ shell
     unit could be attributed to a cluster in the first place; naming them is
     exactly what makes this leak newly POSSIBLE, and nothing tested it.
  4. Determinism of unit names and cluster MEMBERSHIP across a rebuild. Existing
     determinism tests pin slice text and the ignored sample, not these.

Skips cleanly when tree-sitter is absent (the C/C++ path needs it).
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.index import build_index
from daedalus.structcore.parse import tree_sitter_available
from daedalus.structcore.slice import semantic_slice

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# A C function long enough to clear ``unit_clusters``' min_loc.
C_BODY = """int checksum_block(const unsigned char *p, int n) {
    int acc = 0;
    for (int i = 0; i < n; i++) {
        acc = (acc << 1) ^ p[i];
    }
    return acc;
}
"""

C_SIBLING = """unsigned rotate_left(unsigned v, int k) {
    unsigned lo = v << k;
    unsigned hi = v >> (32 - k);
    return lo | hi;
}
"""

CPP_BODY = """int Engine::tally(const int *p, int n) {
    int acc = 0;
    for (int i = 0; i < n; i++) {
        acc = (acc << 1) ^ p[i];
    }
    return acc;
}
"""

WIDGET_CPP = '''#include "widget.h"

int Widget::compute(int x) const {
    int acc = 0;
    for (int i = 0; i < x; i++) { acc += i; }
    return acc;
}

void Widget::reset() {
    cached_ = 0;
    dirty_ = true;
}

Widget::Widget(int x) : seed_(x) {
    cached_ = 0;
}

Widget::~Widget() {
    release(cached_);
}

template<typename T> T Box<T>::get() const {
    return value_;
}
'''


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class CppSymbolSliceTest(unittest.TestCase):
    """S1 blast radius #2: "file.cpp::SomeFunc" never resolved, so the symbol
    slice silently degraded to the WHOLE FILE.

    This is the failure mode worth a dedicated test because it is invisible from
    the outside: a degraded slice is a well-formed slice containing strictly more
    than was asked for. Nothing raised, nothing was reported -- callers just
    quietly paid for the entire file. The last test here pins the degradation
    itself, so the contrast is asserted and not merely described.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "src/widget.h",
               "class Widget { int compute(int x) const; void reset(); };\n")
        _write(self.root, "src/widget.cpp", WIDGET_CPP)
        # Two units, so "the slice contains checksum_block" cannot pass on the
        # whole-file fallback -- the second function is the discriminator.
        _write(self.root, "src/util.c", C_BODY + "\n" + C_SIBLING)
        self.idx = build_index(self.root)

    def _focus(self, target: str) -> str:
        res = semantic_slice(self.root, target, idx=self.idx)
        self.assertEqual(res["focus_file"], target.split("::", 1)[0])
        return res["slice_text"].split("# =====", 2)[1]

    def test_out_of_line_method_symbol_resolves(self):
        block = self._focus("src/widget.cpp::Widget::compute")
        self.assertIn("Widget::compute", block)
        # the neighbouring methods must NOT be dragged in -- that is the bug
        self.assertNotIn("Widget::reset", block)
        self.assertNotIn("Widget::~Widget", block)

    def test_constructor_destructor_and_template_symbols_resolve(self):
        for sym, absent in (("Widget::Widget", "Widget::compute"),
                            ("Widget::~Widget", "Widget::compute"),
                            ("Box<T>::get", "Widget::reset")):
            with self.subTest(sym):
                block = self._focus("src/widget.cpp::" + sym)
                self.assertIn(sym, block)
                self.assertNotIn(absent, block)

    def test_plain_c_function_symbol_resolves(self):
        res = semantic_slice(self.root, "src/util.c::checksum_block", idx=self.idx)
        self.assertEqual(res["focus_symbol"], "checksum_block")
        block = res["slice_text"].split("# =====", 2)[1]
        self.assertIn("checksum_block", block)
        # The load-bearing half: ``focus_symbol`` is just the parsed target
        # string and is set even when nothing resolved, and the whole-file
        # fallback contains the requested name too. Only the ABSENCE of the
        # sibling proves a symbol was actually isolated.
        self.assertNotIn("rotate_left", block)

    def test_unresolvable_symbol_still_degrades_to_whole_file(self):
        """The pre-S1 behaviour, pinned deliberately.

        This is what EVERY C/C++ symbol target used to do. It is retained as the
        fallback for a genuinely unknown symbol, so the assertion is that the
        degradation still exists *and* is now reached only when the symbol truly
        is not there -- otherwise a future regression in naming would silently
        reinstate the old behaviour for real symbols while every other test in
        this class kept passing on the fallback text.
        """
        block = self._focus("src/widget.cpp::no_such_symbol")
        self.assertIn("Widget::compute", block)
        self.assertIn("Widget::reset", block)


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class ShellCloneLeakTest(unittest.TestCase):
    """S1 x scope: naming C/C++ units is what makes a shell leak POSSIBLE.

    ``build_index`` accumulates ``all_units`` only for rels outside ``ignored``,
    so the guarantee holds structurally -- but it holds one line above the clone
    passes and nothing pinned it for C/C++. Before S1 this test could not even
    have failed: every C unit was "<anonymous>", so no shell C unit could be
    attributed to a named cluster.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        os.environ.pop("DAEDALUS_IGNORE", None)

    def _seed(self, ext: str, body: str) -> None:
        _write(self.root, f"TCT_app/core.{ext}", body)
        _write(self.root, f"reference/vendor_a.{ext}", body)
        _write(self.root, f"reference/vendor_b.{ext}", body)

    def _all_clusters(self, idx) -> str:
        # ``duplication`` also carries ``near_excluded_languages`` (a list of
        # strings, not clusters); repr over the whole mapping is fine here and
        # deliberately catches a leak into ANY cluster kind, present or future.
        return json.dumps(idx["duplication"])

    def test_fixture_is_live_without_a_center(self):
        """A test that passes because the fixture is inert is worse than none.

        Three byte-identical C functions MUST cluster when nothing is shelled --
        and the cluster must be named, which is S1 working end-to-end through
        ``build_index`` (not just through ``extract_units``).
        """
        self._seed("c", C_BODY)
        cl = build_index(self.root)["duplication"]["unit_clusters"]
        self.assertEqual(len(cl), 1)
        self.assertEqual(cl[0]["count"], 3)
        self.assertEqual(cl[0]["name"], "checksum_block")
        self.assertEqual({s["name"] for s in cl[0]["sites"]}, {"checksum_block"})

    def test_c_shell_units_do_not_leak_into_clusters(self):
        self._seed("c", C_BODY)
        idx = build_index(self.root, center=["TCT_app"])
        self.assertEqual(sorted(idx["modules"]), ["TCT_app/core.c"])
        self.assertNotIn("reference/", self._all_clusters(idx))
        # the two shell copies are the only other sites, so nothing can cluster
        self.assertEqual(idx["duplication"]["unit_clusters"], [])

    def test_cpp_shell_units_do_not_leak_into_clusters(self):
        self._seed("cpp", CPP_BODY)
        wide = build_index(self.root)["duplication"]["unit_clusters"]
        self.assertEqual(wide[0]["name"], "Engine::tally")  # fixture is live
        idx = build_index(self.root, center=["TCT_app"])
        self.assertNotIn("reference/", self._all_clusters(idx))
        self.assertEqual(idx["duplication"]["unit_clusters"], [])

    def test_shell_c_file_is_not_counted_in_metrics(self):
        self._seed("c", C_BODY)
        idx = build_index(self.root, center=["TCT_app"])
        self.assertEqual(idx["n_files"], 1)
        self.assertEqual(idx["ignored"]["count"], 2)
        self.assertNotIn("reference/vendor_a.c", idx["modules"])

    def test_ambiguous_construct_is_not_fabricated_into_a_name(self):
        """The under-report guard, asserted where it matters.

        ``int (*get_handler(int))(void)`` nests a second function_declarator and
        is genuinely undecidable. The pre-S1 scan would have returned the return
        TYPE here; a fabricated name is worse than none because "<anonymous>" is
        filtered out of the Type-3 pool and an invented identifier is not.
        """
        amb = ("int (*get_handler(int k))(void) {\n"
               "    int acc = k;\n"
               "    acc += 1;\n"
               "    return 0;\n"
               "}\n")
        _write(self.root, "a.c", amb)
        _write(self.root, "b.c", amb)
        cl = build_index(self.root)["duplication"]["unit_clusters"]
        # Type-1 keys on the fingerprint, not the name, so these DO cluster --
        # under the honest name, never under "int" or a guess.
        self.assertEqual(cl[0]["name"], "<anonymous>")
        self.assertEqual({s["name"] for s in cl[0]["sites"]}, {"<anonymous>"})


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class NonPythonNeighborhoodScopeTest(unittest.TestCase):
    """S2 x scope: expansion is open to every language now, so the center
    boundary has to hold on the non-Python path too -- and hold SELECTIVELY.

    ``test_structcore_ignore`` covers the all-shell case (one edge, one stop).
    The case that separates a working boundary from a broken one is a target
    whose includes straddle it: one edge must expand, the other must stop, in
    the same call. A boundary that dropped everything would pass the all-shell
    test just as well.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        os.environ.pop("DAEDALUS_IGNORE", None)
        _write(self.root, "TCT_app/app.c",
               '#include "core.h"\n#include "vendor.h"\n\n'
               "int go(void) { return core_init() + vendor_call(); }\n")
        _write(self.root, "TCT_app/core.h", "int core_init(void);\n")
        _write(self.root, "reference/vendor.h", "int vendor_call(void);\n")
        self.idx = build_index(self.root, center=["TCT_app"])

    def test_both_edges_resolve_but_only_the_center_one_expands(self):
        # The trap stated as an assertion: import_edges is shell-INCLUSIVE, so
        # both targets are present there; only one is in ``modules``. Expansion
        # must read the second fact.
        self.assertEqual(self.idx["import_edges"]["TCT_app/app.c"],
                         ["TCT_app/core.h", "reference/vendor.h"])
        self.assertIn("TCT_app/core.h", self.idx["modules"])
        self.assertNotIn("reference/vendor.h", self.idx["modules"])

        res = semantic_slice(self.root, "TCT_app/app.c", idx=self.idx)
        deps = {i["file"] for i in res["included"] if i["role"] == "dependency"}
        self.assertEqual(deps, {"TCT_app/core.h"})
        self.assertNotIn("reference/vendor.h", res["slice_text"])
        self.assertEqual(res["shell_boundary_stops"], 1)

    def test_neighborhood_is_non_empty_for_a_non_python_target(self):
        """The S2 defect in one line: this used to be just the focus file."""
        res = semantic_slice(self.root, "TCT_app/app.c", idx=self.idx)
        self.assertGreater(res["n_included"], 1)

    def test_a_shell_file_is_never_an_expansion_target(self):
        """Both directions. The shell header has a real, resolved in-edge from a
        center file, so the reverse map genuinely offers it as a caller."""
        rev = self.idx.get("import_edges_reverse", {})
        self.assertEqual(rev.get("reference/vendor.h"), ["TCT_app/app.c"])
        for res in (semantic_slice(self.root, "TCT_app/app.c", idx=self.idx),
                    semantic_slice(self.root, "TCT_app/core.h", idx=self.idx)):
            for inc in res["included"]:
                self.assertFalse(inc["file"].startswith("reference/"),
                                 f"shell file expanded: {inc}")

    def test_python_neighborhood_is_unchanged_by_the_same_rules(self):
        """S2 rerouted the PYTHON path through import_edges too, so Python is
        not merely untouched -- it is a re-implementation that must agree. Same
        repo shape in Python: one center dep expanded, one shell dep stopped."""
        with TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "TCT_app/__init__.py", "")
            _write(root, "TCT_app/app.py",
                   "from TCT_app import core\nfrom reference import vendor\n\n\n"
                   "def go():\n    return core.core_init() + vendor.vendor_call()\n")
            _write(root, "TCT_app/core.py", "def core_init():\n    return 1\n")
            _write(root, "reference/__init__.py", "")
            _write(root, "reference/vendor.py", "def vendor_call():\n    return 2\n")

            idx = build_index(root, center=["TCT_app"])
            res = semantic_slice(root, "TCT_app/app.py", idx=idx)
            deps = {i["file"] for i in res["included"] if i["role"] == "dependency"}
            self.assertEqual(deps, {"TCT_app/core.py"})
            self.assertEqual(res["shell_boundary_stops"], 1)


@unittest.skipUnless(tree_sitter_available(), "tree-sitter not installed")
class IndexDeterminismTest(unittest.TestCase):
    """Determinism is load-bearing: the index must be byte-identical run to run.

    S1 put NAMES into cluster payloads for a language that previously had none,
    and S2 put a new reverse map on the expansion path. Both are new ways for
    set/dict iteration order to reach output.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        os.environ.pop("DAEDALUS_IGNORE", None)
        # Exact clones (C), renamed-only clones (C++ -> Type-2), and Python, so
        # more than one cluster kind and more than one language are pinned.
        for i in range(6):
            _write(self.root, f"src/m{i}.c", C_BODY)
            _write(self.root, f"src/u{i}.cpp",
                   "int Engine::tally%d(const int *p, int n) {\n"
                   "    int acc = 0;\n"
                   "    for (int i = 0; i < n; i++) {\n"
                   "        acc = (acc << 1) ^ p[i];\n"
                   "    }\n"
                   "    return acc;\n}\n" % i)
            _write(self.root, f"src/p{i}.py",
                   "def compute(a, b):\n    t = 0\n    for i in range(a):\n"
                   "        t += i * b\n    return t\n")

    def test_rebuild_is_identical(self):
        a = build_index(self.root)
        b = build_index(self.root)
        self.assertEqual(a["duplication"], b["duplication"])
        self.assertEqual(a["import_edges"], b["import_edges"])
        self.assertEqual(a["import_edges_reverse"], b["import_edges_reverse"])
        # not vacuous: there is real clustered content to be unstable about
        self.assertTrue(a["duplication"]["unit_clusters"])
        self.assertTrue(a["duplication"]["renamed_clusters"])

    def test_names_and_cluster_membership_stable_across_hashseed(self):
        """In-process rebuilds share one hash seed, so they cannot catch a set
        iteration reaching output. Separate interpreters with different seeds
        can."""
        prog = (
            "import json,sys\n"
            "from daedalus.structcore.index import build_index\n"
            "idx = build_index(sys.argv[1])\n"
            "out = {}\n"
            "for kind, cl in idx['duplication'].items():\n"
            "    if kind == 'near_excluded_languages':\n"
            "        out[kind] = cl\n"
            "        continue\n"
            "    out[kind] = [[c.get('name'), c.get('names'),\n"
            "                  [s['module'] for s in c.get('sites', [])],\n"
            "                  c.get('files')] for c in cl]\n"
            "print(json.dumps(out, sort_keys=True))\n"
        )
        seen = []
        for seed in ("0", "1", "12345", "99991"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            p = subprocess.run([sys.executable, "-c", prog, str(self.root)],
                               capture_output=True, text=True, env=env,
                               cwd=str(REPO_ROOT))
            self.assertEqual(p.returncode, 0, p.stderr)
            seen.append(json.loads(p.stdout.strip().splitlines()[-1]))

        self.assertTrue(seen[0]["unit_clusters"], "fixture produced no clusters")
        self.assertIn("checksum_block",
                      [c[0] for c in seen[0]["unit_clusters"]])
        for other in seen[1:]:
            self.assertEqual(seen[0], other,
                             "unit names / cluster membership vary with PYTHONHASHSEED")


if __name__ == "__main__":
    unittest.main()
