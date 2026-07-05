import unittest

from agent_env.claude_bridge import _blocked_report_from_wrapper, _extract_json, build_prompt
from agent_env.file_bridge import _read_request
from agent_env.memory import MemoryEvent
from agent_env.router import route_task
from agent_env.schemas import validate_report


class AgentEnvTests(unittest.TestCase):
    def test_routes_gui_paths_to_ui_agent(self):
        agent = route_task("Fix panel layout", ["C:/repo/TCT_app/gui/motor_panel.py"])
        self.assertEqual(agent["name"], "ui-ux-dev")

    def test_routes_driver_paths_to_hardware_agent(self):
        agent = route_task("Fix oscilloscope timeout", ["C:/repo/TCT_app/devices/oscilloscope.py"])
        self.assertEqual(agent["name"], "hardware-dev")

    def test_validates_report_schema(self):
        errors = validate_report(
            {
                "status": "done",
                "summary": "Updated the panel.",
                "files_changed": ["TCT_app/gui/motor_panel.py"],
                "tests_run": ["python -m pytest tests -q"],
                "risks": [],
                "todos": [],
                "handoff": {},
            }
        )
        self.assertEqual(errors, [])

    def test_rejects_chatty_report(self):
        errors = validate_report({"status": "done", "summary": "x" * 700})
        self.assertTrue(errors)

    def test_extracts_result_wrapped_json(self):
        report = _extract_json(
            '{"result":"{\\"status\\":\\"done\\",\\"summary\\":\\"ok\\",'
            '\\"files_changed\\":[],\\"tests_run\\":[],\\"risks\\":[],'
            '\\"todos\\":[],\\"handoff\\":{}}"}'
        )
        self.assertEqual(report["status"], "done")

    def test_prompt_contains_pruned_context(self):
        agent = route_task("Fix panel layout", ["C:/repo/TCT_app/gui/motor_panel.py"])
        prompt = build_prompt("Fix panel layout", "C:/repo", ["C:/repo/TCT_app/gui/motor_panel.py"], agent)
        self.assertIn("Do not use full chat history", prompt)
        self.assertIn("Relevant paths", prompt)

    def test_converts_claude_limit_to_blocked_report(self):
        report = _blocked_report_from_wrapper(
            '{"is_error":true,"api_error_status":429,"result":"session limit","session_id":"abc"}'
        )
        self.assertIsNotNone(report)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["handoff"]["api_error_status"], 429)

    def test_request_uses_default_repo_root(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "request.json"
            path.write_text('{"objective":"review"}', encoding="utf-8")
            request = _read_request(path, "C:/repo")
        self.assertEqual(request["repo_root"], "C:/repo")
        self.assertEqual(request["paths"], [])

    def test_memory_event_record_shape(self):
        record = MemoryEvent(kind="manual", summary="recover", todos=["fix todo"]).to_record()
        self.assertEqual(record["kind"], "manual")
        self.assertEqual(record["todos"], ["fix todo"])
        self.assertIn("time", record)


if __name__ == "__main__":
    unittest.main()
