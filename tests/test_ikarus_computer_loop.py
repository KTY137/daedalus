"""General computer loop contract tests; fake adapters are not live host evidence."""
from __future__ import annotations

import itertools
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


# Both counter-cases below kept their claim but lost two planner calls in G1-IKARUS-29:
# their original sequences ran five and four plans without an intervening tool step and
# now end on the plan budget, which is the intended new behaviour and is asserted by
# test_four_paraphrased_plans_without_a_tool_step_stall_under_unbounded_execution.

def test_a_different_plan_or_a_tool_step_resets_the_identical_plan_sequence(isolated, monkeypatch):
    """Over-eagerness guard: two identical plans, a different one, a tool step and two more
    identical plans are not a stall under either rule."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN, PLAN, PLAN_OTHER, READ, PLAN, PLAN, DONE))
    assert result["state"] == "completed", result["summary"]
    assert (result["planner_calls"], result["tool_steps"], result["replans"]) == (7, 1, 4)
    assert len(service.calls) == 1


def test_an_invalid_response_between_plans_resets_the_identical_plan_sequence(isolated, monkeypatch):
    """Without the reset the third PLAN would be the third identical plan in a row and stall."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    responses = iter([json.dumps(PLAN), json.dumps(PLAN), "not a proposal at all",
                      json.dumps(PLAN), json.dumps(READ), json.dumps(DONE)])
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=lambda *args: next(responses))
    assert result["state"] == "completed", result["summary"]
    assert (result["planner_calls"], result["tool_steps"], result["repair_calls"]) == (6, 1, 1)


def test_identical_plans_stall_under_the_bounded_default_before_the_step_limit(isolated):
    root, ledger = isolated
    service = Service(max_steps=8)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN, PLAN, PLAN, READ, DONE))
    assert result["state"] == "stalled" and result["planner_calls"] == 3


# --------------------------------------------------------------------------
# G1-IKARUS-29: the two items G1-IKARUS-26 left open (missions computer-loop-measure-03/04)
# --------------------------------------------------------------------------

# Paraphrases of one another: no two consecutive step lists compare equal, so the
# identical-plan rule of G1-IKARUS-26 never fires on this sequence. Codex refused
# whitespace normalisation and paraphrase detection; the budget below counts plans
# instead of comparing their text.
PLAN_A = {"type": "plan", "steps": ["Read the page and report the title.", "Observe the DOM again."]}
PLAN_B = {"type": "plan", "steps": ["Report the title of the page.", "Then observe the DOM."]}
PLAN_C = {"type": "plan", "steps": ["First read the page.", "Report its title afterwards."]}
PLAN_D = {"type": "plan", "steps": ["Look at the page and state the title."]}


def test_four_paraphrased_plans_without_a_tool_step_stall_under_unbounded_execution(isolated, monkeypatch):
    """Mission computer-loop-measure-03 with a planner that paraphrases instead of repeating:
    a plan that never proposes a tool is no progress, whatever its wording. The budget is a
    progress criterion, so it holds when every Revision-10 cap axis is disabled."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN_A, PLAN_B, PLAN_C, PLAN_D, READ, DONE),
                                    mission_id="plan-budget")
    assert result["state"] == "stalled", result["summary"]
    assert "no tool step" in result["summary"] and "plan budget" in result["summary"]
    assert (result["planner_calls"], result["tool_steps"], result["replans"]) == (4, 0, 3)
    assert len(result["proposals"]) == 4, "all four proposals stay retained"
    assert result["plan"]["revision"] == 4
    assert service.calls == []


def test_a_tool_step_renews_the_plan_budget(isolated, monkeypatch):
    """The budget is per step, not per mission: three plans, a tool step, three more plans."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN_A, PLAN_B, PLAN_C, READ,
                                                    PLAN_A, PLAN_B, PLAN_C, DONE))
    assert result["state"] == "completed", result["summary"]
    assert (result["planner_calls"], result["tool_steps"]) == (8, 1)
    assert len(service.calls) == 1


