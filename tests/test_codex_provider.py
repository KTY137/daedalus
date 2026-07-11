"""Offline tests for the Codex CLI provider, its lane wiring, and doctor.

No test here invokes the real ``codex`` binary, touches the network, or needs
``codex login``: every subprocess call is mocked. The egress-policy tests prove
that a policy-denied path is refused BEFORE any subprocess/provider dispatch.
"""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from daedalus import core, metrics
from daedalus.offload import offload
from daedalus.projects import load_project
from daedalus.provider_router import route_and_select
from daedalus.providers import get_provider
from daedalus.providers.codex_cli import CodexCLIProvider
from daedalus.sensitivity import load_policy

AGENT = {"name": "docs-dev", "call_name": "Sam", "model_tier": "sonnet"}

VALID_REPORT = {
    "status": "done",
    "summary": "did the thing",
    "files_changed": ["docs/notes.md"],
    "tests_run": [],
    "risks": [],
    "todos": [],
    "handoff": {},
}


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["codex"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _write_last_message(payload_text):
    """Side effect for the mocked subprocess.run: emulate `codex exec` writing
    its final agent message to the --output-last-message file."""
    def _side_effect(cmd, **kwargs):
        out_path = cmd[cmd.index("--output-last-message") + 1]
        Path(out_path).write_text(payload_text, encoding="utf-8")
        return _completed(0)
    return _side_effect


class CodexProviderRunTests(unittest.TestCase):
    def setUp(self):
        self.provider = CodexCLIProvider()
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, **overrides):
        kwargs = dict(objective="Draft release notes", repo_root=self.repo,
                      paths=["docs/notes.md"], agent=AGENT, timeout_s=5)
        kwargs.update(overrides)
        return self.provider.run(**kwargs)

    def test_success_path_returns_coerced_report(self):
        # pin the .CMD-shim resolution so the asserted argv is deterministic
        with patch("daedalus.providers.codex_cli.shutil.which",
                   return_value="C:/npm/codex.CMD"), \
                patch("daedalus.providers.codex_cli.subprocess.run",
                      side_effect=_write_last_message(json.dumps(VALID_REPORT))) as run:
            out = self._run(writable=True)
        self.assertEqual(out["provider"], "codex_cli")
        self.assertEqual(out["agent"], "docs-dev")
        self.assertEqual(out["report"]["status"], "done")
        self.assertEqual(out["report"]["files_changed"], ["docs/notes.md"])
        cmd = run.call_args.args[0]
        # invoked via the RESOLVED path (bare "codex" cannot spawn on Windows)
        self.assertEqual(cmd[:2], ["C:/npm/codex.CMD", "exec"])
        self.assertIn("--cd", cmd)
        self.assertEqual(cmd[cmd.index("--cd") + 1], self.repo)
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--output-schema", cmd)
        self.assertEqual(run.call_args.kwargs.get("cwd"), self.repo)
        self.assertEqual(run.call_args.kwargs.get("timeout"), 5)

    def test_not_writable_uses_read_only_sandbox(self):
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   side_effect=_write_last_message(json.dumps(VALID_REPORT))) as run:
            self._run()  # writable defaults to False (fail-closed)
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "read-only")

    def test_json_wrapped_in_prose_is_still_extracted(self):
        raw = "Here is my report:\n" + json.dumps(VALID_REPORT) + "\nDone."
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   side_effect=_write_last_message(raw)):
            out = self._run()
        self.assertEqual(out["report"]["status"], "done")

    def test_timeout_returns_blocked_report(self):
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=5)):
            out = self._run(writable=True)
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("timed out", out["report"]["summary"])
        self.assertTrue(out["report"]["handoff"].get("disk_may_be_dirty"))
        self.assertTrue(out["report"]["risks"])  # partial-edit warning in write mode

    def test_nonzero_exit_returns_blocked_report(self):
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   return_value=_completed(2, stderr="auth required")):
            out = self._run()
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("exit code 2", out["report"]["summary"])
        self.assertEqual(out["report"]["handoff"].get("exit_code"), 2)

    def test_malformed_output_returns_blocked_report(self):
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   side_effect=_write_last_message("totally not json")):
            out = self._run()
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("malformed", out["report"]["summary"])

    def test_missing_last_message_returns_blocked_report(self):
        # exit 0 but codex never wrote the --output-last-message file
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   return_value=_completed(0)):
            out = self._run()
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("no final message", out["report"]["summary"])

    def test_launch_oserror_returns_blocked_report(self):
        with patch("daedalus.providers.codex_cli.subprocess.run",
                   side_effect=OSError("not found")):
            out = self._run()
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("could not be launched", out["report"]["summary"])


