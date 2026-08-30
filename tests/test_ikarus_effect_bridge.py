"""G1-IKARUS-06: Ikarus one-shot -> canonical effect-kernel bridge."""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

from daedalus.ikarus_effect_bridge import (
    IkarusEffectBridgeRefused,
    build_oneshot_effect_execution_request,
    build_oneshot_effect_lease_request,
)
from daedalus.ikarus_oneshot import OneShotRequest
from daedalus.ikarus_tool_scope import project_oneshot_tool_scope
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.schemas import ContractProvenance, ResourceBudget
from daedalus.spine.effect_boundary import Effect


ROOT = Path(__file__).resolve().parents[1]
TOOL_SCOPE_FIXTURE = ROOT / "tests/test_ikarus_tool_scope.py"


def _load_tool_scope_fixture():
    name = "daedalus_test_ikarus_effect_bridge_tool_scope_fixture"
    spec = importlib.util.spec_from_file_location(name, TOOL_SCOPE_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_tool_scope_fixture()


def _subjects(tmp_path: Path, *, cost_bound: int | None = 100_000):
    binding = fixture._binding()
    request = OneShotRequest.from_runtime_binding(
        binding,
        purpose="effect-kernel-bridge",
        instructions="Operate only inside the supplied effect scope.",
        user_input="Inspect the evidence once.",
        budget=ResourceBudget(
            max_tokens=1024,
            max_cost_microusd=cost_bound,
            max_wall_time_s=60,
            max_attempts=1,
        ),
    )
    manifest = fixture._manifest()
    evidence = fixture._runtime_evidence(request, binding, manifest, tmp_path)
    policy = fixture._policy(request)
    tools = project_oneshot_tool_scope(
        request,
        evidence,
        manifest,
        policy,
        requested_tools=("read-file", "web-search"),
        disabled_tools=("web-search",),
    )
    return request, evidence, tools


def _effect_request(tmp_path: Path, **overrides):
    request, evidence, tools = _subjects(tmp_path)
    kwargs = {
        "request_id": "ikarus-effect-request-1",
        "mission_id": "mission-ikarus-1",
        "attempt_id": "attempt-ikarus-1",
        "entrypoint_id": "provider.hermes-oneshot",
        "idempotency_namespace": "mission-ikarus-1-attempt-1",
        "kill_switch_ref": "mission-ikarus-kill",
        "kill_switch_generation": 4,
        "requested_effects": (
            Effect.FILESYSTEM_WRITE,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
            Effect.SECRETS,
        ),
        "created_at": fixture.NOW,
        "writable_paths": ("workspace/out.txt",),
        "egress_endpoints": ("https://api.example.test/v1",),
        "secret_refs": ("provider-key",),
    }
    kwargs.update(overrides)
    effect_request = build_oneshot_effect_lease_request(
        request,
        evidence,
        tools,
        **kwargs,
    )
    return request, evidence, tools, effect_request


def test_bridge_emits_only_canonical_effect_lease_request(tmp_path):
    request, evidence, tools, effect_request = _effect_request(tmp_path)

    assert type(effect_request) is EffectLeaseRequest
    assert effect_request.runtime_manifest_sha256 == evidence.runtime_manifest_sha256
    assert effect_request.runtime_conformance_sha256 == evidence.runtime_conformance_sha256
    assert effect_request.provenance.source_revision == evidence.source_revision
    assert request.digest in effect_request.provenance.input_digests
    assert evidence.digest in effect_request.provenance.input_digests
    assert tools.digest in effect_request.provenance.input_digests
    assert tools.policy_decision_sha256 in effect_request.provenance.input_digests
    assert effect_request.effect_scope.tools == ("read-file",)
    assert effect_request.effect_scope.writable_paths == ("workspace/out.txt",)
    assert effect_request.effect_scope.egress_endpoints == (
        "https://api.example.test/v1",
    )
    assert effect_request.effect_scope.secret_refs == ("provider-key",)
    assert effect_request.effect_scope.max_cost_microusd == 100_000
    assert effect_request.effect_scope.timeout_s == 60
    assert effect_request.effect_scope.max_concurrency == 1
    assert effect_request.effect_scope.kill_switch_ref == "mission-ikarus-kill"
    assert effect_request.effect_scope.read_only is False


def test_execution_request_is_exactly_narrowed_from_kernel_request(tmp_path):
    request, evidence, tools, effect_request = _effect_request(tmp_path)
    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="ikarus-execution-1",
        idempotency_key="ikarus-execution-key-1",
        requested_effects=(Effect.NETWORK_EGRESS, Effect.SPEND),
        writable_paths=(),
        secret_refs=(),
        max_cost_microusd=25_000,
    )

    assert type(execution) is EffectExecutionRequest
    assert execution.requested_effects == (
        Effect.NETWORK_EGRESS.value,
        Effect.SPEND.value,
    )
    assert execution.tools == tools.enabled_tools == ("read-file",)
    assert execution.writable_paths == ()
    assert execution.egress_endpoints == ("https://api.example.test/v1",)
    assert execution.secret_refs == ()
    assert execution.max_cost_microusd == 25_000
    assert execution.kill_switch_ref == effect_request.effect_scope.kill_switch_ref
    assert execution.kill_switch_generation == effect_request.kill_switch_generation


