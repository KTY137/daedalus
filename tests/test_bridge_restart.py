"""What happens when the watcher dies mid-request, and what happens on restart.

`process_request` applies five possible side effects in a row -- report, linked
conversation projection, arrival line, memory record, archive move -- and a
crash between any two of them leaves the request sitting in the outbox with
some of them already applied. The restarted watcher then re-globs that request
and does the whole sequence again.

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
their destination paths are fixed, so a rewrite is an overwrite. The generic
seam tests below retain that baseline for pre-ledger/non-provider work. The
lease-bearing integration test additionally pins the formerly ambiguous
provider-to-report window to one canonical effect and one provider invocation.
"""

from __future__ import annotations

import errno
import json
import os
import sqlite3
import threading
import time
import unittest.mock as mock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daedalus import file_bridge as fb
from daedalus import conversation as conversation_mod
from daedalus import memory as memory_mod
from daedalus import web_api


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
        # require_watcher=False: these tests manufacture request files to drive
        # process_request/restart recovery directly. There is deliberately no
        # watcher -- the test IS the consumer. The liveness guard that enqueue()
        # applies by default is exercised in tests/test_bridge_enqueue_guard.py.
        return fb.enqueue(objective, "/repo", [], lane=lane, source="user",
                          require_watcher=False)

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


class Crash(BaseException):
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
    # A report projection must never discover or mutate the developer's live
    # canonical spine while these mocked bridge tasks run.
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(tmp_path / "spine.sqlite3"))
    return b


