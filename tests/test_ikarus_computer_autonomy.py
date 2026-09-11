"""Bounded advisory planning over real canonical storage, with inert host fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.spine.durability import open_gate0_spine_writer


READ = {"type": "tool", "tool": "browser.read", "arguments": {}}
FILL = {"type": "tool", "tool": "browser.fill", "arguments": {"text": "fixture"}}
DONE = {"type": "finish", "summary": "The observed fixture is present."}
PLAN = {"type": "plan", "steps": ["Read the page", "Check the fixture"]}


class Service:
    policy_digest = "a" * 64

    def __init__(self, *, max_steps=8, enabled=True, outcome=None):
        self.calls = []
        self.max_steps = max_steps
        self.enabled = enabled
        self.outcome = outcome
        self.closed = False
        self.probes = []
        self.probe = None

    def capabilities(self):
        return {"enabled": self.enabled, "max_steps": self.max_steps, "timeout_s": 20,
                "tools": [{"name": "browser.read", "parameters": {
                    "type": "object", "properties": {}, "additionalProperties": False}},
                    {"name": "browser.fill", "parameters": {"type": "object",
                        "properties": {"text": {"type": "string"}}, "required": ["text"],
                        "additionalProperties": False}}]}

    def set_cancellation_probe(self, callback):
        self.probes.append(callback)
        self.probe = callback

    def check_cancelled(self):
        if self.probe and self.probe():
            raise RuntimeError("owner cancelled")

    def execute(self, tool, arguments, *, mission_id, attempt_id):
        self.calls.append((tool, arguments, mission_id, attempt_id))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome or {
            "ok": True, "state": "completed", "result": {
                "status": "observed", "document_sha256": "b" * 64, "text": "fixture",
                "observation_id": str(len(self.calls)), "postcondition_verified": False},
            "evidence": {"receipt": str(len(self.calls))},
        }

    def close(self):
        self.closed = True


class Planner:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, prompt, capabilities, limit_policy, remaining):
        self.calls.append((json.loads(prompt.rsplit("\n", 1)[1]), remaining))
        response = next(self.responses)
        return response if isinstance(response, str) else json.dumps(response)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.setattr(loop, "control_root", lambda root: tmp_path / "control")
    monkeypatch.setattr(loop, "_context_snapshot", lambda root: {
        "context_sha256": "d" * 64, "notes": [], "skills": []})
    with open_gate0_spine_writer(tmp_path / "canonical.sqlite3") as ledger:
        yield tmp_path, ledger


def artifact(root, ref):
    return json.loads((root / "control" / "ikarus-computer-artifacts" / (ref["sha256"] + ".json")).read_text())


@pytest.mark.parametrize("steps", [[], ["x"] * 13, [""], ["  "], [1], ["x" * 241], ["x\ny"], ["x\ry"]])
def test_plan_shape_is_bounded(steps):
    with pytest.raises(loop.ComputerLoopRefused):
        loop._parse_proposal(json.dumps({"type": "plan", "steps": steps}))


def test_plan_cannot_add_authority():
    with pytest.raises(loop.ComputerLoopRefused):
        loop._parse_proposal(json.dumps({**PLAN, "policy": "allow-all"}))
    assert loop._parse_proposal(json.dumps({"type": "plan", "steps": ["x" * 240] * 12}))["type"] == "plan"


def test_plan_and_replan_are_advisory_mission_bound_artifacts(isolated):
    root, ledger = isolated
    service = Service(max_steps=4)
    revised = {"type": "plan", "steps": ["Report the retained observation"]}
    planner = Planner(PLAN, READ, revised, DONE)
    events = list(loop.computer_events(root, "Inspect fixture", service=service, ledger=ledger,
                                      propose=planner, mission_id="planned-fixture"))
    report = events[-1][1]
    assert report["state"] == "completed"
    assert (report["planner_calls"], report["tool_steps"], report["replans"], report["repair_calls"]) == (4, 1, 1, 0)
    assert report["task_success_verified"] is False
    assert report["plan"]["advisory"] is True and report["plan"]["revision"] == 2
    assert report["plan"]["steps"] == revised["steps"]
    assert service.calls[0][-1] == "planned-fixture-step-0001"
    assert len([payload for event, payload in events if payload.get("phase") == "plan"]) == 2
    raw_plan = artifact(root, report["plan"]["artifact"])
    assert json.loads(raw_plan["response"]) == revised
    assert raw_plan["mission_sha256"] == report["mission_sha256"]
    assert raw_plan["authority_root"] == str(root)
    assert artifact(root, report["mission_artifact"])["authority_root"] == str(root)
    assert all(row.payload["authority_root"] == str(root) for row in ledger.recent_intents(loop.PROPOSAL_KIND))
    assert ledger.recent_intents(loop.STEP_KIND)[0].payload["authority_root"] == str(root)
    assert not ledger.open_intents()


def test_advisory_plan_schema_reaches_guarded_transport(monkeypatch):
    from daedalus.orchestration.ikarus import shell
    captured = []
    monkeypatch.setattr(loop, "_require_context_route", lambda caps: "ollama_http")
    def llm(*args, **kwargs):
        captured.append(kwargs["response_schema"])
        return json.dumps(PLAN), "fixture", None
    monkeypatch.setattr(shell, "_llm", llm)
    loop._model_proposal("fixture", {"tools": []}, loop.load_from_env(), 1)
    plan = next(spec for spec in captured[0]["anyOf"] if spec["properties"]["type"]["const"] == "plan")
    assert plan["properties"]["steps"]["maxItems"] == 12
    assert plan["additionalProperties"] is False


@pytest.mark.parametrize("responses, expected_tools", [((PLAN, PLAN, DONE), 0), (("invalid", READ, DONE), 1)])
def test_plans_and_repairs_consume_same_total_budget(isolated, responses, expected_tools):
    root, ledger = isolated
    service = Service(max_steps=2)
    planner = Planner(*responses)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "step_limit"
    assert report["planner_calls"] == len(planner.calls) == 2
    assert len(service.calls) == expected_tools


def test_two_correction_chances_retain_every_exact_invalid_response(isolated):
    root, ledger = isolated
    service = Service()
    raw = '  {"type": "invalid", "hint": "synthetic fixture"}\n'
    planner = Planner(raw, raw, raw, READ)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "blocked"
    assert report["planner_calls"] == 3 and report["repair_calls"] == 2
    assert not service.calls
    assert len(report["proposals"]) == 3
    for ref in report["proposals"]:
        retained = artifact(root, ref)
        assert retained["response"] == raw
        assert retained["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert len(ledger.recent_intents(loop.PROPOSAL_KIND)) == 3


@pytest.mark.parametrize("invalid", ["not JSON", {"type": "tool", "tool": "file.read", "arguments": {}},
                                      {"type": "tool", "tool": "browser.fill", "arguments": {"text": 7}}])
def test_preflight_correction_is_bounded_data_and_cleared_after_valid_plan(isolated, invalid):
    root, ledger = isolated
    service = Service()
    planner = Planner(invalid, PLAN, READ, DONE)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "completed" and report["repair_calls"] == 1
    correction = planner.calls[1][0]["correction_context"]
    assert correction["trust"] == "untrusted_data"
    assert len(correction["response_excerpt"]) <= 2000 and len(correction["reason"]) <= 500
    assert "correction_context" not in planner.calls[2][0]
    assert len(service.calls) == 1 and service.calls[0][0] == "browser.read"


def test_successful_proposal_resets_consecutive_repair_chances(isolated):
    root, ledger = isolated
    planner = Planner("bad", "bad", PLAN, "bad", "bad", READ, DONE)
    report = loop.run_computer_task(root, "Inspect fixture", service=Service(), ledger=ledger, propose=planner)
    assert report["state"] == "completed"
    assert report["planner_calls"] == 7 and report["repair_calls"] == 4


def test_owner_disabled_attempts_remove_numeric_retry_and_call_caps(isolated, monkeypatch):
    from daedalus.limit_policy import ExecutionLimitPolicy, LimitAxes
    root, ledger = isolated
    policy = ExecutionLimitPolicy(mode="custom", configured=LimitAxes(attempts=False))
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", policy.to_env_value())
    planner = Planner("bad-one", "bad-two", "bad-three", "bad-four", READ, DONE)
    report = loop.run_computer_task(root, "Inspect fixture", service=Service(max_steps=1),
                                    ledger=ledger, propose=planner)
    assert report["state"] == "completed"
    assert report["planner_calls"] == 6 and report["repair_calls"] == 4
    assert all(remaining is not None for _, remaining in planner.calls)


def test_identical_invalid_output_stalls_when_retry_axis_is_disabled(isolated, monkeypatch):
    from daedalus.limit_policy import ExecutionLimitPolicy
    root, ledger = isolated
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", ExecutionLimitPolicy(mode="unbounded_execution").to_env_value())
    planner = Planner("same invalid response", "same invalid response", "same invalid response", READ)
    service = Service(max_steps=1)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "stalled" and report["planner_calls"] == 3
    assert not service.calls
    assert all(remaining is None for _, remaining in planner.calls)


def test_schema_preflight_rejects_invalid_hash_and_numeric_overflow():
    from daedalus.runtimes.computer import TOOL_SPECS
    inventory = {"file.write": {"parameters": TOOL_SPECS["file.write"][1]}}
    with pytest.raises(loop.ComputerLoopRefused, match="advertised format"):
        loop._validate_tool_proposal({"tool": "file.write", "arguments": {
            "path": "fixture", "text": "fixture", "expected_sha256": ""}}, inventory)
    with pytest.raises(loop.ComputerLoopRefused, match="one JSON"):
        loop._parse_proposal('{"type":"tool","tool":"desktop.click","arguments":{"x":1e999}}')


def test_secret_response_is_hashed_withheld_and_never_repaired(isolated):
    root, ledger = isolated
    raw = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC-NONSECRET-FIXTURE\n-----END PRIVATE KEY-----"
    service = Service()
    planner = Planner(raw, READ)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "blocked" and report["planner_calls"] == 1
    assert report["repair_calls"] == 0 and not service.calls
    retained = artifact(root, report["proposals"][0])
    assert retained["response"] is None and retained["withheld_by_secret_floor"] is True
    assert retained["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert all(raw not in path.read_text() for path in (root / "control").rglob("*.json"))


@pytest.mark.parametrize("outcome", [
    {"ok": False, "state": "denied", "result": {}},
    {"ok": False, "state": "reconciliation_required", "result": {}},
    {"ok": True, "state": "completed", "result": {"postcondition_verified": False}},
    RuntimeError("effect outcome unknown"),
])
def test_adapter_refusal_unknown_or_failed_postcondition_never_replans(isolated, outcome):
    root, ledger = isolated
    service = Service(outcome=outcome)
    planner = Planner(READ, PLAN, READ)
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger, propose=planner)
    assert report["state"] == "blocked" and report["planner_calls"] == 1
    assert report["repair_calls"] == 0 and len(service.calls) == 1


def test_three_unchanged_read_observations_stall_despite_fresh_receipts(isolated):
    root, ledger = isolated
    service = Service()
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger,
                                    propose=Planner(READ, READ, READ, READ, DONE))
    assert report["state"] == "stalled"
    assert report["planner_calls"] == len(service.calls) == 3
    assert report["task_success_verified"] is False


def test_intervening_input_resets_no_progress_detection(isolated):
    root, ledger = isolated
    service = Service()
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger,
                                    propose=Planner(READ, READ, FILL, READ, READ, DONE))
    assert report["state"] == "completed" and len(service.calls) == 5


def test_distinct_content_or_target_evidence_is_progress():
    base = {"ok": True, "state": "completed", "result": {"text": "a", "document_sha256": "a" * 64}}
    changed = {**base, "result": {**base["result"], "document_sha256": "b" * 64}}
    assert loop._observation_signature("browser.read", {}, base) != loop._observation_signature("browser.read", {}, changed)
    assert loop._observation_signature("file.read", {"path": "a"}, base) != loop._observation_signature("file.read", {"path": "b"}, base)


def test_cancellation_before_suspended_model_call_prevents_it(isolated):
    root, ledger = isolated
    stopped = False
    service = Service()
    planner = Planner(READ)
    events = loop.computer_events(root, "Inspect fixture", service=service, ledger=ledger,
                                 propose=planner, cancelled=lambda: stopped)
    assert next(events)[1]["phase"] == "planning"
    stopped = True
    report = list(events)[-1][1]
    assert report["state"] == "cancelled" and report["planner_calls"] == 0
    assert not planner.calls and not service.calls and service.probe is None


def test_cancellation_after_correction_model_call_prevents_tool(isolated):
    root, ledger = isolated
    service = Service()
    planner = Planner("bad", READ)
    stopped = False
    def propose(*args):
        nonlocal stopped
        response = planner(*args)
        stopped = len(planner.calls) == 2
        return response
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger,
                                    propose=propose, cancelled=lambda: stopped)
    assert report["state"] == "cancelled" and report["planner_calls"] == 2
    assert not service.calls and service.probe is None


def test_plan_cannot_extend_shared_timeout(isolated):
    root, ledger = isolated
    now = 0
    planner = Planner(PLAN, READ)
    def propose(*args):
        nonlocal now
        response = planner(*args)
        now += 11
        return response
    service = Service()
    report = loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger,
                                    propose=propose, clock=lambda: now)
    assert report["state"] == "timeout" and report["planner_calls"] == 2
    assert [remaining for _, remaining in planner.calls] == [20, 9]
    assert not service.calls


@pytest.mark.parametrize("failure", ["disabled", "bad_steps", "caps_raise", "policy_changed", "limits_changed"])
def test_owned_service_closes_even_before_mission_admission(isolated, monkeypatch, failure):
    from daedalus.runtimes import computer
    root, ledger = isolated
    service = Service(enabled=failure != "disabled", max_steps=0 if failure == "bad_steps" else 8)
    if failure == "caps_raise":
        service.capabilities = lambda: (_ for _ in ()).throw(ValueError("invalid capability fixture"))
    monkeypatch.setattr(computer, "ComputerService", lambda *args, **kwargs: service)
    kwargs = {"expected_policy_sha256": "b" * 64} if failure == "policy_changed" else {}
    if failure == "limits_changed":
        kwargs["expected_execution_limit_policy_sha256"] = "b" * 64
    if failure == "disabled":
        assert loop.run_computer_task(root, "Inspect fixture", ledger=ledger, **kwargs)["state"] == "unavailable"
    else:
        with pytest.raises((loop.ComputerLoopRefused, ValueError)):
            loop.run_computer_task(root, "Inspect fixture", ledger=ledger, **kwargs)
    assert service.closed and service.probe is None
    assert not ledger.recent_intents(loop.MISSION_KIND)


def test_external_service_probe_is_cleared_without_taking_ownership(isolated):
    root, ledger = isolated
    service = Service()
    callback = lambda: False
    loop.run_computer_task(root, "Inspect fixture", service=service, ledger=ledger,
                           propose=Planner(DONE), cancelled=callback)
    assert service.probes == [callback, None]
    assert service.closed is False


def test_generator_close_clears_native_cancellation_probe(isolated):
    root, ledger = isolated
    service = Service()
    callback = lambda: False
    events = loop.computer_events(root, "Inspect fixture", service=service, ledger=ledger,
                                 propose=Planner(PLAN, READ), cancelled=callback)
    assert next(events)[1]["phase"] == "planning"
    assert next(events)[1]["phase"] == "plan"
    events.close()
    assert service.probes == [callback, None] and not service.calls
    assert ledger.recent_intents(loop.MISSION_KIND)[0].is_open


@pytest.mark.parametrize("authority", [None, "different-authority"])
def test_global_mission_id_cannot_replay_unscoped_or_other_authority(isolated, authority):
    root, ledger = isolated
    prior, _ = loop._claim_mission(ledger, {"objective": "Inspect fixture", "policy_sha256": "a" * 64,
                                         "authority_root": authority}, "scoped-fixture")
    ledger.mark_completed(prior.id, result={"state": "completed", "summary": "other authority private fixture"})
    planner = Planner(READ)
    with pytest.raises(loop.ComputerLoopRefused, match="authority root"):
        loop.run_computer_task(root, "Inspect fixture", service=Service(), ledger=ledger,
                               propose=planner, mission_id="scoped-fixture")
    assert not planner.calls


def test_runtime_path_release_fence_inventory_is_preserved():
    """G1-IKARUS-25 narrowed the v0.1.6 fence: file tools are projected through
    the handle-anchored adapter (file.write without replacement), path-based
    vision stays out, observation-only vision keeps its exact shape."""
    from daedalus.runtimes.computer import _release_tool_spec
    for name in ("vision.match", "vision.changes"):
        assert _release_tool_spec(name) is None
    for name in ("file.read", "file.write", "file.list", "file.move", "file.mkdir"):
        assert _release_tool_spec(name) is not None
    _, write_schema = _release_tool_spec("file.write")
    assert "expected_sha256" not in write_schema["properties"]
    for name in ("vision.inspect", "vision.ocr"):
        _, schema = _release_tool_spec(name)
        assert "path" not in schema["properties"]
        assert schema["required"] == ["observation_id"]
