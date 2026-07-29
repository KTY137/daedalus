"""Report-arrival signal + watcher liveness (file_bridge status / heartbeat).

Covers the 2026-07-13 hardening: unread-report ledger (inbox/.seen/),
inbox/LATEST.log arrival lines, bridge_status(), heartbeat write/classify,
doctor's stale-heartbeat warning, and the codex inline-brief smell warning.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from daedalus import file_bridge


class _BridgeDirs(unittest.TestCase):
    """Base: fresh temp INBOX/OUTBOX/heartbeat per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.inbox = tmp / "inbox"
        self.outbox = tmp / "outbox"
        self.inbox.mkdir()
        self.outbox.mkdir()
        self.heartbeat = tmp / "runs" / "bridge_heartbeat.json"
        patches = [
            patch.object(file_bridge, "INBOX", self.inbox),
            patch.object(file_bridge, "OUTBOX", self.outbox),
            patch.object(file_bridge, "HEARTBEAT_PATH", self.heartbeat),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        file_bridge._last_idle_beat = 0.0  # un-throttle between tests

    def _report(self, name: str, payload: dict | None = None) -> Path:
        path = self.inbox / f"{name}.report.json"
        path.write_text(json.dumps(payload or {
            "bridge_status": "done", "lane": "codex",
            "request": {"project": "project_tct", "lane": "codex"},
            "report": {"summary": "did the thing"},
        }), encoding="utf-8")
        return path


class UnreadLedgerTests(_BridgeDirs):
    def test_new_reports_are_unread_until_marked(self):
        self._report("a")
        self._report("b")
        self.assertEqual([p.name for p in file_bridge.unread_reports()],
                         ["a.report.json", "b.report.json"])
        marked = file_bridge.mark_read(["a.report.json"])
        self.assertEqual(marked, ["a.report.json"])
        self.assertEqual([p.name for p in file_bridge.unread_reports()],
                         ["b.report.json"])

    def test_mark_read_all_and_suffixless_name(self):
        self._report("a")
        self._report("b")
        # suffixless name resolves to <name>.report.json
        self.assertEqual(file_bridge.mark_read(["b"]), ["b.report.json"])
        self.assertEqual(file_bridge.mark_read(all_reports=True), ["a.report.json"])
        self.assertEqual(file_bridge.unread_reports(), [])

    def test_mark_read_unknown_name_is_noop(self):
        self.assertEqual(file_bridge.mark_read(["nope"]), [])

    def test_note_report_arrival_appends_one_line(self):
        path = self._report("a")
        report = json.loads(path.read_text(encoding="utf-8"))
        file_bridge._note_report_arrival(path, report)
        file_bridge._note_report_arrival(path, report)
        lines = (self.inbox / "LATEST.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("a.report.json", lines[0])
        self.assertIn("status=done", lines[0])
        self.assertIn("lane=codex", lines[0])


class BridgeStatusTests(_BridgeDirs):
    def test_status_counts_queue_and_unread(self):
        (self.outbox / "t1.json").write_text(
            json.dumps({"objective": "x", "lane": "codex", "project": "project_tct"}),
            encoding="utf-8")
        self._report("a")
        self._report("b")
        file_bridge.mark_read(["a"])
        status = file_bridge.bridge_status("project_tct")
        self.assertEqual(status["queue_depth"], 1)
        self.assertEqual(status["unread_count"], 1)
        self.assertEqual(status["unread"][0]["name"], "b.report.json")
        self.assertEqual(status["reports_total"], 2)
        self.assertEqual(status["watcher"]["state"], "none")

    def test_status_project_filter(self):
        self._report("other", {"bridge_status": "done", "lane": "local",
                               "request": {"project": "not_tct"}, "report": {}})
        status = file_bridge.bridge_status("project_tct")
        self.assertEqual(status["unread_count"], 0)
        # unfiltered still sees it
        self.assertEqual(file_bridge.bridge_status()["unread_count"], 1)

    def test_print_status_smoke(self):
        self._report("a")
        buf = io.StringIO()
        with redirect_stdout(buf):
            file_bridge._print_status(file_bridge.bridge_status())
        out = buf.getvalue()
        self.assertIn("1 UNREAD", out)
        self.assertIn("mark-read", out)


class HeartbeatTests(_BridgeDirs):
    def test_no_heartbeat_is_none_state_with_restart_hint(self):
        hb = file_bridge.heartbeat_status()
        self.assertEqual(hb["state"], "none")
        self.assertIn("file_bridge watch", hb["restart"])

    def test_alive_then_stale(self):
        file_bridge.write_heartbeat(project="project_tct", force=True)
        now = time.time()
        self.assertEqual(file_bridge.heartbeat_status(now=now)["state"], "alive")
        stale = file_bridge.heartbeat_status(now=now + file_bridge.STALE_AFTER_S + 1)
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["restart"],
                         "python -m daedalus.file_bridge watch --project project_tct")

    def test_busy_then_wedged_uses_task_budget_not_stale_window(self):
        started = time.time()
        file_bridge.write_heartbeat(
            project="project_tct",
            current={"file": "t.json", "started_epoch": started}, force=True)
        # 20 min into a codex task: NOT stale, just busy
        busy = file_bridge.heartbeat_status(now=started + 1200)
        self.assertEqual(busy["state"], "busy")
        wedged = file_bridge.heartbeat_status(
            now=started + file_bridge.BUSY_BUDGET_S + 1)
        self.assertEqual(wedged["state"], "wedged")

    def test_idle_beats_are_throttled_but_forced_beats_land(self):
        file_bridge.write_heartbeat(force=True)
        first = self.heartbeat.read_text(encoding="utf-8")
        file_bridge.write_heartbeat()  # throttled: within IDLE_BEAT_EVERY_S
        self.assertEqual(self.heartbeat.read_text(encoding="utf-8"), first)
        file_bridge.write_heartbeat(current={"file": "t.json",
                                             "started_epoch": time.time()})
        self.assertNotEqual(self.heartbeat.read_text(encoding="utf-8"), first)

    def test_restart_hint_falls_back_to_repo_root(self):
        hint = file_bridge.restart_hint({"repo_root": "C:\\repo"})
        self.assertIn('--repo-root "C:\\repo"', hint)


class DoctorHeartbeatTests(_BridgeDirs):
    def _doctor_line(self) -> str:
        from daedalus.doctor import _print_watcher_heartbeat
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_watcher_heartbeat()
        return buf.getvalue()

    def test_doctor_warns_on_stale_heartbeat_with_restart_one_liner(self):
        file_bridge.write_heartbeat(project="project_tct", force=True)
        with patch.object(file_bridge, "STALE_AFTER_S", -1.0):
            out = self._doctor_line()
        self.assertIn("STALE", out)
        self.assertIn("python -m daedalus.file_bridge watch --project project_tct", out)

    def test_doctor_ok_on_fresh_heartbeat(self):
        file_bridge.write_heartbeat(project="project_tct", force=True)
        out = self._doctor_line()
        self.assertIn("[OK] bridge watcher heartbeat", out)

    def test_doctor_notes_missing_heartbeat_without_false_alarm(self):
        out = self._doctor_line()
        self.assertIn("[--]", out)
        self.assertIn("none recorded", out)


class CodexInlineBriefWarningTests(unittest.TestCase):
    LONG = "Please refactor the scan panel: " + "do this and that, " * 20

    def test_long_codex_objective_without_queue_ref_warns(self):
        msg = file_bridge.codex_inline_brief_warning(self.LONG, "codex")
        self.assertIsNotNone(msg)
        self.assertIn("CODEX_QUEUE.md", msg)

    def test_queue_reference_silences_warning(self):
        obj = self.LONG + " -- full brief: task C9 in docs/CODEX_QUEUE.md"
        self.assertIsNone(file_bridge.codex_inline_brief_warning(obj, "codex"))
        # spaced spelling counts too
        obj2 = self.LONG + " (see the codex queue md file)"
        self.assertIsNone(file_bridge.codex_inline_brief_warning(obj2, "codex"))

    def test_short_or_non_codex_objectives_do_not_warn(self):
        self.assertIsNone(file_bridge.codex_inline_brief_warning(
            "Execute task C9 from docs/CODEX_QUEUE.md", "codex"))
        self.assertIsNone(file_bridge.codex_inline_brief_warning(self.LONG, "auto"))

    def test_enqueue_emits_warning_to_stderr_but_still_enqueues(self):
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            err = io.StringIO()
            with patch.object(file_bridge, "OUTBOX", Path(d)), \
                    contextlib.redirect_stderr(err):
                path = file_bridge.enqueue(self.LONG, "/r", [], lane="codex")
            self.assertTrue(path.exists())
            self.assertIn("WARNING", err.getvalue())
            self.assertIn("CODEX_QUEUE.md", err.getvalue())


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
# a queue that loses a task is not a queue                                     #
# --------------------------------------------------------------------------- #
def test_two_enqueues_in_the_same_second_do_not_overwrite(tmp_path, monkeypatch):
    """The filename was `{second-resolution stamp}-{slug}.json`.

    Two enqueues of the SAME objective inside one second produced the same
    path, and the second silently overwrote the first: a task queue that drops
    a task under load, with no error and nothing in any log. 1753 unit tests
    were green over it; the end-to-end acceptance run found it by queueing two
    requests and getting one report back.
    """
    from daedalus import file_bridge as fb

    monkeypatch.setattr(fb, "OUTBOX", tmp_path / "outbox")
    # Freeze the clock so both calls land in the same second by construction,
    # instead of hoping they do.
    monkeypatch.setattr(fb, "_stamp", lambda: "20260101T000000Z")

    first = fb.enqueue("identical objective", str(tmp_path), [])
    second = fb.enqueue("identical objective", str(tmp_path), [])

    assert first != second, "the second enqueue overwrote the first"
    assert first.exists() and second.exists()
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 2


def test_a_third_collision_also_gets_its_own_name(tmp_path, monkeypatch):
    # The control for the suffix loop: one extra name is not enough if three
    # tasks arrive together.
    from daedalus import file_bridge as fb

    monkeypatch.setattr(fb, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(fb, "_stamp", lambda: "20260101T000000Z")
    paths = [fb.enqueue("same", str(tmp_path), []) for _ in range(3)]
    assert len({p.name for p in paths}) == 3, [p.name for p in paths]


def test_distinct_objectives_still_get_readable_names(tmp_path, monkeypatch):
    # The timestamp+slug shape is for a human reading the directory; the fix
    # must not turn every filename into an opaque id.
    from daedalus import file_bridge as fb

    monkeypatch.setattr(fb, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(fb, "_stamp", lambda: "20260101T000000Z")
    p = fb.enqueue("wire the compaction module", str(tmp_path), [])
    assert p.name.startswith("20260101T000000Z-wire-the-compaction-module")


def test_PARALLEL_producers_do_not_collide(tmp_path, monkeypatch):
    """The race a serial test cannot see.

    The first fix for the second-resolution collision was an existence check
    with a counter -- check-then-use. Two producers running at once both see
    the same free name and both write it, and every serial caller (including
    the acceptance check that found the original bug) goes green over it.
    Uniqueness has to come from the name, not from looking.
    """
    import threading

    from daedalus import file_bridge as fb

    monkeypatch.setattr(fb, "OUTBOX", tmp_path / "outbox")
    monkeypatch.setattr(fb, "_stamp", lambda: "20260101T000000Z")

    made, errors = [], []
    start = threading.Barrier(12)

    def worker():
        try:
            start.wait(timeout=10)
            made.append(fb.enqueue("same objective", str(tmp_path), []))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(made) == 12
    assert len({p.name for p in made}) == 12, "two producers wrote the same file"
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 12


def test_a_request_is_published_atomically(tmp_path, monkeypatch):
    """A reader never sees half a request.

    The watcher globs `*.json` on a timer. A plain `write_text` lets it pick up
    a file that is half a JSON document, so the request has to appear under a
    name the glob ignores and then be renamed into place.
    """
    from daedalus import file_bridge as fb

    monkeypatch.setattr(fb, "OUTBOX", tmp_path / "outbox")
    seen: list[list[str]] = []
    real_write = Path.write_text

    def spy(self, *a, **kw):
        result = real_write(self, *a, **kw)
        # Whatever a poller would see the instant the bytes land.
        seen.append(sorted(p.name for p in (tmp_path / "outbox").glob("*.json")))
        return result

    monkeypatch.setattr(Path, "write_text", spy)
    path = fb.enqueue("atomic probe", str(tmp_path), [])

    assert path.exists()
    # At the moment the body was written, no *.json was visible yet.
    assert seen and seen[-1] == [], (
        f"a partially written request was glob-visible: {seen[-1]}")
    assert not list((tmp_path / "outbox").glob("*.tmp")), "temp file left behind"
    assert json.loads(path.read_text(encoding="utf-8"))["objective"] == "atomic probe"
