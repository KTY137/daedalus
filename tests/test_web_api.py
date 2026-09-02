from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from daedalus import file_bridge
from daedalus.interfaces.http import web_api
from daedalus.orchestration import control_plane, conversation as conversation_mod, hierarchy, ikarus_chat, runtime_registry
from daedalus.interfaces.http.bootstrap_prompt import claude_bootstrap_prompt
from daedalus.foundation.env import env_status, load_env
from daedalus.interfaces.http.web_api import _json_safe


class HostCapabilitiesContractTest(unittest.TestCase):
    def test_plain_web_host_does_not_claim_desktop_affordances(self) -> None:
        caps = web_api._host_capabilities()
        self.assertEqual(caps["host_mode"], "browser")
        self.assertFalse(caps["can_manage_openvscode"])
        self.assertFalse(caps["can_open_external_editor"])
        self.assertFalse(caps["can_send_editor_commands"])
        self.assertTrue(caps["editor_commands_require_session"])
        self.assertTrue(caps["measured_at"])

    def test_managed_host_projects_only_measured_ide_affordances(self) -> None:
        caps = web_api._host_capabilities("desktop", {
            "services": {"ide": {
                "available": True,
                "reachable": True,
                "ui_url": "http://127.0.0.1:3000/",
            }}
        })
        self.assertEqual(caps["host_mode"], "desktop")
        self.assertTrue(caps["can_manage_openvscode"])
        self.assertTrue(caps["can_open_external_editor"])
        # Route availability alone is not evidence of a nonce-bound session.
        self.assertFalse(caps["can_send_editor_commands"])


class EnvRedactionTest(unittest.TestCase):
    def test_load_env_redacts_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "DEEPSEEK_API_KEY=super-secret\n"
                "OLLAMA_HOST=http://127.0.0.1:11434\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                status = load_env(env_file)

        self.assertTrue(status["secrets"]["DEEPSEEK_API_KEY"]["configured"])
        encoded = json.dumps(status)
        self.assertNotIn("super-secret", encoded)
        self.assertIn("OLLAMA_HOST", status["public"])


class HierarchyContractTest(unittest.TestCase):
    def test_capabilities_shape(self) -> None:
        payload = hierarchy.capabilities()
        self.assertTrue(payload["ok"])
        ids = {c["id"] for c in payload["capabilities"]}
        self.assertIn("ollama_write", ids)
        self.assertIn("claude_escalate", ids)
        self.assertIn("deepseek_advisory", ids)

    def test_hierarchy_has_nodes_edges_and_policy_flags(self) -> None:
        payload = hierarchy.hierarchy("project_tct")
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["nodes"], list)
        self.assertIsInstance(payload["edges"], list)
        self.assertIsInstance(payload["health"], dict)
        self.assertIsInstance(payload["policy_flags"], dict)
        node_types = {n["type"] for n in payload["nodes"]}
        self.assertIn("project", node_types)
        self.assertIn("agent", node_types)
        self.assertIn("category", node_types)
        self.assertIn("capability", node_types)
        edge_types = {e["type"] for e in payload["edges"]}
        self.assertIn("can_use", edge_types)


class ControlPlaneContractTest(unittest.TestCase):
    def test_unified_profiles_include_claude_and_codex_surfaces(self) -> None:
        # project_tct is an operator catalogue entry whose absolute root may
        # live on another machine. Exercise the surface contract against this
        # checkout instead of making AGENTS.md existence depend on that host.
        with mock.patch(
            "daedalus.orchestration.control_plane._repo_root",
            return_value=Path(__file__).resolve().parents[1],
        ):
            payload = control_plane.unified_profiles("project_tct")
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["profiles"], list)
        self.assertIn("claude", payload)
        self.assertIn("codex", payload)
        self.assertIn("runtimes", payload)
        statuses = {p["sync_status"] for p in payload["profiles"]}
        self.assertTrue(statuses & {"unified", "daedalus_only", "claude_only", "drift"})
        self.assertTrue(payload["codex"]["agents_md"]["exists"])

    def test_autonomy_resolution_is_most_restrictive(self) -> None:
        project_data = {
            "team": {
                "autonomy": {
                    "default": "autonomous",
                    "agents": {"qa-critic": "semi_auto"},
                    "capabilities": {"file_write": "manual"},
                }
            }
        }
        result = control_plane.resolve_autonomy(project_data, "qa-critic", "file_write")
        self.assertEqual(result["mode"], "manual")
        self.assertTrue(result["requires_confirmation"])

    def test_ikarus_draft_contains_subagents_and_does_not_apply(self) -> None:
        payload = ikarus_chat.chat("project_tct", "Build a full app project network", apply=False)
        self.assertTrue(payload["ok"])
        self.assertIn("draft", payload)
        self.assertGreaterEqual(len(payload["draft"]["roles"]), 1)
        self.assertEqual(len(payload["draft"]["roles"]), len(payload["draft"]["subagents"]))
        self.assertNotIn("applied", payload)


