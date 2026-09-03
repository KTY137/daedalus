"""G1-IKARUS-05: canonical-policy-bound per-call tool projection."""
from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.orchestration.ikarus.oneshot import OneShotRequest, bind_oneshot_runtime_evidence
from daedalus.orchestration.ikarus.runtime_role import (
    SOURCE_ONLY_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
)
from daedalus.orchestration.ikarus.tool_scope import (
    IkarusToolScopeRefused,
    project_oneshot_tool_scope,
)
from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    assemble_recorded_conformance,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    ResourceBudget,
    RuntimeCapabilities,
    RuntimeManifest,
)

HERMES_COMMIT = "fcbd1076a93841fa88855acce810e342a5b78101"
POLICY_SHA = "1" * 64
NOW = datetime(2026, 8, 30, 0, 30, tzinfo=timezone.utc)


def _binding():
    row = RuntimeRoleBinding(
        role="assistant",
        runtime_id="hermes_agent",
        adapter_id="hermes.oneshot-adapter",
        adapter_version="v2026.8.19",
        source_revision=HERMES_COMMIT,
        origin="https://github.com/NousResearch/hermes-agent",
        execution_mode=SOURCE_ONLY_EXECUTION_MODE,
        refusal_reason="source-only until broker-bound execution is admitted",
    )
    snapshot = RuntimeRoleRegistry((row,)).snapshot(row.role, row.runtime_id)
    assert snapshot is not None
    return snapshot


def _request(binding=None):
    binding = binding or _binding()
    return OneShotRequest.from_runtime_binding(
        binding,
        purpose="tool-selection",
        instructions="Use only explicitly enabled tools.",
        user_input="Inspect the requested evidence.",
        budget=ResourceBudget(
            max_tokens=1024,
            max_cost_microusd=100_000,
            max_wall_time_s=60,
            max_attempts=1,
        ),
    )


def _manifest(*, tools=("read-file", "terminal", "web-search")):
    return RuntimeManifest(
        runtime_id="hermes_agent",
        runtime_version="v0.20.5",
        adapter_id="hermes.oneshot-adapter",
        adapter_version="v2026.8.19",
        source_revision=HERMES_COMMIT,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            tool_events=True,
            timeout=True,
            cost_reporting=True,
        ),
        declared_tools=tuple(tools),
        egress_transports=("provider-api",),
        workspace_modes=("read-only",),
        cost_model="provider-reported",
        provenance=ContractProvenance(
            origin="tests.ikarus-tool-scope.runtime",
            source_revision=HERMES_COMMIT,
            created_at=NOW.isoformat(),
            input_digests=(),
        ),
    )


