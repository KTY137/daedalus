"""The live-selftest HARNESS is unit-tested with mocks (fast, deterministic);
the CAPABILITY it checks is exercised by `daedalus selftest` against real Ollama.
This is the two-tier split in action: here we prove the harness skips cleanly
when the bench is down and reports PASS on a real on-disk change.
"""

import unittest
from pathlib import Path
from unittest import mock

from daedalus.interfaces.cli import selftest


class SelftestHarnessTests(unittest.TestCase):
    def test_skips_cleanly_when_bench_not_ready(self):
        with mock.patch("daedalus.doctor.check", return_value={"can_offload_local": False}):
            r = selftest.run()
        self.assertFalse(r["ok"])
        self.assertTrue(r["skipped"])

    def test_reports_pass_on_a_real_disk_change(self):
        def fake_offload(objective, repo, paths, **kw):
            # mimic a good bench: actually rewrite the target with a docstring
            p = Path(repo) / paths[0]
            p.write_text('def greet(name):\n    """Greet."""\n    return "hi " + name\n',
                         encoding="utf-8")
            return {"provider": "ollama", "persona": "Hey", "mode": "write",
                    "action": "offloaded", "verify": {"ok": True},
                    "wrote": ["src/hello.py"]}

        with mock.patch("daedalus.doctor.check", return_value={"can_offload_local": True}), \
                mock.patch("daedalus.offload.offload", side_effect=fake_offload):
            r = selftest.run()
        self.assertTrue(r["ok"], r)
        self.assertFalse(r["skipped"])
        self.assertTrue(all(c["ok"] for c in r["checks"]))

    def test_reports_fail_when_nothing_changed(self):
        def noop_offload(objective, repo, paths, **kw):
            return {"provider": "ollama", "mode": "write", "action": "offloaded",
                    "verify": {"ok": True}, "wrote": []}  # claims success, wrote nothing

        with mock.patch("daedalus.doctor.check", return_value={"can_offload_local": True}), \
                mock.patch("daedalus.offload.offload", side_effect=noop_offload):
            r = selftest.run()
        self.assertFalse(r["ok"])   # file-changed + wrote-ground-truth checks fail


class ScratchRepoCleanupTests(unittest.TestCase):
    """The scratch repo is deleted through the GUARDED walker, and a delete
    that could not finish is REPORTED.

    This was ``shutil.rmtree(repo, ignore_errors=True)`` in a ``finally:`` on a
    directory a live model had just written into -- the same pattern the
    security round removed from ``daedalus.spine.attempt`` one file over.

    The discriminating test is the REPORTING one, deliberately. A "does it
    follow a junction" test would NOT reliably go red on a revert: measured on
    this box, ``shutil.rmtree`` is safe against a junction that is already in
    place and only unsafe against one renamed mid-walk, so a static junction
    fixture can pass against the very code this guard replaced. Swallowed
    versus reported failure separates them every time.
    """

    def test_a_delete_that_cannot_finish_is_reported_not_swallowed(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="daedalus-selftest-test-"))
        blocker = tmp / "held.txt"
        blocker.write_text("x", encoding="utf-8")
        handle = open(blocker, "r+b")          # Windows: an open file blocks removal
        try:
            err = selftest._remove_selftest_repo(tmp)
            if err is None:
                # POSIX happily unlinks an open file; there the delete really
                # does succeed and there is nothing to report.
                self.assertFalse(tmp.exists())
                self.skipTest("this platform can delete a directory holding an "
                              "open file, so no failure exists to report")
            self.assertIn(str(tmp), err)
            self.assertIn("NOT removed", err)
        finally:
            handle.close()
            selftest._remove_selftest_repo(tmp)

    def test_a_clean_scratch_repo_is_actually_removed(self):
        # The control: without it, a function that always failed would pass the
        # reporting test above and prove nothing.
        repo = Path(selftest._build_repo())
        self.assertTrue(repo.exists())
        self.assertIsNone(selftest._remove_selftest_repo(repo))
        self.assertFalse(repo.exists())

    def test_the_module_holds_no_recursive_delete_of_its_own(self):
        # Structural, not a promise in a docstring: re-introducing
        # `shutil.rmtree` here has to cost a visible import line.
        import ast

        source = Path(selftest.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name
                    for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        self.assertNotIn("shutil", imported)


if __name__ == "__main__":
    unittest.main()
