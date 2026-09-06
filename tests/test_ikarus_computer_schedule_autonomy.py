from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import pytest

from daedalus.kernel.policy.computer import BROWSER_TOOLS, ComputerPolicy, ComputerRefused, policy_path
from daedalus.orchestration.ikarus import computer_schedule as subject
from daedalus.runtimes import computer as computer_runtime
from daedalus.runtimes.computer import ComputerService
from daedalus.spine import killswitch
from daedalus.spine.ledger import SpineLedger


@pytest.fixture
def autonomous(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    # This fixture supplies a private deterministic host adapter.  Exercise the
    # canonical mission/lease/CAS/receipt path without coupling those contracts
    # to whichever optional GUI packages happen to be installed on the runner.
    monkeypatch.setattr(computer_runtime, "_release_unavailable_reason",
                        lambda _policy, _tool: "")
    database = tmp_path / "spine.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(database))
    root, workspace = tmp_path / "authority", tmp_path / "scratch"
    root.mkdir()
    workspace.mkdir()
    policy = ComputerPolicy(workspace, tools=BROWSER_TOOLS, origins=("http://127.0.0.1:1",))
    path = policy_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=root, sweep_managed=False)
    switch.arm(note="isolated recurring queue fixture")
    fixture = SimpleNamespace(root=root, policy=policy, path=path, switch=switch, database=database,
                              now=datetime(2026, 9, 5, 12, tzinfo=timezone.utc), calls=[])
    monkeypatch.setattr(subject, "_utcnow", lambda: fixture.now)
    def runner(authority, objective, **kwargs):
        fixture.calls.append((authority, objective, kwargs))
        return observed_report(fixture, mission_id=kwargs["mission_id"])
    monkeypatch.setattr(subject, "_run_computer_task", runner)
    return fixture


def observed_report(fixture, *, tool="browser.read", result=None, mission_id=None):
    """Synthetic private host adapter; actual policy, leases, CAS and receipts."""
    result = result or {"status": "observed", "text": "Fixture status", "postcondition_verified": False}
    mission_id = mission_id or subject.list_scheduled_computer(fixture.root)[0]["mission_id"]
    arguments = {} if tool == "browser.read" else {"observation_id": "f" * 32, "selector": "#fixture"}
    if tool.startswith("vision."):
        arguments = {"observation_id": "f" * 32}
    service = ComputerService(fixture.root)
    service._dispatch = lambda _tool, _args: result
    service._desktop = SimpleNamespace(require_fresh_observation=lambda _id: None)
    try:
        outcome = service.execute(tool, arguments, mission_id=mission_id, attempt_id=mission_id + "-step-0001")
        assert outcome["ok"], outcome
    finally:
        service.close()
    return {"ok": True, "state": "completed", "task_success_verified": False,
            "steps": [{"tool": tool, "outcome": outcome}]}


def recurring(fixture, *, occurrences=3):
    return subject.schedule_computer(fixture.root, fixture.now.isoformat(), "Observe the owner fixture",
                                     owner_confirmed=True, repeat_every_s=60, occurrences=occurrences)


def test_queue_is_immediate_and_uses_original_canonical_path(autonomous):
    f = autonomous
    job = subject.enqueue_computer(f.root, "Observe queued fixture", owner_confirmed=True)
    assert job["due_at"] == f.now.isoformat()
    assert job["repeat_every_s"] is None and job["occurrences"] == 1
    report = subject.dispatch_due_computer(f.root, now=f.now)[0]
    assert report["state"] == "completed" and report["task_success_verified"] is False
    assert len(f.calls) == 1
    with SpineLedger(f.database, read_only=True) as ledger:
        assert len(ledger.recent_intents(subject.SCHEDULE_KIND)) == 1
        assert len(ledger.recent_intents(subject.CLAIM_KIND)) == 1
        assert ledger.recent_intents(subject.CONTINUATION_KIND) == []


@pytest.mark.parametrize("interval,count", [(None, 2), (60, 1), (59, 2), (60, 1001), (60, True), (True, 2), (60.0, 2), (31536001, 2)])
def test_recurrence_bounds_refuse_before_retention(autonomous, interval, count):
    f = autonomous
    with pytest.raises(ComputerRefused, match="occurrences|recurrence"):
        subject.schedule_computer(f.root, f.now.isoformat(), "Observe fixture", owner_confirmed=True,
                                  repeat_every_s=interval, occurrences=count)
    assert not f.database.exists()


def test_queue_cancel_and_recurring_require_explicit_owner(autonomous):
    f = autonomous
    with pytest.raises(ComputerRefused, match="owner"):
        subject.enqueue_computer(f.root, "Observe")
    with pytest.raises(ComputerRefused, match="owner"):
        subject.schedule_computer(f.root, f.now.isoformat(), "Observe", repeat_every_s=60, occurrences=2)
    with pytest.raises(ComputerRefused, match="owner"):
        subject.cancel_computer_schedule(f.root, "untrusted-id")
    assert not f.database.exists()


