from __future__ import annotations

import concurrent.futures
import dataclasses

import pytest

from daedalus.kernel.approvals import ApprovalReplay, ApprovalSignatureError, issue_owner_approval
from daedalus.schemas import ContractProvenance
from daedalus.twin.corpus import CorpusManifest, CorpusRepository
from daedalus.twin.corpus_genesis import CorpusGenesisBinding
from daedalus.twin.gate2_closure import (
    Gate2ClosureApproval,
    Gate2ClosureError,
    Gate2ClosureLedger,
    owner_approval_expectation,
    verify_gate2_closure_approval,
)
from daedalus.twin.gate2_report import WorkflowEvidence, build_gate2_report
from daedalus.twin.motifs import CrossRepositoryAlignment, MotifProvenance, MotifSupport

HEAD = "1" * 40
SHA = "a" * 64
ISSUED = "2026-08-02T10:00:00Z"
EXPIRES = "2026-08-02T11:00:00Z"
NOW = "2026-08-02T10:30:00Z"
SECRET = b"gate-two-owner-secret-material-at-least-thirty-two-bytes"
KEYRING = {("repository-owner", "gate2-owner-key"): SECRET}


def corpus() -> CorpusManifest:
    return CorpusManifest(
        schema="daedalus-corpus-manifest/1",
        corpus_id="gate2-closure-fixture",
        repositories=(
            CorpusRepository(
                repository_id="spring-framework",
                repository_url="https://github.com/spring-projects/spring-framework.git",
                source_revision="4" * 40,
                include_prefixes=("spring-core",),
                language_ids=("java",),
                license_spdx="Apache-2.0",
                license_path="LICENSE.txt",
                review_state="reviewed",
                review_evidence="sha256:" + "1" * 64,
            ),
            CorpusRepository(
                repository_id="tokio",
                repository_url="https://github.com/tokio-rs/tokio.git",
                source_revision="5" * 40,
                include_prefixes=("tokio",),
                language_ids=("rust",),
                license_spdx="MIT",
                license_path="LICENSE",
                review_state="reviewed",
                review_evidence="sha256:" + "2" * 64,
            ),
        ),
    )


def binding(source: CorpusManifest, repository_id: str, *, reviewed: bool = True) -> CorpusGenesisBinding:
    repository = next(item for item in source.repositories if item.repository_id == repository_id)
    values = {
        "spring-framework": ("4", "5", "6", "7", ("java",)),
        "tokio": ("8", "9", "a", "b", ("rust",)),
    }[repository_id]
    manifest_digit, receipt_digit, evidence_digit, repository_digit, languages = values
    return CorpusGenesisBinding(
        repository_id=repository_id,
        source_revision=repository.source_revision,
        project_twin_manifest_sha256=manifest_digit * 64,
        genesis_receipt_sha256=receipt_digit * 64,
        evidence_packet_sha256=evidence_digit * 64,
        corpus_manifest_sha256=source.digest,
        corpus_repository_sha256=repository_digit * 64,
        capability_matrix_sha256="c" * 64,
        review_state="reviewed" if reviewed else "declared",
        review_evidence="sha256:" + "d" * 64 if reviewed else None,
        language_ids=languages,
        blockers=() if reviewed else ("corpus-review-declared",),
    )


