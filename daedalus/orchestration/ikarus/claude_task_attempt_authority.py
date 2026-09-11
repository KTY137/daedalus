"""Authenticate and dispatch sealed Claude work from the live TaskAttempt owner.

The productive ``MissionSupervisor -> TaskAttempt`` path freezes its owner
identity before the runner starts and authenticates the actual isolated
``RunnerContext`` before provider code can see it. This module re-proves that
already-issued Ikarus/runtime/effect/provider authorities belong to that owner.

The dispatch seam deliberately does not require a terminal ``AttemptContract``:
it seals the live owner and existing authorities, reads call arguments only from
the authenticated provider payload, and checks provider receipts before
Mission/WorkItem projection. Terminal Attempt evidence stays a later
corroboration step. Nothing here issues authority or creates another lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ...claude_bridge import ask_claude
from .claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from .claude_composition import (
    ClaudeSealedInvocationBundle,
    _sealed_bundle_members,
)
from .oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .tool_scope import IkarusToolScopeProjection
from ...kernel.contracts import EffectLeaseRequest
from ...kernel.effects import EffectExecutionRequest
from ...kernel.runtime_effects import RuntimeBoundEffectAuthorization
from ...providers.claude_cli import (
    ENTRYPOINT_ID as CLAUDE_ENTRYPOINT_ID,
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from ...runtimes.provider.executable_object_registry import ProviderExecutableObjectRegistry
from ...runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from ...runtimes.provider.invocation_abi import ProviderInvocationABIContract
from ...runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from ...runtimes.provider.invocation_payload import ProviderInvocationPayload
from ...runtimes.provider.observation import ProviderObservationBindingLedger
from ...runtimes.provider.runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)
from ...runtimes.provider.runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingError,
    bind_provider_runtime_invocation,
)
from ...schemas import MissionContract


class IkarusClaudeTaskAttemptAuthorityRefused(RuntimeError):
    """Sealed Claude authority does not belong to the live TaskAttempt owner."""


@dataclass(frozen=True)
class TaskAttemptBoundClaudeInvocation:
    """Inert owner projection beside one exact capability-bearing sealed bundle."""

    handoff: ClaudeTaskAttemptRunnerHandoff
    request: OneShotRequest
    sealed_bundle: ClaudeSealedInvocationBundle

    def __post_init__(self) -> None:
        _exact(self.handoff, ClaudeTaskAttemptRunnerHandoff, "handoff")
        _exact(self.request, OneShotRequest, "request")
        _exact(self.sealed_bundle, ClaudeSealedInvocationBundle, "sealed_bundle")
        if self.request.runtime_id != CLAUDE_RUNTIME_ID:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "TaskAttempt-bound invocation selected a non-Claude runtime"
            )
        authorization = self.sealed_bundle.runtime_authorization
        workspace = self.sealed_bundle.workspace_grant
        mismatches = sorted(
            label
            for label, actual, expected in (
                (
                    "authorization attempt",
                    authorization.request.attempt_id,
                    self.handoff.attempt_id,
                ),
                (
                    "authorization source revision",
                    authorization.request.provenance.source_revision,
                    self.handoff.source_revision,
                ),
                ("workspace attempt", workspace.attempt_id, self.handoff.attempt_id),
                (
                    "workspace source revision",
                    workspace.source_revision,
                    self.handoff.source_revision,
                ),
            )
            if actual != expected
        )
        if mismatches:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "sealed bundle differs from the live TaskAttempt owner: "
                + ", ".join(mismatches)
            )

    @property
    def mission_id(self) -> str:
        return self.handoff.mission_id

    @property
    def work_item_id(self) -> str:
        return self.handoff.work_item_id

    @property
    def attempt_id(self) -> str:
        return self.handoff.attempt_id


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
    """Re-authenticate every Claude authority against one live TaskAttempt owner."""

    for value, exact_type, label in (
        (handoff, ClaudeTaskAttemptRunnerHandoff, "handoff"),
        (request, OneShotRequest, "request"),
        (runtime_evidence, OneShotRuntimeEvidenceBinding, "runtime_evidence"),
        (tool_scope, IkarusToolScopeProjection, "tool_scope"),
        (effect_request, EffectLeaseRequest, "effect_request"),
        (execution, EffectExecutionRequest, "execution"),
        (
            runtime_authorization,
            RuntimeBoundEffectAuthorization,
            "runtime_authorization",
        ),
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
    if (
        request.runtime_id != CLAUDE_RUNTIME_ID
        or runtime_evidence.runtime_id != CLAUDE_RUNTIME_ID
    ):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "live TaskAttempt provider binding requires claude_code_cli"
        )

    comparisons = {
        "runtime evidence request": (runtime_evidence.request_sha256, request.digest),
        "runtime evidence role": (runtime_evidence.role, request.role),
        "runtime binding": (
            runtime_evidence.runtime_binding_sha256,
            request.runtime_binding_sha256,
        ),
        "runtime source revision": (
            runtime_evidence.source_revision,
            handoff.source_revision,
        ),
        "tool request": (tool_scope.request_sha256, request.digest),
        "tool runtime evidence": (
            tool_scope.runtime_evidence_sha256,
            runtime_evidence.digest,
        ),
        "tool runtime manifest": (
            tool_scope.runtime_manifest_sha256,
            runtime_evidence.runtime_manifest_sha256,
        ),
        "effect mission": (effect_request.mission_id, handoff.mission_id),
        "effect attempt": (effect_request.attempt_id, handoff.attempt_id),
        "effect entrypoint": (effect_request.entrypoint_id, CLAUDE_ENTRYPOINT_ID),
        "effect runtime manifest": (
            effect_request.runtime_manifest_sha256,
            runtime_evidence.runtime_manifest_sha256,
        ),
        "effect runtime conformance": (
            effect_request.runtime_conformance_sha256,
            runtime_evidence.runtime_conformance_sha256,
        ),
        "effect source revision": (
            effect_request.provenance.source_revision,
            handoff.source_revision,
        ),
        "runtime authorization request": (runtime_authorization.request, effect_request),
        "workspace attempt": (workspace_grant.attempt_id, handoff.attempt_id),
        "workspace source revision": (
            workspace_grant.source_revision,
            handoff.source_revision,
        ),
        "workspace lease request": (
            workspace_grant.request_sha256,
            effect_request.digest,
        ),
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
    _require_subset(
        tuple(execution.tools),
        tuple(tool_scope.enabled_tools),
        "execution tool scope",
    )
    _require_subset(
        tuple(execution.requested_effects),
        tuple(effect_request.requested_effects),
        "execution effect scope",
    )

    owner_workspace = _resolved_directory(
        handoff.worktree, "TaskAttempt runner workspace"
    )
    granted_workspace = _resolved_directory(
        workspace_grant.worktree, "Claude workspace grant"
    )
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


def compose_task_attempt_bound_claude_invocation(
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
) -> TaskAttemptBoundClaudeInvocation:
    """Authenticate first, then make the existing authority set indivisible."""

    bind_task_attempt_claude_provider_authorities(
        handoff,
        mission,
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
    try:
        bundle = ClaudeSealedInvocationBundle(
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
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "TaskAttempt Claude bundle rejected substituted authority members"
        ) from exc
    return TaskAttemptBoundClaudeInvocation(handoff, request, bundle)


def _is_lower_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _resolved_scoped_path(root: Path, raw: str, label: str) -> Path:
    if type(raw) is not str or not raw.strip():
        raise IkarusClaudeTaskAttemptAuthorityRefused(f"{label} is malformed")
    try:
        path = Path(raw).expanduser()
        return (
            path.resolve(strict=False)
            if path.is_absolute()
            else (root / path).resolve(strict=False)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            f"{label} could not be resolved"
        ) from exc


def _require_payload_paths_within_owner(
    handoff: ClaudeTaskAttemptRunnerHandoff,
    paths: list[str],
) -> None:
    root = _resolved_directory(handoff.worktree, "TaskAttempt runner workspace")
    scopes = tuple(
        _resolved_scoped_path(root, path, "TaskAttempt target path")
        for path in handoff.target_paths
    )
    if any(scope != root and not scope.is_relative_to(root) for scope in scopes):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "TaskAttempt target path escapes the authenticated workspace"
        )
    escaped = []
    for raw in paths:
        candidate = _resolved_scoped_path(root, raw, "Claude payload path")
        if candidate != root and not candidate.is_relative_to(root):
            escaped.append(raw)
        elif not any(
            candidate == scope or candidate.is_relative_to(scope) for scope in scopes
        ):
            escaped.append(raw)
    if escaped:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload path exceeds TaskAttempt owner scope: "
            + ", ".join(sorted(escaped))
        )


def _authenticated_payload_body(
    invocation: TaskAttemptBoundClaudeInvocation,
) -> dict[str, Any]:
    _exact(invocation, TaskAttemptBoundClaudeInvocation, "invocation")
    if invocation.request.runtime_id != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "TaskAttempt-bound invocation no longer names the Claude runtime"
        )
    try:
        payload = invocation.sealed_bundle.invocation_payload.to_dict()
    except Exception as exc:  # noqa: BLE001 - malformed authority is a refusal.
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude invocation payload could not be read"
        ) from exc
    if type(payload) is not dict or type(payload.get("body")) is not dict:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude invocation payload has no exact body object"
        )

    body = payload["body"]
    authorization = invocation.sealed_bundle.runtime_authorization
    workspace = invocation.sealed_bundle.workspace_grant
    mismatches = sorted(
        label
        for label, actual, expected in (
            ("attempt", body.get("attempt_id"), invocation.attempt_id),
            (
                "source revision",
                body.get("source_revision"),
                invocation.handoff.source_revision,
            ),
            ("lease request", body.get("request_sha256"), authorization.request.digest),
            ("worktree", body.get("worktree"), workspace.worktree),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload does not name the live TaskAttempt: "
            + ", ".join(mismatches)
        )

    objective = body.get("objective")
    paths = body.get("paths")
    model = body.get("model")
    timeout_s = body.get("timeout_s")
    if not isinstance(objective, str) or not objective.strip():
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload objective is missing"
        )
    if type(paths) is not list or any(type(path) is not str for path in paths):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload paths are malformed"
        )
    if not isinstance(model, str) or not model.strip():
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload model is missing"
        )
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload timeout is malformed"
        )
    if not _is_lower_sha256(body.get("invocation_sha256")):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload invocation identity is malformed"
        )

    if _resolved_directory(body["worktree"], "Claude payload worktree") != _resolved_directory(
        invocation.handoff.worktree, "TaskAttempt runner workspace"
    ):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "authenticated Claude payload worktree differs from the TaskAttempt workspace"
        )
    _require_payload_paths_within_owner(invocation.handoff, paths)
    return body


def _require_provider_result(
    result: dict[str, Any],
    invocation: TaskAttemptBoundClaudeInvocation,
    invocation_sha256: str,
) -> None:
    if result.get("provider") != "claude_cli":
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude result does not name the canonical Claude provider"
        )
    if result.get("attempt_id") != invocation.attempt_id:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude result does not name the live TaskAttempt"
        )
    if result.get("runtime_id") != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude result does not name the canonical Claude runtime"
        )
    receipt = result.get("runtime_receipt")
    if type(receipt) is not dict:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude result has no exact runtime receipt"
        )
    if receipt.get("invocation_sha256") != invocation_sha256:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude runtime receipt belongs to another authenticated invocation"
        )
    if type(receipt.get("executed")) is not bool:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude runtime receipt has no exact execution state"
        )
    replay = result.get("replay")
    if replay is not None and type(replay) is not bool:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude result has a malformed replay state"
        )
    if (receipt["executed"] and replay is True) or (
        not receipt["executed"] and replay is not True
    ):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude replay evidence contradicts the runtime receipt"
        )
    if not _is_lower_sha256(receipt.get("start_receipt_sha256")):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude runtime receipt has no valid start receipt"
        )
    nested_terminal = receipt.get("terminal_receipt_sha256")
    top_terminal = result.get("terminal_receipt_sha256")
    if nested_terminal is None:
        if result.get("phase") == "terminal" or top_terminal is not None:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "sealed Claude terminal evidence is not backed by the runtime receipt"
            )
    elif (
        not _is_lower_sha256(nested_terminal)
        or result.get("phase") != "terminal"
        or top_terminal != nested_terminal
    ):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude terminal evidence does not match the runtime receipt"
        )


def dispatch_task_attempt_bound_claude_invocation(
    invocation: TaskAttemptBoundClaudeInvocation,
) -> dict[str, Any]:
    """Dispatch from the live TaskAttempt without synthesizing terminal identity."""

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
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "sealed Claude provider returned a non-object result"
        )
    _require_provider_result(result, invocation, body["invocation_sha256"])
    return {
        **result,
        "mission_id": invocation.mission_id,
        "work_item_id": invocation.work_item_id,
    }


def execute_task_attempt_bound_claude_invocation(
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
) -> dict[str, Any]:
    """Authenticate, seal and dispatch one live TaskAttempt-owned Claude call."""

    invocation = compose_task_attempt_bound_claude_invocation(
        handoff,
        mission,
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
    return dispatch_task_attempt_bound_claude_invocation(invocation)


__all__ = [
    "IkarusClaudeTaskAttemptAuthorityRefused",
    "TaskAttemptBoundClaudeInvocation",
    "bind_task_attempt_claude_provider_authorities",
    "compose_task_attempt_bound_claude_invocation",
    "dispatch_task_attempt_bound_claude_invocation",
    "execute_task_attempt_bound_claude_invocation",
]