def test_an_invalid_response_does_not_renew_the_plan_budget(isolated, monkeypatch):
    """Deliberately unlike the identical-plan rule, which an intervening response resets:
    only an executed tool step is progress, and a correction round is not one."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service(max_steps=2)
    responses = iter([json.dumps(PLAN_A), json.dumps(PLAN_B), "not a proposal at all",
                      json.dumps(PLAN_C), json.dumps(PLAN_D), json.dumps(READ), json.dumps(DONE)])
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=lambda *args: next(responses))
    assert result["state"] == "stalled", result["summary"]
    assert (result["planner_calls"], result["repair_calls"]) == (5, 1)
    assert service.calls == []


def test_the_plan_budget_also_holds_under_the_bounded_default(isolated):
    root, ledger = isolated
    service = Service(max_steps=8)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(PLAN_A, PLAN_B, PLAN_C, PLAN_D, READ, DONE))
    assert result["state"] == "stalled" and result["planner_calls"] == 4
    assert service.calls == []


def test_exhausted_wall_time_ends_the_mission_before_the_adapter_starts(isolated):
    """Mission computer-loop-measure-04: two planner calls consumed the 300 s mission budget,
    the browser start then hit the adapter's own cooperative deadline and was reported as a
    tool failure with a `reconciliation_required` outcome. The budget is checked immediately
    before the effect instead: no step artifact, no step intent, no adapter call."""
    root, ledger = isolated
    service = Service()  # timeout_s 10
    # One planner call consumes 9 of the 10 s; the budget is gone when the effect would start.
    ticks = iter((0.0, 0.0, 0.0, 9.0, 10.0, 10.0))
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(READ), clock=lambda: next(ticks),
                                    mission_id="pre-effect-timeout")
    assert result["state"] == "timeout", result["summary"]
    assert "before the tool step" in result["summary"]
    assert service.calls == []
    assert (result["tool_steps"], result["steps"]) == (0, [])
    assert not ledger.recent_intents(loop.STEP_KIND)
    assert not ledger.open_intents()


def test_a_single_planner_call_may_consume_the_whole_budget(isolated):
    """Both wall-time checks read the clock; neither counts planner calls. Measured on this
    host: one 7B call can exceed a whole bounded mission, because the pre-call warm-up gives
    up after 60 s and the /v1 route holds no keep-alive. Here the earlier post-planner rule
    fires first, which pins the ordering of the two checks; no effect starts either way."""
    root, ledger = isolated
    service = Service()  # timeout_s 10
    ticks = iter((0.0, 0.0, 0.0, 10.5, 10.5))
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(READ), clock=lambda: next(ticks))
    assert result["state"] == "timeout", result["summary"]
    assert "Planner exhausted the mission timeout" in result["summary"]
    assert service.calls == [] and result["tool_steps"] == 0


def test_unbounded_execution_never_ends_a_mission_on_wall_time(isolated, monkeypatch):
    """The pre-effect check is the same wall-time axis Revision 10 lets the owner disable."""
    root, ledger = isolated
    _unbounded(monkeypatch)
    service = Service()  # timeout_s 10, while the clock jumps 1000 s per reading
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    propose=planner(READ, DONE),
                                    clock=itertools.count(0, 1000).__next__)
    assert result["state"] == "completed", result["summary"]
    assert len(service.calls) == 1


# --------------------------------------------------------------------------
# G1-IKARUS-31: the planner call is reachable by the cancellation probe
# --------------------------------------------------------------------------


def test_the_default_planner_receives_a_probe_bound_to_the_loop(isolated, monkeypatch):
    """Without a propose override the loop must call _model_proposal with a callable
    ``cancelled`` probe that reflects both the mission cancellation and the service stop."""
    root, ledger = isolated
    service = Service()
    seen = {}

    def recorder(prompt, capabilities, limit_policy, timeout_s, *, cancelled=None):
        seen["probe"] = cancelled
        seen["before"] = cancelled()
        service.stopped = True
        seen["after_stop"] = cancelled()
        service.stopped = False
        return json.dumps(DONE)

    monkeypatch.setattr(loop, "_model_proposal", recorder)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger)
    assert result["state"] == "no_actions", result["summary"]
    assert callable(seen["probe"])
    assert seen["before"] is False and seen["after_stop"] is True


def test_a_user_cancellation_during_the_planner_call_ends_as_cancelled(isolated, monkeypatch):
    """Codex (room, 21:56): user cancellation must map to exactly ``cancelled``."""
    from daedalus.providers._openai_compat import ProviderCancelled

    root, ledger = isolated
    service = Service()
    cancel = threading.Event()

    def planner_that_is_cancelled(prompt, capabilities, limit_policy, timeout_s, *, cancelled=None):
        cancel.set()
        assert cancelled(), "the probe must see the cancellation"
        raise ProviderCancelled("cancelled while provider-call was in flight")

    monkeypatch.setattr(loop, "_model_proposal", planner_that_is_cancelled)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger,
                                    cancelled=cancel.is_set)
    assert result["state"] == "cancelled", result["summary"]
    assert result["planner_calls"] == 1 and result["tool_steps"] == 0
    assert service.calls == []


def test_a_service_stop_during_the_planner_call_keeps_the_stop_attribution(isolated, monkeypatch):
    from daedalus.providers._openai_compat import ProviderCancelled

    root, ledger = isolated
    service = Service()

    def planner_stopped(prompt, capabilities, limit_policy, timeout_s, *, cancelled=None):
        service.stopped = True
        assert cancelled()
        raise ProviderCancelled("cancelled while provider-call was in flight")

    monkeypatch.setattr(loop, "_model_proposal", planner_stopped)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger)
    assert result["state"] == "blocked", result["summary"]
    assert "operator stop" in result["summary"]


# --------------------------------------------------------------------------
# G1-IKARUS-32: the prompt names the next open advisory step (mission computer-loop-measure-06)
# --------------------------------------------------------------------------

PLAN_TWO = {"type": "plan", "steps": ["Read the fixture file.", "Read it again to verify."]}


def _capturing_planner(*responses):
    """Like ``planner`` but retains every prompt payload the loop sent."""
    pending = iter(responses)
    prompts: list[dict] = []

    def propose(prompt, *args):
        prompts.append(json.loads(prompt.rsplit("\n", 1)[1]))  # the payload follows the directive
        return json.dumps(next(pending))
    return propose, prompts


def test_prompt_names_the_next_open_plan_step_and_counts_executed_steps(isolated):
    """Measure-06 (2026-09-05): after one successful tool step the 7B planner proposed the same
    one-step plan three times although the observation already held the page text. The loop
    now tells the planner which advisory step has no executed tool step yet, counted over the
    tool steps since the plan was adopted; nothing is inferred from the step wording."""
    root, ledger = isolated
    service = Service(max_steps=8)
    propose, prompts = _capturing_planner(PLAN_TWO, READ, READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose)
    assert result["state"] == "completed", result["summary"]
    assert prompts[0]["advisory_plan"] is None and prompts[0]["plan_progress"] is None
    first = prompts[1]["plan_progress"]
    assert first == {"tool_steps_since_plan": 0, "next_step_index": 1,
                     "next_step": "Read the fixture file.",
                     "open_steps": ["Read the fixture file.", "Read it again to verify."],
                     "every_step_has_a_tool_step": False}
    second = prompts[2]["plan_progress"]
    assert (second["tool_steps_since_plan"], second["next_step_index"], second["next_step"]) == (1, 2, "Read it again to verify.")
    assert second["open_steps"] == ["Read it again to verify."]
    third = prompts[3]["plan_progress"]
    assert third == {"tool_steps_since_plan": 2, "next_step_index": None, "next_step": None,
                     "open_steps": [], "every_step_has_a_tool_step": True}
    assert prompts[3]["advisory_plan"]["steps"] == PLAN_TWO["steps"], "the plan itself stays in the prompt"


def test_a_revised_plan_restarts_the_progress_count(isolated):
    root, ledger = isolated
    service = Service(max_steps=8)
    propose, prompts = _capturing_planner(PLAN_TWO, READ, PLAN_OTHER, READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose)
    assert result["state"] == "completed", result["summary"]
    after_revision = prompts[3]["plan_progress"]
    assert after_revision["tool_steps_since_plan"] == 0
    assert after_revision["next_step"] == PLAN_OTHER["steps"][0]
    assert prompts[3]["advisory_plan"]["revision"] == 2


def test_progress_never_indexes_past_the_plan_and_is_absent_without_a_plan():
    assert loop._plan_progress(None, 3) is None
    plan = {"advisory": True, "revision": 1, "steps": ["only step"], "artifact": {}}
    assert loop._plan_progress(plan, 5) == {"tool_steps_since_plan": 5, "next_step_index": None, "next_step": None,
                                            "open_steps": [], "every_step_has_a_tool_step": True}


def test_prompt_states_that_an_unchanged_plan_is_not_progress():
    """The directive is data for the planner, not authority: it grants no tool and the loop's
    plan budget (G1-IKARUS-29) still ends a planner that ignores it."""
    text = loop._prompt("objective", [], [], {}, plan={"advisory": True, "revision": 1, "steps": ["s"], "artifact": {}},
                        progress=loop._plan_progress({"steps": ["s"]}, 0))
    assert "plan_progress names the first advisory step without an executed tool step" in text
    assert "Re-proposing an unchanged plan is not progress" in text
    assert "grant no tools" in text


def test_restating_the_plan_in_force_keeps_the_progress_count(isolated):
    """Momus on measure-08 (2026-09-06): the 7B re-proposed the plan already in force after
    executing its only step, and the reset then told it that step was open again. Restating
    a plan is not adopting one: the count against it stands. A different plan still restarts it."""
    root, ledger = isolated
    service = Service(max_steps=8)
    propose, prompts = _capturing_planner(PLAN_TWO, READ, PLAN_TWO, PLAN_OTHER, READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose)
    assert result["state"] == "completed", result["summary"]
    restated = prompts[3]["plan_progress"]
    assert (restated["tool_steps_since_plan"], restated["next_step"]) == (1, "Read it again to verify.")
    assert prompts[3]["advisory_plan"]["revision"] == 2, "the revision count is unchanged by this rule"
    revised = prompts[4]["plan_progress"]
    assert (revised["tool_steps_since_plan"], revised["next_step"]) == (0, PLAN_OTHER["steps"][0])
