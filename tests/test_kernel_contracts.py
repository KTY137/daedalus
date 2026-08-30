# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from daedalus.runtime_registry import RuntimeSpec
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    AttemptContract,
    AttemptReceipt,
    CampaignContract,
    ConformanceCheck,
    ContractProvenance,
    EffectScope,
    EvidencePacket,
    MissionContract,
    NominationReceipt,
    PolicyDecision,
    PromotionReceipt,
    ResourceBudget,
    ResourceUsage,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeManifest,
    parse_kernel_contract,
)
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    TaskSpec,
)


REVISION = "a" * 40
NOW = "2026-07-30T10:00:00Z"
LATER = "2026-07-30T11:00:00+00:00"


def sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def locator(value: str) -> str:
    return f"artifact-locator:sha256:{sha(value)}"


def locator_digest(value: str) -> str:
    return value.rsplit(":", 1)[1]


def provenance(*inputs: str, created_at: str = NOW) -> ContractProvenance:
    return ContractProvenance(
        origin="test.kernel-contracts",
        source_revision=REVISION,
        created_at=created_at,
        input_digests=tuple(inputs),
        trace_id="tr-test-001",
    )


def runtime_manifest() -> RuntimeManifest:
    return RuntimeManifest(
        runtime_id="test-runtime",
        runtime_version="1.2.3",
        adapter_id="test-adapter",
        adapter_version="2.0",
        source_revision=REVISION,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            streaming=True,
            tool_events=True,
            timeout=True,
            cancellation=True,
            workspace_isolation=True,
            workspace_write=True,
        ),
        declared_tools=("python", "git"),
        egress_transports=(),
        workspace_modes=("read-only", "isolated-worktree"),
        cost_model="metered",
        provenance=provenance(),
    )


def mission() -> MissionContract:
    policy = sha("policy")
    return MissionContract(
        mission_id="mission-1",
        objective="Change the requested behavior and retain evidence.",
        source_revision=REVISION,
        work_item_ids=("work-b", "work-a"),
        success_criteria=("tests pass", "artifact retained"),
        policy_sha256=policy,
        budget=ResourceBudget(
            max_tokens=1000,
            max_cost_microusd=200_000,
            max_wall_time_s=60,
            max_attempts=2,
        ),
        provenance=provenance(policy),
    )


def policy_decision(subject: MissionContract) -> PolicyDecision:
    policy = subject.policy_sha256
    return PolicyDecision(
        decision_id="decision-1",
        subject_id=subject.mission_id,
        subject_sha256=subject.digest,
        policy_version="2026-07-30",
        policy_sha256=policy,
        verdict="allow",
        reasons=("bounded candidate worktree",),
        effect_scope=EffectScope(
            read_only=False,
            writable_paths=("src",),
            tools=("python",),
            max_cost_microusd=200_000,
            max_concurrency=1,
            timeout_s=60,
            kill_switch_ref="mission-1-kill",
        ),
        provenance=provenance(subject.digest, policy),
    )


def task() -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        instruction="Change src/value.py.",
        base_revision=REVISION,
        target_paths=("src/value.py",),
        gate_paths=("tests/test_value.py",),
    )


def attempt_contract(
    *,
    manifest: RuntimeManifest | None = None,
    decision: PolicyDecision | None = None,
) -> AttemptContract:
    selected_manifest = manifest or runtime_manifest()
    selected_mission = mission()
    selected_decision = decision or policy_decision(selected_mission)
    selected_task = task()
    return AttemptContract.from_task_spec(
        selected_task,
        attempt_id="attempt-1",
        mission_id=selected_mission.mission_id,
        runtime_manifest_sha256=selected_manifest.digest,
        policy_decision_sha256=selected_decision.digest,
        budget=ResourceBudget(
            max_tokens=800,
            max_cost_microusd=150_000,
            max_wall_time_s=45,
            max_attempts=1,
        ),
        provenance=provenance(
            selected_task.digest,
            selected_manifest.digest,
            selected_decision.digest,
        ),
    )


