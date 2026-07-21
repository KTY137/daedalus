"""Lane A2 close-out: the temporal co-change CEILING check (eval/ceiling.py).

The load-bearing tests are the two controls:

  * POSITIVE control -- a fixture where the missed label's defining file DID
    co-change with the focus before the mint commit. The clean ceiling MUST
    count it REACHABLE: a checker that always reports zero (the exact bug
    class that would silently rubber-stamp the lane-A2 close forever) fails
    here.
  * ARTIFACT control -- the pair co-changes enough times ONLY when the mint
    commit itself is counted. Clean arm must say UNREACHABLE while the leaky
    arm says REACHABLE: the self-prediction leak, demonstrated, which is the
    entire reason the ceiling is measured backtest-clean.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from daedalus.eval.ceiling import (
    _classify,
    render_ceiling,
    temporal_ceiling,
)
from daedalus.structcore.churn import co_change_pairs

GIT = shutil.which("git")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=Test", "-C", str(root), *args],
        check=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# impl.py defines the label symbol; consumer.py (the focus) never imports it,
# so the slice is focus-only and the label is a genuine miss. The symbol name
# is deliberately distinctive: harness._recall is substring-based, so nothing
# else in the fixture may contain it.
_IMPL = "def impl_only_marker_fn(x):\n    return x + 41\n"
_CONSUMER = "def consumer_fn(y):\n    return y * 2\n"


def _task(root: Path, sha: str | None) -> dict:
    t = {
        "id": "fixture-mint-1",
        "label_provenance": "independent_diff",
        "tier": "quarantine",
        "repo": str(root),
        "target": "consumer.py",
        "must_include": ["impl_only_marker_fn"],
    }
    if sha:
        t["minted_at_sha"] = sha
    return t


@unittest.skipUnless(GIT, "git not on PATH")
class CleanReachableTest(unittest.TestCase):
    """POSITIVE control: impl.py + consumer.py co-change TWICE before the mint
    commit -> the clean arm (min_count=2) must classify the miss REACHABLE."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "impl.py", _IMPL)
        _write(self.root, "consumer.py", _CONSUMER)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c1: both created")
        _write(self.root, "impl.py", _IMPL + "# tweak\n")
        _write(self.root, "consumer.py", _CONSUMER + "# tweak\n")
        _git(self.root, "commit", "-qam", "c2: both touched again")
        _write(self.root, "impl.py", _IMPL + "# tweak\n# mint\n")
        _write(self.root, "consumer.py", _CONSUMER + "# tweak\n# mint\n")
        _git(self.root, "commit", "-qam", "c3: the mint commit")
        self.mint_sha = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_prior_coupling_is_reachable_on_the_clean_arm(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=2)
        self.assertEqual(res["n_miss_tasks"], 1)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "REACHABLE")
        self.assertGreater(res["ceiling_clean"], 0.0)
        self.assertTrue(res["reopen_temporal_lane"])

    def test_backtest_rev_is_the_mint_parent(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["backtest_rev"], self.mint_sha + "^")
        self.assertIsNone(row["backtest_rev_reason"])
        self.assertFalse(row["merge_commit"])

    def test_unknown_symbol_is_no_inscope_def(self):
        task = _task(self.root, self.mint_sha)
        task["must_include"] = ["impl_only_marker_fn", "no_such_symbol_xyz"]
        res = temporal_ceiling([task], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["no_such_symbol_xyz"], "NO_INSCOPE_DEF")

    def test_reopen_render_names_the_signal(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=2)
        text = render_ceiling(res)
        text.encode("ascii")  # raw-Windows-console contract
        self.assertIn("REOPEN signal", text)
        self.assertIn("NOT slicer", text)  # never reported as recall


