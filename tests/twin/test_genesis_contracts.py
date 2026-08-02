from __future__ import annotations

from dataclasses import replace

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.spine.envelope import canonical_sha
from daedalus.twin.genesis import (
    GenesisCompileReceipt,
    ProjectTwinContractError,
    ProjectTwinManifest,
    verify_genesis_receipt,
)

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
SOURCE = "1" * 64
FOREST = "2" * 64
SNAPSHOT = "3" * 64
COMPILER = "4" * 64
EVIDENCE = "5" * 64
OUTPUT = "6" * 64


def _manifest() -> ProjectTwinManifest:
    return ProjectTwinManifest(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_artifact=ArtifactRef.from_sha256(SOURCE),
        source_forest_sha256=FOREST,
        fourfold_snapshot_sha256=SNAPSHOT,
        compiler_contract_sha256=COMPILER,
        evidence_packet_sha256=EVIDENCE,
    )


def _receipt(manifest: ProjectTwinManifest) -> GenesisCompileReceipt:
    return GenesisCompileReceipt(
        manifest_sha256=manifest.digest,
        source_revision=manifest.source_revision,
        compiler_contract_sha256=manifest.compiler_contract_sha256,
        output_artifact=ArtifactRef.from_sha256(OUTPUT),
        deterministic=True,
    )


def test_manifest_round_trip_is_canonical_and_revision_exact() -> None:
    manifest = _manifest()
    rebuilt = ProjectTwinManifest.from_dict(manifest.to_dict())

    assert rebuilt == manifest
    assert rebuilt.digest == canonical_sha(manifest.to_dict())
    assert rebuilt.source_artifact.locator.endswith(SOURCE)


def test_genesis_receipt_binds_exact_manifest_revision_and_compiler() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)

    verify_genesis_receipt(manifest, receipt)
    assert receipt.digest == canonical_sha(receipt.to_dict())


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("manifest_sha256", "7" * 64, "manifest"),
        ("source_revision", OTHER_REVISION, "source_revision"),
        ("compiler_contract_sha256", "8" * 64, "compiler_contract"),
    ],
)
def test_genesis_receipt_refuses_replay_or_repackaging(
    field: str, value: str, match: str
) -> None:
    manifest = _manifest()
    receipt = replace(_receipt(manifest), **{field: value})

    with pytest.raises(ProjectTwinContractError, match=match):
        verify_genesis_receipt(manifest, receipt)


def test_manifest_refuses_locator_digest_disagreement() -> None:
    with pytest.raises(ValueError, match="locator"):
        ProjectTwinManifest(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_artifact=ArtifactRef(
                sha256=SOURCE,
                locator=f"artifact-locator:sha256:{'9' * 64}",
            ),
            source_forest_sha256=FOREST,
            fourfold_snapshot_sha256=SNAPSHOT,
            compiler_contract_sha256=COMPILER,
            evidence_packet_sha256=EVIDENCE,
        )


def test_genesis_receipt_requires_determinism_attestation() -> None:
    manifest = _manifest()
    with pytest.raises(ProjectTwinContractError, match="deterministic"):
        GenesisCompileReceipt(
            manifest_sha256=manifest.digest,
            source_revision=REVISION,
            compiler_contract_sha256=COMPILER,
            output_artifact=ArtifactRef.from_sha256(OUTPUT),
            deterministic=False,
        )
