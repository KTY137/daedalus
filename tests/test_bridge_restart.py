"""What happens when the watcher dies mid-request, and what happens on restart.

`process_request` applies four side effects in a row -- report, arrival line,
memory record, archive move -- and a crash between any two of them leaves the
request sitting in the outbox with some of them already applied. The restarted
watcher then re-globs that request and does the whole sequence again.

Measured on the pre-fix code (probe: reconstruct the old body verbatim, inject
a hard crash at each seam, restart, count artifacts):

    crash point   re-ran work   provider   reports   log lines   memory   archived
    after work        yes           2         1          1         1         1
    after report      yes           2         1          1         1         1
    after log         yes           2         1          2         1         1
    after memory      yes           2         1          2         2         1
    (no crash)         no           1         1          1         1         1

So the honest reading of the old behaviour: the work was re-dispatched at every
crash point (on a paid lane, billed twice), the arrival line and the memory
record were duplicated, and the report/archive were NOT duplicated as files --
their destination paths are fixed, so a rewrite is an overwrite. These tests
pin all four to exactly-once, and pin the two windows that remain open
(re-dispatch of interrupted work; the bound that stops it repeating forever).
"""

from __future__ import annotations

import json
import os
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from daedalus import file_bridge as fb
from daedalus import memory as memory_mod


