"""test_eval_mint.py -- independent-oracle task minting (daedalus.eval.mint).

Every assertion here ultimately serves the ANTI-CIRCULARITY guarantee the
module exists for: ``must_include`` must be exactly what a diff literally
touched, never expanded through the callee/import graph.
``test_must_include_excludes_untouched_callee`` is written so it would go RED
the moment someone "helpfully" adds a graph.callees expansion to mint.py --
that is the failure mode this whole track exists to prevent.

Offline only: all git history is built in temp repos via subprocess, exactly
like tests/test_churn.py's house style. No network, no real Claude/Ollama
call, no real device path.
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


# target_func CALLS helper. Only target_func's body differs between v1 and
# v2 -- helper is byte-identical -- so a correct mint must name target_func
# and MUST NOT name helper, even though a graph walk from target_func would
# reach helper in one hop.
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


@unittest.skipUnless(GIT, "git not on PATH")
class MintFromCommitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        (self.root / "mod.py").write_text(_MOD_V1, encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        _git(self.root, "commit", "-qam", "v2: reweight target_func")
        self.sha2 = _git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_must_include_is_exactly_the_changed_symbol(self):
        tasks = mint_from_commit(str(self.root), self.sha2)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["must_include"], ["target_func"])

    def test_must_include_excludes_untouched_callee(self):
        # The anti-circularity assertion. helper() is called BY target_func()
        # but its own source never changed; if a future edit adds a
        # graph.callees expansion (the thing the mint.py module docstring
        # explicitly forbids), "helper" would leak into must_include and this
        # assertion is the one that catches it.
        tasks = mint_from_commit(str(self.root), self.sha2)
        self.assertNotIn("helper", tasks[0]["must_include"])

    def test_single_symbol_single_file_gets_symbol_scoped_target(self):
        tasks = mint_from_commit(str(self.root), self.sha2)
        self.assertEqual(tasks[0]["target"], "mod.py::target_func")

    def test_provenance_tier_sha_and_repo_fields(self):
        task = mint_from_commit(str(self.root), self.sha2)[0]
        self.assertEqual(task["label_provenance"], "independent_diff")
        self.assertEqual(task["tier"], "quarantine")
        self.assertEqual(task["confirmations"], 0)
        self.assertEqual(task["minted_at_sha"], self.sha2)
        self.assertTrue(Path(task["repo"]).exists())

    def test_root_commit_has_no_parent_and_still_mints_everything(self):
        root_sha = _git(self.root, "rev-list", "--max-parents=0", "HEAD").strip()
        tasks = mint_from_commit(str(self.root), root_sha)
        self.assertEqual(len(tasks), 1)
        # No parent -> before is empty -> both symbols in the file count as
        # "added" (there is no unchanged callee to wrongly exclude here).
        self.assertIn("helper", tasks[0]["must_include"])
        self.assertIn("target_func", tasks[0]["must_include"])

    def test_unknown_sha_mints_nothing(self):
        self.assertEqual(mint_from_commit(str(self.root), "deadbeef" * 5), [])

    def test_unresolvable_repo_mints_nothing(self):
        with tempfile.TemporaryDirectory() as not_a_repo:
            self.assertEqual(mint_from_commit(not_a_repo, self.sha2), [])


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
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_uncommitted_worktree_edit_is_diffed_against_head(self):
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        report = {"wrote": ["mod.py"]}
        task = mint_task_from_landed_edit(report, str(self.root))
        self.assertIsNotNone(task)
        self.assertEqual(task["must_include"], ["target_func"])
        self.assertEqual(task["label_provenance"], "independent_diff")
        self.assertEqual(task["tier"], "quarantine")
        self.assertEqual(task["target"], "mod.py::target_func")

    def test_new_file_counts_every_symbol_as_added(self):
        (self.root / "new_mod.py").write_text("def brand_new():\n    return 1\n", encoding="utf-8")
        report = {"wrote": ["new_mod.py"]}
        task = mint_task_from_landed_edit(report, str(self.root))
        self.assertEqual(task["must_include"], ["brand_new"])

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
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "v1")
        (self.root / "mod.py").write_text(_MOD_V2, encoding="utf-8")
        _git(self.root, "commit", "-qam", "v2: reweight target_func")
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
        self.assertEqual(loaded[0]["must_include"], ["target_func"])
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
        self.assertEqual(minted[0]["must_include"], ["target_func"])
        self.assertEqual(minted[0]["tier"], "quarantine")


if __name__ == "__main__":
    unittest.main()
