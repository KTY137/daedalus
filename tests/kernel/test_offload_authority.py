from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.contracts import (
    OFFLOAD_EXECUTION_EFFECTS,
    EffectLeaseRequest,
    OffloadExecutionPlan,
    derive_offload_recovery_path,
    derive_offload_staging_path,
    offload_recovery_path_sha256,
    offload_staging_path_sha256,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    LeasedEffectAuthorization,
    issue_effect_lease,
)
from daedalus.kernel.offload_authority import (
    AuthorizedOffloadExecution,
    OffloadAuthorityBindingError,
    authorize_offload_execution,
    derive_offload_execution_ids,
)
from daedalus.kernel.offload_observations import (
    OffloadWorkspaceObservation,
    TargetBeforeObservation,
    TaskAttemptWorkspaceAttestation,
    _filesystem_mode_sha256,
)
from daedalus.kernel.runtime_tools import RuntimeToolBinding
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
TARGET = "src/package/module.py"
TOOL_ID = "python.test-runner"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class _NoEffectLedger:
    """Tripwire proving that the authority binder remains purely inert."""

    calls = 0

    def begin(self, *args, **kwargs):  # pragma: no cover - any call fails
        self.calls += 1
        raise AssertionError("pure offload binder called ledger.begin")

    def finish(self, *args, **kwargs):  # pragma: no cover - any call fails
        self.calls += 1
        raise AssertionError("pure offload binder called ledger.finish")


@dataclass(frozen=True)
class _Parts:
    plan: OffloadExecutionPlan
    attempt: AttemptContract
    workspace_attestation: TaskAttemptWorkspaceAttestation
    target_before: TargetBeforeObservation
    workspace_observation: OffloadWorkspaceObservation
    runtime_tool_binding: RuntimeToolBinding
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
            max_tokens=8192,
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
        writable_paths=(TARGET,),
        gate_names=("command",),
    )


def _runtime_tool_binding(attempt: AttemptContract) -> RuntimeToolBinding:
    executable_sha = _sha("exact-python-test-runner-bytes")
    executable_path_sha = _sha("exact-python-test-runner-path")
    return RuntimeToolBinding(
        tool_id=TOOL_ID,
        runtime_manifest_sha256=attempt.runtime_manifest_sha256,
        source_revision=attempt.base_revision,
        executable_sha256=executable_sha,
        executable_size=123456,
        executable_path_sha256=executable_path_sha,
        provenance=ContractProvenance(
            origin="tests.offload-authority-tool",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=(
                attempt.runtime_manifest_sha256,
                executable_sha,
                executable_path_sha,
            ),
            trace_id=attempt.mission_id,
        ),
    )


def _replace_provenance_input(
    provenance: ContractProvenance, old: str, new: str
) -> ContractProvenance:
    return dataclasses.replace(
        provenance,
        input_digests=tuple(
            new if value == old else value for value in provenance.input_digests
        ),
    )


