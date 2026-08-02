from __future__ import annotations

import dataclasses
import json

import pytest

from daedalus.kernel.approvals import ApprovalSignatureError, issue_owner_approval
from daedalus.schemas import ContractProvenance
from daedalus.twin.capabilities import CapabilityClaim, CapabilityMatrix, LanguageCapabilityProfile
from daedalus.twin.corpus import CorpusManifest, CorpusRepository
from daedalus.twin.corpus_review import (
    CorpusReviewError,
    CorpusReviewRecord,
    apply_reviewed_record,
    owner_approval_expectation,
    verify_corpus_review_approval,
)

CAPABILITIES = (
    "behavioral_validation",
    "cross_plane_bindings",
    "data_schema",
    "discovery",
    "knowledge_links",
    "symbols",
    "syntax",
    "types",
)
REVIEWED_AT = "2026-08-02T00:00:00Z"
NOW = "2026-08-02T00:05:00Z"
EXPIRES = "2026-08-02T01:00:00Z"
SECRET = b"corpus-review-owner-secret-material-at-least-thirty-two-bytes"
KEYRING = {("repository-owner", "corpus-owner-key"): SECRET}


def manifest() -> CorpusManifest:
    return CorpusManifest(
        schema="daedalus-corpus-manifest/1",
        corpus_id="review-fixture",
        repositories=(
            CorpusRepository(
                repository_id="tokio",
                repository_url="https://github.com/tokio-rs/tokio.git",
                source_revision="1" * 40,
                include_prefixes=("tokio",),
                language_ids=("rust",),
                license_spdx="MIT",
                license_path="LICENSE",
                review_state="declared",
                review_evidence=None,
            ),
        ),
    )


def matrix(source: CorpusManifest) -> CapabilityMatrix:
    claims = tuple(
        CapabilityClaim(
            capability=name,
            state="unsupported",
            evidence=None,
            limitation="fixture makes no semantic capability claim",
        )
        for name in CAPABILITIES
    )
    return CapabilityMatrix(
        schema="daedalus-capability-matrix/1",
        corpus_manifest_digest=f"sha256:{source.digest}",
        profiles=(
            LanguageCapabilityProfile(
                language_id="rust",
                extractor_contract="sha256:" + "2" * 64,
                claims=claims,
            ),
        ),
    )


def record(source: CorpusManifest, capabilities: CapabilityMatrix, *, decision: str = "reviewed") -> CorpusReviewRecord:
    repository = source.repositories[0]
    return CorpusReviewRecord(
        repository_id=repository.repository_id,
        repository_url=repository.repository_url,
        source_revision=repository.source_revision,
        include_prefixes=repository.include_prefixes,
        language_ids=repository.language_ids,
        license_spdx=repository.license_spdx,
        license_path=repository.license_path,
        license_file_sha256="3" * 64,
        source_inventory_sha256="4" * 64,
        capability_matrix_sha256=capabilities.digest,
        reviewer_id="repository-owner",
        reviewed_at=REVIEWED_AT,
        decision=decision,
        rationale_sha256="6" * 64,
    )


def owner_approval(source: CorpusManifest, evidence: CorpusReviewRecord, **changes):
    expectation = owner_approval_expectation(manifest=source, record=evidence)
    values = dict(
        approval_id="corpus-review-approval-001",
        owner_id="repository-owner",
        key_id="corpus-owner-key",
        operation=expectation.operation,
        nomination_receipt_sha256=expectation.nomination_receipt_sha256,
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        evidence_packet_sha256=expectation.evidence_packet_sha256,
        base_revision=expectation.base_revision,
        target_ref=expectation.target_ref,
        expected_target_revision=expectation.current_target_revision,
        nonce="corpus-review-nonce-0001",
        issued_at=REVIEWED_AT,
        expires_at=EXPIRES,
        provenance=ContractProvenance(
            origin="tests.corpus-review",
            source_revision=evidence.source_revision,
            created_at=REVIEWED_AT,
            input_digests=(evidence.digest, evidence.license_file_sha256, evidence.source_inventory_sha256),
        ),
        secret=SECRET,
    )
    values.update(changes)
    return issue_owner_approval(**values)


def apply(source, capabilities, evidence, approval=None, *, keyring=KEYRING, now=NOW):
    return apply_reviewed_record(
        manifest=source,
        capability_matrix=capabilities,
        record=evidence,
        owner_approval=approval or owner_approval(source, evidence),
        keyring=keyring,
        now=now,
    )


