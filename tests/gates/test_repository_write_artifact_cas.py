from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactCASError,
    RepositoryWriteArtifactCASRoot,
    RepositoryWriteArtifactResolutionReceipt,
    ResolvedRepositoryWriteArtifact,
    artifact_relative_path,
    resolve_repository_write_artifact,
)
from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.schemas import ContractProvenance


REVISION = "1" * 40
TREE_REVISION = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
RESOLVED_AT = "2026-08-04T20:01:00+00:00"


def _artifact(content: bytes, *, revision: str = REVISION) -> RepositoryWriteArtifactEvidence:
    digest = hashlib.sha256(content).hexdigest()
    report = "3" * 64
    inventory = "4" * 64
    scan = "5" * 64
    failures = "6" * 64
    provenance = ContractProvenance(
        origin="test.repository-write-artifact",
        source_revision=revision,
        created_at=BUILT_AT,
        input_digests=(report, inventory, scan, failures, digest),
    )
    return RepositoryWriteArtifactEvidence(
        artifact_id="repository-write-inventory",
        source_revision=revision,
        source_tree_revision=TREE_REVISION,
        gate_report_v3_sha256=report,
        inventory_sha256=inventory,
        scan_input_sha256=scan,
        files_scanned=1,
        inventory_generation=2,
        failure_set_sha256=failures,
        failure_count=0,
        artifact_content_sha256=digest,
        locator=f"artifact-locator:sha256:{digest}",
        built_at=BUILT_AT,
        provenance=provenance,
    )