class CodexEgressGateTests(unittest.TestCase):
    """NON-NEGOTIABLE: a policy-denied path never reaches the codex binary."""

    def setUp(self):
        self.provider = CodexCLIProvider()
        self.pol = load_policy(load_project("project_tct"))

    def _gate(self, paths, objective="Draft docstrings"):
        with patch("daedalus.providers.codex_cli.subprocess.run") as run:
            out = self.provider.run(objective=objective, repo_root=".",
                                    paths=paths, agent=AGENT, policy=self.pol,
                                    writable=True)
        run.assert_not_called()
        return out

    def test_device_driver_path_is_refused_before_subprocess(self):
        out = self._gate(["TCT_app/devices/motor_grbl.py"])
        self.assertEqual(out["report"]["status"], "blocked")
        self.assertIn("sensitive", out["report"]["summary"])
        self.assertIn("TCT_app/devices/motor_grbl.py",
                      out["report"]["handoff"]["offending"])

    def test_devices_yaml_and_vendor_paths_are_refused(self):
        for path in ("configs/devices.yaml", "reference/manual.pdf",
                     "lab_assets/photo.png", "vendor/e4control/device.py"):
            out = self._gate([path])
            self.assertEqual(out["report"]["status"], "blocked", path)

    def test_sensitive_objective_content_is_refused(self):
        out = self._gate(["docs/notes.md"],
                         objective="Document the ISEG ramp commands")
        self.assertEqual(out["report"]["status"], "blocked")

    def test_default_policy_is_fail_closed_for_unlisted_paths(self):
        with patch("daedalus.providers.codex_cli.subprocess.run") as run:
            out = self.provider.run(objective="Tweak the widget",
                                    repo_root=".", paths=["src/widget.py"],
                                    agent=AGENT, policy=None)  # default-deny
        run.assert_not_called()
        self.assertEqual(out["report"]["status"], "blocked")


class CodexRoutingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    # NB: paths must be on the egress allow-list (e.g. docs/) -- under the
    # default-deny policy any unlisted path is sensitive and stays local.
    def test_codex_is_fallback_between_bench_and_claude(self):
        avail = {"claude_cli": True, "ollama": False, "deepseek": False, "codex_cli": True}
        _, decision = route_and_select("Draft docstrings for the docs helper",
                                       ["docs/notes.md"], avail)
        self.assertEqual(decision.provider, "codex_cli")

    def test_local_bench_preferred_over_codex_when_up(self):
        avail = {"claude_cli": True, "ollama": True, "deepseek": False, "codex_cli": True}
        _, decision = route_and_select("Draft docstrings for the docs helper",
                                       ["docs/notes.md"], avail)
        self.assertEqual(decision.provider, "ollama")

    def test_unlisted_path_is_sensitive_and_never_codex(self):
        # default-deny: a path not on the allow-list must stay on-machine even
        # when codex is the only bench available -> degrade to Claude.
        avail = {"claude_cli": True, "ollama": False, "deepseek": False, "codex_cli": True}
        _, decision = route_and_select("Draft docstrings for the gui panel",
                                       ["TCT_app/gui/x.py"], avail)
        self.assertEqual(decision.provider, "claude_cli")
        self.assertTrue(decision.sensitive)

    def test_sensitive_task_never_routes_to_codex(self):
        pol = load_policy(load_project("project_tct"))
        avail = {"claude_cli": True, "ollama": True, "deepseek": True, "codex_cli": True}
        _, decision = route_and_select("Draft a summary of the device config",
                                       ["configs/devices.yaml"], avail, pol)
        self.assertEqual(decision.provider, "ollama")
        # ... and with the bench down it degrades to Claude, still never external.
        avail["ollama"] = False
        _, decision = route_and_select("Draft a summary of the device config",
                                       ["configs/devices.yaml"], avail, pol)
        self.assertEqual(decision.provider, "claude_cli")

    def test_offload_dry_run_dispatches_codex_lane(self):
        avail = {"claude_cli": True, "ollama": False, "deepseek": False, "codex_cli": True}
        r = offload("Draft docstrings for the docs helper", ".",
                    paths=["docs/notes.md"], availability=avail)
        self.assertEqual(r["provider"], "codex_cli")
        self.assertEqual(r["action"], "would_offload")
        self.assertTrue(r["eligible"])

    def test_get_provider_returns_codex(self):
        self.assertIsInstance(get_provider("codex_cli"), CodexCLIProvider)


