"""Pure Gate-0 binding for one already-authorized Ollama offload.

This module neither issues nor consumes authority.  It proves that the v2
plan, canonical attempt, observed workspace, exact runtime tool, signed lease
bundle, and narrowed execution request all describe one bounded operation.
"""
from __future__ import annotations

from dataclasses import dataclass

from daedalus.kernel.contracts import OffloadExecutionPlan
from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectAuthorization
from daedalus.kernel.offload_observations import (
    OffloadWorkspaceObservation,
    TargetBeforeObservation,
    TaskAttemptWorkspaceAttestation,
)
from daedalus.kernel.runtime_tools import RuntimeToolBinding
from daedalus.schemas import AttemptContract
from daedalus.spine.envelope import canonical_sha


OFFLOAD_OPERATION = "single-target-ollama-rewrite"


class OffloadAuthorityBindingError(ValueError):
    """Fail-closed refusal before any offload-side effect is consumed."""


def derive_offload_execution_ids(plan: OffloadExecutionPlan) -> tuple[str, str]:
    """Derive retry identity from intent + attempt contract + operation.

    Plan provenance, timestamps, routing receipts, and model observations may
    be legitimately re-sealed without authorizing another provider call.  A
    second model call therefore requires a new AttemptContract (or intent),
    while every plan revision for the same semantic attempt collides in the
    canonical effect ledger.
    """

    if not isinstance(plan, OffloadExecutionPlan):
        raise ValueError("plan must be an OffloadExecutionPlan")
    semantic_identity = {
        "spine_intent_id": plan.spine_intent_id,
        "spine_intent_sha256": plan.spine_intent_sha256,
        "attempt_contract_sha256": plan.attempt_contract_sha256,
        "operation": OFFLOAD_OPERATION,
    }
    execution_sha = canonical_sha(
        {
            "domain": "daedalus.offload-execution-id/2",
            "semantic_identity": semantic_identity,
        }
    )
    idempotency_sha = canonical_sha(
        {
            "domain": "daedalus.offload-idempotency-key/2",
            "semantic_identity": semantic_identity,
        }
    )
    return (
        f"offload-execution:{execution_sha}",
        f"offload-idempotency:{idempotency_sha}",
    )