class _Bridge:
    """A whole file bus in a temp dir, with the real functions wired to it."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.inbox = tmp / "inbox"
        self.outbox = tmp / "outbox"
        self.archive = tmp / "archive"
        self.memory_dir = tmp / "memory"
        self.outbox.mkdir(parents=True)
        self.work_calls: list[str] = []

    # -- inputs ------------------------------------------------------------
    def enqueue(self, objective: str = "the task", lane: str = "claude") -> Path:
        return fb.enqueue(objective, "/repo", [], lane=lane, source="user")

    def drop_raw(self, name: str, text: str) -> Path:
        path = self.outbox / name
        path.write_text(text, encoding="utf-8")
        return path

    # -- observations ------------------------------------------------------
    def reports(self) -> list[str]:
        return sorted(p.name for p in self.inbox.glob("*.report.json")) \
            if self.inbox.exists() else []

    def log_lines(self, key: str | None = None) -> list[str]:
        log = self.inbox / "LATEST.log"
        if not log.exists():
            return []
        lines = log.read_text(encoding="utf-8").splitlines()
        if key is None:
            return lines
        return [ln for ln in lines if ln.endswith(f" key={key}")]

    def memory_records(self, key: str | None = None) -> list[dict]:
        path = memory_mod.EVENTS_PATH
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if key is None or (rec.get("payload") or {}).get("request_file") == key:
                out.append(rec)
        return out

    def archived(self) -> list[str]:
        return sorted(p.name for p in self.archive.glob("*.json")) \
            if self.archive.exists() else []

    def queued(self) -> list[str]:
        return sorted(p.name for p in self.outbox.glob("*.json"))

    def quarantined(self) -> list[str]:
        return [row["name"] for row in fb.quarantined_requests()]


class Crash(Exception):
    """A stand-in for the process dying. Nothing catches this in the code
    under test, which is the point: it unwinds exactly like a hard kill,
    leaving whatever was already on disk on disk."""


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    b = _Bridge(tmp_path)
    monkeypatch.setattr(fb, "INBOX", b.inbox)
    monkeypatch.setattr(fb, "OUTBOX", b.outbox)
    monkeypatch.setattr(fb, "ARCHIVE", b.archive)
    monkeypatch.setattr(fb, "HEARTBEAT_PATH", tmp_path / "runs" / "hb.json")
    # The REAL memory writer runs, into a temp store, so the recovery scan in
    # _memory_already_recorded is exercised against real records.
    monkeypatch.setattr(memory_mod, "MEMORY_DIR", b.memory_dir)
    monkeypatch.setattr(memory_mod, "EVENTS_PATH", b.memory_dir / "events.local.jsonl")
    monkeypatch.setattr(memory_mod, "TODO_PATH", b.memory_dir / "todos.local.md")
    return b


@pytest.fixture
def work(bridge, monkeypatch):
    """Patch the WORK (core.process_bridge_payload) and nothing else.

    This is the provider dispatch -- the expensive, billable step -- so it is
    what a "did the restart re-run it?" test has to count. `process_request`
    itself is fully real in every test in this file."""
    def _work(payload):
        bridge.work_calls.append(payload["objective"])
        return {"bridge_status": "done", "lane": payload["lane"],
                "request": payload, "report": {"summary": "did the thing",
                                               "status": "done"}}
    m = mock.Mock(side_effect=_work)
    monkeypatch.setattr("daedalus.core.process_bridge_payload", m)
    return m


# --------------------------------------------------------------------------- #
# the restart matrix                                                           #
# --------------------------------------------------------------------------- #

def _crash_at(seam: str, bridge, monkeypatch):
    """Install a crash at one seam of process_request by making the real
    collaborator at that seam blow up. process_request stays real."""
    if seam == "work":
        real = bridge  # closure marker; the work mock is replaced below

        def boom_work(payload):
            bridge.work_calls.append(payload["objective"])
            raise Crash("died after dispatching the work, before the report")
        monkeypatch.setattr("daedalus.core.process_bridge_payload", boom_work)

    elif seam == "after_report":
        monkeypatch.setattr(fb, "_note_report_arrival",
                            mock.Mock(side_effect=Crash("died after the report")))

    elif seam == "log_landed":
        # The seam the journal flag CANNOT cover: the line is already in the
        # log, but we died before recording that it was. Only a content check
        # against the log itself keeps the restart from appending a second one.
        real_note = fb._note_report_arrival

        def note_then_die(result_path, report, key=None):
            real_note(result_path, report, key=key)  # the line IS in the log ...
            raise Crash("died after the arrival line, before the journal caught up")
        monkeypatch.setattr(fb, "_note_report_arrival", note_then_die)

    elif seam == "memory_not_landed":
        monkeypatch.setattr(fb, "record_from_bridge_report",
                            mock.Mock(side_effect=Crash("died before the append")))

    elif seam == "memory_landed":
        real_record = fb.record_from_bridge_report

        def append_then_die(report):
            real_record(report)  # the record IS on disk ...
            raise Crash("died after the append, before the journal caught up")
        monkeypatch.setattr(fb, "record_from_bridge_report", append_then_die)

    elif seam == "after_memory":
        monkeypatch.setattr(fb, "_archive_once",
                            mock.Mock(side_effect=Crash("died before the archive")))
    else:  # pragma: no cover - guard against a typo in the parametrize list
        raise AssertionError(f"unknown seam {seam}")


SEAMS = ["work", "after_report", "log_landed", "memory_not_landed",
         "memory_landed", "after_memory"]


@pytest.mark.parametrize("seam", SEAMS)
def test_restart_after_a_crash_produces_exactly_one_of_everything(
        seam, bridge, work, monkeypatch):
    """The headline property: reprocessing is idempotent at every seam.

    One report, one arrival line, one memory record, one archived copy --
    no matter where the process died.
    """
    req = bridge.enqueue()
    key = req.stem

    with monkeypatch.context() as crash:
        _crash_at(seam, bridge, crash)
        with pytest.raises(Crash):
            fb.process_request(req)

    # A crash always leaves the request queued -- that is why the restarted
    # watcher picks it up again, and why any of this matters.
    assert bridge.queued() == [req.name], "the crash did not leave work behind"

    fb.process_request(req)  # <-- the restart

    assert bridge.reports() == [f"{key}.report.json"]
    assert len(bridge.log_lines(key)) == 1, bridge.log_lines()
    assert len(bridge.memory_records(key)) == 1, bridge.memory_records(key)
    assert bridge.archived() == [req.name]
    assert bridge.queued() == []
    report = json.loads((bridge.inbox / f"{key}.report.json").read_text("utf-8"))
    assert report["bridge_status"] == "done"


@pytest.mark.parametrize("seam", SEAMS)
def test_work_is_redispatched_only_when_the_report_never_landed(
        seam, bridge, work, monkeypatch):
    """The money question, separated from the bookkeeping one.

    Re-running the work is a second provider call and, on a paid lane, a second
    bill. It is unavoidable exactly once: if we died between dispatching and
    the report landing, nothing on disk can tell us whether the provider ran.
    Every LATER seam has a complete report to reuse, and must not re-dispatch.
    """
    req = bridge.enqueue()
    with monkeypatch.context() as crash:
        _crash_at(seam, bridge, crash)
        with pytest.raises(Crash):
            fb.process_request(req)
    before = len(bridge.work_calls)
    fb.process_request(req)
    after = len(bridge.work_calls)

    if seam == "work":
        assert after == before + 1, ("a request interrupted before its report "
                                     "landed must be retried")
    else:
        assert after == before, (
            f"seam {seam}: the work was re-dispatched even though a complete "
            "report already existed -- that is a second provider bill")


def test_a_completed_request_reprocessed_outright_changes_nothing(bridge, work):
    """The blunt version: hand process_request the same request twice with no
    crash at all (a copy restored from the archive, a double-glob, a rerun of
    `file_bridge once`)."""
    req = bridge.enqueue()
    key = req.stem
    fb.process_request(req)
    archived = bridge.archive / req.name
    # put it back in the outbox, exactly as a restore-from-archive would
    restored = bridge.outbox / req.name
    restored.write_text(archived.read_text("utf-8"), encoding="utf-8")

    fb.process_request(restored)

    assert len(bridge.work_calls) == 1
    assert len(bridge.log_lines(key)) == 1
    assert len(bridge.memory_records(key)) == 1
    assert bridge.archived() == [req.name]


def test_two_different_requests_are_not_deduped_into_one(bridge, work):
    """The control for every dedupe above: the idempotency key must separate
    distinct requests, not merge them. A key that collided would make this
    file's other tests pass for entirely the wrong reason."""
    a = bridge.enqueue("first task")
    b = bridge.enqueue("second task")
    fb.process_request(a)
    fb.process_request(b)

    assert len(bridge.work_calls) == 2
    assert bridge.reports() == sorted([f"{a.stem}.report.json",
                                       f"{b.stem}.report.json"])
    assert len(bridge.log_lines(a.stem)) == 1
    assert len(bridge.log_lines(b.stem)) == 1
    assert len(bridge.memory_records(a.stem)) == 1
    assert len(bridge.memory_records(b.stem)) == 1
    assert len(bridge.archived()) == 2


