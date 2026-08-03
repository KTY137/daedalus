from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel import (
    OFFLOAD_EXECUTION_EFFECTS,
    AuthorizedOffloadExecution,
    EffectExecutionRequest,
    EffectLeaseRequest,
    LeasedEffectAuthorization,
    OffloadAuthorityBindingError,
    OffloadExecutionPlan,
    authorize_offload_execution,
    derive_offload_execution_ids,
    issue_effect_lease,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    ResourceBudget,
)
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision


REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc)
SECRET = b"offload-authority-test-secret-material-32-bytes"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class _NoEffectLedger:
    """A tripwire proving that the binder neither starts nor finishes work."""

    calls = 0

    def begin(self, *args, **kwargs):  # pragma: no cover - a call fails the test
        self.calls += 1
        raise AssertionError("pure offload binder called ledger.begin")

    def finish(self, *args, **kwargs):  # pragma: no cover - a call fails the test
        self.calls += 1
        raise AssertionError("pure offload binder called ledger.finish")


@dataclass(frozen=True)
class _Parts:
    plan: OffloadExecutionPlan
    attempt: AttemptContract
    authorization: LeasedEffectAuthorization
    execution: EffectExecutionRequest
    ledger: _NoEffectLedger


def _attempt() -> AttemptContract:
    task_sha = _sha("task")
    runtime_sha = _sha("ollama-runtime-manifest")
    policy_sha = _sha("attempt-policy")
    return AttemptContract(
        attempt_id="attempt-1",
        mission_id="mission-1",
        task_id="task-1",
        instruction="Repair the bounded target.",
        base_revision=REVISION,
        task_sha256=task_sha,
        runtime_manifest_sha256=runtime_sha,
        policy_decision_sha256=policy_sha,
        budget=ResourceBudget(
            max_cost_microusd=0,
            max_wall_time_s=120,
            max_attempts=1,
        ),
        provenance=ContractProvenance(
            origin="tests.offload-authority-attempt",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(task_sha, runtime_sha, policy_sha),
            trace_id="mission-1",
        ),
        writable_paths=("src/package/module.py",),
        gate_names=("command",),
    )


def _plan(attempt: AttemptContract) -> OffloadExecutionPlan:
    digests = {
        "intent_sha256": _sha("spine-intent"),
        "attempt_contract_sha256": attempt.digest,
        "task_sha256": attempt.task_sha256,
        "source_artifact_sha256": _sha("source-artifact"),
        "worktree_fingerprint_sha256": _sha("worktree-fingerprint"),
        "model_sha256": _sha("ollama-model"),
        "attempt_policy_decision_sha256": attempt.policy_decision_sha256,
        "availability_sha256": _sha("availability"),
        "routing_index_sha256": _sha("routing-index"),
        "routing_decision_sha256": _sha("routing-decision"),
        "runtime_manifest_sha256": attempt.runtime_manifest_sha256,
        "runtime_conformance_sha256": _sha("runtime-conformance"),
    }
    scope = EffectScope(
        read_only=False,
        writable_paths=attempt.writable_paths,
        egress_endpoints=("http://127.0.0.1:11434",),
        tools=("python",),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref="mission-1-kill",
    )
    return OffloadExecutionPlan(
        plan_id="offload-plan-1",
        spine_intent_id=1,
        **digests,
        task_id=attempt.task_id,
        source_revision=attempt.base_revision,
        # Concrete TaskAttempt branch/effect key, deliberately distinct from
        # the logical AttemptContract id.
        worktree_id="task-attempt-task-1-deadbeef-a1b2c3",
        provider_id="ollama",
        model_id="qwen2.5-coder:7b",
        provider_endpoint="http://127.0.0.1:11434",
        write_mode="write",
        target_paths=attempt.writable_paths,
        requested_effects=OFFLOAD_EXECUTION_EFFECTS,
        effect_scope=scope,
        kill_switch_generation=3,
        max_model_calls=1,
        timeout_s=120,
        max_cost_microusd=0,
        tool_argv=("python", "-m", "daedalus.tools.vet"),
        verifier_argv=("python", "-m", "pytest", "-q", "tests/test_module.py"),
        metrics_enabled=False,
        drafts_enabled=False,
        auto_mint_enabled=False,
        provenance=ContractProvenance(
            origin="tests.offload-authority-plan",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=tuple(digests.values()),
            trace_id=attempt.mission_id,
        ),
    )


