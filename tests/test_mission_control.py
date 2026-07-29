"""Pin the Mission Control backend contract in daedalus/core.py.

These tests lock the JSON shapes the Mission Control webview depends on:
get_dashboard, model_resources, get_queue, get_squads, get_quality, and the
routing summary. Everything that could touch the network, spawn a
subprocess, or depend on the local machine having Ollama/git installed is
mocked, so the suite is deterministic on any box.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from daedalus import core


class FakeOllamaResponse:
    """Minimal stand-in for the object returned by urllib.request.urlopen."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeOllamaResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _fake_urlopen(*args, **kwargs):
    return FakeOllamaResponse({"models": []})


class MissionControlContractTest(unittest.TestCase):
    """Base case: patches every external effect so no test hits the network,
    spawns a subprocess, or depends on Ollama/git being installed."""

    def setUp(self) -> None:
        patchers = [
            mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen),
            mock.patch("daedalus.core._process_rows", return_value=[]),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)


class DashboardContractTest(MissionControlContractTest):
    def setUp(self) -> None:
        super().setUp()
        # Force a project-free dashboard so it never touches real
        # projects/*.json, a real repo_root, or shells out to git via
        # collect_status()/enforcement_status().
        patcher = mock.patch("daedalus.core.list_projects", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_top_level_keys(self) -> None:
        dashboard = core.get_dashboard(None)
        expected_keys = {
            "ok", "generated_at", "selected_project", "projects", "watcher",
            "models", "provider_health", "squads", "queue", "quality",
            "routing", "enforcement", "metrics", "warnings",
            "claude_crew", "categories",   # webview contract: Squads + Role Wheel tabs
            "governance",                  # webview contract: Promotion panel
        }
        self.assertIsInstance(dashboard, dict)
        missing = expected_keys - dashboard.keys()
        self.assertEqual(missing, set(), f"dashboard missing keys: {missing}")
        # The Role Wheel renders from state.categories -- pin the joined shape.
        cats = dashboard["categories"]
        self.assertIsInstance(cats, list)
        if cats:
            for key in ("id", "name", "icon", "color", "lane", "tier", "agents", "count"):
                self.assertIn(key, cats[0], f"category missing '{key}'")

    def test_field_types(self) -> None:
        dashboard = core.get_dashboard(None)
        self.assertIs(dashboard["ok"], True)
        self.assertIsInstance(dashboard["generated_at"], str)
        self.assertIsInstance(dashboard["projects"], list)
        self.assertIsInstance(dashboard["watcher"], dict)
        self.assertIsInstance(dashboard["models"], dict)
        self.assertIsInstance(dashboard["provider_health"], dict)
        self.assertIsInstance(dashboard["squads"], dict)
        self.assertIsInstance(dashboard["queue"], dict)
        self.assertIsInstance(dashboard["quality"], dict)
        self.assertIsInstance(dashboard["routing"], dict)
        self.assertIsInstance(dashboard["enforcement"], dict)
        self.assertIsInstance(dashboard["metrics"], dict)
        self.assertIsInstance(dashboard["warnings"], list)
        # With no projects configured, selected_project must be None and the
        # projects list empty -- pins the "no project selected" shape too.
        self.assertIsNone(dashboard["selected_project"])
        self.assertEqual(dashboard["projects"], [])

    def test_routing_shape_embedded_in_dashboard(self) -> None:
        dashboard = core.get_dashboard(None)
        routing = dashboard["routing"]
        for key in ("selected_lane", "recommended_lane", "reason"):
            self.assertIn(key, routing)
        self.assertIsInstance(routing["reason"], str)


class ModelResourcesContractTest(MissionControlContractTest):
    def test_keys_and_types(self) -> None:
        result = core.model_resources(None)
        self.assertIsInstance(result["models"], list)
        self.assertIsInstance(result["disk"], dict)
        for key in ("free_gb", "used_gb", "total_gb"):
            self.assertIn(key, result["disk"])
            self.assertIsInstance(result["disk"][key], float)
        self.assertIsInstance(result["total_size_gb"], float)
        self.assertIsInstance(result["safe_parallel_workers_estimate"], int)
        self.assertIn("server_ready", result)
        self.assertIn("ollama_cli_on_path", result)
        self.assertIsInstance(result["suggested"], list)

    def test_server_ready_reflects_mocked_success(self) -> None:
        # Since urlopen is mocked to succeed, server_ready must be True and
        # no network error should be surfaced.
        result = core.model_resources(None)
        self.assertTrue(result["server_ready"])
        self.assertEqual(result["error"], "")

    def test_offline_ollama_is_handled_without_raising(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("refused")):
            result = core.model_resources(None)
        self.assertFalse(result["server_ready"])
        self.assertEqual(result["models"], [])
        self.assertIn("Ollama server is offline or unreachable.", result["warnings"])


class QueueContractTest(MissionControlContractTest):
    def test_keys_and_types(self) -> None:
        result = core.get_queue(None)
        self.assertIsInstance(result["pending"], list)
        self.assertIsInstance(result["reports"], list)
        self.assertIsInstance(result["processed"], list)
        self.assertIn("latest_failed", result)


class SquadsContractTest(MissionControlContractTest):
    def test_keys_and_types(self) -> None:
        result = core.get_squads(None)
        self.assertIn("max_workers", result)
        self.assertIn("default_lane", result)
        self.assertIn("active_agents", result)
        self.assertIn("semi_auto", result)
        self.assertIsInstance(result["squads"], list)
        for squad in result["squads"]:
            self.assertIn("name", squad)
            self.assertIn("agents", squad)
            self.assertIsInstance(squad["agents"], list)

    def test_default_squads_present_with_no_project(self) -> None:
        result = core.get_squads(None)
        squad_names = {squad["name"] for squad in result["squads"]}
        self.assertEqual(squad_names, set(core.DEFAULT_SQUADS.keys()))


class QualityContractTest(MissionControlContractTest):
    def test_invariant_keys(self) -> None:
        result = core.get_quality(None)
        self.assertIs(result["schema_non_empty_summary"], True)
        self.assertIs(result["local_only_never_claude"], True)
        self.assertIs(result["empty_reports_fail"], True)
        self.assertIn("stale_watchers", result)
        self.assertIn("fallback_alarm", result)
        self.assertIn("fallback_rate", result)

    def test_stale_watchers_is_zero_with_no_processes(self) -> None:
        # _process_rows is mocked to [] for every test in this suite, so
        # there can be no stale watchers and no alarm from that source.
        result = core.get_quality(None)
        self.assertEqual(result["stale_watchers"], 0)


class RoutingSummaryContractTest(MissionControlContractTest):
    def test_local_only_default_short_circuits(self) -> None:
        watcher = {"stale_count": 0}
        models = {"server_ready": True}
        quality = {"fallback_alarm": False}
        routing = core.routing_summary(None, watcher, models, quality)
        self.assertEqual(
            set(routing.keys()), {"selected_lane", "recommended_lane", "reason"}
        )
        # team_config(None) has no project, so default_lane falls back to
        # "local_only", which always recommends itself.
        self.assertEqual(routing["selected_lane"], "local_only")
        self.assertEqual(routing["recommended_lane"], "local_only")
        self.assertIsInstance(routing["reason"], str)
        self.assertTrue(routing["reason"])


if __name__ == "__main__":
    unittest.main()