def test_the_memory_recovery_scan_is_not_paid_on_the_happy_path(
        bridge, work, monkeypatch):
    """`_memory_already_recorded` reads the whole memory log. It exists only to
    resolve the one ambiguous journal state, and must never run otherwise --
    otherwise every request pays for a full scan of an ever-growing file."""
    spy = mock.Mock(side_effect=fb._memory_already_recorded)
    monkeypatch.setattr(fb, "_memory_already_recorded", spy)
    fb.process_request(bridge.enqueue())
    assert spy.call_count == 0

    req = bridge.enqueue("second")
    with monkeypatch.context() as crash:
        _crash_at("memory_landed", bridge, crash)
        with pytest.raises(Crash):
            fb.process_request(req)
    fb.process_request(req)
    assert spy.call_count == 1, "the ambiguous state must consult the memory log"


def test_an_interrupted_cross_device_archive_move_leaves_one_copy(bridge, work):
    """shutil.move across filesystems is copy-then-unlink. Killed in between,
    the request exists in BOTH the outbox and the archive; the restart must
    converge on one archived file, not two."""
    req = bridge.enqueue()
    bridge.archive.mkdir(parents=True, exist_ok=True)
    fb.process_request(req)
    # replay the interrupted move: the copy landed, the source never went away
    (bridge.outbox / req.name).write_text(
        (bridge.archive / req.name).read_text("utf-8"), encoding="utf-8")

    fb.process_request(bridge.outbox / req.name)

    assert bridge.archived() == [req.name], bridge.archived()
    assert bridge.queued() == []


def test_a_truncated_report_is_not_mistaken_for_a_finished_one(bridge, work):
    """A report left half-written by an older, non-atomic build must not be
    read back as "the work is done" -- that would hand a truncated result to
    the caller as a success."""
    req = bridge.enqueue()
    key = req.stem
    (bridge.inbox).mkdir(parents=True, exist_ok=True)
    (bridge.inbox / f"{key}.report.json").write_text(
        '{"bridge_status": "do', encoding="utf-8")  # cut mid-write
    fb._write_journal(key, {"key": key, "steps": {"report": True},
                            "attempts": 1, "state": "reported"})

    fb.process_request(req)

    assert len(bridge.work_calls) == 1, "a truncated report was reused as a receipt"
    report = json.loads((bridge.inbox / f"{key}.report.json").read_text("utf-8"))
    assert report["bridge_status"] == "done"


