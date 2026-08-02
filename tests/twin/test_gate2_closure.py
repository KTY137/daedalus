from __future__ import annotations

import dataclasses

import pytest

from daedalus.twin.corpus_genesis import CorpusGenesisBinding
from daedalus.twin.gate2_closure import (
    Gate2ClosureApproval,
    Gate2ClosureError,
    Gate2ClosureLedger,
    verify_gate2_closure_approval,
)
from daedalus.twin.gate2_report import WorkflowEvidence, build_gate2_report
from daedalus.twin.motifs import CrossRepositoryAlignment, MotifProvenance, MotifSupport

HEAD = "1" * 40
SHA = "a" * 64
ISSUED = "2026-08-02T10:00:00Z"
EXPIRES = "2026-08-02T11:00:00Z"
NOW = "2026-08-02T10:30:00Z"


def binding(*, reviewed: bool = True) -> CorpusGenesisBinding:
    return CorpusGenesisBinding(
        repository_id="tokio",
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


def motif() -> MotifProvenance:
    left = MotifSupport(
        repository_id="spring-framework",
        source_revision="1" * 40,
        project_twin_manifest_sha256="1" * 64,
        subgraph_sha256="2" * 64,
        license_spdx="Apache-2.0",
        extractor_contract_sha256="3" * 64,
        evidence_sha256="4" * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )
    right = MotifSupport(
        repository_id="tokio",
        source_revision="2" * 40,
        project_twin_manifest_sha256="5" * 64,
        subgraph_sha256="6" * 64,
        license_spdx="MIT",
        extractor_contract_sha256="7" * 64,
        evidence_sha256="8" * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )
    first, second = sorted((left.digest, right.digest))
    alignment = CrossRepositoryAlignment(
        left_support_sha256=first,
        right_support_sha256=second,
        mapping_sha256="9" * 64,
        algorithm_contract_sha256="a" * 64,
        status="verified",
        evidence_sha256="b" * 64,
        limitation=None,
    )
    return MotifProvenance(
        schema="daedalus-motif-provenance/1",
        motif_id="service-lifecycle",
        supports=(left, right),
        alignments=(alignment,),
        invariant_sha256s=("c" * 64,),
        negative_example_sha256s=("d" * 64,),
        evaluator_evidence_sha256s=("e" * 64,),
    )


def report(*, reviewed: bool = True):
    checks = (
        WorkflowEvidence("Gate 2 Corpus Pilot", 101, HEAD, "success", "8" * 64),
        WorkflowEvidence("Gate 2 Project Twin", 102, HEAD, "success", "9" * 64),
        WorkflowEvidence("Iron Plan", 103, HEAD, "success", "a" * 64),
    )
    return build_gate2_report(
        head_sha=HEAD,
        iron_plan_sha256=SHA,
        workflow_evidence=checks,
        bindings=(binding(reviewed=reviewed),),
        motifs=(motif(),),
    )


def approval(value) -> Gate2ClosureApproval:
    return Gate2ClosureApproval(
        head_sha=value.head_sha,
        iron_plan_sha256=value.iron_plan_sha256,
        report_sha256=value.digest,
        evidence_packet_sha256="3" * 64,
        corpus_manifest_sha256="4" * 64,
        capability_matrix_sha256="6" * 64,
        motif_provenance_sha256s=value.motif_provenance_sha256s,
        workflow_run_ids=tuple((item.workflow_name, item.run_id) for item in value.workflow_evidence),
        target_state="gate-2-closed",
        issued_at=ISSUED,
        expires_at=EXPIRES,
        nonce="gate2-closure-nonce-0001",
    )


def verify(value, token, *, now: str = NOW) -> None:
    verify_gate2_closure_approval(
        approval=token,
        report=value,
        evidence_packet_sha256="3" * 64,
        corpus_manifest_sha256="4" * 64,
        capability_matrix_sha256="6" * 64,
        now=now,
    )


def test_exact_closed_report_approval_round_trips_and_verifies() -> None:
    value = report()
    token = approval(value)
    assert Gate2ClosureApproval.from_json_bytes(token.to_json_bytes()) == token
    verify(value, token)


def test_open_report_cannot_be_approved() -> None:
    value = report(reviewed=False)
    token = approval(value)
    with pytest.raises(Gate2ClosureError, match="open Gate-2 report"):
        verify(value, token)


@pytest.mark.parametrize(
    ("field", "replacement", "expected"),
    (
        ("head_sha", "2" * 40, "head_sha"),
        ("report_sha256", "f" * 64, "report"),
        ("evidence_packet_sha256", "f" * 64, "evidence_packet"),
        ("corpus_manifest_sha256", "f" * 64, "corpus_manifest"),
        ("capability_matrix_sha256", "f" * 64, "capability_matrix"),
        ("workflow_run_ids", (("Gate 2 Corpus Pilot", 999), ("Gate 2 Project Twin", 102), ("Iron Plan", 103)), "workflow_runs"),
    ),
)
def test_substitution_and_stale_run_bindings_refuse(field, replacement, expected) -> None:
    value = report()
    token = dataclasses.replace(approval(value), **{field: replacement})
    with pytest.raises(Gate2ClosureError, match=expected):
        verify(value, token)


def test_expired_and_not_yet_valid_approvals_refuse() -> None:
    value = report()
    token = approval(value)
    with pytest.raises(Gate2ClosureError, match="expired"):
        verify(value, token, now=EXPIRES)
    with pytest.raises(Gate2ClosureError, match="not_yet_valid"):
        verify(value, token, now="2026-08-02T09:59:59Z")


def test_ledger_consumes_nonce_once_and_persists_canonical_receipt(tmp_path) -> None:
    value = report()
    token = approval(value)
    ledger = Gate2ClosureLedger(tmp_path)
    path = ledger.consume(
        approval=token,
        report=value,
        evidence_packet_sha256="3" * 64,
        corpus_manifest_sha256="4" * 64,
        capability_matrix_sha256="6" * 64,
        now=NOW,
    )
    assert path.is_file()
    assert token.digest.encode() in path.read_bytes()
    with pytest.raises(Gate2ClosureError, match="already been consumed"):
        ledger.consume(
            approval=token,
            report=value,
            evidence_packet_sha256="3" * 64,
            corpus_manifest_sha256="4" * 64,
            capability_matrix_sha256="6" * 64,
            now=NOW,
        )


def test_nonce_and_target_state_are_strict() -> None:
    value = report()
    with pytest.raises(Gate2ClosureError, match="nonce"):
        dataclasses.replace(approval(value), nonce="short")
    with pytest.raises(Gate2ClosureError, match="target_state"):
        dataclasses.replace(approval(value), target_state="gate-3-open")
