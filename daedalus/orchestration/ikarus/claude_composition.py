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

from ...claude_bridge import ask_claude
from .effect_bridge import (
    IkarusEffectBridgeRefused,
    validate_oneshot_mission_attempt,
)
from .oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .tool_scope import IkarusToolScopeProjection
from ...kernel.contracts import EffectLeaseRequest
from ...kernel.effects import EffectExecutionRequest
from ...kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ...providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from ...runtimes.provider.executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from ...runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from ...runtimes.provider.invocation_abi import ProviderInvocationABIContract
from ...runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from ...runtimes.provider.invocation_payload import ProviderInvocationPayload
from ...runtimes.provider.observation import ProviderObservationBindingLedger
from ...runtimes.provider.runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingError,
    bind_provider_runtime_invocation,
)
from ...schemas import AttemptContract, MissionContract


class IkarusClaudeCompositionRefused(RuntimeError):
    """The supplied mission/attempt/runtime subjects cannot form one Claude call."""


@dataclass(frozen=True)
class ClaudeSealedInvocationBundle:
    """One indivisible capability-bearing input to the public Claude bridge.

    The individual records are still owned and authenticated by their existing
    kernel/runtime layers. This type grants nothing and verifies no signature;
    it only prevents this composition seam from representing an impossible
    half-bundle. ``ClaudeCLIProvider`` and the sealed broker remain the
    authority boundary and re-verify every member before an effect can start.

    Exact-type checks are intentional. Duck-typed authority members can execute
    caller-controlled property access before the sealed broker sees them, so
    the bundle rejects substituted member objects at construction.

    PORT NOTE (2026-09-09). On the originating lane this record lived in
    ``daedalus.claude_bridge`` and ``ask_claude`` took it as a single
    ``sealed_bundle`` argument. Current ``main`` instead keeps the nine members
    as separate keyword arguments AND already refuses any partial set with
    ``ClaudeProviderAuthorizationRequired``, so the anti-half-bundle guard
    exists there in a different shape. The record is kept here -- one
    definition, in the module that composes it -- rather than changing a public
    bridge signature that other callers on ``main`` depend on.
    :func:`_sealed_bundle_members` is the single explosion point.
    """

    runtime_authorization: "RuntimeBoundEffectAuthorization"
    effect_execution: "EffectExecutionRequest"
    workspace_grant: "ClaudeWorkspaceGrant"
    invocation_authority: "ProviderInvocationObservationAuthority"
    invocation_payload: "ProviderInvocationPayload"
    invocation_abi: "ProviderInvocationABIContract"
    observation_binding_ledger: "ProviderObservationBindingLedger"
    executable_registry: "ProviderExecutableObjectRegistry"
    pre_admission: "ProviderExecutablePreAdmissionReceipt"

    def __post_init__(self) -> None:
        missing = [
            name
            for name in _SEALED_BUNDLE_MEMBERS
            if getattr(self, name) is None
        ]
        if missing:
            raise ValueError(
                "Claude sealed invocation bundle cannot contain empty members: "
                + ", ".join(missing)
            )

        expected_types = {
            "runtime_authorization": RuntimeBoundEffectAuthorization,
            "effect_execution": EffectExecutionRequest,
            "workspace_grant": ClaudeWorkspaceGrant,
            "invocation_authority": ProviderInvocationObservationAuthority,
            "invocation_payload": ProviderInvocationPayload,
            "invocation_abi": ProviderInvocationABIContract,
            "observation_binding_ledger": ProviderObservationBindingLedger,
            "executable_registry": ProviderExecutableObjectRegistry,
            "pre_admission": ProviderExecutablePreAdmissionReceipt,
        }
        substituted = [
            name
            for name, expected_type in expected_types.items()
            if type(getattr(self, name)) is not expected_type
        ]
        if substituted:
            raise TypeError(
                "Claude sealed invocation bundle requires exact authority member types: "
                + ", ".join(substituted)
            )


_SEALED_BUNDLE_MEMBERS = (
    "runtime_authorization",
    "effect_execution",
    "workspace_grant",
    "invocation_authority",
    "invocation_payload",
    "invocation_abi",
    "observation_binding_ledger",
    "executable_registry",
    "pre_admission",
)


