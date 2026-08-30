# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Movement I.5 / Move 3 — churn x complexity hotspots.

``git_churn`` degrades cleanly (no git / not a repo -> {}); when a repo IS
present, a frequently-changed file outranks an equally-complex but stable one in
the hotspot list (the CodeScene signal). The git-fixture test is skipped if git
is not on PATH; the graceful-degradation test always runs.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.churn import (
    co_change_pairs,
    git_churn,
    temporal_misses,
    _parse_numstat,
)


# An identically-complex function body (long + guarded) planted in two files, so
# base complexity is equal and CHURN is the only differentiator.
def _complex(tag: str) -> str:
    body = [f"def handler_{tag}(payload):", "    total = 0"]
    for i in range(60):
        body.append(f"    try:")
        body.append(f"        total = total + {i}")
        body.append(f"    except Exception:")
        body.append(f"        total = total - {i}")
    body.append("    return total")
    return "\n".join(body) + "\n"


GIT = shutil.which("git")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=Test", "-C", str(root), *args],
        check=True, capture_output=True,
    )


class NumstatParseTest(unittest.TestCase):
    def test_parses_and_sums_added_plus_deleted(self):
        out = "10\t2\tfoo.py\n5\t5\tfoo.py\n-\t-\timg.png\n"
        churn = _parse_numstat(out)
        self.assertEqual(churn["foo.py"], 10 + 2 + 5 + 5)
        self.assertEqual(churn.get("img.png"), 0)  # binary '-' counts as 0

    def test_rename_notation_follows_new_path(self):
        out = "3\t1\told.py => new.py\n2\t0\tpkg/{a => b}/mod.py\n"
        churn = _parse_numstat(out)
        self.assertEqual(churn.get("new.py"), 4)
        self.assertEqual(churn.get("pkg/b/mod.py"), 2)


class GracefulDegradeTest(unittest.TestCase):
    def test_non_git_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(git_churn(d), {})

    def test_hotspots_present_without_churn(self):
        # Non-git repo: hotspots still produced, churn field defaults to 0.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.py").write_text(_complex("x"), encoding="utf-8")
            idx = build_index(root)
            self.assertTrue(idx["hotspots"])
            self.assertEqual(idx["hotspots"][0]["churn"], 0)


@unittest.skipUnless(GIT, "git not on PATH")
class ChurnRankingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        # Both files start identical (equal base complexity).
        (self.root / "hot.py").write_text(_complex("hot"), encoding="utf-8")
        (self.root / "stable.py").write_text(_complex("stable"), encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "init")
        # Churn ONLY hot.py: many edits, then restore original (base stays equal).
        original = _complex("hot")
        for n in range(1, 16):
            (self.root / "hot.py").write_text(
                original.replace("total = 0", f"total = {n}"), encoding="utf-8")
            _git(self.root, "commit", "-qam", f"edit {n}")
        (self.root / "hot.py").write_text(original, encoding="utf-8")
        _git(self.root, "commit", "-qam", "restore")

    def tearDown(self):
        self._tmp.cleanup()

    def test_churn_map_ranks_hot_above_stable(self):
        churn = git_churn(self.root)
        self.assertGreater(churn.get("hot.py", 0), churn.get("stable.py", 0))

    def test_hotspot_score_reflects_churn(self):
        idx = build_index(self.root)
        rows = {h["module"]: h for h in idx["hotspots"]}
        self.assertIn("hot.py", rows)
        self.assertIn("stable.py", rows)
        self.assertGreater(rows["hot.py"]["churn"], rows["stable.py"]["churn"])
        # Equal base complexity, higher churn -> strictly higher hotspot score.
        self.assertGreater(rows["hot.py"]["score"], rows["stable.py"]["score"])
        order = [h["module"] for h in idx["hotspots"]]
        self.assertLess(order.index("hot.py"), order.index("stable.py"))