def clean_result(attempt: AttemptContract) -> AttemptResult:
    diff = b"diff --git a/src/value.py b/src/value.py\n"
    artifact = PatchArtifact(
        task_id=attempt.task_id,
        branch="daedalus-attempt-task-1",
        base_revision=attempt.base_revision,
        diff_bytes=diff,
        diff_sha256=sha(diff),
        changed_paths=("src/value.py",),
        created_ts=NOW,
    )
    gate = GateResult(
        passed=True,
        name="pytest",
        command=("python", "-m", "pytest"),
        returncode=0,
        output="1 passed",
        duration_s=0.25,
    )
    candidate_locator = locator("candidate locator")
    return AttemptResult(
        state="clean",
        task_id=attempt.task_id,
        started_ts=NOW,
        finished_ts=LATER,
        duration_s=3600.0,
        effect_key="daedalus-attempt-task-1",
        branch="daedalus-attempt-task-1",
        base_revision=attempt.base_revision,
        artifact=artifact,
        artifact_locator={
            "uri": f"sha256:{artifact.diff_sha256}",
            "locator_uri": candidate_locator,
        },
        gates=gate,
    )


def evidence_packet(
    attempt: AttemptContract,
    result: AttemptResult,
) -> EvidencePacket:
    assert result.artifact is not None
    assert result.gates is not None
    gate_locator = locator("gate output locator")
    candidate_locator = result.artifact_locator["locator_uri"]
    return EvidencePacket.from_attempt_result(
        result,
        attempt=attempt,
        packet_id="evidence-1",
        usage=ResourceUsage(
            input_tokens=100,
            output_tokens=50,
            cost_microusd=10_000,
            wall_time_ms=250,
        ),
        provenance=provenance(
            attempt.digest,
            attempt.policy_decision_sha256,
            result.artifact.diff_sha256,
            result.gates.output_sha256,
            locator_digest(gate_locator),
            locator_digest(candidate_locator),
            created_at=LATER,
        ),
        evidence_locator=gate_locator,
        evaluator_assurance="deterministic",
    )