def _parts() -> _Parts:
    attempt = _attempt()
    plan = _plan(attempt)
    request = EffectLeaseRequest(
        request_id="offload-request-1",
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        entrypoint_id="python.offload",
        requested_effects=plan.requested_effects,
        effect_scope=plan.effect_scope,
        idempotency_namespace="mission-1/attempt-1",
        kill_switch_generation=plan.kill_switch_generation,
        runtime_manifest_sha256=plan.runtime_manifest_sha256,
        runtime_conformance_sha256=plan.runtime_conformance_sha256,
        execution_plan_sha256=plan.digest,
        provenance=ContractProvenance(
            origin="tests.offload-authority-request",
            source_revision=plan.source_revision,
            created_at=NOW.isoformat(),
            input_digests=(
                plan.digest,
                plan.runtime_manifest_sha256,
                plan.runtime_conformance_sha256,
            ),
            trace_id=attempt.mission_id,
        ),
    )
    policy_sha = _sha("effect-policy")
    policy = PolicyDecision(
        decision_id="effect-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=policy_sha,
        verdict="allow",
        reasons=("exact bounded Ollama offload",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.offload-authority-policy",
            source_revision=request.provenance.source_revision,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, policy_sha),
            trace_id=attempt.mission_id,
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="offload-lease-1",
        issuer_key_id="kernel-key-1",
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
    )
    ledger = _NoEffectLedger()
    spec = REGISTRY_BY_ID["python.offload"]
    authorization = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,  # type: ignore[arg-type] -- intentional inert tripwire
        keyring={"kernel-key-1": SECRET},
        guard_decisions=tuple(
            GuardDecision(
                contract=contract,
                allowed=True,
                evidence=f"artifact-locator:sha256:{_sha(contract)}",
            )
            for contract in spec.guard_contracts
        ),
        current_kill_switch_generation=plan.kill_switch_generation,
    )
    execution_id, idempotency_key = derive_offload_execution_ids(plan.digest)
    execution = EffectExecutionRequest(
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        requested_effects=plan.requested_effects,
        writable_paths=plan.effect_scope.writable_paths,
        egress_endpoints=plan.effect_scope.egress_endpoints,
        tools=plan.effect_scope.tools,
        secret_refs=plan.effect_scope.secret_refs,
        max_cost_microusd=plan.max_cost_microusd,
        kill_switch_ref=plan.effect_scope.kill_switch_ref,
        kill_switch_generation=plan.kill_switch_generation,
        execution_plan_sha256=plan.digest,
    )
    return _Parts(plan, attempt, authorization, execution, ledger)


def _replace_provenance_input(
    provenance: ContractProvenance, old: str, new: str
) -> ContractProvenance:
    return dataclasses.replace(
        provenance,
        input_digests=tuple(new if value == old else value for value in provenance.input_digests),
    )


def _replace_plan_digest(
    plan: OffloadExecutionPlan, field: str, label: str
) -> OffloadExecutionPlan:
    old = getattr(plan, field)
    new = _sha(label)
    return dataclasses.replace(
        plan,
        **{field: new},
        provenance=_replace_provenance_input(plan.provenance, old, new),
    )


def _replace_lease_digest(parts: _Parts, field: str, label: str) -> _Parts:
    lease = parts.authorization.lease
    old = getattr(lease, field)
    new = _sha(label)
    changed = dataclasses.replace(
        lease,
        **{field: new},
        provenance=_replace_provenance_input(lease.provenance, old, new),
    )
    return dataclasses.replace(
        parts,
        authorization=dataclasses.replace(parts.authorization, lease=changed),
    )