def test_recurring_finite_chain_retains_policy_and_waits_after_actual_finish(autonomous, monkeypatch):
    f = autonomous
    first = recurring(f)
    assert recurring(f)["created"] is False
    original = subject._run_computer_task
    def slow(*args, **kwargs):
        f.now += timedelta(minutes=15)
        return original(*args, **kwargs)
    monkeypatch.setattr(subject, "_run_computer_task", slow)
    for occurrence in range(1, 4):
        report = subject.dispatch_due_computer(f.root, now=f.now)[0]
        assert report["occurrence"] == occurrence
        assert report["series_id"] == first["schedule_id"]
        if occurrence < 3:
            successor = report["continuation"]
            assert successor["due_at"] == (f.now + timedelta(seconds=60)).isoformat()
            assert subject.dispatch_due_computer(f.root, now=f.now) == []
            f.now += timedelta(seconds=60)
        else:
            assert report["continuation"] is None
    assert len(f.calls) == 3
    assert len({call[2]["mission_id"] for call in f.calls}) == 3
    assert all(call[2]["expected_policy_sha256"] == f.policy.digest for call in f.calls)
    assert subject.dispatch_due_computer(f.root, now=f.now + timedelta(days=100)) == []
    history = subject.list_scheduled_computer(f.root)
    assert [row["occurrence"] for row in history] == [1, 2, 3]
    assert all(row["expires_at"] == (subject._instant(row["due_at"]) + timedelta(hours=24)).isoformat() for row in history)


@pytest.mark.parametrize("failure", ["blocked", "reconciliation_required", "cancelled", "stalled", "empty", "input", "missing_receipt", "corrupt_artifact", "missing_terminal"])
def test_uncertain_failed_or_unverified_occurrence_never_continues(autonomous, monkeypatch, failure):
    f = autonomous
    recurring(f)
    report = observed_report(f, tool="browser.click" if failure == "input" else "browser.read")
    if failure == "empty":
        report["steps"] = []
    elif failure == "input":
        pass
    elif failure == "missing_receipt":
        del report["steps"][0]["outcome"]["evidence"]["terminal_sha256"]
    elif failure == "corrupt_artifact":
        digest = report["steps"][0]["outcome"]["evidence"]["artifact"]["sha256"]
        (killswitch.control_root(f.root) / "computer-artifacts" / (digest + ".json")).write_text("{}")
    elif failure == "missing_terminal":
        digest = report["steps"][0]["outcome"]["evidence"]["binding"]["terminal_record_sha256"]
        (killswitch.control_root(f.root) / "computer-effect-evidence" / "lease-terminal" / (digest + ".json")).unlink()
    else:
        report.update(ok=False, state=failure)
    monkeypatch.setattr(subject, "_run_computer_task", lambda *args, **kwargs: report)
    result = subject.dispatch_due_computer(f.root, now=f.now)[0]
    assert result["continuation"]["state"] == "stopped"
    assert len(subject.list_scheduled_computer(f.root)) == 1
    assert subject.dispatch_due_computer(f.root, now=f.now + timedelta(hours=1)) == []


@pytest.mark.parametrize("gap", ["claim_terminal", "schedule_terminal", "next_spec"])
def test_crash_after_terminal_recovers_metadata_without_replaying_effect(autonomous, monkeypatch, gap):
    f = autonomous
    first = recurring(f)
    real_complete = SpineLedger.mark_completed
    def complete(ledger, intent_id, **kwargs):
        row = next(row for row in ledger.recent_intents() if row.id == intent_id)
        result = real_complete(ledger, intent_id, **kwargs)
        if (gap == "claim_terminal" and row.kind == subject.CLAIM_KIND
                or gap == "schedule_terminal" and row.kind == subject.SCHEDULE_KIND):
            raise KeyboardInterrupt("simulated process loss after committed terminal")
        return result
    original_persist = subject._persist
    def persist(ledger, root, spec, receipt):
        result = original_persist(ledger, root, spec, receipt)
        if gap == "next_spec" and spec.get("occurrence") == 2:
            raise KeyboardInterrupt("simulated process loss after successor CAS and intent")
        return result
    monkeypatch.setattr(SpineLedger, "mark_completed", complete)
    monkeypatch.setattr(subject, "_persist", persist)
    with pytest.raises(KeyboardInterrupt):
        subject.dispatch_due_computer(f.root, now=f.now)
    assert len(f.calls) == 1
    monkeypatch.setattr(SpineLedger, "mark_completed", real_complete)
    monkeypatch.setattr(subject, "_persist", original_persist)
    recovered = subject.dispatch_due_computer(f.root, now=f.now)
    assert recovered[0]["metadata_only"] is True
    assert len(f.calls) == 1
    rows = subject.list_scheduled_computer(f.root)
    assert len(rows) == 2 and rows[0]["schedule_id"] == first["schedule_id"]
    assert rows[0]["next_schedule_id"] == rows[1]["schedule_id"]
    assert subject.dispatch_due_computer(f.root, now=f.now) == []


