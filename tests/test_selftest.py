"""The live-selftest HARNESS is unit-tested with mocks (fast, deterministic);
the CAPABILITY it checks is exercised by `daedalus selftest` against real Ollama.
This is the two-tier split in action: here we prove the harness skips cleanly
when the bench is down and reports PASS on a real on-disk change.
"""

import unittest
from pathlib import Path
from unittest import mock

from daedalus import selftest


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


if __name__ == "__main__":
    unittest.main()