def _roots(tmp_path: Path, *, revision: str = REVISION) -> RepositoryWriteArtifactCASRoot:
    cas = tmp_path / "cas"
    primary = tmp_path / "primary"
    cas.mkdir()
    primary.mkdir()
    return RepositoryWriteArtifactCASRoot(
        path=str(cas.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=revision,
    )


def _publish(root: RepositoryWriteArtifactCASRoot, artifact: RepositoryWriteArtifactEvidence, content: bytes) -> Path:
    relative = artifact_relative_path(artifact.locator)
    path = Path(root.path).joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


def test_resolves_exact_object_and_emits_round_trip_receipt(tmp_path: Path) -> None:
    content = b'{"closed":false}'
    artifact = _artifact(content)
    root = _roots(tmp_path)
    path = _publish(root, artifact, content)

    resolved = resolve_repository_write_artifact(
        artifact,
        root,
        resolution_id="resolution-1",
        resolved_at=RESOLVED_AT,
    )

    assert type(resolved) is ResolvedRepositoryWriteArtifact
    assert resolved.content == content
    assert resolved.receipt.relative_path == artifact_relative_path(artifact.locator)
    assert resolved.receipt.file_size == len(content)
    assert resolved.receipt.artifact_content_sha256 == artifact.artifact_content_sha256
    assert resolved.receipt.artifact_evidence_sha256 == artifact.digest
    assert resolved.receipt.cas_root_sha256 == root.digest
    assert resolved.receipt.file_inode == path.stat().st_ino
    assert (
        RepositoryWriteArtifactResolutionReceipt.from_dict(
            resolved.receipt.to_dict()
        )
        == resolved.receipt
    )


def test_locator_path_is_exact_and_sharded() -> None:
    digest = "ab" + "c" * 62
    assert artifact_relative_path(f"artifact-locator:sha256:{digest}") == (
        "sha256/ab/" + "c" * 62
    )
    with pytest.raises(RepositoryWriteArtifactCASError, match="locator is malformed"):
        artifact_relative_path("sha256:" + digest)


def test_missing_object_refuses_without_creating_shards(tmp_path: Path) -> None:
    artifact = _artifact(b"missing")
    root = _roots(tmp_path)

    with pytest.raises(RepositoryWriteArtifactCASError, match="shard directory is missing"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )

    assert tuple(Path(root.path).iterdir()) == ()


def test_wrong_bytes_refuse(tmp_path: Path) -> None:
    artifact = _artifact(b"expected")
    root = _roots(tmp_path)
    _publish(root, artifact, b"substituted")

    with pytest.raises(RepositoryWriteArtifactCASError, match="digest contradicts"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_stale_revision_refuses_before_open(tmp_path: Path) -> None:
    artifact = _artifact(b"bytes")
    root = _roots(tmp_path, revision="7" * 40)
    _publish(root, artifact, b"bytes")

    with pytest.raises(RepositoryWriteArtifactCASError, match="source revisions differ"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_primary_checkout_overlap_refuses(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    with pytest.raises(RepositoryWriteArtifactCASError, match="must be disjoint"):
        RepositoryWriteArtifactCASRoot(
            path=str(shared.resolve()),
            primary_checkout_root=str(shared.resolve()),
            source_revision=REVISION,
        )


def test_symlink_object_refuses(tmp_path: Path) -> None:
    artifact = _artifact(b"bytes")
    root = _roots(tmp_path)
    relative = artifact_relative_path(artifact.locator)
    path = Path(root.path).joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True)
    target = tmp_path / "outside.bin"
    target.write_bytes(b"bytes")
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(RepositoryWriteArtifactCASError, match="may not be a symlink"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_symlink_shard_refuses(tmp_path: Path) -> None:
    artifact = _artifact(b"bytes")
    root = _roots(tmp_path)
    digest = artifact.artifact_content_sha256
    sha_root = Path(root.path) / "sha256"
    sha_root.mkdir()
    outside = tmp_path / "outside-shard"
    outside.mkdir()
    try:
        (sha_root / digest[:2]).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    (outside / digest[2:]).write_bytes(b"bytes")

    with pytest.raises(RepositoryWriteArtifactCASError, match="symlink components"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_hard_link_alias_refuses(tmp_path: Path) -> None:
    artifact = _artifact(b"bytes")
    root = _roots(tmp_path)
    path = _publish(root, artifact, b"bytes")
    try:
        os.link(path, tmp_path / "alias.bin")
    except OSError:
        pytest.skip("hard links are unavailable")

    with pytest.raises(RepositoryWriteArtifactCASError, match="hard-link aliases"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_oversized_object_refuses_before_read(tmp_path: Path) -> None:
    artifact = _artifact(b"small")
    root = _roots(tmp_path)
    path = _publish(root, artifact, b"small")
    with path.open("r+b") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)

    with pytest.raises(RepositoryWriteArtifactCASError, match="size is invalid"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_path_replacement_during_read_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"x" * (1024 * 1024 + 1)
    artifact = _artifact(content)
    root = _roots(tmp_path)
    path = _publish(root, artifact, content)
    original_read = os.read
    calls = 0

    def replacing_read(descriptor: int, size: int) -> bytes:
        nonlocal calls
        block = original_read(descriptor, size)
        calls += 1
        if calls == 1:
            replacement = path.with_suffix(".replacement")
            replacement.write_bytes(content)
            os.replace(replacement, path)
        return block

    monkeypatch.setattr("daedalus.gates.repository_write_artifact_cas.os.read", replacing_read)

    with pytest.raises(RepositoryWriteArtifactCASError, match="changed after read"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_exact_input_types_are_required(tmp_path: Path) -> None:
    artifact = _artifact(b"bytes")
    root = _roots(tmp_path)
    _publish(root, artifact, b"bytes")

    class RootSubclass(RepositoryWriteArtifactCASRoot):
        pass

    substituted = RootSubclass(
        path=root.path,
        primary_checkout_root=root.primary_checkout_root,
        source_revision=root.source_revision,
    )
    with pytest.raises(RepositoryWriteArtifactCASError, match="root must be exact"):
        resolve_repository_write_artifact(
            artifact,
            substituted,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_receipt_rejects_substituted_locator(tmp_path: Path) -> None:
    content = b"bytes"
    artifact = _artifact(content)
    root = _roots(tmp_path)
    _publish(root, artifact, content)
    resolved = resolve_repository_write_artifact(
        artifact,
        root,
        resolution_id="resolution-1",
        resolved_at=RESOLVED_AT,
    )
    payload = resolved.receipt.to_dict()
    payload["locator"] = "artifact-locator:sha256:" + "f" * 64

    with pytest.raises(RepositoryWriteArtifactCASError, match="contradicts content digest"):
        RepositoryWriteArtifactResolutionReceipt.from_dict(payload)