def test_the_report_is_published_atomically(bridge, work):
    """The inbox is polled. A plain write_text lets a reader glob a report that
    is half a JSON document.

    Note what this must NOT do: assert that *some* observed write saw an empty
    inbox. The journal is written first, so that is true even with a
    non-atomic report write -- a test that would pass for the wrong reason.
    It has to pin the moment the REPORT BODY lands.
    """
    req = bridge.enqueue()
    body_writes: list[tuple[str, list[str]]] = []
    real_write = Path.write_text

    def spy(self, *a, **kw):
        result = real_write(self, *a, **kw)
        if f"{req.stem}.report.json" in self.name:
            # whatever an inbox poller would see the instant these bytes land
            body_writes.append(
                (self.name, sorted(p.name for p in bridge.inbox.glob("*.report.json"))))
        return result

    with mock.patch.object(Path, "write_text", spy):
        fb.process_request(req)

    assert body_writes, "the report body was never written"
    for name, visible in body_writes:
        assert not name.endswith(".report.json"), (
            f"the report body was written straight to {name}, a name the inbox "
            "glob matches -- a poller can see half of it")
        assert visible == [], f"a partial report was glob-visible: {visible}"
    assert (bridge.inbox / f"{req.stem}.report.json").exists()
    assert not list(bridge.inbox.glob("*.report.json.tmp")), "temp file left behind"


# --------------------------------------------------------------------------- #
# poison input                                                                 #
# --------------------------------------------------------------------------- #

def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_malformed_json_is_quarantined_not_silently_skipped(bridge, work):
    bad = bridge.drop_raw("20260101T000000Z-poison-deadbeef.json", "{not json at all")
    _age(bad, fb.SETTLE_GRACE_S + 5)

    with pytest.raises(json.JSONDecodeError):
        fb.process_request(bad)  # the real function still refuses it
    result = fb.handle_poison_request(bad, _capture(bad))

    assert bridge.queued() == [], "poison left in the outbox = crash-loop fuel"
    assert bridge.quarantined() == [bad.name]
    assert (bridge.archive / "quarantine" / f"{bad.stem}.error.json").exists()
    report = json.loads(result.read_text("utf-8"))
    assert report["bridge_status"] == "quarantined"
    assert bridge.archived() == [], "poison must not be filed as processed work"


def _capture(path: Path) -> BaseException:
    try:
        fb._read_request(path, None)
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("expected the request to be rejected")


def test_a_half_written_request_is_left_to_settle_not_destroyed(bridge, work):
    """Our enqueue publishes atomically, but a hand-drop or a foreign producer
    does not. Quarantining a file that is merely mid-write throws away a good
    request; the cure has to be one more poll, not a bin."""
    half = bridge.drop_raw("20260101T000000Z-slow-producer-cafe0001.json",
                           '{"objective": "half a doc')
    exc = _capture(half)

    assert fb.handle_poison_request(half, exc) is None
    assert bridge.queued() == [half.name], "a mid-write request was destroyed"
    assert bridge.quarantined() == []

    # ... and once it has stopped changing, it IS poison.
    _age(half, fb.SETTLE_GRACE_S + 5)
    assert fb.handle_poison_request(half, exc) is not None
    assert bridge.quarantined() == [half.name]


def test_a_structurally_invalid_request_is_poison_immediately(bridge, work):
    """Valid JSON that is not a request is not a partial write, and must not
    get the settle grace -- otherwise the grace is a hole, not a guard."""
    bad = bridge.drop_raw("20260101T000000Z-no-objective-cafe0002.json",
                          json.dumps({"repo_root": "/r"}))
    exc = _capture(bad)
    assert isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)

    fb.handle_poison_request(bad, exc)  # fresh mtime, deliberately not aged

    assert bridge.quarantined() == [bad.name]
    assert bridge.queued() == []


