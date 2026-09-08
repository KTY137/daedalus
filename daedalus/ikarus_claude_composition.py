"""Compose one mission-bound Ikarus call into the sealed Claude runtime seam.

The function in this module is deliberately a composition root, not an authority
issuer.  Every capability-bearing member must already exist and remain owned by
its canonical kernel/runtime ledger.  Ikarus contributes only the proof that the
one-shot request, WorkItem/Attempt and effect projection name the same execution
before the existing provider invocation binder authenticates the sealed runtime
subject.
"""
from __future__ import annotations

from datetime import datetime

from .claude_bridge import ClaudeSealedInvocationBundle
from .ikarus_effect_bridge import (
    IkarusEffectBridgeRefused,
    validate_oneshot_mission_attempt,
)
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import ClaudeWorkspaceGrant
from .runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from .runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from .runtimes.provider_invocation_abi import ProviderInvocationABIContract
from .runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from .runtimes.provider_invocation_payload import ProviderInvocationPayload
from .runtimes.provider_observation import ProviderObservationBindingLedger
from .runtimes.provider_runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingError,
    bind_provider_runtime_invocation,
)
from .schemas import AttemptContract, MissionContract


class IkarusClaudeCompositionRefused(RuntimeError):
    """The supplied mission/attempt/runtime subjects cannot form one Claude call."""


def _require_workspace_binding(
    attempt: AttemptContract,
    effect_request: EffectLeaseRequest,
    execution: EffectExecutionRequest,
    runtime_authorization: RuntimeBoundEffectAuthorization,
    workspace_grant: ClaudeWorkspaceGrant,
) -> None:
    if type(runtime_authorization) is not RuntimeBoundEffectAuthorization:
        raise IkarusClaudeCompositionRefused(
            "runtime_authorization must be an exact RuntimeBoundEffectAuthorization"
        )
    if type(workspace_grant) is not ClaudeWorkspaceGrant:
        raise IkarusClaudeCompositionRefused(
            "workspace_grant must be an exact ClaudeWorkspaceGrant"
        )
    if runtime_authorization.request != effect_request:
        raise IkarusClaudeCompositionRefused(
            "runtime authorization belongs to a different effect lease request"
        )

    comparisons = {
        "workspace attempt": (workspace_grant.attempt_id, attempt.attempt_id),
        "workspace source revision": (
            workspace_grant.source_revision,
            attempt.base_revision,
        ),
        "workspace lease request": (
            workspace_grant.request_sha256,
            effect_request.digest,
        ),
        "workspace execution": (
            workspace_grant.execution_sha256,
            execution.digest,
        ),
    }
    mismatches = tuple(
        sorted(
            label
            for label, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise IkarusClaudeCompositionRefused(
            "Claude workspace grant does not name the canonical mission attempt: "
            + ", ".join(mismatches)
        )


def compose_oneshot_claude_sealed_invocation(
    mission: MissionContract,
    attempt: AttemptContract,
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
) -> ClaudeSealedInvocationBundle:
    """Assemble already-issued authorities only after all subjects re-authenticate.

    No lease, workspace capability, provider authority or receipt is minted here,
    and no Effect or provider code is started.  The canonical Ikarus bridge first
    proves Mission -> WorkItem -> Attempt -> effect identity.  The existing
    provider-runtime binder then proves the signed ABI/executable conjunction.
    Only that conjunction is representable as the public Claude sealed bundle.
    """

    try:
        validate_oneshot_mission_attempt(
            mission,
            attempt,
            request,
            runtime_evidence,
            tool_scope,
            effect_request,
            execution,
        )
    except IkarusEffectBridgeRefused as exc:
        raise IkarusClaudeCompositionRefused(
            "Ikarus mission/attempt effect binding refused Claude composition"
        ) from exc

    _require_workspace_binding(
        attempt,
        effect_request,
        execution,
        runtime_authorization,
        workspace_grant,
    )

    try:
        bind_provider_runtime_invocation(
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
        raise IkarusClaudeCompositionRefused(
            "sealed provider invocation does not authenticate the mission attempt"
        ) from exc

    try:
        return ClaudeSealedInvocationBundle(
            runtime_authorization=runtime_authorization,
            effect_execution=execution,
            workspace_grant=workspace_grant,
            invocation_authority=invocation_authority,
            invocation_payload=invocation_payload,
            invocation_abi=invocation_abi,
            observation_binding_ledger=observation_binding_ledger,
            executable_registry=executable_registry,
            pre_admission=pre_admission,
        )
    except (TypeError, ValueError) as exc:
        raise IkarusClaudeCompositionRefused(
            "Claude sealed bundle rejected substituted authority members"
        ) from exc


__all__ = [
    "IkarusClaudeCompositionRefused",
    "compose_oneshot_claude_sealed_invocation",
]
