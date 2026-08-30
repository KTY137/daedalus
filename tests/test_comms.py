# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the Phase 3 VS Code comms integration:

- `init_repo` drops CLAUDE.md/AGENTS.md into the target repo (never overwrites)
- `.vscode/tasks.json` is valid JSON and contains the bridge watch task
- `docs/COMMS_PROTOCOL.md` documents every request field `_read_request` handles
"""

import inspect
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus.config import TOOL_INSTRUCTION_TEMPLATES, init_repo
from daedalus.enforce import BEGIN, END, enforce_repo
from daedalus.file_bridge import _read_request
from daedalus import core
from daedalus.kairos import control as mission_control
from daedalus.providers import list_providers, provider_health

ROOT = Path(__file__).resolve().parents[1]
TASKS_JSON = ROOT / ".vscode" / "tasks.json"
PROTOCOL_MD = ROOT / "docs" / "COMMS_PROTOCOL.md"
EXTENSION_DIR = ROOT / "vscode-agent-env"
EXTENSION_PACKAGE = EXTENSION_DIR / "package.json"
EXTENSION_MAIN = EXTENSION_DIR / "extension.js"


class InitRepoToolInstructionTests(unittest.TestCase):
    def test_init_repo_copies_tool_instruction_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_repo(tmp)
            for name in TOOL_INSTRUCTION_TEMPLATES:
                target = Path(tmp) / name
                self.assertTrue(target.exists(), f"{name} was not copied into the repo root")
                template = ROOT / "templates" / name
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    template.read_text(encoding="utf-8"),
                    f"{name} does not match its template",
                )

    def test_init_repo_never_overwrites_existing_instruction_files(self):
        sentinel = "# customized locally -- keep me\n"
        with tempfile.TemporaryDirectory() as tmp:
            for name in TOOL_INSTRUCTION_TEMPLATES:
                (Path(tmp) / name).write_text(sentinel, encoding="utf-8")
            init_repo(tmp)
            for name in TOOL_INSTRUCTION_TEMPLATES:
                self.assertEqual(
                    (Path(tmp) / name).read_text(encoding="utf-8"),
                    sentinel,
                    f"{name} was overwritten by init_repo",
                )

    def test_init_repo_return_value_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = init_repo(tmp)
        self.assertTrue(result.endswith("agentenv.json"))

    def test_enforce_repo_appends_managed_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# Custom Claude\n\nKeep this.\n", encoding="utf-8")
            result = enforce_repo(tmp, project="demo")
            self.assertTrue(result["enforced"])
            for name in ("AGENTS.md", "CLAUDE.md"):
                text = (root / name).read_text(encoding="utf-8")
                self.assertIn(BEGIN, text)
                self.assertIn(END, text)
                self.assertIn("--project demo", text)
            self.assertIn("Keep this.", (root / "CLAUDE.md").read_text(encoding="utf-8"))
            self.assertTrue((root / ".agentenv" / "enforcement.json").exists())


class VsCodeTasksTests(unittest.TestCase):
    def test_tasks_json_parses_and_declares_version(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "2.0.0")
        self.assertTrue(data["tasks"])

    def test_watch_task_is_background_and_keyed_on_ready_line(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        watch = next(
            (t for t in data["tasks"] if t.get("label") == "Daedalus Bridge: watch"), None
        )
        self.assertIsNotNone(watch, "missing 'Daedalus Bridge: watch' task")
        self.assertTrue(watch.get("isBackground"), "watch task must be isBackground")
        self.assertIn("daedalus.file_bridge", watch.get("args", []))
        self.assertIn("watch", watch.get("args", []))
        matcher = json.dumps(watch.get("problemMatcher", {}))
        self.assertIn("AGENT_BRIDGE_READY", matcher,
                      "background problemMatcher must key on the AGENT_BRIDGE_READY line")

    def test_expected_task_labels_present(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        labels = {t.get("label") for t in data["tasks"]}
        for expected in (
            "Daedalus Bridge: watch",
            "Daedalus Bridge: watch project",
            "Daedalus: doctor",
            "Daedalus: status",
            "Daedalus: list projects",
            "Daedalus: benchmark (dry)",
            "Daedalus: spawn (prompt for objective)",
            "Daedalus Team: enqueue local-only",
            "Daedalus Team: enqueue auto",
            "Daedalus: run tests",
        ):
            self.assertIn(expected, labels)

    def test_spawn_task_prompts_for_objective(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        spawn = next(
            t for t in data["tasks"] if t.get("label") == "Daedalus: spawn (prompt for objective)"
        )
        self.assertIn("${input:objective}", spawn.get("args", []))
        self.assertIn("${input:project}", spawn.get("args", []))
        input_ids = {i.get("id") for i in data.get("inputs", [])}
        self.assertIn("objective", input_ids)
        self.assertIn("project", input_ids)


class VsCodeExtensionTests(unittest.TestCase):
    def test_extension_manifest_parses_and_contributes_views(self):
        data = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
        self.assertEqual(data["main"], "./extension.js")
        containers = data["contributes"]["viewsContainers"]["activitybar"]
        self.assertTrue(any(c["id"] == "daedalus" for c in containers))
        self.assertTrue((EXTENSION_DIR / "resources" / "daedalus.svg").exists())
        views = data["contributes"]["views"]["daedalus"]
        view_ids = {v["id"] for v in views}
        self.assertIn("daedalusDashboardView", view_ids)
        self.assertIn("daedalusProjects", view_ids)
        self.assertIn("daedalusQueue", view_ids)

    def test_extension_manifest_contributes_expected_commands(self):
        data = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
        commands = {c["command"] for c in data["contributes"]["commands"]}
        for command in (
            "daedalus.refresh",
            "daedalus.startWatcher",
            "daedalus.stopWatcher",
            "daedalus.status",
            "daedalus.enqueueLocalOnly",
            "daedalus.enqueueAuto",
            "daedalus.enqueueClaude",
            "daedalus.reviewDiff",
            "daedalus.spawn",
            "daedalus.openInbox",
            "daedalus.openOutbox",
            "daedalus.openMemory",
            "daedalus.openDashboard",
        ):
            self.assertIn(command, commands)

    def test_extension_main_registers_expected_commands(self):
        src = EXTENSION_MAIN.read_text(encoding="utf-8")
        for command in (
            "daedalus.startWatcher",
            "daedalus.enqueueLocalOnly",
            "daedalus.enqueueAuto",
            "daedalus.reviewDiff",
            "daedalus.spawn",
            "daedalus.openDashboard",
        ):
            self.assertIn(f'registerCommand("{command}"', src)
        self.assertIn('"daedalus.file_bridge"', src)
        self.assertIn('"daedalus.cli"', src)

    def test_extension_dashboard_supports_team_and_environment_controls(self):
        src = EXTENSION_MAIN.read_text(encoding="utf-8")
        for needle in (
            "max_workers",
            "active_agents",
            "default_lane",
            "Claude extension",
            "Codex/OpenAI extension",
            "Ollama",
            "daedalusDashboard",
            "daedalusDashboardView",
            "Enforce Harness",
            "enforceProject",
        ):
            self.assertIn(needle, src)

    def test_extension_dashboard_has_mission_control_tabs_and_handlers(self):
        src = EXTENSION_MAIN.read_text(encoding="utf-8")
        for needle in (
            "Overview",
            "Queue Timeline",
            "Agent Squads",
            "Model Resources",
            "Quality Gates",
            "Command Deck",
            "review-diff",
            "copy",
            "openLatest",
        ):
            self.assertIn(needle, src)

    def test_extension_uses_backend_json_contracts(self):
        src = EXTENSION_MAIN.read_text(encoding="utf-8")
        for needle in (
            '"dashboard", "--json"',
            '"review-diff", "--project"',
            "project_config",
            "provider_health",
            "routing",
        ):
            self.assertIn(needle, src)

    def test_extension_javascript_syntax_when_node_available(self):
        node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
        if not Path(node).exists() and shutil.which("node") is None:
            self.skipTest("node is not installed")
        completed = subprocess.run(
            [node, "--check", str(EXTENSION_MAIN)],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class MissionControlEndpointTests(unittest.TestCase):
    def test_dashboard_json_contract(self):
        with patch("daedalus.core.model_resources", return_value={"ok": True, "project": "project_tct", "warnings": [], "models": [], "server_ready": False}), \
                patch("daedalus.core.watcher_status", return_value={"ok": True, "project": "project_tct", "warnings": [], "running": False, "watchers": [], "stale_count": 0}):
            payload = core.get_dashboard("project_tct")
        for key in ("projects", "queue", "metrics", "models", "squads", "quality", "watcher", "enforcement", "provider_health", "routing"):
            self.assertIn(key, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selected_project"], "project_tct")
        self.assertEqual(payload["project"], "project_tct")

    def test_squads_use_project_team_fields(self):
        data = core.get_squads("project_tct")
        self.assertEqual(data["default_lane"], "local_only")
        self.assertIn("semi_auto", data)
        self.assertTrue(any(s["name"] == "Hardware" for s in data["squads"]))

    def test_watcher_status_marks_repo_root_only_watcher_stale(self):
        row = {"pid": 12, "command": "python -m daedalus.file_bridge watch --repo-root C:\\old"}
        with patch("daedalus.core._process_rows", return_value=[row]):
            status = core.watcher_status("project_tct")
        self.assertEqual(status["stale_count"], 1)
        self.assertTrue(status["warnings"])

    def test_watcher_status_accepts_project_watcher(self):
        row = {"pid": 13, "command": "python -m daedalus.file_bridge watch --project project_tct"}
        with patch("daedalus.core._process_rows", return_value=[row]):
            status = core.watcher_status("project_tct")
        self.assertEqual(status["stale_count"], 0)
        self.assertTrue(status["running"])

    def test_review_diff_queues_local_only_without_running_claude(self):
        with patch("daedalus.core.resolve_repo_root", return_value="C:/repo"), \
                patch("daedalus.file_bridge.enqueue", return_value=Path("outbox/task.json")) as enqueue:
            payload = core.review_diff("project_tct", lane="local_only")
        self.assertEqual(payload["lane"], "local_only")
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["lane"], "local_only")
        self.assertEqual(kwargs["project"], "project_tct")
        self.assertTrue(payload["ok"])

    def test_local_only_bridge_failure_never_calls_claude(self):
        payload = {
            "objective": "review",
            "repo_root": "C:/repo",
            "paths": [],
            "model": "sonnet",
            "lane": "local_only",
            "strategy": "single",
            "project": "project_tct",
        }
        with patch("daedalus.core._try_ikarus", return_value=None), \
                patch("daedalus.core._ask_claude_report") as ask:
            report = core.process_bridge_payload(payload)
        ask.assert_not_called()
        self.assertEqual(report["bridge_status"], "failed")
        self.assertIn("Claude fallback skipped", report["error"])

    def test_models_handles_no_server(self):
        with patch("daedalus.core.urllib.request.urlopen", side_effect=OSError("offline")):
            payload = core.model_resources()
        self.assertFalse(payload["server_ready"])
        self.assertEqual(payload["models"], [])
        self.assertTrue(payload["warnings"])

    def test_models_parses_ollama_tags(self):
        class Resp:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return json.dumps({"models": [{"name": "qwen2.5-coder:7b", "size": 4683087561, "details": {"parameter_size": "7.6B", "quantization_level": "Q4_K_M"}, "capabilities": ["completion", "tools"]}]}).encode("utf-8")
        with patch("daedalus.core.urllib.request.urlopen", return_value=Resp()):
            payload = core.model_resources()
        self.assertTrue(payload["server_ready"])
        self.assertEqual(payload["models"][0]["name"], "qwen2.5-coder:7b")
        self.assertAlmostEqual(payload["models"][0]["size_gb"], 4.36)

    def test_provider_registry_includes_future_placeholders(self):
        names = {row["name"] for row in list_providers()}
        for name in ("ollama", "claude_cli", "deepseek", "openai_api", "anthropic_api", "codex_cli"):
            self.assertIn(name, names)
        rows = provider_health()
        openai = next(row for row in rows if row["name"] == "openai_api")
        self.assertFalse(openai["implemented"])
        self.assertFalse(openai["available"])


class ProtocolDocTests(unittest.TestCase):
    def test_protocol_doc_mentions_every_read_request_field(self):
        src = inspect.getsource(_read_request)
        fields = set(re.findall(r'payload(?:\.setdefault\(|\.get\(|\[)\s*"([a-z_]+)"', src))
        fields |= set(re.findall(r'"([a-z_]+)"\s+not in payload', src))
        self.assertTrue(fields, "could not derive any request fields from _read_request")
        doc = PROTOCOL_MD.read_text(encoding="utf-8")
        for field in sorted(fields):
            self.assertIn(f"`{field}`", doc,
                          f"COMMS_PROTOCOL.md does not document request field '{field}'")

    def test_protocol_doc_covers_lanes_and_flow(self):
        doc = PROTOCOL_MD.read_text(encoding="utf-8")
        for needle in (
            "`auto`", "`local`", "`claude`",
            "outbox", "inbox", "runs/processed",
            "bridge_status", "agent_report_v1", "AGENT_BRIDGE_READY",
        ):
            self.assertIn(needle, doc)


if __name__ == "__main__":
    unittest.main()
