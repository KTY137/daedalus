# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import daedalus.gates.repository_write_artifact_cas as cas_module
from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactCASError,
    RepositoryWriteArtifactCASRoot,
    artifact_relative_path,
    resolve_repository_write_artifact,
)
from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.schemas import ContractProvenance


REVISION = "1" * 40
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
        source_tree_revision="2" * 40,
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


def _fixture(tmp_path: Path, content: bytes):
    cas = tmp_path / "cas"
    primary = tmp_path / "primary"
    cas.mkdir()
    primary.mkdir()
    root = RepositoryWriteArtifactCASRoot(
        path=str(cas.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=REVISION,
    )
    artifact = _artifact(content)
    path = cas.joinpath(*artifact_relative_path(artifact.locator).split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return artifact, root, path


def test_regular_object_replacement_after_descriptor_read_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"same-content-different-inode"
    artifact, root, path = _fixture(tmp_path, content)
    original = cas_module._read_exact_file

    def read_then_replace(candidate: Path, before: os.stat_result) -> bytes:
        result = original(candidate, before)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(content)
        os.replace(replacement, path)
        return result

    monkeypatch.setattr(cas_module, "_read_exact_file", read_then_replace)

    with pytest.raises(RepositoryWriteArtifactCASError, match="changed after read"):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )


def test_symlink_to_original_inode_after_descriptor_read_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"same-original-inode"
    artifact, root, path = _fixture(tmp_path, content)
    retained = path.with_suffix(".retained")
    original = cas_module._read_exact_file

    def read_then_redirect(candidate: Path, before: os.stat_result) -> bytes:
        result = original(candidate, before)
        path.rename(retained)
        try:
            path.symlink_to(retained)
        except (OSError, NotImplementedError):
            retained.rename(path)
            pytest.skip("symlinks are unavailable")
        return result

    monkeypatch.setattr(cas_module, "_read_exact_file", read_then_redirect)

    with pytest.raises(
        RepositoryWriteArtifactCASError,
        match="became a symlink after read",
    ):
        resolve_repository_write_artifact(
            artifact,
            root,
            resolution_id="resolution-1",
            resolved_at=RESOLVED_AT,
        )
