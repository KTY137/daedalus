from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.repository.write_evidence import (
    RepositoryWriteArtifactEvidence,
    RepositoryWriteArtifactEvidenceError,
)
from daedalus.schemas import ContractProvenance


REVISION = "1" * 40
TREE = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
REPORT = "a" * 64
INVENTORY = "b" * 64
SCAN = "c" * 64
FAILURES = "d" * 64
CONTENT = "e" * 64


class DerivedProvenance(ContractProvenance):
    pass


def _artifact() -> RepositoryWriteArtifactEvidence:
    provenance = ContractProvenance(
        origin="gate0.repository-write-artifact",
        source_revision=REVISION,
        created_at=BUILT_AT,
        input_digests=(REPORT, INVENTORY, SCAN, FAILURES, CONTENT),
    )
    return RepositoryWriteArtifactEvidence(
        artifact_id="artifact.repository-write-inventory",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v3_sha256=REPORT,
        inventory_sha256=INVENTORY,
        scan_input_sha256=SCAN,
        files_scanned=1,
        inventory_generation=2,
        failure_set_sha256=FAILURES,
        failure_count=0,
        artifact_content_sha256=CONTENT,
        locator=f"artifact-locator:sha256:{CONTENT}",
        built_at=BUILT_AT,
        provenance=provenance,
    )


def test_artifact_requires_exact_provenance_container() -> None:
    artifact = _artifact()
    derived = DerivedProvenance(
        origin=artifact.provenance.origin,
        source_revision=artifact.provenance.source_revision,
        created_at=artifact.provenance.created_at,
        input_digests=artifact.provenance.input_digests,
        trace_id=artifact.provenance.trace_id,
    )
    assert isinstance(derived, ContractProvenance)
    assert type(derived) is not ContractProvenance
    with pytest.raises(
        RepositoryWriteArtifactEvidenceError,
        match="exact ContractProvenance",
    ):
        dataclasses.replace(artifact, provenance=derived)


def test_artifact_contract_class_remains_exact_after_round_trip() -> None:
    artifact = _artifact()
    rebuilt = RepositoryWriteArtifactEvidence.from_dict(artifact.to_dict())
    assert type(rebuilt) is RepositoryWriteArtifactEvidence
    assert type(rebuilt.provenance) is ContractProvenance
