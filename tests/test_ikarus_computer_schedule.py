from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, FILE_TOOLS, policy_path
from daedalus.orchestration.ikarus import computer_schedule as subject
from daedalus.spine import killswitch
from daedalus.spine.ledger import SpineLedger


@pytest.fixture
def scheduled(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    database = tmp_path / "spine.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(database))
    root = tmp_path / "authority"
    root.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace, tools=FILE_TOOLS)
    path = policy_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=root, sweep_managed=False)
    switch.arm(note="scheduled local fixture")
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(subject, "_utcnow", lambda: now)
    calls = []
    def run(authority, objective, **kwargs):
        calls.append((authority, objective, kwargs))
        return {"ok": True, "state": "completed", "task_success_verified": False, "steps": []}
    monkeypatch.setattr(subject, "_run_computer_task", run)
    return root, policy, path, switch, now, calls, database


def queue(fixture, objective="Inspect scratch files"):
    root, _, _, _, now, _, _ = fixture
    return subject.schedule_computer(root, (now + timedelta(minutes=1)).isoformat(), objective, owner_confirmed=True)


def test_due_time_frozen_policy_canonical_claim_and_no_repeat(scheduled):
    root, policy, _, _, now, calls, database = scheduled
    job = queue(scheduled)
    assert job["created"] is True
    assert subject.dispatch_due_computer(root, now=now) == []
    report = subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert report[0]["state"] == "completed"
    assert len(calls) == 1
    assert calls[0][2]["mission_id"] == job["mission_id"]
    assert calls[0][2]["expected_policy_sha256"] == policy.digest
    assert calls[0][2]["expected_execution_limit_policy_sha256"]
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=3)) == []
    assert subject.list_scheduled_computer(root)[0]["state"] == "completed"
    with SpineLedger(database, read_only=True) as ledger:
        assert len(ledger.recent_intents(subject.SCHEDULE_KIND)) == 1
        assert len(ledger.recent_intents(subject.CLAIM_KIND)) == 1
        assert not ledger.open_intents(subject.CLAIM_KIND)


def test_duplicate_admission_preserves_original_receipt(scheduled, monkeypatch):
    first = queue(scheduled)
    real_admit = subject._admit
    def different_receipt(*args):
        receipt = real_admit(*args)
        return SimpleNamespace(to_dict=lambda: {**receipt.to_dict(), "retry_measurement": "new receipt"})
    monkeypatch.setattr(subject, "_admit", different_receipt)
    second = queue(scheduled)
    assert second["created"] is False
    assert second["schedule_id"] == first["schedule_id"]
    assert second["admission"] == first["admission"]


def test_unconfirmed_and_naive_time_have_no_schedule_effect(scheduled):
    root, _, _, _, now, _, database = scheduled
    with pytest.raises(ComputerRefused, match="owner"):
        subject.schedule_computer(root, (now + timedelta(minutes=1)).isoformat(), "task")
    with pytest.raises(ComputerRefused, match="timezone"):
        subject.schedule_computer(root, "2026-09-06T10:00:00", "task", owner_confirmed=True)
    assert not database.exists()


@pytest.mark.parametrize("reason", ["policy", "expiry", "cancelled", "stopped", "limits"])
def test_revoked_expired_and_cancelled_jobs_never_invoke_runner(scheduled, monkeypatch, reason):
    root, policy, path, switch, now, calls, _ = scheduled
    queue(scheduled)
    due = now + timedelta(minutes=2)
    cancelled = None
    if reason == "policy":
        path.write_text(json.dumps(replace(policy, tools=("file.list",)).to_dict()), encoding="utf-8")
    elif reason == "expiry":
        due += timedelta(days=2)
    elif reason == "cancelled":
        cancelled = lambda: True
    elif reason == "stopped":
        switch.stop("fixture revoked authority")
    else:
        monkeypatch.setattr(subject, "load_from_env", lambda: SimpleNamespace(fingerprint_sha256="f" * 64))
    result = subject.dispatch_due_computer(root, now=due, cancelled=cancelled)
    assert result[0]["state"] == "blocked"
    assert calls == []
    assert subject.dispatch_due_computer(root, now=due) == []


def test_interrupted_claim_requires_reconciliation_without_retry(scheduled, monkeypatch):
    root, _, _, _, now, calls, _ = scheduled
    queue(scheduled)
    def crash(*args, **kwargs):
        raise KeyboardInterrupt("simulated host interruption after committed claim")
    monkeypatch.setattr(subject, "_run_computer_task", crash)
    with pytest.raises(KeyboardInterrupt):
        subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert subject.list_scheduled_computer(root)[0]["state"] == "reconciliation_required"
    monkeypatch.setattr(subject, "_run_computer_task", lambda *a, **k: pytest.fail("interrupted work must not repeat"))
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=3)) == []