def _with_request(parts: _Parts, request: EffectLeaseRequest) -> _Parts:
    return dataclasses.replace(
        parts,
        authorization=dataclasses.replace(parts.authorization, request=request),
    )


def _tamper(parts: _Parts, case: str) -> _Parts:
    plan = parts.plan
    attempt = parts.attempt
    auth = parts.authorization
    request = auth.request
    policy = auth.policy_decision
    execution = parts.execution

    if case == "attempt_contract":
        return dataclasses.replace(
            parts, plan=_replace_plan_digest(plan, "attempt_contract_sha256", case)
        )
    if case == "worktree_plan_digest":
        return dataclasses.replace(
            parts,
            plan=dataclasses.replace(plan, worktree_id="task-attempt-other-branch"),
        )
    if case == "task_id":
        return dataclasses.replace(parts, plan=dataclasses.replace(plan, task_id="task-2"))
    if case == "task_sha":
        return dataclasses.replace(
            parts, plan=_replace_plan_digest(plan, "task_sha256", case)
        )
    if case == "attempt_policy":
        return dataclasses.replace(
            parts,
            plan=_replace_plan_digest(plan, "attempt_policy_decision_sha256", case),
        )
    if case == "attempt_runtime":
        return dataclasses.replace(
            parts, plan=_replace_plan_digest(plan, "runtime_manifest_sha256", case)
        )
    if case == "attempt_targets":
        changed_attempt = dataclasses.replace(
            attempt,
            writable_paths=("src/package/module.py", "src/package/other.py"),
        )
        changed_plan = dataclasses.replace(
            plan,
            attempt_contract_sha256=changed_attempt.digest,
            provenance=_replace_provenance_input(
                plan.provenance, attempt.digest, changed_attempt.digest
            ),
        )
        return dataclasses.replace(parts, attempt=changed_attempt, plan=changed_plan)
    if case == "attempt_wall_time_budget":
        changed_attempt = dataclasses.replace(
            attempt,
            budget=dataclasses.replace(attempt.budget, max_wall_time_s=119),
        )
        changed_plan = dataclasses.replace(
            plan,
            attempt_contract_sha256=changed_attempt.digest,
            provenance=_replace_provenance_input(
                plan.provenance, attempt.digest, changed_attempt.digest
            ),
        )
        changed_request = dataclasses.replace(
            request,
            execution_plan_sha256=changed_plan.digest,
            provenance=_replace_provenance_input(
                request.provenance, plan.digest, changed_plan.digest
            ),
        )
        # Rebind every downstream digest so only the semantic budget ceiling
        # can make the otherwise self-consistent bundle fail.
        changed_policy = dataclasses.replace(
            policy,
            subject_sha256=changed_request.digest,
            provenance=_replace_provenance_input(
                policy.provenance, request.digest, changed_request.digest
            ),
        )
        changed_lease = dataclasses.replace(
            auth.lease,
            request_sha256=changed_request.digest,
            policy_decision_sha256=changed_policy.digest,
            provenance=dataclasses.replace(
                auth.lease.provenance,
                input_digests=tuple(
                    changed_request.digest
                    if value == request.digest
                    else changed_policy.digest
                    if value == policy.digest
                    else value
                    for value in auth.lease.provenance.input_digests
                ),
            ),
        )
        return dataclasses.replace(
            parts,
            plan=changed_plan,
            attempt=changed_attempt,
            authorization=dataclasses.replace(
                auth,
                request=changed_request,
                policy_decision=changed_policy,
                lease=changed_lease,
            ),
            execution=dataclasses.replace(
                execution, execution_plan_sha256=changed_plan.digest
            ),
        )
    if case == "request_entrypoint":
        changed_request = dataclasses.replace(request, entrypoint_id="python.other")
        changed_lease = dataclasses.replace(auth.lease, entrypoint_id="python.other")
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(
                auth, request=changed_request, lease=changed_lease
            ),
        )
    if case == "request_mission":
        return _with_request(parts, dataclasses.replace(request, mission_id="mission-2"))
    if case == "request_attempt":
        return _with_request(parts, dataclasses.replace(request, attempt_id="attempt-2"))
    if case == "request_revision":
        changed_provenance = dataclasses.replace(
            request.provenance, source_revision="b" * 40
        )
        return _with_request(
            parts, dataclasses.replace(request, provenance=changed_provenance)
        )
    if case == "request_plan":
        changed_plan_sha = _sha("other-plan")
        changed_request = dataclasses.replace(
            request,
            execution_plan_sha256=changed_plan_sha,
            provenance=_replace_provenance_input(
                request.provenance, plan.digest, changed_plan_sha
            ),
        )
        return _with_request(parts, changed_request)
    if case == "request_plan_provenance":
        # Corrupt an otherwise frozen object to exercise the binder's own
        # defense as well as the constructor-level provenance check.
        object.__setattr__(
            request,
            "provenance",
            ContractProvenance(
                origin=request.provenance.origin,
                source_revision=request.provenance.source_revision,
                created_at=request.provenance.created_at,
                input_digests=(
                    plan.runtime_manifest_sha256,
                    plan.runtime_conformance_sha256,
                ),
                trace_id=request.provenance.trace_id,
            ),
        )
        return parts
    if case == "request_runtime_conformance":
        old = request.runtime_conformance_sha256
        new = _sha(case)
        changed_request = dataclasses.replace(
            request,
            runtime_conformance_sha256=new,
            provenance=_replace_provenance_input(request.provenance, old, new),
        )
        return _with_request(parts, changed_request)
    if case == "lease_request_sha":
        return _replace_lease_digest(parts, "request_sha256", case)
    if case == "lease_revision":
        changed_lease = dataclasses.replace(
            auth.lease,
            provenance=dataclasses.replace(
                auth.lease.provenance, source_revision="b" * 40
            ),
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, lease=changed_lease),
        )
    if case == "lease_policy_sha":
        return _replace_lease_digest(parts, "policy_decision_sha256", case)
    if case == "policy_subject":
        other_request_sha = _sha(case)
        changed_policy = dataclasses.replace(
            policy,
            subject_sha256=other_request_sha,
            provenance=_replace_provenance_input(
                policy.provenance, request.digest, other_request_sha
            ),
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, policy_decision=changed_policy),
        )
    if case == "policy_verdict":
        changed_policy = dataclasses.replace(
            policy, verdict="deny", effect_scope=EffectScope()
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, policy_decision=changed_policy),
        )
    if case == "lease_runtime_id":
        changed_lease = dataclasses.replace(auth.lease, runtime_id="other-runtime")
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, lease=changed_lease),
        )
    if case == "lease_runtime_manifest":
        old = auth.lease.runtime_manifest_sha256
        new = _sha(case)
        changed_lease = dataclasses.replace(
            auth.lease,
            runtime_manifest_sha256=new,
            provenance=_replace_provenance_input(auth.lease.provenance, old, new),
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, lease=changed_lease),
        )
    if case == "request_effects":
        changed = dataclasses.replace(
            request,
            requested_effects=("filesystem_write", "network_egress"),
        )
        return _with_request(parts, changed)
    if case == "lease_effects":
        changed = dataclasses.replace(
            auth.lease,
            requested_effects=("filesystem_write", "network_egress"),
        )
        return dataclasses.replace(
            parts, authorization=dataclasses.replace(auth, lease=changed)
        )
    if case == "request_scope":
        changed_scope = dataclasses.replace(plan.effect_scope, timeout_s=119)
        return _with_request(
            parts, dataclasses.replace(request, effect_scope=changed_scope)
        )
    if case == "execution_scope":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(
                execution, writable_paths=("src/package/other.py",)
            ),
        )
    if case == "request_generation":
        return _with_request(
            parts,
            dataclasses.replace(request, kill_switch_generation=2),
        )
    if case == "execution_generation":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, kill_switch_generation=2),
        )
    if case == "authorization_generation":
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(
                auth, current_kill_switch_generation=2
            ),
        )
    if case == "execution_plan":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(
                execution, execution_plan_sha256=_sha("other-execution-plan")
            ),
        )
    if case == "execution_id":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, execution_id="offload-execution:other"),
        )
    if case == "idempotency_key":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(
                execution, idempotency_key="offload-idempotency:other"
            ),
        )
    raise AssertionError(f"unknown tamper case: {case}")


