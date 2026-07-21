"""test_eval_mint.py -- independent-oracle task minting (daedalus.eval.mint).

Every assertion here ultimately serves the ANTI-CIRCULARITY guarantee the
module exists for: ``must_include`` must be exactly what a diff literally
touched in files OTHER than the target, never expanded through the
callee/import graph and never drawn from the target file itself (the slice
emits its focus file in full, so a same-file label is recalled by
construction -- see mint.py's module docstring, CROSS-FILE ONLY).
``test_must_include_excludes_untouched_callee`` is written so it would go RED
the moment someone "helpfully" adds a graph.callees expansion to mint.py --
that is the failure mode this whole track exists to prevent.

Fixtures below always touch at least two in-scope files when a task is
expected to mint: a single-file commit/edit has no cross-file label source
and must mint nothing (see MintNothingReasonsTest / the *_mints_nothing
tests throughout) -- that is a REQUIRED outcome, not a gap in coverage.

Offline only: all git history is built in temp repos via subprocess, exactly
like tests/test_churn.py's house style. No network, no real Claude/Ollama
call, no real device path. The scope tests rely on ``daedalus.structcore``'s
real (in-process) indexer against these tiny temp repos -- no mocking of
``cached_index`` is needed or wanted, since the whole point is proving mint.py
consults the SAME scope boundary the slicer does.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus.eval.mint import (
    MINT_CONFIRM_THRESHOLD,
    MUST_INCLUDE_CAP,
    _mint_from_diffs,
    add_minted_task,
    confirm_minted_task,
    confirm_task,
    load_minted_tasks,
    mint_from_commit,
    mint_task_from_landed_edit,
    save_minted_tasks,
)

GIT = shutil.which("git")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=Test", "-C", str(root), *args],
        check=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    return proc.stdout


# mod.py: target_func CALLS helper. Only target_func's body differs between
# v1 and v2 -- helper is byte-identical -- so a correct mint must never name
# helper, even though a graph walk from target_func would reach it in one hop
# (the anti-circularity case), AND must never name it simply because it is
# unreachable in the same file as the target (the cross-file case).
_MOD_V1 = (
    "def helper(x):\n"
    "    return x + 1\n"
    "\n"
    "def target_func(x):\n"
    "    return helper(x) * 2\n"
)

_MOD_V2 = (
    "def helper(x):\n"
    "    return x + 1\n"
    "\n"
    "def target_func(x):\n"
    "    return helper(x) * 3 + 1\n"
)

# other.py: a second in-scope file, changed in the SAME commit/edit as mod.py
# in most fixtures below -- the cross-file label source. Its own symbol
# (other_func) must be the thing that ends up in must_include, never
# target_func/helper.
_OTHER_V1 = "def other_func(y):\n    return y - 1\n"
_OTHER_V2 = "def other_func(y):\n    return y - 1 if y else 0\n"


@unittest.skipUnless(GIT, "git not on PATH")
class MintFromCommitTest(unittest.TestCase):
    """mod.py + other.py both change in v2 -- a genuine cross-file commit."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        (self.root / "mod.py").write_text(_MOD_V1, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V1, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        self.sha1 = _git(self.root, "rev-parse", "HEAD").strip()
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V2, encoding="utf-8")
        _git(self.root, "commit", "-qam", "v2: reweight target_func and other_func")
        self.sha2 = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_must_include_is_the_cross_file_symbol_only(self):
        # mod.py and other.py each changed exactly one symbol -> tie on count,
        # broken by path ("mod.py" < "other.py"): mod.py is the target, so
        # must_include can only ever come from other.py.
        tasks = mint_from_commit(str(self.root), self.sha2)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["must_include"], ["other_func"])

    def test_must_include_excludes_same_file_and_untouched_callee(self):
        tasks = mint_from_commit(str(self.root), self.sha2)
        must_include = tasks[0]["must_include"]
        self.assertNotIn("target_func", must_include)  # same file as target
        self.assertNotIn("helper", must_include)       # same file AND untouched

    def test_single_symbol_target_gets_symbol_scoped_target(self):
        tasks = mint_from_commit(str(self.root), self.sha2)
        self.assertEqual(tasks[0]["target"], "mod.py::target_func")

    def test_provenance_tier_sha_repo_and_new_fields(self):
        task = mint_from_commit(str(self.root), self.sha2)[0]
        self.assertEqual(task["label_provenance"], "independent_diff")
        self.assertEqual(task["tier"], "quarantine")
        self.assertEqual(task["confirmations"], 0)
        self.assertEqual(task["minted_at_sha"], self.sha2)
        self.assertTrue(Path(task["repo"]).exists())
        self.assertEqual(task["must_include_dropped"], 0)
        self.assertEqual(task["skipped_out_of_scope"], [])

    def test_root_commit_has_no_parent_and_stays_cross_file_only(self):
        # v1 itself is the root commit and already adds BOTH files: mod.py
        # gets 2 added symbols (helper, target_func), other.py gets 1
        # (other_func) -> mod.py anchors on symbol COUNT, so other_func is
        # the only valid label even though every symbol here is "added".
        tasks = mint_from_commit(str(self.root), self.sha1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["must_include"], ["other_func"])
        self.assertNotIn("helper", tasks[0]["must_include"])
        self.assertNotIn("target_func", tasks[0]["must_include"])
        self.assertEqual(tasks[0]["target"], "mod.py")  # 2 own symbols -> file-level

    def test_unknown_sha_mints_nothing(self):
        self.assertEqual(mint_from_commit(str(self.root), "deadbeef" * 5), [])

    def test_unresolvable_repo_mints_nothing(self):
        with tempfile.TemporaryDirectory() as not_a_repo:
            self.assertEqual(mint_from_commit(not_a_repo, self.sha2), [])

    def test_single_file_commit_mints_nothing(self):
        # A follow-up commit touching ONLY mod.py has no cross-file label
        # source at all, regardless of how many symbols changed inside it.
        (self.root / "mod.py").write_text(
            _MOD_V2.replace("* 3 + 1", "* 5 + 2"), encoding="utf-8")
        _git(self.root, "commit", "-qam", "v3: mod.py only")
        sha3 = _git(self.root, "rev-parse", "HEAD").strip()
        self.assertEqual(mint_from_commit(str(self.root), sha3), [])

    def test_out_of_scope_dist_file_is_skipped_not_target_or_label(self):
        # dist/ is a hard-excluded dir for the indexer (structcore/index.py
        # _IGNORE_DIRS) -- exactly the minified-build-artifact class this
        # scope check exists to keep out of both target and must_include.
        (self.root / "dist").mkdir()
        (self.root / "dist" / "bundle.js").write_text("var x=1;", encoding="utf-8")
        (self.root / "mod.py").write_text(
            _MOD_V2.replace("* 3 + 1", "* 9"), encoding="utf-8")
        (self.root / "other.py").write_text(
            _OTHER_V2.replace("y - 1 if y", "y - 2 if y"), encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qam", "v3: touches dist/ too")
        sha3 = _git(self.root, "rev-parse", "HEAD").strip()

        tasks = mint_from_commit(str(self.root), sha3)
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["skipped_out_of_scope"], ["dist/bundle.js"])
        self.assertNotIn("dist/bundle.js", task["target"])
        self.assertFalse(any("dist" in m for m in task["must_include"]))


