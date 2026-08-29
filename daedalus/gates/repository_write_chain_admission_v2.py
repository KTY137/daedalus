"""Gate-0 repository-write admission v2: one release-facing evidence subject.

Version 1 authenticates the retained ArtifactStore bytes, mechanical verifier
receipt, and external collector replay attestation.  This additive version also
requires an independently reconstructed shared inventory/classification
snapshot, including any signed/replayed non-runtime conformity sidecar.

The public API accepts no raw artifact bytes and no caller-projected
classification report.  It reconstructs both lower-level receipts and binds
them into one canonical record.  The record remains evidence only: successful
admission is not Gate closure, OwnerApproval, release, merge, or promotion.
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
from .repository_write_chain_admission import (
    RepositoryWriteChainAdmissionError,
    RepositoryWriteChainAdmissionReceipt,
    admit_repository_write_chain,
)
from .repository_write_chain_artifact_verifier import (
    RepositoryWriteChainArtifactVerificationReceipt,
)
from .repository_write_chain_collector_attestation import (
    RepositoryWriteChainCollectorAttestation,
)
from .repository_write_chain_evidence import RepositoryWriteChainArtifactEvidence
from .repository_write_chain_result import RepositoryWriteChainResult
from .repository_write_chain_snapshot_binding import (
    RepositoryWriteChainSnapshotBindingError,
    RepositoryWriteChainSnapshotBindingReceipt,
    verify_repository_write_chain_shared_snapshot,
)
from .repository_write_inventory_v2 import RepositoryWriteInventoryV2
from .repository_write_non_runtime_sidecar import RepositoryWriteNonRuntimeBindingSet


_ADMISSION_V2_ORIGIN = "gate0.repository-write-chain-admission-v2"
_ADMISSION_V2_CHECKS = tuple(
    sorted(
        (
            "authenticated-artifact-admission",
            "cross-admission-binding",
            "shared-inventory-classification-snapshot",
        )
    )
)


class RepositoryWriteChainAdmissionV2Error(RuntimeError):
    """The complete repository-write evidence subject is not admissible."""


def _as_utc_text(value: datetime, name: str) -> str:
    if not isinstance(value, datetime):
        raise RepositoryWriteChainAdmissionV2Error(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryWriteChainAdmissionV2Error(
            f"{name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _derived_authenticated(
    snapshot: RepositoryWriteChainSnapshotBindingReceipt,
) -> bool:
    return bool(
        snapshot.classified_surface_count > 0
        and snapshot.missing_surface_count == 0
        and snapshot.authenticated_surface_count
        == snapshot.classified_surface_count
    )


@dataclass(frozen=True)
class RepositoryWriteChainAdmissionV2Receipt(CanonicalContract):
    """One binding of shared snapshot and authenticated artifact admission."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-chain-admission-receipt/2"
    )

    admission_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    inventory_sha256: str
    classification_sha256: str
    non_runtime_binding_set_sha256: str
    chain_result_sha256: str
    artifact_evidence_sha256: str
    shared_snapshot_sha256: str
    artifact_admission_sha256: str
    artifact_locator_sha256: str
    artifact_content_sha256: str
    collector_attestation_sha256: str
    evidence_authenticated: bool
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
                "gate_report_v4_sha256",
                "inventory_sha256",
                "classification_sha256",
                "non_runtime_binding_set_sha256",
                "chain_result_sha256",
                "artifact_evidence_sha256",
                "shared_snapshot_sha256",
                "artifact_admission_sha256",
                "artifact_locator_sha256",
                "artifact_content_sha256",
                "collector_attestation_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainAdmissionV2Error(
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
        except RepositoryWriteChainAdmissionV2Error:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainAdmissionV2Error(
                "repository-write chain admission-v2 receipt is malformed"
            ) from exc
        if self.checks != _ADMISSION_V2_CHECKS:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 checks are not exact"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 provenance must be exact ContractProvenance"
            )
        if self.provenance.origin != _ADMISSION_V2_ORIGIN:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 provenance origin is invalid"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 revision contradicts provenance"
            )
        if self.provenance.created_at != self.admitted_at:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 time contradicts provenance"
            )
        if self.provenance.trace_id != self.admission_id:
            raise RepositoryWriteChainAdmissionV2Error(
                "admission-v2 trace_id must equal admission_id"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.inventory_sha256,
                    self.classification_sha256,
                    self.non_runtime_binding_set_sha256,
                    self.chain_result_sha256,
                    self.artifact_evidence_sha256,
                    self.shared_snapshot_sha256,
                    self.artifact_admission_sha256,
                    self.artifact_locator_sha256,
                    self.artifact_content_sha256,
                    self.collector_attestation_sha256,
                ),
                "repository-write chain admission-v2 receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteChainAdmissionV2Error(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainAdmissionV2Receipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainAdmissionV2Error:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainAdmissionV2Error(
                "repository-write chain admission-v2 payload is malformed"
            ) from exc