def _runtime_evidence(request, binding, manifest, tmp_path: Path):
    observations = {
        name: RecordedObservation(
            passed=True,
            detail="offline fixture",
            transcript={"check": name, "result": "passed"},
        )
        for name in RUNTIME_CONFORMANCE_CHECKS
    }
    conformance = assemble_recorded_conformance(
        manifest,
        observations=observations,
        artifact_root=tmp_path / "runtime-evidence",
        receipt_id="ikarus-tool-scope-runtime",
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    return bind_oneshot_runtime_evidence(
        request,
        binding,
        manifest,
        conformance,
        now=NOW + timedelta(seconds=2),
    )


def _policy(request, *, tools=("read-file", "terminal", "web-search"), verdict="allow"):
    effect_scope = EffectScope()
    if verdict == "allow" and tools:
        effect_scope = EffectScope(
            read_only=True,
            tools=tuple(tools),
            max_cost_microusd=0,
            timeout_s=30,
            kill_switch_ref="tests.kill-switch",
        )
    return PolicyDecision(
        decision_id="ikarus-tool-policy",
        subject_id=request.purpose,
        subject_sha256=request.digest,
        policy_version="test/1",
        policy_sha256=POLICY_SHA,
        verdict=verdict,
        reasons=("explicit test policy",),
        effect_scope=effect_scope,
        provenance=ContractProvenance(
            origin="tests.ikarus-tool-scope.policy",
            source_revision=HERMES_COMMIT,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
        ),
    )


def _subjects(tmp_path: Path):
    binding = _binding()
    request = _request(binding)
    manifest = _manifest()
    evidence = _runtime_evidence(request, binding, manifest, tmp_path)
    policy = _policy(request)
    return request, manifest, evidence, policy


def test_explicit_enable_disable_is_exactly_digest_bound(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    projection = project_oneshot_tool_scope(
        request,
        evidence,
        manifest,
        policy,
        requested_tools=("web-search", "read-file"),
        disabled_tools=("web-search",),
    )

    assert projection.requested_tools == ("read-file", "web-search")
    assert projection.disabled_tools == ("web-search",)
    assert projection.enabled_tools == ("read-file",)
    assert projection.request_sha256 == request.digest
    assert projection.runtime_evidence_sha256 == evidence.digest
    assert projection.runtime_manifest_sha256 == manifest.digest
    assert projection.policy_decision_sha256 == policy.digest
    assert projection.digest == project_oneshot_tool_scope(
        request,
        evidence,
        manifest,
        policy,
        requested_tools=("read-file", "web-search"),
        disabled_tools=("web-search",),
    ).digest


def test_empty_request_never_inherits_ambient_runtime_or_policy_tools(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    projection = project_oneshot_tool_scope(request, evidence, manifest, policy)

    assert manifest.declared_tools
    assert policy.effect_scope.tools
    assert request.subject()["tool_scope"] == []
    assert projection.requested_tools == ()
    assert projection.enabled_tools == ()


def test_runtime_undeclared_tool_refuses(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    with pytest.raises(IkarusToolScopeRefused, match="not declared"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("database-write",),
        )


def test_policy_ungranted_tool_refuses(tmp_path):
    binding = _binding()
    request = _request(binding)
    manifest = _manifest()
    evidence = _runtime_evidence(request, binding, manifest, tmp_path)
    policy = _policy(request, tools=("read-file",))

    with pytest.raises(IkarusToolScopeRefused, match="not granted"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("terminal",),
        )


def test_all_tool_wildcard_semantics_are_refused(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    with pytest.raises(IkarusToolScopeRefused, match="wildcard/all-tool"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("all",),
        )


def test_disable_can_only_narrow_explicit_request(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    with pytest.raises(IkarusToolScopeRefused, match="subset"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("read-file",),
            disabled_tools=("terminal",),
        )


def test_deny_policy_never_becomes_tool_authority(tmp_path):
    binding = _binding()
    request = _request(binding)
    manifest = _manifest()
    evidence = _runtime_evidence(request, binding, manifest, tmp_path)
    policy = _policy(request, tools=(), verdict="deny")

    with pytest.raises(IkarusToolScopeRefused, match="allow PolicyDecision"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("read-file",),
        )


def test_policy_subject_substitution_refuses(tmp_path):
    request, manifest, evidence, _policy_for_request = _subjects(tmp_path)
    foreign_request = replace(request, user_input="Foreign request subject")
    foreign_policy = _policy(foreign_request)
    with pytest.raises(IkarusToolScopeRefused, match="different request"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            foreign_policy,
            requested_tools=("read-file",),
        )


def test_runtime_evidence_substitution_refuses(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    foreign = replace(evidence, runtime_manifest_sha256="3" * 64)
    with pytest.raises(IkarusToolScopeRefused, match="different manifest"):
        project_oneshot_tool_scope(
            request,
            foreign,
            manifest,
            policy,
            requested_tools=("read-file",),
        )


def test_duplicate_tool_request_refuses(tmp_path):
    request, manifest, evidence, policy = _subjects(tmp_path)
    with pytest.raises(IkarusToolScopeRefused, match="duplicates"):
        project_oneshot_tool_scope(
            request,
            evidence,
            manifest,
            policy,
            requested_tools=("read-file", "read-file"),
        )


def test_module_is_projection_only_and_has_no_effect_or_plugin_discovery_authority():
    path = Path(__file__).resolve().parents[1] / "daedalus" / "orchestration" / "ikarus" / "tool_scope.py"
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
    assert not ({"open", "exec", "eval", "run_runtime_provider", "begin_effect"} & call_names)
