"""Computer/Genesis adapter contracts; runner doubles are not live LLM evidence."""
import json

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, DAEDALUS_TOOLS, GENESIS_TOOLS
from daedalus.runtimes import computer as runtime
from daedalus.runtimes.computer_genesis import GenesisBuildTool, GenesisRunner, GenesisPreRunRefusal, GenesisRunFailure


def green(**kw):
    return {"request_key": kw["request_key"], "target": kw["target"], "run_id": "genesis-abc123",
            "status": "preview-ready", "candidate": {"sha256": "a" * 64, "locator": "/home/private/cas"},
            "evidence": {"sha256": "b" * 64, "status": "passed", "candidate_tree_sha256": "a" * 64},
            "roundtrip": {"sha256": "c" * 64, "status": "passed", "checks": {k: True for k in ("build", "test", "runtime", "package", "containment", "code", "type", "data", "knowledge", "tensor_kernel")}},
            "publication": {"status": "not-requested", "automatic_promotion": False, "owner_approval_required": True}, "blockers": []}


def test_separate_owner_grant_and_closed_schema(tmp_path):
    assert GENESIS_TOOLS == ("daedalus.genesis",)
    assert not set(GENESIS_TOOLS) & set(DAEDALUS_TOOLS)
    assert ComputerPolicy(workspace=tmp_path).tools == ()
    assert GENESIS_TOOLS[0] in runtime._HOST_MUTATION_TOOLS
    for args in ({}, {"prompt": "x", "repo_root": "/"}, {"prompt": "x", "target": "shell"}, {"prompt": 1}):
        with pytest.raises(ComputerRefused):
            runtime._validate_arguments(GENESIS_TOOLS[0], args)


def test_canonical_port_receives_bound_request_and_checkpoint(tmp_path):
    calls, checkpoints = [], []
    def run(prompt, **kwargs):
        calls.append((prompt, kwargs)); kwargs["caller_checkpoint"]()
        return green(**kwargs)
    tool = GenesisBuildTool(tmp_path, lambda: checkpoints.append(1), GenesisRunner(run))
    first = tool.execute({"prompt": "Build a task board"})
    second = tool.execute({"prompt": "Build a task board"})
    assert calls[0][1]["repo_root"] == tmp_path
    assert calls[0][1]["request_key"] == calls[1][1]["request_key"]
    assert len(checkpoints) == 6
    assert first == second and first["postcondition_verified"] is True
    assert first["tensor_kernel_verified"] is True and first["applied"] is False
    assert "/home/private" not in json.dumps(first)


@pytest.mark.parametrize("args", [{}, {"prompt": ""}, {"prompt": "x", "target": "shell"},
                                  {"prompt": "x", "argv": ["python"]}, {"prompt": "x", "stack": 1}])
def test_bad_request_never_enters_workload(tmp_path, args):
    def forbidden(*a, **kw):
        pytest.fail("invalid request entered Genesis")
    tool = GenesisBuildTool(tmp_path, lambda: None, GenesisRunner(forbidden))
    with pytest.raises(GenesisPreRunRefusal):
        tool.execute(args)


@pytest.mark.parametrize("field,value", [("request_key", "other"), ("target", "cli"),
                                         ("status", "running"), ("candidate", {}),
                                         ("publication", {"automatic_promotion": True}),
                                         ("roundtrip", {"checks": {"tensor_kernel": "true"}})])
def test_bad_receipt_is_uncertain_not_a_success_or_effect_free_refusal(tmp_path, field, value):
    def run(prompt, **kw):
        return {**green(**kw), field: value}
    tool = GenesisBuildTool(tmp_path, lambda: None, GenesisRunner(run))
    with pytest.raises(GenesisRunFailure) as caught:
        tool.execute({"prompt": "Build a task board"})
    assert caught.value.effect_state == "uncertain"


def test_exception_text_does_not_leak_host_path(tmp_path):
    def run(*args, **kwargs):
        raise RuntimeError("private /home/victim/secret")
    tool = GenesisBuildTool(tmp_path, lambda: None, GenesisRunner(run))
    with pytest.raises(GenesisRunFailure) as caught:
        tool.execute({"prompt": "Build tasks"})
    assert "/home/victim" not in str(caught.value)


