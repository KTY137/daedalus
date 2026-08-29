"""Read-only ArtifactStore resolution for repository-write chain evidence."""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from daedalus.gates.repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
)
from daedalus.gates.repository_write_chain_result import CHAIN_RESULT_SCHEMA
from daedalus.gates.repository_write_chain_store_resolution import (
    CHAIN_RESULT_MEDIA_TYPE,
    CHAIN_RESULT_STORE_METADATA,
    CHAIN_RESULT_STORE_ORIGIN,
    RepositoryWriteChainStoreResolutionError,
    RepositoryWriteChainStoreResolutionReceipt,
    resolve_repository_write_chain_artifact,
)
from daedalus.gates.repository_write_classification import CLASSIFICATION_SCHEMA
from daedalus.schemas import ContractProvenance
from daedalus.storage import ArtifactStore


REVISION = "a" * 40
TREE = "b" * 40
REPORT = "c" * 64
CHAIN = "d" * 64
INVENTORY = "e" * 64
CLASSIFICATION = "f" * 64
STAGE_SET = "1" * 64
BUILT_AT = "2026-08-29T14:10:00.000000+00:00"
RESOLVED_AT = "2026-08-29T14:11:00.000000+00:00"
ARTIFACT_ID = "repository-write-chain-result.1"
RAW = b'{"schema":"fixture.repository-write-chain-result/1"}'


def _store_provenance(content_sha256: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "origin": CHAIN_RESULT_STORE_ORIGIN,
        "source_revision": REVISION,
        "created_at": BUILT_AT,
        "input_digests": sorted(
            {
                REPORT,
                CHAIN,
                INVENTORY,
                CLASSIFICATION,
                STAGE_SET,
                content_sha256,
            }
        ),
        "trace_id": ARTIFACT_ID,
    }
    values.update(overrides)
    return values


def _evidence(
    *,
    content_sha256: str,
    locator: str,
) -> RepositoryWriteChainArtifactEvidence:
    inputs = (
        REPORT,
        CHAIN,
        INVENTORY,
        CLASSIFICATION,
        STAGE_SET,
        content_sha256,
    )
    return RepositoryWriteChainArtifactEvidence(
        artifact_id=ARTIFACT_ID,
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v4_sha256=REPORT,
        chain_result_schema=CHAIN_RESULT_SCHEMA,
        chain_result_sha256=CHAIN,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_sha256=INVENTORY,
        classification_sha256=CLASSIFICATION,
        stage_digest_set_sha256=STAGE_SET,
        inventory_surface_count=1,
        classified_surface_count=1,
        missing_surface_count=0,
        authenticated_surface_count=1,
        evidence_authenticated=True,
        artifact_content_sha256=content_sha256,
        locator=locator,
        built_at=BUILT_AT,
        provenance=ContractProvenance(
            origin="gate0.repository-write-chain-artifact-evidence",
            source_revision=REVISION,
            created_at=BUILT_AT,
            input_digests=inputs,
        ),
    )


def _stored(
    tmp_path: Path,
    *,
    raw: bytes = RAW,
    media_type: str = CHAIN_RESULT_MEDIA_TYPE,
    metadata: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
):
    store = ArtifactStore(tmp_path / "cas", min_free_gib=0.0)
    content = hashlib.sha256(raw).hexdigest()
    locator = store.put_bytes(
        raw,
        expected_sha256=content,
        media_type=media_type,
        metadata=(CHAIN_RESULT_STORE_METADATA if metadata is None else metadata),
        provenance=(
            _store_provenance(content) if provenance is None else provenance
        ),
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return store, checkout, content, locator


def _resolve(
    artifact: RepositoryWriteChainArtifactEvidence,
    store: ArtifactStore,
    checkout: Path,
):
    return resolve_repository_write_chain_artifact(
        artifact,
        store,
        primary_checkout=checkout,
        resolution_id="chain-store-resolution.1",
        resolved_at=RESOLVED_AT,
    )


def test_real_artifact_store_locator_and_blob_identities_remain_distinct(
    tmp_path: Path,
) -> None:
    store, checkout, content, locator = _stored(tmp_path)
    assert locator.artifact_sha256 == content
    assert locator.locator_sha256 != content
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)

    raw, receipt = _resolve(artifact, store, checkout)

    assert raw == RAW
    assert receipt.artifact_locator_sha256 == locator.locator_sha256
    assert receipt.artifact_content_sha256 == content
    assert receipt.byte_length == len(RAW)
    assert receipt.evidence_authenticated is True
    assert RepositoryWriteChainStoreResolutionReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_legacy_blob_digest_disguised_as_locator_is_not_store_evidence(
    tmp_path: Path,
) -> None:
    store, checkout, content, _ = _stored(tmp_path)
    legacy = _evidence(
        content_sha256=content,
        locator=f"artifact-locator:sha256:{content}",
    )
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="locator is missing",
    ):
        _resolve(legacy, store, checkout)


