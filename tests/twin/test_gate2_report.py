from __future__ import annotations

import json

import pytest

from daedalus.twin.corpus_genesis import CorpusGenesisBinding
from daedalus.twin.gate2_report import (
    Gate2Report,
    Gate2ReportError,
    WorkflowEvidence,
    assert_monotonic_gate2_report,
    build_gate2_report,
)
from daedalus.twin.motifs import CrossRepositoryAlignment, MotifProvenance, MotifSupport

HEAD = "1" * 40
OTHER_HEAD = "2" * 40
SHA = "a" * 64


def binding(*, reviewed: bool = True, repository_id: str = "tokio") -> CorpusGenesisBinding:
    return CorpusGenesisBinding(
        repository_id=repository_id,
        source_revision="3" * 40,
        project_twin_manifest_sha256="1" * 64,
        genesis_receipt_sha256="2" * 64,
        evidence_packet_sha256="3" * 64,
        corpus_manifest_sha256="4" * 64,
        corpus_repository_sha256="5" * 64,
        capability_matrix_sha256="6" * 64,
        review_state="reviewed" if reviewed else "declared",
        review_evidence="sha256:" + "7" * 64 if reviewed else None,
        language_ids=("rust",),
        blockers=() if reviewed else ("corpus-review-declared",),
    )


def motif(*, verified: bool = True) -> MotifProvenance:
    left = MotifSupport(
        repository_id="spring-framework",
        source_revision="4" * 40,
        project_twin_manifest_sha256="4" * 64,
        subgraph_sha256="5" * 64,
        license_spdx="Apache-2.0",
        extractor_contract_sha256="6" * 64,
        evidence_sha256="7" * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )
    right = MotifSupport(
        repository_id="tokio",
        source_revision="5" * 40,
        project_twin_manifest_sha256="8" * 64,
        subgraph_sha256="9" * 64,
        license_spdx="MIT",
        extractor_contract_sha256="a" * 64,
        evidence_sha256="b" * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )
    first, second = sorted((left.digest, right.digest))
    alignment = CrossRepositoryAlignment(
        left_support_sha256=first,
        right_support_sha256=second,
        mapping_sha256="c" * 64,
        algorithm_contract_sha256="d" * 64,
        status="verified" if verified else "rejected",
        evidence_sha256="e" * 64 if verified else None,
        limitation=None if verified else "alignment failed the invariant check",
    )
    return MotifProvenance(
        schema="daedalus-motif-provenance/1",
        motif_id="bounded-service-lifecycle",
        supports=(left, right),
        alignments=(alignment,),
        invariant_sha256s=("d" * 64,),
        negative_example_sha256s=("e" * 64,),
        evaluator_evidence_sha256s=("f" * 64,),
    )


def checks(*, head: str = HEAD, corpus_conclusion: str = "success") -> tuple[WorkflowEvidence, ...]:
    return (
        WorkflowEvidence("Gate 2 Corpus Pilot", 101, head, corpus_conclusion, "8" * 64),
        WorkflowEvidence("Gate 2 Project Twin", 102, head, "success", "9" * 64),
        WorkflowEvidence("Iron Plan", 103, head, "success", "a" * 64),
    )


def report(*, reviewed: bool = True, verified_motif: bool = True, head: str = HEAD) -> Gate2Report:
    return build_gate2_report(
        head_sha=head,
        iron_plan_sha256=SHA,
        workflow_evidence=checks(head=head),
        bindings=(binding(reviewed=reviewed),),
        motifs=(motif(verified=verified_motif),),
    )


def test_report_closes_only_for_exact_green_reviewed_evidence_and_verified_motif() -> None:
    value = report()
    assert value.closed
    assert value.blockers == ()
    assert Gate2Report.from_json_bytes(value.to_json_bytes()) == value


def test_declared_corpus_binding_remains_a_mechanical_blocker() -> None:
    value = report(reviewed=False)
    assert not value.closed
    assert value.blockers == ("binding-tokio-corpus-review-declared",)


