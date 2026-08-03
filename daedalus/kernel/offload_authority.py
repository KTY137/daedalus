"""Pure Gate-0 binding for one already-authorized Ollama offload.

This module does not issue leases, verify signatures, persist grants, consume a
lease, or invoke a provider.  It only proves that the canonical attempt, frozen
offload plan, signed lease bundle, and narrowed execution request all describe
the same single effect.  Cryptographic and durable start authority remains in
``verify_effect_lease`` and ``EffectLeaseLedger.begin``.
"""
from __future__ import annotations

from dataclasses import dataclass

from daedalus.kernel.contracts import OffloadExecutionPlan
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    LeasedEffectAuthorization,
)
from daedalus.schemas import AttemptContract, _sha256
from daedalus.spine.envelope import canonical_sha


class OffloadAuthorityBindingError(ValueError):
    """Fail-closed refusal before any offload-side effect is consumed."""


def derive_offload_execution_ids(
    execution_plan_sha256: str,
) -> tuple[str, str]:
    """Return the sole execution/idempotency identity for one plan digest.

    Domain-separated digests keep the two identifiers distinct while making
    both functions solely of the immutable plan.  Consequently, a second lease
    for the same plan still collides with the first execution in the canonical
    effect ledger instead of creating another provider call identity.
    """

    plan_sha = _sha256(execution_plan_sha256, "execution_plan_sha256")
    execution_sha = canonical_sha(
        {
            "domain": "daedalus.offload-execution-id/1",
            "execution_plan_sha256": plan_sha,
        }
    )
    idempotency_sha = canonical_sha(
        {
            "domain": "daedalus.offload-idempotency-key/1",
            "execution_plan_sha256": plan_sha,
        }
    )
    return (
        f"offload-execution:{execution_sha}",
        f"offload-idempotency:{idempotency_sha}",
    )


def _mismatches(
    plan: OffloadExecutionPlan,
    attempt: AttemptContract,
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

    # The plan is downstream of, and must retain, the exact canonical attempt.
    exact("attempt_contract_sha256", plan.attempt_contract_sha256, attempt.digest)
    # ``worktree_id`` names the concrete TaskAttempt workspace (today its
    # randomized branch/effect key), not the logical AttemptContract id.  This
    # value is protected by the plan/request/lease digest chain, but this pure
    # binder has no RunnerContext from which to verify it.  The execution seam
    # must compare it with ``RunnerContext.branch`` before consuming the lease.
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
    exact("attempt_writable_paths", plan.target_paths, attempt.writable_paths)
    if len(attempt.writable_paths) != 1:
        mismatches.append("attempt_single_target")
    if (
        attempt.budget.max_wall_time_s is not None
        and plan.timeout_s > attempt.budget.max_wall_time_s
    ):
        mismatches.append("attempt_wall_time_budget")
    if (
        attempt.budget.max_cost_microusd is not None
        and plan.max_cost_microusd > attempt.budget.max_cost_microusd
    ):
        mismatches.append("attempt_cost_budget")

    # The effect-policy subject is the request that explicitly contains the
    # plan digest.  This keeps the pre-policy plan free of a hash cycle.
    exact("request_entrypoint", request.entrypoint_id, "python.offload")
    exact("request_mission_id", request.mission_id, attempt.mission_id)
    exact("request_attempt_id", request.attempt_id, attempt.attempt_id)
    exact(
        "request_source_revision",
        request.provenance.source_revision,
        plan.source_revision,
    )
    exact(
        "request_execution_plan_sha256",
        request.execution_plan_sha256,
        plan.digest,
    )
    if plan.digest not in request.provenance.input_digests:
        mismatches.append("request_plan_provenance")

    # The lease and policy must name the exact request bytes.  Signature,
    # expiry, registry freshness, persisted-grant identity, and replay remain
    # deliberately delegated to the existing Effect Lease authority.
    exact("lease_request_id", lease.request_id, request.request_id)
    exact("lease_request_sha256", lease.request_sha256, request.digest)
    exact("lease_entrypoint", lease.entrypoint_id, request.entrypoint_id)
    exact(
        "lease_idempotency_namespace",
        lease.idempotency_namespace,
        request.idempotency_namespace,
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
    exact(
        "lease_policy_decision_sha256",
        lease.policy_decision_sha256,
        policy.digest,
    )

    # Gate-0 supports only the pinned Ollama HTTP runtime for this plan type.
    exact("lease_runtime_id", lease.runtime_id, "ollama_http")
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

    # No subset or widening is accepted at this binder.  The generic lease
    # implementation may support narrowing; this single-call plan intentionally
    # binds the complete effects and scope end to end.
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

    expected_execution_id, expected_idempotency_key = derive_offload_execution_ids(
        plan.digest
    )
    exact("execution_id", execution.execution_id, expected_execution_id)
    exact("idempotency_key", execution.idempotency_key, expected_idempotency_key)
    exact(
        "execution_execution_plan_sha256",
        execution.execution_plan_sha256,
        plan.digest,
    )
    return mismatches


@dataclass(frozen=True)
class AuthorizedOffloadExecution:
    """An inert, exact binding of one plan to one leased execution request."""

    plan: OffloadExecutionPlan
    attempt: AttemptContract
    authorization: LeasedEffectAuthorization
    execution: EffectExecutionRequest

    def __post_init__(self) -> None:
        expected_types = (
            ("plan", self.plan, OffloadExecutionPlan),
            ("attempt", self.attempt, AttemptContract),
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
    authorization: LeasedEffectAuthorization,
    execution: EffectExecutionRequest,
) -> AuthorizedOffloadExecution:
    """Bind canonical inputs without minting, persisting, or consuming them."""

    return AuthorizedOffloadExecution(
        plan=plan,
        attempt=attempt,
        authorization=authorization,
        execution=execution,
    )


__all__ = [
    "AuthorizedOffloadExecution",
    "OffloadAuthorityBindingError",
    "authorize_offload_execution",
    "derive_offload_execution_ids",
]
