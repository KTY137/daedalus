# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tests for .daedalusignore -- per-repo structural ignore rules."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.ignore import (
    IGNORE_FILENAME, effective_rules, load_ignore_rules,
)
from daedalus.structcore.index import build_index, cached_index


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class IgnorePatternTests(unittest.TestCase):
    """Pattern semantics, exercised without touching the indexer."""

    def _rules(self, body: str):
        self.tmp = getattr(self, "tmp", None) or TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / IGNORE_FILENAME).write_text(body, encoding="utf-8")
        return load_ignore_rules(root)

    def test_missing_file_is_empty_and_matches_nothing(self):
        with TemporaryDirectory() as td:
            r = load_ignore_rules(Path(td))
            self.assertFalse(r)
            self.assertFalse(r.matches("anything/at/all.py"))
            self.assertEqual(r.fingerprint, "")

    def test_directory_rule_covers_descendants(self):
        r = self._rules("reference/\n")
        self.assertTrue(r.matches("reference/foo.py"))
        self.assertTrue(r.matches("reference/deep/nested/bar.py"))
        self.assertFalse(r.matches("src/foo.py"))

    def test_directory_rule_does_not_match_a_file_of_that_name(self):
        # 'build/' is a directory rule; a FILE named 'build' is not a directory.
        r = self._rules("build/\n")
        self.assertTrue(r.matches("build/out.py"))
        self.assertFalse(r.matches("build"))
        self.assertFalse(r.matches("scripts/build"))

    def test_unanchored_name_matches_at_any_depth(self):
        r = self._rules("vendor/\n")
        self.assertTrue(r.matches("a/b/vendor/x.py"))
        self.assertTrue(r.matches("vendor/x.py"))

    def test_slash_pattern_is_root_anchored(self):
        r = self._rules("docs/vendor/\n")
        self.assertTrue(r.matches("docs/vendor/x.py"))
        # same trailing name, different location -> NOT matched
        self.assertFalse(r.matches("src/docs/vendor/x.py"))

    def test_glob_extension(self):
        r = self._rules("*.generated.py\n")
        self.assertTrue(r.matches("a/b/thing.generated.py"))
        self.assertFalse(r.matches("a/b/thing.py"))

    def test_comments_and_blank_lines_ignored(self):
        r = self._rules("# a comment\n\n   \nreference/\n")
        self.assertEqual(len(r.rules), 1)
        self.assertTrue(r.matches("reference/x.py"))

    def test_negation_carves_an_exception_last_match_wins(self):
        r = self._rules("reference/\n!reference/keepme.py\n")
        self.assertTrue(r.matches("reference/other.py"))
        self.assertFalse(r.matches("reference/keepme.py"))

    def test_fingerprint_changes_with_content(self):
        a = self._rules("reference/\n")
        b = self._rules("reference/\nvendor/\n")
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_env_patterns_extend_the_file(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")
            os.environ["DAEDALUS_IGNORE"] = "scratch/"
            self.addCleanup(os.environ.pop, "DAEDALUS_IGNORE", None)
            r = effective_rules(root)
            self.assertTrue(r.matches("reference/x.py"))
            self.assertTrue(r.matches("scratch/y.py"))


class IgnoreIndexTests(unittest.TestCase):
    """The load-bearing part: metrics withheld, import edges kept."""

    def setUp(self):
        self.td = TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        os.environ.pop("DAEDALUS_IGNORE", None)

    def test_ignored_files_are_excluded_from_modules_and_counted(self):
        _write(self.root, "app.py", "import os\n")
        _write(self.root, "reference/vendored.py", "import sys\n")
        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")

        idx = build_index(self.root)
        self.assertIn("app.py", idx["modules"])
        self.assertNotIn("reference/vendored.py", idx["modules"])
        self.assertEqual(idx["ignored"]["count"], 1)
        self.assertEqual(idx["n_files"], 1)
        self.assertEqual(idx["ignored"]["n_files_scanned"], 2)
        self.assertIn("reference/", idx["ignored"]["ignore_patterns"])

    def test_no_ignore_file_leaves_everything_indexed(self):
        _write(self.root, "app.py")
        _write(self.root, "reference/vendored.py")
        idx = build_index(self.root)
        self.assertIn("reference/vendored.py", idx["modules"])
        self.assertEqual(idx["ignored"]["count"], 0)

    def test_import_INTO_ignored_tree_still_resolves(self):
        """The whole point of 'excluded from metrics, kept for imports'."""
        _write(self.root, "app.py", "from reference import vendored\n")
        _write(self.root, "reference/__init__.py", "")
        _write(self.root, "reference/vendored.py", "VALUE = 1\n")
        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")

        idx = build_index(self.root)
        self.assertNotIn("reference/vendored.py", idx["modules"])
        edges = idx["import_edges"].get("app.py", [])
        self.assertTrue(
            any(e.startswith("reference/") for e in edges),
            f"edge into ignored tree was dropped; got {edges}",
        )

    def test_ignored_files_do_not_form_clone_clusters(self):
        body = "def alpha():\n    total = 0\n    for i in range(10):\n        total += i * 3\n    return total\n"
        _write(self.root, "reference/a.py", body)
        _write(self.root, "reference/b.py", body)
        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")

        idx = build_index(self.root)
        for kind, clusters in idx["duplication"].items():
            for c in clusters:
                blob = repr(c)
                self.assertNotIn("reference/", blob,
                                 f"ignored file leaked into {kind}")

    def test_hotspots_exclude_ignored_files(self):
        _write(self.root, "app.py", "x = 1\n")
        _write(self.root, "reference/big.py", "def f():\n" + "    y = 1\n" * 200)
        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")
        idx = build_index(self.root)
        names = {h.get("module") or h.get("path") for h in idx["module_heat"]}
        self.assertNotIn("reference/big.py", names)

    def test_cache_key_tracks_ignore_file_edits(self):
        """Editing .daedalusignore must not return the previously cached index."""
        _write(self.root, "app.py")
        _write(self.root, "reference/vendored.py")

        first = cached_index(self.root)
        self.assertIn("reference/vendored.py", first["modules"])

        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")
        second = cached_index(self.root)
        self.assertNotIn("reference/vendored.py", second["modules"],
                         "stale index returned after .daedalusignore was added")

    def test_center_makes_everything_outside_it_shell(self):
        """Declare what the project IS; the rest of the repo is periphery."""
        _write(self.root, "TCT_app/main.py", "x = 1\n")
        _write(self.root, "reference/vendored.py", "y = 2\n")
        _write(self.root, "scratch/notes.py", "z = 3\n")

        idx = build_index(self.root, center=["TCT_app"])
        self.assertIn("TCT_app/main.py", idx["modules"])
        self.assertNotIn("reference/vendored.py", idx["modules"])
        self.assertNotIn("scratch/notes.py", idx["modules"])
        self.assertEqual(idx["ignored"]["count"], 2)
        self.assertEqual(idx["ignored"]["center"], ["TCT_app"])

    def test_center_import_INTO_shell_still_resolves(self):
        _write(self.root, "TCT_app/main.py", "from reference import vendored\n")
        _write(self.root, "reference/__init__.py", "")
        _write(self.root, "reference/vendored.py", "VALUE = 1\n")

        idx = build_index(self.root, center=["TCT_app"])
        edges = idx["import_edges"].get("TCT_app/main.py", [])
        self.assertTrue(any(e.startswith("reference/") for e in edges),
                        f"edge into shell was dropped; got {edges}")

    def test_center_and_ignore_compose(self):
        """center says which tree is yours; ignore carves within it."""
        _write(self.root, "TCT_app/main.py")
        _write(self.root, "TCT_app/generated_stub.py")
        _write(self.root, "reference/vendored.py")
        (self.root / IGNORE_FILENAME).write_text("*generated*\n", encoding="utf-8")

        idx = build_index(self.root, center=["TCT_app"])
        self.assertIn("TCT_app/main.py", idx["modules"])
        self.assertNotIn("TCT_app/generated_stub.py", idx["modules"])
        self.assertNotIn("reference/vendored.py", idx["modules"])

    def test_multiple_center_roots(self):
        _write(self.root, "app/a.py")
        _write(self.root, "lib/b.py")
        _write(self.root, "reference/c.py")
        idx = build_index(self.root, center=["app", "lib"])
        self.assertIn("app/a.py", idx["modules"])
        self.assertIn("lib/b.py", idx["modules"])
        self.assertNotIn("reference/c.py", idx["modules"])

    def test_empty_center_is_whole_repo(self):
        """The un-configured default must not change behaviour."""
        _write(self.root, "a.py")
        _write(self.root, "reference/b.py")
        idx = build_index(self.root, center=[])
        self.assertIn("a.py", idx["modules"])
        self.assertIn("reference/b.py", idx["modules"])
        self.assertEqual(idx["ignored"]["count"], 0)

    def test_center_prefix_is_path_segment_not_substring(self):
        """'app' must not swallow 'apparel/'."""
        _write(self.root, "app/a.py")
        _write(self.root, "apparel/b.py")
        idx = build_index(self.root, center=["app"])
        self.assertIn("app/a.py", idx["modules"])
        self.assertNotIn("apparel/b.py", idx["modules"])

    def test_cache_key_tracks_center_change(self):
        _write(self.root, "app/a.py")
        _write(self.root, "reference/b.py")
        wide = cached_index(self.root)
        self.assertIn("reference/b.py", wide["modules"])
        narrow = cached_index(self.root, center=["app"])
        self.assertNotIn("reference/b.py", narrow["modules"],
                         "stale index returned after center changed")

    def test_slice_does_not_fan_out_into_shell(self):
        """The fan-out the center is meant to stop."""
        from daedalus.structcore.slice import semantic_slice

        _write(self.root, "TCT_app/main.py", "from reference import vendored\n\ndef go():\n    return 1\n")
        _write(self.root, "reference/__init__.py", "")
        _write(self.root, "reference/vendored.py", "def helper():\n    return 2\n")

        idx = build_index(self.root, center=["TCT_app"])
        sl = semantic_slice(self.root, "TCT_app/main.py", idx=idx)
        files = {inc["file"] for inc in sl["included"]}
        self.assertNotIn("reference/vendored.py", files,
                         "slice expanded through the shell boundary")
        # The drop is now REPORTED, not accidental. Before S2 the boundary held
        # only as a side effect of the lookup being built from ``modules``;
        # routing expansion through the (shell-inclusive) import_edges makes it
        # a deliberate test, so it has to say when it fired.
        self.assertEqual(sl["shell_boundary_stops"], 1)

    def test_slice_does_not_fan_out_into_shell_non_python(self):
        """Same boundary, C target. S2 opened neighborhood expansion to every
        language; the shell test must hold there too, not just for Python."""
        from daedalus.structcore.slice import semantic_slice

        _write(self.root, "TCT_app/app.c", '#include "lib.h"\n\nint go(void) { return 1; }\n')
        _write(self.root, "reference/lib.h", "int lib_call(int x);\n")

        idx = build_index(self.root, center=["TCT_app"])
        # The trap, stated as an assertion: the edge IS retained in import_edges
        # (resolution runs outside the metric guard) while the target is NOT in
        # modules. Expansion must read the second fact, not the first.
        self.assertEqual(idx["import_edges"]["TCT_app/app.c"], ["reference/lib.h"])
        self.assertNotIn("reference/lib.h", idx["modules"])

        sl = semantic_slice(self.root, "TCT_app/app.c", idx=idx)
        files = {inc["file"] for inc in sl["included"]}
        self.assertNotIn("reference/lib.h", files,
                         "C slice expanded through the shell boundary")
        self.assertEqual(sl["shell_boundary_stops"], 1)

    def test_tests_preset_excludes_test_files_from_metrics(self):
        """'ignore tests for our struc map' -- tests are code, but not targets."""
        _write(self.root, "TCT_app/gui/style.py", "x = 1\n")
        _write(self.root, "TCT_app/tests/test_planner_panel.py", "def test_a():\n    pass\n")
        _write(self.root, "TCT_app/tests/conftest.py", "import pytest\n")
        _write(self.root, "TCT_app/analysis/laser_test.py", "y = 2\n")

        idx = build_index(self.root, center=["TCT_app"], ignore=["@tests"])
        self.assertIn("TCT_app/gui/style.py", idx["modules"])
        self.assertNotIn("TCT_app/tests/test_planner_panel.py", idx["modules"])
        self.assertNotIn("TCT_app/tests/conftest.py", idx["modules"])
        # '*_test.py' must match, and it is a real source file otherwise
        self.assertNotIn("TCT_app/analysis/laser_test.py", idx["modules"])

    def test_tests_preset_does_not_hide_non_test_code(self):
        """A preset that over-matches would silently delete real signal."""
        _write(self.root, "app/testing_utils.py", "x = 1\n")   # not a test file
        _write(self.root, "app/latest.py", "y = 2\n")          # contains 'test'
        _write(self.root, "app/contest.py", "z = 3\n")
        idx = build_index(self.root, ignore=["@tests"])
        for keep in ("app/testing_utils.py", "app/latest.py", "app/contest.py"):
            self.assertIn(keep, idx["modules"], f"{keep} was wrongly ignored")

    def test_unknown_preset_passes_through_not_silently_dropped(self):
        from daedalus.structcore.ignore import expand_presets
        self.assertEqual(expand_presets(["@nope"]), ["@nope"])
        self.assertIn("tests/", expand_presets(["@tests"]))

    def test_project_config_ignore_reaches_the_index(self):
        """The web path: projects/<name>.json 'ignore' must actually apply."""
        from daedalus import web_api

        _write(self.root, "app/main.py")
        _write(self.root, "app/tests/test_x.py")
        idx = build_index(self.root, ignore=web_api._project_ignore(None) or ["@tests"])
        self.assertIn("app/main.py", idx["modules"])
        self.assertNotIn("app/tests/test_x.py", idx["modules"])

    def test_cache_key_tracks_ignore_argument_change(self):
        _write(self.root, "app/main.py")
        _write(self.root, "app/tests/test_x.py")
        wide = cached_index(self.root)
        self.assertIn("app/tests/test_x.py", wide["modules"])
        narrow = cached_index(self.root, ignore=["@tests"])
        self.assertNotIn("app/tests/test_x.py", narrow["modules"],
                         "stale index returned after ignore patterns changed")

    def test_determinism_ignored_set_is_stable(self):
        for i in range(6):
            _write(self.root, f"reference/m{i}.py", f"v = {i}\n")
        _write(self.root, "app.py")
        (self.root / IGNORE_FILENAME).write_text("reference/\n", encoding="utf-8")
        a = build_index(self.root)["ignored"]
        b = build_index(self.root)["ignored"]
        self.assertEqual(a["sample"], b["sample"])
        self.assertEqual(a["count"], b["count"])


if __name__ == "__main__":
    unittest.main()