@pytest.fixture
def work(bridge, monkeypatch):
    """Patch the WORK (core.process_bridge_payload) and nothing else.

    This is the provider dispatch -- the expensive, billable step -- so it is
    what a "did the restart re-run it?" test has to count. `process_request`
    itself is fully real in every test in this file."""
    def _work(payload, *, effect_identity=None):
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

        def boom_work(payload, *, effect_identity=None):
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
    """The pre-ledger work-stub question, separated from bookkeeping.

    This fixture deliberately replaces the canonical bridge payload consumer,
    so it has no Effect Lease to replay. It is retried only when no report
    landed; every later seam reuses the report. The next integration test runs
    the real leased consumer and proves that its provider is not retried even
    in that first window.
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


def test_atomic_report_survives_crash_before_report_journal_commit(
        bridge, work, monkeypatch):
    """The report itself closes the last report->journal crash window.

    A canonical Effect Lease prevents a second provider side effect here, but
    entering replay could still replace the original success with a failed
    ``effect_replay`` projection.  A whole, request-bound report must therefore
    be reused even while the journal's ``steps.report`` bit still says false.
    """
    req = bridge.enqueue()
    key = req.stem
    real_write_journal = fb._write_journal
    crashed = {"done": False}

    def die_before_report_journal_commit(journal_key, entry):
        if (journal_key == key and entry.get("state") == "reported"
                and not crashed["done"]):
            crashed["done"] = True
            raise Crash("report landed; report journal commit did not")
        return real_write_journal(journal_key, entry)

    with monkeypatch.context() as crash:
        crash.setattr(fb, "_write_journal", die_before_report_journal_commit)
        with pytest.raises(Crash):
            fb.process_request(req)

    report_path = bridge.inbox / f"{key}.report.json"
    original_report = report_path.read_bytes()
    assert json.loads(original_report.decode("utf-8"))["bridge_status"] == "done"
    assert fb._read_journal(key)["steps"].get("report") is not True
    assert len(bridge.work_calls) == 1

    fb.process_request(req)

    assert report_path.read_bytes() == original_report
    assert len(bridge.work_calls) == 1, "restart entered provider replay"
    assert fb._read_journal(key)["state"] == "done"
    assert bridge.queued() == []
    assert bridge.archived() == [req.name]


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("missing_status", "bridge_status"),
        ("wrong_key", "request_file"),
        ("malformed_digest", "malformed"),
        ("missing_binding", "no provable request identity"),
        ("contradictory_digest", "contradicts its request body"),
    ],
)
def test_report_request_binding_defects_fail_closed(defect, message):
    key = "task-bound-report"
    request = {"objective": "do it", "repo_root": "/repo"}
    report = {
        "bridge_status": "done",
        "request_file": key,
        "request": request,
        "request_sha256": fb._request_sha256(request),
    }
    if defect == "missing_status":
        report.pop("bridge_status")
    elif defect == "wrong_key":
        report["request_file"] = "different-task"
    elif defect == "malformed_digest":
        report["request_sha256"] = "not-a-digest"
    elif defect == "missing_binding":
        report.pop("request")
        report.pop("request_sha256")
    elif defect == "contradictory_digest":
        report["request_sha256"] = "0" * 64

    with pytest.raises(ValueError, match=message):
        fb._report_request_binding(report, key)


def test_memory_write_failure_preserves_report_and_retries_only_bookkeeping(
        bridge, work, monkeypatch, capsys):
    """A downstream store outage cannot revoke a durable provider report.

    The managed watcher must retain the original terminal artifact, leave the
    request retryable, and then resume at memory without invoking either the
    provider or the already-successful conversation projector a second time.
    """
    req = bridge.enqueue()
    key = req.stem
    real_record = fb.record_from_bridge_report
    memory_attempts = {"count": 0}

    def fail_memory_once(report):
        memory_attempts["count"] += 1
        if memory_attempts["count"] == 1:
            raise OSError("memory store temporarily unavailable")
        return real_record(report)

    project = mock.Mock(wraps=fb._project_report_to_conversation)
    note = mock.Mock(wraps=fb._note_report_arrival)
    poison = mock.Mock(wraps=fb.handle_poison_request)
    monkeypatch.setattr(fb, "record_from_bridge_report", fail_memory_once)
    monkeypatch.setattr(fb, "_project_report_to_conversation", project)
    monkeypatch.setattr(fb, "_note_report_arrival", note)
    monkeypatch.setattr(fb, "handle_poison_request", poison)

    first_poll: dict[str, object] = {}
    sleeps = {"count": 0}

    class _StopWatcher(BaseException):
        pass

    def stop_after_retry(_seconds):
        sleeps["count"] += 1
        if sleeps["count"] == 1:
            first_poll["report"] = (
                bridge.inbox / f"{key}.report.json").read_bytes()
            first_poll["journal"] = fb._read_journal(key)
            return
        raise _StopWatcher

    monkeypatch.setattr(fb.time, "sleep", stop_after_retry)
    with pytest.raises(_StopWatcher):
        fb.watch(None, 0.0, project="p")

    pending = first_poll["journal"]
    assert isinstance(pending, dict)
    assert pending["state"] == "bookkeeping_pending"
    assert pending["steps"]["report"] is True
    assert pending["steps"]["log"] is True
    assert pending["steps"]["memory"] == "pending"
    assert pending["terminal_bookkeeping_error"]["step"] == "memory"

    report_path = bridge.inbox / f"{key}.report.json"
    assert report_path.read_bytes() == first_poll["report"]
    assert len(bridge.work_calls) == 1
    assert project.call_count == 1
    assert note.call_count == 1
    assert memory_attempts["count"] == 2
    assert len(bridge.memory_records(key)) == 1
    assert poison.call_count == 0
    assert bridge.quarantined() == []
    assert bridge.queued() == []
    assert bridge.archived() == [req.name]

    finished = fb._read_journal(key)
    assert finished["state"] == "done"
    assert "terminal_bookkeeping_error" not in finished
    assert finished["terminal_bookkeeping_failures"][-1]["type"] == "OSError"
    output = capsys.readouterr().out
    assert "BOOKKEEPING PENDING" in output
    assert "QUARANTINED" not in output


def test_leased_provider_completion_survives_crash_before_bridge_report(
        bridge, tmp_path, monkeypatch):
    """Fault injection at the exact gap the file journal could not resolve.

    The real bridge consumer runs through the real Effect-Lease ledger. The
    provider implementation is a mock below ``offload`` (zero process/network
    calls). We then crash after the canonical effect is terminal but before
    ``process_request`` can publish its report. Restart must reuse the private
    filename-derived identity and receive ``effect_replay`` without invoking
    that provider a second time.
    """
    from types import SimpleNamespace

    from daedalus import budget, core, progress
    from daedalus.kernel.offload_lease import lease_ledger_path
    from daedalus.spine.killswitch import KillSwitch

    repo_root = str(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    budget_path = tmp_path / "budget.json"
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(budget_path))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "5.00")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "40")
    budget.reset_default_ledger()
    KillSwitch(repo_root=repo_root).arm(note="crash replay test")
    monkeypatch.setattr(
        progress, "_DEFAULT_LOG", progress.ProgressLog(tmp_path / "progress.jsonl")
    )

    decision = SimpleNamespace(
        provider="ollama", persona="Lucia", mode="advisory",
        reason="mocked trusted local route",
    )
    req = fb.enqueue(
        "Review the documentation wording",
        repo_root,
        ["docs/x.md"],
        lane="local_only",
        source="test",
        require_watcher=False,
    )
    real_process = core.process_bridge_payload
    dispatches: list[dict[str, str]] = []

    def process_then_crash_once(payload, *, effect_identity=None):
        dispatches.append(dict(effect_identity or {}))
        result = real_process(payload, effect_identity=effect_identity)
        if len(dispatches) == 1:
            assert result["bridge_status"] == "done"
            raise Crash("died after effect terminal, before bridge report")
        return result

    try:
        with mock.patch(
            "daedalus.core._availability_from_doctor",
            return_value={
                "claude_cli": False, "ollama": True,
                "deepseek": False, "codex_cli": False,
            },
        ), mock.patch(
            "daedalus.kairos.scheduler.route_and_select",
            return_value=({"name": "docs-dev"}, decision),
        ), mock.patch(
            "daedalus.offload._offload_impl",
            return_value={"action": "offloaded", "wrote": []},
        ) as provider, mock.patch.object(
            core, "process_bridge_payload", side_effect=process_then_crash_once
        ):
            with pytest.raises(Crash, match="after effect terminal"):
                fb.process_request(req)

            journal_after_crash = fb._read_journal(req.stem)
            assert journal_after_crash["state"] == "in_flight"
            assert journal_after_crash["effect_identity"] == dispatches[0]
            assert bridge.queued() == [req.name]

            result_path = fb.process_request(req)

        report = json.loads(result_path.read_text(encoding="utf-8"))
        assert provider.call_count == 1
        assert dispatches[0] == dispatches[1]
        assert report["bridge_status"] == "failed"
        assert "idempotent replay refused" in report["error"]
        assert bridge.queued() == []
        assert bridge.archived() == [req.name]
        assert fb._read_journal(req.stem)["state"] == "done"

        # One exact lease and one terminal execution are the authority for the
        # second call's refusal; the bridge journal is not a side effect ledger.
        with sqlite3.connect(lease_ledger_path(repo_root)) as connection:
            leases = connection.execute(
                "SELECT lease_id FROM effect_leases"
            ).fetchall()
            executions = connection.execute(
                "SELECT state FROM effect_executions"
            ).fetchall()
        assert leases == [(dispatches[0]["lease_id"],)]
        assert executions == [("COMPLETED",)]

        budget_doc = json.loads(budget_path.read_text(encoding="utf-8"))
        opens = [row for row in budget_doc["entries"]
                 if row.get("kind") == "envelope_open"]
        assert len(opens) == 1, "effect replay opened a second spend envelope"
    finally:
        budget.reset_default_ledger()


def test_request_json_cannot_choose_the_internal_effect_identity(
        bridge, monkeypatch):
    supplied = {
        "attempt_id": "caller-attempt",
        "lease_id": "caller-lease",
        "issued_at": "2000-01-01T00:00:00.000000+00:00",
    }
    payload = {
        "objective": "review docs",
        "repo_root": "/repo",
        "paths": [],
        "lane": "local_only",
        "strategy": "single",
        "effect_identity": supplied,
    }
    req = bridge.drop_raw(
        "20260831T000000Z-review-docs-cafebabe.json", json.dumps(payload)
    )
    captured: list[dict[str, str]] = []

    def work(request, *, effect_identity=None):
        captured.append(dict(effect_identity or {}))
        return {
            "bridge_status": "done",
            "lane": request["lane"],
            "request": request,
            "report": {"summary": "done", "status": "done"},
        }

    monkeypatch.setattr("daedalus.core.process_bridge_payload", work)
    fb.process_request(req)

    journal = fb._read_journal(req.stem)
    assert captured == [journal["effect_identity"]]
    assert captured[0] != supplied
    assert captured[0]["attempt_id"].startswith("file-bridge-")
    assert captured[0]["lease_id"].endswith("-lease")


def test_configure_crash_retries_a_convergent_local_upsert_not_a_provider(
        bridge, tmp_path, monkeypatch):
    """Keep the leased guarantee scoped honestly to provider dispatch.

    ``strategy=configure`` writes a role locally and never enters
    ``WaveExecutor``.  After a completed create loses its outer report, retry
    performs the same deterministic upsert (reported as an update) and reaches
    the same normalized file content.  This is safe convergence, not a claim
    that every bridge strategy owns a canonical leased exactly-once effect.
    """
    from daedalus import agents_registry, core

    repo = tmp_path / "configure-project"
    repo.mkdir()
    payload = {
        "objective": "configure the documentation role",
        "repo_root": str(repo),
        "paths": [],
        "lane": "local_only",
        "source": "test",
        "strategy": "configure",
        "role": {
            "name": "doc-bot",
            "model_tier": "haiku",
            "owns": ["docs/**"],
            "output_schema": "agent_report_v1",
        },
    }
    req = bridge.drop_raw(
        "20260831T000000Z-configure-doc-bot-deadbeef.json",
        json.dumps(payload),
    )
    real_process = core.process_bridge_payload
    actions: list[str] = []

    def configure_then_crash_once(payload, *, effect_identity=None):
        result = real_process(payload, effect_identity=effect_identity)
        actions.append(result["result"]["action"])
        if len(actions) == 1:
            raise Crash("died after configure write, before bridge report")
        return result

    monkeypatch.setattr(
        core, "process_bridge_payload", configure_then_crash_once
    )
    with pytest.raises(Crash, match="after configure write"):
        fb.process_request(req)

    first_config = agents_registry.get_role("doc-bot", str(repo))
    assert first_config is not None
    result_path = fb.process_request(req)

    report = json.loads(result_path.read_text(encoding="utf-8"))
    assert actions == ["created", "updated"]
    assert report["bridge_status"] == "done"
    assert report["result"]["config"] == first_config
    assert agents_registry.get_role("doc-bot", str(repo)) == first_config
    assert bridge.queued() == []
    assert bridge.archived() == [req.name]


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


def test_memory_provenance_uses_observed_provider_not_requested_lane(
        bridge, monkeypatch):
    req = bridge.enqueue(lane="claude")

    def observed_local(payload, *, effect_identity=None):
        bridge.work_calls.append(payload["objective"])
        return {
            "bridge_status": "done", "lane": payload["lane"],
            "requested_lane": payload["lane"],
            "actual_providers": ["ollama"], "request": payload,
            "report": {"summary": "did the thing", "status": "done"},
        }

    monkeypatch.setattr(
        "daedalus.core.process_bridge_payload", observed_local)
    fb.process_request(req)

    (event,) = bridge.memory_records(req.stem)
    assert event["source"] == "file_bridge:ollama"


def test_concurrent_consumers_serialize_one_request_and_publish_one_success(
        bridge, monkeypatch):
    """A watcher/``once`` race has one claimant and one completed-report reader.

    The first consumer is held inside provider work while the second enters the
    same public ``process_request`` path.  The loser must wait for the per-key
    OS claim, then reuse the winner's report after the request is archived.  It
    must never dispatch or publish an ``effect_replay`` failure over success.
    """
    req = bridge.enqueue()
    key = req.stem
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow_work(payload, *, effect_identity=None):
        calls.append(payload["objective"])
        started.set()
        if not release.wait(5.0):
            raise AssertionError("test did not release the winning consumer")
        return {
            "bridge_status": "done",
            "lane": payload["lane"],
            "request": payload,
            "report": {"summary": "did the thing", "status": "done"},
        }

    monkeypatch.setattr("daedalus.core.process_bridge_payload", slow_work)
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(fb.process_request, req)
        assert started.wait(2.0), "first consumer never reached provider work"
        loser = pool.submit(fb.process_request, req)
        time.sleep(0.15)
        assert not loser.done(), "second consumer did not wait on the request claim"
        assert calls == ["the task"]
        release.set()
        winner_path = winner.result(timeout=5.0)
        loser_path = loser.result(timeout=5.0)

    assert winner_path == loser_path == bridge.inbox / f"{key}.report.json"
    assert calls == ["the task"]
    report = json.loads(winner_path.read_text(encoding="utf-8"))
    assert report["bridge_status"] == "done"
    assert report["report"]["status"] == "done"
    assert len(bridge.log_lines(key)) == 1
    assert len(bridge.memory_records(key)) == 1
    assert bridge.archived() == [req.name]
    assert bridge.queued() == []


@pytest.mark.skipif(os.name != "nt", reason="Windows CRT retry contract")
def test_blocking_request_claim_retries_beyond_crt_ten_attempt_limit(
        tmp_path, monkeypatch):
    """Blocking request claims do not inherit ``LK_LOCK``'s ten-try ceiling."""
    import msvcrt

    real_locking = msvcrt.locking
    attempts = 0

    def contended_then_available(fd, mode, nbytes):
        nonlocal attempts
        if mode == msvcrt.LK_NBLCK:
            attempts += 1
            if attempts <= 12:
                raise OSError(errno.EACCES, "synthetic lock contention")
        return real_locking(fd, mode, nbytes)

    monkeypatch.setattr(msvcrt, "locking", contended_then_available)
    monkeypatch.setattr(fb.time, "sleep", lambda _seconds: None)

    with fb._BridgeWatcherLock(
        tmp_path / "request.process.lock", blocking=True,
        label="synthetic request claim",
    ):
        pass

    assert attempts == 13


