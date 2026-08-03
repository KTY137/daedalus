from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daedalus.gates import (
    assert_strict_exact_head,
    evidence_requirements_sha256,
    strict_mechanical_blockers,
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

REV = "a" * 40
TREE = "b" * 40
NOW = datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)


def prov(origin: str, revision: str, created: datetime, *digests: str):
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=created.isoformat(),
        input_digests=tuple(sorted(set(digests))),
    )


def build_index(*, add_inconsistent_extras: bool = False) -> GateEvidenceIndex:
    workflow_log = "1" * 64
    workflow_artifact = "2" * 64
    workflows = [
        WorkflowRunEvidence(
            workflow_id="iron-plan",
            run_id=10,
            source_revision=REV,
            conclusion="success",
            completed_at=NOW.isoformat(),
            expires_at=(NOW + timedelta(days=1)).isoformat(),
            logs_sha256=workflow_log,
            artifact_sha256s=(workflow_artifact,),
            provenance=prov(
                "tests.strict-workflow",
                REV,
                NOW,
                workflow_log,
                workflow_artifact,
            ),
        )
    ]
    artifact_sha = "3" * 64
    artifacts = [
        ArtifactEvidence(
            artifact_id="wheel-artifact",
            artifact_kind="wheel",
            source_revision=REV,
            source_tree_revision=TREE,
            content_sha256=artifact_sha,
            locator=f"artifact-locator:sha256:{artifact_sha}",
            built_at=NOW.isoformat(),
            provenance=prov("tests.strict-artifact", REV, NOW, artifact_sha),
        )
    ]
    envelope_sha = "4" * 64
    runtimes = [
        RuntimeEnvelopeEvidence(
            runtime_id="claude-code-cli",
            envelope_sha256=envelope_sha,
            source_revision=REV,
            authority="live-runtime",
            status="passed",
            observed_at=NOW.isoformat(),
            expires_at=(NOW + timedelta(days=1)).isoformat(),
            provenance=prov("tests.strict-runtime", REV, NOW, envelope_sha),
        )
    ]
    fault_sha = "5" * 64
    faults = [
        FaultMatrixEvidence(
            matrix_id="gate0-faults",
            source_revision=REV,
            status="passed",
            matrix_sha256=fault_sha,
            scenario_ids=("approval-replay",),
            executed_at=NOW.isoformat(),
            provenance=prov("tests.strict-fault", REV, NOW, fault_sha),
        )
    ]
    reviews = []
    for marker, perspective in (("6", "architecture"), ("7", "security")):
        transcript = marker * 64
        reviews.append(
            ReviewEvidence(
                review_id=f"{perspective}-review",
                perspective=perspective,
                assurance="human",
                source_revision=REV,
                verdict="passed",
                unresolved_finding_ids=(),
                transcript_sha256=transcript,
                reviewed_at=NOW.isoformat(),
                provenance=prov(
                    f"tests.strict-{perspective}", REV, NOW, transcript
                ),
            )
        )
    approval = "8" * 64
    verifier = "9" * 64
    owner = OwnerDecisionEvidence(
        decision_id="owner-gate0",
        source_revision=REV,
        owner_approval_sha256=approval,
        verifier_receipt_sha256=verifier,
        verified_at=NOW.isoformat(),
        provenance=prov("tests.strict-owner", REV, NOW, approval, verifier),
    )

    if add_inconsistent_extras:
        extra_log = "c" * 64
        workflows.append(
            WorkflowRunEvidence(
                workflow_id="optional-nightly",
                run_id=11,
                source_revision="f" * 40,
                conclusion="failure",
                completed_at=NOW.isoformat(),
                expires_at=(NOW + timedelta(days=1)).isoformat(),
                logs_sha256=extra_log,
                artifact_sha256s=(),
                provenance=prov(
                    "tests.strict-extra-workflow",
                    "f" * 40,
                    NOW,
                    extra_log,
                ),
            )
        )
        mismatch_content = "d" * 64
        mismatch_locator = "e" * 64
        artifacts.append(
            ArtifactEvidence(
                artifact_id="extra-source",
                artifact_kind="source-archive",
                source_revision=REV,
                source_tree_revision=TREE,
                content_sha256=mismatch_content,
                locator=f"artifact-locator:sha256:{mismatch_locator}",
                built_at=NOW.isoformat(),
                provenance=prov(
                    "tests.strict-extra-artifact",
                    REV,
                    NOW,
                    mismatch_content,
                    mismatch_locator,
                ),
            )
        )
        extra_envelope = "0" * 64
        runtimes.append(
            RuntimeEnvelopeEvidence(
                runtime_id="ollama-http",
                envelope_sha256=extra_envelope,
                source_revision=REV,
                authority="offline-fixture",
                status="failed",
                observed_at=NOW.isoformat(),
                expires_at=(NOW + timedelta(days=1)).isoformat(),
                provenance=prov(
                    "tests.strict-extra-runtime", REV, NOW, extra_envelope
                ),
            )
        )

    plan = "a" * 64
    registry = "b" * 64
    retained = [
        plan,
        registry,
        *(item.digest for item in workflows),
        *(item.digest for item in artifacts),
        *(item.digest for item in runtimes),
        *(item.digest for item in faults),
        *(item.digest for item in reviews),
        owner.digest,
    ]
    return GateEvidenceIndex(
        index_id="strict-gate0",
        gate=0,
        source_revision=REV,
        source_tree_revision=TREE,
        iron_plan_sha256=plan,
        registry_sha256=registry,
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        required_workflow_ids=("iron-plan",),
        required_artifact_kinds=("wheel",),
        required_runtime_ids=("claude-code-cli",),
        required_fault_matrix_ids=("gate0-faults",),
        required_review_perspectives=("architecture", "security"),
        workflows=tuple(workflows),
        artifacts=tuple(artifacts),
        runtimes=tuple(runtimes),
        fault_matrices=tuple(faults),
        reviews=tuple(reviews),
        owner_decision=owner,
        provenance=prov("tests.strict-index", REV, NOW, *retained),
    )


