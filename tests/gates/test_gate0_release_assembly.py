from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.gates import (
    Gate0ReleaseReport,
    GateReport,
    assemble_gate0_release_report,
    evidence_requirements_sha256,
)
from daedalus.gates.evidence import (
    ArtifactEvidence,
    FaultMatrixEvidence,
    GateEvidenceIndex,
    OwnerDecisionEvidence,
    ReviewEvidence,
    RuntimeEnvelopeEvidence,
    WorkflowRunEvidence,
)
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
TREE = "b" * 40
REGISTRY = "c" * 64
PLAN = "d" * 64
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def provenance(origin: str, revision: str, created_at: datetime, *digests: str):
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=created_at.isoformat(),
        input_digests=tuple(sorted(set(digests))),
    )


def local_report(**changes) -> GateReport:
    values = {
        "gate": 0,
        "source_revision": REVISION,
        "registry_sha256": REGISTRY,
        "security_boundary_claimed": False,
        "owner_approval_enforced": True,
    }
    values.update(changes)
    return GateReport(**values)


def workflow(
    workflow_id: str = "gate0-required",
    *,
    revision: str = REVISION,
    conclusion: str = "success",
) -> WorkflowRunEvidence:
    logs = ("1" if workflow_id == "gate0-required" else "2") * 64
    artifact_sha = "3" * 64
    return WorkflowRunEvidence(
        workflow_id=workflow_id,
        run_id=101 if workflow_id == "gate0-required" else 102,
        source_revision=revision,
        conclusion=conclusion,
        completed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        logs_sha256=logs,
        artifact_sha256s=(artifact_sha,),
        provenance=provenance(
            "tests.release-workflow", revision, NOW, logs, artifact_sha
        ),
    )


def artifact(kind: str, content: str, *, tree: str = TREE) -> ArtifactEvidence:
    return ArtifactEvidence(
        artifact_id=f"artifact-{kind}",
        artifact_kind=kind,
        source_revision=REVISION,
        source_tree_revision=tree,
        content_sha256=content,
        locator=f"artifact-locator:sha256:{content}",
        built_at=NOW.isoformat(),
        provenance=provenance("tests.release-artifact", REVISION, NOW, content),
    )


def runtime() -> RuntimeEnvelopeEvidence:
    envelope = "4" * 64
    return RuntimeEnvelopeEvidence(
        runtime_id="claude-code-cli",
        envelope_sha256=envelope,
        source_revision=REVISION,
        authority="live-runtime",
        status="passed",
        observed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        provenance=provenance("tests.release-runtime", REVISION, NOW, envelope),
    )


def fault() -> FaultMatrixEvidence:
    matrix = "5" * 64
    return FaultMatrixEvidence(
        matrix_id="gate0-faults",
        source_revision=REVISION,
        status="passed",
        matrix_sha256=matrix,
        scenario_ids=("approval-replay", "target-head-race"),
        executed_at=NOW.isoformat(),
        provenance=provenance("tests.release-fault", REVISION, NOW, matrix),
    )


def review(perspective: str, *, assurance: str = "human") -> ReviewEvidence:
    transcript = ("6" if perspective == "architecture" else "7") * 64
    return ReviewEvidence(
        review_id=f"{perspective}-review",
        perspective=perspective,
        assurance=assurance,
        source_revision=REVISION,
        verdict="passed",
        unresolved_finding_ids=(),
        transcript_sha256=transcript,
        reviewed_at=NOW.isoformat(),
        provenance=provenance(
            f"tests.release-{perspective}", REVISION, NOW, transcript
        ),
    )


def owner() -> OwnerDecisionEvidence:
    approval = "8" * 64
    verifier = "9" * 64
    return OwnerDecisionEvidence(
        decision_id="owner-gate0-close",
        source_revision=REVISION,
        owner_approval_sha256=approval,
        verifier_receipt_sha256=verifier,
        verified_at=NOW.isoformat(),
        provenance=provenance(
            "tests.release-owner", REVISION, NOW, approval, verifier
        ),
    )