def test_completed_filename_key_rejects_a_different_request_body(
        bridge, work):
    """A caller-controlled stem cannot alias a previous request identity."""
    req = bridge.enqueue(objective="first body")
    key = req.stem
    result_path = fb.process_request(req)
    journal_path = fb._journal_path(key)
    archived_path = bridge.archive / req.name
    original_report = result_path.read_bytes()
    original_journal = journal_path.read_bytes()
    original_archive = archived_path.read_bytes()

    contradictory = json.loads(original_archive.decode("utf-8"))
    contradictory["objective"] = "different body under the same filename"
    replacement = bridge.drop_raw(req.name, json.dumps(contradictory))

    with pytest.raises(fb.RequestIdentityConflict) as caught:
        fb.process_request(replacement)

    conflict = caught.value
    assert conflict.key == key
    assert conflict.expected != conflict.observed
    assert conflict.moved is True
    assert conflict.quarantine_path.exists()
    quarantined = json.loads(conflict.quarantine_path.read_text(encoding="utf-8"))
    assert quarantined["objective"] == "different body under the same filename"
    sidecar = conflict.quarantine_path.with_name(
        f"{conflict.quarantine_path.stem}.error.json"
    )
    detail = json.loads(sidecar.read_text(encoding="utf-8"))
    assert detail["reason"] == "request_identity_conflict"
    assert detail["expected_request_sha256"] == conflict.expected
    assert detail["observed_request_sha256"] == conflict.observed

    assert result_path.read_bytes() == original_report
    assert journal_path.read_bytes() == original_journal
    assert archived_path.read_bytes() == original_archive
    report = json.loads(original_report.decode("utf-8"))
    assert report["bridge_status"] == "done"
    assert report["request"]["objective"] == "first body"
    assert report["request_sha256"] == conflict.expected
    assert len(bridge.work_calls) == 1
    assert len(bridge.log_lines(key)) == 1
    assert len(bridge.memory_records(key)) == 1
    assert bridge.queued() == []