def test_competing_dispatchers_make_one_committed_claim(scheduled, monkeypatch):
    root, _, _, _, now, calls, _ = scheduled
    queue(scheduled)
    barrier = threading.Barrier(2)
    real_list = subject._list_scheduled
    def together(*args, **kwargs):
        result = real_list(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(subject, "_list_scheduled", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(subject.dispatch_due_computer, root, now=now + timedelta(minutes=2)) for _ in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]
    assert len(calls) == 1
    assert sum(any(row["state"] == "completed" and not row.get("replayed") for row in result) for result in outcomes) == 1


def test_only_one_due_mission_per_tick(scheduled):
    root, _, _, _, now, calls, _ = scheduled
    queue(scheduled, "First separate task")
    queue(scheduled, "Second separate task")
    assert len(subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))) == 1
    assert len(calls) == 1
    subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert len(calls) == 2


def test_authority_root_filter_never_dispatches_another_root(scheduled):
    root, policy, _, _, now, calls, _ = scheduled
    queue(scheduled)
    other = root.parent / "other-authority"
    other.mkdir()
    path = policy_path(other)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    killswitch.KillSwitch(repo_root=other, sweep_managed=False).arm(note="second isolated fixture")
    second = subject.schedule_computer(other, (now + timedelta(minutes=1)).isoformat(), "Other root task", owner_confirmed=True)
    assert [item["schedule_id"] for item in subject.list_scheduled_computer(other)] == [second["schedule_id"]]
    subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert len(calls) == 1 and calls[0][0] == root
    assert subject.list_scheduled_computer(other)[0]["state"] == "scheduled"


def test_corrupt_spec_is_visible_and_never_dispatched(scheduled):
    root, _, path, _, now, calls, _ = scheduled
    job = queue(scheduled)
    artifact = path.parent / "computer-artifacts" / (job["artifact"]["sha256"] + ".json")
    artifact.write_bytes(b'{"corrupt":true}')
    assert subject.list_scheduled_computer(root)[0]["state"] == "invalid"
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=2)) == []
    assert calls == []


def test_runner_exception_is_not_claimed_as_safe_failure_to_retry(scheduled, monkeypatch):
    root, _, _, _, now, _, _ = scheduled
    queue(scheduled)
    def fail(*args, **kwargs):
        raise OSError("outcome unknown after invocation")
    monkeypatch.setattr(subject, "_run_computer_task", fail)
    result = subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert result[0]["state"] == "reconciliation_required"
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=3)) == []


def test_scheduled_path_effect_is_release_locked_without_retry(scheduled, monkeypatch):
    from daedalus.orchestration.ikarus.computer_loop import run_computer_task
    root, policy, _, _, now, _, database = scheduled
    planner_calls = []
    def propose(*args):
        planner_calls.append(args)
        return json.dumps({"type": "tool", "tool": "file.write", "arguments": {
            "path": "scheduled.txt", "text": "Scheduled Ikarus fixture"}})
    def runner(authority, objective, **kwargs):
        return run_computer_task(authority, objective, propose=propose, **kwargs)
    monkeypatch.setattr(subject, "_run_computer_task", runner)
    queue(scheduled, "Write the scheduled disposable fixture")
    result = subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    assert result[0]["state"] == "unavailable", result
    assert result[0]["ok"] is False
    assert result[0]["steps"] == []
    assert planner_calls == []
    assert not (policy.workspace / "scheduled.txt").exists()
    with SpineLedger(database, read_only=True) as ledger:
        assert len(ledger.recent_intents("ikarus.computer.mission")) == 0
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=3)) == []


def test_secret_objective_is_refused_before_any_retention(scheduled, monkeypatch):
    root, _, path, _, now, calls, database = scheduled
    secret = "-----BEGIN PRIVATE KEY-----\nfixture sensitive material\n-----END PRIVATE KEY-----"
    monkeypatch.setattr(subject, "_admit", lambda *a, **k: pytest.fail("secret objective must not reach admission"))
    with pytest.raises(ComputerRefused, match="secret"):
        subject.schedule_computer(root, (now + timedelta(minutes=1)).isoformat(), secret, owner_confirmed=True)
    assert not database.exists()
    assert not (path.parent / "computer-artifacts").exists()


def test_tick_excludes_resolved_history_before_reading_artifacts(scheduled, monkeypatch):
    root, _, _, _, now, calls, database = scheduled
    completed = queue(scheduled, "Historical completed task")
    subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))
    pending = queue(scheduled, "Current pending task")
    with SpineLedger(database, read_only=True) as ledger:
        assert len(ledger.intents_matching_payload("authority_root", (str(root),), kind=subject.SCHEDULE_KIND)) == 2
        unresolved = ledger.intents_matching_payload("authority_root", (str(root),), kind=subject.SCHEDULE_KIND, open_only=True)
        assert [row.payload["schedule_id"] for row in unresolved] == [pending["schedule_id"]]
    real_spec = subject._spec
    def inspect(authority, row):
        assert row.payload["schedule_id"] != completed["schedule_id"], "resolved history must not be hydrated on scheduler ticks"
        return real_spec(authority, row)
    monkeypatch.setattr(subject, "_spec", inspect)
    assert subject.dispatch_due_computer(root, now=now + timedelta(minutes=2))[0]["state"] == "completed"
    assert len(calls) == 2