def evidence_index(
    report: GateReport,
    *,
    owner_decision: OwnerDecisionEvidence | None = None,
    report_artifact_sha256: str | None = None,
    registry_sha256: str = REGISTRY,
    workflows: tuple[WorkflowRunEvidence, ...] | None = None,
    architecture_assurance: str = "human",
) -> GateEvidenceIndex:
    mechanical_sha = str(report.to_dict()["report_sha256"])
    report_sha = report_artifact_sha256 or mechanical_sha
    retained_workflows = workflows or (workflow(),)
    retained_artifacts = (
        artifact("gate-report", report_sha),
        artifact("wheel", "e" * 64),
    )
    retained_runtimes = (runtime(),)
    retained_faults = (fault(),)
    retained_reviews = (
        review("architecture", assurance=architecture_assurance),
        review("security"),
    )
    selected_owner = owner() if owner_decision is None else owner_decision
    retained = [
        PLAN,
        registry_sha256,
        *(item.digest for item in retained_workflows),
        *(item.digest for item in retained_artifacts),
        *(item.digest for item in retained_runtimes),
        *(item.digest for item in retained_faults),
        *(item.digest for item in retained_reviews),
    ]
    if selected_owner is not False and selected_owner is not None:
        retained.append(selected_owner.digest)
    return GateEvidenceIndex(
        index_id="gate0-release-index",
        gate=0,
        source_revision=REVISION,
        source_tree_revision=TREE,
        iron_plan_sha256=PLAN,
        registry_sha256=registry_sha256,
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        required_workflow_ids=("gate0-required",),
        required_artifact_kinds=("gate-report", "wheel"),
        required_runtime_ids=("claude-code-cli",),
        required_fault_matrix_ids=("gate0-faults",),
        required_review_perspectives=("architecture", "security"),
        workflows=retained_workflows,
        artifacts=retained_artifacts,
        runtimes=retained_runtimes,
        fault_matrices=retained_faults,
        reviews=retained_reviews,
        owner_decision=(
            None if selected_owner is False else selected_owner
        ),
        provenance=provenance(
            "tests.release-index", REVISION, NOW, *retained
        ),
    )


def trust_sets(value: GateEvidenceIndex) -> dict[str, tuple[str, ...]]:
    result = {
        "trusted_requirements_sha256s": (evidence_requirements_sha256(value),),
        "trusted_iron_plan_sha256s": (value.iron_plan_sha256,),
        "trusted_registry_sha256s": (value.registry_sha256,),
        "trusted_workflow_evidence_sha256s": tuple(
            item.digest for item in value.workflows
        ),
        "trusted_artifact_evidence_sha256s": tuple(
            item.digest for item in value.artifacts
        ),
        "trusted_runtime_envelope_sha256s": tuple(
            item.envelope_sha256 for item in value.runtimes
        ),
        "trusted_fault_matrix_sha256s": tuple(
            item.matrix_sha256 for item in value.fault_matrices
        ),
        "trusted_review_evidence_sha256s": tuple(
            item.digest for item in value.reviews
        ),
        "trusted_owner_verifier_sha256s": (),
    }
    if value.owner_decision is not None:
        result["trusted_owner_verifier_sha256s"] = (
            value.owner_decision.verifier_receipt_sha256,
        )
    return result


def assemble(report: GateReport, value: GateEvidenceIndex, **changes):
    arguments = {
        "release_id": "gate0-release",
        "current_revision": REVISION,
        "current_tree_revision": TREE,
        "now": NOW + timedelta(minutes=1),
        **trust_sets(value),
    }
    arguments.update(changes)
    return assemble_gate0_release_report(report, value, **arguments)