def test_identity_conflict_sidecar_failure_cannot_overwrite_old_report(
        bridge, work, monkeypatch):
    """Conflict recovery I/O remains conflict-owned, never generic poison."""
    req = bridge.enqueue(objective="authoritative body")
    key = req.stem
    result_path = fb.process_request(req)
    journal_path = fb._journal_path(key)
    archived_path = bridge.archive / req.name
    original_report = result_path.read_bytes()
    original_journal = journal_path.read_bytes()
    original_archive = archived_path.read_bytes()

    contradictory = json.loads(original_archive.decode("utf-8"))
    contradictory["objective"] = "conflicting newcomer"
    replacement = bridge.drop_raw(req.name, json.dumps(contradictory))
    real_write = fb._write_json_atomic

    def fail_conflict_sidecar(path, payload):
        if path.parent == bridge.archive / "quarantine":
            raise OSError("conflict sidecar storage unavailable")
        return real_write(path, payload)

    monkeypatch.setattr(fb, "_write_json_atomic", fail_conflict_sidecar)
    poison = mock.Mock(wraps=fb.handle_poison_request)
    monkeypatch.setattr(fb, "handle_poison_request", poison)

    with pytest.raises(fb.RequestIdentityConflict) as caught:
        fb.process_request(replacement)

    conflict = caught.value
    assert conflict.moved is False
    assert isinstance(conflict.quarantine_error, OSError)
    assert replacement.exists(), "failed diagnostic must leave newcomer retryable"
    poison.assert_not_called()
    assert result_path.read_bytes() == original_report
    assert journal_path.read_bytes() == original_journal
    assert archived_path.read_bytes() == original_archive
    assert len(bridge.work_calls) == 1


def test_generic_poison_recovery_cannot_overwrite_a_durable_report(
        bridge, work, capsys):
    req = bridge.enqueue(objective="first body")
    key = req.stem
    result_path = fb.process_request(req)
    original_report = result_path.read_bytes()
    # Lose the recovery proof too: the terminal artifact alone remains
    # authoritative and must not be replaced by generic poison handling.
    fb._journal_path(key).write_text("{corrupt journal", encoding="utf-8")
    damaged_journal = fb._journal_path(key).read_bytes()
    original_archive = (bridge.archive / req.name).read_bytes()
    restored = bridge.drop_raw(req.name, "{truncated replacement")

    result = fb.handle_poison_request(
        restored, ValueError("restored request is malformed"))

    assert result == result_path
    assert result_path.read_bytes() == original_report
    assert fb._journal_path(key).read_bytes() == damaged_journal
    assert (bridge.archive / req.name).read_bytes() == original_archive
    assert bridge.queued() == [req.name]
    assert bridge.quarantined() == []
    assert len(bridge.work_calls) == 1
    output = capsys.readouterr().out
    assert "REPORT PRESERVED" in output
    assert "QUARANTINED" not in output


