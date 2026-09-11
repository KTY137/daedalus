from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from daedalus.gates.repository.write_artifact_cas import (
    RepositoryWriteArtifactCASError,
    RepositoryWriteArtifactCASRoot,
    artifact_relative_path,
    resolve_repository_write_artifact,
)
from daedalus.gates.repository.write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.schemas import ContractProvenance


REVISION = "1" * 40
TREE_REVISION = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
RESOLVED_AT = "2026-08-04T20:01:00+00:00"


def _artifact(content: bytes) -> RepositoryWriteArtifactEvidence:
    digest = hashlib.sha256(content).hexdigest()
    report = "3" * 64
    inventory = "4" * 64
    scan = "5" * 64
    failures = "6" * 64
    return RepositoryWriteArtifactEvidence(
        artifact_id="repository-write-inventory",
        source_revision=REVISION,
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
        provenance=ContractProvenance(
            origin="test.repository-write-artifact",
            source_revision=REVISION,
            created_at=BUILT_AT,
            input_digests=(report, inventory, scan, failures, digest),
        ),
    )


def _root(tmp_path: Path) -> RepositoryWriteArtifactCASRoot:
    cas = tmp_path / "cas"
    primary = tmp_path / "primary"
    cas.mkdir()
    primary.mkdir()
    return RepositoryWriteArtifactCASRoot(
        path=str(cas.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=REVISION,
    )


def _publish(
    root: RepositoryWriteArtifactCASRoot,
    artifact: RepositoryWriteArtifactEvidence,
    content: bytes,
) -> Path:
    path = Path(root.path).joinpath(*artifact_relative_path(artifact.locator).split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


def test_artifact_subclass_refuses_before_resolution(tmp_path: Path) -> None:
    content = b"bytes"
    artifact = _artifact(content)
    root = _root(tmp_path)
    _publish(root, artifact, content)

    class ArtifactSubclass(RepositoryWriteArtifactEvidence):
        pass

    substituted = ArtifactSubclass(**{
        field: getattr(artifact, field)
        for field in (
            "artifact_id",
            "source_revision",
            "source_tree_revision",
            "gate_report_v3_sha256",
            "inventory_sha256",
            "scan_input_sha256",
            "files_scanned",
            "inventory_generation",
            "failure_set_sha256",
            "failure_count",
            "artifact_content_sha256",
            "locator",
            "built_at",
            "provenance",
        )
    })

    with pytest.raises(RepositoryWriteArtifactCASError, match="artifact must be exact"):
        resolve_repository_write_artifact(
            substituted,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_opened_descriptor_substitution_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"same-content"
    artifact = _artifact(content)
    root = _root(tmp_path)
    expected = _publish(root, artifact, content)
    decoy = tmp_path / "decoy.bin"
    decoy.write_bytes(content)
    original_open = os.open

    def substituted_open(path: str | os.PathLike[str], flags: int) -> int:
        if Path(path) == expected:
            return original_open(decoy, flags)
        return original_open(path, flags)

    monkeypatch.setattr(
        "daedalus.gates.repository.write_artifact_cas.os.open",
        substituted_open,
    )

    with pytest.raises(RepositoryWriteArtifactCASError, match="changed before read"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_root_path_symlink_refuses(tmp_path: Path) -> None:
    real_cas = tmp_path / "real-cas"
    primary = tmp_path / "primary"
    alias = tmp_path / "cas-alias"
    real_cas.mkdir()
    primary.mkdir()
    try:
        alias.symlink_to(real_cas, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(RepositoryWriteArtifactCASError, match="may not be a symlink"):
        RepositoryWriteArtifactCASRoot(
            path=str(alias.absolute()),
            primary_checkout_root=str(primary.resolve()),
            source_revision=REVISION,
        )


def test_primary_root_component_redirection_refuses(tmp_path: Path) -> None:
    cas = tmp_path / "cas"
    real_primary = tmp_path / "real-primary"
    alias = tmp_path / "primary-alias"
    cas.mkdir()
    real_primary.mkdir()
    try:
        alias.symlink_to(real_primary, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(RepositoryWriteArtifactCASError, match="may not be a symlink"):
        RepositoryWriteArtifactCASRoot(
            path=str(cas.resolve()),
            primary_checkout_root=str(alias.absolute()),
            source_revision=REVISION,
        )