def _observations(
    attempt: AttemptContract,
) -> tuple[
    TaskAttemptWorkspaceAttestation,
    TargetBeforeObservation,
    OffloadWorkspaceObservation,
]:
    attestation_inputs = tuple(
        _sha(label)
        for label in (
            "spine-intent",
            "task",
            "workspace-path",
            "worktree-root-path",
            "primary-checkout-path",
            "workspace-identity",
            "primary-checkout-identity",
            "git-admin-identity",
            "reach-chain",
            "allocation-record",
        )
    )
    attestation = TaskAttemptWorkspaceAttestation(
        workspace_id="task-attempt-task-1-deadbeef-a1b2c3",
        spine_intent_id=1,
        spine_intent_sha256=attestation_inputs[0],
        task_id=attempt.task_id,
        task_sha256=attempt.task_sha256,
        source_revision=attempt.base_revision,
        branch="daedalus-attempt-task-1-deadbeef-a1b2c3",
        workspace_path_sha256=attestation_inputs[2],
        worktree_root_path_sha256=attestation_inputs[3],
        primary_checkout_path_sha256=attestation_inputs[4],
        workspace_identity_sha256=attestation_inputs[5],
        primary_checkout_identity_sha256=attestation_inputs[6],
        git_admin_identity_sha256=attestation_inputs[7],
        reach_chain_sha256=attestation_inputs[8],
        allocation_record_sha256=attestation_inputs[9],
        provenance=ContractProvenance(
            origin="tests.offload-authority-attestation",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=attestation_inputs,
            trace_id=attempt.mission_id,
        ),
    )
    target_inputs = (
        attestation.digest,
        _sha("target-before"),
        _sha("target-file-identity"),
        _sha("target-parent-chain"),
        _filesystem_mode_sha256(0o644),
    )
    target = TargetBeforeObservation(
        workspace_attestation_sha256=attestation.digest,
        source_revision=attempt.base_revision,
        target_path=TARGET,
        target_kind="existing-regular-utf8-file",
        content_sha256=target_inputs[1],
        byte_length=23,
        git_mode="100644",
        encoding="utf-8",
        file_identity_sha256=target_inputs[2],
        parent_chain_sha256=target_inputs[3],
        provenance=ContractProvenance(
            origin="tests.offload-authority-target",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=target_inputs,
            trace_id=attempt.mission_id,
        ),
        filesystem_mode=0o644,
    )
    workspace_inputs = (
        attestation.digest,
        _sha("base-source-artifact"),
        _sha("source-fingerprint"),
        _sha("source-fingerprint-artifact"),
        target.digest,
    )
    workspace = OffloadWorkspaceObservation(
        workspace_id=attestation.workspace_id,
        workspace_attestation_sha256=attestation.digest,
        source_revision=attempt.base_revision,
        base_source_artifact_sha256=workspace_inputs[1],
        source_fingerprint_sha256=workspace_inputs[2],
        source_fingerprint_artifact_sha256=workspace_inputs[3],
        target_before_observation_sha256=target.digest,
        provenance=ContractProvenance(
            origin="tests.offload-authority-workspace",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=workspace_inputs,
            trace_id=attempt.mission_id,
        ),
    )
    return attestation, target, workspace


def _plan(
    attempt: AttemptContract,
    runtime_tool_binding: RuntimeToolBinding,
    workspace_attestation: TaskAttemptWorkspaceAttestation,
    target_before: TargetBeforeObservation,
    workspace_observation: OffloadWorkspaceObservation,
) -> OffloadExecutionPlan:
    staging_path = derive_offload_staging_path(
        attempt_id=attempt.attempt_id,
        workspace_id=workspace_attestation.workspace_id,
        target_path=TARGET,
    )
    staging_sha = offload_staging_path_sha256(staging_path)
    recovery_path = derive_offload_recovery_path(
        attempt_id=attempt.attempt_id,
        workspace_id=workspace_attestation.workspace_id,
        target_path=TARGET,
    )
    recovery_sha = offload_recovery_path_sha256(recovery_path)
    store_root_sha = _sha("artifact-store-root")
    digests = {
        "spine_intent_sha256": _sha("spine-intent"),
        "attempt_contract_sha256": attempt.digest,
        "task_sha256": attempt.task_sha256,
        "base_source_artifact_sha256": workspace_observation.base_source_artifact_sha256,
        "workspace_attestation_sha256": workspace_attestation.digest,
        "workspace_observation_sha256": workspace_observation.digest,
        "target_before_sha256": target_before.content_sha256,
        "expected_model_sha256": _sha("ollama-model"),
        "prompt_template_sha256": _sha("prompt-template"),
        "prompt_sha256": _sha("prompt"),
        "response_schema_sha256": _sha("response-schema"),
        "ollama_request_sha256": _sha("ollama-request"),
        "attempt_policy_decision_sha256": attempt.policy_decision_sha256,
        "runtime_manifest_sha256": attempt.runtime_manifest_sha256,
        "runtime_conformance_sha256": _sha("runtime-conformance"),
        "runtime_tool_binding_sha256": runtime_tool_binding.digest,
    }
    scope = EffectScope(
        read_only=False,
        writable_paths=tuple(
            sorted((*attempt.writable_paths, staging_path, recovery_path))
        ),
        egress_endpoints=("http://127.0.0.1:11434",),
        tools=(TOOL_ID,),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref="mission-1-kill",
    )
    return OffloadExecutionPlan(
        spine_intent_id=1,
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        task_id=attempt.task_id,
        **digests,
        source_revision=attempt.base_revision,
        workspace_id=workspace_attestation.workspace_id,
        target_path=TARGET,
        target_kind="existing-regular-utf8-file",
        target_before_size=target_before.byte_length,
        target_git_mode=target_before.git_mode,
        provider_id="ollama",
        runtime_id="ollama_http",
        provider_endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5-coder:7b",
        num_ctx=8192,
        num_predict=1024,
        seed=7,
        temperature_milli=0,
        keep_alive="0",
        max_response_bytes=2_000_000,
        max_metadata_calls=1,
        max_model_calls=1,
        verifier_argv=(TOOL_ID, "-q", "tests/test_module.py"),
        verifier_timeout_s=30,
        requested_effects=OFFLOAD_EXECUTION_EFFECTS,
        effect_scope=scope,
        kill_switch_generation=3,
        total_timeout_s=120,
        max_cost_microusd=0,
        staging_path=staging_path,
        staging_path_sha256=staging_sha,
        recovery_path=recovery_path,
        recovery_path_sha256=recovery_sha,
        artifact_store_root_sha256=store_root_sha,
        provenance=ContractProvenance(
            origin="tests.offload-authority-plan-v4",
            source_revision=attempt.base_revision,
            created_at=NOW.isoformat(),
            input_digests=(
                *digests.values(),
                staging_sha,
                recovery_sha,
                store_root_sha,
            ),
            trace_id=attempt.mission_id,
        ),
    )


