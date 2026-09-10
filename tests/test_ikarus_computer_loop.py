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
    monkeypatch.setattr(computer, "computer_status", lambda root, project=None, project_readers=None: {
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


# --------------------------------------------------------------------------
# G1-IKARUS-33: the report and the mission artifact say which planner ran and whether
# context left the machine (measure-09 ran Codex over allow_remote_context)
# --------------------------------------------------------------------------

class RemoteService(Service):
    def capabilities(self):
        caps = super().capabilities()
        caps.update({"planner_provider": "codex_cli", "planner_model": "gpt-6-astra", "allow_remote_context": True})
        return caps


def test_report_and_mission_artifact_carry_the_planner_provenance(isolated):
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=Service(), ledger=ledger,
                                    propose=planner(READ, DONE), mission_id="planner-local")
    assert result["planner"] == {"provider": "ollama_http", "model": None, "remote_context": False}
    artifacts = (root / "control" / "ikarus-computer-artifacts").glob("*.json")
    mission_artifact = next(json.loads(path.read_text()) for path in artifacts if '"repository_input"' in path.read_text())
    assert mission_artifact["planner"] == {"provider": "ollama_http", "model": None, "remote_context": False}


def test_remote_planner_is_named_in_the_report_the_chat_and_the_history(isolated):
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=RemoteService(), ledger=ledger,
                                    propose=planner(READ, DONE), mission_id="planner-remote")
    assert result["planner"] == {"provider": "codex_cli", "model": "gpt-6-astra", "remote_context": True}
    text = loop._chat_report(result)
    assert "Planner: codex_cli (gpt-6-astra)" in text
    assert "Kontext hat den Rechner verlassen: ja" in text
    assert "verlassen: nein" in loop._chat_report({**result, "planner": {"provider": "ollama_http", "model": None, "remote_context": False}})


def test_a_report_without_planner_facts_still_renders(isolated):
    """Retained reports from before this packet have no planner key."""
    text = loop._chat_report({"summary": "old", "steps": [], "mission_id": "m"})
    assert "Planner:" not in text


# --------------------------------------------------------------------------
# Council 2026-09-06 (council-20260906T012701Z-c52b8002, 3 of 3 seats) on G1-IKARUS-32/33
# --------------------------------------------------------------------------

PLAN_EXTENDED = {"type": "plan", "steps": ["Read the fixture file.", "Read it again to verify.", "Summarise both reads."]}
PLAN_CHANGED_FRONT = {"type": "plan", "steps": ["Open the fixture instead.", "Read it again to verify."]}


def test_a_revision_that_extends_the_plan_keeps_progress_over_the_unchanged_prefix(isolated):
    """Anthropic seat: [s1,s2,s3] executed, then [s1,s2,s3,s4] reset progress to step 1 and
    invited re-execution. Progress now survives over the steps a revision left unchanged at
    the front; a revision that changes the first step restarts at 0."""
    root, ledger = isolated
    service = Service(max_steps=10)
    propose, prompts = _capturing_planner(PLAN_TWO, READ, READ, PLAN_EXTENDED, PLAN_CHANGED_FRONT, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose)
    assert result["state"] == "completed", result["summary"]
    extended = prompts[4]["plan_progress"]
    assert (extended["tool_steps_since_plan"], extended["next_step"]) == (2, "Summarise both reads.")
    changed = prompts[5]["plan_progress"]
    assert (changed["tool_steps_since_plan"], changed["next_step"]) == (0, "Open the fixture instead.")


def test_a_failed_tool_step_is_not_progress_against_the_plan(isolated):
    """Anthropic and OpenAI seats: the increment ran before the ok check. The loop ends on a
    failed step, so the only observable is the order in the report: the plan is still in force
    with zero executed steps recorded against it, and the mission is blocked, not completed."""
    root, ledger = isolated
    service = Service(max_steps=6, result={"ok": False, "state": "denied", "result": {}, "evidence": {}})
    propose, prompts = _capturing_planner(PLAN_TWO, READ, READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose)
    assert result["state"] == "blocked" and result["tool_steps"] == 1
    assert len(prompts) == 2, "no prompt is built after a failed step, so no advanced count can reach a planner"
    # Odysseus (2026-09-06 09:04): the repair had no discriminating test because the counter
    # was invisible. The report now carries the final progress view against the plan in force.
    assert result["plan_progress"] == {"tool_steps_since_plan": 0, "next_step_index": 1,
                                       "next_step": "Read the fixture file.",
                                       "open_steps": ["Read the fixture file.", "Read it again to verify."],
                                       "every_step_has_a_tool_step": False}


