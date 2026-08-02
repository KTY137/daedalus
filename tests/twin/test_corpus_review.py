from __future__ import annotations

import dataclasses
import json

import pytest

from daedalus.twin.capabilities import CapabilityClaim, CapabilityMatrix, LanguageCapabilityProfile
from daedalus.twin.corpus import CorpusManifest, CorpusRepository
from daedalus.twin.corpus_review import CorpusReviewError, CorpusReviewRecord, apply_reviewed_record

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
        reviewed_at="2026-08-02T00:00:00Z",
        approval_sha256="5" * 64,
        decision=decision,
        rationale_sha256="6" * 64,
    )


def test_exact_owner_bound_record_upgrades_one_declared_repository() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    reviewed = apply_reviewed_record(
        manifest=source,
        capability_matrix=capabilities,
        record=evidence,
    )
    assert source.repositories[0].review_state == "declared"
    assert reviewed.repositories[0].review_state == "reviewed"
    assert reviewed.repositories[0].review_evidence == f"sha256:{evidence.digest}"
    assert CorpusReviewRecord.from_json_bytes(evidence.to_json_bytes()) == evidence


def test_rejected_record_is_retained_but_cannot_upgrade_manifest() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities, decision="rejected")
    with pytest.raises(CorpusReviewError, match="only a reviewed decision"):
        apply_reviewed_record(
            manifest=source,
            capability_matrix=capabilities,
            record=evidence,
        )


def test_revision_repository_and_capability_substitution_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    with pytest.raises(CorpusReviewError, match="source_revision"):
        apply_reviewed_record(
            manifest=source,
            capability_matrix=capabilities,
            record=dataclasses.replace(evidence, source_revision="7" * 40),
        )
    with pytest.raises(CorpusReviewError, match="repository_url"):
        apply_reviewed_record(
            manifest=source,
            capability_matrix=capabilities,
            record=dataclasses.replace(evidence, repository_url="https://github.com/other/repo.git"),
        )
    with pytest.raises(CorpusReviewError, match="capability matrix"):
        apply_reviewed_record(
            manifest=source,
            capability_matrix=capabilities,
            record=dataclasses.replace(evidence, capability_matrix_sha256="8" * 64),
        )


def test_stale_matrix_manifest_binding_and_repeat_upgrade_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    reviewed = apply_reviewed_record(manifest=source, capability_matrix=capabilities, record=evidence)
    with pytest.raises(CorpusReviewError, match="declared repository"):
        apply_reviewed_record(manifest=reviewed, capability_matrix=capabilities, record=evidence)

    changed_source = CorpusManifest(
        schema=source.schema,
        corpus_id=source.corpus_id,
        repositories=(dataclasses.replace(source.repositories[0], source_revision="9" * 40),),
    )
    with pytest.raises(CorpusReviewError, match="source corpus manifest"):
        apply_reviewed_record(
            manifest=changed_source,
            capability_matrix=capabilities,
            record=dataclasses.replace(evidence, source_revision="9" * 40),
        )


def test_noncanonical_record_and_missing_approval_refuse() -> None:
    source = manifest()
    capabilities = matrix(source)
    evidence = record(source, capabilities)
    pretty = (json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(CorpusReviewError, match="canonical JSON"):
        CorpusReviewRecord.from_json_bytes(pretty)
    with pytest.raises((CorpusReviewError, ValueError), match="approval_sha256"):
        dataclasses.replace(evidence, approval_sha256="")
