"""The verify gate's test budget: configurable, honest, and never a silent pass.

Background (MEASURED 2026-07-29): this repo's `.agentenv/agentenv.json` declared
``"test_command": "python -m pytest tests -q -x"`` -- the whole suite -- while
``verifier.verify`` hard-coded ``timeout_s=120`` and ``offload`` passed nothing
else. The suite needs far longer than 120 s, so the committed configuration was
STRUCTURALLY unable to pass; every live write died as::

    "tests": ok=false, "could not run tests: ... timed out after 120 seconds"
    action: escalated_after_verify_fail

Three separate properties are pinned here:

1. ``test_timeout_s`` is a per-project knob that reaches ``_run_tests``, and its
   ABSENCE still means 120 s -- adding the knob must not re-time any other repo.
2. A timeout is never a pass, and is distinguishable from a red suite. Both
   block the write; they are opposite diagnoses and the escalation is recorded
   against the local lane's routing metrics.
3. A malformed budget falls back to the default, never to "no timeout".

Plus the disk-truth arming fix: the test gate used to be armed by the model's
self-reported ``files_changed``, which a worker could set to ``[]`` while still
writing to disk -- dodging the suite entirely.
"""
from __future__ import annotations

import inspect
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from daedalus import metrics
from daedalus.orchestration import verifier
from daedalus.config import STARTER
from daedalus.limit_policy import ExecutionLimitPolicy, MODE_UNBOUNDED_EXECUTION
from daedalus.orchestration.verifier import DEFAULT_TEST_TIMEOUT_S, _effective_timeout, verify
# THE LIVE CASCADE TAKES A LEASE NOW, AND SO DOES THIS TEST. The shim that
# used to stand here called ``daedalus.offload._offload_impl`` directly with
# ``live=True`` -- a complete, un-leased write path. That second caller is
# exactly why ``scripts/declare_write_surfaces.py`` could not attribute the
# provider run to ``python.offload``'s Effect Lease: a write reachable from a
# leased AND an un-leased caller is attributable to neither. The planner no
# longer executes anything, so these tests take the door production takes.
from test_offload_lease_harness import live_offload as offload


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTENV = REPO_ROOT / ".agentenv" / "agentenv.json"

VALID = {"status": "done", "summary": "ok", "files_changed": [],
         "tests_run": [], "risks": [], "todos": [], "handoff": {}}


def _tests_check(vr) -> dict:
    hits = [c for c in vr.checks if c["name"] == "tests"]
    assert len(hits) == 1, f"expected exactly one tests check, got {vr.checks}"
    return hits[0]


# --------------------------------------------------------------------------- #
# 1. the default is preserved                                                  #
# --------------------------------------------------------------------------- #
class DefaultBudgetTests(unittest.TestCase):
    def test_the_default_budget_is_still_120_seconds(self):
        # Asserted against the live objects, not the source text: a docstring
        # that says "120" survives the constant being changed to 5.
        self.assertEqual(DEFAULT_TEST_TIMEOUT_S, 120)
        self.assertEqual(
            inspect.signature(verify).parameters["timeout_s"].default, 120,
            "verify()'s default budget changed -- that silently re-times the "
            "verify gate of EVERY repo that declares no test_timeout_s")

    def test_a_caller_that_passes_no_budget_gets_the_default(self):
        seen = {}

        def spy(cmd, cwd, timeout_s):
            seen["timeout_s"] = timeout_s
            return True, "ok", "pass"

        with mock.patch.object(verifier, "_run_tests", spy):
            verify(VALID, str(REPO_ROOT), test_command="whatever")
        self.assertEqual(seen["timeout_s"], 120)

    def test_the_starter_config_declares_the_knob_at_the_default(self):
        # Scaffolding a fresh repo must not change its gate's timing.
        self.assertIn("test_timeout_s", STARTER)
        self.assertEqual(STARTER["test_timeout_s"], DEFAULT_TEST_TIMEOUT_S)