def _parts() -> _Parts:
    attempt = _attempt()
    runtime_tool_binding = _runtime_tool_binding(attempt)
    workspace_attestation, target_before, workspace_observation = _observations(
        attempt
    )
    plan = _plan(
        attempt,
        runtime_tool_binding,
        workspace_attestation,
        target_before,
        workspace_observation,
    )
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
    execution_id, idempotency_key = derive_offload_execution_ids(plan)
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
    return _Parts(
        plan,
        attempt,
        workspace_attestation,
        target_before,
        workspace_observation,
        runtime_tool_binding,
        authorization,
        execution,
        ledger,
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


def _with_request(parts: _Parts, request: EffectLeaseRequest) -> _Parts:
    return dataclasses.replace(
        parts,
        authorization=dataclasses.replace(parts.authorization, request=request),
    )


def _replace_contract_digest(contract, field: str, label: str):
    old = getattr(contract, field)
    new = _sha(label)
    return dataclasses.replace(
        contract,
        **{field: new},
        provenance=_replace_provenance_input(contract.provenance, old, new),
    )


def _tamper(parts: _Parts, case: str) -> _Parts:
    plan = parts.plan
    attempt = parts.attempt
    attestation = parts.workspace_attestation
    target = parts.target_before
    workspace = parts.workspace_observation
    binding = parts.runtime_tool_binding
    auth = parts.authorization
    request = auth.request
    lease = auth.lease
    policy = auth.policy_decision
    execution = parts.execution

    if case == "attempt_contract":
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(attempt, instruction="Different instruction."),
        )
    if case == "attempt_mission":
        return dataclasses.replace(
            parts, attempt=dataclasses.replace(attempt, mission_id="mission-2")
        )
    if case == "attempt_id":
        return dataclasses.replace(
            parts, attempt=dataclasses.replace(attempt, attempt_id="attempt-2")
        )
    if case == "attempt_task":
        return dataclasses.replace(parts, attempt=dataclasses.replace(attempt, task_id="task-2"))
    if case == "attempt_source":
        changed_provenance = dataclasses.replace(attempt.provenance, source_revision="b" * 40)
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(
                attempt, base_revision="b" * 40, provenance=changed_provenance
            ),
        )
    if case == "attempt_policy":
        changed = _sha("other-attempt-policy")
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(
                attempt,
                policy_decision_sha256=changed,
                provenance=_replace_provenance_input(
                    attempt.provenance, attempt.policy_decision_sha256, changed
                ),
            ),
        )
    if case == "attempt_runtime":
        changed = _sha("other-runtime-manifest")
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(
                attempt,
                runtime_manifest_sha256=changed,
                provenance=_replace_provenance_input(
                    attempt.provenance, attempt.runtime_manifest_sha256, changed
                ),
            ),
        )
    if case == "attempt_targets":
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(attempt, writable_paths=("src/other.py",)),
        )
    if case == "attempt_wall_budget":
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(
                attempt,
                budget=dataclasses.replace(attempt.budget, max_wall_time_s=119),
            ),
        )
    if case == "attempt_token_budget":
        return dataclasses.replace(
            parts,
            attempt=dataclasses.replace(
                attempt,
                budget=dataclasses.replace(
                    attempt.budget, max_tokens=plan.num_ctx - 1
                ),
            ),
        )
    if case == "workspace_intent_id":
        return dataclasses.replace(
            parts,
            workspace_attestation=dataclasses.replace(attestation, spine_intent_id=2),
        )
    if case == "workspace_intent_sha":
        return dataclasses.replace(
            parts,
            workspace_attestation=_replace_contract_digest(
                attestation, "spine_intent_sha256", case
            ),
        )
    if case == "workspace_id":
        return dataclasses.replace(
            parts,
            workspace_attestation=dataclasses.replace(
                attestation, workspace_id="other-workspace"
            ),
        )
    if case == "workspace_attestation":
        return dataclasses.replace(
            parts,
            workspace_attestation=dataclasses.replace(
                attestation, branch="other-observed-branch"
            ),
        )
    if case == "workspace_observation":
        return dataclasses.replace(
            parts,
            workspace_observation=_replace_contract_digest(
                workspace, "source_fingerprint_sha256", case
            ),
        )
    if case == "workspace_source":
        return dataclasses.replace(
            parts,
            workspace_attestation=dataclasses.replace(
                attestation,
                source_revision="b" * 40,
                provenance=dataclasses.replace(
                    attestation.provenance, source_revision="b" * 40
                ),
            ),
        )
    if case == "workspace_base_source":
        return dataclasses.replace(
            parts,
            workspace_observation=_replace_contract_digest(
                workspace, "base_source_artifact_sha256", case
            ),
        )
    if case == "workspace_task":
        return dataclasses.replace(
            parts,
            workspace_attestation=dataclasses.replace(attestation, task_id="task-2"),
        )
    if case == "workspace_target":
        return dataclasses.replace(
            parts,
            target_before=dataclasses.replace(target, target_path="src/other.py"),
        )
    if case == "workspace_target_before_sha":
        return dataclasses.replace(
            parts,
            target_before=_replace_contract_digest(
                target, "content_sha256", case
            ),
        )
    if case == "workspace_target_before_size":
        return dataclasses.replace(
            parts,
            target_before=dataclasses.replace(
                target, byte_length=target.byte_length + 1
            ),
        )
    if case == "workspace_target_git_mode":
        return dataclasses.replace(
            parts,
            target_before=dataclasses.replace(target, git_mode="100755"),
        )
    if case == "observation_attestation":
        return dataclasses.replace(
            parts,
            workspace_observation=_replace_contract_digest(
                workspace, "workspace_attestation_sha256", case
            ),
        )
    if case == "observation_target":
        return dataclasses.replace(
            parts,
            workspace_observation=_replace_contract_digest(
                workspace, "target_before_observation_sha256", case
            ),
        )
    if case == "target_attestation":
        return dataclasses.replace(
            parts,
            target_before=_replace_contract_digest(
                target, "workspace_attestation_sha256", case
            ),
        )
    if case == "runtime_tool_digest":
        other = _sha("other-executable")
        changed = dataclasses.replace(
            binding,
            executable_sha256=other,
            provenance=_replace_provenance_input(
                binding.provenance, binding.executable_sha256, other
            ),
        )
        return dataclasses.replace(parts, runtime_tool_binding=changed)
    if case == "runtime_tool_id":
        return dataclasses.replace(
            parts,
            runtime_tool_binding=dataclasses.replace(binding, tool_id="other.tool"),
        )
    if case == "runtime_tool_manifest":
        other = _sha("other-tool-manifest")
        changed = dataclasses.replace(
            binding,
            runtime_manifest_sha256=other,
            provenance=_replace_provenance_input(
                binding.provenance, binding.runtime_manifest_sha256, other
            ),
        )
        return dataclasses.replace(parts, runtime_tool_binding=changed)
    if case == "runtime_tool_source":
        changed = dataclasses.replace(
            binding,
            source_revision="b" * 40,
            provenance=dataclasses.replace(binding.provenance, source_revision="b" * 40),
        )
        return dataclasses.replace(parts, runtime_tool_binding=changed)
    if case == "plan_workspace_id":
        other_workspace = "other-workspace"
        other_staging = derive_offload_staging_path(
            attempt_id=plan.attempt_id,
            workspace_id=other_workspace,
            target_path=plan.target_path,
        )
        other_staging_sha = offload_staging_path_sha256(other_staging)
        other_recovery = derive_offload_recovery_path(
            attempt_id=plan.attempt_id,
            workspace_id=other_workspace,
            target_path=plan.target_path,
        )
        other_recovery_sha = offload_recovery_path_sha256(other_recovery)
        return dataclasses.replace(
            parts,
            plan=dataclasses.replace(
                plan,
                workspace_id=other_workspace,
                staging_path=other_staging,
                staging_path_sha256=other_staging_sha,
                recovery_path=other_recovery,
                recovery_path_sha256=other_recovery_sha,
                effect_scope=dataclasses.replace(
                    plan.effect_scope,
                    writable_paths=tuple(
                        sorted((plan.target_path, other_staging, other_recovery))
                    ),
                ),
                provenance=_replace_provenance_input(
                    _replace_provenance_input(
                        plan.provenance,
                        plan.staging_path_sha256,
                        other_staging_sha,
                    ),
                    plan.recovery_path_sha256,
                    other_recovery_sha,
                ),
            ),
        )
    if case == "plan_task_sha":
        return dataclasses.replace(parts, plan=_replace_plan_digest(plan, "task_sha256", case))
    if case == "request_entrypoint":
        changed_request = dataclasses.replace(request, entrypoint_id="python.other")
        changed_lease = dataclasses.replace(lease, entrypoint_id="python.other")
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
    if case == "request_plan":
        other = _sha("other-plan")
        return _with_request(
            parts,
            dataclasses.replace(
                request,
                execution_plan_sha256=other,
                provenance=_replace_provenance_input(request.provenance, plan.digest, other),
            ),
        )
    if case == "request_runtime":
        other = _sha("other-request-runtime")
        return _with_request(
            parts,
            dataclasses.replace(
                request,
                runtime_manifest_sha256=other,
                provenance=_replace_provenance_input(
                    request.provenance, request.runtime_manifest_sha256, other
                ),
            ),
        )
    if case == "request_scope":
        return _with_request(
            parts,
            dataclasses.replace(
                request,
                effect_scope=dataclasses.replace(request.effect_scope, timeout_s=119),
            ),
        )
    if case == "request_idempotency_namespace":
        changed_request = dataclasses.replace(
            request, idempotency_namespace="mission-1/other-attempt"
        )
        changed_lease = dataclasses.replace(
            lease, idempotency_namespace=changed_request.idempotency_namespace
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(
                auth, request=changed_request, lease=changed_lease
            ),
        )
    if case == "lease_request_sha":
        other = _sha("other-request-digest")
        changed = dataclasses.replace(
            lease,
            request_sha256=other,
            provenance=_replace_provenance_input(lease.provenance, request.digest, other),
        )
        return dataclasses.replace(parts, authorization=dataclasses.replace(auth, lease=changed))
    if case == "lease_runtime":
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(
                auth, lease=dataclasses.replace(lease, runtime_id="other-runtime")
            ),
        )
    if case == "policy_subject":
        other = _sha("other-policy-subject")
        changed = dataclasses.replace(
            policy,
            subject_sha256=other,
            provenance=_replace_provenance_input(policy.provenance, request.digest, other),
        )
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, policy_decision=changed),
        )
    if case == "policy_verdict":
        changed = dataclasses.replace(policy, verdict="deny", effect_scope=EffectScope())
        return dataclasses.replace(
            parts,
            authorization=dataclasses.replace(auth, policy_decision=changed),
        )
    if case == "execution_scope":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, writable_paths=("src/other.py",)),
        )
    if case == "execution_generation":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, kill_switch_generation=2),
        )
    if case == "execution_plan":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, execution_plan_sha256=_sha("other-plan")),
        )
    if case == "execution_id":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, execution_id="offload-execution:other"),
        )
    if case == "idempotency_key":
        return dataclasses.replace(
            parts,
            execution=dataclasses.replace(execution, idempotency_key="offload-idempotency:other"),
        )
    raise AssertionError(f"unknown tamper case: {case}")


