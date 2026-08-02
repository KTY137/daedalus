from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.twin.genesis import (
    AtomicProjectTwinStore,
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


def test_manifest_round_trip_refuses_unknown_schema() -> None:
    payload = _manifest().to_dict()
    payload["schema"] = "daedalus-project-twin-manifest/999"
    with pytest.raises(ProjectTwinContractError, match="schema"):
        ProjectTwinManifest.from_dict(payload)


def test_genesis_receipt_binds_exact_manifest_revision_and_compiler() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)

    verify_genesis_receipt(manifest, receipt)
    assert receipt.digest == canonical_sha(receipt.to_dict())
    assert GenesisCompileReceipt.from_dict(receipt.to_dict()) == receipt


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


def test_atomic_store_round_trip_and_idempotent_replay(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    store = AtomicProjectTwinStore(tmp_path)

    first_ref = store.publish(manifest, receipt)
    second_ref = store.publish(manifest, receipt)
    rebuilt_manifest, rebuilt_receipt = store.load(manifest.digest)

    assert first_ref == second_ref
    assert rebuilt_manifest == manifest
    assert rebuilt_receipt == receipt
    assert list(tmp_path.glob("*.json")) == [tmp_path / f"{manifest.digest}.json"]
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_store_refuses_receipt_for_another_manifest(tmp_path: Path) -> None:
    manifest = _manifest()
    changed_manifest = replace(manifest, source_revision=OTHER_REVISION)
    store = AtomicProjectTwinStore(tmp_path)

    with pytest.raises(ProjectTwinContractError, match="manifest|source_revision"):
        store.publish(changed_manifest, _receipt(manifest))
    assert not list(tmp_path.iterdir())


def test_atomic_store_refuses_noncanonical_record(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    store = AtomicProjectTwinStore(tmp_path)
    store.publish(manifest, receipt)
    path = tmp_path / f"{manifest.digest}.json"
    payload = json.loads(path.read_text(encoding="ascii"))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="ascii")

    with pytest.raises(ProjectTwinContractError, match="canonically encoded"):
        store.load(manifest.digest)


def test_atomic_store_refuses_manifest_tampering(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    store = AtomicProjectTwinStore(tmp_path)
    store.publish(manifest, receipt)
    path = tmp_path / f"{manifest.digest}.json"
    payload = json.loads(path.read_text(encoding="ascii"))
    payload["manifest"]["repository_id"] = "attacker/repackaged"
    path.write_text(canonical_json(payload), encoding="ascii")

    with pytest.raises(ProjectTwinContractError, match="manifest digest"):
        store.load(manifest.digest)


def test_atomic_store_refuses_receipt_tampering(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    store = AtomicProjectTwinStore(tmp_path)
    store.publish(manifest, receipt)
    path = tmp_path / f"{manifest.digest}.json"
    payload = json.loads(path.read_text(encoding="ascii"))
    payload["receipt"]["output_artifact"] = ArtifactRef.from_sha256("9" * 64).to_dict()
    path.write_text(canonical_json(payload), encoding="ascii")

    with pytest.raises(ProjectTwinContractError, match="receipt digest"):
        store.load(manifest.digest)


def test_atomic_store_refuses_digest_path_collision(tmp_path: Path) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    store = AtomicProjectTwinStore(tmp_path)
    path = tmp_path / f"{manifest.digest}.json"
    path.write_text("{}", encoding="ascii")

    with pytest.raises(ProjectTwinContractError, match="different bytes"):
        store.publish(manifest, receipt)


def test_atomic_store_reports_missing_record(tmp_path: Path) -> None:
    store = AtomicProjectTwinStore(tmp_path)
    with pytest.raises(ProjectTwinContractError, match="does not exist"):
        store.load("f" * 64)