# --------------------------------------------------------------------------- #
# 2. a timeout is not a pass, and not a test failure either                    #
# --------------------------------------------------------------------------- #
class TimeoutIsDistinguishableTests(unittest.TestCase):
    """These drive a REAL subprocess -- the timeout has to actually happen."""

    def _run(self, snippet: str, timeout_s: int) -> dict:
        # Bare `python`, not sys.executable: _run_tests uses POSIX shlex.split,
        # which eats the backslashes in a Windows interpreter path. The repo's
        # own declared test_command has the same bare-`python` shape.
        with tempfile.TemporaryDirectory() as d:
            cmd = f'python -c "{snippet}"'
            return _tests_check(verify(VALID, d, test_command=cmd,
                                       timeout_s=timeout_s))

    def test_a_green_suite_reports_pass(self):
        c = self._run("pass", 30)
        self.assertTrue(c["ok"])
        self.assertEqual(c["status"], "pass")

    def test_a_red_suite_reports_fail(self):
        c = self._run("raise SystemExit(1)", 30)
        self.assertFalse(c["ok"])
        self.assertEqual(c["status"], "fail")

    def test_a_timeout_is_never_read_as_a_pass(self):
        t0 = time.time()
        c = self._run("import time; time.sleep(30)", 2)
        # It really was killed by the budget, not by the command exiting.
        self.assertLess(time.time() - t0, 25, "the command was not killed")
        self.assertFalse(c["ok"], "a killed suite must never satisfy the gate")
        self.assertEqual(c["status"], "timeout")

    def test_a_timeout_is_distinguishable_from_a_red_suite(self):
        # The whole point: both block the write, but a consumer must be able to
        # tell "the write broke the tests" from "we did not give the suite time
        # to answer" WITHOUT string-matching English out of a truncated detail.
        killed = self._run("import time; time.sleep(30)", 2)
        red = self._run("raise SystemExit(1)", 30)
        self.assertFalse(killed["ok"])
        self.assertFalse(red["ok"])
        self.assertNotEqual(
            killed["status"], red["status"],
            "timeout and test-failure collapsed into one indistinguishable signal")
        # And the budget that was actually applied is reported, so a reader can
        # see WHICH number needs raising.
        self.assertEqual(killed["timeout_s"], 2)

    def test_an_unrunnable_command_is_an_error_not_a_failure(self):
        c = self._run_missing()
        self.assertFalse(c["ok"])
        self.assertEqual(c["status"], "error")

    def _run_missing(self) -> dict:
        with tempfile.TemporaryDirectory() as d:
            return _tests_check(verify(
                VALID, d, test_command="daedalus-no-such-binary-xyz --go",
                timeout_s=30))


# --------------------------------------------------------------------------- #
# 3. a malformed budget must never mean "unlimited"                            #
# --------------------------------------------------------------------------- #
class MalformedBudgetTests(unittest.TestCase):
    def test_junk_budgets_fall_back_to_the_default_not_to_no_timeout(self):
        # subprocess.run(timeout=None) waits FOREVER. Coercing junk to None
        # would turn a config typo into a wedged harness.
        for bad in (None, 0, -1, -900, "600", "", [], {}, True, False, 0.0):
            with self.subTest(bad=bad):
                self.assertEqual(_effective_timeout(bad), DEFAULT_TEST_TIMEOUT_S)

    def test_a_sane_budget_is_honoured(self):
        self.assertEqual(_effective_timeout(900), 900)

    def test_a_fractional_budget_is_not_truncated_into_instant_expiry(self):
        # int(0.5) == 0, and a 0 budget expires before the suite starts. A
        # small fractional budget is silly but it must stay what was declared
        # rather than silently becoming the failure mode above it.
        self.assertEqual(_effective_timeout(0.5), 0.5)
        self.assertEqual(_effective_timeout(1.9), 1.9)
        self.assertGreater(_effective_timeout(0.5), 0)

    def test_a_zero_budget_does_not_hang_and_does_not_pass(self):
        seen = {}

        def spy(cmd, cwd, timeout_s):
            seen["timeout_s"] = timeout_s
            return True, "ok", "pass"

        with mock.patch.object(verifier, "_run_tests", spy):
            verify(VALID, str(REPO_ROOT), test_command="whatever", timeout_s=0)
        self.assertEqual(seen["timeout_s"], DEFAULT_TEST_TIMEOUT_S)

    def test_explicit_unbounded_wall_time_passes_no_timeout_but_keeps_the_gate(self):
        seen = {}

        def spy(cmd, cwd, timeout_s):
            seen["timeout_s"] = timeout_s
            return True, "ok", "pass"

        policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
        with mock.patch.object(verifier, "_run_tests", spy):
            result = verify(
                VALID,
                str(REPO_ROOT),
                test_command="whatever",
                timeout_s=1,
                execution_limit_policy=policy,
            )

        check = _tests_check(result)
        self.assertIsNone(seen["timeout_s"])
        self.assertIsNone(check["timeout_s"])
        self.assertFalse(check["wall_time_ceiling_enabled"])
        self.assertEqual(
            check["execution_limit_policy_sha256"],
            policy.fingerprint_sha256,
        )