def test_store_must_be_bidirectionally_disjoint_from_primary_checkout(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    store = ArtifactStore(checkout / "cas", min_free_gib=0.0)
    content = hashlib.sha256(RAW).hexdigest()
    locator = store.put_bytes(
        RAW,
        expected_sha256=content,
        media_type=CHAIN_RESULT_MEDIA_TYPE,
        metadata=CHAIN_RESULT_STORE_METADATA,
        provenance=_store_provenance(content),
    )
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="overlaps the primary checkout",
    ):
        _resolve(artifact, store, checkout)


def test_wrong_locator_media_type_is_refused(tmp_path: Path) -> None:
    store, checkout, content, locator = _stored(
        tmp_path,
        media_type="application/octet-stream",
    )
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="media type",
    ):
        _resolve(artifact, store, checkout)


def test_wrong_locator_metadata_is_refused(tmp_path: Path) -> None:
    store, checkout, content, locator = _stored(
        tmp_path,
        metadata={"kind": "some-other-artifact"},
    )
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="metadata",
    ):
        _resolve(artifact, store, checkout)


def test_locator_provenance_must_bind_the_exact_artifact_subject(
    tmp_path: Path,
) -> None:
    content = hashlib.sha256(RAW).hexdigest()
    store, checkout, _, locator = _stored(
        tmp_path,
        provenance=_store_provenance(content, trace_id="foreign-chain-result.1"),
    )
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="provenance contradicts",
    ):
        _resolve(artifact, store, checkout)


def test_blob_corruption_is_refused_before_bytes_escape(tmp_path: Path) -> None:
    store, checkout, content, locator = _stored(tmp_path)
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    locator.blob_path.write_bytes(b"corrupt")
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="size contradicts|digest contradicts",
    ):
        _resolve(artifact, store, checkout)


def test_locator_manifest_replacement_is_refused(tmp_path: Path) -> None:
    store, checkout, content, locator = _stored(tmp_path)
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    locator.locator_path.write_bytes(b"{}")
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="locator digest contradicts",
    ):
        _resolve(artifact, store, checkout)


def test_locator_identity_can_change_without_changing_blob_identity(
    tmp_path: Path,
) -> None:
    store, checkout, content, locator = _stored(tmp_path)
    second = store.put_bytes(
        RAW,
        expected_sha256=content,
        media_type=CHAIN_RESULT_MEDIA_TYPE,
        metadata=CHAIN_RESULT_STORE_METADATA,
        provenance=_store_provenance(content, trace_id="another-chain-result.1"),
    )
    assert second.artifact_sha256 == locator.artifact_sha256
    assert second.locator_sha256 != locator.locator_sha256
    artifact = _evidence(content_sha256=content, locator=second.locator_uri)
    with pytest.raises(
        RepositoryWriteChainStoreResolutionError,
        match="provenance contradicts",
    ):
        _resolve(artifact, store, checkout)


def test_evidence_contract_no_longer_conflates_locator_and_blob_digest(
    tmp_path: Path,
) -> None:
    _, _, content, locator = _stored(tmp_path)
    artifact = _evidence(content_sha256=content, locator=locator.locator_uri)
    replaced = dataclasses.replace(
        artifact,
        locator=f"artifact-locator:sha256:{'0' * 64}",
    )
    assert replaced.artifact_content_sha256 == content
    assert replaced.locator.endswith("0" * 64)
