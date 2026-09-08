"""Compose one mission-bound Ikarus call into the sealed Claude runtime seam.

The functions in this module form a composition/dispatch boundary, not an
authority issuer. Every capability-bearing member must already exist and remain
owned by its canonical kernel/runtime ledger. Ikarus contributes only the proof
that the one-shot request, WorkItem/Attempt and effect projection name the same
execution before the existing provider invocation binder authenticates the
sealed runtime subject.

The live dispatch helper deliberately consumes the authenticated provider
payload carried by that sealed subject. Objective, worktree, paths, model and
timeout are therefore not re-supplied from chat/queue JSON at execution time.
That keeps the Mission/Attempt -> provider handoff in-process and preserves the
canonical WorkItem identity for terminal UI evidence without creating a second
scheduler or provider path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .claude_bridge import ClaudeSealedInvocationBundle, ask_claude
from .ikarus_effect_bridge import (
    IkarusEffectBridgeRefused,
    validate_oneshot_mission_attempt,
)
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
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


@dataclass(frozen=True)
class MissionBoundClaudeInvocation:
    """In-process projection retaining canonical Mission/WorkItem identity.

    The sealed bundle remains the only capability-bearing provider input. This
    wrapper grants nothing; it keeps the already-validated Mission and Attempt
    alongside that bundle so a successful provider result can be projected back
    to the exact WorkItem instead of reconstructing identity from queue text.
    """

    mission: MissionContract
    attempt: AttemptContract
    request: OneShotRequest
    sealed_bundle: ClaudeSealedInvocationBundle

    def __post_init__(self) -> None:
        if type(self.mission) is not MissionContract:
            raise TypeError("mission must be an exact MissionContract")
        if type(self.attempt) is not AttemptContract:
            raise TypeError("attempt must be an exact AttemptContract")
        if type(self.request) is not OneShotRequest:
            raise TypeError("request must be an exact OneShotRequest")
        if type(self.sealed_bundle) is not ClaudeSealedInvocationBundle:
            raise TypeError(
                "sealed_bundle must be an exact ClaudeSealedInvocationBundle"
            )
        if self.request.runtime_id != CLAUDE_RUNTIME_ID:
            raise IkarusClaudeCompositionRefused(
                "mission-bound Claude invocation selected a non-Claude runtime"
            )
        if self.attempt.mission_id != self.mission.mission_id:
            raise IkarusClaudeCompositionRefused(
                "mission-bound invocation attempt belongs to another mission"
            )
        if self.attempt.task_id not in self.mission.work_item_ids:
            raise IkarusClaudeCompositionRefused(
                "mission-bound invocation attempt names a foreign WorkItem"
            )
        authorization = self.sealed_bundle.runtime_authorization
        if authorization.request.attempt_id != self.attempt.attempt_id:
            raise IkarusClaudeCompositionRefused(
                "mission-bound invocation bundle belongs to another attempt"
            )
        if (
            authorization.request.provenance.source_revision
            != self.attempt.base_revision
        ):
            raise IkarusClaudeCompositionRefused(
                "mission-bound invocation bundle belongs to another source revision"
            )

    @property
    def mission_id(self) -> str:
        return self.mission.mission_id

    @property
    def work_item_id(self) -> str:
        return self.attempt.task_id

    @property
    def attempt_id(self) -> str:
        return self.attempt.attempt_id


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
    and no Effect or provider code is started. The canonical Ikarus bridge first
    proves Mission -> WorkItem -> Attempt -> effect identity. The existing
    provider-runtime binder then proves the signed ABI/executable conjunction.
    Only that conjunction is representable as the public Claude sealed bundle.
    """

    if request.runtime_id != CLAUDE_RUNTIME_ID or runtime_evidence.runtime_id != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeCompositionRefused(
            "Claude composition requires the canonical claude_code_cli runtime binding"
        )
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


def compose_mission_bound_claude_invocation(
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
) -> MissionBoundClaudeInvocation:
    """Retain canonical WorkItem identity beside the fully sealed provider call."""

    sealed_bundle = compose_oneshot_claude_sealed_invocation(
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
    return MissionBoundClaudeInvocation(
        mission=mission,
        attempt=attempt,
        request=request,
        sealed_bundle=sealed_bundle,
    )


def _authenticated_payload_body(
    invocation: MissionBoundClaudeInvocation,
) -> dict[str, Any]:
    """Read provider call arguments only from the authenticated payload body."""

    if invocation.request.runtime_id != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeCompositionRefused(
            "mission-bound invocation no longer names the Claude runtime"
        )
    try:
        payload = invocation.sealed_bundle.invocation_payload.to_dict()
    except Exception as exc:  # noqa: BLE001 - malformed authority is a refusal.
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude invocation payload could not be read"
        ) from exc
    if type(payload) is not dict or type(payload.get("body")) is not dict:
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude invocation payload has no exact body object"
        )
    body = payload["body"]
    authorization = invocation.sealed_bundle.runtime_authorization
    workspace_grant = invocation.sealed_bundle.workspace_grant
    comparisons = {
        "attempt": (body.get("attempt_id"), invocation.attempt_id),
        "source revision": (
            body.get("source_revision"),
            invocation.attempt.base_revision,
        ),
        "lease request": (
            body.get("request_sha256"),
            authorization.request.digest,
        ),
        "worktree": (body.get("worktree"), workspace_grant.worktree),
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
            "authenticated Claude payload does not name the mission attempt: "
            + ", ".join(mismatches)
        )

    objective = body.get("objective")
    paths = body.get("paths")
    model = body.get("model")
    timeout_s = body.get("timeout_s")
    if not isinstance(objective, str) or not objective.strip():
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude payload objective is missing"
        )
    if type(paths) is not list or any(not isinstance(path, str) for path in paths):
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude payload paths are malformed"
        )
    if not isinstance(model, str) or not model.strip():
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude payload model is missing"
        )
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int)
        or timeout_s <= 0
    ):
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude payload timeout is malformed"
        )
    return body


def dispatch_mission_bound_claude_invocation(
    invocation: MissionBoundClaudeInvocation,
) -> dict[str, Any]:
    """Execute one sealed Claude call and project its result to the WorkItem.

    The provider arguments come only from the authenticated invocation payload,
    never from queue/chat metadata. The provider must return the same runtime and
    Attempt identity before Ikarus adds Mission/WorkItem projection fields. Phase
    and terminal receipt remain provider evidence and are never fabricated here.
    """

    if type(invocation) is not MissionBoundClaudeInvocation:
        raise IkarusClaudeCompositionRefused(
            "dispatch requires an exact MissionBoundClaudeInvocation"
        )
    body = _authenticated_payload_body(invocation)
    result = ask_claude(
        body["objective"],
        body["worktree"],
        list(body["paths"]),
        model=body["model"],
        timeout_s=body["timeout_s"],
        sealed_bundle=invocation.sealed_bundle,
    )
    if type(result) is not dict:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude provider returned a non-object result"
        )
    if result.get("attempt_id") != invocation.attempt_id:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result does not name the canonical Attempt"
        )
    if result.get("runtime_id") != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result does not name the canonical Claude runtime"
        )
    return {
        **result,
        "mission_id": invocation.mission_id,
        "work_item_id": invocation.work_item_id,
    }


__all__ = [
    "IkarusClaudeCompositionRefused",
    "MissionBoundClaudeInvocation",
    "compose_mission_bound_claude_invocation",
    "compose_oneshot_claude_sealed_invocation",
    "dispatch_mission_bound_claude_invocation",
]