def test_disabled_tool_never_reappears_at_kernel_or_execution_boundary(tmp_path):
    request, evidence, tools, effect_request = _effect_request(tmp_path)
    assert tools.requested_tools == ("read-file", "web-search")
    assert tools.disabled_tools == ("web-search",)
    assert effect_request.effect_scope.tools == ("read-file",)

    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="ikarus-execution-2",
        idempotency_key="ikarus-execution-key-2",
    )
    assert execution.tools == ("read-file",)
    assert "web-search" not in execution.tools


def test_timeout_cannot_broaden_one_shot_wall_time_budget(tmp_path):
    request, evidence, tools = _subjects(tmp_path)
    with pytest.raises(IkarusEffectBridgeRefused, match="wall-time budget"):
        build_oneshot_effect_lease_request(
            request,
            evidence,
            tools,
            request_id="ikarus-effect-request-timeout",
            mission_id="mission-timeout",
            attempt_id="attempt-timeout",
            entrypoint_id="provider.hermes-oneshot",
            idempotency_namespace="mission-timeout-attempt",
            kill_switch_ref="mission-timeout-kill",
            kill_switch_generation=1,
            requested_effects=(Effect.NETWORK_EGRESS,),
            created_at=fixture.NOW,
            egress_endpoints=("https://api.example.test/v1",),
            timeout_s=61,
        )


def test_spend_effect_requires_explicit_one_shot_cost_bound(tmp_path):
    request, evidence, tools = _subjects(tmp_path, cost_bound=None)
    with pytest.raises(IkarusEffectBridgeRefused, match="spend effect"):
        build_oneshot_effect_lease_request(
            request,
            evidence,
            tools,
            request_id="ikarus-effect-request-spend",
            mission_id="mission-spend",
            attempt_id="attempt-spend",
            entrypoint_id="provider.hermes-oneshot",
            idempotency_namespace="mission-spend-attempt",
            kill_switch_ref="mission-spend-kill",
            kill_switch_generation=1,
            requested_effects=(Effect.NETWORK_EGRESS, Effect.SPEND),
            created_at=fixture.NOW,
            egress_endpoints=("https://api.example.test/v1",),
        )