def motif() -> MotifProvenance:
    left = MotifSupport(
        repository_id="spring-framework",
        source_revision="4" * 40,
        project_twin_manifest_sha256="4" * 64,
        subgraph_sha256="2" * 64,
        license_spdx="Apache-2.0",
        extractor_contract_sha256="3" * 64,
        evidence_sha256="4" * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )
    right = MotifSupport(
        repository_id="tokio",
        source_revision="5" * 40,
        project_twin_manifest_sha256="8" * 64,
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
    source = corpus()
    checks = (
        WorkflowEvidence("Gate 2 Corpus Pilot", 101, HEAD, "success", "8" * 64),
        WorkflowEvidence("Gate 2 Project Twin", 102, HEAD, "success", "9" * 64),
        WorkflowEvidence("Iron Plan", 103, HEAD, "success", "a" * 64),
    )
    return build_gate2_report(
        head_sha=HEAD,
        iron_plan_sha256=SHA,
        corpus_manifest=source,
        workflow_evidence=checks,
        bindings=(
            binding(source, "spring-framework"),
            binding(source, "tokio", reviewed=reviewed),
        ),
        motifs=(motif(),),
    )


def closure(value, **changes) -> Gate2ClosureApproval:
    values = dict(
        head_sha=value.head_sha,
        iron_plan_sha256=value.iron_plan_sha256,
        report_sha256=value.digest,
        evidence_packet_sha256="a" * 64,
        corpus_manifest_sha256=value.corpus_manifest_sha256,
        capability_matrix_sha256="c" * 64,
        motif_provenance_sha256s=value.motif_provenance_sha256s,
        workflow_run_ids=tuple((item.workflow_name, item.run_id) for item in value.workflow_evidence),
        target_state="gate-2-closed",
        issued_at=ISSUED,
        expires_at=EXPIRES,
        nonce="gate2-closure-nonce-0001",
    )
    values.update(changes)
    return Gate2ClosureApproval(**values)


def signed_owner_approval(value, token, **changes):
    expectation = owner_approval_expectation(closure=token, report=value)
    values = dict(
        approval_id="gate2-closure-approval-001",
        owner_id="repository-owner",
        key_id="gate2-owner-key",
        operation=expectation.operation,
        nomination_receipt_sha256=expectation.nomination_receipt_sha256,
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        evidence_packet_sha256=expectation.evidence_packet_sha256,
        base_revision=expectation.base_revision,
        target_ref=expectation.target_ref,
        expected_target_revision=expectation.current_target_revision,
        nonce=token.nonce,
        issued_at=token.issued_at,
        expires_at=token.expires_at,
        provenance=ContractProvenance(
            origin="tests.gate2-closure",
            source_revision=value.head_sha,
            created_at=ISSUED,
            input_digests=(value.digest, token.digest, token.evidence_packet_sha256),
        ),
        secret=SECRET,
    )
    values.update(changes)
    return issue_owner_approval(**values)


def verify(value, token, owner=None, *, now=NOW, keyring=KEYRING):
    return verify_gate2_closure_approval(
        closure=token,
        owner_approval=owner or signed_owner_approval(value, token),
        keyring=keyring,
        report=value,
        evidence_packet_sha256=token.evidence_packet_sha256,
        corpus_manifest_sha256=value.corpus_manifest_sha256,
        capability_matrix_sha256=token.capability_matrix_sha256,
        now=now,
    )


def consume(ledger, value, token, owner=None):
    return ledger.consume(
        closure=token,
        owner_approval=owner or signed_owner_approval(value, token),
        keyring=KEYRING,
        report=value,
        evidence_packet_sha256=token.evidence_packet_sha256,
        corpus_manifest_sha256=value.corpus_manifest_sha256,
        capability_matrix_sha256=token.capability_matrix_sha256,
        now=NOW,
    )


def test_exact_signed_complete_report_round_trips_and_verifies() -> None:
    value = report()
    token = closure(value)
    assert Gate2ClosureApproval.from_json_bytes(token.to_json_bytes()) == token
    verified = verify(value, token)
    assert verified.operation == "close-gate-2"
    assert verified.candidate_artifact_sha256 == token.digest


def test_incomplete_corpus_report_cannot_be_approved_even_with_valid_signature() -> None:
    value = report(reviewed=False)
    token = closure(value)
    owner = signed_owner_approval(value, token)
    with pytest.raises(Gate2ClosureError, match="open Gate-2 report"):
        verify(value, token, owner)


def test_forged_signature_and_unknown_key_refuse() -> None:
    value = report()
    token = closure(value)
    owner = signed_owner_approval(value, token)
    with pytest.raises(ApprovalSignatureError, match="signature mismatch"):
        verify(value, token, dataclasses.replace(owner, signature_sha256="f" * 64))
    with pytest.raises(ApprovalSignatureError, match="unknown"):
        verify(value, token, owner, keyring={})


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
def test_closure_detail_substitution_refuses(field, replacement, expected) -> None:
    value = report()
    original = closure(value)
    owner = signed_owner_approval(value, original)
    with pytest.raises(Gate2ClosureError, match=expected):
        verify(value, dataclasses.replace(original, **{field: replacement}), owner)


def test_owner_envelope_and_detail_time_substitution_refuse() -> None:
    value = report()
    token = closure(value)
    with pytest.raises(Exception, match="target_ref"):
        verify(value, token, signed_owner_approval(value, token, target_ref="experimental"))
    with pytest.raises(Gate2ClosureError, match="nonce"):
        verify(value, token, signed_owner_approval(value, token, nonce="gate2-closure-nonce-9999"))
    with pytest.raises(Gate2ClosureError, match="expires_at"):
        verify(value, token, signed_owner_approval(value, token, expires_at="2026-08-02T10:45:00Z"))


def test_expired_and_not_yet_valid_details_refuse() -> None:
    value = report()
    token = closure(value)
    owner = signed_owner_approval(value, token)
    with pytest.raises(Gate2ClosureError, match="expired"):
        verify(value, token, owner, now=EXPIRES)
    with pytest.raises(Gate2ClosureError, match="not_yet_valid"):
        verify(value, token, owner, now="2026-08-02T09:59:59Z")


def test_ledger_consumes_authenticated_closure_once(tmp_path) -> None:
    value = report()
    token = closure(value)
    owner = signed_owner_approval(value, token)
    ledger = Gate2ClosureLedger(tmp_path / "gate2-closure.sqlite3")
    receipt = consume(ledger, value, token, owner)
    assert receipt.closure_approval_sha256 == token.digest
    assert ledger.closed(value.digest)
    with pytest.raises(ApprovalReplay, match="already consumed"):
        consume(ledger, value, token, owner)


def test_repackaging_or_new_nonce_cannot_reclose_same_report(tmp_path) -> None:
    value = report()
    token = closure(value)
    ledger = Gate2ClosureLedger(tmp_path / "gate2-closure.sqlite3")
    consume(ledger, value, token, signed_owner_approval(value, token))
    with pytest.raises(ApprovalReplay):
        consume(ledger, value, token, signed_owner_approval(value, token, approval_id="gate2-closure-approval-002"))
    new_token = closure(value, nonce="gate2-closure-nonce-0002")
    with pytest.raises(ApprovalReplay):
        consume(ledger, value, new_token, signed_owner_approval(value, new_token, approval_id="gate2-closure-approval-003"))


def test_concurrent_consumption_allows_exactly_one_winner(tmp_path) -> None:
    value = report()
    token = closure(value)
    owner = signed_owner_approval(value, token)
    ledger = Gate2ClosureLedger(tmp_path / "gate2-closure.sqlite3")

    def attempt(_: int) -> str:
        try:
            consume(ledger, value, token, owner)
            return "success"
        except ApprovalReplay:
            return "replay"

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    assert outcomes.count("success") == 1
    assert outcomes.count("replay") == 3


def test_nonce_target_state_and_secret_are_strict() -> None:
    value = report()
    with pytest.raises(Gate2ClosureError, match="nonce"):
        closure(value, nonce="short")
    with pytest.raises(Gate2ClosureError, match="target_state"):
        closure(value, target_state="gate-3-open")
    token = closure(value)
    with pytest.raises(ValueError, match="at least 32"):
        signed_owner_approval(value, token, secret=b"weak")
