from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import control_plane, hierarchy, ikarus_chat, runtime_registry
from daedalus.bootstrap_prompt import claude_bootstrap_prompt
from daedalus.env import env_status, load_env
from daedalus.web_api import _json_safe


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


class InspectorEditRoundTripTest(unittest.TestCase):
    """The webapp inspector's PUT endpoints persist for real (coffee-retro
    trust gap 'inspector edit round-trip'): a patch through the same functions
    web_api routes to (agents_registry.update_role / categories.update) lands
    in the per-repo override, is visible on the next load, and never mutates
    the shipped template/global file."""

    def test_agent_role_patch_persists_per_repo_and_spares_template(self) -> None:
        from daedalus import agents_registry

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
        from daedalus import categories

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