def test_exact_authenticated_record_upgrades_one_declared_repository() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    approval = owner_approval(source, evidence)
    reviewed = apply(source, capabilities, evidence, approval)
    assert source.repositories[0].review_state == "declared"
    assert reviewed.repositories[0].review_state == "reviewed"
    assert reviewed.repositories[0].review_evidence.startswith("sha256:")
    assert reviewed.repositories[0].review_evidence != f"sha256:{evidence.digest}"
    assert CorpusReviewRecord.from_json_bytes(evidence.to_json_bytes()) == evidence
    verified = verify_corpus_review_approval(
        manifest=source,
        record=evidence,
        owner_approval=approval,
        keyring=KEYRING,
        now=NOW,
    )
    assert verified.owner_id == evidence.reviewer_id
    assert verified.candidate_artifact_sha256 == evidence.digest


def test_rejected_record_cannot_upgrade_even_with_valid_owner_signature() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities, decision="rejected")
    with pytest.raises(CorpusReviewError, match="only a reviewed decision"):
        apply(source, capabilities, evidence)


def test_forged_signature_unknown_key_and_wrong_reviewer_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    approval = owner_approval(source, evidence)
    forged = dataclasses.replace(approval, signature_sha256="f" * 64)
    with pytest.raises(ApprovalSignatureError, match="signature mismatch"):
        apply(source, capabilities, evidence, forged)
    with pytest.raises(ApprovalSignatureError, match="unknown"):
        apply(source, capabilities, evidence, approval, keyring={})
    wrong_reviewer = owner_approval(
        source,
        evidence,
        owner_id="other-owner",
        key_id="other-key",
        secret=b"other-corpus-owner-secret-material-at-least-thirty-two-bytes",
    )
    with pytest.raises(CorpusReviewError, match="reviewer_id"):
        apply(
            source,
            capabilities,
            evidence,
            wrong_reviewer,
            keyring={("other-owner", "other-key"): b"other-corpus-owner-secret-material-at-least-thirty-two-bytes"},
        )


def test_revision_repository_and_capability_substitution_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    approval = owner_approval(source, evidence)
    with pytest.raises(CorpusReviewError, match="source_revision"):
        apply(source, capabilities, dataclasses.replace(evidence, source_revision="7" * 40), approval)
    with pytest.raises(CorpusReviewError, match="repository_url"):
        apply(source, capabilities, dataclasses.replace(evidence, repository_url="https://github.com/other/repo.git"), approval)
    with pytest.raises(CorpusReviewError, match="capability matrix"):
        apply(source, capabilities, dataclasses.replace(evidence, capability_matrix_sha256="8" * 64), approval)


def test_owner_envelope_substitution_refuses() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    wrong_target = owner_approval(source, evidence, target_ref="corpus/other/repository")
    with pytest.raises(Exception, match="target_ref"):
        apply(source, capabilities, evidence, wrong_target)
    wrong_candidate = owner_approval(source, evidence, candidate_artifact_sha256="f" * 64)
    with pytest.raises(Exception, match="candidate_artifact_sha256"):
        apply(source, capabilities, evidence, wrong_candidate)


def test_stale_matrix_manifest_binding_repeat_upgrade_and_expiry_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    approval = owner_approval(source, evidence)
    reviewed = apply(source, capabilities, evidence, approval)
    with pytest.raises(CorpusReviewError, match="declared repository"):
        apply(reviewed, capabilities, evidence, approval)

    changed_source = CorpusManifest(
        schema=source.schema,
        corpus_id=source.corpus_id,
        repositories=(dataclasses.replace(source.repositories[0], source_revision="9" * 40),),
    )
    with pytest.raises(CorpusReviewError, match="source corpus manifest"):
        apply(changed_source, capabilities, dataclasses.replace(evidence, source_revision="9" * 40), approval)
    with pytest.raises(Exception, match="expired"):
        apply(source, capabilities, evidence, approval, now=EXPIRES)


def test_noncanonical_record_and_review_time_binding_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    pretty = (json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(CorpusReviewError, match="canonical JSON"):
        CorpusReviewRecord.from_json_bytes(pretty)
    approval = owner_approval(source, evidence, issued_at="2026-08-02T00:01:00Z")
    with pytest.raises(CorpusReviewError, match="reviewed_at"):
        apply(source, capabilities, evidence, approval)