def test_rejected_motif_alignment_remains_a_mechanical_blocker() -> None:
    value = report(verified_motif=False)
    assert not value.closed
    assert value.blockers == (
        "motif-bounded-service-lifecycle-no-verified-cross-repository-alignment",
        "motif-bounded-service-lifecycle-support-spring-framework-unaligned",
        "motif-bounded-service-lifecycle-support-tokio-unaligned",
    )


def test_missing_failed_and_stale_workflows_are_visible_blockers() -> None:
    evidence = (
        WorkflowEvidence("Gate 2 Corpus Pilot", 101, HEAD, "failure", "8" * 64),
        WorkflowEvidence("Iron Plan", 103, OTHER_HEAD, "success", "a" * 64),
    )
    value = build_gate2_report(
        head_sha=HEAD,
        iron_plan_sha256=SHA,
        workflow_evidence=evidence,
        bindings=(binding(),),
        motifs=(motif(),),
    )
    assert value.blockers == (
        "workflow-gate-2-corpus-pilot-failure",
        "workflow-gate-2-project-twin-missing",
        "workflow-iron-plan-stale-head",
    )


def test_report_refuses_missing_motif_duplicate_or_unknown_workflow_evidence() -> None:
    with pytest.raises(Gate2ReportError, match="motif provenance"):
        build_gate2_report(
            head_sha=HEAD,
            iron_plan_sha256=SHA,
            workflow_evidence=checks(),
            bindings=(binding(),),
            motifs=(),
        )
    duplicate = checks() + (checks()[0],)
    with pytest.raises(Gate2ReportError, match="unique"):
        build_gate2_report(
            head_sha=HEAD,
            iron_plan_sha256=SHA,
            workflow_evidence=duplicate,
            bindings=(binding(),),
            motifs=(motif(),),
        )
    with pytest.raises(Gate2ReportError, match="required"):
        WorkflowEvidence("Other Workflow", 1, HEAD, "success", SHA)


def test_closed_field_is_derived_and_noncanonical_bytes_refuse() -> None:
    value = report()
    payload = value.to_dict()
    payload["closed"] = False
    with pytest.raises(Gate2ReportError, match="derived"):
        Gate2Report.from_dict(payload)
    pretty = (json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(Gate2ReportError, match="canonical JSON"):
        Gate2Report.from_json_bytes(pretty)


def test_monotonicity_refuses_competing_exact_head_and_evidence_loss() -> None:
    closed = report()
    competing = build_gate2_report(
        head_sha=HEAD,
        iron_plan_sha256=SHA,
        workflow_evidence=checks(),
        bindings=(binding(),),
        motifs=(motif(),),
        external_constraints=("legacy-python313-not-portable",),
    )
    with pytest.raises(Gate2ReportError, match="competing"):
        assert_monotonic_gate2_report(closed, competing)

    evidence_loss = build_gate2_report(
        head_sha=OTHER_HEAD,
        iron_plan_sha256=SHA,
        workflow_evidence=checks(head=OTHER_HEAD),
        bindings=(binding(reviewed=False),),
        motifs=(motif(),),
    )
    with pytest.raises(Gate2ReportError, match="drops previously retained binding"):
        assert_monotonic_gate2_report(closed, evidence_loss)


def test_monotonicity_refuses_closed_to_open_regression_with_retained_evidence() -> None:
    closed = report()
    regressed = Gate2Report(
        schema="daedalus-gate2-report/1",
        head_sha=OTHER_HEAD,
        iron_plan_sha256=closed.iron_plan_sha256,
        workflow_evidence=checks(head=OTHER_HEAD),
        binding_sha256s=closed.binding_sha256s,
        motif_provenance_sha256s=closed.motif_provenance_sha256s,
        blockers=("manual-regression",),
        external_constraints=(),
    )
    with pytest.raises(Gate2ReportError, match="cannot regress"):
        assert_monotonic_gate2_report(closed, regressed)