@unittest.skipUnless(GIT, "git not on PATH")
class CoChangePairsTest(unittest.TestCase):
    """Hand-built history: a.py/b.py always co-change and never import each
    other (true coupling, no static edge); a 7-file 'mega' commit is the ONLY
    place x.py/y.py ever co-occur (coincidental, must be capped out)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")

        names = ["a.py", "b.py", "c.py", "x.py", "y.py", "j1.py", "j2.py", "j3.py", "j4.py", "j5.py"]
        for n in names:
            (self.root / n).write_text("VALUE = 0\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "init")  # 10 files -> dropped at cap=5

        for i in range(1, 5):
            (self.root / "a.py").write_text(f"VALUE = {i}\n", encoding="utf-8")
            (self.root / "b.py").write_text(f"VALUE = {i}\n", encoding="utf-8")
            _git(self.root, "add", "-A")
            _git(self.root, "commit", "-q", "-m", f"a+b edit {i}")

        (self.root / "c.py").write_text("VALUE = 99\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c only")

        for n in ["x.py", "y.py", "j1.py", "j2.py", "j3.py", "j4.py", "j5.py"]:
            (self.root / n).write_text("VALUE = 7\n", encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "mega touch (7 files, over cap)")

    def tearDown(self):
        self._tmp.cleanup()

    def test_true_coupling_surfaces_with_positive_pmi(self):
        pairs = co_change_pairs(self.root, max_files_per_commit=5)
        row = next((p for p in pairs if {p["a"], p["b"]} == {"a.py", "b.py"}), None)
        self.assertIsNotNone(row)
        self.assertGreater(row["pmi"], 0)
        self.assertEqual(row["count"], 4)

    def test_mega_commit_pair_is_suppressed_by_cap(self):
        # x.py/y.py co-occur ONLY in the 7-file commit, which exceeds cap=5 and
        # is dropped whole -- proving the cap, not just min_count, is doing work.
        pairs = co_change_pairs(self.root, max_files_per_commit=5)
        self.assertFalse(any({p["a"], p["b"]} == {"x.py", "y.py"} for p in pairs))

    def test_git_churn_contract_unchanged_alongside_cochange(self):
        # git_churn's shape and non-degraded behavior must be untouched by the
        # new co_change_pairs code path living in the same module.
        churn = git_churn(self.root)
        self.assertIsInstance(churn, dict)
        self.assertGreater(churn.get("a.py", 0), 0)
        for v in churn.values():
            self.assertIsInstance(v, int)

    def test_temporal_misses_reports_both_axes_for_real_pairs(self):
        idx = build_index(self.root)
        pairs = co_change_pairs(self.root, max_files_per_commit=5)
        misses = temporal_misses(idx, pairs)
        row = next((m for m in misses if {m["a"], m["b"]} == {"a.py", "b.py"}), None)
        self.assertIsNotNone(row)
        self.assertIn("recall_axis", row)
        self.assertGreater(row["recall_axis"]["pmi"], 0)
        self.assertIn("compression_cost_loc", row)
        self.assertGreaterEqual(row["compression_cost_loc"], 0)


class TemporalMissesExclusionTest(unittest.TestCase):
    """Pure-function checks on temporal_misses against hand-built idx/pairs --
    no git involved, isolates the graph-exclusion + two-axis reporting logic."""

    def test_pair_with_static_edge_is_excluded(self):
        idx = {"import_edges": {"d.py": ["e.py"]}, "modules": {"d.py": {"loc": 10}, "e.py": {"loc": 20}}}
        pairs = [{"a": "d.py", "b": "e.py", "count": 5, "count_a": 5, "count_b": 5,
                 "commits_considered": 5, "pmi": 1.5, "lift": 4.0}]
        self.assertEqual(temporal_misses(idx, pairs), [])

    def test_pair_with_no_static_edge_reports_both_axes(self):
        idx = {"import_edges": {}, "modules": {"p.py": {"loc": 10}, "q.py": {"loc": 20}}}
        pairs = [{"a": "p.py", "b": "q.py", "count": 3, "count_a": 3, "count_b": 3,
                 "commits_considered": 5, "pmi": 0.9, "lift": 2.5}]
        out = temporal_misses(idx, pairs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["compression_cost_loc"], 30)
        self.assertEqual(out[0]["recall_axis"], {"pmi": 0.9, "lift": 2.5, "count": 3})

    def test_reverse_direction_edge_also_excludes(self):
        # The static edge can point either way; a co-change pair is "known to
        # the graph" if EITHER direction has an import edge.
        idx = {"import_edges": {"e.py": ["d.py"]}, "modules": {}}
        pairs = [{"a": "d.py", "b": "e.py", "count": 5, "count_a": 5, "count_b": 5,
                 "commits_considered": 5, "pmi": 1.5, "lift": 4.0}]
        self.assertEqual(temporal_misses(idx, pairs), [])


if __name__ == "__main__":
    unittest.main()
