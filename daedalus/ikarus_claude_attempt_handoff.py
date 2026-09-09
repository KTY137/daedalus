"""Bind a persisted Attempt start to the mission-bound Claude handoff.

This module is deliberately a narrow producer-side guard.  The existing
``execute_mission_bound_claude_invocation`` function remains the authority and
provider composition seam; this wrapper adds the missing lifecycle invariant
that a fresh Attempt start must already have been committed by the canonical
Attempt ledger before a provider effect is reachable.

No authority is issued here and no state is reconstructed from chat, queue, or
status JSON.  A replayed/completed/pending Attempt therefore cannot trigger a
new Claude provider run through this entrypoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .ikarus_claude_composition import execute_mission_bound_claude_invocation
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.attempts import AttemptBeginResult, AttemptStartRecord
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import ClaudeWorkspaceGrant
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
from .schemas import AttemptContract, MissionContract


class IkarusClaudeAttemptHandoffRefused(RuntimeError):
    """A durable Attempt start does not authorize one fresh Claude dispatch."""


def require_fresh_persisted_attempt_start(
    begin: AttemptBeginResult,
    attempt: AttemptContract,
) -> AttemptStartRecord:
    """Authenticate the canonical Attempt-ledger start before any provider call.

    ``AttemptLedger.begin`` returns ``execute=True`` only for the transaction
    that durably won the single-start race.  Existing starts return
    ``execute=False`` (with a terminal completion for replay, or without one for
    reconciliation).  Only the fresh winner may cross this producer boundary.
    """

    if type(begin) is not AttemptBeginResult:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptBeginResult"
        )
    if type(attempt) is not AttemptContract:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptContract"
        )
    if begin.execute is not True or begin.completion is not None:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires the fresh durable Attempt-start winner"
        )
    start = begin.start
    if type(start) is not AttemptStartRecord:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptStartRecord"
        )

    mismatches = tuple(
        label
        for label, actual, expected in (
            ("attempt id", start.attempt_id, attempt.attempt_id),
            ("attempt digest", start.attempt_sha256, attempt.digest),
            ("source revision", start.source_revision, attempt.base_revision),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeAttemptHandoffRefused(
            "persisted Attempt start does not bind the Claude Attempt authority: "
            + ", ".join(mismatches)
        )
    return start


def execute_started_mission_bound_claude_invocation(
    begin: AttemptBeginResult,
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
) -> dict[str, Any]:
    """Dispatch Claude only after the canonical Attempt start is durable.

    The check happens before the existing atomic authority composition seam is
    entered.  The downstream function still re-authenticates Mission, WorkItem,
    Attempt, runtime, Effect, workspace, ABI, executable and observation
    authority; this wrapper contributes only the durable lifecycle fact.
    """

    require_fresh_persisted_attempt_start(begin, attempt)
    return execute_mission_bound_claude_invocation(
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        runtime_authorization=runtime_authorization,
        workspace_grant=workspace_grant,
        invocation_authority=invocation_authority,
        invocation_payload=invocation_payload,
        invocation_abi=invocation_abi,
        observation_binding_ledger=observation_binding_ledger,
        executable_registry=executable_registry,
        pre_admission=pre_admission,
        at=at,
    )


__all__ = [
    "IkarusClaudeAttemptHandoffRefused",
    "execute_started_mission_bound_claude_invocation",
    "require_fresh_persisted_attempt_start",
]
