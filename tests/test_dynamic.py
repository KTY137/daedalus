# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for Phase 2: dynamic decomposition + the unified bench/Claude
bridge. Every model/network seam is mocked -- no live Ollama or Claude call is
made. Run with:  python -m unittest discover tests
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daedalus import file_bridge
from daedalus.kairos.decompose import decompose
from daedalus.kairos.scheduler import KairosScheduler


class DecomposeFallbackTests(unittest.TestCase):
    """When the local model is unreachable, the deterministic split is used."""

    def test_multi_path_splits_one_subtask_per_path(self):
        with patch("daedalus.kairos.decompose.server_reachable", return_value=False):
            out = decompose("Tidy the modules", "/repo",
                            paths=["a.py", "b.py", "c.py"])
        self.assertEqual(len(out), 3)
        self.assertEqual([s["paths"] for s in out], [["a.py"], ["b.py"], ["c.py"]])
        self.assertTrue(all(s["objective"] == "Tidy the modules" for s in out))

    def test_single_path_is_one_passthrough_subtask(self):
        with patch("daedalus.kairos.decompose.server_reachable", return_value=False):
            out = decompose("Tidy one module", "/repo", paths=["only.py"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], {"objective": "Tidy one module", "paths": ["only.py"]})

    def test_no_paths_still_returns_one_subtask(self):
        with patch("daedalus.kairos.decompose.server_reachable", return_value=False):
            out = decompose("Do the thing", "/repo")
        self.assertEqual(out, [{"objective": "Do the thing", "paths": []}])


class DecomposeModelTests(unittest.TestCase):
    """When the local model answers, its JSON breakdown drives the subtasks."""

    def test_parses_mocked_json_breakdown(self):
        payload = json.dumps({"subtasks": [
            {"objective": "Add docstrings to a", "paths": ["a.py"]},
            {"objective": "Refactor helper in b", "paths": ["b.py"]},
        ]})
        with patch("daedalus.kairos.decompose.server_reachable", return_value=True), \
                patch("daedalus.kairos.decompose.chat_completion", return_value=payload) as cc:
            out = decompose("Improve module", "/repo", paths=["a.py", "b.py"])
        cc.assert_called_once()  # went through the model, not the fallback
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["objective"], "Add docstrings to a")
        self.assertEqual(out[0]["paths"], ["a.py"])

    def test_parses_bare_json_array_and_honours_max_subtasks(self):
        payload = json.dumps([
            {"objective": "s1", "paths": []},
            {"objective": "s2", "paths": []},
            {"objective": "s3", "paths": []},
        ])
        with patch("daedalus.kairos.decompose.server_reachable", return_value=True), \
                patch("daedalus.kairos.decompose.chat_completion", return_value=payload):
            out = decompose("Split me", "/repo", max_subtasks=2)
        self.assertEqual(len(out), 2)  # truncated to max_subtasks

    def test_garbage_response_falls_back(self):
        with patch("daedalus.kairos.decompose.server_reachable", return_value=True), \
                patch("daedalus.kairos.decompose.chat_completion", return_value="not json at all"):
            out = decompose("Fallback please", "/repo", paths=["x.py", "y.py"])
        self.assertEqual(len(out), 2)  # deterministic per-path split


class IkarusSpawnTests(unittest.TestCase):
    def test_spawn_dry_run_returns_a_plan(self):
        # Offline: no model -> deterministic subtask; plan() never touches network.
        with patch("daedalus.kairos.decompose.server_reachable", return_value=False):
            plan = KairosScheduler().spawn("Draft docstrings for the gui panel", "/repo", dry_run=True)
        self.assertIsInstance(plan, dict)
        for key in ("assignments", "spawned", "bounced_to_adam", "waves"):
            self.assertIn(key, plan)
        self.assertIsInstance(plan["assignments"], list)
        self.assertGreaterEqual(len(plan["assignments"]), 1)


