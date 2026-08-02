from __future__ import annotations

import dataclasses
import json

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.twin.capabilities import (
    CapabilityClaim,
    CapabilityMatrix,
    LanguageCapabilityProfile,
)
from daedalus.twin.corpus import CorpusManifest, CorpusRepository
from daedalus.twin.corpus_genesis import (
    CorpusGenesisBinding,
    CorpusGenesisBindingError,
    bind_corpus_genesis,
    verify_corpus_genesis_binding,
)
from daedalus.twin.genesis import GenesisCompileReceipt, ProjectTwinManifest

REVISION = "1" * 40
SHA = "a" * 64
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


def corpus(*, review_state: str = "declared", revision: str = REVISION) -> CorpusManifest:
    return CorpusManifest(
        schema="daedalus-corpus-manifest/1",
        corpus_id="test-corpus",
        repositories=(
            CorpusRepository(
                repository_id="tokio",
                repository_url="https://github.com/tokio-rs/tokio.git",
                source_revision=revision,
                include_prefixes=("tokio",),
                language_ids=("rust",),
                license_spdx="MIT",
                license_path="LICENSE",
                review_state=review_state,
                review_evidence=("sha256:" + "b" * 64)
                if review_state == "reviewed"
                else None,
            ),
        ),
    )


def matrix(corpus_manifest: CorpusManifest, *, failed: bool = False) -> CapabilityMatrix:
    claims = []
    for capability in CAPABILITIES:
        state = "failed" if failed and capability == "syntax" else "partial"
        claims.append(
            CapabilityClaim(
                capability=capability,
                state=state,
                evidence=None if state == "failed" else "sha256:" + "c" * 64,
                limitation="injected extractor failure"
                if state == "failed"
                else "bounded pilot evidence only",
            )
        )
    return CapabilityMatrix(
        schema="daedalus-capability-matrix/1",
        corpus_manifest_digest="sha256:" + corpus_manifest.digest,
        profiles=(
            LanguageCapabilityProfile(
                language_id="rust",
                extractor_contract="sha256:" + "d" * 64,
                claims=tuple(claims),
            ),
        ),
    )


def twin(*, revision: str = REVISION, repository_id: str = "tokio") -> tuple[ProjectTwinManifest, GenesisCompileReceipt]:
    manifest = ProjectTwinManifest(
        repository_id=repository_id,
        source_revision=revision,
        source_artifact=ArtifactRef.from_sha256("2" * 64),
        source_forest_sha256="3" * 64,
        fourfold_snapshot_sha256="4" * 64,
        compiler_contract_sha256="5" * 64,
        evidence_packet_sha256="6" * 64,
    )
    receipt = GenesisCompileReceipt(
        manifest_sha256=manifest.digest,
        source_revision=revision,
        compiler_contract_sha256=manifest.compiler_contract_sha256,
        output_artifact=ArtifactRef.from_sha256("7" * 64),
        deterministic=True,
    )
    return manifest, receipt


def test_declared_corpus_is_bound_but_cannot_close_gate2() -> None:
    corpus_manifest = corpus()
    capability_matrix = matrix(corpus_manifest)
    manifest, receipt = twin()
    binding = bind_corpus_genesis(
        manifest=manifest,
        receipt=receipt,
        corpus_manifest=corpus_manifest,
        capability_matrix=capability_matrix,
    )
    assert binding.project_twin_manifest_sha256 == manifest.digest
    assert binding.genesis_receipt_sha256 == receipt.digest
    assert binding.evidence_packet_sha256 == manifest.evidence_packet_sha256
    assert binding.corpus_manifest_sha256 == corpus_manifest.digest
    assert binding.capability_matrix_sha256 == capability_matrix.digest
    assert binding.blockers == ("corpus-review-declared",)
    assert not binding.closed_for_gate2
    assert CorpusGenesisBinding.from_json_bytes(binding.to_json_bytes()) == binding


def test_reviewed_corpus_without_failed_capabilities_can_close_binding() -> None:
    corpus_manifest = corpus(review_state="reviewed")
    binding = bind_corpus_genesis(
        manifest=twin()[0],
        receipt=twin()[1],
        corpus_manifest=corpus_manifest,
        capability_matrix=matrix(corpus_manifest),
    )
    assert binding.review_evidence == "sha256:" + "b" * 64
    assert binding.blockers == ()
    assert binding.closed_for_gate2