def test_a_linked_terminal_report_projects_one_honest_conversation_outcome(
        bridge, work):
    req = bridge.enqueue()
    with conversation_mod.ConversationStore() as store:
        turn = store.append_turn(
            "c1", user_message="do it", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", req.stem, turn_id=turn.id, kind="queue_task")

        fb.process_request(req)

        status = store.dispatch_status(req.stem)
        reports = [event for event in status["events"]
                   if event.lifecycle == conversation_mod.LIFECYCLE_REPORTED]
        assert len(reports) == 1
        event = reports[0]
        assert event.outcome_state == conversation_mod.PRESENT
        assert "applied" in event.summary
        assert event.source_event_id == f"file_bridge.report:{req.stem}"
        assert event.detail == {
            "source": "file_bridge.report",
            "request_file": req.stem,
            "bridge_status": "done",
            "lane": "claude",
            "requested_lane": "claude",
            "actual_providers": [],
            "reported_status": "done",
            "reported_summary": "did the thing",
            "error": None,
            "applied": None,
            "application_reason": (
                "bridge completion alone is not application evidence"),
        }


def test_restart_after_conversation_projection_does_not_duplicate_the_event(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", req.stem, kind="queue_task")

        # Projection happens immediately before the arrival-line seam. The
        # crash therefore leaves the canonical fact committed but the request
        # queued, exactly the ambiguous restart window this test must close.
        with monkeypatch.context() as crash:
            _crash_at("after_report", bridge, crash)
            with pytest.raises(Crash):
                fb.process_request(req)
        fb.process_request(req)

        reports = store.spine.intents_by_effect_key(
            req.stem, kind=conversation_mod.KIND_REPORT)
        assert len(reports) == 1


def test_projection_failure_keeps_terminal_report_and_retries_without_provider(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", req.stem, kind="queue_task")

        with monkeypatch.context() as broken:
            broken.setattr(
                conversation_mod, "default_store",
                mock.Mock(side_effect=OSError("spine temporarily unavailable")))
            with pytest.raises(fb.ConversationProjectionPending):
                fb.process_request(req)

        # Provider work and its terminal report remain facts. Cleanup is held
        # so the next pass retries only the canonical projection; this is not
        # poison and must not be moved to quarantine.
        assert len(bridge.work_calls) == 1
        assert bridge.reports() == [f"{req.stem}.report.json"]
        assert bridge.queued() == [req.name]
        assert bridge.archived() == []
        assert bridge.quarantined() == []
        assert fb._read_journal(req.stem)["steps"]["report"] is True

        fb.process_request(req)

        assert len(bridge.work_calls) == 1, "projection retry re-ran the provider"
        assert len(store.spine.intents_by_effect_key(
            req.stem, kind=conversation_mod.KIND_REPORT)) == 1
        assert bridge.archived() == [req.name]
        assert bridge.queued() == []


@pytest.mark.parametrize("failure", [
    conversation_mod.UnknownDispatch("dispatch disappeared"),
    conversation_mod.ConflictingDispatchEvent("source identity conflict"),
    sqlite3.IntegrityError("constraint failed"),
    sqlite3.OperationalError("no such table: intents"),
    PermissionError("permission denied"),
    OSError("unclassified I/O failure"),
    ValueError("malformed projection payload"),
], ids=["unknown-dispatch", "source-conflict", "sqlite-integrity",
        "sqlite-permanent", "permission", "unclassified-io", "malformed"])
def test_permanent_projection_failures_keep_their_type_and_are_not_pending(
        bridge, monkeypatch, failure):
    key = "task-permanent-error"
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, kind="queue_task")

    failing_store = mock.Mock()
    failing_store.dispatch_status.return_value = {"lifecycle": "dispatched"}
    failing_store.record_dispatch_event.side_effect = failure
    monkeypatch.setattr(conversation_mod, "default_store",
                        mock.Mock(return_value=failing_store))

    with pytest.raises(type(failure)) as caught:
        fb._project_report_to_conversation(key, {"bridge_status": "done"})

    assert caught.value is failure


def test_sqlite_lock_projection_failure_is_transient_pending(
        bridge, monkeypatch):
    key = "task-locked-store"
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, kind="queue_task")

    locked = sqlite3.OperationalError("database is locked")
    failing_store = mock.Mock()
    failing_store.dispatch_status.return_value = {"lifecycle": "dispatched"}
    failing_store.record_dispatch_event.side_effect = locked
    monkeypatch.setattr(conversation_mod, "default_store",
                        mock.Mock(return_value=failing_store))

    with pytest.raises(fb.ConversationProjectionPending) as caught:
        fb._project_report_to_conversation(key, {"bridge_status": "done"})

    assert caught.value.cause is locked


def test_mutated_report_after_projection_is_not_requeued_or_redispatched(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    key = req.stem
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, kind="queue_task")
        fb.process_request(req)

        report_path = bridge.inbox / f"{key}.report.json"
        mutated = json.loads(report_path.read_text(encoding="utf-8"))
        mutated["report"]["summary"] = "a different terminal claim"
        fb._write_json_atomic(report_path, mutated)
        requeue = mock.Mock(wraps=fb._requeue_for_projection)
        monkeypatch.setattr(fb, "_requeue_for_projection", requeue)

        with pytest.raises(conversation_mod.ConflictingDispatchEvent):
            fb.reconcile_conversation_report(key)

        requeue.assert_not_called()
        assert bridge.queued() == []
        assert bridge.archived() == [req.name]
        assert len(bridge.work_calls) == 1
        reports = store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)
        assert len(reports) == 1
        assert reports[0].payload["detail"]["reported_summary"] == "did the thing"