def test_a_non_boolean_remote_flag_never_reaches_a_remote_planner(monkeypatch):
    """Anthropic and OpenAI seats: remote_context is reported false for allow_remote_context=1.
    The route check uses the same `is True` test, so such a policy is refused before any planner
    call and the report line can never say 'nein' for a planner that received observations.
    (ComputerPolicy itself refuses a non-boolean flag at construction.)"""
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    with pytest.raises(loop.ComputerLoopRefused, match="local-only"):
        loop._require_context_route({"planner_provider": "codex_cli", "allow_remote_context": 1})
    with pytest.raises(loop.ComputerLoopRefused, match="local-only"):
        loop._require_context_route({"planner_provider": "codex_cli", "allow_remote_context": "true"})
    assert loop._require_context_route({"planner_provider": "codex_cli", "allow_remote_context": True}) == "codex_cli"


def test_directive_states_the_real_threshold():
    text = loop._prompt("o", [], [], {}, plan={"advisory": True, "revision": 1, "steps": ["s"], "artifact": {}},
                        progress=loop._plan_progress({"steps": ["s"]}, 0))
    assert "three in a row end the task as stalled" in text
    assert "ends the task as stalled" not in text.replace("three in a row end the task as stalled", "")


# --------------------------------------------------------------------------
# G1-IKARUS-35: scheduled autonomy says whether a watcher will ever tick this root
# --------------------------------------------------------------------------

def _heartbeat(tmp_path, monkeypatch, payload):
    import daedalus.file_bridge as fb
    path = tmp_path / "bridge_heartbeat.json"
    if payload is not None:
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(fb, "HEARTBEAT_PATH", path)
    return path


def test_watcher_projection_names_whether_this_root_is_ticked(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "_pid_alive", lambda pid: True)  # liveness has its own tests below
    root = tmp_path / "authority"
    root.mkdir()
    now = 1_000_000.0
    _heartbeat(tmp_path, monkeypatch, None)
    none = loop.watcher_projection(root, now=now)
    assert (none["state"], none["ticks_this_root"], none["serves_this_root"]) == ("none", False, None)
    assert none["restart"] == f'python -m daedalus.file_bridge watch --repo-root "{root.resolve()}"'
    _heartbeat(tmp_path, monkeypatch, {"epoch": now - 5, "pid": 4242, "repo_root": str(root), "current": None})
    mine = loop.watcher_projection(root, now=now)
    assert (mine["state"], mine["ticks_this_root"], mine["serves_this_root"], mine["pid"]) == ("alive", True, True, 4242)
    _heartbeat(tmp_path, monkeypatch, {"epoch": now - 5, "pid": 1, "repo_root": str(tmp_path / "elsewhere"), "current": None})
    other = loop.watcher_projection(root, now=now)
    assert (other["state"], other["ticks_this_root"], other["serves_this_root"]) == ("alive", False, False)
    _heartbeat(tmp_path, monkeypatch, {"epoch": now - 3600, "pid": 4242, "repo_root": str(root), "current": None})
    stale = loop.watcher_projection(root, now=now)
    assert (stale["state"], stale["ticks_this_root"]) == ("stale", False)


def test_watcher_projection_is_a_fail_open_read(tmp_path, monkeypatch):
    import daedalus.file_bridge as fb
    def boom(now=None):
        raise OSError("heartbeat unreadable")
    monkeypatch.setattr(fb, "heartbeat_status", boom)
    out = loop.watcher_projection(tmp_path, now=1.0)
    assert (out["state"], out["ticks_this_root"]) == ("unknown", False)
    assert "OSError" in out["detail"]