def _require_cross_binding(
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    chain_result: RepositoryWriteChainResult,
    artifact: RepositoryWriteChainArtifactEvidence,
    attestation: RepositoryWriteChainCollectorAttestation,
    snapshot: RepositoryWriteChainSnapshotBindingReceipt,
    artifact_admission: RepositoryWriteChainAdmissionReceipt,
    *,
    admitted_at: str,
) -> None:
    report_sha256 = report.to_dict()["report_sha256"]
    expected_snapshot = {
        "source_revision": inventory.source_revision,
        "gate_report_v4_sha256": report_sha256,
        "inventory_sha256": inventory.digest,
        "classification_sha256": chain_result.classification_digest,
        "chain_result_sha256": chain_result.digest,
        "non_runtime_binding_set_sha256": binding_set.digest,
        "verified_at": admitted_at,
    }
    snapshot_mismatches = sorted(
        name
        for name, expected in expected_snapshot.items()
        if getattr(snapshot, name) != expected
    )
    if snapshot_mismatches:
        raise RepositoryWriteChainAdmissionV2Error(
            "shared-snapshot receipt differs from admitted subject: "
            + ", ".join(snapshot_mismatches)
        )

    expected_artifact = {
        "source_revision": inventory.source_revision,
        "source_tree_revision": artifact.source_tree_revision,
        "gate_report_v4_sha256": report_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": chain_result.digest,
        "collector_attestation_sha256": attestation.digest,
        "evidence_authenticated": _derived_authenticated(snapshot),
        "admitted_at": admitted_at,
    }
    artifact_mismatches = sorted(
        name
        for name, expected in expected_artifact.items()
        if getattr(artifact_admission, name) != expected
    )
    if artifact_mismatches:
        raise RepositoryWriteChainAdmissionV2Error(
            "artifact admission differs from shared admitted subject: "
            + ", ".join(artifact_mismatches)
        )
    if artifact.source_revision != inventory.source_revision:
        raise RepositoryWriteChainAdmissionV2Error(
            "artifact source revision differs from shared snapshot"
        )
    if artifact.chain_result_sha256 != chain_result.digest:
        raise RepositoryWriteChainAdmissionV2Error(
            "artifact chain digest differs from shared snapshot"
        )


