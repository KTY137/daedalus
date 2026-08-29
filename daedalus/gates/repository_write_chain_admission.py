"""Atomic admission of repository-write chain evidence.

The public admission path accepts no raw artifact byte buffer.  It resolves the
retained ArtifactStore locator, replays the strict byte verifier over those
resolved bytes, authenticates the collector replay attestation over the same
subject, and binds the three receipts into one canonical admission record.

Admission authenticates evidence; it is not equivalent to a successful Gate.
A chain whose retained verification says ``evidence_authenticated=False`` may
remain useful authenticated failure evidence and is retained as such.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
from daedalus.storage import ArtifactStore

from .report_v4 import GateReportV4
from .repository_write_chain_artifact_verifier import (
    RepositoryWriteChainArtifactVerificationError,
    RepositoryWriteChainArtifactVerificationReceipt,
    verify_repository_write_chain_artifact,
)
from .repository_write_chain_collector_attestation import (
    RepositoryWriteChainCollectorAttestation,
    RepositoryWriteChainCollectorAttestationError,
    verify_repository_write_chain_collector_attestation,
)
from .repository_write_chain_evidence import RepositoryWriteChainArtifactEvidence
from .repository_write_chain_result import RepositoryWriteChainResult
from .repository_write_chain_store_resolution import (
    RepositoryWriteChainStoreResolutionError,
    RepositoryWriteChainStoreResolutionReceipt,
    resolve_repository_write_chain_artifact,
)


_ADMISSION_ORIGIN = "gate0.repository-write-chain-admission"
_ADMISSION_CHECKS = tuple(
    sorted(
        (
            "collector-replay-attestation",
            "cross-receipt-binding",
            "store-resolution",
            "strict-byte-verification",
        )
    )
)


class RepositoryWriteChainAdmissionError(RuntimeError):
    """The repository-write chain evidence tuple is not admissible."""


def _as_utc_text(value: datetime, name: str) -> str:
    if not isinstance(value, datetime):
        raise RepositoryWriteChainAdmissionError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryWriteChainAdmissionError(
            f"{name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class RepositoryWriteChainAdmissionReceipt(CanonicalContract):
    """One exact binding of store, byte-verifier, and collector evidence."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-chain-admission-receipt/1"
    )

    admission_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    artifact_evidence_sha256: str
    store_resolution_sha256: str
    artifact_verification_sha256: str
    collector_attestation_sha256: str
    artifact_locator_sha256: str
    artifact_content_sha256: str
    chain_result_sha256: str
    collector_id: str
    collector_key_id: str
    evidence_authenticated: bool
    admitted_at: str
    checks: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "admission_id",
                "collector_id",
                "collector_key_id",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _identifier(getattr(self, field_name), field_name),
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
                "gate_report_v4_sha256",
                "artifact_evidence_sha256",
                "store_resolution_sha256",
                "artifact_verification_sha256",
                "collector_attestation_sha256",
                "artifact_locator_sha256",
                "artifact_content_sha256",
                "chain_result_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainAdmissionError(
                    "evidence_authenticated must be a boolean"
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
        except RepositoryWriteChainAdmissionError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainAdmissionError(
                "repository-write chain admission receipt is malformed"
            ) from exc
        if self.checks != _ADMISSION_CHECKS:
            raise RepositoryWriteChainAdmissionError(
                "admission checks are not exact"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainAdmissionError(
                "admission provenance must be exact ContractProvenance"
            )
        if self.provenance.origin != _ADMISSION_ORIGIN:
            raise RepositoryWriteChainAdmissionError(
                "admission provenance origin is invalid"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainAdmissionError(
                "admission source revision contradicts provenance"
            )
        if self.provenance.created_at != self.admitted_at:
            raise RepositoryWriteChainAdmissionError(
                "admission time contradicts provenance"
            )
        if self.provenance.trace_id != self.admission_id:
            raise RepositoryWriteChainAdmissionError(
                "admission trace_id must equal admission_id"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.artifact_evidence_sha256,
                    self.store_resolution_sha256,
                    self.artifact_verification_sha256,
                    self.collector_attestation_sha256,
                    self.artifact_locator_sha256,
                    self.artifact_content_sha256,
                    self.chain_result_sha256,
                ),
                "repository-write chain admission receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteChainAdmissionError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainAdmissionReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainAdmissionError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainAdmissionError(
                "repository-write chain admission payload is malformed"
            ) from exc


def _require_cross_receipt_binding(
    artifact: RepositoryWriteChainArtifactEvidence,
    resolution: RepositoryWriteChainStoreResolutionReceipt,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
    attestation: RepositoryWriteChainCollectorAttestation,
) -> None:
    expected_resolution = {
        "source_revision": artifact.source_revision,
        "source_tree_revision": artifact.source_tree_revision,
        "gate_report_v4_sha256": artifact.gate_report_v4_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": artifact.chain_result_sha256,
        "evidence_authenticated": artifact.evidence_authenticated,
    }
    resolution_mismatches = sorted(
        field_name
        for field_name, expected in expected_resolution.items()
        if getattr(resolution, field_name) != expected
    )
    if resolution_mismatches:
        raise RepositoryWriteChainAdmissionError(
            "store resolution differs from artifact evidence: "
            + ", ".join(resolution_mismatches)
        )

    expected_verification = {
        "source_revision": artifact.source_revision,
        "source_tree_revision": artifact.source_tree_revision,
        "gate_report_v4_sha256": artifact.gate_report_v4_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": artifact.chain_result_sha256,
        "evidence_authenticated": artifact.evidence_authenticated,
    }
    verification_mismatches = sorted(
        field_name
        for field_name, expected in expected_verification.items()
        if getattr(verification, field_name) != expected
    )
    if verification_mismatches:
        raise RepositoryWriteChainAdmissionError(
            "artifact verification differs from artifact evidence: "
            + ", ".join(verification_mismatches)
        )

    expected_attestation = {
        "source_revision": artifact.source_revision,
        "source_tree_revision": artifact.source_tree_revision,
        "gate_report_v4_sha256": artifact.gate_report_v4_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_verification_sha256": verification.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": artifact.chain_result_sha256,
        "evidence_authenticated": artifact.evidence_authenticated,
    }
    attestation_mismatches = sorted(
        field_name
        for field_name, expected in expected_attestation.items()
        if getattr(attestation, field_name) != expected
    )
    if attestation_mismatches:
        raise RepositoryWriteChainAdmissionError(
            "collector attestation differs from admitted evidence: "
            + ", ".join(attestation_mismatches)
        )


def admit_repository_write_chain(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    retained_result: RepositoryWriteChainResult,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
    attestation: RepositoryWriteChainCollectorAttestation,
    store: ArtifactStore,
    *,
    primary_checkout: str,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_collector_toolchain_sha256: str,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
    resolution_id: str,
    admission_id: str,
) -> RepositoryWriteChainAdmissionReceipt:
    """Admit the exact resolved/verifier/collector tuple without raw-byte input."""

    if type(artifact) is not RepositoryWriteChainArtifactEvidence:
        raise RepositoryWriteChainAdmissionError(
            "artifact must be exact RepositoryWriteChainArtifactEvidence"
        )
    if type(report) is not GateReportV4:
        raise RepositoryWriteChainAdmissionError(
            "report must be exact GateReportV4"
        )
    if type(retained_result) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainAdmissionError(
            "retained_result must be exact RepositoryWriteChainResult"
        )
    if type(verification) is not RepositoryWriteChainArtifactVerificationReceipt:
        raise RepositoryWriteChainAdmissionError(
            "verification must be exact artifact verification receipt"
        )
    if type(attestation) is not RepositoryWriteChainCollectorAttestation:
        raise RepositoryWriteChainAdmissionError(
            "attestation must be exact collector replay attestation"
        )
    admitted_at = _as_utc_text(now, "now")

    try:
        artifact_bytes, resolution = resolve_repository_write_chain_artifact(
            artifact,
            store,
            primary_checkout=primary_checkout,
            resolution_id=resolution_id,
            resolved_at=admitted_at,
        )
    except RepositoryWriteChainStoreResolutionError as exc:
        raise RepositoryWriteChainAdmissionError(
            "ArtifactStore resolution refused"
        ) from exc

    try:
        replayed_verification = verify_repository_write_chain_artifact(
            artifact,
            report,
            artifact_bytes,
            verification_id=verification.verification_id,
            verified_at=verification.verified_at,
        )
    except RepositoryWriteChainArtifactVerificationError as exc:
        raise RepositoryWriteChainAdmissionError(
            "strict artifact verification refused resolved bytes"
        ) from exc
    if replayed_verification.to_dict() != verification.to_dict():
        raise RepositoryWriteChainAdmissionError(
            "retained artifact verification differs from resolved-byte replay"
        )

    _require_cross_receipt_binding(
        artifact,
        resolution,
        verification,
        attestation,
    )
    try:
        verify_repository_write_chain_collector_attestation(
            attestation,
            artifact,
            verification,
            retained_result,
            report,
            artifact_bytes,
            keyring=keyring,
            expected_collector_id=expected_collector_id,
            expected_collector_toolchain_sha256=(
                expected_collector_toolchain_sha256
            ),
            current_revision=current_revision,
            current_tree_revision=current_tree_revision,
            now=now,
        )
    except RepositoryWriteChainCollectorAttestationError as exc:
        raise RepositoryWriteChainAdmissionError(
            "collector replay attestation refused"
        ) from exc

    provenance = ContractProvenance(
        origin=_ADMISSION_ORIGIN,
        source_revision=artifact.source_revision,
        created_at=admitted_at,
        input_digests=tuple(
            sorted(
                {
                    artifact.gate_report_v4_sha256,
                    artifact.digest,
                    resolution.digest,
                    verification.digest,
                    attestation.digest,
                    resolution.artifact_locator_sha256,
                    artifact.artifact_content_sha256,
                    artifact.chain_result_sha256,
                }
            )
        ),
        trace_id=admission_id,
    )
    return RepositoryWriteChainAdmissionReceipt(
        admission_id=admission_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v4_sha256=artifact.gate_report_v4_sha256,
        artifact_evidence_sha256=artifact.digest,
        store_resolution_sha256=resolution.digest,
        artifact_verification_sha256=verification.digest,
        collector_attestation_sha256=attestation.digest,
        artifact_locator_sha256=resolution.artifact_locator_sha256,
        artifact_content_sha256=artifact.artifact_content_sha256,
        chain_result_sha256=artifact.chain_result_sha256,
        collector_id=attestation.collector_id,
        collector_key_id=attestation.collector_key_id,
        evidence_authenticated=artifact.evidence_authenticated,
        admitted_at=admitted_at,
        checks=_ADMISSION_CHECKS,
        provenance=provenance,
    )


__all__ = [
    "RepositoryWriteChainAdmissionError",
    "RepositoryWriteChainAdmissionReceipt",
    "admit_repository_write_chain",
]
