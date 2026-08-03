from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

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
NOW = datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc)
PLAN = "1" * 64
REGISTRY = "2" * 64


def provenance(
    origin: str,
    *digests: str,
    created_at: datetime = NOW,
    revision: str = REVISION,
) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=created_at.isoformat(),
        input_digests=tuple(sorted(set(digests))),
    )


def workflow(
    workflow_id: str = "iron-plan",
    *,
    conclusion: str = "success",
    revision: str = REVISION,
    expires_at: datetime | None = None,
) -> WorkflowRunEvidence:
    logs = "3" * 64
    artifact = "4" * 64
    return WorkflowRunEvidence(
        workflow_id=workflow_id,
        run_id=100,
        source_revision=revision,
        conclusion=conclusion,
        completed_at=NOW.isoformat(),
        expires_at=(expires_at or NOW + timedelta(days=7)).isoformat(),
        logs_sha256=logs,
        artifact_sha256s=(artifact,),
        provenance=provenance("tests.workflow", logs, artifact, revision=revision),
    )


def artifact(
    kind: str = "wheel",
    *,
    revision: str = REVISION,
    tree: str = TREE,
) -> ArtifactEvidence:
    content = "5" * 64
    locator_digest = "6" * 64
    return ArtifactEvidence(
        artifact_id=f"artifact-{kind}",
        artifact_kind=kind,
        source_revision=revision,
        source_tree_revision=tree,
        content_sha256=content,
        locator=f"artifact-locator:sha256:{locator_digest}",
        built_at=NOW.isoformat(),
        provenance=provenance(
            "tests.artifact", content, locator_digest, revision=revision
        ),
    )


def runtime(
    runtime_id: str = "claude-code-cli",
    *,
    authority: str = "live-runtime",
    status: str = "passed",
    revision: str = REVISION,
    expires_at: datetime | None = None,
) -> RuntimeEnvelopeEvidence:
    envelope = "7" * 64
    return RuntimeEnvelopeEvidence(
        runtime_id=runtime_id,
        envelope_sha256=envelope,
        source_revision=revision,
        authority=authority,
        status=status,
        observed_at=NOW.isoformat(),
        expires_at=(expires_at or NOW + timedelta(days=1)).isoformat(),
        provenance=provenance("tests.runtime", envelope, revision=revision),
    )


def fault(
    matrix_id: str = "gate0-faults",
    *,
    status: str = "passed",
    revision: str = REVISION,
) -> FaultMatrixEvidence:
    matrix = "8" * 64
    return FaultMatrixEvidence(
        matrix_id=matrix_id,
        source_revision=revision,
        status=status,
        matrix_sha256=matrix,
        scenario_ids=("approval-replay", "target-head-race"),
        executed_at=NOW.isoformat(),
        provenance=provenance("tests.fault", matrix, revision=revision),
    )


def review(
    review_id: str,
    perspective: str,
    *,
    assurance: str = "human",
    verdict: str = "passed",
    findings: tuple[str, ...] = (),
    revision: str = REVISION,
) -> ReviewEvidence:
    transcript = ("9" if perspective == "architecture" else "c") * 64
    return ReviewEvidence(
        review_id=review_id,
        perspective=perspective,
        assurance=assurance,
        source_revision=revision,
        verdict=verdict,
        unresolved_finding_ids=findings,
        transcript_sha256=transcript,
        reviewed_at=NOW.isoformat(),
        provenance=provenance("tests.review", transcript, revision=revision),
    )


def owner(*, revision: str = REVISION) -> OwnerDecisionEvidence:
    approval = "d" * 64
    verifier = "e" * 64
    return OwnerDecisionEvidence(
        decision_id="owner-gate0-close",
        source_revision=revision,
        owner_approval_sha256=approval,
        verifier_receipt_sha256=verifier,
        verified_at=NOW.isoformat(),
        provenance=provenance(
            "tests.owner-decision", approval, verifier, revision=revision
        ),
    )


def index(**changes) -> GateEvidenceIndex:
    values = {
        "index_id": "gate0-exact-head",
        "gate": 0,
        "source_revision": REVISION,
        "source_tree_revision": TREE,
        "iron_plan_sha256": PLAN,
        "registry_sha256": REGISTRY,
        "generated_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "required_workflow_ids": ("iron-plan",),
        "required_artifact_kinds": ("wheel",),
        "required_runtime_ids": ("claude-code-cli",),
        "required_fault_matrix_ids": ("gate0-faults",),
        "required_review_perspectives": ("architecture", "security"),
        "workflows": (workflow(),),
        "artifacts": (artifact(),),
        "runtimes": (runtime(),),
        "fault_matrices": (fault(),),
        "reviews": (
            review("architecture-review", "architecture"),
            review("security-review", "security"),
        ),
        "owner_decision": owner(),
    }
    values.update(changes)
    retained = [
        PLAN,
        REGISTRY,
        *(item.digest for item in values["workflows"]),
        *(item.digest for item in values["artifacts"]),
        *(item.digest for item in values["runtimes"]),
        *(item.digest for item in values["fault_matrices"]),
        *(item.digest for item in values["reviews"]),
    ]
    if values["owner_decision"] is not None:
        retained.append(values["owner_decision"].digest)
    values["provenance"] = provenance(
        "tests.gate-evidence-index",
        *retained,
        created_at=NOW,
        revision=values["source_revision"],
    )
    return GateEvidenceIndex(**values)