def test_watcher_preserves_report_and_evicts_initial_projection_conflict(
        bridge, work, monkeypatch, capsys):
    req = bridge.enqueue()
    key = req.stem
    with conversation_mod.ConversationStore() as store:
        seed_turn = store.append_turn(
            "seed", user_message="seed", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("seed", "seed-dispatch", turn_id=seed_turn.id)
        store.record_dispatch_event(
            "seed-dispatch", outcome_state=conversation_mod.PRESENT,
            summary="different first claim", detail={"version": 1},
            source_event_id=f"file_bridge.report:{key}")
        turn = store.append_turn(
            "c1", user_message="do it", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, turn_id=turn.id, kind="queue_task")

        class _StopWatcher(Exception):
            pass

        sleeps = {"count": 0}

        def stop_after_two_polls(_seconds):
            sleeps["count"] += 1
            if sleeps["count"] >= 2:
                raise _StopWatcher

        monkeypatch.setattr(fb.time, "sleep", stop_after_two_polls)
        with pytest.raises(_StopWatcher):
            fb.watch(None, 0.0, project="p")

        assert sleeps["count"] == 2, "the permanent conflict kept being processed"
        assert len(bridge.work_calls) == 1
        assert bridge.queued() == []
        assert bridge.archived() == [req.name]
        assert bridge.quarantined() == []
        report = json.loads(
            (bridge.inbox / f"{key}.report.json").read_text(encoding="utf-8"))
        assert report["bridge_status"] == "done"
        assert report["report"]["summary"] == "did the thing"
        journal = fb._read_journal(key)
        assert journal["state"] == "done_with_projection_error"
        assert journal["conversation_projection_error"]["type"] == (
            "ConflictingDispatchEvent")
        assert len(store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)) == 0

    output = capsys.readouterr().out
    assert "PROJECTION ERROR" in output
    assert "ConflictingDispatchEvent" in output
    assert "QUARANTINED" not in output


def test_projection_error_cleanup_retry_skips_provider_and_projector(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    key = req.stem
    with conversation_mod.ConversationStore() as store:
        seed_turn = store.append_turn(
            "seed", user_message="seed", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("seed", "seed-dispatch", turn_id=seed_turn.id)
        store.record_dispatch_event(
            "seed-dispatch", outcome_state=conversation_mod.PRESENT,
            summary="different first claim", detail={"version": 1},
            source_event_id=f"file_bridge.report:{key}")
        turn = store.append_turn(
            "c1", user_message="do it", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, turn_id=turn.id, kind="queue_task")

        real_project = fb._project_report_to_conversation
        project = mock.Mock(wraps=real_project)
        monkeypatch.setattr(fb, "_project_report_to_conversation", project)
        real_archive = fb._archive_once
        archive_calls = {"count": 0}

        def locked_once(path, request_key):
            archive_calls["count"] += 1
            if archive_calls["count"] == 1:
                return False
            return real_archive(path, request_key)

        monkeypatch.setattr(fb, "_archive_once", locked_once)

        with pytest.raises(fb.ConversationProjectionFailed):
            fb.process_request(req)

        assert bridge.queued() == [req.name]
        assert fb._read_journal(key)["state"] == "projection_failed"
        assert len(bridge.work_calls) == 1
        assert project.call_count == 1

        fb.process_request(req)

        assert len(bridge.work_calls) == 1
        assert project.call_count == 1, "cleanup retry repeated a permanent conflict"
        assert bridge.queued() == []
        assert bridge.archived() == [req.name]
        assert fb._read_journal(key)["state"] == "done_with_projection_error"
        report = json.loads(
            (bridge.inbox / f"{key}.report.json").read_text(encoding="utf-8"))
        assert report["bridge_status"] == "done"


def test_report_that_wins_the_enqueue_link_race_is_reconciled_once(
        bridge, work):
    req = bridge.enqueue()
    key = req.stem

    # The fast watcher wins: report and archive exist before the API records a
    # conversation link. The report-owned arrival call correctly did nothing
    # at that instant because no link existed yet.
    fb.process_request(req)
    assert len(bridge.work_calls) == 1

    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, kind="queue_task")
        assert store.dispatch_status(key)["latest"].lifecycle == (
            conversation_mod.LIFECYCLE_DISPATCHED)

        # Model the API's post-link check racing a normal report projection.
        # Both use the same source_event_id, so SQLite must return one fact.
        with ThreadPoolExecutor(max_workers=2) as pool:
            projected = list(pool.map(
                lambda _: fb.reconcile_conversation_report(key), range(2)))

        assert projected[0].id == projected[1].id
        reports = store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)
        assert len(reports) == 1
        assert store.dispatch_status(key)["latest"].outcome_state == (
            conversation_mod.PRESENT)
        assert len(bridge.work_calls) == 1


def test_late_reconcile_failure_requeues_only_projection_not_provider(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    key = req.stem
    fb.process_request(req)  # report + archive win before the link
    assert bridge.archived() == [req.name]

    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, kind="queue_task")
        with monkeypatch.context() as broken:
            broken.setattr(
                conversation_mod, "default_store",
                mock.Mock(side_effect=OSError("spine temporarily unavailable")))
            with pytest.raises(fb.ConversationProjectionPending) as caught:
                fb.reconcile_conversation_report(key)

        assert caught.value.retry_queued is True
        assert bridge.queued() == [req.name]
        assert bridge.archived() == []
        assert len(bridge.work_calls) == 1

        fb.process_request(bridge.outbox / req.name)

        assert len(bridge.work_calls) == 1, "late retry re-ran provider work"
        assert len(store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)) == 1
        assert bridge.queued() == []
        assert bridge.archived() == [req.name]


def test_late_projection_is_not_requeued_without_report_reuse_proof(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    key = req.stem
    fb.process_request(req)
    # Simulate lost/corrupt recovery metadata. The report still exists, but
    # process_request would not know to reuse it; requeueing could re-bill.
    fb._write_journal(key, {"key": key, "steps": {}, "state": "unknown"})
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key)
        with monkeypatch.context() as broken:
            broken.setattr(
                conversation_mod, "default_store",
                mock.Mock(side_effect=OSError("spine temporarily unavailable")))
            with pytest.raises(fb.ConversationProjectionPending) as caught:
                fb.reconcile_conversation_report(key)

    assert caught.value.retry_queued is False
    assert bridge.queued() == []
    assert bridge.archived() == [req.name]
    assert len(bridge.work_calls) == 1


def test_report_reconciliation_rejects_non_key_paths(bridge):
    with pytest.raises(ValueError, match="plain file-bridge request key"):
        fb.reconcile_conversation_report("../outside")
    with pytest.raises(ValueError, match="plain file-bridge request key"):
        fb.reconcile_conversation_report("C:\\outside")


