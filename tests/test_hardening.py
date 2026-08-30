# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Hardening tests for thin-coverage load-bearing modules: sensitivity policy
merging, verifier gates, token policy/monitor parsing, memory snapshots, the
file bridge request layer, read-only provider enforcement, and metrics math.

OFFLINE AND DETERMINISTIC: every external seam (Claude logs, subprocess test
runners, memory/metrics log paths) is mocked or pointed at a temp dir. Run
with:  python -m unittest discover tests

Tests marked `# BUG?:` document surprising CURRENT behavior on purpose; they
assert what the code does today so a fix will show up as a test change.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daedalus import file_bridge, memory, metrics, verifier
from daedalus.providers.base import Provider, ProviderCapabilities
from daedalus.sensitivity import (
    DEFAULT_POLICY,
    GENERIC_DENY_CONTENT,
    GENERIC_DENY_SUBSTRINGS,
    change_risk,
    classify_data,
    load_policy,
    path_write_blocked,
)
from daedalus.token_monitor import read_usage_samples, summarize_usage
from daedalus.token_policy import MAX_PATHS_PER_REQUEST, trim_paths, trim_text


def _report(files_changed=None, status="done"):
    return {"status": status, "summary": "s", "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class SensitivityPolicyTests(unittest.TestCase):
    """Policy merging, path/write gating, and risk classification."""

    def test_custom_deny_merges_with_generic_secret_floor(self):
        pol = load_policy({"policy": {"deny": ["vendor_ip/", ".env"]}})
        self.assertIn("vendor_ip/", pol.deny_substrings)
        for frag in GENERIC_DENY_SUBSTRINGS:
            self.assertIn(frag, pol.deny_substrings)
        # duplicate ".env" from the project config is deduplicated, not doubled
        self.assertEqual(len(pol.deny_substrings), len(set(pol.deny_substrings)))
        self.assertTrue(classify_data(["vendor_ip/sauce.py"], policy=pol).sensitive)

    def test_custom_allow_replaces_generic_allow(self):
        # Unlike deny (always unioned), a project "allow" REPLACES the generic
        # allow-list entirely: docs/ stops being egress-safe.
        pol = load_policy({"policy": {"allow": ["public/"]}})
        self.assertEqual(pol.allow_substrings, ("public/",))
        self.assertTrue(classify_data(["docs/guide.txt"], policy=pol).sensitive)
        self.assertFalse(classify_data(["public/notes.txt"], policy=pol).sensitive)

    def test_high_risk_paths_keep_generic_floor(self):
        pol = load_policy({"policy": {"high_risk_paths": ["/custom_hw/"]}})
        self.assertIn("/custom_hw/", pol.high_risk_path_substrings)
        self.assertIn("/devices/", pol.high_risk_path_substrings)
        self.assertIn("/devices/", load_policy({}).high_risk_path_substrings)
        self.assertTrue(path_write_blocked("repo/devices/motor.py", load_policy({})))

    def test_custom_deny_content_merged_and_bad_patterns_skipped(self):
        pol = load_policy({"policy": {"deny_content": [
            r"\bvendor[-_]secret\b",  # valid -> compiled
            "[unclosed",              # invalid regex -> skipped, no crash
            "x" * 300,                # over-long -> skipped (ReDoS guard)
            123,                      # non-str -> skipped
        ]}})
        self.assertEqual(len(pol.deny_content), len(GENERIC_DENY_CONTENT) + 1)
        self.assertTrue(classify_data([], extra_text="the vendor_secret handshake",
                                      policy=pol).sensitive)
        # generic markers survive the merge
        self.assertTrue(classify_data([], extra_text="password: hunter2",
                                      policy=pol).sensitive)

    def test_allow_exception_beats_deny_and_default_deny(self):
        pol = load_policy({"policy": {"allow_exceptions": [".env.example"]}})
        # exception is checked FIRST, so it overrides the ".env" deny fragment
        self.assertFalse(classify_data(["config/.env.example"], policy=pol).sensitive)
        denied = classify_data(["config/.env"], policy=pol)
        self.assertTrue(denied.sensitive)
        self.assertEqual(denied.offending, ["config/.env"])
        self.assertIn("denylisted", denied.reasons[0])

    def test_default_deny_flags_unlisted_path_and_allows_docs(self):
        res = classify_data(["src/private_module.py"])
        self.assertTrue(res.sensitive)
        self.assertIn("default-deny", res.reasons[0])
        self.assertFalse(classify_data(["docs/guide.md"]).sensitive)
        self.assertFalse(classify_data(["tests/test_widget.py"]).sensitive)

    def test_classify_extra_text_matches_secret_assignment(self):
        res = classify_data([], extra_text="API_KEY = abc123")
        self.assertTrue(res.sensitive)
        self.assertEqual(res.offending, [])  # content match, not a path match
        self.assertEqual(len(res.reasons), 1)  # stops at the first marker
        self.assertIn("content matches", res.reasons[0])
        self.assertFalse(classify_data([], extra_text="plain prose, no markers").sensitive)

    def test_path_write_blocked_windows_and_posix_paths(self):
        pol = load_policy({"policy": {"high_risk_paths": ["/devices/"]}})
        self.assertTrue(path_write_blocked(r"TCT_app\devices\motor_grbl.py", pol))
        self.assertTrue(path_write_blocked("TCT_app/devices/motor_grbl.py", pol))
        self.assertTrue(path_write_blocked(r"TCT_APP\DEVICES\MOTOR.PY", pol))  # case-folded
        # generic secret floor also matches backslash paths, even w/o project policy
        self.assertTrue(path_write_blocked(r"conf\prod.env", DEFAULT_POLICY))
        self.assertFalse(path_write_blocked("TCT_app/gui/panel.py", pol))

    def test_simulated_suffix_bypasses_deny(self):
        pol = load_policy({"policy": {"high_risk_paths": ["/devices/"]}})
        self.assertFalse(path_write_blocked("TCT_app/devices/motor_grbl_simulated.py", pol))
        self.assertTrue(path_write_blocked("secrets/password_simulated.py", pol))

    def test_change_risk_high_term_and_path_floor(self):
        self.assertEqual(change_risk("deploy the new dashboard"), "high")
        pol = load_policy({"policy": {"high_risk_paths": ["/devices/", "state_machine"]}})
        # benign wording, high-blast-radius path (backslashes normalized) -> high
        self.assertEqual(change_risk("tidy comments", [r"TCT_app\devices\motor.py"], pol),
                         "high")

    def test_change_risk_mid_and_low(self):
        self.assertEqual(change_risk("refactor the parser helper"), "mid")
        self.assertEqual(change_risk("update readme wording"), "low")

    def test_change_risk_substring_false_positive(self):
        # BUG?: risk terms are plain substring matches, so "author" contains
        # "auth" and a docs-only task gets forced to the high-risk tier.
        self.assertEqual(change_risk("credit the author in docs"), "high")


class VerifierHardeningTests(unittest.TestCase):
    """require_changes gate, config parsing, and test_command wiring."""

    def test_write_mode_noop_fails_did_work(self):
        res = verifier.verify(_report(), ".", require_changes=True)
        self.assertFalse(res.ok)
        self.assertIn("did_work", res.failed)

    def test_write_mode_with_changes_passes_did_work(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            res = verifier.verify(_report(["ok.py"]), d, require_changes=True)
        self.assertTrue(res.ok)
        self.assertNotIn("did_work", res.failed)

    def test_advisory_no_changes_passes(self):
        # require_changes=False (default): a change-free advisory report is fine
        res = verifier.verify(_report(), ".")
        self.assertTrue(res.ok)
        self.assertEqual([c["name"] for c in res.checks], ["schema"])

    def test_invalid_json_config_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cfg.json").write_text("{ nope", encoding="utf-8")
            res = verifier.verify(_report(["cfg.json"]), d)
        self.assertFalse(res.ok)
        self.assertIn("parse:cfg.json", res.failed)
        detail = next(c["detail"] for c in res.checks if c["name"] == "parse:cfg.json")
        self.assertIn("invalid json", detail)

    def test_valid_json_config_passes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cfg.json").write_text('{"a": 1}', encoding="utf-8")
            self.assertTrue(verifier.verify(_report(["cfg.json"]), d).ok)

    def test_uncompilable_python_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            res = verifier.verify(_report(["broken.py"]), d)
        self.assertFalse(res.ok)
        self.assertIn("syntax:broken.py", res.failed)

    def test_test_command_wiring_success(self):
        fake = SimpleNamespace(returncode=0, stdout="2 passed", stderr="")
        with patch("daedalus.verifier.subprocess.run", return_value=fake) as run:
            res = verifier.verify(_report(), "/repo",
                                  test_command="pytest -q tests", test_cwd="/elsewhere")
        run.assert_called_once()
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["pytest", "-q", "tests"])  # shlex-split argv
        self.assertEqual(kwargs["cwd"], "/elsewhere")
        self.assertEqual(kwargs["timeout"], 120)
        self.assertTrue(res.ok)
        tests_check = next(c for c in res.checks if c["name"] == "tests")
        self.assertIn("2 passed", tests_check["detail"])

    def test_test_command_failure_and_default_cwd(self):
        fake = SimpleNamespace(returncode=1, stdout="1 failed", stderr="boom")
        with patch("daedalus.verifier.subprocess.run", return_value=fake) as run:
            res = verifier.verify(_report(), "/repo", test_command="pytest -q")
        self.assertEqual(run.call_args.kwargs["cwd"], "/repo")  # falls back to repo_root
        self.assertFalse(res.ok)
        self.assertIn("tests", res.failed)


class TokenPolicyTests(unittest.TestCase):
    def test_trim_text_boundaries(self):
        self.assertEqual(trim_text("abcde", 5), "abcde")   # at the limit: unchanged
        self.assertEqual(trim_text("abcdef", 5), "ab...")  # one over: ellipsized to limit
        self.assertEqual(len(trim_text("x" * 100, 10)), 10)
        self.assertEqual(trim_text("ab  cdef", 7), "ab...")  # rstrip may undershoot
        self.assertEqual(trim_text("", 5), "")
        # BUG?: max_chars < 3 makes the slice negative (text[:max_chars-3]), so
        # the "trimmed" output is LONGER than the limit it was given.
        self.assertEqual(trim_text("abcdef", 2), "abcde...")

    def test_trim_paths_dedupe_order_and_limit(self):
        self.assertEqual(trim_paths(["b", "a", "b", "c"], limit=3), ["b", "a", "c"])
        self.assertEqual(trim_paths([]), [])
        fifteen = [f"p{i}" for i in range(15)]
        trimmed = trim_paths(fifteen)
        self.assertEqual(len(trimmed), MAX_PATHS_PER_REQUEST)
        self.assertEqual(trimmed[0], "p0")  # first-seen order preserved


class TokenMonitorParsingTests(unittest.TestCase):
    """JSONL parsing fed from a temp file -- never the real Claude logs."""

    def test_malformed_lines_are_skipped(self):
        lines = [
            "",
            "   ",
            "{this is not json",
            '{"message": "not-a-dict"}',  # dict without usage/error -> ignored
            json.dumps({"timestamp": "t1", "sessionId": "s1", "message": {
                "model": "m1",
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_creation_input_tokens": 1, "cache_read_input_tokens": 2},
                "content": [{"text": "hi"}]}}),
            json.dumps({"timestamp": "t2", "isApiErrorMessage": True,
                        "apiErrorStatus": 429, "error": "rate_limit"}),
        ]
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.jsonl"
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with patch("daedalus.token_monitor._iter_project_logs", return_value=[log]):
                samples = read_usage_samples()
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].fresh_tokens, 16)  # 10 + 5 + 1, cache reads excluded
        self.assertEqual(samples[0].cache_read_input_tokens, 2)
        self.assertEqual(samples[0].text, "hi")
        self.assertEqual(samples[1].api_error_status, 429)
        summary = summarize_usage(samples)
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["rate_limit_events"], 1)

    def test_valid_json_non_object_line_raises(self):
        # BUG?: a line that IS valid JSON but not an object (e.g. an array)
        # survives json.loads and then crashes _sample_from_obj with
        # AttributeError (list has no .get) instead of being skipped like the
        # other malformed lines.
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "log.jsonl"
            log.write_text("[1, 2, 3]\n", encoding="utf-8")
            with patch("daedalus.token_monitor._iter_project_logs", return_value=[log]):
                with self.assertRaises(AttributeError):
                    read_usage_samples()