def test_a_failing_quarantine_does_not_take_the_watcher_down(
        bridge, work, monkeypatch):
    """The recovery path is the last thing standing between poison and a dead
    watcher, so it must not have its own uncaught failure mode."""
    bad = bridge.drop_raw("20260101T000000Z-poison-cafe0003.json", "{{{")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    monkeypatch.setattr(fb, "quarantine_request",
                        mock.Mock(side_effect=RuntimeError("disk full")))

    assert fb.handle_poison_request(bad, _capture(bad)) is None  # no raise


def test_the_watch_loop_survives_poison_and_keeps_working(bridge, work, monkeypatch):
    """End-to-end through the REAL watch loop: a poison file and a good request
    in the same outbox. The watcher must not die, must not spin on the poison,
    and must still deliver the good request."""
    bad = bridge.drop_raw("00000000T000000Z-poison-cafe0004.json", "{ broken")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    good = bridge.enqueue("real work")

    class _Stop(Exception):
        pass

    sleeps = {"n": 0}

    def stop_after_three(_s):
        sleeps["n"] += 1
        if sleeps["n"] >= 3:
            raise _Stop
    monkeypatch.setattr(fb.time, "sleep", stop_after_three)

    with pytest.raises(_Stop):
        fb.watch(None, 0.0, project="p")

    assert sleeps["n"] == 3, "the watcher died before completing its polls"
    assert bridge.quarantined() == [bad.name]
    assert bridge.archived() == [good.name]
    assert bridge.queued() == []
    # Three polls over the poison produced ONE quarantine report and ONE line,
    # not one per poll.
    assert len(bridge.log_lines(bad.stem)) == 1, bridge.log_lines()
    assert len(bridge.work_calls) == 1


def test_a_locked_poison_file_does_not_re_report_every_poll(bridge, work, monkeypatch):
    """If the eviction itself fails (file locked by another process) the request
    stays in the outbox and is seen again next poll. That retry must not
    re-emit the report and the arrival line each time."""
    bad = bridge.drop_raw("20260101T000000Z-locked-cafe0005.json", "{ nope")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    monkeypatch.setattr(fb, "_quarantine_move", mock.Mock(return_value=False))

    for _ in range(4):
        try:
            fb.process_request(bad)
        except Exception as exc:  # noqa: BLE001
            fb.handle_poison_request(bad, exc)

    assert len(bridge.log_lines(bad.stem)) == 1, bridge.log_lines()
    assert bridge.reports() == [f"{bad.stem}.report.json"]


def test_a_request_that_hard_kills_the_process_is_not_dispatched_forever(
        bridge, monkeypatch):
    """A request that segfaults or OOMs a provider cannot be caught -- the
    process just dies with the request still queued. Without a bound the
    watcher re-dispatches (and on a paid lane re-bills) it on every restart."""
    calls = {"n": 0}

    def kill(payload):
        calls["n"] += 1
        raise Crash("provider took the process with it")
    monkeypatch.setattr("daedalus.core.process_bridge_payload", kill)

    req = bridge.enqueue()
    for _ in range(fb.MAX_ATTEMPTS + 3):
        try:
            fb.process_request(req)
        except Crash:
            pass

    assert calls["n"] == fb.MAX_ATTEMPTS, (
        f"dispatched {calls['n']} times, bound is {fb.MAX_ATTEMPTS}")
    assert bridge.quarantined() == [req.name]
    assert bridge.queued() == []
    report = json.loads((bridge.inbox / f"{req.stem}.report.json").read_text("utf-8"))
    assert report["bridge_status"] == "quarantined"
    assert "interrupted" in report["reason"]


def test_status_shows_quarantined_requests(bridge, work, capsys):
    """Quarantine is only better than silence if somebody is told."""
    bad = bridge.drop_raw("20260101T000000Z-poison-cafe0006.json", "{ bad")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    fb.handle_poison_request(bad, _capture(bad))

    status = fb.bridge_status()
    assert status["quarantined_count"] == 1
    assert status["quarantined"][0]["name"] == bad.name
    assert status["queue_depth"] == 0
    assert fb.stream_state()["quarantined_count"] == 1

    capsys.readouterr()
    fb._print_status(status)
    out = capsys.readouterr().out
    assert "QUARANTINED" in out
    assert bad.name in out