def test_queue_response_keeps_successful_link_true_when_projection_is_pending(
        bridge, monkeypatch):
    with conversation_mod.ConversationStore() as store:
        turn = store.append_turn("c1", user_message="do it", intent="enqueue",
                                 status=conversation_mod.STATUS_PROPOSED)
        body = {
            "project": "p", "objective": "do it", "conversation_id": "c1",
            "turn_id": turn.id,
        }
        pending = fb.ConversationProjectionPending(
            "task-1", OSError("spine temporarily unavailable"))
        pending.retry_queued = True
        monkeypatch.setattr(web_api, "_read_body", lambda _handler: body)
        monkeypatch.setattr(
            web_api.core, "queue_task",
            mock.Mock(return_value={"queued": str(bridge.outbox / "task-1.json")}))
        monkeypatch.setattr(conversation_mod, "default_store", lambda: store)
        monkeypatch.setattr(
            fb, "reconcile_conversation_report", mock.Mock(side_effect=pending))

        handler = object.__new__(web_api.DaedalusHandler)
        handler.path = "/api/queue"
        captured: dict[str, object] = {}
        handler._send_json = lambda payload, status=200: captured.update(
            payload=payload, status=status)
        handler._handle_post()

    result = captured["payload"]
    link = result["conversation_link"]
    assert link["linked"] is True
    assert link["turn_id"] == turn.id
    assert link["projection_pending"] is True
    assert link["projection_retry_queued"] is True
    assert link["projection"]["state"] == "pending"
    assert "temporarily unavailable" in link["projection"]["error"]


