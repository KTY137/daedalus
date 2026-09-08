"""Mission/Attempt -> sealed Claude invocation composition regressions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.ikarus_claude_composition as composition
from daedalus.claude_bridge import ClaudeSealedInvocationBundle
from daedalus.ikarus_effect_bridge import build_oneshot_effect_execution_request
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.providers.claude_cli import ClaudeWorkspaceGrant
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


ROOT = Path(__file__).resolve().parents[1]
EFFECT_BRIDGE_FIXTURE = ROOT / "tests/test_ikarus_effect_bridge.py"


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


def _subjects(tmp_path: Path):
    work_item_id = "wi-000-ikarus-claude"
    attempt_id = "attempt-ikarus-claude-1"
    request, evidence, tools, effect_request = fixture._effect_request(
        tmp_path,
        attempt_id=attempt_id,
    )
    execution = build_oneshot_effect_execution_request(
        request,
        evidence,
        tools,
        effect_request,
        execution_id="ikarus-claude-execution-1",
        idempotency_key="ikarus-claude-execution-key-1",
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
    assert entrypoint_id == effect_request.entrypoint_id
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