def _sealed_bundle_members(
    bundle: ClaudeSealedInvocationBundle,
) -> dict[str, Any]:
    """Explode the sealed bundle into the keyword arguments ``ask_claude`` takes.

    The bridge on ``main`` names ``effect_execution`` as ``effect_execution``
    and expects each member individually; it raises
    ``ClaudeProviderAuthorizationRequired`` when any of the nine is missing.
    Every caller in this package must route through this function so the
    bundle stays the only way the nine are assembled.
    """

    if type(bundle) is not ClaudeSealedInvocationBundle:
        raise IkarusClaudeCompositionRefused(
            "sealed provider members require an exact ClaudeSealedInvocationBundle"
        )
    return {name: getattr(bundle, name) for name in _SEALED_BUNDLE_MEMBERS}


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
    if not _is_lower_sha256(body.get("invocation_sha256")):
        raise IkarusClaudeCompositionRefused(
            "authenticated Claude payload invocation identity is malformed"
        )
    return body


def _is_lower_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _require_provider_result_binding(
    result: dict[str, Any],
    invocation: MissionBoundClaudeInvocation,
    *,
    invocation_sha256: str,
) -> None:
    """Authenticate provider identity and receipts before WorkItem projection."""

    if result.get("provider") != "claude_cli":
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result does not name the canonical Claude provider"
        )
    if result.get("attempt_id") != invocation.attempt_id:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result does not name the canonical Attempt"
        )
    if result.get("runtime_id") != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result does not name the canonical Claude runtime"
        )

    runtime_receipt = result.get("runtime_receipt")
    if type(runtime_receipt) is not dict:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result has no exact runtime receipt"
        )
    if runtime_receipt.get("invocation_sha256") != invocation_sha256:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude runtime receipt belongs to another authenticated invocation"
        )
    if type(runtime_receipt.get("executed")) is not bool:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude runtime receipt has no exact execution state"
        )
    replay = result.get("replay")
    if replay is not None and type(replay) is not bool:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude result has a malformed replay state"
        )
    executed = runtime_receipt["executed"]
    if (executed and replay is True) or (not executed and replay is not True):
        raise IkarusClaudeCompositionRefused(
            "sealed Claude replay evidence contradicts the runtime receipt"
        )
    if not _is_lower_sha256(runtime_receipt.get("start_receipt_sha256")):
        raise IkarusClaudeCompositionRefused(
            "sealed Claude runtime receipt has no valid start receipt"
        )

    nested_terminal = runtime_receipt.get("terminal_receipt_sha256")
    top_terminal = result.get("terminal_receipt_sha256")
    phase = result.get("phase")
    if nested_terminal is None:
        if phase == "terminal" or top_terminal is not None:
            raise IkarusClaudeCompositionRefused(
                "sealed Claude terminal evidence is not backed by the runtime receipt"
            )
        return
    if not _is_lower_sha256(nested_terminal):
        raise IkarusClaudeCompositionRefused(
            "sealed Claude runtime receipt has an invalid terminal receipt"
        )
    if phase != "terminal" or top_terminal != nested_terminal:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude terminal evidence does not match the runtime receipt"
        )


def dispatch_mission_bound_claude_invocation(
    invocation: MissionBoundClaudeInvocation,
) -> dict[str, Any]:
    """Execute one sealed Claude call and project its result to the WorkItem.

    The provider arguments come only from the authenticated invocation payload,
    never from queue/chat metadata. The provider must return the same provider,
    runtime, Attempt identity and exact invocation receipt before Ikarus adds
    Mission/WorkItem projection fields. Phase and terminal receipt remain
    provider evidence and are never fabricated here.
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
        **_sealed_bundle_members(invocation.sealed_bundle),
    )
    if type(result) is not dict:
        raise IkarusClaudeCompositionRefused(
            "sealed Claude provider returned a non-object result"
        )
    _require_provider_result_binding(
        result,
        invocation,
        invocation_sha256=body["invocation_sha256"],
    )
    return {
        **result,
        "mission_id": invocation.mission_id,
        "work_item_id": invocation.work_item_id,
    }


def execute_mission_bound_claude_invocation(
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
    """Consume one complete authority set and dispatch it as one atomic handoff.

    This is the productive Ikarus-facing seam for a Mission/Attempt authority
    producer. It intentionally issues nothing: every authority must already be
    canonical and in-process. Composition completes before dispatch is reachable,
    so a partial or substituted authority set can never fall through to Claude.
    """

    invocation = compose_mission_bound_claude_invocation(
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
    return dispatch_mission_bound_claude_invocation(invocation)


__all__ = [
    "IkarusClaudeCompositionRefused",
    "MissionBoundClaudeInvocation",
    "compose_mission_bound_claude_invocation",
    "compose_oneshot_claude_sealed_invocation",
    "dispatch_mission_bound_claude_invocation",
    "execute_mission_bound_claude_invocation",
]
