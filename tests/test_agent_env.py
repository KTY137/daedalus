import unittest
from unittest.mock import patch

from daedalus.claude_bridge import _blocked_report_from_wrapper, _extract_json, build_prompt
from daedalus.file_bridge import _read_request
from daedalus.orchestration.fallback import fallback_decision
from daedalus.memory import MemoryEvent
from daedalus.kairos.orchestrate import _infer_paths
from daedalus.kairos.scheduler import KairosScheduler
from daedalus.foundation.projects import list_projects, load_project, resolve_repo_root
from daedalus.router import route_task
from daedalus.status import _count_open_todos
from daedalus.schemas import validate_report
from daedalus.token_policy import STATIC_PROMPT_PREFIX, trim_paths, trim_text
from daedalus.token_monitor import STATUS_PATH, UsageSample, checkpoint_if_needed, should_checkpoint, summarize_usage


class DaedalusTests(unittest.TestCase):
    def test_routes_gui_paths_to_ui_agent(self):
        agent = route_task("Fix panel layout", ["C:/repo/TCT_app/gui/motor_panel.py"])
        self.assertEqual(agent["name"], "ui-ux-dev")

    def test_routes_driver_paths_to_hardware_agent(self):
        agent = route_task("Fix oscilloscope timeout", ["C:/repo/TCT_app/devices/oscilloscope.py"])
        self.assertEqual(agent["name"], "hardware-dev")

    def test_active_agents_filter_routes_within_enabled_team(self):
        agent = route_task(
            "Fix panel layout",
            ["C:/repo/TCT_app/gui/motor_panel.py"],
            active_agents=["docs-dev", "qa-critic"],
        )
        self.assertEqual(agent["name"], "qa-critic")

    def test_no_active_agents_raises(self):
        with self.assertRaises(RuntimeError):
            route_task("Fix panel layout", active_agents=["missing-agent"])

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

    def test_rejects_empty_summary(self):
        errors = validate_report(
            {
                "status": "needs_review",
                "summary": "",
                "files_changed": [],
                "tests_run": [],
                "risks": [],
                "todos": [],
                "handoff": {},
            }
        )
        self.assertTrue(any("summary" in err for err in errors))

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
        self.assertTrue(prompt.startswith(STATIC_PROMPT_PREFIX))
        self.assertIn("Do not use full chat history", prompt)
        self.assertIn("Relevant paths", prompt)

    def test_converts_claude_limit_to_blocked_report(self):
        report = _blocked_report_from_wrapper(
            '{"is_error":true,"api_error_status":429,"result":"session limit","session_id":"abc"}'
        )
        self.assertIsNotNone(report)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["handoff"]["api_error_status"], 429)
        self.assertTrue(report["handoff"]["fallback"]["continue"])

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

    def test_project_profile_resolves_repo_root(self):
        project = load_project("project_tct")
        self.assertIn("project_tct", project["repo_root"])
        self.assertEqual(resolve_repo_root(project="project_tct"), project["repo_root"])

    def test_project_registry_lists_projects(self):
        self.assertIn("project_tct", list_projects())

    def test_ikarus_loads_project_team_controls(self):
        project_data = {
            "repo_root": "C:/repo",
            "team": {"max_workers": 5, "active_agents": ["docs-dev"]},
            "policy": {},
        }
        with patch("daedalus.foundation.projects.load_project", return_value=project_data):
            ikarus = KairosScheduler(project="demo")
        self.assertEqual(ikarus.max_workers, 5)
        self.assertEqual(ikarus.active_agents, ["docs-dev"])

    def test_done_events_close_matching_todos(self):
        events = [
            {"status": "open", "todos": ["Fix panel"]},
            {"status": "done", "todos": ["fix panel"]},
            {"status": "open", "todos": ["Review diff"]},
        ]
        self.assertEqual(_count_open_todos(events), 1)

    def test_infers_existing_paths(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        paths = _infer_paths("look at README.md", str(repo_root))
        self.assertTrue(any(path.endswith("README.md") for path in paths))

    def test_fallback_allows_codex_when_claude_blocked(self):
        decision = fallback_decision("blocked", risk_level="normal")
        self.assertTrue(decision["continue"])
        self.assertEqual(decision["mode"], "codex_solo")

    def test_fallback_can_block_when_user_requires_claude(self):
        decision = fallback_decision("blocked", user_requires_claude=True)
        self.assertFalse(decision["continue"])

    def test_token_policy_trims_paths_and_text(self):
        self.assertEqual(trim_paths(["a", "a", "b"], limit=2), ["a", "b"])
        self.assertEqual(trim_text("abcdef", 5), "ab...")

    def test_usage_summary_detects_rate_limit(self):
        summary = summarize_usage(
            [
                UsageSample(
                    path="x",
                    timestamp="now",
                    session_id="s",
                    model="m",
                    api_error_status=429,
                    error="rate_limit",
                    text="limit",
                )
            ]
        )
        triggered, reason = should_checkpoint(summary, 50000, 120000)
        self.assertTrue(triggered)
        self.assertIn("limit", reason.lower())

    def test_usage_summary_detects_large_context(self):
        summary = summarize_usage(
            [
                UsageSample(
                    path="x",
                    timestamp="now",
                    session_id="s",
                    model="m",
                    cache_read_input_tokens=140000,
                )
            ]
        )
        triggered, _ = should_checkpoint(summary, 50000, 120000)
        self.assertTrue(triggered)

    def test_checkpoint_status_has_stable_trigger_key(self):
        # Existing local Claude logs are environment-dependent; just verify the
        # status writer uses a key when it runs.
        status = checkpoint_if_needed("C:/definitely-not-a-real-repo", fresh_threshold=1, cached_threshold=1)
        self.assertIn("trigger_key", status)
        self.assertTrue(STATUS_PATH.exists())


if __name__ == "__main__":
    unittest.main()