class CodexLaneBridgeTests(unittest.TestCase):
    def test_known_lanes_include_codex(self):
        self.assertIn("codex", core.KNOWN_LANES)

    def _payload(self, **overrides):
        payload = {"objective": "Draft release notes", "repo_root": ".",
                   "paths": [], "model": "sonnet", "lane": "codex",
                   "strategy": "single"}
        payload.update(overrides)
        return payload

    def test_codex_lane_dispatches_to_provider(self):
        out = {"provider": "codex_cli", "persona": "Cody", "agent": "docs-dev",
               "report": VALID_REPORT}
        with patch.object(CodexCLIProvider, "available", return_value=True), \
                patch.object(CodexCLIProvider, "run", return_value=out) as run:
            report = core.process_bridge_payload(self._payload())
        run.assert_called_once()
        self.assertEqual(report["bridge_status"], "done")
        self.assertEqual(report["lane"], "codex")
        self.assertEqual(report["report"]["status"], "done")
        # no project policy loaded -> fail-closed: read-only sandbox
        self.assertFalse(run.call_args.kwargs["writable"])

    def test_codex_lane_grants_write_with_policy_on_low_risk(self):
        out = {"provider": "codex_cli", "persona": "Riley", "agent": "ui-ux-dev",
               "report": VALID_REPORT}
        payload = self._payload(project="project_tct",
                                objective="Draft docstrings for the scan panel",
                                paths=["TCT_app/gui/scan_panel.py"])
        with patch.object(CodexCLIProvider, "available", return_value=True), \
                patch.object(CodexCLIProvider, "run", return_value=out) as run:
            report = core.process_bridge_payload(payload)
        self.assertEqual(report["bridge_status"], "done")
        self.assertTrue(run.call_args.kwargs["writable"])
        self.assertIsNotNone(run.call_args.kwargs["policy"])

    def test_codex_lane_refuses_denied_path_before_dispatch(self):
        payload = self._payload(project="project_tct",
                                paths=["TCT_app/devices/motor_grbl.py"])
        with patch.object(CodexCLIProvider, "run", MagicMock()) as run, \
                patch.object(CodexCLIProvider, "available", return_value=True):
            report = core.process_bridge_payload(payload)
        run.assert_not_called()
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["lane"], "codex")
        self.assertIn("egress policy refused", report["error"])

    def test_codex_lane_never_falls_back_to_claude(self):
        with patch.object(CodexCLIProvider, "available", return_value=True), \
                patch.object(CodexCLIProvider, "run", side_effect=RuntimeError("boom")), \
                patch("daedalus.core._ask_claude_report") as ask:
            report = core.process_bridge_payload(self._payload())
        ask.assert_not_called()
        self.assertEqual(report["bridge_status"], "failed")
        self.assertEqual(report["lane"], "codex")

    def test_codex_lane_reports_missing_cli(self):
        with patch.object(CodexCLIProvider, "available", return_value=False), \
                patch.object(CodexCLIProvider, "run", MagicMock()) as run:
            report = core.process_bridge_payload(self._payload())
        run.assert_not_called()
        self.assertEqual(report["bridge_status"], "failed")
        self.assertIn("not on PATH", report["error"])

    def test_availability_from_doctor_includes_codex(self):
        ready = {"claude_cli": True, "can_offload_local": False,
                 "deepseek_key": False, "codex_cli": True}
        with patch("daedalus.doctor.check", return_value=ready):
            avail = core._availability_from_doctor()
        self.assertTrue(avail["codex_cli"])
        self.assertFalse(avail["ollama"])


