"""Offline tests for Phase 2: dynamic decomposition + the unified bench/Claude
bridge. Every model/network seam is mocked -- no live Ollama or Claude call is
made. Run with:  python -m unittest discover tests
"""

from __future__ import annotations

import json
import os
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
    """Queue lanes use the leased Ikarus path or fail closed, fully mocked."""

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

    def test_claude_lane_refuses_without_caller_held_broker_authority(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="claude")
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError(
                              "queue bridge must not directly call Claude")) as ask, \
                    patch("daedalus.offload.offload",
                          side_effect=AssertionError("offload must not run on the claude lane")) as off:
                out_path = file_bridge.process_request(req)
            ask.assert_not_called()
            off.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["lane"], "claude")
        self.assertEqual(report["requested_lane"], "claude")
        self.assertEqual(report["actual_providers"], [])
        self.assertIn("broker authorization", report["error"])

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
                    patch("daedalus.claude_bridge.ask_claude",
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
            wave_result = SimpleNamespace(mode="gated", results=[{
                "worker": "Noah-local", "lane": "ollama", "mode": "write",
                "owner": "ui-ux-dev", "status": "gated_held", "wrote": [],
                "result": {"provider": "ollama"},
                "effect_lease": {"lease_id": "mocked-lease"},
            }])
            decision = SimpleNamespace(provider="ollama", persona="Noah-local",
                                       mode="write", reason="low-risk local task")
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value=doctor_ready), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "ui-ux-dev"}, decision)), \
                    patch("daedalus.core._head_sha_safe", return_value="a" * 40), \
                    patch("daedalus.build_exec.WaveExecutor.run_wave",
                          return_value=wave_result) as run_wave, \
                    patch("daedalus.offload.offload",
                          side_effect=AssertionError(
                              "core must not bypass WaveExecutor")) as off, \
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError("claude must not run for an eligible local task")) as ask:
                out_path = file_bridge.process_request(req)
            run_wave.assert_called_once()
            off.assert_not_called()
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "done")
        self.assertEqual(report["lane"], "local")
        self.assertEqual(report["requested_lane"], "local")
        self.assertEqual(report["assigned_providers"], ["ollama"])
        self.assertEqual(report["actual_providers"], ["ollama"])
        self.assertEqual(report["orchestrator"], "ikarus")
        self.assertEqual(report["result"]["assignments"][0]["status"], "gated_held")

    def test_effect_lease_denial_is_reported_without_claude_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="local")
            decision = SimpleNamespace(
                provider="ollama", persona="Noah-local",
                mode="advisory", reason="local review",
            )
            wave_result = SimpleNamespace(mode="lease_denied", results=[{
                "worker": "Noah-local", "lane": "ollama",
                "mode": "advisory", "owner": "ui-ux-dev",
                "status": "effect_lease_denied",
                "reason": "operator permit is not armed",
            }])
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value={
                        "claude_cli": True, "can_offload_local": True,
                        "deepseek_key": False, "codex_cli": False,
                    }), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "ui-ux-dev"}, decision)), \
                    patch("daedalus.core._head_sha_safe", return_value="a" * 40), \
                    patch("daedalus.build_exec.WaveExecutor.run_wave",
                          return_value=wave_result), \
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError(
                              "an Effect denial must not be bypassed")) as ask:
                out_path = file_bridge.process_request(req)
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["lane"], "local")
        self.assertEqual(report["assigned_providers"], ["ollama"])
        self.assertEqual(report["actual_providers"], [])
        self.assertIn("permit", report["error"])
        self.assertEqual(
            report["result"]["assignments"][0]["status"],
            "effect_lease_denied",
        )

    def test_terminal_wave_failure_never_dispatches_a_second_provider(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="auto")
            decision = SimpleNamespace(
                provider="ollama", persona="Noah-local",
                mode="write", reason="local write",
            )
            wave_result = SimpleNamespace(mode="gated", results=[{
                "worker": "Noah-local", "lane": "ollama",
                "mode": "write", "owner": "ui-ux-dev",
                "status": "write_gate_failed",
                "reason": "verification failed after the leased attempt",
                "provider_receipt": {
                    "action": "escalated_after_verify_fail",
                },
            }])
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value={
                        "claude_cli": True, "can_offload_local": True,
                        "deepseek_key": False, "codex_cli": False,
                    }), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "ui-ux-dev"}, decision)), \
                    patch("daedalus.core._head_sha_safe", return_value="a" * 40), \
                    patch("daedalus.build_exec.WaveExecutor.run_wave",
                          return_value=wave_result), \
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError(
                              "a terminal wave failure must not dispatch again")) as ask:
                out_path = file_bridge.process_request(req)
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["lane"], "auto")
        self.assertEqual(report["requested_lane"], "auto")
        self.assertEqual(report["actual_providers"], [])
        self.assertIn("verification failed", report["error"])
        self.assertEqual(
            report["result"]["assignments"][0]["status"],
            "write_gate_failed",
        )

    def test_lost_gated_artifact_still_reports_the_observed_provider(self):
        from daedalus import core

        assigned, actual = core._ikarus_provider_facts([{
            "lane": "ollama",
            "status": "gated_artifact_lost",
            "provider_receipt": {"provider": "ollama", "action": "offloaded"},
        }])

        self.assertEqual(assigned, ["ollama"])
        self.assertEqual(actual, ["ollama"])

    def test_spawn_strategy_is_refused_before_any_unleased_dispatch(self):
        from daedalus import core

        payload = {
            "objective": "Split and edit several modules",
            "repo_root": "/repo",
            "paths": ["a.py", "b.py"],
            "model": "sonnet",
            "lane": "local",
            "strategy": "spawn",
        }
        with patch.object(
            KairosScheduler, "spawn",
            side_effect=AssertionError("spawn must not dispatch outside WaveExecutor"),
        ) as spawn, patch(
            "daedalus.core._ask_claude_report",
            side_effect=AssertionError("a refused bypass must not fall back"),
        ) as ask:
            report = core.process_bridge_payload(payload)
        spawn.assert_not_called()
        ask.assert_not_called()
        self.assertEqual(report["bridge_status"], "failed")
        self.assertIn("no canonical leased multi-task adapter", report["error"])

    def test_local_only_exposes_only_reachable_trusted_ollama(self):
        from daedalus import core

        doctor_ready = {
            "claude_cli": True, "can_offload_local": True,
            "deepseek_key": True, "codex_cli": True,
        }
        with patch("daedalus.doctor.check", return_value=doctor_ready), \
                patch.dict(os.environ, {
                    "OLLAMA_HOST": "http://127.0.0.1:11434",
                }, clear=True):
            availability = core._ikarus_availability("local_only")
        self.assertEqual(availability, {
            "claude_cli": False,
            "ollama": True,
            "deepseek": False,
            "codex_cli": False,
        })

    def test_local_only_refuses_an_untrusted_remote_ollama_endpoint(self):
        from daedalus import core

        doctor_ready = {
            "claude_cli": True, "can_offload_local": True,
            "deepseek_key": True, "codex_cli": True,
        }
        with patch("daedalus.doctor.check", return_value=doctor_ready), \
                patch.dict(os.environ, {
                    "OLLAMA_HOST": "http://203.0.113.9:11434",
                    # Exact endpoint consent admits the egress lane; it does
                    # not turn a remote endpoint into local_only authority.
                    "DAEDALUS_OLLAMA_REMOTE_OK": "http://203.0.113.9:11434",
                }, clear=True):
            availability = core._ikarus_availability("local_only")
        self.assertEqual(availability, {
            "claude_cli": False,
            "ollama": False,
            "deepseek": False,
            "codex_cli": False,
        })

    def test_auto_report_names_external_provider_without_relabelling_lane(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="auto")
            decision = SimpleNamespace(
                provider="deepseek", persona="Dora",
                mode="advisory", reason="mocked external assignment",
            )
            wave_result = SimpleNamespace(mode="sequential", results=[{
                "worker": "Dora", "lane": "deepseek", "mode": "advisory",
                "owner": "docs-dev", "status": "offloaded", "wrote": [],
                "result": {"provider": "deepseek", "draft": "draft-1"},
            }])
            with patch.object(file_bridge, "INBOX", tmp / "inbox"), \
                    patch.object(file_bridge, "ARCHIVE", tmp / "archive"), \
                    patch.object(file_bridge, "record_from_bridge_report", lambda r: None), \
                    patch("daedalus.doctor.check", return_value={
                        "claude_cli": True, "can_offload_local": True,
                        "deepseek_key": True, "codex_cli": False,
                    }), \
                    patch("daedalus.kairos.scheduler.route_and_select",
                          return_value=({"name": "docs-dev"}, decision)), \
                    patch("daedalus.core._head_sha_safe", return_value="a" * 40), \
                    patch("daedalus.build_exec.WaveExecutor.run_wave",
                          return_value=wave_result), \
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError(
                              "successful leased work must not dispatch again")) as ask:
                out_path = file_bridge.process_request(req)
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["bridge_status"], "done")
        self.assertEqual(report["lane"], "auto")
        self.assertEqual(report["requested_lane"], "auto")
        self.assertEqual(report["assigned_providers"], ["deepseek"])
        self.assertEqual(report["actual_providers"], ["deepseek"])

    def test_local_lane_ineligible_refuses_unbrokered_claude_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            req = self._write_request(tmp, lane="local")
            doctor_ready = {"claude_cli": True, "can_offload_local": True, "deepseek_key": False}
            # Route lands on the senior lane -> not a FREE lane -> refuse. The
            # bridge has no authority to turn that bounce into a direct call.
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
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError(
                              "ineligible route must not directly call Claude")) as ask:
                out_path = file_bridge.process_request(req)
            off.assert_not_called()
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["lane"], "local")
        self.assertEqual(report["requested_lane"], "local")
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["actual_providers"], [])
        self.assertIn("broker authorization", report["error"])

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
                    patch("daedalus.claude_bridge.ask_claude",
                          side_effect=AssertionError("local_only must not call Claude")) as ask:
                out_path = file_bridge.process_request(req)
            off.assert_not_called()
            ask.assert_not_called()
            report = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(report["lane"], "local_only")
        self.assertEqual(report["requested_lane"], "local_only")
        self.assertEqual(report["bridge_status"], "failed")
        self.assertIn("external fallback is prohibited", report["error"])


if __name__ == "__main__":
    unittest.main()