class WebApiSerializationTest(unittest.TestCase):
    def test_json_safe_never_emits_bytes_repr(self) -> None:
        payload = {"ok": True, "path": Path("x/y")}
        data = _json_safe(payload).decode("utf-8")
        self.assertIn('"path"', data)
        self.assertNotIn("Path(", data)


class TaskOutcomeTruthTest(unittest.TestCase):
    @staticmethod
    def _report(assignment: dict) -> dict:
        return {
            "bridge_status": "done",
            "lane": "auto",
            "requested_lane": "auto",
            "actual_providers": ["deepseek"],
            "request": {"lane": "auto", "project": "p", "objective": "work"},
            "result": {"assignments": [assignment]},
        }

    def test_advisory_result_is_not_applied_even_when_draft_persistence_failed(self) -> None:
        for draft in ("draft-1", None):
            with self.subTest(draft=draft):
                report = self._report({
                    "status": "offloaded", "mode": "advisory", "wrote": [],
                    "owner": "docs-dev",
                    "result": {"draft": draft, "verify": {"ok": True}},
                })
                applied, reason = web_api._derive_applied(report)
                self.assertFalse(applied)
                self.assertIn("advisory", reason)
                if draft is None:
                    self.assertIn("no persisted draft", reason)

    def test_gated_candidate_is_held_not_applied_and_summary_says_so(self) -> None:
        report = self._report({
            "status": "gated_held", "mode": "write", "wrote": [],
            "owner": "core-dev", "result": {},
        })
        applied, reason = web_api._derive_applied(report)
        self.assertFalse(applied)
        self.assertIn("held", reason)

        status, summary = web_api._task_report_fields(report)
        self.assertEqual(status, "gated_held")
        self.assertIn("not applied", summary)

        reported_status, reported_summary = file_bridge._reported_result(report)
        self.assertEqual(reported_status, "gated_held")
        self.assertIn("not applied", reported_summary)
        _, projected_summary, detail = file_bridge._conversation_report_fields(
            "task-1", report)
        self.assertFalse(detail["applied"])
        self.assertIn("not applied", projected_summary)

    def test_write_needs_disk_diff_and_passed_gate_before_applied_true(self) -> None:
        assignment = {
            "status": "offloaded", "mode": "write", "wrote": ["x.py"],
            "owner": "core-dev", "result": {"verify": {"ok": True}},
        }
        applied, reason = web_api._derive_applied(self._report(assignment))
        self.assertTrue(applied)
        self.assertIn("verification gate passed", reason)

        assignment["result"] = {}
        applied, reason = web_api._derive_applied(self._report(assignment))
        self.assertIsNone(applied)
        self.assertIn("passed verification gate", reason)

    def test_failed_verify_with_unreverted_paths_is_loudly_unknown(self) -> None:
        report = self._report({
            "status": "write_gate_failed", "mode": "write",
            "owner": "core-dev",
            "provider_receipt": {
                "action": "escalated_after_verify_fail",
                "wrote": ["x.py"], "verify": {"ok": False},
            },
        })
        report["bridge_status"] = "failed"

        applied, reason = web_api._derive_applied(report)
        self.assertIsNone(applied)
        self.assertIn("unreverted", reason)
        self.assertIn("manual cleanup", reason)

        outcome, summary, detail = file_bridge._conversation_report_fields(
            "task-dirty", report)
        self.assertEqual(outcome, conversation_mod.DEGRADED)
        self.assertIsNone(detail["applied"])
        self.assertIn("manual cleanup", detail["application_reason"])
        self.assertIn("manual cleanup", summary)

    def test_failed_verify_with_measured_empty_writes_is_not_applied(self) -> None:
        report = self._report({
            "status": "write_gate_failed", "mode": "write",
            "owner": "core-dev",
            "provider_receipt": {
                "action": "escalated_after_verify_fail", "wrote": [],
            },
        })
        report["bridge_status"] = "failed"

        applied, reason = web_api._derive_applied(report)
        self.assertFalse(applied)
        self.assertIn("no unreverted", reason)

    def test_outer_empty_write_default_cannot_hide_dirty_receipt(self) -> None:
        report = self._report({
            "status": "write_gate_failed", "mode": "write", "wrote": [],
            "owner": "core-dev",
            "provider_receipt": {
                "action": "escalated_after_verify_fail", "wrote": ["x.py"],
            },
        })
        report["bridge_status"] = "failed"

        applied, reason = web_api._derive_applied(report)
        self.assertIsNone(applied)
        self.assertIn("unreverted", reason)

    def test_dirty_failure_receipt_outranks_contradictory_held_status(self) -> None:
        report = self._report({
            "status": "gated_held", "mode": "write", "wrote": [],
            "owner": "core-dev",
            "provider_receipt": {
                "action": "escalated_after_verify_fail", "wrote": ["x.py"],
            },
        })

        applied, reason = web_api._derive_applied(report)
        self.assertIsNone(applied)
        self.assertIn("unreverted", reason)
        self.assertIn("manual cleanup", reason)

    def test_conflicting_verify_evidence_cannot_claim_applied(self) -> None:
        report = self._report({
            "status": "offloaded", "mode": "write", "wrote": ["x.py"],
            "owner": "core-dev", "verify": {"ok": True},
            "result": {"verify": {"ok": False}},
        })

        applied, reason = web_api._derive_applied(report)
        self.assertIsNone(applied)
        self.assertIn("passed verification gate", reason)

    def test_mixed_applied_and_unapplied_assignments_are_partial_unknown(self) -> None:
        report = self._report({
            "status": "offloaded", "mode": "write", "wrote": ["x.py"],
            "owner": "core-dev", "result": {"verify": {"ok": True}},
        })
        report["result"]["assignments"].append({
            "status": "gated_held", "mode": "write", "wrote": [],
            "owner": "ui-dev", "result": {},
        })

        applied, reason = web_api._derive_applied(report)
        self.assertIsNone(applied)
        self.assertIn("verification gate passed", reason)
        self.assertIn("held", reason)

    def test_terminal_task_snapshot_keeps_requested_lane_and_actual_provider(self) -> None:
        report = self._report({
            "status": "offloaded", "mode": "advisory", "wrote": [],
            "owner": "docs-dev", "result": {"draft": "draft-1"},
        })
        progress = SimpleNamespace(
            terminal=True,
            stalled=False,
            to_dict=lambda: {
                "observed_at": "2026-08-31T00:00:00+00:00", "age_s": 0.0,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            (inbox / "task-1.report.json").write_text(
                json.dumps(report), encoding="utf-8")
            with mock.patch.object(file_bridge, "INBOX", inbox), mock.patch(
                "daedalus.progress_sources.snapshot_from_bridge",
                return_value=progress,
            ):
                snapshot = web_api._task_snapshot("task-1")
        self.assertEqual(snapshot["lane"], "auto")
        self.assertEqual(snapshot["requested_lane"], "auto")
        self.assertEqual(snapshot["actual_providers"], ["deepseek"])


class RuntimeRegistryTest(unittest.TestCase):
    def test_runtime_registry_has_cli_and_api_slots(self) -> None:
        payload = runtime_registry.all_status()
        ids = {row["id"] for row in payload["runtimes"]}
        self.assertIn("claude_code_cli", ids)
        self.assertIn("codex_cli", ids)
        self.assertIn("ollama_http", ids)
        self.assertIn("anthropic_api", ids)
        self.assertIn("openai_api", ids)

    def test_runtime_status_does_not_leak_api_keys(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret-test"}, clear=False):
            payload = runtime_registry.runtime_status("openai_api")
        encoded = json.dumps(payload)
        self.assertTrue(payload["available"])
        self.assertNotIn("sk-secret-test", encoded)

    def test_uncached_status_carries_no_measured_at(self) -> None:
        # The direct path must be byte-identical to before the cache landed:
        # measured_at appears only when a caller opts into the cache.
        rows = runtime_registry.all_status()["runtimes"]
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("measured_at", row)

    def test_cached_status_stamps_when_it_measured_and_serves_the_cache(self) -> None:
        # Owner decision 2026-08-27: cache the slow probe, but every cached row
        # says WHEN it was probed so a stale "erreichbar" cannot lie. A probe
        # runs at most once here; the second call is served from the cache and
        # ages the reading rather than re-launching a CLI.
        probes: dict[str, int] = {}

        def _counting(runtime_id: str) -> dict:
            probes[runtime_id] = probes.get(runtime_id, 0) + 1
            return {"id": runtime_id, "available": True, "auth_status": "cli_detected"}

        runtime_registry.reset_status_cache()
        try:
            with mock.patch.object(runtime_registry, "runtime_status", _counting):
                first = runtime_registry.all_status(use_cache=True)["runtimes"]
                second = runtime_registry.all_status(use_cache=True)["runtimes"]
        finally:
            runtime_registry.reset_status_cache()

        self.assertTrue(all(count == 1 for count in probes.values()), probes)
        for row in first:
            self.assertIn("measured_at", row)
            self.assertEqual(row["measured_age_s"], 0.0)
        for row in second:
            self.assertIn("measured_at", row)
            self.assertGreaterEqual(row["measured_age_s"], 0.0)

    def test_cache_expiry_reprobes(self) -> None:
        # A zero TTL is always expired, so every call re-probes -- the freshness
        # bound is real, not decorative.
        probes = {"n": 0}

        def _counting(runtime_id: str) -> dict:
            probes["n"] += 1
            return {"id": runtime_id, "available": True}

        runtime_registry.reset_status_cache()
        try:
            with mock.patch.object(runtime_registry, "runtime_status", _counting):
                runtime_registry.cached_runtime_status("claude_code_cli", ttl_s=0.0)
                runtime_registry.cached_runtime_status("claude_code_cli", ttl_s=0.0)
        finally:
            runtime_registry.reset_status_cache()
        self.assertEqual(probes["n"], 2)


class InspectorEditRoundTripTest(unittest.TestCase):
    """The webapp inspector's PUT endpoints persist for real (coffee-retro
    trust gap 'inspector edit round-trip'): a patch through the same functions
    web_api routes to (agents_registry.update_role / categories.update) lands
    in the per-repo override, is visible on the next load, and never mutates
    the shipped template/global file."""

    def test_agent_role_patch_persists_per_repo_and_spares_template(self) -> None:
        from daedalus.orchestration import agents_registry

        template = Path("templates/agents/generalist-dev.json")
        before = template.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            current = agents_registry.get_role("generalist-dev", tmp)
            self.assertIsNotNone(current)
            new_tier = "haiku" if current.get("model_tier") != "haiku" else "sonnet"

            path = agents_registry.update_role("generalist-dev", {"model_tier": new_tier}, tmp)
            self.assertTrue(str(path).startswith(str(Path(tmp).resolve())) or str(path).startswith(tmp),
                            f"override must live under the repo, got {path}")

            reloaded = agents_registry.get_role("generalist-dev", tmp)
            self.assertEqual(reloaded["model_tier"], new_tier)
        self.assertEqual(template.read_bytes(), before, "template must never be mutated")

    def test_category_patch_persists_per_repo_and_spares_global(self) -> None:
        from daedalus.orchestration import categories

        global_file = Path("agents/categories.json")
        before = global_file.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            cat_id = categories.load()[0]["id"]

            path = categories.update(cat_id, {"name": "Round Trip Check"}, tmp)
            self.assertEqual(path, Path(tmp) / ".agentenv" / "categories.json")

            reloaded = categories.get(cat_id, tmp)
            self.assertEqual(reloaded["name"], "Round Trip Check")
            # without the repo_root the patch must NOT be visible
            self.assertNotEqual(categories.get(cat_id)["name"], "Round Trip Check")
        self.assertEqual(global_file.read_bytes(), before, "global file must never be mutated")


class BootstrapPromptTest(unittest.TestCase):
    def test_claude_bootstrap_prompt_mentions_harness_and_project(self) -> None:
        payload = claude_bootstrap_prompt("project_tct")
        self.assertIn("project_tct", payload["prompt"])
        self.assertIn("daedalus.cli spawn", payload["prompt"])
        self.assertIn("Ollama", payload["prompt"])
        self.assertIn("outbox", payload["prompt"])


class LatentSearchRouteTest(unittest.TestCase):
    """Regression: the /api/latent/search route literal was once written with
    backslashes ("\\api\\latent\\search") and could never match; GET dispatch
    must reach the handler body instead of falling through to static serving."""

    @staticmethod
    def _get(path: str) -> dict:
        from daedalus.interfaces.http.web_api import DaedalusHandler

        handler = object.__new__(DaedalusHandler)
        handler.path = path
        captured: dict = {}

        def send_json(payload, status: int = 200) -> None:
            captured["payload"] = payload
            captured["status"] = status

        handler._send_json = send_json
        handler._send_static = lambda p: captured.setdefault("static", p)
        handler._handle_get()
        return captured

    def test_latent_search_route_dispatches(self) -> None:
        # No query string: the handler body answers 400 "q is required",
        # which proves the route matched (an unmatched path serves static).
        captured = self._get("/api/latent/search")
        self.assertNotIn("static", captured)
        self.assertEqual(captured["status"], 400)
        self.assertEqual(captured["payload"]["error"], "q is required")

    def test_all_route_literals_use_forward_slashes(self) -> None:
        import inspect
        import re

        from daedalus.interfaces.http import effects, read

        source = inspect.getsource(read) + inspect.getsource(effects)
        routes = re.findall(r'path == "([^"]*)"', source)
        self.assertTrue(routes, "expected route literals in HTTP route owners")
        for route in routes:
            self.assertTrue(
                route.startswith("/") and "\\" not in route,
                f"route literal is not a forward-slash path: {route!r}",
            )