@unittest.skipUnless(GIT, "git not on PATH")
class LeakArtifactTest(unittest.TestCase):
    """ARTIFACT control: one prior co-commit + the mint commit. At min_count=2
    the pair exists ONLY when the mint commit is counted -- clean UNREACHABLE,
    leaky REACHABLE. The measured self-prediction leak, in miniature."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "impl.py", _IMPL)
        _write(self.root, "consumer.py", _CONSUMER)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c1: both created (the ONLY prior co-commit)")
        _write(self.root, "impl.py", _IMPL + "# solo\n")
        _git(self.root, "commit", "-qam", "c2: impl alone")
        _write(self.root, "impl.py", _IMPL + "# solo\n# mint\n")
        _write(self.root, "consumer.py", _CONSUMER + "# mint\n")
        _git(self.root, "commit", "-qam", "c3: the mint commit")
        self.mint_sha = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_leak_shows_only_on_the_leaky_arm(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "UNREACHABLE")
        self.assertEqual(row["classes_leaky"]["impl_only_marker_fn"], "REACHABLE")
        self.assertEqual(res["ceiling_clean"], 0.0)
        self.assertGreater(res["ceiling_leaky"], 0.0)
        self.assertFalse(res["reopen_temporal_lane"])
        text = render_ceiling(res)
        self.assertIn("reopen signal: none", text)

    def test_permissive_min_count_finds_the_single_prior_co_commit(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=1)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "REACHABLE")
        # A reopen "signal" measured below the threshold that defines the
        # reopen condition must carry the noise-floor qualifier.
        text = render_ceiling(res)
        self.assertIn("BELOW the reopen threshold", text)

    def test_task_without_sha_scores_leaky_only(self):
        res = temporal_ceiling([_task(self.root, None)], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "NO_BACKTEST_REV")
        self.assertEqual(row["backtest_rev_reason"], "no minted_at_sha")
        self.assertEqual(row["classes_leaky"]["impl_only_marker_fn"], "REACHABLE")
        # NO_BACKTEST_REV labels leave the clean denominator entirely.
        self.assertEqual(res["ceiling_clean"], 0.0)
        self.assertFalse(res["reopen_temporal_lane"])

    def test_unresolvable_sha_is_reported_not_crashed(self):
        res = temporal_ceiling([_task(self.root, "0" * 40)], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "NO_BACKTEST_REV")
        self.assertEqual(row["backtest_rev_reason"], "sha unresolvable or root commit")


class ClassifyUnitTest(unittest.TestCase):
    """The STATIC_EDGE branch can only arise from a slicer defect (a missed
    label whose defining file is already a static neighbour), which no honest
    integration fixture should produce -- so the branch is pinned here."""

    @staticmethod
    def _counts(mapping):
        return lambda rel: mapping.get(rel, 0)

    def test_static_edge_outranks_temporal(self):
        classes = _classify(
            ["sym"], "focus.py", self._counts({"dep.py": 5}), 2,
            sym_defs={"sym": {"dep.py"}}, modules={"focus.py": {}, "dep.py": {}},
            edges={"focus.py": ["dep.py"]}, rev_edges={},
        )
        self.assertEqual(classes["sym"], "STATIC_EDGE")

    def test_decision_order_no_def_beats_everything(self):
        classes = _classify(
            ["sym"], "focus.py", self._counts({"dep.py": 5}), 2,
            sym_defs={}, modules={"focus.py": {}, "dep.py": {}},
            edges={"focus.py": ["dep.py"]}, rev_edges={},
        )
        self.assertEqual(classes["sym"], "NO_INSCOPE_DEF")

    def test_out_of_scope_def_does_not_count(self):
        # Defined only in a SHELL file -> not an in-scope def at all.
        classes = _classify(
            ["sym"], "focus.py", self._counts({"vendor/dep.py": 5}), 2,
            sym_defs={"sym": {"vendor/dep.py"}}, modules={"focus.py": {}},
            edges={}, rev_edges={},
        )
        self.assertEqual(classes["sym"], "NO_INSCOPE_DEF")

    def test_count_below_min_count_is_unreachable(self):
        classes = _classify(
            ["sym"], "focus.py", self._counts({"dep.py": 1}), 2,
            sym_defs={"sym": {"dep.py"}}, modules={"focus.py": {}, "dep.py": {}},
            edges={}, rev_edges={},
        )
        self.assertEqual(classes["sym"], "UNREACHABLE")


@unittest.skipUnless(GIT, "git not on PATH")
class RenameBoundaryTest(unittest.TestCase):
    """The Nemesis catch, pinned: coupling split across a rename boundary.
    impl.py co-changes once with legacy.py (c1) and once with its renamed
    successor consumer.py (c2) -- one real coupling, two spellings, count 1
    each. A rename-blind match dies at min_count=2; the alias-unified count
    (1 + 1 = 2) must classify it REACHABLE."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "impl.py", _IMPL)
        _write(self.root, "legacy.py", _CONSUMER)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c1: impl + legacy born together")
        _git(self.root, "mv", "legacy.py", "consumer.py")
        _write(self.root, "impl.py", _IMPL + "# tweak\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c2: rename legacy->consumer, touch impl")
        _write(self.root, "impl.py", _IMPL + "# tweak\n# mint\n")
        _write(self.root, "consumer.py", _CONSUMER + "# mint\n")
        _git(self.root, "commit", "-qam", "c3: the mint commit")
        self.mint_sha = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_coupling_across_the_rename_is_reachable(self):
        res = temporal_ceiling([_task(self.root, self.mint_sha)], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "REACHABLE")
        self.assertEqual(res["alias_probe_failures"], 0)


