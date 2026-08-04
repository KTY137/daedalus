from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
    RepositoryWriteArtifactEvidenceError,
)
from daedalus.schemas import ContractProvenance

from .test_repository_write_evidence import _artifact


class DerivedProvenance(ContractProvenance):
    pass


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
