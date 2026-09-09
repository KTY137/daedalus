"""Authenticate sealed Claude authority against the live TaskAttempt runner owner.

This seam exists for the productive ``MissionSupervisor -> TaskAttempt`` path.
The runner handoff already proves which Mission/WorkItem/Attempt and isolated
workspace own the effect.  Before any provider code is reachable, this module
re-proves that the already-issued one-shot, Effect Lease, runtime, workspace,
invocation ABI and executable evidence all name that same owner.

Nothing here issues authority, starts an Effect, calls a provider, reconstructs
an ``AttemptContract`` or creates another scheduler/lifecycle.  The returned
receipt is the existing provider executable-binding evidence produced by the
canonical runtime binder.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .ikarus_claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import (
    ENTRYPOINT_ID as CLAUDE_ENTRYPOINT_ID,
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from .runtimes.provider_executable_object_registry import ProviderExecutableObjectRegistry
from .runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from .runtimes.provider_invocation_abi import ProviderInvocationABIContract
from .runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from .runtimes.provider_invocation_payload import ProviderInvocationPayload
from .runtimes.provider_observation import ProviderObservationBindingLedger
from .runtimes.provider_runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)
from .runtimes.provider_runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingError,
    bind_provider_runtime_invocation,
)
from .schemas import MissionContract


class IkarusClaudeTaskAttemptAuthorityRefused(RuntimeError):
    """Sealed Claude authority does not belong to the live TaskAttempt owner."""


def _exact(value: Any, exact_type: type[Any], label: str) -> None:
    if type(value) is not exact_type:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            f"{label} must be exact {exact_type.__name__}"
        )


def _snapshot_mission(mission: MissionContract) -> MissionContract:
    _exact(mission, MissionContract, "mission")
    try:
        supplied_digest = mission.digest
        snapshot = MissionContract.from_dict(mission.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "MissionContract could not be snapshotted for provider authority binding"
        ) from exc
    if snapshot.digest != supplied_digest:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "MissionContract changed during provider authority binding"
        )
    return snapshot


def _resolved_directory(value: str | Path, label: str) -> Path:
    try:
        resolved = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            f"{label} could not be resolved"
        ) from exc
    if not resolved.is_dir():
        raise IkarusClaudeTaskAttemptAuthorityRefused(f"{label} is not a directory")
    return resolved


def _require_subset(values: tuple[str, ...], allowed: tuple[str, ...], label: str) -> None:
    escaped = sorted(set(values) - set(allowed))
    if escaped:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            f"{label} exceeds TaskAttempt owner scope: " + ", ".join(escaped)
        )


def bind_task_attempt_claude_provider_authorities(
    handoff: ClaudeTaskAttemptRunnerHandoff,
    mission: MissionContract,
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
    effect_request: EffectLeaseRequest,
    execution: EffectExecutionRequest,
    *,
    runtime_authorization: RuntimeBoundEffectAuthorization,
    workspace_grant: ClaudeWorkspaceGrant,
    invocation_authority: ProviderInvocationObservationAuthority,
    invocation_payload: ProviderInvocationPayload,
    invocation_abi: ProviderInvocationABIContract,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    at: datetime,
) -> ProviderRuntimeExecutableBindingReceipt:
    """Re-authenticate every Claude authority against one live TaskAttempt owner.

    The provider runtime binder remains the sole verifier for signed ABI,
    executable-object, pre-admission and observation authority.  This function
    contributes only the missing outer-owner proof: those subjects must first
    agree with the authenticated TaskAttempt runner handoff and its exact
    isolated worktree.
    """

    for value, exact_type, label in (
        (handoff, ClaudeTaskAttemptRunnerHandoff, "handoff"),
        (request, OneShotRequest, "request"),
        (runtime_evidence, OneShotRuntimeEvidenceBinding, "runtime_evidence"),
        (tool_scope, IkarusToolScopeProjection, "tool_scope"),
        (effect_request, EffectLeaseRequest, "effect_request"),
        (execution, EffectExecutionRequest, "execution"),
        (runtime_authorization, RuntimeBoundEffectAuthorization, "runtime_authorization"),
        (workspace_grant, ClaudeWorkspaceGrant, "workspace_grant"),
    ):
        _exact(value, exact_type, label)
    if type(at) is not datetime or at.tzinfo is None or at.utcoffset() is None:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "at must be an exact timezone-aware datetime"
        )

    snapshot = _snapshot_mission(mission)
    if handoff.mission_id != snapshot.mission_id:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "runner handoff belongs to a different Mission"
        )
    if handoff.work_item_id not in snapshot.work_item_ids:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "runner handoff names a foreign WorkItem"
        )
    if handoff.source_revision != snapshot.source_revision:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "runner handoff belongs to a different source revision"
        )
    if request.runtime_id != CLAUDE_RUNTIME_ID or runtime_evidence.runtime_id != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "live TaskAttempt provider binding requires claude_code_cli"
        )

    comparisons = {
        "runtime evidence request": (runtime_evidence.request_sha256, request.digest),
        "runtime evidence role": (runtime_evidence.role, request.role),
        "runtime binding": (runtime_evidence.runtime_binding_sha256, request.runtime_binding_sha256),
        "runtime source revision": (runtime_evidence.source_revision, handoff.source_revision),
        "tool request": (tool_scope.request_sha256, request.digest),
        "tool runtime evidence": (tool_scope.runtime_evidence_sha256, runtime_evidence.digest),
        "tool runtime manifest": (tool_scope.runtime_manifest_sha256, runtime_evidence.runtime_manifest_sha256),
        "effect mission": (effect_request.mission_id, handoff.mission_id),
        "effect attempt": (effect_request.attempt_id, handoff.attempt_id),
        "effect entrypoint": (effect_request.entrypoint_id, CLAUDE_ENTRYPOINT_ID),
        "effect runtime manifest": (effect_request.runtime_manifest_sha256, runtime_evidence.runtime_manifest_sha256),
        "effect runtime conformance": (effect_request.runtime_conformance_sha256, runtime_evidence.runtime_conformance_sha256),
        "effect source revision": (effect_request.provenance.source_revision, handoff.source_revision),
        "runtime authorization request": (runtime_authorization.request, effect_request),
        "workspace attempt": (workspace_grant.attempt_id, handoff.attempt_id),
        "workspace source revision": (workspace_grant.source_revision, handoff.source_revision),
        "workspace lease request": (workspace_grant.request_sha256, effect_request.digest),
        "workspace execution": (workspace_grant.execution_sha256, execution.digest),
    }
    mismatches = sorted(
        label for label, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude authority differs from the live TaskAttempt owner: "
            + ", ".join(mismatches)
        )

    if tuple(effect_request.effect_scope.tools) != tuple(tool_scope.enabled_tools):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Effect Lease tool scope differs from the canonical Ikarus tool projection"
        )
    _require_subset(
        tuple(effect_request.effect_scope.writable_paths),
        handoff.target_paths,
        "Effect Lease writable scope",
    )
    _require_subset(
        tuple(execution.writable_paths),
        handoff.target_paths,
        "execution writable scope",
    )
    _require_subset(tuple(execution.tools), tuple(tool_scope.enabled_tools), "execution tool scope")
    _require_subset(
        tuple(execution.requested_effects),
        tuple(effect_request.requested_effects),
        "execution effect scope",
    )

    owner_workspace = _resolved_directory(handoff.worktree, "TaskAttempt runner workspace")
    granted_workspace = _resolved_directory(workspace_grant.worktree, "Claude workspace grant")
    if owner_workspace != granted_workspace:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude workspace grant does not name the authenticated TaskAttempt workspace"
        )

    try:
        receipt = bind_provider_runtime_invocation(
            effect_request.entrypoint_id,
            authorization=runtime_authorization,
            execution=execution,
            invocation_authority=invocation_authority,
            invocation_payload=invocation_payload,
            invocation_abi=invocation_abi,
            observation_binding_ledger=observation_binding_ledger,
            executable_registry=executable_registry,
            pre_admission=pre_admission,
            at=at,
        )
    except ProviderRuntimeInvocationBindingError as exc:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude invocation/executable authority did not authenticate"
        ) from exc
    if type(receipt) is not ProviderRuntimeExecutableBindingReceipt:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "provider runtime binder returned a non-exact executable receipt"
        )
    return receipt


__all__ = [
    "IkarusClaudeTaskAttemptAuthorityRefused",
    "bind_task_attempt_claude_provider_authorities",
]