@unittest.skipUnless(GIT, "git not on PATH")
class MintFromLandedEditTest(unittest.TestCase):
    """Simulates the offload.py seam directly: report["wrote"] plays the role
    of disk_changed (offload.py:194-197), and the edit is left UNCOMMITTED on
    disk -- exactly what offload() does; it never commits."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        (self.root / "mod.py").write_text(_MOD_V1, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V1, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_uncommitted_worktree_edit_is_diffed_against_head(self):
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V2, encoding="utf-8")
        report = {"wrote": ["mod.py", "other.py"]}
        task = mint_task_from_landed_edit(report, str(self.root))
        self.assertIsNotNone(task)
        self.assertEqual(task["must_include"], ["other_func"])
        self.assertEqual(task["label_provenance"], "independent_diff")
        self.assertEqual(task["tier"], "quarantine")
        self.assertEqual(task["target"], "mod.py::target_func")

    def test_new_file_mixed_with_edit_counts_as_cross_file_add(self):
        # mod.py gets a real edit (1 symbol); new_mod.py is a brand-new file
        # (1 symbol, wholly "added") -- tie on count, path sort picks mod.py
        # as target, so the new file's symbol is what lands in must_include.
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        (self.root / "new_mod.py").write_text("def brand_new():\n    return 1\n", encoding="utf-8")
        report = {"wrote": ["mod.py", "new_mod.py"]}
        task = mint_task_from_landed_edit(report, str(self.root))
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "mod.py::target_func")
        self.assertEqual(task["must_include"], ["brand_new"])

    def test_single_new_file_alone_mints_nothing(self):
        # Only one file written -> no cross-file label source, regardless of
        # how many symbols the new file itself defines.
        (self.root / "new_mod.py").write_text("def brand_new():\n    return 1\n", encoding="utf-8")
        report = {"wrote": ["new_mod.py"]}
        self.assertIsNone(mint_task_from_landed_edit(report, str(self.root)))

    def test_no_writes_mints_nothing(self):
        self.assertIsNone(mint_task_from_landed_edit({"wrote": []}, str(self.root)))
        self.assertIsNone(mint_task_from_landed_edit({}, str(self.root)))

    def test_symbol_identical_rewrite_mints_nothing(self):
        # "wrote" says the file changed, but the CONTENT is byte-identical to
        # HEAD -- no symbol source differs, so nothing should mint (guards
        # against a caller passing a stale/incorrect "wrote" list).
        (self.root / "mod.py").write_text(_MOD_V1, encoding="utf-8")
        report = {"wrote": ["mod.py"]}
        self.assertIsNone(mint_task_from_landed_edit(report, str(self.root)))

    def test_out_of_scope_written_file_is_skipped_not_target_or_label(self):
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V2, encoding="utf-8")
        (self.root / "dist").mkdir()
        (self.root / "dist" / "bundle.js").write_text("var x=1;", encoding="utf-8")
        report = {"wrote": ["mod.py", "other.py", "dist/bundle.js"]}
        task = mint_task_from_landed_edit(report, str(self.root))
        self.assertIsNotNone(task)
        self.assertEqual(task["skipped_out_of_scope"], ["dist/bundle.js"])
        self.assertEqual(task["must_include"], ["other_func"])


class MintFromDiffsScopeAndLabelTest(unittest.TestCase):
    """Pure-function checks against ``_mint_from_diffs`` directly -- no git,
    no indexer -- isolating exactly the scope-filtering / cross-file-only /
    cap rules from the git plumbing already covered above."""

    @staticmethod
    def _module(names: list[str], variant: int) -> str:
        return "".join(f"def {n}():\n    return {variant}\n\n" for n in names)

    def _files_ab(self):
        a_before = self._module(["f", "f2"], 1)
        a_after = self._module(["f", "f2"], 2)
        b_before = self._module(["g"], 1)
        b_after = self._module(["g"], 2)
        return {"a.py": (a_before, a_after), "b.py": (b_before, b_after)}

    def test_cross_file_labels_only_a_anchors_b_labels(self):
        # a.py changed 2 symbols, b.py changed 1 -> a.py anchors (more
        # changed symbols), so must_include can only be b.py's symbol(s).
        files = self._files_ab()
        task, diag = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"a.py", "b.py"}))
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "a.py")
        self.assertEqual(task["must_include"], ["g"])
        self.assertNotIn("f", task["must_include"])
        self.assertNotIn("f2", task["must_include"])
        self.assertEqual(diag["skipped_out_of_scope"], [])

    def test_out_of_scope_file_never_target_or_label_and_is_reported(self):
        files = self._files_ab()
        files["dist/bundle.js"] = (None, "var x=1;")
        task, diag = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"a.py", "b.py"}))  # dist/bundle.js deliberately absent
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "a.py")
        self.assertEqual(task["must_include"], ["g"])
        self.assertEqual(task["skipped_out_of_scope"], ["dist/bundle.js"])
        self.assertEqual(diag["skipped_out_of_scope"], ["dist/bundle.js"])

    def test_only_out_of_scope_file_changed_mints_nothing_with_reason(self):
        files = {"dist/bundle.js": (None, "var x=1;")}
        task, diag = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset())
        self.assertIsNone(task)
        self.assertEqual(diag["skipped_out_of_scope"], ["dist/bundle.js"])
        self.assertTrue(diag["reason"])

    def test_single_in_scope_file_mints_nothing_with_reason(self):
        files = {"a.py": (self._module(["f"], 1), self._module(["f"], 2))}
        task, diag = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"a.py"}))
        self.assertIsNone(task)
        self.assertEqual(diag["skipped_out_of_scope"], [])
        self.assertIn("a.py", diag["reason"])

    def test_target_choice_tie_breaks_on_path(self):
        # Both files change exactly one symbol -> tie on count; the anchor
        # must be the lexicographically smaller path regardless of dict
        # insertion order (zzz.py is inserted first here).
        files = {
            "zzz.py": (self._module(["z_sym"], 1), self._module(["z_sym"], 2)),
            "aaa.py": (self._module(["a_sym"], 1), self._module(["a_sym"], 2)),
        }
        task, _ = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"zzz.py", "aaa.py"}))
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "aaa.py::a_sym")
        self.assertEqual(task["must_include"], ["z_sym"])

    def test_label_cap_enforced_and_drop_count_recorded(self):
        # a.py changes 31 symbols (anchor, more than b.py's 30) so it never
        # contests the cap; b.py's 30 same-magnitude symbols are the label
        # pool -- capped at MUST_INCLUDE_CAP (25), keeping the alphabetically
        # first 25 (equal magnitude -> the tie-break is the symbol name).
        a_names = [f"a_sym{i:02d}" for i in range(31)]
        b_names = [f"b_sym{i:02d}" for i in range(30)]
        files = {
            "a.py": (self._module(a_names, 1), self._module(a_names, 2)),
            "b.py": (self._module(b_names, 1), self._module(b_names, 2)),
        }
        task, _ = _mint_from_diffs(
            files, repo_root=".", minted_at_sha="deadbeef", source="commit",
            in_scope=frozenset({"a.py", "b.py"}))
        self.assertIsNotNone(task)
        self.assertEqual(task["target"], "a.py")
        self.assertEqual(len(task["must_include"]), MUST_INCLUDE_CAP)
        self.assertEqual(task["must_include_dropped"], 30 - MUST_INCLUDE_CAP)
        self.assertEqual(task["must_include"], sorted(f"b_sym{i:02d}" for i in range(MUST_INCLUDE_CAP)))
        self.assertTrue(all(name.startswith("b_sym") for name in task["must_include"]))


class ConfirmationCounterTest(unittest.TestCase):
    """Pure-function checks -- no git needed, isolates the tier-promotion rule."""

    def _quarantined_task(self) -> dict:
        return {
            "id": "mint-test-abc123", "repo": ".", "target": "x.py::f",
            "must_include": ["f"], "label_provenance": "independent_diff",
            "tier": "quarantine", "minted_at_sha": "deadbeef", "confirmations": 0,
            "mint_source": "commit",
        }

    def test_stays_quarantined_below_threshold(self):
        task = self._quarantined_task()
        for _ in range(MINT_CONFIRM_THRESHOLD - 1):
            confirm_task(task)
        self.assertEqual(task["tier"], "quarantine")
        self.assertEqual(task["confirmations"], MINT_CONFIRM_THRESHOLD - 1)

    def test_promotes_to_primary_at_threshold(self):
        task = self._quarantined_task()
        for _ in range(MINT_CONFIRM_THRESHOLD):
            confirm_task(task)
        self.assertEqual(task["tier"], "primary")
        self.assertEqual(task["confirmations"], MINT_CONFIRM_THRESHOLD)

    def test_confirming_a_primary_task_is_a_noop(self):
        task = self._quarantined_task()
        task["tier"] = "primary"
        task["confirmations"] = 99
        confirm_task(task)
        self.assertEqual(task["tier"], "primary")
        self.assertEqual(task["confirmations"], 99)


class MintStorePersistenceTest(unittest.TestCase):
    """Regression for the MEDIUM defect's "no persistence" leg: before this
    fix, mint_task_from_landed_edit/mint_from_commit/confirm_task returned or
    mutated in-memory dicts only -- nothing survived past the caller's local
    variable. Never touches the real default store (always an explicit temp
    path), so this can run in parallel with other repair tracks safely."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_path = str(Path(self._tmp.name) / "minted_tasks.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _task(self, id_="mint-x-1", confirmations=0, tier="quarantine"):
        return {
            "id": id_, "repo": ".", "target": "x.py::f", "must_include": ["f"],
            "label_provenance": "independent_diff", "tier": tier,
            "minted_at_sha": "deadbeef", "confirmations": confirmations,
            "mint_source": "commit",
        }

    def test_load_missing_store_returns_empty(self):
        self.assertEqual(load_minted_tasks(self.store_path), [])

    def test_save_then_load_roundtrip(self):
        save_minted_tasks([self._task()], path=self.store_path)
        loaded = load_minted_tasks(self.store_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "mint-x-1")
        self.assertEqual(loaded[0]["must_include"], ["f"])

    def test_add_minted_task_is_idempotent_by_id(self):
        # Minting the same diff twice (e.g. re-running --mint-commit on the
        # same SHA) must not duplicate the quarantine entry.
        add_minted_task(self._task(), path=self.store_path)
        add_minted_task(self._task(), path=self.store_path)
        self.assertEqual(len(load_minted_tasks(self.store_path)), 1)

    def test_add_minted_task_appends_distinct_ids(self):
        add_minted_task(self._task("mint-a"), path=self.store_path)
        add_minted_task(self._task("mint-b"), path=self.store_path)
        self.assertEqual({t["id"] for t in load_minted_tasks(self.store_path)},
                         {"mint-a", "mint-b"})

    def test_confirm_minted_task_persists_confirmation_count(self):
        add_minted_task(self._task(confirmations=0), path=self.store_path)
        confirm_minted_task("mint-x-1", path=self.store_path)
        loaded = load_minted_tasks(self.store_path)
        self.assertEqual(loaded[0]["confirmations"], 1)
        self.assertEqual(loaded[0]["tier"], "quarantine")

    def test_confirm_minted_task_promotes_to_primary_at_threshold_and_persists(self):
        add_minted_task(self._task(confirmations=0), path=self.store_path)
        for _ in range(MINT_CONFIRM_THRESHOLD):
            confirm_minted_task("mint-x-1", path=self.store_path)
        loaded = load_minted_tasks(self.store_path)
        self.assertEqual(loaded[0]["tier"], "primary")
        self.assertEqual(loaded[0]["confirmations"], MINT_CONFIRM_THRESHOLD)

    def test_confirm_minted_task_unknown_id_returns_none_and_does_not_create_file(self):
        self.assertIsNone(confirm_minted_task("nope", path=self.store_path))
        self.assertFalse(Path(self.store_path).exists())