def trust_sets(value: GateEvidenceIndex) -> dict[str, tuple[str, ...]]:
    assert value.owner_decision is not None
    return {
        "trusted_requirements_sha256s": (evidence_requirements_sha256(value),),
        "trusted_iron_plan_sha256s": (value.iron_plan_sha256,),
        "trusted_registry_sha256s": (value.registry_sha256,),
        "trusted_workflow_evidence_sha256s": tuple(
            item.digest for item in value.workflows
        ),
        "trusted_artifact_sha256s": tuple(
            item.content_sha256 for item in value.artifacts
        ),
        "trusted_runtime_envelope_sha256s": tuple(
            item.envelope_sha256 for item in value.runtimes
        ),
        "trusted_fault_matrix_sha256s": tuple(
            item.matrix_sha256 for item in value.fault_matrices
        ),
        "trusted_review_transcript_sha256s": tuple(
            item.transcript_sha256 for item in value.reviews
        ),
        "trusted_owner_verifier_sha256s": (
            value.owner_decision.verifier_receipt_sha256,
        ),
    }


def test_strict_verifier_accepts_only_trusted_coherent_exact_head() -> None:
    value = build_index()
    trusted = trust_sets(value)
    assert strict_mechanical_blockers(
        value,
        current_revision=REV,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
        **trusted,
    ) == ()
    assert_strict_exact_head(
        value,
        current_revision=REV,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
        **trusted,
    )


def test_empty_external_trust_sets_fail_closed() -> None:
    value = build_index()
    blockers = strict_mechanical_blockers(
        value,
        current_revision=REV,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
    )
    assert "index:untrusted-requirements" in blockers
    assert "index:untrusted-iron-plan" in blockers
    assert "index:untrusted-registry" in blockers
    assert "workflow:iron-plan:untrusted-evidence" in blockers
    assert "artifact:wheel:untrusted-content" in blockers
    assert "runtime:claude-code-cli:untrusted-envelope" in blockers
    assert "fault-matrix:gate0-faults:untrusted-matrix" in blockers
    assert "review:architecture:untrusted-transcript" in blockers
    assert "owner-decision:untrusted-verifier-receipt" in blockers


def test_candidate_cannot_shrink_requirements_without_external_adoption() -> None:
    value = build_index()
    trusted = trust_sets(value)
    trusted["trusted_requirements_sha256s"] = ("f" * 64,)
    blockers = strict_mechanical_blockers(
        value,
        current_revision=REV,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
        **trusted,
    )
    assert "index:untrusted-requirements" in blockers


def test_inconsistent_extra_evidence_cannot_be_silently_ignored() -> None:
    value = build_index(add_inconsistent_extras=True)
    blockers = strict_mechanical_blockers(
        value,
        current_revision=REV,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
        **trust_sets(value),
    )
    assert "workflow:optional-nightly:foreign-source-revision" in blockers
    assert "workflow:optional-nightly:conclusion-failure" in blockers
    assert "artifact:source-archive:locator-content-mismatch" in blockers
    assert "runtime:ollama-http:non-live-authority" in blockers
    assert "runtime:ollama-http:status-failed" in blockers
    with pytest.raises(ValueError, match="Gate evidence index has blocker"):
        assert_strict_exact_head(
            value,
            current_revision=REV,
            current_tree_revision=TREE,
            now=NOW + timedelta(minutes=1),
            **trust_sets(value),
        )


def test_naive_verification_time_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        strict_mechanical_blockers(
            build_index(),
            current_revision=REV,
            current_tree_revision=TREE,
            now=datetime(2026, 8, 3, 3, 1),
        )