def test_open_crashed_claim_never_repeats_or_overlaps_queued_work(autonomous, monkeypatch):
    f = autonomous
    recurring(f)
    def crash(*args, **kwargs):
        f.calls.append("uncertain effect")
        raise KeyboardInterrupt("after effect admission")
    monkeypatch.setattr(subject, "_run_computer_task", crash)
    with pytest.raises(KeyboardInterrupt):
        subject.dispatch_due_computer(f.root, now=f.now)
    second = subject.enqueue_computer(f.root, "Other queued fixture", owner_confirmed=True)
    result = subject.dispatch_due_computer(f.root, now=f.now)
    assert result[0]["state"] == "waiting" and result[0]["schedule_id"] == second["schedule_id"]
    assert f.calls == ["uncertain effect"]
    assert len(subject.list_scheduled_computer(f.root)) == 2


def test_cancellation_is_durable_idempotent_and_covers_entire_series(autonomous):
    f = autonomous
    first = recurring(f)
    second = subject.dispatch_due_computer(f.root, now=f.now)[0]["continuation"]["next_schedule_id"]
    cancel = subject.cancel_computer_schedule(f.root, second, owner_confirmed=True)
    assert cancel["created"] is True and cancel["series_id"] == first["schedule_id"]
    assert subject.cancel_computer_schedule(f.root, first["schedule_id"], owner_confirmed=True)["created"] is False
    rows = subject.list_scheduled_computer(f.root)
    assert all(row["cancel_requested"] for row in rows)
    assert rows[1]["state"] == "cancelled"
    assert subject.dispatch_due_computer(f.root, now=f.now + timedelta(hours=1)) == []
    assert len(f.calls) == 1
    with SpineLedger(f.database, read_only=True) as ledger:
        assert len(ledger.recent_intents(subject.CANCEL_KIND)) == 1