class HarnessAllTasksLoadPathTest(unittest.TestCase):
    """Regression for the MEDIUM defect's "no load path" leg: a minted task
    persisted to the store must actually reach daedalus.eval.harness's
    default task set -- before this fix there was no such path (TASKS was a
    hardcoded literal and nothing ever read the store). Patches
    daedalus.eval.mint.DEFAULT_MINT_STORE_PATH so this never touches the real
    repo's minted_tasks.json."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_path = str(Path(self._tmp.name) / "minted_tasks.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_tasks_is_exactly_tasks_when_store_is_empty(self):
        # Additive/fail-closed check: with nothing ever minted (no store
        # file), all_tasks() must be byte-identical to the hardcoded TASKS --
        # this closes the loop without changing behavior for every caller who
        # has never run a mint.
        from daedalus.eval import harness
        from daedalus.eval.tasks import TASKS
        with mock.patch("daedalus.eval.mint.DEFAULT_MINT_STORE_PATH", self.store_path):
            self.assertEqual(harness.all_tasks(), TASKS)

    def test_all_tasks_includes_a_persisted_minted_task(self):
        from daedalus.eval import harness
        from daedalus.eval.tasks import TASKS
        minted = {
            "id": "mint-commit-abcdef012345", "repo": ".", "target": "x.py::f",
            "must_include": ["f"], "label_provenance": "independent_diff",
            "tier": "quarantine", "minted_at_sha": "deadbeef", "confirmations": 0,
            "mint_source": "commit",
        }
        save_minted_tasks([minted], path=self.store_path)
        with mock.patch("daedalus.eval.mint.DEFAULT_MINT_STORE_PATH", self.store_path):
            tasks = harness.all_tasks()
        self.assertEqual(len(tasks), len(TASKS) + 1)
        self.assertIn(minted, tasks)


@unittest.skipUnless(GIT, "git not on PATH")
class MintCliEntryPointTest(unittest.TestCase):
    """Regression for the MEDIUM defect's "no entry point" leg: before this
    fix, __main__.py had --tier2/--arms/--project/--provider/--gate/
    --update-baseline/--baseline-path and NOTHING that could mint. This
    exercises --mint-commit and --confirm-mint end to end, plus the full
    mint -> persist -> all_tasks() loop using the real default store path
    (patched to a temp file, never the repo's real minted_tasks.json)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        (self.root / "mod.py").write_text(_MOD_V1, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V1, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        (self.root / "other.py").write_text(_OTHER_V2, encoding="utf-8")
        _git(self.root, "commit", "-qam", "v2: reweight target_func and other_func")
        self.sha2 = _git(self.root, "rev-parse", "HEAD").strip()
        self._store_tmp = tempfile.TemporaryDirectory()
        self.store_path = str(Path(self._store_tmp.name) / "minted_tasks.json")

    def tearDown(self):
        self._tmp.cleanup()
        self._store_tmp.cleanup()

    def test_mint_commit_cli_persists_a_quarantined_task(self):
        from daedalus.eval import __main__ as eval_main
        rc = eval_main.main(["--mint-commit", self.sha2, "--repo", str(self.root),
                             "--mint-store-path", self.store_path])
        self.assertEqual(rc, 0)
        loaded = load_minted_tasks(self.store_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["must_include"], ["other_func"])
        self.assertEqual(loaded[0]["tier"], "quarantine")

    def test_mint_commit_cli_unresolvable_sha_exits_nonzero_and_persists_nothing(self):
        from daedalus.eval import __main__ as eval_main
        rc = eval_main.main(["--mint-commit", "deadbeef" * 5, "--repo", str(self.root),
                             "--mint-store-path", self.store_path])
        self.assertEqual(rc, 1)
        self.assertEqual(load_minted_tasks(self.store_path), [])

    def test_confirm_mint_cli_promotes_at_threshold(self):
        from daedalus.eval import __main__ as eval_main
        eval_main.main(["--mint-commit", self.sha2, "--repo", str(self.root),
                        "--mint-store-path", self.store_path])
        task_id = load_minted_tasks(self.store_path)[0]["id"]
        for _ in range(MINT_CONFIRM_THRESHOLD):
            rc = eval_main.main(["--confirm-mint", task_id,
                                 "--mint-store-path", self.store_path])
            self.assertEqual(rc, 0)
        self.assertEqual(load_minted_tasks(self.store_path)[0]["tier"], "primary")

    def test_confirm_mint_cli_unknown_id_exits_nonzero(self):
        from daedalus.eval import __main__ as eval_main
        rc = eval_main.main(["--confirm-mint", "nope",
                             "--mint-store-path", self.store_path])
        self.assertEqual(rc, 1)

    def test_mint_commit_cli_then_all_tasks_picks_it_up_via_default_path(self):
        """The end-to-end closure of the flywheel: --mint-commit persists to
        the DEFAULT store path (no --mint-store-path override), and a plain
        harness.all_tasks() call -- exactly what every run_* function uses --
        picks it up with no extra wiring. This is the load path that the
        MEDIUM defect said could never be reached."""
        from daedalus.eval import __main__ as eval_main
        from daedalus.eval import harness
        with mock.patch("daedalus.eval.mint.DEFAULT_MINT_STORE_PATH", self.store_path):
            rc = eval_main.main(["--mint-commit", self.sha2, "--repo", str(self.root)])
            self.assertEqual(rc, 0)
            tasks = harness.all_tasks()
        minted = [t for t in tasks if t.get("mint_source") == "commit"]
        self.assertEqual(len(minted), 1)
        self.assertEqual(minted[0]["must_include"], ["other_func"])
        self.assertEqual(minted[0]["tier"], "quarantine")


if __name__ == "__main__":
    unittest.main()
