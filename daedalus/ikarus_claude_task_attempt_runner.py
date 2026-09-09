"""RoleHarness adapter for sealed Claude execution inside one live TaskAttempt.

The supervisor authenticates ``ClaudeTaskAttemptRunnerHandoff`` before this
factory is reached. This module deliberately issues no authority and owns no
lifecycle. It only asks a trusted in-process resolver for the already-issued
runtime/effect/provider subjects, composes them through the canonical
TaskAttempt authority boundary immediately, and returns a runner that can only
dispatch the resulting sealed invocation.

The factory also snapshots the exact planned runtime-role descriptor. That
closes a provenance gap between supervisor planning and provider admission: a
resolver cannot substitute a different runtime binding while still presenting
valid provider-side evidence. Keeping composition in the factory (rather than
the returned runner) matters for the same reason: provider-controlled runner
code never receives the loose authority set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from .ikarus_claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from .ikarus_claude_task_attempt_authority import (
    IkarusClaudeTaskAttemptAuthorityRefused,
    TaskAttemptBoundClaudeInvocation,
    compose_task_attempt_bound_claude_invocation,
    dispatch_task_attempt_bound_claude_invocation,
)
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_runtime_role import (
    AUTHENTICATED_HANDOFF_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
    RuntimeRoleSnapshot,
)
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from .runtimes.provider_executable_object_registry import ProviderExecutableObjectRegistry
from .runtimes.provider_executable_pre_admission import ProviderExecutablePreAdmissionReceipt
from .runtimes.provider_invocation_abi import ProviderInvocationABIContract
from .runtimes.provider_invocation_authority import ProviderInvocationObservationAuthority
from .runtimes.provider_invocation_payload import ProviderInvocationPayload
from .runtimes.provider_observation import ProviderObservationBindingLedger
from .schemas import MissionContract


@dataclass(frozen=True)
class ClaudeTaskAttemptInvocationInputs:
    """Inert in-process grouping of already-issued Claude invocation inputs.

    This object is not an authority, receipt, registry, or serialized contract.
    Canonical validation remains owned by
    :func:`compose_task_attempt_bound_claude_invocation`.
    """

    mission: MissionContract
    request: OneShotRequest
    runtime_evidence: OneShotRuntimeEvidenceBinding
    tool_scope: IkarusToolScopeProjection
    effect_request: EffectLeaseRequest
    execution: EffectExecutionRequest
    runtime_authorization: RuntimeBoundEffectAuthorization
    workspace_grant: ClaudeWorkspaceGrant
    invocation_authority: ProviderInvocationObservationAuthority
    invocation_payload: ProviderInvocationPayload
    invocation_abi: ProviderInvocationABIContract
    observation_binding_ledger: ProviderObservationBindingLedger
    executable_registry: ProviderExecutableObjectRegistry
    pre_admission: ProviderExecutablePreAdmissionReceipt
    at: datetime

    def compose(
        self,
        handoff: ClaudeTaskAttemptRunnerHandoff,
    ) -> TaskAttemptBoundClaudeInvocation:
        """Seal this exact input set against the authenticated TaskAttempt owner."""

        return compose_task_attempt_bound_claude_invocation(
            handoff,
            self.mission,
            self.request,
            self.runtime_evidence,
            self.tool_scope,
            self.effect_request,
            self.execution,
            runtime_authorization=self.runtime_authorization,
            workspace_grant=self.workspace_grant,
            invocation_authority=self.invocation_authority,
            invocation_payload=self.invocation_payload,
            invocation_abi=self.invocation_abi,
            observation_binding_ledger=self.observation_binding_ledger,
            executable_registry=self.executable_registry,
            pre_admission=self.pre_admission,
            at=self.at,
        )


ClaudeTaskAttemptInputResolver = Callable[
    [Any, ClaudeTaskAttemptRunnerHandoff],
    ClaudeTaskAttemptInvocationInputs,
]


def _snapshot_runtime_binding(
    runtime_binding: RuntimeRoleSnapshot,
) -> RuntimeRoleSnapshot:
    """Detach the factory from caller-owned frozen-but-mutable descriptor data."""

    if type(runtime_binding) is not RuntimeRoleSnapshot:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude runner factory requires an exact RuntimeRoleSnapshot"
        )
    try:
        validated = RuntimeRoleBinding(
            role=runtime_binding.role,
            runtime_id=runtime_binding.runtime_id,
            adapter_id=runtime_binding.adapter_id,
            adapter_version=runtime_binding.adapter_version,
            source_revision=runtime_binding.source_revision,
            origin=runtime_binding.origin,
            execution_mode=runtime_binding.execution_mode,
            refusal_reason=runtime_binding.refusal_reason,
        )
        snapshot = RuntimeRoleRegistry((validated,)).snapshot(
            validated.role,
            validated.runtime_id,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude runtime-role binding could not be snapshotted"
        ) from exc
    if snapshot is None or snapshot.digest != runtime_binding.digest:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude runtime-role binding changed while its snapshot was captured"
        )
    if snapshot.runtime_id != CLAUDE_RUNTIME_ID:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude runner factory requires the canonical claude_code_cli runtime"
        )
    if snapshot.execution_mode != AUTHENTICATED_HANDOFF_EXECUTION_MODE:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude runner factory requires an authenticated-handoff runtime binding"
        )
    return snapshot


def _require_planned_runtime(
    item: Any,
    runtime_binding: RuntimeRoleSnapshot,
) -> None:
    """Corroborate the RoleHarness work item against its exact planned binding."""

    if (
        str(getattr(item, "role", "")) != runtime_binding.role
        or str(getattr(item, "runtime_id", "")) != runtime_binding.runtime_id
    ):
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "Claude RoleHarness item differs from the planned runtime-role binding"
        )


def _require_resolved_runtime(
    inputs: ClaudeTaskAttemptInvocationInputs,
    runtime_binding: RuntimeRoleSnapshot,
) -> None:
    """Refuse a resolver that swaps the runtime descriptor behind a valid handoff."""

    mismatches = sorted(
        label
        for label, actual, expected in (
            ("request role", inputs.request.role, runtime_binding.role),
            ("request runtime", inputs.request.runtime_id, runtime_binding.runtime_id),
            (
                "request runtime binding",
                inputs.request.runtime_binding_sha256,
                runtime_binding.digest,
            ),
            ("runtime evidence role", inputs.runtime_evidence.role, runtime_binding.role),
            (
                "runtime evidence runtime",
                inputs.runtime_evidence.runtime_id,
                runtime_binding.runtime_id,
            ),
            (
                "runtime evidence binding",
                inputs.runtime_evidence.runtime_binding_sha256,
                runtime_binding.digest,
            ),
            (
                "runtime evidence source revision",
                inputs.runtime_evidence.source_revision,
                runtime_binding.source_revision,
            ),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeTaskAttemptAuthorityRefused(
            "resolved Claude authority differs from the planned runtime-role binding: "
            + ", ".join(mismatches)
        )


def make_task_attempt_claude_handoff_runner_factory(
    runtime_binding: RuntimeRoleSnapshot,
    resolve_inputs: ClaudeTaskAttemptInputResolver,
) -> Callable[[Any, ClaudeTaskAttemptRunnerHandoff], Callable[[Any], Any]]:
    """Adapt a trusted input resolver to ``RoleHarness.handoff_runner_factory``.

    ``runtime_binding`` is the exact immutable plan descriptor resolved by the
    supervisor. It is snapshotted when the factory is built, then corroborated
    against both the actual ``PlannedItem`` and the resolver's request/runtime
    evidence. The resolver is invoked only after ``MissionSupervisor`` has
    authenticated the real ``RunnerContext`` and produced ``handoff``.

    The returned loose inputs are sealed *before* a runner is handed back to
    ``TaskAttempt``. Consequently the runner closure retains only the canonical
    :class:`TaskAttemptBoundClaudeInvocation` and cannot widen authority.
    """

    planned_runtime = _snapshot_runtime_binding(runtime_binding)
    if not callable(resolve_inputs):
        raise TypeError("resolve_inputs must be callable")

    def _factory(
        item: Any,
        handoff: ClaudeTaskAttemptRunnerHandoff,
    ) -> Callable[[Any], Any]:
        if type(handoff) is not ClaudeTaskAttemptRunnerHandoff:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "Claude runner factory requires an exact authenticated "
                "ClaudeTaskAttemptRunnerHandoff"
            )
        _require_planned_runtime(item, planned_runtime)

        inputs = resolve_inputs(item, handoff)
        if type(inputs) is not ClaudeTaskAttemptInvocationInputs:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "Claude input resolver must return an exact "
                "ClaudeTaskAttemptInvocationInputs"
            )
        _require_resolved_runtime(inputs, planned_runtime)

        # Seal while still inside the authenticated RoleHarness factory seam.
        # The returned runner closes over the sealed invocation only.
        invocation = inputs.compose(handoff)

        def _runner(_ctx: Any) -> Any:
            return dispatch_task_attempt_bound_claude_invocation(invocation)

        return _runner

    return _factory


__all__ = [
    "ClaudeTaskAttemptInputResolver",
    "ClaudeTaskAttemptInvocationInputs",
    "make_task_attempt_claude_handoff_runner_factory",
]