def test_running_callback_observes_durable_cancel_and_no_successor(autonomous, monkeypatch):
    f = autonomous
    first = recurring(f)
    entered, release = threading.Event(), threading.Event()
    def running(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        assert kwargs["cancelled"]() is True
        return {"ok": False, "state": "cancelled", "steps": [], "task_success_verified": False}
    monkeypatch.setattr(subject, "_run_computer_task", running)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(subject.dispatch_due_computer, f.root, now=f.now)
        try:
            assert entered.wait(15)
            subject.cancel_computer_schedule(f.root, first["schedule_id"], owner_confirmed=True)
            assert subject.list_scheduled_computer(f.root)[0]["state"] == "cancellation_requested"
        finally:
            release.set()
        result = future.result(timeout=20)[0]
    assert result["state"] == "cancelled" and result["continuation"]["state"] == "stopped"
    assert len(subject.list_scheduled_computer(f.root)) == 1


def test_cancellation_works_after_policy_revoke_but_never_for_other_root(autonomous):
    f = autonomous
    first = recurring(f)
    other = f.root.parent / "other-authority"
    other.mkdir()
    with pytest.raises(ComputerRefused, match="authority"):
        subject.cancel_computer_schedule(other, first["schedule_id"], owner_confirmed=True)
    f.switch.stop("fixture stop")
    f.path.unlink()
    assert subject.cancel_computer_schedule(f.root, first["schedule_id"], owner_confirmed=True)["cancel_requested"]
    assert subject.dispatch_due_computer(f.root, now=f.now) == []


def test_cancelled_pending_rows_are_closed_and_not_read_on_later_ticks(autonomous, monkeypatch):
    f = autonomous
    first = recurring(f)
    subject.cancel_computer_schedule(f.root, first["schedule_id"], owner_confirmed=True)
    with SpineLedger(f.database, read_only=True) as ledger:
        assert ledger.intents_matching_payload("authority_root", (str(f.root),), kind=subject.SCHEDULE_KIND, open_only=True) == []
        assert len(ledger.recent_intents(subject.SCHEDULE_KIND)) == 1
    monkeypatch.setattr(subject, "_spec", lambda *args: pytest.fail("cancelled history must not be hydrated on a tick"))
    assert subject.dispatch_due_computer(f.root, now=f.now + timedelta(days=1)) == []


def test_cancel_between_dispatch_selection_and_claim_never_creates_claim(autonomous, monkeypatch):
    f = autonomous
    first = recurring(f)
    original = subject._admit
    def admit(entrypoint, evidence):
        if entrypoint == "python.computer_dispatch_due":
            subject.cancel_computer_schedule(f.root, first["schedule_id"], owner_confirmed=True)
        return original(entrypoint, evidence)
    monkeypatch.setattr(subject, "_admit", admit)
    assert subject.dispatch_due_computer(f.root, now=f.now) == []
    assert f.calls == []
    with SpineLedger(f.database, read_only=True) as ledger:
        assert ledger.recent_intents(subject.CLAIM_KIND) == []


def test_other_missions_real_terminal_evidence_cannot_authorize_recurrence(autonomous, monkeypatch):
    f = autonomous
    recurring(f)
    donor = observed_report(f, mission_id="other-owner-fixture")
    monkeypatch.setattr(subject, "_run_computer_task", lambda *args, **kwargs: donor)
    result = subject.dispatch_due_computer(f.root, now=f.now)[0]
    assert result["continuation"]["state"] == "stopped"
    assert "another occurrence" in result["continuation"]["reason"]
    assert len(subject.list_scheduled_computer(f.root)) == 1


def test_canonical_ocr_observation_name_continues_with_actual_kernel_receipts(autonomous, monkeypatch):
    f = autonomous
    native = f.root.parent / "trusted-native-fixture.exe"
    native.write_bytes(b"MZ-test-only-no-launch")
    f.policy = replace(f.policy, tools=(*BROWSER_TOOLS, "vision.ocr", "desktop.observe"),
                       applications=(("fixture", (str(native),)),))
    f.path.write_text(json.dumps(f.policy.to_dict()), encoding="utf-8")
    def runner(*args, **kwargs):
        return observed_report(f, tool="vision.ocr", mission_id=kwargs["mission_id"],
                               result={"status": "observed", "text": "OCR fixture", "postcondition_verified": False})
    monkeypatch.setattr(subject, "_run_computer_task", runner)
    recurring(f, occurrences=2)
    result = subject.dispatch_due_computer(f.root, now=f.now)[0]
    assert result["state"] == "completed", result
    assert result["continuation"]["state"] == "scheduled", result


@pytest.mark.parametrize("change", ["policy", "limits", "expiry"])
def test_successor_still_checks_frozen_scope_and_expiry(autonomous, monkeypatch, change):
    f = autonomous
    recurring(f)
    subject.dispatch_due_computer(f.root, now=f.now)
    f.now += timedelta(minutes=1)
    if change == "policy":
        f.path.write_text(json.dumps(replace(f.policy, tools=("browser.read",)).to_dict()), encoding="utf-8")
    elif change == "limits":
        monkeypatch.setattr(subject, "load_from_env", lambda: SimpleNamespace(fingerprint_sha256="f" * 64))
    else:
        f.now += timedelta(days=2)
    result = subject.dispatch_due_computer(f.root, now=f.now)[0]
    assert result["state"] == "blocked" and result["continuation"]["state"] == "stopped"
    assert len(f.calls) == 1


def test_live_recurring_browser_observation_uses_real_mission_and_terminal_receipts(autonomous, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    from daedalus.orchestration.ikarus.computer_loop import run_computer_task
    f = autonomous
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><p>Owner recurring fixture observed</p></body></html>")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    f.policy = replace(f.policy, origins=(url,))
    f.path.write_text(json.dumps(f.policy.to_dict()), encoding="utf-8")
    def runner(authority, objective, **kwargs):
        proposals = iter([{"type": "tool", "tool": "browser.navigate", "arguments": {"url": url}},
                          {"type": "finish", "summary": "Observed the local fixture"}])
        return run_computer_task(authority, objective, propose=lambda *args: json.dumps(next(proposals)), **kwargs)
    monkeypatch.setattr(subject, "_run_computer_task", runner)
    try:
        recurring(f, occurrences=2)
        first = subject.dispatch_due_computer(f.root, now=f.now)[0]
        if first["state"] != "completed" and "initialization unavailable" in json.dumps(first):
            pytest.skip("Playwright Chromium distribution unavailable")
        assert first["state"] == "completed", first
        assert first["continuation"]["state"] == "scheduled", first
        f.now += timedelta(minutes=1)
        last = subject.dispatch_due_computer(f.root, now=f.now)[0]
        assert last["state"] == "completed" and last["continuation"] is None
        assert last["task_success_verified"] is False
        assert len(requests) >= 2
        assert all(row["state"] == "completed" for row in subject.list_scheduled_computer(f.root))
        with SpineLedger(f.database, read_only=True) as ledger:
            assert len(ledger.recent_intents("ikarus.computer.mission")) == 2
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
