from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactCASError,
    RepositoryWriteArtifactResolutionReceipt,
    _MAX_ARTIFACT_BYTES,
    _RESOLUTION_CHECKS,
)
from daedalus.schemas import ContractProvenance


REVISION = "1" * 40
TREE_REVISION = "2" * 40
CONTENT = "3" * 64
EVIDENCE = "4" * 64
ROOT = "5" * 64
RESOLVED_AT = "2026-08-04T20:01:00+00:00"
LOCATOR = f"artifact-locator:sha256:{CONTENT}"
RELATIVE = f"sha256/{CONTENT[:2]}/{CONTENT[2:]}"


def _receipt() -> RepositoryWriteArtifactResolutionReceipt:
    return RepositoryWriteArtifactResolutionReceipt(
        resolution_id="resolution-1",
        source_revision=REVISION,
        source_tree_revision=TREE_REVISION,
        artifact_evidence_sha256=EVIDENCE,
        locator=LOCATOR,
        artifact_content_sha256=CONTENT,
        cas_root_sha256=ROOT,
        relative_path=RELATIVE,
        file_device=1,
        file_inode=2,
        file_size=17,
        file_mtime_ns=3,
        resolved_at=RESOLVED_AT,
        checks=_RESOLUTION_CHECKS,
        provenance=ContractProvenance(
            origin="gate0.repository-write-artifact-cas",
            source_revision=REVISION,
            created_at=RESOLVED_AT,
            input_digests=(EVIDENCE, CONTENT, ROOT),
        ),
    )


def test_receipt_round_trip_is_exact() -> None:
    receipt = _receipt()
    assert RepositoryWriteArtifactResolutionReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_relative_path_substitution_refuses() -> None:
    payload = _receipt().to_dict()
    payload["relative_path"] = "sha256/ff/" + "f" * 62
    with pytest.raises(RepositoryWriteArtifactCASError, match="contradicts locator"):
        RepositoryWriteArtifactResolutionReceipt.from_dict(payload)


@pytest.mark.parametrize("file_size", [0, _MAX_ARTIFACT_BYTES + 1])
def test_file_size_outside_resolver_bounds_refuses(file_size: int) -> None:
    payload = _receipt().to_dict()
    payload["file_size"] = file_size
    with pytest.raises(RepositoryWriteArtifactCASError, match="file size is invalid"):
        RepositoryWriteArtifactResolutionReceipt.from_dict(payload)


def test_incomplete_checks_refuse() -> None:
    payload = _receipt().to_dict()
    payload["checks"] = list(_RESOLUTION_CHECKS[:-1])
    with pytest.raises(RepositoryWriteArtifactCASError, match="checks are not exact"):
        RepositoryWriteArtifactResolutionReceipt.from_dict(payload)


def test_foreign_provenance_revision_refuses() -> None:
    receipt = _receipt()
    with pytest.raises(
        RepositoryWriteArtifactCASError,
        match="source revision contradicts provenance",
    ):
        dataclasses.replace(
            receipt,
            provenance=ContractProvenance(
                origin="gate0.repository-write-artifact-cas",
                source_revision="9" * 40,
                created_at=RESOLVED_AT,
                input_digests=(EVIDENCE, CONTENT, ROOT),
            ),
        )