def test_queue_response_surfaces_permanent_projection_conflict_without_retry(
        bridge, work, monkeypatch):
    req = bridge.enqueue()
    key = req.stem
    fb.process_request(req)  # report and archive exist before the API link

    with conversation_mod.ConversationStore() as store:
        seed_turn = store.append_turn(
            "seed", user_message="seed", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("seed", "seed-dispatch", turn_id=seed_turn.id)
        # Model a durable first claim whose source identity is later paired
        # with a different report body. This is an integrity disagreement,
        # never temporary store unavailability.
        store.record_dispatch_event(
            "seed-dispatch", outcome_state=conversation_mod.PRESENT,
            summary="first terminal claim", detail={"version": 1},
            source_event_id=f"file_bridge.report:{key}")
        turn = store.append_turn(
            "c1", user_message="do it", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)

        body = {
            "project": "p", "objective": "do it", "conversation_id": "c1",
            "turn_id": turn.id,
        }
        monkeypatch.setattr(web_api, "_read_body", lambda _handler: body)
        monkeypatch.setattr(
            web_api.core, "queue_task",
            mock.Mock(return_value={"queued": str(bridge.outbox / req.name)}))
        requeue = mock.Mock(wraps=fb._requeue_for_projection)
        monkeypatch.setattr(fb, "_requeue_for_projection", requeue)

        handler = object.__new__(web_api.DaedalusHandler)
        handler.path = "/api/queue"
        captured: dict[str, object] = {}
        handler._send_json = lambda payload, status=200: captured.update(
            payload=payload, status=status)
        handler._handle_post()

    link = captured["payload"]["conversation_link"]
    assert link["linked"] is True
    assert link["turn_id"] == turn.id
    assert link["projection"]["state"] == "error"
    assert "ConflictingDispatchEvent" in link["projection"]["error"]
    assert "projection_pending" not in link
    assert "projection_retry_queued" not in link
    requeue.assert_not_called()
    assert bridge.queued() == []
    assert bridge.archived() == [req.name]
    assert len(bridge.work_calls) == 1


@pytest.mark.parametrize("bad_turn_id", [None, True, 1.9, 0, -1, "1"])
def test_queue_refuses_ambiguous_conversation_link_before_enqueue(
        bridge, monkeypatch, bad_turn_id):
    body = {
        "project": "p", "objective": "do it", "conversation_id": "c1",
        "turn_id": bad_turn_id,
    }
    queue = mock.Mock()
    monkeypatch.setattr(web_api, "_read_body", lambda _handler: body)
    monkeypatch.setattr(web_api.core, "queue_task", queue)

    handler = object.__new__(web_api.DaedalusHandler)
    handler.path = "/api/queue"
    captured: dict[str, object] = {}
    handler._send_json = lambda payload, status=200: captured.update(
        payload=payload, status=status)
    handler._handle_post()

    queue.assert_not_called()
    assert captured["status"] == 400
    assert "positive turn_id" in captured["payload"]["error"]


def test_an_unlinked_task_keeps_the_conversation_spine_unchanged(bridge, work):
    # Create an isolated canonical spine so this proves "no event", not merely
    # the early return used when no spine exists at all.
    with conversation_mod.ConversationStore() as store:
        before = store.spine.recent_intents(kind=conversation_mod.KIND_REPORT)
        req = bridge.enqueue()
        fb.process_request(req)
        after = store.spine.recent_intents(kind=conversation_mod.KIND_REPORT)

    assert before == after == []
    assert bridge.archived() == [req.name]
    assert bridge.reports() == [f"{req.stem}.report.json"]


def test_a_linked_failed_report_is_degraded_and_application_stays_unknown(
        bridge, monkeypatch):
    req = bridge.enqueue()

    def fail(payload, *, effect_identity=None):
        return {"bridge_status": "failed", "lane": payload["lane"],
                "request": payload, "error": "executor unavailable"}

    monkeypatch.setattr("daedalus.core.process_bridge_payload", fail)
    with conversation_mod.ConversationStore() as store:
        store.append_turn("c1", user_message="do it", intent="enqueue",
                          status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", req.stem, kind="queue_task")
        fb.process_request(req)

        latest = store.dispatch_status(req.stem)["latest"]
        assert latest.outcome_state == conversation_mod.DEGRADED
        assert latest.detail["applied"] is None
        assert "on-disk outcome is unproven" in (
            latest.detail["application_reason"])
        assert latest.detail["error"] == "executor unavailable"


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


def test_quarantine_projection_conflict_is_visible_and_does_not_spin(
        bridge, work, capsys):
    bad = bridge.drop_raw("20260101T000000Z-poison-conflict.json", "{broken")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    key = bad.stem
    with conversation_mod.ConversationStore() as store:
        seed_turn = store.append_turn(
            "seed", user_message="seed", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("seed", "seed-dispatch", turn_id=seed_turn.id)
        store.record_dispatch_event(
            "seed-dispatch", outcome_state=conversation_mod.PRESENT,
            summary="different first claim", detail={"version": 1},
            source_event_id=f"file_bridge.report:{key}")
        turn = store.append_turn(
            "c1", user_message="do it", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, turn_id=turn.id, kind="queue_task")

        result = fb.handle_poison_request(bad, _capture(bad))

        assert result == bridge.inbox / f"{key}.report.json"
        assert bridge.queued() == []
        assert bridge.quarantined() == [bad.name]
        assert len(bridge.work_calls) == 0
        report = json.loads(result.read_text(encoding="utf-8"))
        assert report["bridge_status"] == "quarantined"
        assert fb._read_journal(key)["conversation_projection_error"]["type"] == (
            "ConflictingDispatchEvent")
        assert len(store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)) == 0

    output = capsys.readouterr().out
    assert "QUARANTINED" in output
    assert "PROJECTION ERROR" in output
    assert "QUARANTINE FAILED" not in output


def test_transient_quarantine_projection_resumes_exact_report_without_provider(
        bridge, work, monkeypatch):
    """A transient spine failure resumes the raw-bound quarantine, not work."""
    bad = bridge.drop_raw(
        "20260101T000000Z-poison-transient.json", "{malformed raw bytes"
    )
    _age(bad, fb.SETTLE_GRACE_S + 5)
    key = bad.stem

    with conversation_mod.ConversationStore() as store:
        turn = store.append_turn(
            "c1", user_message="bad imported request", intent="enqueue",
            status=conversation_mod.STATUS_PROPOSED)
        store.link_dispatch("c1", key, turn_id=turn.id, kind="queue_task")

        with monkeypatch.context() as unavailable:
            unavailable.setattr(
                conversation_mod,
                "default_store",
                mock.Mock(side_effect=OSError("spine temporarily unavailable")),
            )
            first_path = fb.handle_poison_request(bad, _capture(bad))

        assert first_path == bridge.inbox / f"{key}.report.json"
        first_report_bytes = first_path.read_bytes()
        assert json.loads(first_report_bytes.decode("utf-8"))[
            "bridge_status"
        ] == "quarantined"
        first_journal = fb._read_journal(key)
        assert first_journal["state"] == "quarantine_pending"
        assert first_journal["quarantine_record"]["request_raw_sha256"] == (
            fb._raw_request_sha256(bad)
        )
        assert bridge.reports() == [f"{key}.report.json"]
        assert bridge.queued() == [bad.name]
        assert bridge.quarantined() == []
        assert len(store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)) == 0
        assert bridge.work_calls == []

        second_path = fb.process_request(bad)

        assert second_path == first_path
        assert second_path.read_bytes() == first_report_bytes
        assert fb._read_journal(key)["state"] == "quarantined"
        events = store.spine.intents_by_effect_key(
            key, kind=conversation_mod.KIND_REPORT)
        assert len(events) == 1
        assert store.dispatch_status(key)["latest"].outcome_state == (
            conversation_mod.DEGRADED)
        assert bridge.work_calls == []
        assert bridge.queued() == []
        assert bridge.quarantined() == [bad.name]


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


def test_a_locked_poison_file_does_not_re_report_every_poll(
        bridge, work, monkeypatch, capsys):
    """If the eviction itself fails (file locked by another process) the request
    stays in the outbox and is seen again next poll. That retry must not
    re-emit the report and the arrival line each time."""
    bad = bridge.drop_raw("20260101T000000Z-locked-cafe0005.json", "{ nope")
    _age(bad, fb.SETTLE_GRACE_S + 5)
    real_move = fb._quarantine_move
    lock = {"held": True}

    def move_when_unlocked(path, key):
        return False if lock["held"] else real_move(path, key)

    move = mock.Mock(side_effect=move_when_unlocked)
    monkeypatch.setattr(fb, "_quarantine_move", move)

    report_path = fb.handle_poison_request(bad, _capture(bad))
    report_bytes = report_path.read_bytes()
    for _ in range(3):
        with pytest.raises(fb.QuarantineMovePending):
            fb.process_request(bad)

    assert len(bridge.log_lines(bad.stem)) == 1, bridge.log_lines()
    assert bridge.reports() == [f"{bad.stem}.report.json"]
    assert fb._read_journal(bad.stem)["state"] == "quarantine_move_pending"
    assert bridge.queued() == [bad.name]
    assert bridge.quarantined() == []
    output = capsys.readouterr().out
    assert "QUARANTINE MOVE PENDING" in output
    assert "QUARANTINED" not in output

    lock["held"] = False
    assert fb.process_request(bad) == report_path

    assert report_path.read_bytes() == report_bytes
    assert len(bridge.log_lines(bad.stem)) == 1, bridge.log_lines()
    assert fb._read_journal(bad.stem)["state"] == "quarantined"
    assert bridge.queued() == []
    assert bridge.quarantined() == [bad.name]
    assert move.call_count == 5


def test_a_request_that_hard_kills_the_process_is_not_dispatched_forever(
        bridge, monkeypatch):
    """A request that segfaults or OOMs a provider cannot be caught -- the
    process just dies with the request still queued. Without a bound the
    watcher re-dispatches (and on a paid lane re-bills) it on every restart."""
    calls = {"n": 0}

    def kill(payload, *, effect_identity=None):
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