def test_scheduled_and_queue_replies_state_the_watcher(monkeypatch):
    from daedalus.orchestration.ikarus import computer_schedule
    from daedalus.kairos import scheduler as kairos
    monkeypatch.setattr(computer_schedule, "list_scheduled_computer", lambda root: [{"schedule_id": "s1", "state": "scheduled"}])
    monkeypatch.setattr(loop, "watcher_projection", lambda root, now=None: {
        "state": "none", "serves_this_root": None, "ticks_this_root": False, "age_s": None, "pid": None,
        "watcher_root": None, "restart": "python -m daedalus.file_bridge watch --repo-root \"X\""})
    events = list(loop.conversation_events("fixture", "/computer scheduled"))
    final = events[-1][1]
    assert "Watcher: nicht aktiv" in final["assistant"]
    assert "werden nicht automatisch ausgef" in final["assistant"]
    assert 'file_bridge watch --repo-root "X"' in final["assistant"]
    assert final["computer"]["watcher"]["ticks_this_root"] is False
    monkeypatch.setattr(kairos.KairosScheduler, "enqueue_computer",
                        lambda self, root, objective, owner_confirmed=False: {"schedule_id": "q1", "state": "scheduled"})
    monkeypatch.setattr(loop, "watcher_projection", lambda root, now=None: {
        "state": "alive", "serves_this_root": True, "ticks_this_root": True, "age_s": 4.0, "pid": 77,
        "watcher_root": "X", "restart": "python -m daedalus.file_bridge watch --repo-root \"X\""})
    queued = list(loop.conversation_events("fixture", "/computer queue read the page"))[-1][1]
    assert "Watcher: aktiv" in queued["assistant"] and "PID 77" in queued["assistant"]
    assert queued["computer"]["watcher"]["ticks_this_root"] is True


# --------------------------------------------------------------------------
# G1-IKARUS-42: the report says how big each prompt was and whether it exceeded the
# planner's estimated context window (Momus 2026-09-06: measure before compacting)
# --------------------------------------------------------------------------

class LongTextService(Service):
    def __init__(self, chars, **kwargs):
        super().__init__(result={"ok": True, "state": "verified", "result": {"text": "x" * chars}, "evidence": {}}, **kwargs)


def test_report_and_proposal_artifacts_carry_prompt_size_and_the_planner_window(isolated, monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=Service(), ledger=ledger,
                                    propose=planner(READ, DONE), mission_id="prompt-size")
    assert result["planner_context_tokens"] == 6144
    assert result["context_estimate"] == "chars/4"
    assert result["prompt_overflow_calls"] == 0
    assert result["prompt_chars_max"] > 500
    artifacts = (root / "control" / "ikarus-computer-artifacts").glob("*.json")
    proposals = [json.loads(path.read_text()) for path in artifacts if '"ikarus-computer-proposal/1"' in path.read_text()]
    assert sorted(a["prompt_chars"] for a in proposals) and all(a["context_window_exceeded_estimate"] is False for a in proposals)
    assert max(a["prompt_chars"] for a in proposals) == result["prompt_chars_max"]