class DoctorCodexTests(unittest.TestCase):
    def _check(self, which_map):
        with patch("daedalus.doctor.shutil.which",
                   side_effect=lambda name: which_map.get(name)), \
                patch("daedalus.doctor._ollama_models", return_value=None):
            from daedalus.doctor import check
            return check()

    def test_check_reports_codex_present(self):
        r = self._check({"codex": "C:/npm/codex.cmd", "claude": "C:/npm/claude.cmd"})
        self.assertTrue(r["codex_cli"])

    def test_check_reports_codex_absent(self):
        r = self._check({"claude": "C:/npm/claude.cmd"})
        self.assertFalse(r["codex_cli"])

    def test_codex_status_absent_makes_no_subprocess_calls(self):
        from daedalus.doctor import codex_status
        with patch("daedalus.doctor.shutil.which", return_value=None), \
                patch("daedalus.doctor.subprocess.run") as run:
            status = codex_status()
        run.assert_not_called()
        self.assertEqual(status, {"present": False, "version": None, "logged_in": None})

    def test_codex_status_present_version_and_auth(self):
        from daedalus.doctor import codex_status

        def fake_run(cmd, **kwargs):
            # probes must use the RESOLVED shim path, never the bare name
            if cmd == ["C:/npm/codex.cmd", "--version"]:
                return _completed(0, stdout="codex-cli 0.144.1\n")
            if cmd == ["C:/npm/codex.cmd", "login", "status"]:
                return _completed(0, stdout="Logged in using ChatGPT\n")
            raise AssertionError(f"unexpected command {cmd}")

        with patch("daedalus.doctor.shutil.which", return_value="C:/npm/codex.cmd"), \
                patch("daedalus.doctor.subprocess.run", side_effect=fake_run):
            status = codex_status()
        self.assertEqual(status["version"], "codex-cli 0.144.1")
        self.assertTrue(status["logged_in"])

    def test_codex_status_logged_out(self):
        from daedalus.doctor import codex_status

        def fake_run(cmd, **kwargs):
            if cmd[1:] == ["--version"]:
                return _completed(0, stdout="codex-cli 0.144.1\n")
            return _completed(1, stderr="Not logged in")

        with patch("daedalus.doctor.shutil.which", return_value="C:/npm/codex.cmd"), \
                patch("daedalus.doctor.subprocess.run", side_effect=fake_run):
            status = codex_status()
        self.assertFalse(status["logged_in"])

    def test_doctor_main_renders_codex_line(self):
        from daedalus import doctor
        ready = {"claude_cli": True, "ollama_up": False,
                 "ollama_host": "http://127.0.0.1:11434",
                 "ollama_model_wanted": "qwen2.5-coder:7b", "ollama_models": [],
                 "ollama_model_present": False, "deepseek_key": False,
                 "can_offload_local": False, "codex_cli": True}
        cx = {"present": True, "version": "codex-cli 0.144.1", "logged_in": True}
        buf = io.StringIO()
        with patch("daedalus.doctor.check", return_value=ready), \
                patch("daedalus.doctor.codex_status", return_value=cx), \
                contextlib.redirect_stdout(buf):
            doctor.main()
        out = buf.getvalue()
        self.assertIn("codex CLI", out)
        self.assertIn("codex-cli 0.144.1", out)
        self.assertIn("logged in", out)

    def test_doctor_main_renders_codex_absent(self):
        from daedalus import doctor
        ready = {"claude_cli": True, "ollama_up": False,
                 "ollama_host": "http://127.0.0.1:11434",
                 "ollama_model_wanted": "qwen2.5-coder:7b", "ollama_models": [],
                 "ollama_model_present": False, "deepseek_key": False,
                 "can_offload_local": False, "codex_cli": False}
        cx = {"present": False, "version": None, "logged_in": None}
        buf = io.StringIO()
        with patch("daedalus.doctor.check", return_value=ready), \
                patch("daedalus.doctor.codex_status", return_value=cx), \
                contextlib.redirect_stdout(buf):
            doctor.main()
        self.assertIn("[--] codex CLI", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
