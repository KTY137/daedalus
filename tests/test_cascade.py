import os
import tempfile
import unittest
from pathlib import Path

from agent_env import compaction, metrics, semantic_route, verifier
from agent_env.offload import offload
from agent_env.projects import load_project
from agent_env.sensitivity import load_policy, path_write_blocked


def _report(files_changed=None, status="done"):
    return {"status": status, "summary": "s", "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class VerifierTests(unittest.TestCase):
    def test_schema_pass_no_files(self):
        self.assertTrue(verifier.verify(_report(), ".").ok)

    def test_schema_fail(self):
        bad = _report()
        bad["status"] = "bogus"
        self.assertFalse(verifier.verify(bad, ".").ok)

    def test_syntax_failure_detected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "broken.py").write_text("def f(:\n", encoding="utf-8")
            res = verifier.verify(_report(["broken.py"]), d)
            self.assertFalse(res.ok)
            self.assertTrue(any(c["name"].startswith("syntax:") for c in res.checks))

    def test_syntax_pass(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            self.assertTrue(verifier.verify(_report(["ok.py"]), d).ok)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_fallback_rate(self):
        metrics.record(provider="ollama", action="offloaded", eligible=True)
        metrics.record(provider="claude_cli", action="escalate_to_claude", eligible=True)
        s = metrics.summary()
        self.assertEqual(s["offloadable"], 2)
        self.assertEqual(s["fell_back_to_claude"], 1)
        self.assertAlmostEqual(s["fallback_rate"], 0.5)


class OffloadRoutingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_eligible_but_bench_down_escalates(self):
        avail = {"claude_cli": True, "ollama": False, "deepseek": False}
        r = offload("Draft docstrings for the gui panel", ".",
                    paths=["TCT_app/gui/x.py"], availability=avail)
        self.assertTrue(r["eligible"])
        self.assertEqual(r["action"], "escalate_to_claude")

    def test_would_offload_when_bench_up(self):
        avail = {"claude_cli": True, "ollama": True, "deepseek": False}
        r = offload("Draft docstrings for the gui panel", ".",
                    paths=["TCT_app/gui/x.py"], availability=avail)
        self.assertEqual(r["action"], "would_offload")
        self.assertEqual(r["provider"], "ollama")

    def test_hardware_task_is_senior_not_eligible(self):
        avail = {"claude_cli": True, "ollama": True, "deepseek": False}
        r = offload("Refactor the ISEG HV ramp driver", ".",
                    paths=["TCT_app/devices/bias_supply_iseg.py"], availability=avail)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["provider"], "claude_cli")


class SemanticFallbackTests(unittest.TestCase):
    def test_falls_back_to_keyword_when_embedder_down(self):
        # No Ollama here -> _embed returns None -> keyword router is used.
        agent = semantic_route.semantic_route("review scan state machine races",
                                              paths=["TCT_app/controller/state_machine.py"])
        self.assertIn("name", agent)


class CompactionTests(unittest.TestCase):
    def test_compacts_long_history(self):
        msgs = [{"role": "system", "content": "sys"}]
        msgs += [{"role": "user", "content": f"m{i}"} for i in range(20)]
        out = compaction.compact(msgs, keep_last=4)
        self.assertEqual(out[0]["role"], "system")
        self.assertTrue(any("[compacted earlier context]" in m["content"]
                            for m in out if m["role"] == "system"))
        self.assertLess(len(out), len(msgs))
        self.assertEqual(out[-1]["content"], "m19")


class WriteGuardTests(unittest.TestCase):
    """Regression tests for Mary's findings on the write-guard."""

    def setUp(self):
        self.pol = load_policy(load_project("project_tct"))

    def test_base_py_is_blocked(self):        # Mary #4
        self.assertTrue(path_write_blocked("TCT_app/devices/bias_supply_iseg_base.py", self.pol))

    def test_simulated_is_allowed(self):
        self.assertFalse(path_write_blocked("TCT_app/devices/motor_grbl_simulated.py", self.pol))

    def test_real_driver_blocked(self):
        self.assertTrue(path_write_blocked("TCT_app/devices/motor_grbl.py", self.pol))

    def test_controller_blocked(self):
        self.assertTrue(path_write_blocked("TCT_app/controller/state_machine.py", self.pol))

    def test_gui_allowed(self):
        self.assertFalse(path_write_blocked("TCT_app/gui/scan_panel.py", self.pol))

    def test_default_policy_would_leave_devices_writable(self):
        # This is the hole Mary found: under DEFAULT_POLICY the guard is off.
        self.assertFalse(path_write_blocked("TCT_app/devices/motor_grbl.py"))


class OffloadFailClosedTests(unittest.TestCase):
    """Mary #1: a live write with no project policy loaded must be refused."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_live_write_without_policy_is_refused(self):
        avail = {"claude_cli": True, "ollama": True, "deepseek": False}
        r = offload("Add a docstring to the scan panel", ".",
                    paths=["TCT_app/gui/scan_panel.py"], live=True, availability=avail, project=None)
        self.assertEqual(r["action"], "escalate_to_claude")
        self.assertIn("policy", r.get("note", ""))


if __name__ == "__main__":
    unittest.main()