def admit_repository_write_chain_v2(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    classification_input: Mapping[str, object],
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    retained_result: RepositoryWriteChainResult,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
    attestation: RepositoryWriteChainCollectorAttestation,
    store: ArtifactStore,
    *,
    primary_checkout: str,
    subjects: Mapping[str, object],
    non_runtime_collector_secrets: Mapping[str, bytes | str],
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_collector_toolchain_sha256: str,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
    snapshot_binding_id: str,
    resolution_id: str,
    artifact_admission_id: str,
    admission_id: str,
) -> RepositoryWriteChainAdmissionV2Receipt:
    """Reconstruct every repository-write trust layer and bind one v2 receipt."""

    if type(artifact) is not RepositoryWriteChainArtifactEvidence:
        raise RepositoryWriteChainAdmissionV2Error(
            "artifact must be exact repository-write artifact evidence"
        )
    if type(report) is not GateReportV4:
        raise RepositoryWriteChainAdmissionV2Error(
            "report must be exact GateReportV4"
        )
    if type(inventory) is not RepositoryWriteInventoryV2:
        raise RepositoryWriteChainAdmissionV2Error(
            "inventory must be exact repository-write inventory-v2"
        )
    if type(binding_set) is not RepositoryWriteNonRuntimeBindingSet:
        raise RepositoryWriteChainAdmissionV2Error(
            "binding_set must be exact non-runtime binding set"
        )
    if type(retained_result) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainAdmissionV2Error(
            "retained_result must be exact chain result"
        )
    admitted_at = _as_utc_text(now, "now")

    try:
        snapshot = verify_repository_write_chain_shared_snapshot(
            report,
            inventory,
            classification_input,
            binding_set,
            retained_result,
            subjects=subjects,
            collector_secrets=non_runtime_collector_secrets,
            binding_id=snapshot_binding_id,
            verified_at=admitted_at,
        )
    except RepositoryWriteChainSnapshotBindingError as exc:
        raise RepositoryWriteChainAdmissionV2Error(
            "shared inventory/classification snapshot refused"
        ) from exc

    try:
        artifact_admission = admit_repository_write_chain(
            artifact,
            report,
            retained_result,
            verification,
            attestation,
            store,
            primary_checkout=primary_checkout,
            keyring=collector_keyring,
            expected_collector_id=expected_collector_id,
            expected_collector_toolchain_sha256=(
                expected_collector_toolchain_sha256
            ),
            current_revision=current_revision,
            current_tree_revision=current_tree_revision,
            now=now,
            resolution_id=resolution_id,
            admission_id=artifact_admission_id,
        )
    except RepositoryWriteChainAdmissionError as exc:
        raise RepositoryWriteChainAdmissionV2Error(
            "authenticated artifact admission refused"
        ) from exc

    _require_cross_binding(
        report,
        inventory,
        binding_set,
        retained_result,
        artifact,
        attestation,
        snapshot,
        artifact_admission,
        admitted_at=admitted_at,
    )
    provenance = ContractProvenance(
        origin=_ADMISSION_V2_ORIGIN,
        source_revision=inventory.source_revision,
        created_at=admitted_at,
        input_digests=tuple(
            sorted(
                {
                    snapshot.gate_report_v4_sha256,
                    snapshot.inventory_sha256,
                    snapshot.classification_sha256,
                    snapshot.non_runtime_binding_set_sha256,
                    snapshot.chain_result_sha256,
                    artifact.digest,
                    snapshot.digest,
                    artifact_admission.digest,
                    artifact_admission.artifact_locator_sha256,
                    artifact.artifact_content_sha256,
                    attestation.digest,
                }
            )
        ),
        trace_id=admission_id,
    )
    return RepositoryWriteChainAdmissionV2Receipt(
        admission_id=admission_id,
        source_revision=inventory.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v4_sha256=snapshot.gate_report_v4_sha256,
        inventory_sha256=snapshot.inventory_sha256,
        classification_sha256=snapshot.classification_sha256,
        non_runtime_binding_set_sha256=snapshot.non_runtime_binding_set_sha256,
        chain_result_sha256=snapshot.chain_result_sha256,
        artifact_evidence_sha256=artifact.digest,
        shared_snapshot_sha256=snapshot.digest,
        artifact_admission_sha256=artifact_admission.digest,
        artifact_locator_sha256=artifact_admission.artifact_locator_sha256,
        artifact_content_sha256=artifact.artifact_content_sha256,
        collector_attestation_sha256=attestation.digest,
        evidence_authenticated=artifact_admission.evidence_authenticated,
        admitted_at=admitted_at,
        checks=_ADMISSION_V2_CHECKS,
        provenance=provenance,
    )


__all__ = [
    "RepositoryWriteChainAdmissionV2Error",
    "RepositoryWriteChainAdmissionV2Receipt",
    "admit_repository_write_chain_v2",
]