def test_authority_binds_the_complete_chain_without_starting_an_effect() -> None:
    parts = _parts()
    bound = authorize_offload_execution(
        plan=parts.plan,
        attempt=parts.attempt,
        workspace_attestation=parts.workspace_attestation,
        target_before=parts.target_before,
        workspace_observation=parts.workspace_observation,
        runtime_tool_binding=parts.runtime_tool_binding,
        authorization=parts.authorization,
        execution=parts.execution,
    )

    assert bound == AuthorizedOffloadExecution(
        plan=parts.plan,
        attempt=parts.attempt,
        workspace_attestation=parts.workspace_attestation,
        target_before=parts.target_before,
        workspace_observation=parts.workspace_observation,
        runtime_tool_binding=parts.runtime_tool_binding,
        authorization=parts.authorization,
        execution=parts.execution,
    )
    assert parts.ledger.calls == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        bound.workspace_attestation = dataclasses.replace(  # type: ignore[misc]
            parts.workspace_attestation, workspace_id="other"
        )


def test_execution_identity_ignores_plan_resealing_but_changes_with_semantics() -> None:
    plan = _parts().plan
    first = derive_offload_execution_ids(plan)
    resealed = dataclasses.replace(
        plan,
        model_id="qwen2.5-coder:14b",
        provenance=dataclasses.replace(
            plan.provenance, created_at="2026-08-03T00:01:00+00:00"
        ),
    )
    changed_attempt = _replace_plan_digest(
        plan, "attempt_contract_sha256", "new-attempt-contract"
    )
    changed_intent = _replace_plan_digest(
        plan, "spine_intent_sha256", "new-spine-intent"
    )

    assert resealed.digest != plan.digest
    assert derive_offload_execution_ids(resealed) == first
    assert first[0] != first[1]
    assert derive_offload_execution_ids(changed_attempt) != first
    assert derive_offload_execution_ids(changed_intent) != first
    with pytest.raises(ValueError, match="OffloadExecutionPlan"):
        derive_offload_execution_ids(plan.digest)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("case", "error"),
    (
        ("attempt_contract", "attempt_contract_sha256"),
        ("attempt_mission", "attempt_mission_id"),
        ("attempt_id", "attempt_id"),
        ("attempt_task", "task_id"),
        ("attempt_source", "source_revision"),
        ("attempt_policy", "attempt_policy_decision_sha256"),
        ("attempt_runtime", "attempt_runtime_manifest_sha256"),
        ("attempt_targets", "attempt_writable_paths"),
        ("attempt_wall_budget", "attempt_wall_time_budget"),
        ("attempt_token_budget", "attempt_token_budget"),
        ("workspace_intent_id", "workspace_spine_intent_id"),
        ("workspace_intent_sha", "workspace_spine_intent_sha256"),
        ("workspace_id", "workspace_id"),
        ("workspace_attestation", "workspace_attestation_sha256"),
        ("workspace_observation", "workspace_observation_sha256"),
        ("workspace_source", "workspace_source_revision"),
        ("workspace_base_source", "workspace_base_source_artifact_sha256"),
        ("workspace_task", "workspace_task_id"),
        ("workspace_target", "workspace_target_path"),
        ("workspace_target_before_sha", "workspace_target_before_sha256"),
        ("workspace_target_before_size", "workspace_target_before_size"),
        ("workspace_target_git_mode", "workspace_target_git_mode"),
        ("observation_attestation", "observation_workspace_attestation_sha256"),
        ("observation_target", "observation_target_before_sha256"),
        ("target_attestation", "target_workspace_attestation_sha256"),
        ("runtime_tool_digest", "runtime_tool_binding_sha256"),
        ("runtime_tool_id", "runtime_tool_id"),
        ("runtime_tool_manifest", "runtime_tool_manifest_sha256"),
        ("runtime_tool_source", "runtime_tool_source_revision"),
        ("plan_workspace_id", "workspace_id"),
        ("plan_task_sha", "task_sha256"),
        ("request_entrypoint", "request_entrypoint"),
        ("request_mission", "request_mission_id"),
        ("request_attempt", "request_attempt_id"),
        ("request_plan", "request_execution_plan_sha256"),
        ("request_runtime", "request_runtime_manifest_sha256"),
        ("request_scope", "request_effect_scope"),
        ("request_idempotency_namespace", "request_idempotency_namespace"),
        ("lease_request_sha", "lease_request_sha256"),
        ("lease_runtime", "lease_runtime_id"),
        ("policy_subject", "policy_subject_sha256"),
        ("policy_verdict", "policy_verdict"),
        ("execution_scope", "execution_writable_paths"),
        ("execution_generation", "execution_kill_switch_generation"),
        ("execution_plan", "execution_execution_plan_sha256"),
        ("execution_id", "execution_id"),
        ("idempotency_key", "idempotency_key"),
    ),
)
def test_any_cross_contract_tampering_fails_before_effect_start(
    case: str, error: str
) -> None:
    parts = _tamper(_parts(), case)
    with pytest.raises(OffloadAuthorityBindingError, match=error):
        authorize_offload_execution(
            plan=parts.plan,
            attempt=parts.attempt,
            workspace_attestation=parts.workspace_attestation,
            target_before=parts.target_before,
            workspace_observation=parts.workspace_observation,
            runtime_tool_binding=parts.runtime_tool_binding,
            authorization=parts.authorization,
            execution=parts.execution,
        )
    assert parts.ledger.calls == 0
