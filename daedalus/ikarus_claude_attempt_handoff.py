"""Bind a persisted, prepared Attempt to the mission-bound Claude handoff.

This module is deliberately a narrow producer-side guard.  The existing
``execute_mission_bound_claude_invocation`` function remains the authority and
provider composition seam; this wrapper adds the missing lifecycle invariant
that a fresh Attempt start must already have been committed by the canonical
Attempt ledger and that Claude must receive the exact isolated workspace the
Attempt coordinator prepared before a provider effect is reachable.

No authority is issued here and no state is reconstructed from chat, queue, or
status JSON.  A replayed/completed/pending Attempt, a stale prepared handle, or
a recombined workspace therefore cannot trigger a new Claude provider run
through this entrypoint.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .ikarus_claude_composition import execute_mission_bound_claude_invocation
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.attempts import (
    AttemptBeginResult,
    AttemptLedger,
    AttemptStartRecord,
    PreparedAttempt,
)
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
    """A durable, prepared Attempt does not authorize one fresh Claude dispatch."""


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


def require_live_pending_attempt(
    attempt_ledger: AttemptLedger,
    start: AttemptStartRecord,
) -> AttemptStartRecord:
    """Re-read canonical lifecycle state immediately before provider dispatch.

    ``PreparedAttempt`` is an immutable handoff value.  A caller can retain it
    after another path has already completed the Attempt, so trusting only its
    embedded ``AttemptBeginResult`` would turn a stale snapshot into execution
    authority.  The canonical Event-Store is therefore consulted again at the
    last producer boundary.  The exact persisted start must still be pending.
    """

    if not isinstance(attempt_ledger, AttemptLedger):
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires the canonical AttemptLedger"
        )
    if type(start) is not AttemptStartRecord:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptStartRecord"
        )
    try:
        matching = tuple(
            candidate
            for candidate in attempt_ledger.pending()
            if candidate.attempt_id == start.attempt_id
        )
    except Exception as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "canonical Attempt lifecycle could not be re-read before Claude dispatch"
        ) from exc
    if len(matching) != 1:
        raise IkarusClaudeAttemptHandoffRefused(
            "prepared Attempt is no longer the live pending Attempt"
        )
    candidate = matching[0]
    try:
        same_start = candidate is start or candidate == start
    except (AttributeError, TypeError, ValueError):
        same_start = False
    if not same_start:
        raise IkarusClaudeAttemptHandoffRefused(
            "live pending Attempt start differs from the prepared Attempt start"
        )
    return start


def require_fresh_prepared_attempt_workspace(
    prepared: PreparedAttempt,
    attempt: AttemptContract,
    workspace_grant: ClaudeWorkspaceGrant,
) -> AttemptStartRecord:
    """Bind the durable start to the exact coordinator-prepared Claude workspace.

    ``PreparedAttempt`` is the kernel handoff produced only after the start was
    persisted and the source tree materialized.  Claude's structural workspace
    grant must name that same resolved directory; a separately supplied path is
    not allowed to ride on an otherwise valid Attempt start.
    """

    if type(prepared) is not PreparedAttempt:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact PreparedAttempt"
        )
    if type(workspace_grant) is not ClaudeWorkspaceGrant:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact ClaudeWorkspaceGrant"
        )

    start = require_fresh_persisted_attempt_start(prepared.begin, attempt)
    if prepared.workspace is None:
        raise IkarusClaudeAttemptHandoffRefused(
            "fresh Claude handoff requires the prepared Attempt workspace"
        )
    if workspace_grant.attempt_id != attempt.attempt_id:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant belongs to a different Attempt"
        )
    if workspace_grant.source_revision != attempt.base_revision:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant belongs to a different source revision"
        )

    try:
        prepared_workspace = Path(prepared.workspace).expanduser().resolve(strict=True)
        granted_workspace = Path(workspace_grant.worktree).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "prepared Claude workspace could not be resolved"
        ) from exc
    if not prepared_workspace.is_dir() or prepared_workspace != granted_workspace:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant does not bind the prepared Attempt workspace"
        )
    return start


def execute_started_mission_bound_claude_invocation(
    prepared: PreparedAttempt,
    mission: MissionContract,
    attempt: AttemptContract,
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
    effect_request: EffectLeaseRequest,
    execution: EffectExecutionRequest,
    *,
    attempt_ledger: AttemptLedger,
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
    """Dispatch Claude only from a live, durable, prepared canonical Attempt.

    Lifecycle/workspace authentication and a live Event-Store re-read happen
    before the existing atomic authority composition seam is entered.  The
    downstream function still re-authenticates Mission, WorkItem, Attempt,
    runtime, Effect, workspace, ABI, executable and observation authority; this
    wrapper contributes only durable lifecycle facts and exact prepared-workspace
    identity.
    """

    start = require_fresh_prepared_attempt_workspace(
        prepared,
        attempt,
        workspace_grant,
    )
    require_live_pending_attempt(attempt_ledger, start)
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
    "require_fresh_prepared_attempt_workspace",
    "require_live_pending_attempt",
]