def test_missing_port_is_not_advertised_or_leased(tmp_path, monkeypatch):
    policy = ComputerPolicy(workspace=tmp_path / "workspace", tools=GENESIS_TOOLS)
    monkeypatch.setattr(runtime, "load_policy", lambda root: policy)
    monkeypatch.setattr(runtime, "control_root", lambda root: tmp_path / "control")
    service = runtime.ComputerService(tmp_path)
    assert service.capabilities()["tools"] == []
    with pytest.raises(ComputerRefused, match="Genesis runner"):
        service._admit_release_capability(GENESIS_TOOLS[0], {"prompt": "Build tasks"})


def test_hopping_mode_narrows_tools_and_requires_owner_tests(tmp_path, monkeypatch):
    from daedalus.runtimes.computer_ariadne import CampaignRunner
    tools = GENESIS_TOOLS + ("daedalus.ariadne_campaign",)
    policy = ComputerPolicy(workspace=tmp_path / "workspace", tools=tools)
    monkeypatch.setattr(runtime, "load_policy", lambda root: policy)
    monkeypatch.setattr(runtime, "control_root", lambda root: tmp_path / "control")
    service = runtime.ComputerService(tmp_path, project="fixture", hopping=True,
                                     genesis_runner=GenesisRunner(lambda *a, **k: None),
                                     campaign_runner=CampaignRunner(lambda **k: None, lambda r: "a" * 40, lambda p: None))
    caps = service.capabilities()
    assert [t["name"] for t in caps["tools"]] == ["daedalus.ariadne_campaign"]
    assert caps["tools"][0]["parameters"]["properties"]["evaluation"]["enum"] == ["owner-tests"]
    with pytest.raises(ComputerRefused, match="hopping"):
        service._admit_release_capability("daedalus.genesis", {"prompt": "Build tasks"})


def _configured_service(tmp_path, monkeypatch, runner):
    from daedalus.kernel.policy.computer import policy_path
    from daedalus.spine import killswitch
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    policy = ComputerPolicy(workspace=tmp_path / "workspace", tools=GENESIS_TOOLS)
    path = policy_path(authority)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="isolated Genesis adapter acceptance").running
    return runtime.ComputerService(authority, genesis_runner=runner)


def test_real_computer_lease_retains_genesis_scope_and_verified_result(tmp_path, monkeypatch):
    # The builder is a double; only the Computer lease and retention are real.
    service = _configured_service(tmp_path, monkeypatch, GenesisRunner(lambda prompt, **kw: green(**kw)))
    result = service.execute("daedalus.genesis", {"prompt": "Build tasks"}, mission_id="genesis-lease", attempt_id="one")
    assert result["ok"] is True, result
    assert result["result"]["tensor_kernel_verified"] is True
    stored = [json.loads(p.read_text()) for p in (service.control / "computer-artifacts").glob("*.json")]
    observations = [o for o in stored if o.get("schema") == "daedalus-computer-result/1"]
    assert len(observations) == 1
    assert observations[0]["filesystem_scope_kind"] == "control-root-genesis-candidate"
    assert observations[0]["host_mutation"] is True
    assert "locator" not in json.dumps(observations[0]["result"])


def test_real_lease_distinguishes_genesis_preflight_from_uncertain_effect(tmp_path, monkeypatch):
    def broken(prompt, **kw):
        raise RuntimeError("inner build failed")
    service = _configured_service(tmp_path, monkeypatch, GenesisRunner(broken))
    refused = service.execute("daedalus.genesis", {"prompt": " "}, mission_id="genesis-refusal", attempt_id="one")
    assert refused["state"] == "blocked", refused
    uncertain = service.execute("daedalus.genesis", {"prompt": "Build tasks"}, mission_id="genesis-failed", attempt_id="two")
    assert uncertain["state"] == "reconciliation_required", uncertain


@pytest.mark.skipif(__import__("os").name != "nt", reason="real candidate runtime acceptance runs on Windows CI")
def test_real_genesis_through_real_computer_lease_runs_tensor_kernel(tmp_path, monkeypatch):
    from daedalus.orchestration.genesis.service import run_genesis
    service = _configured_service(tmp_path, monkeypatch, GenesisRunner(run_genesis))
    result = service.execute("daedalus.genesis", {"prompt": "Build a local task board with search"},
                             mission_id="genesis-native", attempt_id="one")
    assert result["ok"] is True, result
    observed = result["result"]
    assert observed["status"] == "preview-ready", observed
    assert observed["tensor_kernel_verified"] is observed["postcondition_verified"] is True
    assert observed["applied"] is observed["automatic_promotion"] is False
    assert observed["candidate_tree_sha256"] and observed["evidence_packet_sha256"]
