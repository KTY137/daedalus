from __future__ import annotations

import dataclasses
import hashlib

import pytest

from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationError,
    RepositoryWriteArtifactVerificationReceipt,
    verify_repository_write_artifact,
)
from daedalus.gates.repository_write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "1" * 40
TREE = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
VERIFIED_AT = "2026-08-04T20:01:00+00:00"


class DerivedArtifact(RepositoryWriteArtifactEvidence):
    pass


class DerivedReport(GateReportV3):
    pass


class DerivedBytes(bytes):
    pass


class DerivedProvenance(ContractProvenance):
    pass


def _subjects() -> tuple[
    RepositoryWriteArtifactEvidence,
    GateReportV3,
    bytes,
]:
    inventory = RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="3" * 64,
        files_scanned=1,
        base_inventory_digest="4" * 64,
        stdlib_delta_digest="5" * 64,
        surfaces=(),
    )
    raw = canonical_json(inventory.to_dict()).encode("ascii")
    report = GateReportV3(
        gate=0,
        source_revision=REVISION,
        registry_sha256="6" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        repository_write_inventory_sha256=inventory.digest,
        repository_write_scan_input_sha256=inventory.scan_input_sha256,
        repository_write_files_scanned=inventory.files_scanned,
        repository_write_inventory_generation=2,
        repository_write_failures=(),
    )
    content_sha = hashlib.sha256(raw).hexdigest()
    report_sha = report.to_dict()["report_sha256"]
    failure_sha = canonical_sha([])
    provenance = ContractProvenance(
        origin="gate0.repository-write-artifact",
        source_revision=REVISION,
        created_at=BUILT_AT,
        input_digests=(
            report_sha,
            inventory.digest,
            inventory.scan_input_sha256,
            failure_sha,
            content_sha,
        ),
    )
    artifact = RepositoryWriteArtifactEvidence(
        artifact_id="artifact.repository-write-inventory",
        source_revision=REVISION,
        source_tree_revision=TREE,
        gate_report_v3_sha256=report_sha,
        inventory_sha256=inventory.digest,
        scan_input_sha256=inventory.scan_input_sha256,
        files_scanned=inventory.files_scanned,
        inventory_generation=2,
        failure_set_sha256=failure_sha,
        failure_count=0,
        artifact_content_sha256=content_sha,
        locator=f"artifact-locator:sha256:{content_sha}",
        built_at=BUILT_AT,
        provenance=provenance,
    )
    return artifact, report, raw


def _verify(artifact, report, raw):
    return verify_repository_write_artifact(
        artifact,
        report,
        raw,
        verification_id="verification.repository-write-artifact",
        verified_at=VERIFIED_AT,
    )


def test_artifact_subclass_refuses_before_byte_verification() -> None:
    artifact, report, raw = _subjects()
    derived = DerivedArtifact(**{
        field.name: getattr(artifact, field.name)
        for field in dataclasses.fields(RepositoryWriteArtifactEvidence)
    })
    assert isinstance(derived, RepositoryWriteArtifactEvidence)
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="artifact must be exact",
    ):
        _verify(derived, report, raw)


def test_report_subclass_refuses_before_byte_verification() -> None:
    artifact, report, raw = _subjects()
    derived = DerivedReport(**{
        field.name: getattr(report, field.name)
        for field in dataclasses.fields(GateReportV3)
    })
    assert isinstance(derived, GateReportV3)
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="report must be exact",
    ):
        _verify(artifact, derived, raw)


@pytest.mark.parametrize(
    "raw",
    [
        bytearray(b"{}"),
        memoryview(b"{}"),
        DerivedBytes(b"{}"),
    ],
)
def test_mutable_view_or_bytes_subclass_refuses_before_hashing(raw) -> None:
    artifact, report, _ = _subjects()
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="exact immutable bytes",
    ):
        _verify(artifact, report, raw)


def test_artifact_failure_count_must_match_verified_inventory() -> None:
    artifact, report, raw = _subjects()
    contradictory = dataclasses.replace(artifact, failure_count=1)
    assert contradictory.failure_set_sha256 == artifact.failure_set_sha256
    # The contradiction is refused by the artifact/GateReport-v3 cross-binding
    # layer, which emits a stable machine-readable blocker code; the deeper
    # inventory-level failure-count check stays as defence in depth.
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="repository-write-artifact:failure-count-mismatch",
    ):
        _verify(contradictory, report, raw)


def test_receipt_rejects_derived_provenance() -> None:
    artifact, report, raw = _subjects()
    receipt = _verify(artifact, report, raw)
    derived = DerivedProvenance(
        origin=receipt.provenance.origin,
        source_revision=receipt.provenance.source_revision,
        created_at=receipt.provenance.created_at,
        input_digests=receipt.provenance.input_digests,
        trace_id=receipt.provenance.trace_id,
    )
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="exact ContractProvenance",
    ):
        dataclasses.replace(receipt, provenance=derived)


def test_receipt_round_trip_restores_exact_types() -> None:
    artifact, report, raw = _subjects()
    receipt = _verify(artifact, report, raw)
    rebuilt = RepositoryWriteArtifactVerificationReceipt.from_dict(
        receipt.to_dict()
    )
    assert type(rebuilt) is RepositoryWriteArtifactVerificationReceipt
    assert type(rebuilt.provenance) is ContractProvenance