def test_complete_exact_head_index_is_deterministic_and_round_trips() -> None:
    first = index()
    second = index()
    assert first.digest == second.digest
    assert first.to_dict() == second.to_dict()
    assert GateEvidenceIndex.from_dict(first.to_dict()) == first
    assert first.mechanical_blockers(
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(hours=1),
    ) == ()


def test_missing_failed_stale_and_foreign_evidence_are_explicit_blockers() -> None:
    value = index(
        workflows=(workflow(conclusion="failure"),),
        artifacts=(artifact(tree="f" * 40),),
        runtimes=(
            runtime(
                authority="offline-fixture",
                status="failed",
                expires_at=NOW + timedelta(minutes=30),
            ),
        ),
        fault_matrices=(fault(status="failed"),),
        reviews=(
            review(
                "architecture-model-review",
                "architecture",
                assurance="model-opinion",
            ),
            review(
                "security-review",
                "security",
                verdict="changes-requested",
                findings=("finding-1",),
            ),
        ),
        owner_decision=None,
    )
    blockers = value.mechanical_blockers(
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(hours=1),
    )
    assert "workflow:iron-plan:conclusion-failure" in blockers
    assert "artifact:wheel:foreign-source-tree" in blockers
    assert "runtime:claude-code-cli:non-live-authority" in blockers
    assert "runtime:claude-code-cli:status-failed" in blockers
    assert "runtime:claude-code-cli:expired" in blockers
    assert "fault-matrix:gate0-faults:status-failed" in blockers
    assert "review:architecture:no-human-pass" in blockers
    assert "review:security:changes-requested" in blockers
    assert "review:security:unresolved-findings" in blockers
    assert "owner-decision:missing" in blockers


def test_current_head_and_index_expiry_are_rechecked_at_verification_time() -> None:
    value = index()
    blockers = value.mechanical_blockers(
        current_revision="f" * 40,
        current_tree_revision="0" * 40,
        now=NOW + timedelta(days=2),
    )
    assert "index:foreign-source-revision" in blockers
    assert "index:foreign-source-tree" in blockers
    assert "index:expired" in blockers
    assert "workflow:iron-plan:foreign-source-revision" in blockers
    assert "artifact:wheel:foreign-source-revision" in blockers
    assert "runtime:claude-code-cli:foreign-source-revision" in blockers
    assert "fault-matrix:gate0-faults:foreign-source-revision" in blockers
    assert "owner-decision:foreign-source-revision" in blockers


def test_duplicate_ambiguous_evidence_is_refused() -> None:
    first = workflow()
    second = dataclasses.replace(first, run_id=101)
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        index(workflows=(first, second))
    with pytest.raises(ValueError, match="ambiguous duplicate"):
        index(artifacts=(artifact(), dataclasses.replace(artifact(), artifact_id="other")))


def test_provenance_and_timestamp_repackaging_are_refused() -> None:
    value = workflow()
    with pytest.raises(ValueError, match="completed_at contradicts"):
        dataclasses.replace(
            value,
            completed_at=(NOW + timedelta(seconds=1)).isoformat(),
        )
    with pytest.raises(ValueError, match="does not bind"):
        dataclasses.replace(
            value,
            provenance=dataclasses.replace(value.provenance, input_digests=()),
        )


def test_tampered_serialized_index_cannot_round_trip() -> None:
    value = index()
    payload = value.to_dict()
    payload["source_revision"] = "f" * 40
    with pytest.raises(ValueError, match="contradicts provenance"):
        GateEvidenceIndex.from_dict(payload)


def test_model_opinion_is_retained_but_never_satisfies_hard_review() -> None:
    value = index(
        reviews=(
            review(
                "architecture-model",
                "architecture",
                assurance="model-opinion",
            ),
            review("security-human", "security"),
        )
    )
    blockers = value.mechanical_blockers(
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(minutes=1),
    )
    assert "review:architecture:no-human-pass" in blockers
    assert "review:security:no-human-pass" not in blockers