def test_contract_serialization_is_canonical_strict_and_round_trips():
    first = mission()
    second = MissionContract(
        mission_id=first.mission_id,
        objective=first.objective,
        source_revision=first.source_revision,
        work_item_ids=tuple(reversed(first.work_item_ids)),
        success_criteria=tuple(reversed(first.success_criteria)),
        policy_sha256=first.policy_sha256,
        budget=first.budget,
        provenance=ContractProvenance(
            origin=first.provenance.origin,
            source_revision=first.provenance.source_revision,
            created_at="2026-07-30T12:00:00+02:00",
            input_digests=tuple(reversed(first.provenance.input_digests)),
            trace_id=first.provenance.trace_id,
        ),
    )

    assert first.to_json() == second.to_json()
    assert first.digest == second.digest
    assert json.loads(first.to_json()) == first.to_dict()
    parsed = parse_kernel_contract(json.loads(first.to_json()))
    assert parsed == first
    assert parsed.digest == first.digest

    malformed = first.to_dict()
    malformed["contract_version"] = "999"
    with pytest.raises(ValueError, match="contract_version"):
        parse_kernel_contract(malformed)
    malformed = first.to_dict()
    malformed["pretend_field"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_kernel_contract(malformed)


def test_contracts_snapshot_nested_json_and_reject_non_json_values():
    output = sha("gate output")
    evidence_locator = locator("gate output locator")
    raw_details = {"nested": {"values": [1, 2]}}
    item_provenance = provenance(output, locator_digest(evidence_locator))
    from daedalus.schemas import EvidenceItem

    item = EvidenceItem(
        evidence_id="ev-1",
        evaluator="pytest",
        assurance="deterministic",
        verdict="failed",
        output_sha256=output,
        evidence_locator=evidence_locator,
        collected_at=NOW,
        provenance=item_provenance,
        details=raw_details,
    )
    before = item.details["nested"]["values"]
    raw_details["nested"]["values"].append(3)

    assert before == (1, 2)
    with pytest.raises(TypeError):
        item.details["new"] = "mutation"
    with pytest.raises(FrozenInstanceError):
        item.verdict = "passed"
    with pytest.raises(ValueError, match="non-finite"):
        type(item)(
            evidence_id="ev-2",
            evaluator="pytest",
            assurance="deterministic",
            verdict="failed",
            output_sha256=output,
            evidence_locator=evidence_locator,
            collected_at=NOW,
            provenance=item_provenance,
            details={"score": float("nan")},
        )


def test_mission_and_attempt_refuse_unbounded_or_unpinned_work():
    unbounded = TaskSpec(
        task_id="legacy",
        instruction="change anything",
        base_revision=REVISION,
    )
    manifest = runtime_manifest()
    selected_mission = mission()
    decision = policy_decision(selected_mission)

    with pytest.raises(ValueError, match="no target_paths"):
        AttemptContract.from_task_spec(
            unbounded,
            attempt_id="attempt-legacy",
            mission_id=selected_mission.mission_id,
            runtime_manifest_sha256=manifest.digest,
            policy_decision_sha256=decision.digest,
            budget=ResourceBudget(max_attempts=1),
            provenance=provenance(unbounded.digest, manifest.digest, decision.digest),
        )
    with pytest.raises(ValueError, match="frozen base_revision"):
        AttemptContract.from_task_spec(
            TaskSpec(
                task_id="floating",
                instruction="change src",
                target_paths=("src",),
            ),
            attempt_id="attempt-floating",
            mission_id=selected_mission.mission_id,
            runtime_manifest_sha256=manifest.digest,
            policy_decision_sha256=decision.digest,
            budget=ResourceBudget(max_attempts=1),
            provenance=provenance(sha("unused"), manifest.digest, decision.digest),
        )
    with pytest.raises(ValueError, match="must bound tokens, cost, or wall time"):
        MissionContract(
            mission_id="mission-unbounded",
            objective="No budget",
            source_revision=REVISION,
            work_item_ids=("work-1",),
            success_criteria=("done",),
            policy_sha256=selected_mission.policy_sha256,
            budget=ResourceBudget(),
            provenance=provenance(selected_mission.policy_sha256),
        )


def test_attempt_adapter_binds_existing_task_runtime_and_policy_contracts():
    manifest = runtime_manifest()
    selected_mission = mission()
    decision = policy_decision(selected_mission)
    selected_task = task()
    attempt = AttemptContract.from_task_spec(
        selected_task,
        attempt_id="attempt-1",
        mission_id=selected_mission.mission_id,
        runtime_manifest_sha256=manifest.digest,
        policy_decision_sha256=decision.digest,
        budget=ResourceBudget(max_attempts=1, max_wall_time_s=60),
        provenance=provenance(
            selected_task.digest, manifest.digest, decision.digest
        ),
    )

    assert attempt.task_sha256 == selected_task.digest
    assert attempt.writable_paths == ("src/value.py",)
    assert attempt.gate_names == ("pytest",)
    assert AttemptContract.from_dict(attempt.to_dict()) == attempt
    with pytest.raises(ValueError, match="does not bind"):
        AttemptContract.from_task_spec(
            selected_task,
            attempt_id="attempt-forged",
            mission_id=selected_mission.mission_id,
            runtime_manifest_sha256=manifest.digest,
            policy_decision_sha256=decision.digest,
            # bounded on purpose: an unbounded budget would refuse first and
            # hide the provenance-binding rule this case exists to prove
            budget=ResourceBudget(max_attempts=1, max_wall_time_s=60),
            provenance=provenance(selected_task.digest),
        )


def test_runtime_registry_adapter_is_declared_and_does_not_invent_conformance():
    spec = RuntimeSpec(
        id="writer",
        label="Writer",
        mode="cli",
        command="writer",
        can_write=True,
        agentic=True,
    )
    manifest = RuntimeManifest.from_runtime_spec(
        spec,
        runtime_version="unknown",
        adapter_id="runtime-registry",
        adapter_version="1",
        source_revision=REVISION,
        provenance=provenance(),
    )

    assert manifest.assurance == "declared"
    assert manifest.capabilities.workspace_write is True
    assert manifest.capabilities.streaming is False
    assert manifest.capabilities.workspace_isolation is False
    assert manifest.workspace_modes == ("read-only", "workspace-write")
    assert "isolated-worktree" not in manifest.workspace_modes
    assert RuntimeManifest.from_dict(manifest.to_dict()) == manifest


def test_effectful_policy_allow_requires_kill_switch_and_provenance_binding():
    selected_mission = mission()
    scope = EffectScope(
        read_only=False,
        writable_paths=("src",),
        tools=("python",),
        max_concurrency=1,
    )
    with pytest.raises(ValueError, match="kill_switch_ref"):
        PolicyDecision(
            decision_id="decision-no-kill",
            subject_id=selected_mission.mission_id,
            subject_sha256=selected_mission.digest,
            policy_version="1",
            policy_sha256=selected_mission.policy_sha256,
            verdict="allow",
            reasons=("looks fine",),
            effect_scope=scope,
            provenance=provenance(
                selected_mission.digest, selected_mission.policy_sha256
            ),
        )
    with pytest.raises(ValueError, match="does not bind"):
        PolicyDecision(
            decision_id="decision-unbound",
            subject_id=selected_mission.mission_id,
            subject_sha256=selected_mission.digest,
            policy_version="1",
            policy_sha256=selected_mission.policy_sha256,
            verdict="deny",
            reasons=("not allowed",),
            effect_scope=EffectScope(),
            provenance=provenance(selected_mission.digest),
        )


def test_evidence_adapter_retains_output_digest_and_never_promotes():
    attempt = attempt_contract()
    result = clean_result(attempt)
    packet = evidence_packet(attempt, result)

    assert packet.evaluation_status == "passed"
    assert packet.candidate_artifact_sha256 == result.artifact.diff_sha256
    assert packet.items[0].output_sha256 == result.gates.output_sha256
    assert packet.items[0].details["output_tail"] == "1 passed"
    assert "promotion" not in packet.to_dict()
    assert "nomination" not in packet.to_dict()
    assert EvidencePacket.from_dict(packet.to_dict()) == packet

    wrong = AttemptResult(
        state=result.state,
        task_id="other-task",
        started_ts=result.started_ts,
        finished_ts=result.finished_ts,
        duration_s=result.duration_s,
        effect_key=result.effect_key,
        branch=result.branch,
        base_revision=result.base_revision,
        artifact=result.artifact,
        gates=result.gates,
    )
    gate_locator = locator("gate output locator")
    with pytest.raises(ValueError, match="task_id"):
        EvidencePacket.from_attempt_result(
            wrong,
            attempt=attempt,
            packet_id="evidence-wrong",
            usage=ResourceUsage(),
            provenance=provenance(
                attempt.digest,
                attempt.policy_decision_sha256,
                result.artifact.diff_sha256,
                result.gates.output_sha256,
                locator_digest(gate_locator),
                created_at=LATER,
            ),
            evidence_locator=gate_locator,
            evaluator_assurance="deterministic",
        )


def test_attempt_receipt_maps_legacy_state_without_nominating_or_promoting():
    attempt = attempt_contract()
    result = clean_result(attempt)
    evidence = evidence_packet(attempt, result)
    receipt = AttemptReceipt.from_attempt_result(
        result,
        attempt=attempt,
        evidence=evidence,
        receipt_id="receipt-1",
        usage=evidence.usage,
        provenance=provenance(
            attempt.digest,
            attempt.runtime_manifest_sha256,
            attempt.policy_decision_sha256,
            evidence.digest,
            created_at=LATER,
        ),
    )

    assert receipt.outcome == "passed"
    assert set(receipt.to_dict()).isdisjoint(
        {"nominated", "promoted", "success", "owner_approval_ref"}
    )
    assert AttemptReceipt.from_dict(receipt.to_dict()) == receipt


def test_nomination_and_owner_promotion_are_separate_receipts():
    attempt = attempt_contract()
    result = clean_result(attempt)
    evidence = evidence_packet(attempt, result)
    candidate = result.artifact.diff_sha256
    candidate_locator = result.artifact_locator["locator_uri"]
    evidence_locator = evidence.items[0].evidence_locator
    nomination = NominationReceipt(
        nomination_id="nomination-1",
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        source_revision=REVISION,
        candidate_artifact_sha256=candidate,
        candidate_artifact_locator=candidate_locator,
        evidence_packet_sha256=evidence.digest,
        evidence_locator=evidence_locator,
        policy_decision_sha256=attempt.policy_decision_sha256,
        nomination_status="nominated",
        reasons=("all frozen gates passed",),
        provenance=provenance(
            candidate,
            locator_digest(candidate_locator),
            evidence.digest,
            locator_digest(evidence_locator),
            attempt.policy_decision_sha256,
            created_at=LATER,
        ),
    )

    approval_ref = locator("owner review 2026-07-30")
    common = {
        "promotion_id": "promotion-1",
        "nomination_receipt_sha256": nomination.digest,
        "candidate_artifact_sha256": candidate,
        "candidate_artifact_locator": candidate_locator,
        "evidence_packet_sha256": evidence.digest,
        "evidence_locator": evidence_locator,
        "source_revision": REVISION,
        "target_revision": "refs/heads/main",
        "reasons": ("owner review required",),
    }
    unapproved_inputs = (
        nomination.digest,
        candidate,
        locator_digest(candidate_locator),
        evidence.digest,
        locator_digest(evidence_locator),
    )
    pending = PromotionReceipt(
        **common,
        provenance=provenance(*unapproved_inputs, created_at=LATER),
        promotion_status="pending-owner",
        owner_approval_ref=None,
        approval_assurance="not-applicable",
    )
    assert pending.promotion_status == "pending-owner"
    with pytest.raises(ValueError, match="owner_approval_ref"):
        PromotionReceipt(
            **common,
            provenance=provenance(*unapproved_inputs, created_at=LATER),
            promotion_status="approved",
            owner_approval_ref=None,
            approval_assurance="authenticated",
        )
    # an approval the boundary never authenticated cannot be dressed as one
    with pytest.raises(ValueError, match="authenticated approval_assurance"):
        PromotionReceipt(
            **common,
            provenance=provenance(*unapproved_inputs, created_at=LATER),
            promotion_status="approved",
            owner_approval_ref=approval_ref,
            approval_assurance="not-applicable",
        )
    approved = PromotionReceipt(
        **common,
        provenance=provenance(
            *unapproved_inputs,
            locator_digest(approval_ref),
            created_at=LATER,
        ),
        promotion_status="approved",
        owner_approval_ref=approval_ref,
        approval_assurance="authenticated",
    )
    assert approved.owner_approval_ref == approval_ref
    assert approved.approval_assurance == "authenticated"
    assert PromotionReceipt.from_dict(approved.to_dict()) == approved


def test_conformance_receipt_cannot_claim_green_over_failed_check():
    manifest = runtime_manifest()
    # the receipt must cover the whole vendor-neutral fixture matrix, so a
    # partial run cannot be presented as a conformant runtime
    checks = tuple(
        ConformanceCheck(
            name=name,
            passed=name != "workspace-isolation",
            evidence_sha256=sha(f"{name} transcript"),
            evidence_locator=locator(f"{name} transcript locator"),
            detail=(
                "write escaped the fixture workspace"
                if name == "workspace-isolation"
                else ""
            ),
        )
        for name in sorted(RUNTIME_CONFORMANCE_CHECKS)
    )
    inputs = (
        manifest.digest,
        *(check.evidence_sha256 for check in checks),
        *(locator_digest(check.evidence_locator) for check in checks),
    )
    with pytest.raises(ValueError, match="contradicts"):
        RuntimeConformanceReceipt(
            receipt_id="conformance-false-green",
            runtime_manifest_sha256=manifest.digest,
            source_revision=REVISION,
            status="passed",
            checks=checks,
            started_at=NOW,
            finished_at=LATER,
            usage=ResourceUsage(wall_time_ms=100),
            provenance=provenance(*inputs, created_at=LATER),
        )
    receipt = RuntimeConformanceReceipt(
        receipt_id="conformance-failed",
        runtime_manifest_sha256=manifest.digest,
        source_revision=REVISION,
        status="failed",
        checks=checks,
        started_at=NOW,
        finished_at=LATER,
        usage=ResourceUsage(wall_time_ms=100),
        provenance=provenance(*inputs, created_at=LATER),
    )
    assert RuntimeConformanceReceipt.from_dict(receipt.to_dict()) == receipt
    # a partial fixture run cannot be presented as a conformant runtime
    with pytest.raises(ValueError, match="exactly cover the vendor-neutral"):
        RuntimeConformanceReceipt(
            receipt_id="conformance-partial",
            runtime_manifest_sha256=manifest.digest,
            source_revision=REVISION,
            status="passed",
            checks=tuple(check for check in checks if check.passed),
            started_at=NOW,
            finished_at=LATER,
            usage=ResourceUsage(wall_time_ms=100),
            provenance=provenance(*inputs, created_at=LATER),
        )


def test_campaign_contract_is_frozen_bounded_and_retains_negative_baseline():
    spec_digest = sha("experiment spec")
    evaluator = sha("sealed evaluator")
    task_digest = sha("task set")
    baseline = sha("random search")
    generator = sha("generator v1")
    model = sha("model v1")
    campaign = CampaignContract(
        campaign_id="campaign-1",
        source_revision=REVISION,
        experiment_spec_sha256=spec_digest,
        evaluator_sha256=evaluator,
        task_sha256s=(task_digest,),
        baseline_sha256s=(baseline,),
        seeds=(3, 1, 2),
        metrics=("success-rate", "cost"),
        operator_axis="representation",
        frozen_components={
            "generator": generator,
            "model": model,
            "evaluator": evaluator,
        },
        writable_paths=("candidates",),
        budget=ResourceBudget(
            max_tokens=30_000,
            max_cost_microusd=2_000_000,
            max_attempts=10,
        ),
        expires_at=LATER,
        provenance=provenance(
            spec_digest,
            evaluator,
            task_digest,
            baseline,
            generator,
            model,
        ),
    )

    assert campaign.seeds == (1, 2, 3)
    assert campaign.baseline_sha256s == (baseline,)
    assert CampaignContract.from_dict(campaign.to_dict()) == campaign
    with pytest.raises(ValueError, match="at least one baseline"):
        CampaignContract(
            campaign_id="campaign-no-control",
            source_revision=REVISION,
            experiment_spec_sha256=spec_digest,
            evaluator_sha256=evaluator,
            task_sha256s=(task_digest,),
            baseline_sha256s=(),
            seeds=(1,),
            metrics=("success-rate",),
            operator_axis="representation",
            frozen_components={"evaluator": evaluator},
            writable_paths=("candidates",),
            budget=ResourceBudget(max_attempts=1),
            expires_at=LATER,
            provenance=provenance(spec_digest, evaluator, task_digest),
        )
