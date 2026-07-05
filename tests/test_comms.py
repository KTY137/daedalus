"""Offline tests for the Phase 3 VS Code comms integration:

- `init_repo` drops CLAUDE.md/AGENTS.md into the target repo (never overwrites)
- `.vscode/tasks.json` is valid JSON and contains the bridge watch task
- `docs/COMMS_PROTOCOL.md` documents every request field `_read_request` handles
"""

import inspect
import json
import re
import tempfile
import unittest
from pathlib import Path

from agent_env.config import TOOL_INSTRUCTION_TEMPLATES, init_repo
from agent_env.file_bridge import _read_request

ROOT = Path(__file__).resolve().parents[1]
TASKS_JSON = ROOT / ".vscode" / "tasks.json"
PROTOCOL_MD = ROOT / "docs" / "COMMS_PROTOCOL.md"


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


class VsCodeTasksTests(unittest.TestCase):
    def test_tasks_json_parses_and_declares_version(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "2.0.0")
        self.assertTrue(data["tasks"])

    def test_watch_task_is_background_and_keyed_on_ready_line(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        watch = next(
            (t for t in data["tasks"] if t.get("label") == "Agent Bridge: watch"), None
        )
        self.assertIsNotNone(watch, "missing 'Agent Bridge: watch' task")
        self.assertTrue(watch.get("isBackground"), "watch task must be isBackground")
        self.assertIn("agent_env.file_bridge", watch.get("args", []))
        self.assertIn("watch", watch.get("args", []))
        matcher = json.dumps(watch.get("problemMatcher", {}))
        self.assertIn("AGENT_BRIDGE_READY", matcher,
                      "background problemMatcher must key on the AGENT_BRIDGE_READY line")

    def test_expected_task_labels_present(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        labels = {t.get("label") for t in data["tasks"]}
        for expected in (
            "Agent Bridge: watch",
            "Agent Env: doctor",
            "Agent Env: status",
            "Agent Env: benchmark (dry)",
            "Agent Env: spawn (prompt for objective)",
            "Agent Env: run tests",
        ):
            self.assertIn(expected, labels)

    def test_spawn_task_prompts_for_objective(self):
        data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
        spawn = next(
            t for t in data["tasks"] if t.get("label") == "Agent Env: spawn (prompt for objective)"
        )
        self.assertIn("${input:objective}", spawn.get("args", []))
        input_ids = {i.get("id") for i in data.get("inputs", [])}
        self.assertIn("objective", input_ids)


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