@unittest.skipUnless(GIT, "git not on PATH")
class MaterialityFloorTest(unittest.TestCase):
    """One genuinely recoverable label among eleven must NOT trip the reopen
    signal -- the exact posture of the 2026-07-21 close (1/43): a lone label
    is not grounds to rebuild a core-API tier."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "impl.py", _IMPL)
        _write(self.root, "consumer.py", _CONSUMER)
        far = "".join(f"def far_away_sym_{i}(x):\n    return x\n\n" for i in range(10))
        _write(self.root, "far.py", far)
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c1: all born together (co-change 1)")
        _write(self.root, "impl.py", _IMPL + "# tweak\n")
        _write(self.root, "consumer.py", _CONSUMER + "# tweak\n")
        _git(self.root, "commit", "-qam", "c2: impl+consumer again (co-change 2)")
        _write(self.root, "impl.py", _IMPL + "# tweak\n# mint\n")
        _write(self.root, "consumer.py", _CONSUMER + "# tweak\n# mint\n")
        _git(self.root, "commit", "-qam", "c3: the mint commit")
        self.mint_sha = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_one_label_of_eleven_stays_closed(self):
        task = _task(self.root, self.mint_sha)
        task["must_include"] = (["impl_only_marker_fn"]
                                + [f"far_away_sym_{i}" for i in range(10)])
        res = temporal_ceiling([task], min_count=2)
        row = res["per_task"][0]
        self.assertEqual(row["classes_clean"]["impl_only_marker_fn"], "REACHABLE")
        # far.py co-changed with consumer only at birth (count 1 < 2).
        self.assertEqual(row["classes_clean"]["far_away_sym_3"], "UNREACHABLE")
        self.assertEqual(res["summary_clean"]["REACHABLE"], 1)
        self.assertAlmostEqual(res["ceiling_clean"], 1 / 11)
        self.assertFalse(res["reopen_temporal_lane"])  # 9.1% < 10%, 1 task < 3
        text = render_ceiling(res)
        self.assertIn("below the materiality floor", text)
        self.assertIn("impl_only_marker_fn", text)  # audit list names the label


@unittest.skipUnless(GIT, "git not on PATH")
class CoChangeRevParamTest(unittest.TestCase):
    """co_change_pairs(rev=...) -- the backtest cut the ceiling stands on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "a.py", "VALUE = 0\n")
        _write(self.root, "b.py", "VALUE = 0\n")
        _git(self.root, "init", "-q")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "c1")
        for i in (1, 2, 3):
            _write(self.root, "a.py", f"VALUE = {i}\n")
            _write(self.root, "b.py", f"VALUE = {i}\n")
            _git(self.root, "commit", "-qam", f"c{i + 1}: a+b")
        self.mid_sha = _git(self.root, "rev-parse", "HEAD~2").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_rev_narrows_history(self):
        full = co_change_pairs(self.root)
        cut = co_change_pairs(self.root, rev=self.mid_sha)
        pair_full = next(p for p in full if {p["a"], p["b"]} == {"a.py", "b.py"})
        pair_cut = next(p for p in cut if {p["a"], p["b"]} == {"a.py", "b.py"})
        self.assertEqual(pair_full["count"], 4)  # c1 creation + 3 co-edits
        self.assertEqual(pair_cut["count"], 2)   # c1 + first co-edit only
        self.assertLess(pair_cut["commits_considered"],
                        pair_full["commits_considered"])

    def test_unresolvable_rev_degrades_to_empty(self):
        self.assertEqual(co_change_pairs(self.root, rev="no-such-ref"), [])


if __name__ == "__main__":
    unittest.main()
