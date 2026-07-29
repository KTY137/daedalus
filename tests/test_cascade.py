import os
import tempfile
import unittest
from pathlib import Path

from daedalus import metrics, semantic_route, verifier
from daedalus.offload import offload
from daedalus.provider_router import route_and_select
from daedalus.projects import load_project
from daedalus.sensitivity import load_policy, path_write_blocked


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

    def test_trusted_only_review_can_use_local_advisory(self):
        avail = {"claude_cli": True, "ollama": True, "deepseek": False}
        agent, decision = route_and_select("Review the current diff for regressions", [], avail)
        self.assertEqual(agent["name"], "qa-critic")
        self.assertEqual(decision.provider, "ollama")
        self.assertEqual(decision.mode, "advisory")


class SemanticFallbackTests(unittest.TestCase):
    def test_falls_back_to_keyword_when_embedder_down(self):
        # No Ollama here -> _embed returns None -> keyword router is used.
        agent = semantic_route.semantic_route("review scan state machine races",
                                              paths=["TCT_app/controller/state_machine.py"])
        self.assertIn("name", agent)


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

    def test_default_policy_blocks_devices(self):
        self.assertTrue(path_write_blocked("TCT_app/devices/motor_grbl.py"))


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
        # Hermetic repo: a repo-local agent forces write-mode routing, but NO
        # policy block exists -> the live write must be refused (fail-closed).
        avail = {"claude_cli": True, "ollama": True, "deepseek": False}
        agents = Path(self._tmp.name) / ".agentenv" / "agents"
        agents.mkdir(parents=True)
        (agents / "gui-dev.json").write_text(
            '{"name": "gui-dev", "call_name": "Pix", "model_tier": "sonnet",'
            ' "external_ok": true, "owns": ["TCT_app/gui"], "triggers": ["docstring"],'
            ' "must_read": [], "output_schema": "agent_report_v1"}',
            encoding="utf-8")
        r = offload("Add a docstring to the scan panel", self._tmp.name,
                    paths=["TCT_app/gui/scan_panel.py"], live=True, availability=avail, project=None)
        self.assertEqual(r["mode"], "write")
        self.assertEqual(r["action"], "escalate_to_claude")
        self.assertIn("policy", r.get("note", ""))


if __name__ == "__main__":
    unittest.main()