def test_authorized_offload_execution_is_inert_frozen_and_exact() -> None:
    parts = _parts()

    bound = authorize_offload_execution(
        plan=parts.plan,
        attempt=parts.attempt,
        authorization=parts.authorization,
        execution=parts.execution,
    )

    assert bound == AuthorizedOffloadExecution(
        parts.plan, parts.attempt, parts.authorization, parts.execution
    )
    assert parts.ledger.calls == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        bound.plan = dataclasses.replace(parts.plan, plan_id="other")  # type: ignore[misc]


def test_execution_identity_is_domain_separated_and_plan_deterministic() -> None:
    plan = _parts().plan
    first = derive_offload_execution_ids(plan.digest)
    second = derive_offload_execution_ids(plan.digest)
    changed = dataclasses.replace(plan, plan_id="offload-plan-2")

    assert first == second
    assert first[0] != first[1]
    assert derive_offload_execution_ids(changed.digest) != first


@pytest.mark.parametrize(
    ("case", "error"),
    (
        ("attempt_contract", "attempt_contract_sha256"),
        ("worktree_plan_digest", "request_execution_plan_sha256"),
        ("task_id", "task_id"),
        ("task_sha", "task_sha256"),
        ("attempt_policy", "attempt_policy_decision_sha256"),
        ("attempt_runtime", "attempt_runtime_manifest_sha256"),
        ("attempt_targets", "attempt_writable_paths"),
        ("attempt_wall_time_budget", "attempt_wall_time_budget"),
        ("request_entrypoint", "request_entrypoint"),
        ("request_mission", "request_mission_id"),
        ("request_attempt", "request_attempt_id"),
        ("request_revision", "request_source_revision"),
        ("request_plan", "request_execution_plan_sha256"),
        ("request_plan_provenance", "request_plan_provenance"),
        ("request_runtime_conformance", "request_runtime_conformance_sha256"),
        ("lease_request_sha", "lease_request_sha256"),
        ("lease_revision", "lease_source_revision"),
        ("lease_policy_sha", "lease_policy_decision_sha256"),
        ("policy_subject", "policy_subject_sha256"),
        ("policy_verdict", "policy_verdict"),
        ("lease_runtime_id", "lease_runtime_id"),
        ("lease_runtime_manifest", "lease_runtime_manifest_sha256"),
        ("request_effects", "request_effects"),
        ("lease_effects", "lease_effects"),
        ("request_scope", "request_effect_scope"),
        ("execution_scope", "execution_writable_paths"),
        ("request_generation", "request_kill_switch_generation"),
        ("execution_generation", "execution_kill_switch_generation"),
        ("authorization_generation", "authorization_kill_switch_generation"),
        ("execution_plan", "execution_execution_plan_sha256"),
        ("execution_id", "execution_id"),
        ("idempotency_key", "idempotency_key"),
    ),
)
def test_contract_tampering_fails_closed(case: str, error: str) -> None:
    parts = _tamper(_parts(), case)

    with pytest.raises(OffloadAuthorityBindingError, match=error):
        authorize_offload_execution(
            plan=parts.plan,
            attempt=parts.attempt,
            authorization=parts.authorization,
            execution=parts.execution,
        )

    assert parts.ledger.calls == 0