def test_failed_capability_remains_a_mechanical_blocker() -> None:
    corpus_manifest = corpus(review_state="reviewed")
    manifest, receipt = twin()
    binding = bind_corpus_genesis(
        manifest=manifest,
        receipt=receipt,
        corpus_manifest=corpus_manifest,
        capability_matrix=matrix(corpus_manifest, failed=True),
    )
    assert binding.blockers == ("rust:syntax:failed",)
    assert not binding.closed_for_gate2


def test_revision_repository_and_capability_substitution_refuse() -> None:
    corpus_manifest = corpus()
    capability_matrix = matrix(corpus_manifest)
    manifest, receipt = twin()

    stale_manifest, stale_receipt = twin(revision="2" * 40)
    with pytest.raises(CorpusGenesisBindingError, match="source_revision"):
        bind_corpus_genesis(
            manifest=stale_manifest,
            receipt=stale_receipt,
            corpus_manifest=corpus_manifest,
            capability_matrix=capability_matrix,
        )

    wrong_repository, wrong_receipt = twin(repository_id="other")
    with pytest.raises(CorpusGenesisBindingError, match="exactly one"):
        bind_corpus_genesis(
            manifest=wrong_repository,
            receipt=wrong_receipt,
            corpus_manifest=corpus_manifest,
            capability_matrix=capability_matrix,
        )

    other_corpus = corpus(revision="3" * 40)
    with pytest.raises(CorpusGenesisBindingError, match="exact corpus"):
        bind_corpus_genesis(
            manifest=manifest,
            receipt=receipt,
            corpus_manifest=corpus_manifest,
            capability_matrix=matrix(other_corpus),
        )


def test_tampered_binding_and_noncanonical_bytes_refuse() -> None:
    corpus_manifest = corpus()
    capability_matrix = matrix(corpus_manifest)
    manifest, receipt = twin()
    binding = bind_corpus_genesis(
        manifest=manifest,
        receipt=receipt,
        corpus_manifest=corpus_manifest,
        capability_matrix=capability_matrix,
    )
    tampered = dataclasses.replace(binding, evidence_packet_sha256="8" * 64)
    with pytest.raises(CorpusGenesisBindingError, match="does not match"):
        verify_corpus_genesis_binding(
            binding=tampered,
            manifest=manifest,
            receipt=receipt,
            corpus_manifest=corpus_manifest,
            capability_matrix=capability_matrix,
        )

    pretty = (json.dumps(binding.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(CorpusGenesisBindingError, match="canonical JSON"):
        CorpusGenesisBinding.from_json_bytes(pretty)


def test_receipt_replay_and_missing_language_profile_refuse() -> None:
    corpus_manifest = corpus()
    capability_matrix = matrix(corpus_manifest)
    manifest, receipt = twin()
    replayed = dataclasses.replace(receipt, manifest_sha256="9" * 64)
    with pytest.raises(ValueError, match="Genesis receipt mismatch"):
        bind_corpus_genesis(
            manifest=manifest,
            receipt=replayed,
            corpus_manifest=corpus_manifest,
            capability_matrix=capability_matrix,
        )

    empty_language_matrix = CapabilityMatrix(
        schema="daedalus-capability-matrix/1",
        corpus_manifest_digest="sha256:" + corpus_manifest.digest,
        profiles=(
            LanguageCapabilityProfile(
                language_id="python",
                extractor_contract="sha256:" + "e" * 64,
                claims=tuple(
                    CapabilityClaim(
                        capability=capability,
                        state="unsupported",
                        evidence=None,
                        limitation="not selected for this pilot",
                    )
                    for capability in CAPABILITIES
                ),
            ),
        ),
    )
    with pytest.raises(CorpusGenesisBindingError, match="does not cover"):
        bind_corpus_genesis(
            manifest=manifest,
            receipt=receipt,
            corpus_manifest=corpus_manifest,
            capability_matrix=empty_language_matrix,
        )