@pytest.mark.parametrize(
    "scope_kwargs,effects,missing",
    [
        (
            {"writable_paths": ("workspace/out.txt",)},
            (Effect.PROCESS_SPAWN,),
            "filesystem_write",
        ),
        (
            {"egress_endpoints": ("https://api.example.test/v1",)},
            (Effect.PROCESS_SPAWN,),
            "network_egress",
        ),
        (
            {"secret_refs": ("provider-key",)},
            (Effect.PROCESS_SPAWN,),
            "secrets",
        ),
    ],
)
def test_scope_cannot_exist_without_corresponding_canonical_effect(
    tmp_path,
    scope_kwargs,
    effects,
    missing,
):
    request, evidence, tools = _subjects(tmp_path)
    with pytest.raises(IkarusEffectBridgeRefused, match=missing):
        build_oneshot_effect_lease_request(
            request,
            evidence,
            tools,
            request_id="ikarus-effect-request-missing",
            mission_id="mission-missing",
            attempt_id="attempt-missing",
            entrypoint_id="provider.hermes-oneshot",
            idempotency_namespace="mission-missing-attempt",
            kill_switch_ref="mission-missing-kill",
            kill_switch_generation=1,
            requested_effects=effects,
            created_at=fixture.NOW,
            **scope_kwargs,
        )


def test_runtime_evidence_substitution_refuses_before_kernel_projection(tmp_path):
    request, evidence, tools = _subjects(tmp_path)
    foreign = dataclasses.replace(evidence, request_sha256="f" * 64)
    with pytest.raises(IkarusEffectBridgeRefused, match="runtime evidence request"):
        build_oneshot_effect_lease_request(
            request,
            foreign,
            tools,
            request_id="ikarus-effect-request-foreign",
            mission_id="mission-foreign",
            attempt_id="attempt-foreign",
            entrypoint_id="provider.hermes-oneshot",
            idempotency_namespace="mission-foreign-attempt",
            kill_switch_ref="mission-foreign-kill",
            kill_switch_generation=1,
            requested_effects=(Effect.NETWORK_EGRESS,),
            created_at=fixture.NOW,
            egress_endpoints=("https://api.example.test/v1",),
        )


def test_execution_cannot_broaden_effect_paths_or_cost(tmp_path):
    request, evidence, tools, effect_request = _effect_request(tmp_path)
    common = {
        "execution_id": "ikarus-execution-broad",
        "idempotency_key": "ikarus-execution-broad-key",
    }
    with pytest.raises(IkarusEffectBridgeRefused, match="requested_effects"):
        build_oneshot_effect_execution_request(
            request,
            evidence,
            tools,
            effect_request,
            requested_effects=(Effect.REPOSITORY_MUTATION,),
            **common,
        )
    with pytest.raises(IkarusEffectBridgeRefused, match="writable_paths"):
        build_oneshot_effect_execution_request(
            request,
            evidence,
            tools,
            effect_request,
            writable_paths=("workspace/foreign.txt",),
            **common,
        )
    with pytest.raises(IkarusEffectBridgeRefused, match="cost"):
        build_oneshot_effect_execution_request(
            request,
            evidence,
            tools,
            effect_request,
            max_cost_microusd=100_001,
            **common,
        )


def test_execution_rejects_kernel_request_without_ikarus_provenance(tmp_path):
    request, evidence, tools, effect_request = _effect_request(tmp_path)
    provenance = ContractProvenance(
        origin="tests.foreign-effect-request",
        source_revision=effect_request.provenance.source_revision,
        created_at=fixture.NOW.isoformat(),
        input_digests=(
            effect_request.runtime_manifest_sha256,
            effect_request.runtime_conformance_sha256,
        ),
        trace_id=effect_request.mission_id,
    )
    foreign = dataclasses.replace(effect_request, provenance=provenance)
    with pytest.raises(IkarusEffectBridgeRefused, match="provenance"):
        build_oneshot_effect_execution_request(
            request,
            evidence,
            tools,
            foreign,
            execution_id="ikarus-execution-foreign",
            idempotency_key="ikarus-execution-foreign-key",
        )


def test_bridge_has_no_provider_policy_lease_or_io_authority():
    path = ROOT / "daedalus/ikarus_effect_bridge.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert not ({"subprocess", "socket", "requests", "httpx", "sqlite3", "os"} & imports)
    assert not (
        {
            "open",
            "exec",
            "eval",
            "run_runtime_provider",
            "issue_effect_lease",
            "issue_runtime_bound_effect_lease",
        }
        & call_names
    )