# --------------------------------------------------------------------------- #
# 4. this repo's own committed config must be one that CAN pass                #
# --------------------------------------------------------------------------- #
# MEASURED 2026-07-29 on this box (8 cores, Windows 11, box otherwise loaded by
# a 7-agent wave): `python -m pytest tests -q -x` -> see MEASURED_SUITE_SECONDS.
# Recorded here so that lowering the declared budget below the observed runtime
# goes RED instead of silently restoring the "can never pass" configuration.
MEASURED_SUITE_SECONDS = 1223


class ThisRepoCanActuallyPassItsOwnGateTests(unittest.TestCase):
    def setUp(self):
        if not AGENTENV.exists():
            self.skipTest("no repo-local .agentenv/agentenv.json")
        self.cfg = json.loads(AGENTENV.read_text(encoding="utf-8"))

    def test_the_declared_budget_exceeds_the_measured_suite_runtime(self):
        declared = self.cfg.get("test_timeout_s")
        self.assertIsInstance(declared, int)
        self.assertGreaterEqual(
            declared, int(MEASURED_SUITE_SECONDS * 1.5),
            "this repo declares the WHOLE suite as its verify gate; a budget "
            "at or near the measured runtime leaves no headroom for a loaded "
            "box and re-creates the structurally-unpassable config")

    def test_the_declared_command_is_still_the_whole_suite(self):
        # Narrowing test_command would be defensible only if docs/ could not
        # break the suite. It can: tests/test_comms.py reads the REAL
        # docs/COMMS_PROTOCOL.md and tests/test_generated_inventory.py reads the
        # REAL docs/FEATURE_INVENTORY.json. write_allow permits docs/, so a
        # narrowed command would leave a genuinely reachable break uncaught.
        self.assertIn("pytest", self.cfg["test_command"])
        self.assertIn("tests", self.cfg["test_command"])


# --------------------------------------------------------------------------- #
# 5. end-to-end plumbing through offload                                       #
# --------------------------------------------------------------------------- #
_OBJECTIVE = "improve the helper defaults"
_TARGET = "docs/notes_helper.py"
_AVAIL_OLLAMA = {"claude_cli": True, "ollama": True, "deepseek": False,
                 "codex_cli": False}
_SILENT_REPORT = {"status": "done", "summary": "s", "files_changed": [],
                  "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class _WritingWorker:
    """Writes the target on disk but SELF-REPORTS files_changed: [] -- the exact
    shape that used to dodge the test gate."""

    def __init__(self, repo_root: str, rel: str):
        self._root, self._rel = repo_root, rel
        self._backup: bytes | None = None
        self.rollback_failures: list[str] = []

    def run(self, **kwargs):
        p = Path(self._root) / self._rel
        self._backup = p.read_bytes() if p.exists() else None
        p.write_text("def blurb():\n    return 'bye'\n", encoding="utf-8")
        return {"report": dict(_SILENT_REPORT)}

    def rollback(self):
        p = Path(self._root) / self._rel
        if self._backup is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(self._backup)
        return [self._rel]


def _mkrepo(tmp: str, extra: dict) -> str:
    root = Path(tmp)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / _TARGET).write_text("def blurb():\n    return 'hi'\n", encoding="utf-8")
    cfg = root / ".agentenv"
    (cfg / "agents").mkdir(parents=True, exist_ok=True)
    body = {"policy": {"default_deny": True, "allow": ["docs/"]},
            "test_cwd": ".", **extra}
    (cfg / "agentenv.json").write_text(json.dumps(body), encoding="utf-8")
    (cfg / "agents" / "helper-dev.json").write_text(
        '{"name": "helper-dev", "call_name": "Help", "model_tier": "sonnet",'
        ' "external_ok": true, "owns": ["docs"], "triggers": ["helper", "improve"],'
        ' "must_read": [], "output_schema": "agent_report_v1",'
        ' "category": "implementation"}', encoding="utf-8")
    return str(root)


class OffloadPlumbsTheBudgetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def _run(self, extra: dict, outcome=(True, "ok", "pass")):
        """Real offload; only the subprocess boundary is stubbed, so the budget
        genuinely travels config -> offload -> verify -> _run_tests."""
        repo = _mkrepo(self._tmp.name, extra)
        seen: dict = {}

        def spy(cmd, cwd, timeout_s):
            seen["cmd"], seen["timeout_s"] = cmd, timeout_s
            return outcome

        worker = _WritingWorker(repo, _TARGET)
        with mock.patch("daedalus.providers.get_provider", return_value=worker), \
                mock.patch.object(verifier, "_run_tests", spy):
            r = offload(_OBJECTIVE, repo, paths=[_TARGET], live=True,
                        availability=_AVAIL_OLLAMA)
        return r, seen

    def test_a_declared_budget_reaches_the_test_runner(self):
        r, seen = self._run({"test_command": "pytest -q", "test_timeout_s": 777})
        self.assertEqual(r["mode"], "write")
        self.assertEqual(seen.get("cmd"), "pytest -q")
        self.assertEqual(seen.get("timeout_s"), 777,
                         "per-project test_timeout_s did not reach the verifier")

    def test_a_project_without_the_key_keeps_the_120s_default(self):
        _r, seen = self._run({"test_command": "pytest -q"})
        self.assertEqual(seen.get("timeout_s"), DEFAULT_TEST_TIMEOUT_S,
                         "adding test_timeout_s silently re-timed a repo that "
                         "never declared one")

    def test_the_test_gate_is_armed_by_disk_truth_not_the_self_report(self):
        # The worker wrote the file but reported files_changed: []. Arming the
        # gate off the self-report let exactly this shape skip the suite.
        _r, seen = self._run({"test_command": "pytest -q", "test_timeout_s": 300})
        self.assertEqual(seen.get("cmd"), "pytest -q",
                         "the test gate never ran: a worker that writes to disk "
                         "while reporting files_changed: [] dodged the suite")

    def test_a_timeout_escalates_and_is_labelled_as_such_in_metrics(self):
        r, _seen = self._run({"test_command": "pytest -q", "test_timeout_s": 300},
                             outcome=(False, "killed", "timeout"))
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        check = _tests_check_dict(r["verify"])
        self.assertFalse(check["ok"])
        self.assertEqual(check["status"], "timeout")
        rows = [json.loads(x) for x in
                metrics.LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
        notes = [row.get("note") for row in rows
                 if row.get("action") == "escalated_after_verify_fail"]
        self.assertTrue(any("tests:timeout" in (n or "") for n in notes),
                        f"metrics recorded an unlabelled reason: {notes}")

    def test_a_red_suite_is_labelled_differently_from_a_timeout(self):
        r, _seen = self._run({"test_command": "pytest -q", "test_timeout_s": 300},
                             outcome=(False, "2 failed", "fail"))
        self.assertEqual(r["action"], "escalated_after_verify_fail")
        rows = [json.loads(x) for x in
                metrics.LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
        notes = [row.get("note") for row in rows
                 if row.get("action") == "escalated_after_verify_fail"]
        self.assertTrue(any("tests:fail" in (n or "") for n in notes), notes)
        self.assertFalse(any("tests:timeout" in (n or "") for n in notes), notes)


def _tests_check_dict(verify_dict: dict) -> dict:
    hits = [c for c in verify_dict["checks"] if c["name"] == "tests"]
    assert len(hits) == 1, verify_dict
    return hits[0]


if __name__ == "__main__":
    unittest.main()