def test_complete_trusted_exact_head_is_the_only_closed_release() -> None:
    report = local_report()
    value = evidence_index(report)
    release = assemble(report, value)

    assert release.closed
    assert release.blockers == ()
    assert release.parsed_gate_report.security_boundary_claimed
    assert release.parsed_gate_report.closed
    assert release.mechanical_report_sha256 == report.to_dict()["report_sha256"]
    assert Gate0ReleaseReport.from_dict(release.to_dict()) == release
    assert assemble(report, value).digest == release.digest


def test_manual_security_claim_cannot_replace_external_trust() -> None:
    report = local_report(security_boundary_claimed=True)
    value = evidence_index(report)
    release = assemble_gate0_release_report(
        report,
        value,
        release_id="gate0-release",
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
    )

    assert not release.closed
    assert not release.parsed_gate_report.security_boundary_claimed
    assert "index:untrusted-requirements" in release.blockers
    assert "owner-decision:untrusted-verifier-receipt" in release.blockers


def test_owner_decision_is_separate_from_the_technical_security_claim() -> None:
    report = local_report()
    value = evidence_index(report, owner_decision=False)
    release = assemble(report, value)

    assert release.parsed_gate_report.security_boundary_claimed
    assert release.parsed_gate_report.closed
    assert not release.closed
    assert release.blockers == ("owner-decision:missing",)


def test_local_runtime_failure_prevents_security_claim_even_with_green_evidence() -> None:
    report = local_report(runtime_conformance_failures=("claude:failed",))
    value = evidence_index(report)
    release = assemble(report, value)

    assert not release.parsed_gate_report.security_boundary_claimed
    assert not release.closed
    assert "runtime_conformance_failures:claude:failed" in release.blockers
    assert "security_boundary_claimed:false" in release.blockers


def test_stale_or_recombined_report_index_bindings_fail_closed() -> None:
    report = local_report()
    value = evidence_index(
        report,
        report_artifact_sha256="f" * 64,
        registry_sha256="0" * 64,
    )
    release = assemble(
        report,
        value,
        current_tree_revision="1" * 40,
    )

    assert not release.closed
    assert "assembly:gate-report-artifact-mismatch" in release.blockers
    assert "assembly:gate-report-registry-mismatch" in release.blockers
    assert "index:foreign-source-tree" in release.blockers
    assert "artifact:gate-report:foreign-source-tree" in release.blockers


def test_failed_optional_evidence_and_model_review_cannot_be_ignored() -> None:
    report = local_report()
    value = evidence_index(
        report,
        workflows=(
            workflow(),
            workflow("optional-nightly", conclusion="failure"),
        ),
        architecture_assurance="model-opinion",
    )
    release = assemble(report, value)

    assert not release.closed
    assert "workflow:optional-nightly:conclusion-failure" in release.blockers
    assert "review:architecture:no-human-pass" in release.blockers
    assert not release.parsed_gate_report.security_boundary_claimed


def test_derived_wire_fields_and_nested_gate_report_are_tamper_evident() -> None:
    report = local_report()
    release = assemble(report, evidence_index(report))

    closed_payload = release.to_dict()
    closed_payload["closed"] = False
    with pytest.raises(ValueError, match="closed contradicts"):
        Gate0ReleaseReport.from_dict(closed_payload)

    blocker_payload = release.to_dict()
    blocker_payload["blockers"] = ["invented"]
    with pytest.raises(ValueError, match="blockers contradict"):
        Gate0ReleaseReport.from_dict(blocker_payload)

    report_payload = release.to_dict()
    report_payload["gate_report"]["security_boundary_claimed"] = "true"
    with pytest.raises(ValueError):
        Gate0ReleaseReport.from_dict(report_payload)


def test_release_provenance_cannot_be_repacked() -> None:
    report = local_report()
    release = assemble(report, evidence_index(report))
    with pytest.raises(ValueError, match="does not bind"):
        dataclasses.replace(
            release,
            provenance=dataclasses.replace(release.provenance, input_digests=()),
        )
