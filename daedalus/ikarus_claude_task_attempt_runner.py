"""RoleHarness adapter for sealed Claude execution inside one live TaskAttempt.

The supervisor authenticates ``ClaudeTaskAttemptRunnerHandoff`` before this
factory is reached.  This module deliberately issues no authority and owns no
lifecycle.  It only asks a trusted in-process resolver for the already-issued
runtime/effect/provider subjects, composes them through the canonical
TaskAttempt authority boundary immediately, and returns a runner that can only
dispatch the resulting sealed invocation.

Keeping composition in the factory (rather than the returned runner) matters:
provider-controlled runner code never receives the loose authority set.
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
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .providers.claude_cli import ClaudeWorkspaceGrant
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


def make_task_attempt_claude_handoff_runner_factory(
    resolve_inputs: ClaudeTaskAttemptInputResolver,
) -> Callable[[Any, ClaudeTaskAttemptRunnerHandoff], Callable[[Any], Any]]:
    """Adapt a trusted input resolver to ``RoleHarness.handoff_runner_factory``.

    The resolver is invoked only after ``MissionSupervisor`` has authenticated
    the real ``RunnerContext`` and produced ``handoff``.  The returned loose
    inputs are sealed *before* a runner is handed back to ``TaskAttempt``.
    Consequently the runner closure retains only the canonical
    :class:`TaskAttemptBoundClaudeInvocation` and cannot widen authority.
    """

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

        inputs = resolve_inputs(item, handoff)
        if type(inputs) is not ClaudeTaskAttemptInvocationInputs:
            raise IkarusClaudeTaskAttemptAuthorityRefused(
                "Claude input resolver must return an exact "
                "ClaudeTaskAttemptInvocationInputs"
            )

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
