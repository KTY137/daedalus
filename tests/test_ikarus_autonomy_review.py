"""Independent autonomy fault checks using isolated canonical state.

Adapter fixtures establish cancellation/provenance behavior, not live desktop
or browser conformance. No test permits a workspace pathname effect.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, policy_path
from daedalus.kernel.artifacts import store_canonical_json
from daedalus.orchestration.ikarus import computer_history, computer_loop, computer_schedule
from daedalus.runtimes import computer
from daedalus.spine import killswitch
from daedalus.spine.durability import open_gate0_spine_writer
from daedalus.spine.ledger import SpineLedger


@pytest.fixture
def isolated_computer(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    root = tmp_path / "authority"
    root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = ComputerPolicy(workspace=workspace, tools=("browser.read",))
    config = policy_path(root)
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    assert killswitch.KillSwitch(repo_root=root, sweep_managed=False).arm(
        note="isolated autonomy review fixture").running
    service = computer.ComputerService(root)
    try:
        yield service
    finally:
        service.close()


def test_cancellation_probe_before_admission_has_no_effect_or_lease(isolated_computer, monkeypatch):
    service = isolated_computer
    service.set_cancellation_probe(lambda: True)
    monkeypatch.setattr(service, "_dispatch", lambda *args: pytest.fail("cancelled adapter entered"))
    monkeypatch.setattr(computer, "acquire_effect_lease", lambda *args, **kwargs: pytest.fail("cancelled lease issued"))
    result = service.execute("browser.read", {}, mission_id="cancel-before", attempt_id="one")
    assert result["state"] == "blocked"
    assert "cancellation requested" in result["error"]
    assert not (service.control / "effect-leases.sqlite3").exists()


def test_inflight_cancellation_retains_unknown_and_never_reenters_adapter(isolated_computer, monkeypatch):
    service = isolated_computer
    requested = []
    calls = []
    service.set_cancellation_probe(lambda: bool(requested))

    def adapter(tool, arguments):
        calls.append(tool)
        requested.append(True)
        service.check_cancelled()
        pytest.fail("adapter continued after cancellation")

    monkeypatch.setattr(service, "_dispatch", adapter)
    first = service.execute("browser.read", {}, mission_id="cancel-inflight", attempt_id="one")
    assert first["state"] == "reconciliation_required", first
    assert "cancellation requested" in first["error"]
    with closing(sqlite3.connect(str(service.control / "effect-leases.sqlite3"))) as database:
        assert database.execute("SELECT state FROM effect_executions").fetchall() == [("STARTED",)]
    service.set_cancellation_probe(None)
    replay = service.execute("browser.read", {}, mission_id="cancel-inflight", attempt_id="one")
    # A freshly issued lease can differ in timestamp and be refused by the
    # persisted lease identity before its old STARTED state is revisited.
    assert replay["state"] in {"blocked", "reconciliation_required"}, replay
    assert calls == ["browser.read"]
    with closing(sqlite3.connect(str(service.control / "effect-leases.sqlite3"))) as database:
        assert database.execute("SELECT state FROM effect_executions").fetchall() == [("STARTED",)]


def test_pagination_never_changes_canonical_pending_recovery(tmp_path):
    path = tmp_path / "spine.sqlite3"
    with open_gate0_spine_writer(path) as ledger:
        records = [ledger.record_intent("review.pagination", {"authority_root": "root"}) for _ in range(5)]
        ledger.mark_completed(records[3].id, result={"state": "completed"})
        page = ledger.intents_matching_payload("authority_root", ("root",), kind="review.pagination", limit=2)
        assert [row.id for row in page] == [records[4].id, records[3].id]
        older = ledger.intents_matching_payload("authority_root", ("root",), kind="review.pagination", limit=2, before_id=page[-1].id)
        assert [row.id for row in older] == [records[2].id, records[1].id]
        pending = ledger.intents_matching_payload("authority_root", ("root",), kind="review.pagination", open_only=True)
        assert [row.id for row in pending] == [records[i].id for i in (4, 2, 1, 0)]


class ReadFixture:
    """No host/provider effects; canonical mission persistence remains real."""

    policy_digest = "a" * 64

    def capabilities(self):
        return {"enabled": True, "tools": [{"name": "browser.read", "parameters": {}}],
                "max_steps": 4, "timeout_s": 60}

    def check_cancelled(self):
        pass

    def execute(self, *args, **kwargs):
        pytest.fail("history fixture unexpectedly executed a tool")


@pytest.fixture
def history_state(tmp_path, monkeypatch):
    database = tmp_path / "history.sqlite3"
    roots = [tmp_path / "alpha", tmp_path / "beta"]
    for root in roots:
        root.mkdir()
    controls = lambda root: tmp_path / "controls" / Path(root).name
    monkeypatch.setattr(computer_loop, "control_root", controls)
    monkeypatch.setattr(computer_loop, "_context_snapshot", lambda root: {"context_sha256": "d" * 64})
    monkeypatch.setattr(computer_history, "control_root", controls)
    monkeypatch.setattr(computer_history, "default_db_path", lambda: database)
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)

    def read_only_ledger(*, read_only):
        assert read_only is True
        return SpineLedger(database, read_only=True)

    monkeypatch.setattr(computer_history, "SpineLedger", read_only_ledger)
    return database, roots, controls


def record_fixture_mission(database, root, mission_id):
    with open_gate0_spine_writer(database) as ledger:
        return computer_loop.run_computer_task(
            root, "Inspect fixture " + mission_id, mission_id=mission_id, ledger=ledger,
            service=ReadFixture(), propose=lambda *args: '{"type":"finish","summary":"No actions needed"}')


def test_history_pages_never_mix_authority_or_infer_complete_history(history_state):
    database, (alpha, beta), _ = history_state
    for index in range(4):
        record_fixture_mission(database, alpha, "alpha-" + str(index))
    record_fixture_mission(database, beta, "beta-private")
    first = computer_history.list_computer_tasks(alpha, limit=2)
    assert {item["mission_id"] for item in first["items"]} == {"alpha-3", "alpha-2"}
    assert first["has_more"] is True
    second = computer_history.list_computer_tasks(alpha, limit=2, before_id=first["next_cursor"])
    assert {item["mission_id"] for item in second["items"]} == {"alpha-1", "alpha-0"}
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert computer_history.computer_task(alpha, "beta-private")["state"] == "not_found"
    assert "beta-private" not in json.dumps(first)


def test_unscoped_legacy_row_exposes_no_objective_or_retained_result(history_state):
    database, (alpha, _), _ = history_state
    with open_gate0_spine_writer(database) as ledger:
        row = ledger.record_intent(computer_history.MISSION_KIND, {
            "mission_id": "legacy", "objective": "private legacy objective"}, effect_key="computer:legacy")
        ledger.mark_completed(row.id, result={"summary": "private legacy outcome"})
    detail = computer_history.computer_task(alpha, "legacy")
    assert detail["state"] == "legacy_unscoped"
    assert "private legacy" not in json.dumps(detail)
    assert computer_history.list_computer_tasks(alpha)["items"] == []


@pytest.mark.parametrize("artifact_key", ["mission_artifact", "report_artifact"])
def test_history_refuses_tampered_cas_bytes_without_echo(history_state, artifact_key):
    database, (alpha, _), controls = history_state
    report = record_fixture_mission(database, alpha, "tampered")
    path = controls(alpha) / "ikarus-computer-artifacts" / (report[artifact_key]["sha256"] + ".json")
    path.write_bytes(b'{"private":"corrupted evidence must not appear"}')
    result = computer_history.computer_task(alpha, "tampered")
    assert result["state"] == "evidence_unavailable"
    assert "corrupted evidence" not in json.dumps(result)
    assert computer_history.list_computer_tasks(alpha)["items"][0]["state"] == "evidence_unavailable"


def test_open_mission_is_not_advertised_as_a_live_worker(history_state):
    database, (alpha, _), _ = history_state
    with open_gate0_spine_writer(database) as ledger:
        events = computer_loop.computer_events(
            alpha, "Pending fixture", mission_id="pending", service=ReadFixture(), ledger=ledger,
            propose=lambda *args: pytest.fail("closed generator called planner"))
        assert next(events)[0] == "progress"
        events.close()
    result = computer_history.computer_task(alpha, "pending")
    assert result["state"] == "pending_or_interrupted"
    assert result["worker_liveness"] == "unknown"
    assert result["terminal"] is False
    assert result["task_success_verified"] is False


def test_history_absent_ledger_creates_no_state_or_runtime(history_state, monkeypatch):
    database, (alpha, _), controls = history_state
    monkeypatch.setattr(computer_history, "SpineLedger", lambda *args, **kwargs: pytest.fail("absent ledger opened"))
    monkeypatch.setattr(computer, "ComputerService", lambda *args, **kwargs: pytest.fail("reader constructed runtime"))
    assert computer_history.list_computer_tasks(alpha)["items"] == []
    assert computer_history.computer_task(alpha, "none")["state"] == "not_found"
    assert not database.exists()
    assert not controls(alpha).exists()


def test_history_rejects_step_cas_with_conflicting_declared_authority(history_state):
    database, (alpha, beta), controls = history_state
    report = record_fixture_mission(database, alpha, "step-scope")
    ref = store_canonical_json(controls(alpha) / "ikarus-computer-artifacts", {
        "mission_sha256": report["mission_sha256"], "authority_root": str(beta),
        "attempt_id": "step-scope-step-0001", "proposal": {"type": "tool", "tool": "browser.read", "arguments": {}},
    })
    with open_gate0_spine_writer(database) as ledger:
        ledger.record_intent(computer_history.STEP_KIND, {
            "mission_id": "step-scope", "authority_root": str(alpha),
            "attempt_id": "step-scope-step-0001", "proposal_sha256": ref.sha256,
        }, effect_key="step-scope-step-0001")
    result = computer_history.computer_task(alpha, "step-scope")
    assert result["state"] == "evidence_unavailable", result


def test_cross_root_same_mission_id_cannot_replay_old_content(history_state):
    database, (alpha, beta), _ = history_state
    record_fixture_mission(database, alpha, "shared-id")
    with open_gate0_spine_writer(database) as ledger:
        with pytest.raises(computer_loop.ComputerLoopRefused, match="authority root"):
            computer_loop.run_computer_task(
                beta, "Inspect fixture shared-id", mission_id="shared-id", ledger=ledger,
                service=ReadFixture(), propose=lambda *args: pytest.fail("cross-root replay called planner"))
        assert len(ledger.recent_intents(computer_history.MISSION_KIND)) == 1


def test_real_browser_navigation_observes_cancellation_and_cannot_repeat(isolated_computer):
    """Real isolated Chromium/loopback HTTP; no external page or desktop input."""
    base_service = isolated_computer
    cancelled = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            cancelled.set()
            body = b"<html><body>Isolated cancellation fixture</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/fixture"
    policy = ComputerPolicy(workspace=base_service._policy.workspace,
                            tools=("browser.navigate",), origins=(url,))
    policy_path(base_service.authority_root).write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    service = computer.ComputerService(base_service.authority_root)
    service.set_cancellation_probe(cancelled.is_set)
    try:
        first = service.execute("browser.navigate", {"url": url}, mission_id="native-cancel", attempt_id="one")
        assert requests == ["/fixture"], first
        assert first["state"] == "reconciliation_required", first
        with closing(sqlite3.connect(str(service.control / "effect-leases.sqlite3"))) as database:
            assert database.execute("SELECT state FROM effect_executions").fetchall() == [("STARTED",)]
        service.set_cancellation_probe(None)
        replay = service.execute("browser.navigate", {"url": url}, mission_id="native-cancel", attempt_id="one")
        assert replay["ok"] is False
        assert requests == ["/fixture"]
    finally:
        service.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_finite_recurrence_runs_real_browser_once_per_distinct_mission(isolated_computer, monkeypatch):
    """Real policy/mission/lease/browser evidence with a deterministic planner."""
    base_service = isolated_computer
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = b"<html><body>Bounded recurring observation fixture</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/recurring"
    root = base_service.authority_root
    policy = ComputerPolicy(workspace=base_service._policy.workspace,
                            tools=("browser.navigate",), origins=(url,), max_steps=4)
    policy_path(root).write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    database = root.parent / "schedule.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(database))
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(computer_schedule, "_utcnow", lambda: now)
    monkeypatch.setattr(computer_loop, "_context_snapshot", lambda root: {"context_sha256": "d" * 64})

    def deterministic_mission(authority, objective, **kwargs):
        replies = iter((
            {"type": "tool", "tool": "browser.navigate", "arguments": {"url": url}},
            {"type": "finish", "summary": "Observed fixture page"},
        ))
        return computer_loop.run_computer_task(authority, objective, **kwargs,
                                              propose=lambda *args: json.dumps(next(replies)))

    monkeypatch.setattr(computer_schedule, "_run_computer_task", deterministic_mission)
    try:
        due = now + timedelta(seconds=1)
        computer_schedule.schedule_computer(root, due.isoformat(), "Observe local fixture twice",
                                           owner_confirmed=True, repeat_every_s=60, occurrences=2)
        first = computer_schedule.dispatch_due_computer(root, now=due)
        assert first[0]["state"] == "completed", first
        assert first[0]["continuation"]["state"] == "scheduled", first
        assert requests == ["/recurring"]
        next_due = datetime.fromisoformat(first[0]["continuation"]["due_at"])
        assert computer_schedule.dispatch_due_computer(root, now=next_due - timedelta(seconds=1)) == []
        second = computer_schedule.dispatch_due_computer(root, now=next_due)
        assert second[0]["state"] == "completed", second
        assert second[0]["mission_id"] != first[0]["mission_id"]
        assert requests == ["/recurring", "/recurring"]
        assert computer_schedule.dispatch_due_computer(root, now=next_due + timedelta(days=1)) == []
        with SpineLedger(database, read_only=True) as ledger:
            assert len(ledger.recent_intents(computer_schedule.SCHEDULE_KIND)) == 2
            assert len(ledger.recent_intents(computer_loop.MISSION_KIND)) == 2
            assert not ledger.open_intents(computer_schedule.CLAIM_KIND)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_cancel_between_due_read_and_claim_reservation_creates_no_stale_claim(isolated_computer, monkeypatch):
    service = isolated_computer
    root = service.authority_root
    database = root.parent / "cancel-race.sqlite3"
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(database))
    now = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(computer_schedule, "_utcnow", lambda: now)
    job = computer_schedule.enqueue_computer(root, "Read fixture later", owner_confirmed=True)
    real_lock = computer_schedule.ExclusiveFileLock
    injected = []

    @contextmanager
    def cancel_before_claim(path, **kwargs):
        if Path(path).name == "computer-schedule-claim.lock" and not injected:
            injected.append(True)
            computer_schedule.cancel_computer_schedule(root, job["schedule_id"], owner_confirmed=True)
        with real_lock(path, **kwargs) as lock:
            yield lock

    monkeypatch.setattr(computer_schedule, "ExclusiveFileLock", cancel_before_claim)
    monkeypatch.setattr(computer_schedule, "_run_computer_task", lambda *args, **kwargs: pytest.fail("cancel race invoked runner"))
    assert computer_schedule.dispatch_due_computer(root, now=now) == []
    with SpineLedger(database, read_only=True) as ledger:
        assert ledger.recent_intents(computer_schedule.CLAIM_KIND) == []
        rows = ledger.recent_intents(computer_schedule.SCHEDULE_KIND)
        assert len(rows) == 1 and not rows[0].is_open
        assert rows[0].result["state"] == "cancelled"
