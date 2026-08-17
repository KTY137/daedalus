from __future__ import annotations

import dataclasses
import hashlib
import inspect
from pathlib import Path

import pytest

from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository_write_artifact_admission import (
    AdmittedRepositoryWriteArtifact,
    RepositoryWriteArtifactAdmissionError,
    RepositoryWriteArtifactAdmissionReceipt,
    admit_repository_write_artifact,
)
from daedalus.gates.repository_write_artifact_cas import (
    RepositoryWriteArtifactCASError,
    RepositoryWriteArtifactCASRoot,
    artifact_relative_path,
)
from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationError,
)
from daedalus.gates.repository_write_evidence import RepositoryWriteArtifactEvidence
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "1" * 40
TREE_REVISION = "2" * 40
BUILT_AT = "2026-08-05T00:00:00+00:00"
ADMITTED_AT = "2026-08-05T00:01:00+00:00"


def _inventory() -> RepositoryWriteInventoryV2:
    return RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="3" * 64,
        files_scanned=1,
        base_inventory_digest="4" * 64,
        stdlib_delta_digest="5" * 64,
        surfaces=(
            RepositoryWriteSurface(
                path="daedalus/example.py",
                line=7,
                column=4,
                origin="base_v1",
                kind="path-write",
                callee="Path.write_text",
                operation="write_text",
                blocking=True,
            ),
        ),
    )


def _failures(inventory: RepositoryWriteInventoryV2) -> tuple[str, ...]:
    return tuple(
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        for surface in inventory.blockers
    )


def _report(inventory: RepositoryWriteInventoryV2) -> GateReportV3:
    return GateReportV3(
        gate=0,
        source_revision=inventory.source_revision,
        registry_sha256="6" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        repository_write_inventory_sha256=inventory.digest,
        repository_write_scan_input_sha256=inventory.scan_input_sha256,
        repository_write_files_scanned=inventory.files_scanned,
        repository_write_inventory_generation=2,
        repository_write_failures=_failures(inventory),
    )


def _artifact(
    report: GateReportV3,
    inventory: RepositoryWriteInventoryV2,
    raw: bytes,
) -> RepositoryWriteArtifactEvidence:
    content_sha256 = hashlib.sha256(raw).hexdigest()
    failure_set_sha256 = canonical_sha(list(report.repository_write_failures))
    provenance = ContractProvenance(
        origin="test.repository-write-artifact",
        source_revision=REVISION,
        created_at=BUILT_AT,
        input_digests=(
            report.to_dict()["report_sha256"],
            inventory.digest,
            inventory.scan_input_sha256,
            failure_set_sha256,
            content_sha256,
        ),
    )
    return RepositoryWriteArtifactEvidence(
        artifact_id="artifact.repository-write-inventory",
        source_revision=REVISION,
        source_tree_revision=TREE_REVISION,
        gate_report_v3_sha256=report.to_dict()["report_sha256"],
        inventory_sha256=inventory.digest,
        scan_input_sha256=inventory.scan_input_sha256,
        files_scanned=inventory.files_scanned,
        inventory_generation=2,
        failure_set_sha256=failure_set_sha256,
        failure_count=len(report.repository_write_failures),
        artifact_content_sha256=content_sha256,
        locator=f"artifact-locator:sha256:{content_sha256}",
        built_at=BUILT_AT,
        provenance=provenance,
    )