def _mismatches(
    plan: OffloadExecutionPlan,
    attempt: AttemptContract,
    workspace_attestation: TaskAttemptWorkspaceAttestation,
    target_before: TargetBeforeObservation,
    workspace_observation: OffloadWorkspaceObservation,
    runtime_tool_binding: RuntimeToolBinding,
    authorization: LeasedEffectAuthorization,
    execution: EffectExecutionRequest,
) -> list[str]:
    request = authorization.request
    lease = authorization.lease
    policy = authorization.policy_decision
    scope = plan.effect_scope
    mismatches: list[str] = []

    def exact(label: str, actual: object, expected: object) -> None:
        if actual != expected:
            mismatches.append(label)

    # Canonical attempt and immutable plan.
    exact("attempt_contract_sha256", plan.attempt_contract_sha256, attempt.digest)
    exact("attempt_mission_id", plan.mission_id, attempt.mission_id)
    exact("attempt_id", plan.attempt_id, attempt.attempt_id)
    exact("task_id", plan.task_id, attempt.task_id)
    exact("task_sha256", plan.task_sha256, attempt.task_sha256)
    exact("source_revision", plan.source_revision, attempt.base_revision)
    exact(
        "attempt_policy_decision_sha256",
        plan.attempt_policy_decision_sha256,
        attempt.policy_decision_sha256,
    )
    exact(
        "attempt_runtime_manifest_sha256",
        plan.runtime_manifest_sha256,
        attempt.runtime_manifest_sha256,
    )
    exact("attempt_writable_paths", (plan.target_path,), attempt.writable_paths)
    if len(attempt.writable_paths) != 1:
        mismatches.append("attempt_single_target")
    if (
        attempt.budget.max_wall_time_s is not None
        and plan.total_timeout_s > attempt.budget.max_wall_time_s
    ):
        mismatches.append("attempt_wall_time_budget")
    if (
        attempt.budget.max_cost_microusd is not None
        and plan.max_cost_microusd > attempt.budget.max_cost_microusd
    ):
        mismatches.append("attempt_cost_budget")
    # ResourceBudget.max_tokens accounts for input + output.  num_predict is
    # only an output ceiling, so accepting it alone could consume the whole
    # budget before the non-empty prompt is counted.  num_ctx is the frozen
    # total context ceiling and is therefore the conservative pre-call bound.
    if (
        attempt.budget.max_tokens is not None
        and plan.num_ctx > attempt.budget.max_tokens
    ):
        mismatches.append("attempt_token_budget")

    # RunnerContext-derived allocation identity and content observations.  No
    # caller-authored digest bag is accepted here: all three inputs are the
    # canonical contracts captured by the observation seam.
    exact(
        "workspace_attestation_sha256",
        workspace_attestation.digest,
        plan.workspace_attestation_sha256,
    )
    exact(
        "workspace_spine_intent_id",
        workspace_attestation.spine_intent_id,
        plan.spine_intent_id,
    )
    exact(
        "workspace_spine_intent_sha256",
        workspace_attestation.spine_intent_sha256,
        plan.spine_intent_sha256,
    )
    exact("workspace_id", workspace_attestation.workspace_id, plan.workspace_id)
    exact(
        "workspace_source_revision",
        workspace_attestation.source_revision,
        plan.source_revision,
    )
    exact("workspace_task_id", workspace_attestation.task_id, plan.task_id)
    exact("workspace_task_sha256", workspace_attestation.task_sha256, plan.task_sha256)

    exact(
        "workspace_observation_sha256",
        workspace_observation.digest,
        plan.workspace_observation_sha256,
    )
    exact(
        "observation_workspace_id",
        workspace_observation.workspace_id,
        plan.workspace_id,
    )
    exact(
        "observation_workspace_attestation_sha256",
        workspace_observation.workspace_attestation_sha256,
        workspace_attestation.digest,
    )
    exact(
        "observation_source_revision",
        workspace_observation.source_revision,
        plan.source_revision,
    )
    exact(
        "workspace_base_source_artifact_sha256",
        workspace_observation.base_source_artifact_sha256,
        plan.base_source_artifact_sha256,
    )
    exact(
        "observation_target_before_sha256",
        workspace_observation.target_before_observation_sha256,
        target_before.digest,
    )

    exact(
        "target_workspace_attestation_sha256",
        target_before.workspace_attestation_sha256,
        workspace_attestation.digest,
    )
    exact("target_source_revision", target_before.source_revision, plan.source_revision)
    exact("workspace_target_path", target_before.target_path, plan.target_path)
    exact("workspace_target_kind", target_before.target_kind, plan.target_kind)
    exact(
        "workspace_target_before_sha256",
        target_before.content_sha256,
        plan.target_before_sha256,
    )
    exact(
        "workspace_target_before_size",
        target_before.byte_length,
        plan.target_before_size,
    )
    exact(
        "workspace_target_git_mode",
        target_before.git_mode,
        plan.target_git_mode,
    )

    # Symbolic verifier id -> runtime manifest -> exact host executable bytes.
    exact(
        "runtime_tool_binding_sha256",
        runtime_tool_binding.digest,
        plan.runtime_tool_binding_sha256,
    )
    exact("runtime_tool_id", runtime_tool_binding.tool_id, plan.verifier_argv[0])
    exact(
        "runtime_tool_manifest_sha256",
        runtime_tool_binding.runtime_manifest_sha256,
        plan.runtime_manifest_sha256,
    )
    exact(
        "runtime_tool_source_revision",
        runtime_tool_binding.source_revision,
        plan.source_revision,
    )

    # The effect-policy subject is the request that explicitly carries the
    # complete plan digest, avoiding a Plan -> Policy -> Request -> Plan cycle.
    exact("request_entrypoint", request.entrypoint_id, "python.offload")
    exact("request_mission_id", request.mission_id, attempt.mission_id)
    exact("request_attempt_id", request.attempt_id, attempt.attempt_id)
    exact(
        "request_source_revision",
        request.provenance.source_revision,
        plan.source_revision,
    )
    exact("request_execution_plan_sha256", request.execution_plan_sha256, plan.digest)
    if plan.digest not in request.provenance.input_digests:
        mismatches.append("request_plan_provenance")

    # Lease/policy byte identity. Signature, expiry, registry freshness,
    # durable grant identity, and replay remain in the Effect Lease authority.
    exact("lease_request_id", lease.request_id, request.request_id)
    exact("lease_request_sha256", lease.request_sha256, request.digest)
    exact("lease_entrypoint", lease.entrypoint_id, request.entrypoint_id)
    exact(
        "lease_idempotency_namespace",
        lease.idempotency_namespace,
        request.idempotency_namespace,
    )
    exact(
        "request_idempotency_namespace",
        request.idempotency_namespace,
        f"{attempt.mission_id}/{attempt.attempt_id}",
    )
    exact(
        "lease_source_revision",
        lease.provenance.source_revision,
        request.provenance.source_revision,
    )
    exact("policy_subject_id", policy.subject_id, request.request_id)
    exact("policy_subject_sha256", policy.subject_sha256, request.digest)
    exact("policy_verdict", policy.verdict, "allow")
    exact(
        "policy_source_revision",
        policy.provenance.source_revision,
        request.provenance.source_revision,
    )
    exact("lease_policy_decision_id", lease.policy_decision_id, policy.decision_id)
    exact("lease_policy_decision_sha256", lease.policy_decision_sha256, policy.digest)

    exact("lease_runtime_id", lease.runtime_id, plan.runtime_id)
    exact(
        "request_runtime_manifest_sha256",
        request.runtime_manifest_sha256,
        plan.runtime_manifest_sha256,
    )
    exact(
        "request_runtime_conformance_sha256",
        request.runtime_conformance_sha256,
        plan.runtime_conformance_sha256,
    )
    exact(
        "lease_runtime_manifest_sha256",
        lease.runtime_manifest_sha256,
        plan.runtime_manifest_sha256,
    )
    exact(
        "lease_runtime_conformance_sha256",
        lease.runtime_conformance_sha256,
        plan.runtime_conformance_sha256,
    )

    # This single-call path accepts neither widening nor narrowing.
    exact("request_effects", request.requested_effects, plan.requested_effects)
    exact("lease_effects", lease.requested_effects, plan.requested_effects)
    exact("execution_effects", execution.requested_effects, plan.requested_effects)
    exact("request_effect_scope", request.effect_scope, scope)
    exact("lease_effect_scope", lease.effect_scope, scope)
    exact("policy_effect_scope", policy.effect_scope, scope)
    exact("execution_writable_paths", execution.writable_paths, scope.writable_paths)
    exact("execution_egress_endpoints", execution.egress_endpoints, scope.egress_endpoints)
    exact("execution_tools", execution.tools, scope.tools)
    exact("execution_secret_refs", execution.secret_refs, scope.secret_refs)
    exact(
        "execution_max_cost_microusd",
        execution.max_cost_microusd,
        scope.max_cost_microusd,
    )
    exact("execution_kill_switch_ref", execution.kill_switch_ref, scope.kill_switch_ref)

    exact(
        "request_kill_switch_generation",
        request.kill_switch_generation,
        plan.kill_switch_generation,
    )
    exact(
        "lease_kill_switch_generation",
        lease.kill_switch_generation,
        plan.kill_switch_generation,
    )
    exact(
        "execution_kill_switch_generation",
        execution.kill_switch_generation,
        plan.kill_switch_generation,
    )
    exact(
        "authorization_kill_switch_generation",
        authorization.current_kill_switch_generation,
        plan.kill_switch_generation,
    )

    expected_execution_id, expected_idempotency_key = derive_offload_execution_ids(plan)
    exact("execution_id", execution.execution_id, expected_execution_id)
    exact("idempotency_key", execution.idempotency_key, expected_idempotency_key)
    exact("execution_execution_plan_sha256", execution.execution_plan_sha256, plan.digest)
    return mismatches