class MemoryTests(unittest.TestCase):
    """append_event + todos.local.md regeneration on a temp memory dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = (memory.MEMORY_DIR, memory.EVENTS_PATH, memory.TODO_PATH)
        memory.MEMORY_DIR = Path(self._tmp.name) / "memory"
        memory.EVENTS_PATH = memory.MEMORY_DIR / "events.local.jsonl"
        memory.TODO_PATH = memory.MEMORY_DIR / "todos.local.md"

    def tearDown(self):
        memory.MEMORY_DIR, memory.EVENTS_PATH, memory.TODO_PATH = self._orig
        self._tmp.cleanup()

    def test_append_event_writes_log_and_regenerates_snapshot(self):
        record = memory.append_event(memory.MemoryEvent(
            kind="manual", summary="panel context", status="open",
            todos=["Fix the panel"], paths=["gui/panel.py"]))
        self.assertIn("time", record)
        lines = memory.EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["todos"], ["Fix the panel"])
        snap = memory.TODO_PATH.read_text(encoding="utf-8")
        self.assertIn("Fix the panel", snap)
        self.assertIn("gui/panel.py", snap)
        self.assertIn("Context: panel context", snap)

    def test_snapshot_separates_open_and_done(self):
        memory.append_event(memory.MemoryEvent(
            kind="manual", summary="s1", status="open", todos=["Fix the panel"]))
        memory.append_event(memory.MemoryEvent(
            kind="manual", summary="s2", status="open", todos=["Review diff"]))
        # done event closes the todo case-insensitively
        memory.append_event(memory.MemoryEvent(
            kind="manual", summary="s3", status="done", todos=["fix the panel"]))
        snap = memory.TODO_PATH.read_text(encoding="utf-8")
        open_part, done_part = snap.split("## Recent Done Items")
        self.assertIn("Review diff", open_part)
        self.assertNotIn("Fix the panel", open_part)
        self.assertIn("fix the panel", done_part)

    def test_corrupt_event_line_breaks_snapshot_refresh(self):
        # BUG?: load_events has no per-line try/except, so ONE corrupt line in
        # events.local.jsonl makes every later append_event raise. Worse, the
        # new event is written to the log BEFORE the snapshot refresh crashes,
        # leaving the log and todos.local.md permanently out of sync until the
        # bad line is removed by hand.
        memory.MEMORY_DIR.mkdir(parents=True)
        memory.EVENTS_PATH.write_text("{corrupt line\n", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            memory.append_event(memory.MemoryEvent(
                kind="manual", summary="after corruption", todos=["t"]))
        lines = memory.EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)  # the event WAS persisted despite the crash
        self.assertIn("after corruption", lines[1])
        with self.assertRaises(json.JSONDecodeError):
            memory.load_events()


class FileBridgeRequestTests(unittest.TestCase):
    """_read_request defaults/validation and enqueue slug generation."""

    def _request(self, body: str, default_root=None):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "req.json"
            path.write_text(body, encoding="utf-8")
            return file_bridge._read_request(path, default_root)

    def test_read_request_defaults(self):
        req = self._request('{"objective": "review", "repo_root": "/r"}')
        self.assertEqual(req["repo_root"], "/r")  # explicit root wins over default
        self.assertEqual(req["paths"], [])
        self.assertEqual(req["model"], "sonnet")
        self.assertEqual(req["lane"], "local_only")  # fail-closed: an unlabeled dropped file never spends unattended

    def test_read_request_missing_objective(self):
        with self.assertRaises(ValueError) as cm:
            self._request('{"repo_root": "/r"}', default_root="/fallback")
        self.assertIn("objective", str(cm.exception))

    def test_read_request_missing_repo_root(self):
        with self.assertRaises(ValueError) as cm:
            self._request('{"objective": "x"}')
        self.assertIn("repo_root", str(cm.exception))

    def _enqueue(self, objective: str) -> Path:
        with tempfile.TemporaryDirectory() as d:
            with patch.object(file_bridge, "OUTBOX", Path(d)), \
                    patch.object(file_bridge, "_stamp", lambda: "20260705T000000Z"):
                path = file_bridge.enqueue(objective, "/r", ["a.py"], require_watcher=False)
                payload = json.loads(path.read_text(encoding="utf-8"))
        return path.name, payload

    def _parts(self, name: str):
        """Split `<stamp>-<slug>-<uniquifier>.json` into its three fields.

        The uniquifier is a late addition: the name used to be stamp+slug
        only, at one-second resolution, so two requests enqueued in the same
        second collided and one was silently overwritten -- a real dropped
        task, found end-to-end while 1756 unit tests were green. The slug
        assertions below are still the point of these tests; parsing here
        keeps them about the slug instead of re-pinning the whole filename."""
        self.assertTrue(name.endswith(".json"), name)
        stem = name[:-len(".json")]
        head, _, unique = stem.rpartition("-")
        stamp, _, slug = head.partition("-")
        return stamp, slug, unique

    def test_enqueue_empty_objective_slug(self):
        name, payload = self._enqueue("")
        stamp, slug, _ = self._parts(name)
        self.assertEqual(stamp, "20260705T000000Z")
        self.assertEqual(slug, "task")  # falls back to 'task'
        self.assertEqual(payload["lane"], "auto")
        self.assertEqual(payload["model"], "sonnet")

    def test_enqueue_symbol_only_objective_slug(self):
        # every char maps to '-' and is stripped -> same 'task' fallback
        name, _ = self._enqueue("!!! ???")
        self.assertEqual(self._parts(name)[1], "task")

    def test_enqueue_normal_slug_and_truncation(self):
        name, payload = self._enqueue("Fix GUI panel layout")
        stamp, slug, _ = self._parts(name)
        self.assertEqual(stamp, "20260705T000000Z")
        self.assertEqual(slug, "fix-gui-panel-layout")
        self.assertEqual(payload["objective"], "Fix GUI panel layout")
        self.assertEqual(payload["paths"], ["a.py"])
        long_name, _ = self._enqueue("a" * 100)
        self.assertEqual(self._parts(long_name)[1], "a" * 48)

    def test_two_identical_requests_in_the_same_second_both_survive(self):
        """The bug the uniquifier exists for, pinned as a property.

        Same objective, same stamp, same outbox -- the queue must end up with
        TWO files. With the old stamp+slug name this produced one, and the
        first request was gone with nothing logged."""
        with tempfile.TemporaryDirectory() as d:
            outbox = Path(d)
            with patch.object(file_bridge, "OUTBOX", outbox), \
                    patch.object(file_bridge, "_stamp", lambda: "20260705T000000Z"):
                first = file_bridge.enqueue("same objective", "/r", [], require_watcher=False)
                second = file_bridge.enqueue("same objective", "/r", [], require_watcher=False)
            self.assertNotEqual(first.name, second.name)
            self.assertEqual(len(list(outbox.glob("*.json"))), 2)

    def test_enqueue_leaves_no_partial_file_a_consumer_could_read(self):
        """Publication is atomic: the temp name must not match the watcher's glob.

        The watcher globs `*.json`; a half-written file matching that glob is
        dispatched as a truncated request."""
        seen: list[list[str]] = []
        real_replace = file_bridge.os.replace

        def spy(src, dst):
            seen.append(sorted(p.name for p in Path(dst).parent.glob("*.json")))
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as d:
            with patch.object(file_bridge, "OUTBOX", Path(d)), \
                    patch.object(file_bridge, "_stamp", lambda: "20260705T000000Z"), \
                    patch.object(file_bridge.os, "replace", spy):
                file_bridge.enqueue("atomic", "/r", [], require_watcher=False)
        self.assertEqual(seen, [[]], "a consumer's glob saw the request mid-write")

    def test_enqueue_preserves_project(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(file_bridge, "OUTBOX", Path(d)), \
                    patch.object(file_bridge, "_stamp", lambda: "20260705T000000Z"):
                path = file_bridge.enqueue("review", "/r", [], project="project_tct",
                                       require_watcher=False)
                payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["project"], "project_tct")


class _StubProvider(Provider):
    def __init__(self, can_write: bool):
        self.caps = ProviderCapabilities(
            name="stub", can_write=can_write, local=True,
            trusted_with_ip=True, agentic=False)

    def available(self) -> bool:
        return True

    def run(self, **kwargs):
        return {}


class ReadOnlyProviderTests(unittest.TestCase):
    def test_read_only_moves_proposals_and_downgrades(self):
        report = _report(["a.py"])
        report["tests_run"] = ["pytest -q"]
        report["handoff"] = {"note": "keep"}
        out = _StubProvider(can_write=False)._enforce_read_only(report)
        self.assertEqual(out["handoff"]["suggested_files"], ["a.py"])
        self.assertEqual(out["handoff"]["note"], "keep")  # existing handoff preserved
        self.assertEqual(out["files_changed"], [])
        self.assertEqual(out["tests_run"], [])
        self.assertEqual(out["status"], "needs_review")  # done -> advisory review

    def test_read_only_without_proposals_keeps_status(self):
        report = _report(status="blocked")
        out = _StubProvider(can_write=False)._enforce_read_only(report)
        self.assertEqual(out["status"], "blocked")  # only 'done' is downgraded
        self.assertNotIn("suggested_files", out["handoff"])
        self.assertEqual(out["files_changed"], [])
        self.assertEqual(out["tests_run"], [])

    def test_writable_provider_untouched(self):
        report = _report(["a.py"])
        out = _StubProvider(can_write=True)._enforce_read_only(report)
        self.assertIs(out, report)
        self.assertEqual(out["files_changed"], ["a.py"])
        self.assertEqual(out["status"], "done")


class MetricsHardeningTests(unittest.TestCase):
    """summary() math and the silent-escalation alarm boundary."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"

    def tearDown(self):
        metrics.LOG = self._orig
        self._tmp.cleanup()

    def test_alarm_fires_at_five_eligible_over_half(self):
        # exactly 5 eligible samples (the alarm floor), 3/5 = 0.6 > 0.5
        metrics.record(provider="ollama", action="offloaded", eligible=True)
        metrics.record(provider="ollama", action="offloaded", eligible=True)
        metrics.record(provider="claude_cli", action="escalate_to_claude", eligible=True)
        metrics.record(provider="claude_cli", action="escalate_to_claude", eligible=True)
        # verify-fail escalations count as fallback too (startswith 'escalate')
        metrics.record(provider="claude_cli", action="escalated_after_verify_fail",
                       eligible=True)
        s = metrics.summary()
        self.assertEqual(s["offloadable"], 5)
        self.assertEqual(s["fell_back_to_claude"], 3)
        self.assertAlmostEqual(s["fallback_rate"], 0.6)
        self.assertTrue(s["alarm"])

    def test_no_alarm_at_exactly_half_rate(self):
        # 6 eligible, 3 fell back -> rate exactly 0.5, alarm needs strictly > 0.5
        for _ in range(3):
            metrics.record(provider="ollama", action="offloaded", eligible=True)
            metrics.record(provider="claude_cli", action="escalate_to_claude",
                           eligible=True)
        s = metrics.summary()
        self.assertEqual(s["offloadable"], 6)
        self.assertAlmostEqual(s["fallback_rate"], 0.5)
        self.assertFalse(s["alarm"])

    def test_no_alarm_under_five_samples(self):
        # 4/4 fell back -> rate 1.0 but below the 5-sample floor -> no alarm
        for _ in range(4):
            metrics.record(provider="claude_cli", action="escalate_to_claude",
                           eligible=True)
        s = metrics.summary()
        self.assertEqual(s["offloadable"], 4)
        self.assertAlmostEqual(s["fallback_rate"], 1.0)
        self.assertFalse(s["alarm"])

    def test_corrupt_line_skipped_and_ineligible_excluded(self):
        metrics.LOG.parent.mkdir(parents=True, exist_ok=True)
        metrics.LOG.write_text("not json at all\n", encoding="utf-8")
        metrics.record(provider="ollama", action="offloaded", eligible=True)
        # ineligible (senior/high-risk) work never counts toward the rate
        metrics.record(provider="claude_cli", action="escalate_to_claude", eligible=False)
        s = metrics.summary()
        self.assertEqual(s["total"], 2)  # corrupt line dropped, both records kept
        self.assertEqual(s["offloadable"], 1)
        self.assertEqual(s["fell_back_to_claude"], 0)
        self.assertAlmostEqual(s["fallback_rate"], 0.0)
        self.assertFalse(s["alarm"])


if __name__ == "__main__":
    unittest.main()
