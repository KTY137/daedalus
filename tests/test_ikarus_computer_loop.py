"""General computer loop contract tests; fake adapters are not live host evidence."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.orchestration.llm_client import IkarusLLMClient, LLMRequest, LLMResponse, LLMToolCall
from daedalus.spine.durability import open_gate0_spine_writer


class Service:
    policy_digest = "a" * 64

    def __init__(self, *, enabled=True, result=None, max_steps=4, unavailable=None):
        self.calls = []
        self.enabled = enabled
        self.unavailable = dict(unavailable or {})
        self.result = result or {"ok": True, "state": "verified", "result": {"text": "fixture"}, "evidence": {"digest": "b" * 64}}
        self.max_steps = max_steps
        self.stopped = False

    def capabilities(self):
        return {"enabled": self.enabled, "tools": [{"name": "file.read", "description": "Read a permitted file", "parameters": {}}],
                "unavailable": dict(self.unavailable),
                "max_steps": self.max_steps, "timeout_s": 10, "planner_provider": "ollama_http"}

    def check_cancelled(self):
        if self.stopped:
            raise RuntimeError("operator stop")

    def execute(self, tool, arguments, *, mission_id, attempt_id):
        self.calls.append((tool, arguments, mission_id, attempt_id))
        return self.result


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.setattr(loop, "control_root", lambda root: tmp_path / "control")
    monkeypatch.setattr(loop, "_context_snapshot", lambda root: {"context_sha256": "d" * 64, "notes": [], "skills": []})
    with open_gate0_spine_writer(tmp_path / "spine.sqlite3") as ledger:
        yield tmp_path, ledger


def planner(*responses):
    pending = iter(responses)
    return lambda *args: json.dumps(next(pending))


READ = {"type": "tool", "tool": "file.read", "arguments": {"path": "fixture.txt"}}
DONE = {"type": "finish", "summary": "I read the fixture."}


def test_tool_passes_adapter_and_retains_canonical_mission(isolated):
    root, ledger = isolated
    service = Service()
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, DONE), mission_id="computer-test")
    assert result["ok"] is True
    assert result["task_success_verified"] is False
    assert service.calls == [("file.read", {"path": "fixture.txt"}, "computer-test", "computer-test-step-0001")]
    assert not ledger.open_intents()
    assert len(ledger.recent_intents(loop.MISSION_KIND)) == 1
    artifacts = list((root / "control" / "ikarus-computer-artifacts").glob("*.json"))
    mission_artifact = next(json.loads(path.read_text()) for path in artifacts if '"repository_input"' in path.read_text())
    assert mission_artifact["repository_input"]["status"] == "inapplicable"
    assert mission_artifact["mission"]["contract_type"] == "daedalus.mission"


@pytest.mark.parametrize("proposal", [
    {"type": "tool", "tool": "shell.unrestricted", "arguments": {}},
    {"type": "tool", "tool": "file.read", "arguments": {}, "policy": "allow-all"},
    {"type": "tool", "tool": "file.read", "arguments": "malformed"},
])
def test_unavailable_or_malformed_tool_performs_zero_effects(isolated, proposal):
    root, ledger = isolated
    service = Service()
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(proposal))
    assert result["state"] == "blocked"
    assert not service.calls


def test_adapter_failure_cannot_be_rewritten_as_model_success(isolated):
    root, ledger = isolated
    service = Service(result={"ok": False, "state": "denied", "result": {}, "evidence": {}})
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, DONE))
    assert result["state"] == "blocked"
    assert result["planner_summary"] is None
    assert len(service.calls) == 1


def test_failed_postcondition_stops_planner_even_with_completed_receipt(isolated):
    root, ledger = isolated
    service = Service(result={"ok": True, "state": "completed", "result": {"postcondition_verified": False}})
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, DONE))
    assert result["state"] == "blocked"
    assert result["planner_summary"] is None


def test_setup_command_can_run_without_preexisting_policy(monkeypatch):
    from daedalus.runtimes import computer
    monkeypatch.setattr(computer, "ComputerService", lambda *args: pytest.fail("setup constructed unconfigured service"))
    calls = []
    def setup(root, *, owner_confirmed):
        calls.append(owner_confirmed)
        return {"ok": True, "created": True}
    monkeypatch.setattr(computer, "setup_computer", setup)
    events = list(loop.conversation_events("fixture", "/computer setup"))
    assert calls == [True]
    assert events[-1][1]["computer"]["created"] is True


def test_explicit_configuration_is_not_a_planner_tool(monkeypatch):
    from daedalus.interfaces import computer_configuration
    calls = []
    def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
        calls.append((policy, owner_confirmed, expected_policy_sha256))
        return {"ok": True, "changed": True}
    monkeypatch.setattr(computer_configuration, "configure_computer", configure)
    payload = {"policy": {"schema": "fixture"}, "expected_policy_sha256": "c" * 64}
    events = list(loop.conversation_events("fixture", "/computer configure " + json.dumps(payload)))
    assert calls == [({"schema": "fixture"}, True, "c" * 64)]
    assert events[-1][1]["computer"]["changed"] is True


def test_status_displays_copyable_configuration_and_enabled_capability_limits(monkeypatch):
    from daedalus.runtimes import computer
    monkeypatch.setattr(computer, "computer_status", lambda root: {
        "enabled": True, "workspace": "fixture-workspace", "tools": [{"name": "browser.read"}],
        "policy_sha256": "a" * 64, "configuration": {"schema": "fixture"},
        "browser_limits": "static pages only", "desktop_validation": "not yet measured",
    })
    events = list(loop.conversation_events("fixture", "/computer status"))
    response = events[-1][1]["assistant"]
    assert '"expected_policy_sha256": "' + "a" * 64 + '"' in response
    assert '"policy": {' in response
    assert "static pages only" in response
    assert "not yet measured" not in response


def test_frozen_schedule_policy_is_checked_before_model_or_mission(isolated):
    root, ledger = isolated
    service = Service()
    with pytest.raises(loop.ComputerLoopRefused, match="policy changed"):
        loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(),
                               expected_policy_sha256="b" * 64)
    assert not service.calls
    assert not ledger.recent_intents(loop.MISSION_KIND)


def test_unverified_observation_can_be_followed_by_another_tool(isolated):
    root, ledger = isolated
    service = Service(result={"ok": True, "state": "completed", "result": {"status": "observed", "postcondition_verified": False}})
    result = loop.run_computer_task(root, "Observe fixture", service=service, ledger=ledger, propose=planner(READ, READ, DONE))
    assert result["state"] == "completed"
    assert len(service.calls) == 2


def test_terminal_mission_replay_never_calls_adapter(isolated):
    root, ledger = isolated
    service = Service()
    first = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, DONE), mission_id="replay-test")
    replay = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(), mission_id="replay-test")
    assert replay["replayed"] is True
    assert replay["report_artifact"] == first["report_artifact"]
    assert len(service.calls) == 1


def test_interrupted_mission_requires_reconciliation(isolated):
    root, ledger = isolated
    service = Service()
    events = loop.computer_events(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, DONE), mission_id="crash-test")
    assert next(events)[1]["phase"] == "planning"
    assert next(events)[1]["phase"] == "observed"
    events.close()
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(), mission_id="crash-test")
    assert result["state"] == "reconciliation_required"
    assert len(service.calls) == 1


def test_step_limit_is_enforced(isolated):
    root, ledger = isolated
    service = Service(max_steps=1)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=planner(READ, READ))
    assert result["state"] == "step_limit"
    assert len(service.calls) == 1


def test_planner_exhausts_timeout_before_tool(isolated):
    root, ledger = isolated
    service = Service()
    ticks = iter((0, 0, 11, 11))
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(READ), clock=lambda: next(ticks))
    assert result["state"] == "timeout"
    assert not service.calls


def test_stop_after_model_prevents_next_effect(isolated):
    root, ledger = isolated
    service = Service()
    def stop(*args):
        service.stopped = True
        return json.dumps(READ)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=stop)
    assert result["state"] == "blocked"
    assert not service.calls


def test_cancellation_after_model_prevents_next_effect(isolated):
    root, ledger = isolated
    service = Service()
    calls = []
    def propose(*args):
        calls.append(True)
        return json.dumps(READ)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=propose, cancelled=lambda: bool(calls))
    assert result["state"] == "cancelled"
    assert not service.calls


def test_unconfigured_computer_never_creates_mission(isolated):
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=Service(enabled=False), ledger=ledger, propose=planner())
    assert result["state"] == "unavailable"
    assert not ledger.recent_intents(loop.MISSION_KIND)


def test_secret_objective_refused_before_storage_or_model(isolated):
    root, ledger = isolated
    service = Service()
    with pytest.raises(loop.ComputerLoopRefused, match="secret floor"):
        loop.run_computer_task(root, "-----BEGIN PRIVATE KEY-----\nSYNTHETIC-NONSECRET-FIXTURE\n-----END PRIVATE KEY-----",
                               service=service, ledger=ledger, propose=planner())
    assert not service.calls
    assert not ledger.recent_intents(loop.MISSION_KIND)


@pytest.mark.parametrize("host", ["https://example.com", "http://localhost:11434", "http://127.0.0.1.evil.invalid", "http://user:password@127.0.0.1"])
def test_local_context_refuses_non_numeric_loopback(host, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", host)
    with pytest.raises(loop.ComputerLoopRefused):
        loop._require_context_route({"planner_provider": "ollama_http"})


def test_local_context_refuses_external_provider():
    with pytest.raises(loop.ComputerLoopRefused):
        loop._require_context_route({"planner_provider": "claude_code_cli"})


def test_tool_only_llm_response_is_usable():
    client = IkarusLLMClient(environ={})
    response = client.complete(LLMRequest("Propose a tool"),
                               lambda *args: LLMResponse("", "ollama_http", tool_calls=(LLMToolCall("file.read"),)),
                               requested="ollama_http")
    assert len(response.tool_calls) == 1


def test_command_route_only_matches_explicit_command():
    assert loop.is_computer_command("/computer read a file")
    assert loop.is_computer_command(" /COMPUTER status ")
    assert not loop.is_computer_command("explain /computer")
    assert not loop.is_computer_command("/computerx")


def test_duplicate_json_keys_refused():
    with pytest.raises(loop.ComputerLoopRefused):
        loop._parse_proposal('{"type":"tool","tool":"file.read","tool":"file.write","arguments":{}}')


def test_blocking_command_routes_before_software_classifier(monkeypatch):
    from daedalus.orchestration.ikarus import shell
    called = []
    def events(project, message):
        called.append((project, message))
        yield "final", {"intent": "computer", "assistant": "Observed fixture", "computer": {"ok": True}}
    monkeypatch.setattr(loop, "conversation_events", events)
    monkeypatch.setattr(shell, "classify", lambda *args: pytest.fail("computer command entered software classifier"))
    result = shell._ask_inner("project", "/computer read fixture", provider="deepseek")
    assert result["intent"] == "computer"
    assert called == [("project", "/computer read fixture")]


def test_stream_cancellation_reaches_inflight_computer_planner(isolated):
    from daedalus.orchestration.ikarus.shell import _CancellableAskStream
    root, ledger = isolated
    service = Service()
    model_started = threading.Event()
    model_release = threading.Event()
    cancel_event = threading.Event()
    def propose(*args):
        model_started.set()
        assert model_release.wait(5)
        return json.dumps(READ)
    events = loop.computer_events(root, "Read fixture", service=service, ledger=ledger,
                                 propose=propose, cancelled=cancel_event.is_set)
    wrapped = _CancellableAskStream(events, lambda result: result, cancel_event)
    assert next(wrapped)[1]["phase"] == "planning"
    results = []
    def consume():
        results.extend(list(wrapped))
    worker = threading.Thread(target=consume)
    worker.start()
    assert model_started.wait(5)
    assert wrapped.cancel() == "requested"
    model_release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert not service.calls
    assert not results


# --------------------------------------------------------------------------
# G1-IKARUS-26: what the live 2026-09-05 measurement found (missions computer-loop-measure-02/03)
# --------------------------------------------------------------------------

PLAN = {"type": "plan", "steps": ["Read the page and report the title.", "Observe the current browser DOM again."]}
PLAN_OTHER = {"type": "plan", "steps": ["Read the page and report the title."]}
RELEASE_LOCK = "workspace path tools are disabled in v0.1.6 until handle-relative, reparse-safe I/O is independently verified"


def _unbounded(monkeypatch):
    """The owner's Revision-10 master option: every Daedalus-owned cap axis disabled."""
    from daedalus.kernel.policy.limits import ExecutionLimitPolicy, store_in_env

    env = {}
    store_in_env(ExecutionLimitPolicy(mode="unbounded_execution"), env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_release_locked_policy_is_reported_as_locked_not_as_missing(isolated):
    """Mission computer-loop-measure-02: a configured policy whose every tool was
    release-locked was reported as if no policy existed."""
    root, ledger = isolated
    locked = Service(enabled=False, unavailable={"file.read": RELEASE_LOCK, "file.write": RELEASE_LOCK})
    result = loop.run_computer_task(root, "Read fixture", service=locked, ledger=ledger, propose=planner())
    assert result["state"] == "unavailable"
    assert "every configured tool is unavailable" in result["summary"]
    assert "file.read: workspace path tools are disabled" in result["summary"]
    assert "owner-configured" not in result["summary"]
    assert not ledger.recent_intents(loop.MISSION_KIND)
    missing = loop.run_computer_task(root, "Read fixture", service=Service(enabled=False), ledger=ledger, propose=planner())
    assert missing["state"] == "unavailable"
    assert "needs an owner-configured computer policy" in missing["summary"]


def test_three_identical_plans_stall_even_under_unbounded_execution(isolated, monkeypatch):
    """Mission computer-loop-measure-03: a 7B planner repeated one plan eleven times and only
    the kill switch ended the loop. Identical plans are a progress criterion, not a cap, so
    the rule holds when every cap axis is disabled and the step limit is not enforced."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN, PLAN, PLAN, READ, DONE), mission_id="plan-stall")
    assert result["state"] == "stalled", result["summary"]
    assert "identical advisory plans" in result["summary"]
    assert (result["planner_calls"], result["replans"], result["tool_steps"]) == (3, 2, 0)
    assert len(result["proposals"]) == 3, "all three proposals stay retained"
    assert result["plan"]["revision"] == 3
    assert service.calls == []


def test_a_different_plan_or_a_tool_step_resets_the_identical_plan_sequence(isolated, monkeypatch):
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN, PLAN, PLAN_OTHER, PLAN, PLAN, READ, PLAN, PLAN, DONE))
    assert result["state"] == "completed", result["summary"]
    assert (result["planner_calls"], result["tool_steps"], result["replans"]) == (9, 1, 6)
    assert len(service.calls) == 1


def test_an_invalid_response_between_plans_resets_the_identical_plan_sequence(isolated, monkeypatch):
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    responses = iter([json.dumps(PLAN), json.dumps(PLAN), "not a proposal at all",
                      json.dumps(PLAN), json.dumps(PLAN), json.dumps(READ), json.dumps(DONE)])
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=lambda *args: next(responses))
    assert result["state"] == "completed", result["summary"]
    assert result["planner_calls"] == 7 and result["tool_steps"] == 1


def test_identical_plans_stall_under_the_bounded_default_before_the_step_limit(isolated):
    root, ledger = isolated
    service = Service(max_steps=8)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN, PLAN, PLAN, READ, DONE))
    assert result["state"] == "stalled" and result["planner_calls"] == 3
