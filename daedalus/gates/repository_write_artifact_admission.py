"""Atomic read-only admission for one repository-write inventory artifact.

This module composes the exact local-CAS resolver with the strict inventory-byte
verifier. The caller cannot inject already-resolved bytes or independently pair
receipts. One call resolves the locator, verifies the canonical inventory bytes
against GateReport-v3, cross-binds both receipts, and returns immutable evidence.

Admission is not release authority. The module does not authenticate an artifact
signer, inspect Git HEAD, update an evidence index, issue OwnerApproval, create a
PromotionReceipt, mutate a checkout, merge, promote, or change a Gate state.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)

from .report_v3 import GateReportV3
from .repository_write_artifact_cas import (
    RepositoryWriteArtifactCASRoot,
    RepositoryWriteArtifactResolutionReceipt,
    resolve_repository_write_artifact,
)
from .repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationReceipt,
    verify_repository_write_artifact,
)
from .repository_write_evidence import RepositoryWriteArtifactEvidence


_ADMISSION_CHECKS = (
    "cas-resolution",
    "cross-receipt-binding",
    "gate-report-v3-binding",
    "inventory-byte-verification",
)


class RepositoryWriteArtifactAdmissionError(ValueError):
    """The composed artifact subject or its cross-receipt binding is invalid."""


@dataclass(frozen=True)
class RepositoryWriteArtifactAdmissionReceipt(CanonicalContract):
    """Canonical binding of one resolution receipt and one verification receipt."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-artifact-admission-receipt/1"
    )

    admission_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v3_sha256: str
    artifact_evidence_sha256: str
    artifact_content_sha256: str
    inventory_sha256: str
    cas_root_sha256: str
    resolution_receipt_sha256: str
    verification_receipt_sha256: str
    admitted_at: str
    checks: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "admission_id",
                _identifier(self.admission_id, "admission_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "source_tree_revision",
                _revision(self.source_tree_revision, "source_tree_revision"),
            )
            for field_name in (
                "gate_report_v3_sha256",
                "artifact_evidence_sha256",
                "artifact_content_sha256",
                "inventory_sha256",
                "cas_root_sha256",
                "resolution_receipt_sha256",
                "verification_receipt_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "admitted_at",
                _utc_timestamp(self.admitted_at, "admitted_at"),
            )
            object.__setattr__(
                self,
                "checks",
                _sorted_strings(self.checks, "checks", identifiers=True),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactAdmissionError(
                "artifact admission receipt is malformed"
            ) from exc
        if self.checks != _ADMISSION_CHECKS:
            raise RepositoryWriteArtifactAdmissionError(
                "artifact admission checks are not exact"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteArtifactAdmissionError(
                "admission provenance must be exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteArtifactAdmissionError(
                "admission source revision contradicts provenance"
            )
        if self.provenance.created_at != self.admitted_at:
            raise RepositoryWriteArtifactAdmissionError(
                "admission time contradicts provenance"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v3_sha256,
                    self.artifact_evidence_sha256,
                    self.artifact_content_sha256,
                    self.inventory_sha256,
                    self.cas_root_sha256,
                    self.resolution_receipt_sha256,
                    self.verification_receipt_sha256,
                ),
                "repository-write artifact admission receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteArtifactAdmissionError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteArtifactAdmissionReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteArtifactAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactAdmissionError(
                "artifact admission receipt payload is malformed"
            ) from exc


@dataclass(frozen=True)
class AdmittedRepositoryWriteArtifact:
    """Immutable resolved bytes and all exact receipts for one admission."""

    content: bytes
    resolution_receipt: RepositoryWriteArtifactResolutionReceipt
    verification_receipt: RepositoryWriteArtifactVerificationReceipt
    admission_receipt: RepositoryWriteArtifactAdmissionReceipt

    def __post_init__(self) -> None:
        if type(self.content) is not bytes:
            raise RepositoryWriteArtifactAdmissionError(
                "admitted artifact content must be exact immutable bytes"
            )
        if type(self.resolution_receipt) is not RepositoryWriteArtifactResolutionReceipt:
            raise RepositoryWriteArtifactAdmissionError(
                "resolution receipt must be exact resolution receipt"
            )
        if type(self.verification_receipt) is not RepositoryWriteArtifactVerificationReceipt:
            raise RepositoryWriteArtifactAdmissionError(
                "verification receipt must be exact verification receipt"
            )
        if type(self.admission_receipt) is not RepositoryWriteArtifactAdmissionReceipt:
            raise RepositoryWriteArtifactAdmissionError(
                "admission receipt must be exact admission receipt"
            )
        content_sha256 = hashlib.sha256(self.content).hexdigest()
        resolution = self.resolution_receipt
        verification = self.verification_receipt
        admission = self.admission_receipt
        if len(self.content) != resolution.file_size:
            raise RepositoryWriteArtifactAdmissionError(
                "admitted byte length contradicts resolution receipt"
            )
        if content_sha256 != resolution.artifact_content_sha256:
            raise RepositoryWriteArtifactAdmissionError(
                "admitted bytes contradict resolution receipt"
            )
        if content_sha256 != verification.artifact_content_sha256:
            raise RepositoryWriteArtifactAdmissionError(
                "admitted bytes contradict verification receipt"
            )
        if resolution.source_revision != verification.source_revision:
            raise RepositoryWriteArtifactAdmissionError(
                "resolution and verification source revisions differ"
            )
        if resolution.source_tree_revision != verification.source_tree_revision:
            raise RepositoryWriteArtifactAdmissionError(
                "resolution and verification source-tree revisions differ"
            )
        if resolution.artifact_evidence_sha256 != verification.artifact_evidence_sha256:
            raise RepositoryWriteArtifactAdmissionError(
                "resolution and verification artifact evidence differ"
            )
        expected = {
            "source_revision": resolution.source_revision,
            "source_tree_revision": resolution.source_tree_revision,
            "artifact_evidence_sha256": resolution.artifact_evidence_sha256,
            "artifact_content_sha256": content_sha256,
            "inventory_sha256": verification.inventory_sha256,
            "cas_root_sha256": resolution.cas_root_sha256,
            "resolution_receipt_sha256": resolution.digest,
            "verification_receipt_sha256": verification.digest,
        }
        for field_name, expected_value in expected.items():
            if getattr(admission, field_name) != expected_value:
                raise RepositoryWriteArtifactAdmissionError(
                    f"admission receipt contradicts {field_name}"
                )
        if admission.gate_report_v3_sha256 != verification.gate_report_v3_sha256:
            raise RepositoryWriteArtifactAdmissionError(
                "admission receipt contradicts GateReport-v3 binding"
            )
        if resolution.resolved_at != admission.admitted_at:
            raise RepositoryWriteArtifactAdmissionError(
                "resolution time contradicts admission time"
            )
        if verification.verified_at != admission.admitted_at:
            raise RepositoryWriteArtifactAdmissionError(
                "verification time contradicts admission time"
            )


def _require_exact_subjects(
    artifact: RepositoryWriteArtifactEvidence,
    report: GateReportV3,
    root: RepositoryWriteArtifactCASRoot,
) -> None:
    if type(artifact) is not RepositoryWriteArtifactEvidence:
        raise RepositoryWriteArtifactAdmissionError(
            "artifact must be exact RepositoryWriteArtifactEvidence"
        )
    if type(report) is not GateReportV3:
        raise RepositoryWriteArtifactAdmissionError(
            "report must be exact GateReportV3"
        )
    if type(root) is not RepositoryWriteArtifactCASRoot:
        raise RepositoryWriteArtifactAdmissionError(
            "root must be exact RepositoryWriteArtifactCASRoot"
        )


def admit_repository_write_artifact(
    artifact: RepositoryWriteArtifactEvidence,
    report: GateReportV3,
    root: RepositoryWriteArtifactCASRoot,
    *,
    admission_id: str,
    resolution_id: str,
    verification_id: str,
    admitted_at: str,
) -> AdmittedRepositoryWriteArtifact:
    """Resolve, verify, and cross-bind one exact repository-write artifact."""

    _require_exact_subjects(artifact, report, root)
    resolved = resolve_repository_write_artifact(
        artifact,
        root,
        resolution_id=resolution_id,
        resolved_at=admitted_at,
    )
    verification = verify_repository_write_artifact(
        artifact,
        report,
        resolved.content,
        verification_id=verification_id,
        verified_at=admitted_at,
    )
    resolution = resolved.receipt
    report_sha256 = report.to_dict()["report_sha256"]
    if resolution.source_revision != verification.source_revision:
        raise RepositoryWriteArtifactAdmissionError(
            "resolution and verification source revisions differ"
        )
    if resolution.source_tree_revision != verification.source_tree_revision:
        raise RepositoryWriteArtifactAdmissionError(
            "resolution and verification source-tree revisions differ"
        )
    if resolution.artifact_evidence_sha256 != verification.artifact_evidence_sha256:
        raise RepositoryWriteArtifactAdmissionError(
            "resolution and verification artifact evidence differ"
        )
    if resolution.artifact_content_sha256 != verification.artifact_content_sha256:
        raise RepositoryWriteArtifactAdmissionError(
            "resolution and verification content digests differ"
        )
    if verification.gate_report_v3_sha256 != report_sha256:
        raise RepositoryWriteArtifactAdmissionError(
            "verification receipt detached from GateReport-v3"
        )
    provenance = ContractProvenance(
        origin="gate0.repository-write-artifact-admission",
        source_revision=artifact.source_revision,
        created_at=admitted_at,
        input_digests=(
            report_sha256,
            artifact.digest,
            resolution.artifact_content_sha256,
            verification.inventory_sha256,
            root.digest,
            resolution.digest,
            verification.digest,
        ),
    )
    admission = RepositoryWriteArtifactAdmissionReceipt(
        admission_id=admission_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v3_sha256=report_sha256,
        artifact_evidence_sha256=artifact.digest,
        artifact_content_sha256=resolution.artifact_content_sha256,
        inventory_sha256=verification.inventory_sha256,
        cas_root_sha256=root.digest,
        resolution_receipt_sha256=resolution.digest,
        verification_receipt_sha256=verification.digest,
        admitted_at=admitted_at,
        checks=_ADMISSION_CHECKS,
        provenance=provenance,
    )
    return AdmittedRepositoryWriteArtifact(
        content=resolved.content,
        resolution_receipt=resolution,
        verification_receipt=verification,
        admission_receipt=admission,
    )


__all__ = [
    "AdmittedRepositoryWriteArtifact",
    "RepositoryWriteArtifactAdmissionError",
    "RepositoryWriteArtifactAdmissionReceipt",
    "admit_repository_write_artifact",
]