class BridgeLaneRoutingTests(unittest.TestCase):
    """process_request must send lane='claude' to ask_claude and local-capable
    lanes through Ikarus -- both fully mocked."""

    def _write_request(self, tmp: Path, lane: str) -> Path:
        req = tmp / "req.json"
        req.write_text(json.dumps({
            "objective": "Draft docstrings for the gui panel",
            "repo_root": "/repo",
            "paths": ["TCT_app/gui/panel.py"],
            "model": "sonnet",
            "lane": lane,
        }), encoding="utf-8")
        return req

    def test_claude_lane_calls_ask_claude_not_offload(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="claude")
            claude_result = {"agent": "ui-ux-dev", "report": {"status": "done", "summary": "ok"}}
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.core.ask_claude", return_value=claude_result) as ask, \
                    patch("daedalus.offload.offload",
                          side_effect=AssertionError("offload must not run on the claude lane")) as off:
                out_path = file_bridge.process_request(req)
            ask.assert_called_once()
            off.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "done")
        self.assertEqual(report["lane"], "claude")
        self.assertEqual(report["report"]["status"], "done")

    def test_unknown_or_missing_lane_fails_closed_not_claude(self):
        """A typo'd or absent lane must never reach a paid provider unattended."""
        from daedalus import core
        for bad in ({"lane": "local-only"}, {"lane": "banana"}, {}):
            payload = {"objective": "x", "repo_root": "", "paths": [], "model": "", **bad}
            with patch("daedalus.core._try_ikarus", return_value=None), \
                    patch("daedalus.core._ask_claude_report",
                          side_effect=AssertionError("unknown/missing lane must not reach Claude")):
                report = core.process_bridge_payload(payload)
            self.assertEqual(report["bridge_status"], "failed")
            self.assertNotEqual(report.get("lane"), "claude")

    def test_lane_less_request_fails_closed_through_file_bridge(self):
        """The REAL watcher path: a file dropped in outbox with NO lane key must
        not reach Claude (regression for the setdefault('lane','auto') hole)."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = tmp / "req.json"
            req.write_text(json.dumps({
                "objective": "Draft docstrings for the gui panel",
                "repo_root": "/repo",
                "paths": ["TCT_app/gui/panel.py"],
                "model": "sonnet",
            }), encoding="utf-8")  # deliberately no "lane" key
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.core._try_ikarus", return_value=None), \
                    patch("daedalus.core.ask_claude",
                          side_effect=AssertionError("lane-less file must not reach Claude")):
                out_path = file_bridge.process_request(req)
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "failed")
        self.assertNotEqual(report.get("lane"), "claude")

    def test_local_lane_eligible_runs_offload_not_claude(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="local")
            doctor_ready = {"claude_cli": True, "can_offload_local": True, "deepseek_key": False}
            offload_result = {"owner": "ui-ux-dev", "provider": "ollama", "action": "offloaded",
                              "report": {"status": "done", "summary": "bench did it"}}
            decision = SimpleNamespace(provider="ollama", persona="Noah-local",
                                       mode="write", reason="low-risk local task")
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value=doctor_ready), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "ui-ux-dev"}, decision)), \
                    patch("daedalus.offload.offload", return_value=offload_result) as off, \
                    patch("daedalus.core.ask_claude",
                          side_effect=AssertionError("claude must not run for an eligible local task")) as ask:
                out_path = file_bridge.process_request(req)
            off.assert_called_once()
            ask.assert_not_called()
            # offload was invoked live, on the bench, with the doctor availability.
            _, kwargs = off.call_args
            self.assertTrue(kwargs.get("live"))
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "done")
        self.assertEqual(report["lane"], "local")
        self.assertEqual(report["orchestrator"], "ikarus")
        self.assertEqual(report["result"]["assignments"][0]["status"], "offloaded")

    def test_local_lane_ineligible_falls_through_to_claude(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="local")
            doctor_ready = {"claude_cli": True, "can_offload_local": True, "deepseek_key": False}
            # Route lands on the senior lane -> not a FREE lane -> fall through.
            decision = SimpleNamespace(provider="claude_cli", persona="Adam",
                                       mode="advisory", reason="senior lane")
            claude_result = {"agent": "hardware-dev", "report": {"status": "done", "summary": "senior"}}
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value=doctor_ready), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "hardware-dev"}, decision)), \
                    patch("daedalus.offload.offload",
                          side_effect=AssertionError("offload must not run for a senior-lane route")) as off, \
                    patch("daedalus.core.ask_claude", return_value=claude_result) as ask:
                out_path = file_bridge.process_request(req)
            off.assert_not_called()
            ask.assert_called_once()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["lane"], "claude")
        self.assertEqual(report["bridge_status"], "done")

    def test_local_only_lane_never_falls_through_to_claude(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="local_only")
            doctor_ready = {"claude_cli": True, "can_offload_local": True, "deepseek_key": False}
            decision = SimpleNamespace(provider="claude_cli", persona="Adam",
                                       mode="advisory", reason="senior lane")
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value=doctor_ready), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "hardware-dev"}, decision)), \
                    patch("daedalus.offload.offload",
                          side_effect=AssertionError("offload must not run for a senior-lane route")) as off, \
                    patch("daedalus.core.ask_claude",
                          side_effect=AssertionError("local_only must not call Claude")) as ask:
                out_path = file_bridge.process_request(req)
            off.assert_not_called()
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["lane"], "local")
        self.assertEqual(report["bridge_status"], "failed")
        self.assertIn("Claude fallback skipped", report["error"])


if __name__ == "__main__":
    unittest.main()