@dataclass(frozen=True)
class AuthorizedOffloadExecution:
    """An inert, exact binding of one plan to one leased execution request."""

    plan: OffloadExecutionPlan
    attempt: AttemptContract
    workspace_attestation: TaskAttemptWorkspaceAttestation
    target_before: TargetBeforeObservation
    workspace_observation: OffloadWorkspaceObservation
    runtime_tool_binding: RuntimeToolBinding
    authorization: LeasedEffectAuthorization
    execution: EffectExecutionRequest

    def __post_init__(self) -> None:
        expected_types = (
            ("plan", self.plan, OffloadExecutionPlan),
            ("attempt", self.attempt, AttemptContract),
            (
                "workspace_attestation",
                self.workspace_attestation,
                TaskAttemptWorkspaceAttestation,
            ),
            ("target_before", self.target_before, TargetBeforeObservation),
            (
                "workspace_observation",
                self.workspace_observation,
                OffloadWorkspaceObservation,
            ),
            ("runtime_tool_binding", self.runtime_tool_binding, RuntimeToolBinding),
            ("authorization", self.authorization, LeasedEffectAuthorization),
            ("execution", self.execution, EffectExecutionRequest),
        )
        wrong = [
            name
            for name, value, expected in expected_types
            if not isinstance(value, expected)
        ]
        if wrong:
            raise OffloadAuthorityBindingError(
                "offload authority requires canonical contract type(s): "
                + ", ".join(wrong)
            )
        mismatches = _mismatches(
            self.plan,
            self.attempt,
            self.workspace_attestation,
            self.target_before,
            self.workspace_observation,
            self.runtime_tool_binding,
            self.authorization,
            self.execution,
        )
        if mismatches:
            raise OffloadAuthorityBindingError(
                "offload authority binding mismatch: "
                + ", ".join(sorted(set(mismatches)))
            )


def authorize_offload_execution(
    *,
    plan: OffloadExecutionPlan,
    attempt: AttemptContract,
    workspace_attestation: TaskAttemptWorkspaceAttestation,
    target_before: TargetBeforeObservation,
    workspace_observation: OffloadWorkspaceObservation,
    runtime_tool_binding: RuntimeToolBinding,
    authorization: LeasedEffectAuthorization,
    execution: EffectExecutionRequest,
) -> AuthorizedOffloadExecution:
    """Bind canonical inputs without minting, persisting, or consuming them."""

    return AuthorizedOffloadExecution(
        plan=plan,
        attempt=attempt,
        workspace_attestation=workspace_attestation,
        target_before=target_before,
        workspace_observation=workspace_observation,
        runtime_tool_binding=runtime_tool_binding,
        authorization=authorization,
        execution=execution,
    )


__all__ = [
    "AuthorizedOffloadExecution",
    "OFFLOAD_OPERATION",
    "OffloadAuthorityBindingError",
    "authorize_offload_execution",
    "derive_offload_execution_ids",
]