def _root(tmp_path: Path, *, revision: str = REVISION) -> RepositoryWriteArtifactCASRoot:
    cas = tmp_path / "cas"
    primary = tmp_path / "primary"
    cas.mkdir()
    primary.mkdir()
    return RepositoryWriteArtifactCASRoot(
        path=str(cas.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=revision,
    )


def _publish(
    root: RepositoryWriteArtifactCASRoot,
    artifact: RepositoryWriteArtifactEvidence,
    raw: bytes,
) -> Path:
    path = Path(root.path).joinpath(*artifact_relative_path(artifact.locator).split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return path


def _subject(tmp_path: Path):
    inventory = _inventory()
    raw = canonical_json(inventory.to_dict()).encode("ascii")
    report = _report(inventory)
    artifact = _artifact(report, inventory, raw)
    root = _root(tmp_path)
    _publish(root, artifact, raw)
    return inventory, raw, report, artifact, root


def _admit(tmp_path: Path) -> AdmittedRepositoryWriteArtifact:
    _, _, report, artifact, root = _subject(tmp_path)
    return admit_repository_write_artifact(
        artifact,
        report,
        root,
        admission_id="admission.repository-write-artifact",
        resolution_id="resolution.repository-write-artifact",
        verification_id="verification.repository-write-artifact",
        admitted_at=ADMITTED_AT,
    )


def test_atomic_admission_resolves_verifies_and_cross_binds(tmp_path: Path) -> None:
    inventory, raw, report, artifact, root = _subject(tmp_path)
    admitted = admit_repository_write_artifact(
        artifact,
        report,
        root,
        admission_id="admission.repository-write-artifact",
        resolution_id="resolution.repository-write-artifact",
        verification_id="verification.repository-write-artifact",
        admitted_at=ADMITTED_AT,
    )

    assert type(admitted) is AdmittedRepositoryWriteArtifact
    assert admitted.content == raw
    assert admitted.resolution_receipt.artifact_evidence_sha256 == artifact.digest
    assert admitted.verification_receipt.inventory_sha256 == inventory.digest
    assert admitted.admission_receipt.gate_report_v3_sha256 == report.to_dict()[
        "report_sha256"
    ]
    assert admitted.admission_receipt.cas_root_sha256 == root.digest
    assert admitted.admission_receipt.resolution_receipt_sha256 == (
        admitted.resolution_receipt.digest
    )
    assert admitted.admission_receipt.verification_receipt_sha256 == (
        admitted.verification_receipt.digest
    )
    assert admitted.resolution_receipt.resolved_at == ADMITTED_AT
    assert admitted.verification_receipt.verified_at == ADMITTED_AT
    assert (
        RepositoryWriteArtifactAdmissionReceipt.from_dict(
            admitted.admission_receipt.to_dict()
        )
        == admitted.admission_receipt
    )


def test_public_api_accepts_no_caller_resolved_bytes_or_receipts() -> None:
    signature = inspect.signature(admit_repository_write_artifact)
    assert tuple(signature.parameters) == (
        "artifact",
        "report",
        "root",
        "admission_id",
        "resolution_id",
        "verification_id",
        "admitted_at",
    )
    assert "artifact_bytes" not in signature.parameters
    assert "resolution_receipt" not in signature.parameters
    assert "verification_receipt" not in signature.parameters


def test_stale_cas_revision_refuses_before_artifact_acceptance(tmp_path: Path) -> None:
    inventory = _inventory()
    raw = canonical_json(inventory.to_dict()).encode("ascii")
    report = _report(inventory)
    artifact = _artifact(report, inventory, raw)
    root = _root(tmp_path, revision="a" * 40)
    _publish(root, artifact, raw)

    with pytest.raises(RepositoryWriteArtifactCASError, match="source revisions differ"):
        admit_repository_write_artifact(
            artifact,
            report,
            root,
            admission_id="admission.repository-write-artifact",
            resolution_id="resolution.repository-write-artifact",
            verification_id="verification.repository-write-artifact",
            admitted_at=ADMITTED_AT,
        )


def test_foreign_gate_report_refuses_after_resolution_without_admission(
    tmp_path: Path,
) -> None:
    _, _, report, artifact, root = _subject(tmp_path)
    foreign = dataclasses.replace(report, registry_sha256="b" * 64)

    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="contradicts GateReport-v3",
    ):
        admit_repository_write_artifact(
            artifact,
            foreign,
            root,
            admission_id="admission.repository-write-artifact",
            resolution_id="resolution.repository-write-artifact",
            verification_id="verification.repository-write-artifact",
            admitted_at=ADMITTED_AT,
        )


def test_substituted_cas_bytes_refuse(tmp_path: Path) -> None:
    inventory = _inventory()
    raw = canonical_json(inventory.to_dict()).encode("ascii")
    report = _report(inventory)
    artifact = _artifact(report, inventory, raw)
    root = _root(tmp_path)
    _publish(root, artifact, raw + b" ")

    with pytest.raises(RepositoryWriteArtifactCASError, match="digest contradicts"):
        admit_repository_write_artifact(
            artifact,
            report,
            root,
            admission_id="admission.repository-write-artifact",
            resolution_id="resolution.repository-write-artifact",
            verification_id="verification.repository-write-artifact",
            admitted_at=ADMITTED_AT,
        )


def test_exact_subject_types_refuse_before_resolution(tmp_path: Path) -> None:
    _, _, report, artifact, root = _subject(tmp_path)

    class RootSubclass(RepositoryWriteArtifactCASRoot):
        pass

    substituted = RootSubclass(
        path=root.path,
        primary_checkout_root=root.primary_checkout_root,
        source_revision=root.source_revision,
    )
    with pytest.raises(RepositoryWriteArtifactAdmissionError, match="root must be exact"):
        admit_repository_write_artifact(
            artifact,
            report,
            substituted,
            admission_id="admission.repository-write-artifact",
            resolution_id="resolution.repository-write-artifact",
            verification_id="verification.repository-write-artifact",
            admitted_at=ADMITTED_AT,
        )


def test_detached_receipts_refuse_immutable_result(tmp_path: Path) -> None:
    admitted = _admit(tmp_path)
    detached_verification = dataclasses.replace(
        admitted.verification_receipt,
        verification_id="verification.detached",
    )
    with pytest.raises(
        RepositoryWriteArtifactAdmissionError,
        match="verification_receipt_sha256",
    ):
        AdmittedRepositoryWriteArtifact(
            content=admitted.content,
            resolution_receipt=admitted.resolution_receipt,
            verification_receipt=detached_verification,
            admission_receipt=admitted.admission_receipt,
        )


def test_admission_receipt_rejects_missing_cross_receipt_provenance(
    tmp_path: Path,
) -> None:
    admitted = _admit(tmp_path)
    provenance = dataclasses.replace(
        admitted.admission_receipt.provenance,
        input_digests=admitted.admission_receipt.provenance.input_digests[:-1],
    )
    with pytest.raises(
        RepositoryWriteArtifactAdmissionError,
        match="does not bind referenced input",
    ):
        dataclasses.replace(admitted.admission_receipt, provenance=provenance)


def test_primary_checkout_is_not_mutated(tmp_path: Path) -> None:
    _, _, report, artifact, root = _subject(tmp_path)
    primary = Path(root.primary_checkout_root)
    marker = primary / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    before = tuple((path.name, path.read_bytes()) for path in primary.iterdir())

    admit_repository_write_artifact(
        artifact,
        report,
        root,
        admission_id="admission.repository-write-artifact",
        resolution_id="resolution.repository-write-artifact",
        verification_id="verification.repository-write-artifact",
        admitted_at=ADMITTED_AT,
    )

    after = tuple((path.name, path.read_bytes()) for path in primary.iterdir())
    assert after == before