def test_an_observation_larger_than_the_window_is_counted_and_said(isolated, monkeypatch):
    """A browser.read may return 20,000 characters and a file.read up to max_file_bytes; the
    7B planner runs at num_ctx 6144. The loop cannot widen the window, it says when the prompt
    exceeded the estimate instead of letting the provider truncate silently."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    root, ledger = isolated
    # G1-IKARUS-45 bounds the prompt view, so the overflow counter stays 0 here; the counter and
    # its chat line are pinned on a report whose window was not respected (a remote or older run).
    monkeypatch.setattr(loop, "_prompt_view", lambda history, **kw: (list(history), loop._no_compaction(kw.get("budget_chars"))))
    result = loop.run_computer_task(root, "Read fixture", service=LongTextService(30_000), ledger=ledger,
                                    propose=planner(READ, DONE))
    assert result["state"] == "completed"
    assert result["prompt_overflow_calls"] == 1, "the second prompt carries the 30,000-character observation"
    assert result["prompt_chars_max"] > 30_000
    text = loop._chat_report(result)
    assert "1 Planner-Aufruf(e)" in text and "6144" in text and "Anfang des Prompts" in text
    assert "Planner-Aufruf(e)" not in loop._chat_report({**result, "prompt_overflow_calls": 0})


def test_a_remote_planner_has_no_estimated_window(isolated, monkeypatch):
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=RemoteService(), ledger=ledger, propose=planner(READ, DONE))
    assert result["planner_context_tokens"] is None and result["prompt_overflow_calls"] is None
    assert "Planner-Aufruf(e)" not in loop._chat_report(result)


# --------------------------------------------------------------------------
# G1-IKARUS-43: a remote planner is an explicit owner choice; no observation reaches any
# planner prompt past the secret floor (forward plan A4 #10, owner 2026-09-06 08:42)
# --------------------------------------------------------------------------

PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nfixture sensitive material\n-----END PRIVATE KEY-----"


def test_an_observation_that_trips_the_secret_floor_never_reaches_a_planner_prompt(isolated):
    """The step is executed and retained as evidence, but the mission ends before the next
    planner call: no prompt containing the observation is built or sent, local or remote."""
    root, ledger = isolated
    service = Service(result={"ok": True, "state": "verified", "result": {"text": "config:\n" + PRIVATE_KEY}, "evidence": {}})
    propose, prompts = _capturing_planner(READ, READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=service, ledger=ledger, propose=propose, mission_id="floor-obs")
    assert result["state"] == "blocked", result["summary"]
    assert "secret floor" in result["summary"] and "step 1" in result["summary"]
    assert len(prompts) == 1 and "PRIVATE KEY" not in json.dumps(prompts)
    assert result["tool_steps"] == 1 and result["steps"][0]["withheld_from_planner"] is True
    assert result["planner_calls"] == 1
    assert not ledger.open_intents()


def test_the_whole_prompt_is_floored_before_every_planner_call(isolated, monkeypatch):
    root, ledger = isolated
    seen = []
    def floor(path, text=""):
        seen.append(path)
        return "fixture rule" if path == "computer-prompt.json" and "Read fixture" in text else None
    monkeypatch.setattr(loop, "secret_floor_rule", floor)
    propose, prompts = _capturing_planner(READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=Service(), ledger=ledger, propose=propose)
    assert result["state"] == "blocked" and "prompt" in result["summary"] and "secret floor" in result["summary"]
    assert prompts == [] and result["planner_calls"] == 0
    assert "computer-prompt.json" in seen


def _planner_command_fixture(monkeypatch, *, provider="ollama_http", model=None, remote=False):
    from daedalus.runtimes import computer
    from daedalus.interfaces import computer_configuration
    configuration = {"schema": "daedalus-computer-policy/1", "workspace": "W", "tools": ["browser.read"], "origins": [],
                     "applications": {}, "planner_provider": provider, "planner_model": model,
                     "allow_remote_context": remote, "max_steps": 16, "timeout_s": 300, "max_file_bytes": 1048576}
    monkeypatch.setattr(computer, "computer_status", lambda root, project=None, project_readers=None: {
        "enabled": True, "workspace": "W", "tools": [{"name": "browser.read"}], "policy_sha256": "e" * 64,
        "configuration": configuration})
    calls = []
    def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
        calls.append((policy, owner_confirmed, expected_policy_sha256))
        return {"ok": True, "changed": True, "policy_sha256": "f" * 64, "policy": policy}
    monkeypatch.setattr(computer_configuration, "configure_computer", configure)
    return calls


def test_choosing_a_remote_planner_requires_a_transient_confirmation_with_the_warning(monkeypatch):
    calls = _planner_command_fixture(monkeypatch)
    asked = list(loop.conversation_events("fixture", "/computer planner codex_cli"))[-1][1]
    assert calls == [], "no policy change before the owner confirms"
    assert asked["computer"]["planner_change"] == "confirmation_required"
    assert "verlassen" in asked["assistant"] and "/computer planner codex_cli confirm-remote" in asked["assistant"]
    confirmed = list(loop.conversation_events("fixture", "/computer planner codex_cli confirm-remote"))[-1][1]
    assert len(calls) == 1
    policy, owner_confirmed, expected = calls[0]
    assert (policy["planner_provider"], policy["planner_model"], policy["allow_remote_context"]) == ("codex_cli", None, True)
    assert owner_confirmed is True and expected == "e" * 64
    assert policy["tools"] == ["browser.read"], "the rest of the policy is carried over unchanged"
    assert "Planner: codex_cli" in confirmed["assistant"] and "Kontext hat den Rechner verlassen: ja" in confirmed["assistant"]
    assert confirmed["computer"]["planner_change"] == "applied"


def test_choosing_the_local_planner_narrows_without_confirmation_and_names_the_model(monkeypatch):
    calls = _planner_command_fixture(monkeypatch, provider="codex_cli", remote=True)
    reply = list(loop.conversation_events("fixture", "/computer planner ollama_http qwen2.5-coder:7b"))[-1][1]
    assert len(calls) == 1
    policy = calls[0][0]
    assert (policy["planner_provider"], policy["planner_model"], policy["allow_remote_context"]) == ("ollama_http", "qwen2.5-coder:7b", False)
    assert "verlassen: nein" in reply["assistant"]
    refused = list(loop.conversation_events("fixture", "/computer planner gpt-magic"))[-1][1]
    assert refused["computer"]["state"] == "blocked" and len(calls) == 1


def test_status_names_the_planner_and_the_planner_command(monkeypatch):
    _planner_command_fixture(monkeypatch, provider="codex_cli", model="gpt-6-astra", remote=True)
    reply = list(loop.conversation_events("fixture", "/computer status"))[-1][1]["assistant"]
    assert "Planner: codex_cli (gpt-6-astra) · Kontext hat den Rechner verlassen: ja" in reply
    assert "/computer planner" in reply


# --------------------------------------------------------------------------
# G1-IKARUS-44: digit-bearing tokens of a finish summary that appear in no retained
# observation (Momus 2026-09-06 design B: a fabrication detector with no confirming power)
# --------------------------------------------------------------------------

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "G1-IKARUS-32_PLANNER_PROGRESS_LIVE"


def _measure_09_report():
    return json.loads((EVIDENCE / "computer-loop-measure-09_browser_bounded_codex-planner.json").read_text(encoding="utf-8"))["report"]


def test_absence_check_is_silent_on_the_retained_codex_finish_and_loud_on_a_fabricated_one():
    """Pre-registered falsifier: no discrimination on measure-09 means the check does not ship."""
    report = _measure_09_report()
    clean = loop.summary_tokens_absent_from_observations(report)
    assert clean["version"] == "v1" and clean["checked"] == 2 and clean["absent"] == []  # 15:00 and the sentinel
    assert clean["grounded_in"]["TANGERINE-4471"] == [1, 2], "grounded in both browser observations"
    fabricated = dict(report, planner_summary=report["planner_summary"]
                      .replace("TANGERINE-4471", "TANGERINE-4472").replace("15:00", "16:30")
                      + " Source: http://127.0.0.1:9/invented.html")
    loud = loop.summary_tokens_absent_from_observations(fabricated)
    assert {"TANGERINE-4472", "16:30"} <= set(loud["absent"])
    assert any("invented" in token for token in loud["absent"])


def test_absence_check_uses_only_observations_never_the_objective_plan_or_arguments():
    report = {"planner_summary": "Order 8842 confirmed at 09:15.",
              "objective": "Confirm order 8842 at 09:15",
              "plan": {"steps": ["confirm order 8842"]},
              "steps": [{"step": 1, "tool": "browser.read", "outcome": {"ok": True, "result": {"text": "no numbers here"}}}]}
    out = loop.summary_tokens_absent_from_observations(report)
    assert set(out["absent"]) == {"8842", "09:15"}
    assert loop.summary_tokens_absent_from_observations({"planner_summary": None, "steps": []}) is None


def test_chat_line_appears_only_when_a_token_is_absent():
    absent = {"version": "v1", "checked": 2, "absent": ["8842"], "grounded_in": {"09:15": [1]}}
    text = loop._chat_report({"summary": "s", "steps": [], "summary_tokens_absent_from_observations": absent})
    assert "8842" in text and "in keiner Beobachtung" in text
    silent = loop._chat_report({"summary": "s", "steps": [], "summary_tokens_absent_from_observations": {**absent, "absent": []}})
    assert "in keiner Beobachtung" not in silent


def test_report_carries_the_absence_check_after_a_finish(isolated):
    root, ledger = isolated
    finish = {"type": "finish", "summary": "The fixture says 4711."}
    result = loop.run_computer_task(root, "Read fixture", service=Service(), ledger=ledger, propose=planner(READ, finish))
    assert result["state"] == "completed"
    assert result["summary_tokens_absent_from_observations"]["absent"] == ["4711"]
    stalled = loop.run_computer_task(root, "Read fixture", service=Service(max_steps=8), ledger=ledger,
                                     propose=planner(PLAN, PLAN, PLAN, READ, DONE))
    assert stalled["summary_tokens_absent_from_observations"] is None, "no finish, nothing to check"


# --------------------------------------------------------------------------
# Odysseus 2026-09-06 09:04 on lane 11 (findings 1, 4, 5): pinned counter, dead-PID heartbeat,
# heartbeat without a bound root
# --------------------------------------------------------------------------

def test_final_plan_progress_is_in_the_report_and_absent_without_a_plan(isolated):
    root, ledger = isolated
    done = loop.run_computer_task(root, "Read fixture", service=Service(max_steps=8), ledger=ledger,
                                  propose=planner(PLAN_TWO, READ, READ, DONE))
    assert done["plan_progress"]["tool_steps_since_plan"] == 2 and done["plan_progress"]["every_step_has_a_tool_step"] is True
    plain = loop.run_computer_task(root, "Read fixture", service=Service(), ledger=ledger, propose=planner(READ, DONE))
    assert plain["plan_progress"] is None


def test_a_fresh_heartbeat_whose_process_is_gone_does_not_tick(tmp_path, monkeypatch):
    root = tmp_path / "authority"; root.mkdir()
    now = 1_000_000.0
    _heartbeat(tmp_path, monkeypatch, {"epoch": now - 5, "pid": 999999, "repo_root": str(root), "current": None})
    monkeypatch.setattr(loop, "_pid_alive", lambda pid: False)
    gone = loop.watcher_projection(root, now=now)
    assert (gone["state"], gone["ticks_this_root"], gone["pid_alive"]) == ("dead_pid", False, False)
    assert "nicht aktiv (dead_pid)" in loop._watcher_line(gone)
    monkeypatch.setattr(loop, "_pid_alive", lambda pid: True)
    alive = loop.watcher_projection(root, now=now)
    assert (alive["state"], alive["ticks_this_root"], alive["pid_alive"]) == ("alive", True, True)


def test_own_process_is_alive_and_a_non_pid_is_unknown():
    import os
    assert loop._pid_alive(os.getpid()) is True
    assert loop._pid_alive(None) is None and loop._pid_alive(-1) is None


def test_a_heartbeat_without_a_bound_root_is_named_as_such(tmp_path, monkeypatch):
    root = tmp_path / "authority"; root.mkdir()
    now = 1_000_000.0
    _heartbeat(tmp_path, monkeypatch, {"epoch": now - 5, "pid": 4242, "repo_root": None, "project": "p", "current": None})
    monkeypatch.setattr(loop, "_pid_alive", lambda pid: True)
    unbound = loop.watcher_projection(root, now=now)
    assert (unbound["state"], unbound["serves_this_root"], unbound["ticks_this_root"]) == ("alive", False, False)
    line = loop._watcher_line(unbound)
    assert "ohne Ordnerbindung" in line and "None" not in line


# --------------------------------------------------------------------------
# G1-IKARUS-45: a bounded prompt view of the history (Momus design A with his constraints),
# built only after measure-11c showed the local window overflows on one page read
# --------------------------------------------------------------------------

def _read_history(*texts, ok=True, tool="browser.read", start=1):
    return [{"step": start + i, "tool": tool, "outcome": {"ok": ok, "state": "verified", "result": {"text": t}},
             "artifact": {"sha256": "a" * 64, "locator": "artifact-locator:sha256:" + "a" * 64}} for i, t in enumerate(texts)]


def test_prompt_view_is_pure_bounded_and_marks_every_elision():
    import copy
    history = _read_history("A" * 10_000, "B" * 10_000, "C" * 10_000, "D" * 10_000)
    before = copy.deepcopy(history)
    view, compaction = loop._prompt_view(history, budget_chars=15_000)
    assert history == before, "the retained history is never mutated"
    assert compaction["version"] == "v1" and compaction["applied"] is True and compaction["fits"] is True
    assert compaction["elided_steps"] == [1, 2, 3, 4] and compaction["verbatim_window"] == loop._STALL_OBSERVATIONS
    oldest = view[0]["outcome"]["result"]
    assert len(oldest["text"]) == loop._OLD_OBSERVATION_TEXT_CHARS and oldest["text_elided"] is True
    assert oldest["text_full_chars"] == 10_000 and len(oldest["text_full_sha256"]) == 64
    assert view[0]["elided_by_prompt_view"] is True and "artifact" in view[0]
    shares = {len(entry["outcome"]["result"]["text"]) for entry in view[1:]}
    assert len(shares) == 1 and loop._MIN_WINDOW_TEXT_CHARS <= shares.pop() < 10_000, "the window shares equally"
    assert sum(len(json.dumps(e, ensure_ascii=False)) for e in view) <= 15_000
    again, _ = loop._prompt_view(history, budget_chars=15_000)
    assert again == view, "deterministic"


def test_prompt_view_keeps_failed_observations_verbatim_and_needs_no_change_when_it_fits():
    history = _read_history("F" * 5_000, ok=False) + _read_history("G" * 5_000, "H" * 5_000, "I" * 5_000, start=2)
    view, compaction = loop._prompt_view(history, budget_chars=12_000)
    assert view[0]["outcome"]["result"]["text"] == "F" * 5_000 and "elided_by_prompt_view" not in view[0]
    assert compaction["applied"] is True and 1 not in compaction["elided_steps"]
    small, none = loop._prompt_view(_read_history("x" * 100), budget_chars=10_000)
    assert none["applied"] is False and small[0]["outcome"]["result"]["text"] == "x" * 100
    unknown, no_window = loop._prompt_view(_read_history("y" * 100_000), budget_chars=None)
    assert no_window["applied"] is False and no_window["reason"] == "no known window"
    with pytest.raises(ValueError):
        loop._prompt_view(history, budget_chars=12_000, verbatim_window=loop._STALL_OBSERVATIONS - 1)


def test_the_loop_bounds_the_prompt_to_the_local_window_and_reports_it(isolated, monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    root, ledger = isolated
    propose, prompts = _capturing_planner(READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=LongTextService(30_000), ledger=ledger,
                                    propose=propose, mission_id="compaction-local")
    assert result["state"] == "completed"
    assert result["prompt_overflow_calls"] == 0 and result["prompt_chars_max"] <= 6144 * 4
    shown = prompts[1]["observations"][0]["outcome"]["result"]
    assert shown["text_elided"] is True and shown["text_full_chars"] == 30_000 and len(shown["text"]) < 30_000
    assert result["compaction"]["version"] == "v1" and result["compaction"]["applied_calls"] == 1
    assert result["steps"][0]["outcome"]["result"]["text"] == "x" * 30_000, "the report keeps the full observation"
    artifacts = (root / "control" / "ikarus-computer-artifacts").glob("*.json")
    proposals = [json.loads(path.read_text()) for path in artifacts if '"ikarus-computer-proposal/1"' in path.read_text()]
    assert any(a["compaction"]["applied"] for a in proposals) and all("compaction" in a for a in proposals)
    assert "text_elided" in json.dumps(prompts[1]) and "elided" in prompts[1].get("_directive", "") or "elided" in loop._prompt("o", [], [], {})


def test_a_remote_planner_gets_the_full_history(isolated):
    root, ledger = isolated
    propose, prompts = _capturing_planner(READ, DONE)
    result = loop.run_computer_task(root, "Read fixture", service=RemoteService(), ledger=ledger, propose=propose)
    assert result["compaction"]["applied_calls"] == 0 and result["compaction"]["reason"] == "no known window"


def test_a_stall_on_elided_reads_is_attributed_to_the_view(isolated, monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "6144")
    root, ledger = isolated
    result = loop.run_computer_task(root, "Read fixture", service=LongTextService(30_000, max_steps=8), ledger=ledger,
                                    propose=planner(READ, READ, READ, DONE))
    assert result["state"] == "stalled" and result["stall_after_elision"] is True
    assert "elided" in result["summary"]
    plain = loop.run_computer_task(root, "Read fixture", service=Service(max_steps=8), ledger=ledger,
                                   propose=planner(READ, READ, READ, DONE))
    assert plain["state"] == "stalled" and plain["stall_after_elision"] is False
