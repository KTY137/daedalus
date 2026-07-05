import unittest

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


if __name__ == "__main__":
    unittest.main()
