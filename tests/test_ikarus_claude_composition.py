"""Mission/Attempt -> sealed Claude invocation composition regressions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.ikarus_claude_composition as composition
from daedalus.claude_bridge import ClaudeSealedInvocationBundle
from daedalus.ikarus_effect_bridge import (
    build_oneshot_effect_execution_request,
    build_oneshot_effect_lease_request,
)
from daedalus.ikarus_oneshot import OneShotRequest
from daedalus.ikarus_runtime_role import (
    SOURCE_ONLY_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
)
from daedalus.ikarus_tool_scope import project_oneshot_tool_scope
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.providers.claude_cli import (
    ENTRYPOINT_ID as CLAUDE_ENTRYPOINT_ID,
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
    claude_idempotency_key,
    claude_invocation_sha256,
)
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation_abi import ProviderInvocationABIContract
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider_observation import ProviderObservationBindingLedger
from daedalus.runtimes.provider_runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingMismatch,
)
from daedalus.schemas import (
    ContractProvenance,
    ResourceBudget,
    RuntimeCapabilities,
    RuntimeManifest,
)
from daedalus.spine.effect_boundary import Effect


ROOT = Path(__file__).resolve().parents[1]
EFFECT_BRIDGE_FIXTURE = ROOT / "tests/test_ikarus_effect_bridge.py"
CLAUDE_SOURCE_REVISION = "c" * 40
OBJECTIVE = "Improve the mission-bound Ikarus Claude runtime seam."
PATHS = ["daedalus/ikarus_claude_composition.py"]
MODEL = "sonnet"
TIMEOUT_S = 30
AGENT = {
    "name": "generalist-dev",
    "call_name": "Generalist Dev",
    "model_tier": MODEL,
}


def _load_effect_bridge_fixture():
    name = "daedalus_test_ikarus_claude_composition_effect_fixture"
    spec = importlib.util.spec_from_file_location(name, EFFECT_BRIDGE_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_effect_bridge_fixture()


def _bare(exact_type):
    return object.__new__(exact_type)


def _claude_runtime_subjects(tmp_path: Path):
    binding = RuntimeRoleBinding(
        role="assistant",
        runtime_id=CLAUDE_RUNTIME_ID,
        adapter_id="claude.oneshot-adapter",
        adapter_version="test-1",
        source_revision=CLAUDE_SOURCE_REVISION,
        origin="tests://ikarus-claude-composition",
        execution_mode=SOURCE_ONLY_EXECUTION_MODE,
        refusal_reason="source-only until the sealed mission runtime admits execution",
    )
    snapshot = RuntimeRoleRegistry((binding,)).snapshot("assistant", CLAUDE_RUNTIME_ID)
    assert snapshot is not None
    request = OneShotRequest.from_runtime_binding(
        snapshot,
        purpose="mission-bound-claude",
        instructions="Use only the sealed mission runtime authority.",
        user_input="Execute one bounded Claude work item.",
        budget=ResourceBudget(
            max_tokens=1024,
            max_cost_microusd=100_000,
            max_wall_time_s=60,
            max_attempts=1,
        ),
    )
    manifest = RuntimeManifest(
        runtime_id=CLAUDE_RUNTIME_ID,
        runtime_version="test-1",
        adapter_id="claude.oneshot-adapter",
        adapter_version="test-1",
        source_revision=CLAUDE_SOURCE_REVISION,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            tool_events=True,
            timeout=True,
            cost_reporting=True,
        ),
        declared_tools=("claude",),
        egress_transports=("provider-api",),
        workspace_modes=("isolated-worktree",),
        cost_model="provider-reported",
        provenance=ContractProvenance(
            origin="tests.ikarus-claude-composition.runtime",
            source_revision=CLAUDE_SOURCE_REVISION,
            created_at=fixture.fixture.NOW.isoformat(),
            input_digests=(),
        ),
    )
    evidence = fixture.fixture._runtime_evidence(
        request,
        snapshot,
        manifest,
        tmp_path,
    )
    policy = fixture.fixture._policy(request, tools=("claude",))
    tools = project_oneshot_tool_scope(
        request,
        evidence,
        manifest,
        policy,
        requested_tools=("claude",),
    )
    return request, evidence, tools


def _subjects(tmp_path: Path):
    work_item_id = "wi-000-ikarus-claude"
    attempt_id = "attempt-ikarus-claude-1"
    request, evidence, tools = _claude_runtime_subjects(tmp_path)
    effect_request = build_oneshot_effect_lease_request(
        request,
        evidence,
        tools,
        request_id="ikarus-claude-effect-request-1",
        mission_id="mission-ikarus-claude-1",
        attempt_id=attempt_id,
        entrypoint_id=CLAUDE_ENTRYPOINT_ID,
        idempotency_namespace="mission-ikarus-claude-attempt-1",
        kill_switch_ref="mission-ikarus-claude-kill",
        kill_switch_generation=1,
        requested_effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        created_at=fixture.fixture.NOW,
        writable_paths=(".",),
        egress_endpoints=("https://api.anthropic.com",),
        timeout_s=TIMEOUT_S,
    )
    invocation_sha256 = claude_invocation_sha256(
        objective=OBJECTIVE,
        worktree=str(tmp_path),
        paths=PATHS,
        agent=AGENT,
        model=MODEL,
        timeout_s=TIMEOUT_S,
        attempt_id=attempt_id,
        source_revision=evidence.source_revision,
        request_sha256=effect_request.digest,
    )
    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="ikarus-claude-execution-1",
        idempotency_key=claude_idempotency_key(invocation_sha256),
        max_cost_microusd=25_000,
    )
    mission = fixture._mission(
        evidence,
        tools,
        mission_id=effect_request.mission_id,
        work_item_id=work_item_id,
    )
    attempt = fixture._attempt(
        evidence,
        tools,
        mission_id=mission.mission_id,
        work_item_id=work_item_id,
        attempt_id=attempt_id,
        writable_paths=(".",),
    )
    authorization = _bare(RuntimeBoundEffectAuthorization)
    object.__setattr__(authorization, "request", effect_request)
    workspace = ClaudeWorkspaceGrant(
        attempt_id=attempt.attempt_id,
        source_revision=attempt.base_revision,
        request_sha256=effect_request.digest,
        execution_sha256=execution.digest,
        worktree=str(tmp_path),
    )
    sealed_members = {
        "runtime_authorization": authorization,
        "workspace_grant": workspace,
        "invocation_authority": _bare(ProviderInvocationObservationAuthority),
        "invocation_payload": _bare(ProviderInvocationPayload),
        "invocation_abi": _bare(ProviderInvocationABIContract),
        "observation_binding_ledger": _bare(ProviderObservationBindingLedger),
        "executable_registry": _bare(ProviderExecutableObjectRegistry),
        "pre_admission": _bare(ProviderExecutablePreAdmissionReceipt),
    }
    return (
        mission,
        attempt,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        sealed_members,
    )


def _provider_body(subjects, tmp_path: Path):
    _, attempt, _, _, _, effect_request, _, _ = subjects
    invocation_sha256 = claude_invocation_sha256(
        objective=OBJECTIVE,
        worktree=str(tmp_path),
        paths=PATHS,
        agent=AGENT,
        model=MODEL,
        timeout_s=TIMEOUT_S,
        attempt_id=attempt.attempt_id,
        source_revision=attempt.base_revision,
        request_sha256=effect_request.digest,
    )
    return {
        "objective": OBJECTIVE,
        "worktree": str(tmp_path),
        "paths": list(PATHS),
        "agent": dict(AGENT),
        "model": MODEL,
        "timeout_s": TIMEOUT_S,
        "attempt_id": attempt.attempt_id,
        "source_revision": attempt.base_revision,
        "request_sha256": effect_request.digest,
        "invocation_sha256": invocation_sha256,
    }


def _compose(subjects, **overrides):
    mission, attempt, request, evidence, tools, effect_request, execution, members = subjects
    kwargs = {**members, "at": fixture.fixture.NOW}
    kwargs.update(overrides)
    return composition.compose_oneshot_claude_sealed_invocation(
        mission,
        attempt,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        **kwargs,
    )


def _compose_bound(subjects, **overrides):
    mission, attempt, request, evidence, tools, effect_request, execution, members = subjects
    kwargs = {**members, "at": fixture.fixture.NOW}
    kwargs.update(overrides)
    return composition.compose_mission_bound_claude_invocation(
        mission,
        attempt,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        **kwargs,
    )


def test_composition_reauthenticates_existing_provider_seam_before_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    effect_request = subjects[5]
    execution = subjects[6]
    members = subjects[7]
    calls = []

    def fake_bind(entrypoint_id, **kwargs):
        calls.append((entrypoint_id, kwargs))
        return object()

    monkeypatch.setattr(composition, "bind_provider_runtime_invocation", fake_bind)

    bundle = _compose(subjects)

    assert type(bundle) is ClaudeSealedInvocationBundle
    assert bundle.runtime_authorization is members["runtime_authorization"]
    assert bundle.effect_execution is execution
    assert bundle.workspace_grant is members["workspace_grant"]
    assert len(calls) == 1
    entrypoint_id, call = calls[0]
    assert entrypoint_id == effect_request.entrypoint_id == CLAUDE_ENTRYPOINT_ID
    assert call["authorization"] is members["runtime_authorization"]
    assert call["execution"] is execution
    assert call["invocation_authority"] is members["invocation_authority"]
    assert call["invocation_payload"] is members["invocation_payload"]
    assert call["invocation_abi"] is members["invocation_abi"]
    assert call["observation_binding_ledger"] is members["observation_binding_ledger"]
    assert call["executable_registry"] is members["executable_registry"]
    assert call["pre_admission"] is members["pre_admission"]
    assert call["at"] == fixture.fixture.NOW


def test_composition_refuses_foreign_workspace_attempt_before_provider_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    members = subjects[7]
    workspace = members["workspace_grant"]
    foreign = ClaudeWorkspaceGrant(
        attempt_id="attempt-foreign",
        source_revision=workspace.source_revision,
        request_sha256=workspace.request_sha256,
        execution_sha256=workspace.execution_sha256,
        worktree=workspace.worktree,
    )
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider binding must not run")

    monkeypatch.setattr(composition, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="workspace attempt",
    ):
        _compose(subjects, workspace_grant=foreign)
    assert called is False


def test_composition_refuses_runtime_authorization_for_other_effect_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    foreign_authorization = _bare(RuntimeBoundEffectAuthorization)
    _, _, _, foreign_request = fixture._effect_request(
        tmp_path / "foreign",
        request_id="ikarus-effect-request-foreign",
        attempt_id=subjects[1].attempt_id,
    )
    object.__setattr__(foreign_authorization, "request", foreign_request)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider binding must not run")

    monkeypatch.setattr(composition, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="different effect lease request",
    ):
        _compose(subjects, runtime_authorization=foreign_authorization)
    assert called is False


def test_composition_translates_provider_subject_mismatch_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)

    def refuse(*args, **kwargs):
        raise ProviderRuntimeInvocationBindingMismatch("foreign provider subject")

    monkeypatch.setattr(composition, "bind_provider_runtime_invocation", refuse)

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="does not authenticate the mission attempt",
    ):
        _compose(subjects)


def test_composition_refuses_non_claude_oneshot_before_provider_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, evidence, tools, effect_request = fixture._effect_request(tmp_path)
    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="foreign-runtime-execution",
        idempotency_key="foreign-runtime-key",
        max_cost_microusd=25_000,
    )
    mission = fixture._mission(
        evidence,
        tools,
        mission_id=effect_request.mission_id,
        work_item_id="wi-foreign-runtime",
    )
    attempt = fixture._attempt(
        evidence,
        tools,
        mission_id=mission.mission_id,
        work_item_id="wi-foreign-runtime",
        attempt_id=effect_request.attempt_id,
    )
    authorization = _bare(RuntimeBoundEffectAuthorization)
    object.__setattr__(authorization, "request", effect_request)
    workspace = ClaudeWorkspaceGrant(
        attempt_id=attempt.attempt_id,
        source_revision=attempt.base_revision,
        request_sha256=effect_request.digest,
        execution_sha256=execution.digest,
        worktree=str(tmp_path),
    )
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider binding must not run for a Hermes one-shot")

    monkeypatch.setattr(composition, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="canonical claude_code_cli runtime binding",
    ):
        composition.compose_oneshot_claude_sealed_invocation(
            mission,
            attempt,
            request,
            evidence,
            tools,
            effect_request,
            execution,
            runtime_authorization=authorization,
            workspace_grant=workspace,
            invocation_authority=_bare(ProviderInvocationObservationAuthority),
            invocation_payload=_bare(ProviderInvocationPayload),
            invocation_abi=_bare(ProviderInvocationABIContract),
            observation_binding_ledger=_bare(ProviderObservationBindingLedger),
            executable_registry=_bare(ProviderExecutableObjectRegistry),
            pre_admission=_bare(ProviderExecutablePreAdmissionReceipt),
            at=fixture.fixture.NOW,
        )
    assert called is False


def test_dispatch_uses_authenticated_payload_and_projects_work_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    monkeypatch.setattr(
        composition,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: object(),
    )
    invocation = _compose_bound(subjects)
    body = _provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    calls = []

    def fake_ask_claude(
        objective,
        repo_root,
        paths,
        model="sonnet",
        timeout_s=300,
        *,
        sealed_bundle=None,
    ):
        calls.append(
            {
                "objective": objective,
                "repo_root": repo_root,
                "paths": paths,
                "model": model,
                "timeout_s": timeout_s,
                "sealed_bundle": sealed_bundle,
            }
        )
        return {
            "provider": "claude_cli",
            "runtime_id": CLAUDE_RUNTIME_ID,
            "attempt_id": subjects[1].attempt_id,
            "phase": "terminal",
            "terminal_receipt_sha256": "f" * 64,
            "report": {"status": "done", "summary": "bounded"},
        }

    monkeypatch.setattr(composition, "ask_claude", fake_ask_claude)

    result = composition.dispatch_mission_bound_claude_invocation(invocation)

    assert len(calls) == 1
    call = calls[0]
    assert call["objective"] == body["objective"]
    assert call["repo_root"] == body["worktree"]
    assert call["paths"] == body["paths"]
    assert call["model"] == body["model"]
    assert call["timeout_s"] == body["timeout_s"]
    assert call["sealed_bundle"] is invocation.sealed_bundle
    assert result["mission_id"] == subjects[0].mission_id
    assert result["work_item_id"] == subjects[1].task_id
    assert result["attempt_id"] == subjects[1].attempt_id
    assert result["runtime_id"] == CLAUDE_RUNTIME_ID
    assert result["phase"] == "terminal"
    assert result["terminal_receipt_sha256"] == "f" * 64


def test_dispatch_refuses_tampered_payload_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    monkeypatch.setattr(
        composition,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: object(),
    )
    invocation = _compose_bound(subjects)
    body = _provider_body(subjects, tmp_path)
    body["attempt_id"] = "attempt-foreign"
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("tampered payload must not reach Claude")

    monkeypatch.setattr(composition, "ask_claude", fail_if_called)

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="authenticated Claude payload does not name the mission attempt: attempt",
    ):
        composition.dispatch_mission_bound_claude_invocation(invocation)
    assert called is False


def test_dispatch_refuses_foreign_provider_identity_before_work_item_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    monkeypatch.setattr(
        composition,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: object(),
    )
    invocation = _compose_bound(subjects)
    body = _provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    monkeypatch.setattr(
        composition,
        "ask_claude",
        lambda *args, **kwargs: {
            "provider": "claude_cli",
            "runtime_id": CLAUDE_RUNTIME_ID,
            "attempt_id": "attempt-foreign",
            "phase": "terminal",
            "terminal_receipt_sha256": "e" * 64,
        },
    )

    with pytest.raises(
        composition.IkarusClaudeCompositionRefused,
        match="does not name the canonical Attempt",
    ):
        composition.dispatch_mission_bound_claude_invocation(invocation)
