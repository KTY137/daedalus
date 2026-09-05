"""Real canonical history, scoped views and explicit command integration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus import computer_history as history, computer_loop as loop
from daedalus.spine import ledger as ledger_module
from daedalus.spine.durability import open_gate0_spine_writer
from daedalus.kernel.policy.computer import ComputerRefused


class ObservationService:
    policy_digest = "a" * 64

    def capabilities(self):
        return {"enabled": True, "tools": [{"name": "browser.read", "parameters": {}}],
                "max_steps": 5, "timeout_s": 30, "planner_provider": "ollama_http"}

    def check_cancelled(self):
        pass

    def execute(self, *args, **kwargs):
        return {"ok": True, "state": "completed", "result": {"text": "fixture"}}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    db = tmp_path / "spine.sqlite3"
    monkeypatch.setattr(ledger_module, "default_db_path", lambda: db)
    monkeypatch.setattr(history, "default_db_path", lambda: db)
    monkeypatch.setattr(history, "control_root", lambda root: Path(root) / "control")
    monkeypatch.setattr(loop, "control_root", lambda root: Path(root) / "control")
    monkeypatch.setattr(loop, "_context_snapshot", lambda root: {"context_sha256": "d" * 64})
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    return tmp_path, db


def run_fixture(root, db, name):
    replies = iter([{"type": "tool", "tool": "browser.read", "arguments": {}},
                    {"type": "finish", "summary": "Read observed fixture"}])
    with open_gate0_spine_writer(db) as ledger:
        return loop.run_computer_task(root, "Read the fixture", service=ObservationService(),
                 mission_id=name, ledger=ledger, propose=lambda *args: json.dumps(next(replies)))


def test_history_reads_real_mission_report_and_steps(isolated):
    root, db = isolated
    original = run_fixture(root, db, "history-fixture")
    assert original["state"] == "completed"
    page = history.list_computer_tasks(root)
    assert page["returned_count"] == 1
    assert page["has_more"] is False
    assert page["items"][0]["state"] == "completed", page
    detail = history.computer_task(root, "history-fixture")
    assert detail["tool_steps"] == 1, detail
    assert detail["recent_steps"][0]["tool"] == "browser.read"
    assert detail["task_success_verified"] is False
    assert detail["worker_liveness"] == "unknown"


def test_history_root_isolation_and_cursor_have_no_duplicates(isolated):
    root, db = isolated
    other = root / "other"
    for name in ("first", "second", "third"):
        run_fixture(root, db, name)
    run_fixture(other, db, "foreign")
    first = history.list_computer_tasks(root, limit=2)
    second = history.list_computer_tasks(root, limit=2, before_id=first["next_cursor"])
    assert first["has_more"] is True
    assert [x["mission_id"] for x in first["items"]] == ["third", "second"]
    assert [x["mission_id"] for x in second["items"]] == ["first"]
    assert not second["has_more"]
    assert history.computer_task(root, "foreign")["state"] == "not_found"
    assert history.list_computer_tasks(other)["returned_count"] == 1


def test_corrupt_or_missing_cas_never_claims_completion(isolated):
    root, db = isolated
    report = run_fixture(root, db, "corrupt")
    path = root / "control" / "ikarus-computer-artifacts" / (report["report_artifact"]["sha256"] + ".json")
    path.write_text('{"state":"completed"}', encoding="ascii")
    assert history.computer_task(root, "corrupt")["state"] == "evidence_unavailable"
    assert history.list_computer_tasks(root)["items"][0]["state"] == "evidence_unavailable"
    path.unlink()
    assert history.computer_task(root, "corrupt")["state"] == "evidence_unavailable"


def test_missing_ledger_reads_create_nothing_and_legacy_content_stays_hidden(isolated):
    root, db = isolated
    before = set(root.iterdir())
    assert history.list_computer_tasks(root)["returned_count"] == 0
    assert history.computer_task(root, "missing")["state"] == "not_found"
    assert set(root.iterdir()) == before
    with open_gate0_spine_writer(db) as ledger:
        ledger.record_intent(history.MISSION_KIND, {"mission_id": "legacy", "objective": "private legacy data"},
                             effect_key="computer:legacy")
    assert history.list_computer_tasks(root)["returned_count"] == 0
    result = history.computer_task(root, "legacy")
    assert result["state"] == "legacy_unscoped"
    assert "private legacy" not in json.dumps(result)


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": True}, {"limit": 101}, {"before_id": -1}])
def test_invalid_display_bounds_refused(isolated, kwargs):
    root, _ = isolated
    with pytest.raises(ComputerRefused):
        history.list_computer_tasks(root, **kwargs)


@pytest.mark.parametrize("interval,count,expected", [("30m", "4", 1800), ("1h", "2", 3600), ("1d", "8", 86400)])
def test_repeat_parser_has_explicit_finite_scope(interval, count, expected):
    assert loop._repeat_request(f"{interval} {count} Read browser") == (expected, int(count), "Read browser")


@pytest.mark.parametrize("text", ["10s 4 task", "1m 0 task", "1m 1001 task", "1m task", "1x 4 task", "1h unlimited task"])
def test_repeat_parser_refuses_accidental_infinite_or_missing_scope(text):
    with pytest.raises(loop.ComputerLoopRefused):
        loop._repeat_request(text)


def test_queue_repeat_cancel_commands_use_existing_scheduler(monkeypatch):
    from daedalus.kairos.scheduler import KairosScheduler
    calls = []
    def queue(self, root, objective, **kwargs):
        calls.append(("queue", objective, kwargs))
        return {"schedule_id": "queued-fixture"}
    def schedule(self, root, due, objective, **kwargs):
        calls.append(("repeat", objective, kwargs))
        return {"schedule_id": "series-fixture"}
    def cancel(self, root, schedule_id, **kwargs):
        calls.append(("cancel", schedule_id, kwargs))
        return {"ok": True, "cancel_requested": True}
    monkeypatch.setattr(KairosScheduler, "enqueue_computer", queue)
    monkeypatch.setattr(KairosScheduler, "schedule_computer", schedule)
    monkeypatch.setattr(KairosScheduler, "cancel_computer_schedule", cancel)
    queue_reply = list(loop.conversation_events(None, "/computer queue Read fixture"))[-1][1]
    repeat_reply = list(loop.conversation_events(None, "/computer every 30m 4 Read fixture"))[-1][1]
    cancel_reply = list(loop.conversation_events(None, "/computer cancel series-fixture"))[-1][1]
    assert "queued-fixture" in queue_reply["assistant"]
    assert "series-fixture" in repeat_reply["assistant"]
    assert cancel_reply["computer"]["cancel_requested"]
    assert calls[1][2] == {"owner_confirmed": True, "repeat_every_s": 1800, "occurrences": 4}
    assert all(call[2]["owner_confirmed"] is True for call in calls)


def test_history_command_is_read_only_route(monkeypatch):
    monkeypatch.setattr(history, "list_computer_tasks", lambda root, **kwargs: {"items": [], "next_cursor": None})
    monkeypatch.setattr(loop, "computer_events", lambda *args, **kwargs: pytest.fail("history called the planner"))
    result = list(loop.conversation_events(None, "/computer tasks"))[-1][1]
    assert result["computer"]["tasks"]["items"] == []


def test_runtime_checkpoints_observe_cooperative_cancel_before_policy_read(monkeypatch):
    from daedalus.runtimes import computer
    service = object.__new__(computer.ComputerService)
    service._switch = type("Switch", (), {"checkpoint": lambda self: None})()
    service.set_cancellation_probe(lambda: True)
    monkeypatch.setattr(computer, "load_policy", lambda *args: pytest.fail("cancellation did not stop before policy read"))
    with pytest.raises(ComputerRefused, match="cancellation requested"):
        service.check_cancelled()
    service.set_cancellation_probe(None)
    assert service._cancellation_probe is None
    with pytest.raises(ComputerRefused):
        service.set_cancellation_probe(True)
