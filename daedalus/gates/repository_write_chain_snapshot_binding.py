"""Independent shared-snapshot verification for GateReport-v4 chain evidence.

GateReport-v4 historically composed a stable GateReport-v3 snapshot and a
stable chain-binding snapshot independently.  Two independently stable
snapshots are not proof that they are the *same* snapshot.  This verifier
reconstructs one classification projection from the exact inventory,
declaration, and signed non-runtime sidecar, binds the retained chain result to
that projection, and then requires every repository-write field visible in the
GateReport to agree with the same typed subjects.

The resulting receipt authenticates a snapshot relationship only.  It does not
close Gate 0 or authorize release/promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)

from .report_v4 import (
    GateReportV4,
    GateReportV4Error,
    verify_repository_write_chain_result_binding,
)
from .repository_write_chain_result import (
    CHAIN_RESULT_SCHEMA,
    RepositoryWriteChainResult,
    RepositoryWriteChainSurface,
)
from .repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    NON_BLOCKING_SURFACE_VERDICT,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    UNCLASSIFIED_SURFACE_VERDICT,
    RepositoryWriteClassificationReport,
    surface_binding_sha256,
    surface_classification_verdict,
)
from .repository_write_inventory_v2 import RepositoryWriteInventoryV2
from .repository_write_non_runtime_sidecar import (
    RepositoryWriteNonRuntimeBindingSet,
    RepositoryWriteNonRuntimeSidecarError,
    project_classification_input_with_non_runtime_sidecar,
)


_SNAPSHOT_ORIGIN = "gate0.repository-write-chain-shared-snapshot"
_INVENTORY_SCHEMA = "daedalus-gate0-repository-write-inventory/2"


class RepositoryWriteChainSnapshotBindingError(RuntimeError):
    """GateReport, inventory, classification, sidecar and chain do not agree."""


def _non_negative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteChainSnapshotBindingError(
            f"{name} must be a non-negative integer"
        )
    return value


def _surface_failure_row(surface: object, verdict: str, doors: tuple[str, ...]) -> str:
    row = (
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        f":verdict={verdict}"
    )
    if doors:
        row = f"{row}:door={','.join(doors)}"
    return row


def _snapshot_verdicts(
    inventory: RepositoryWriteInventoryV2,
    projection: RepositoryWriteClassificationReport,
) -> tuple[str, ...]:
    classified = {row.surface: row for row in projection.classifications}
    census: dict[str, int] = {}
    for surface in inventory.surfaces:
        if not surface.blocking:
            verdict = NON_BLOCKING_SURFACE_VERDICT
        else:
            row = classified.get(surface)
            verdict = (
                UNCLASSIFIED_SURFACE_VERDICT
                if row is None
                else surface_classification_verdict(row)
            )
        census[verdict] = census.get(verdict, 0) + 1
    return tuple(sorted(f"{name}:{count}" for name, count in census.items()))


def _classification_failures(
    inventory: RepositoryWriteInventoryV2,
    projection: RepositoryWriteClassificationReport,
) -> tuple[str, ...]:
    classified = {row.surface: row for row in projection.classifications}
    rows: list[str] = []
    for surface in inventory.surfaces:
        if not surface.blocking:
            continue
        classification = classified.get(surface)
        if classification is None:
            rows.append(
                _surface_failure_row(
                    surface,
                    UNCLASSIFIED_SURFACE_VERDICT,
                    (),
                )
            )
            continue
        if classification.candidate_blockers:
            rows.append(
                _surface_failure_row(
                    surface,
                    surface_classification_verdict(classification),
                    classification.guard_contracts,
                )
            )
    return tuple(sorted(set(rows)))


def _authentication_failures(
    projection: RepositoryWriteClassificationReport,
    bound: Mapping[object, RepositoryWriteChainSurface],
) -> tuple[str, ...]:
    rows: list[str] = []
    for classification in projection.classifications:
        if classification.candidate_blockers:
            continue
        record = bound[classification.surface]
        if record.authenticated:
            continue
        pending = sorted(
            name
            for name, verdict in record.stages
            if verdict
            not in {STAGE_VERDICT_VERIFIED, STAGE_VERDICT_NOT_APPLICABLE}
        )
        rows.append(
            "classification:surface-unauthenticated:"
            f"{classification.surface.path}:"
            f"{classification.surface.line}:"
            f"{classification.surface.column}:"
            f"stages={','.join(pending) if pending else 'none'}"
        )
    if rows:
        rows.append(f"classification:evidence-unauthenticated:{len(rows)}")
    return tuple(sorted(set(rows)))


def _require_sidecar_projection_binding(
    projection: RepositoryWriteClassificationReport,
    binding_set: RepositoryWriteNonRuntimeBindingSet,
) -> None:
    declared = {item.surface_sha256: item for item in binding_set.bindings}
    consumed: set[str] = set()
    for row in projection.classifications:
        digest = surface_binding_sha256(row.source_revision, row.surface)
        admission = row.non_runtime_conformity
        binding = declared.get(digest)
        if admission is None:
            if binding is not None:
                raise RepositoryWriteChainSnapshotBindingError(
                    "sidecar binding was not retained in reconstructed classification"
                )
            continue
        if binding is None:
            raise RepositoryWriteChainSnapshotBindingError(
                "reconstructed non-runtime admission has no sidecar binding"
            )
        if admission.binding.to_dict() != binding.to_dict():
            raise RepositoryWriteChainSnapshotBindingError(
                "reconstructed non-runtime admission differs from sidecar binding"
            )
        consumed.add(digest)
    if consumed != set(declared):
        raise RepositoryWriteChainSnapshotBindingError(
            "non-runtime sidecar coverage differs from reconstructed classification"
        )


def _require_report_fields(
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    projection: RepositoryWriteClassificationReport,
    chain_result: RepositoryWriteChainResult,
    expected_failures: tuple[str, ...],
) -> None:
    expected = {
        "source_revision": inventory.source_revision,
        "repository_write_inventory_sha256": inventory.digest,
        "repository_write_scan_input_sha256": inventory.scan_input_sha256,
        "repository_write_files_scanned": inventory.files_scanned,
        "repository_write_inventory_generation": 2,
        "repository_write_inventory_schema": _INVENTORY_SCHEMA,
        "repository_write_scanner_error": 0,
        "repository_write_surfaces_total": len(inventory.surfaces),
        "repository_write_classification_schema": CLASSIFICATION_SCHEMA,
        "repository_write_surface_verdicts": _snapshot_verdicts(
            inventory, projection
        ),
        "repository_write_failures": expected_failures,
        "repository_write_chain_result_schema": CHAIN_RESULT_SCHEMA,
        "repository_write_chain_result_sha256": chain_result.digest,
    }
    mismatches = sorted(
        name
        for name, expected_value in expected.items()
        if getattr(report, name) != expected_value
    )
    if mismatches:
        raise RepositoryWriteChainSnapshotBindingError(
            "GateReport-v4 repository-write fields differ from shared snapshot: "
            + ", ".join(mismatches)
        )


@dataclass(frozen=True)
class RepositoryWriteChainSnapshotBindingReceipt(CanonicalContract):
    """Canonical proof that report and chain were checked against one snapshot."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-chain-shared-snapshot-receipt/1"
    )

    binding_id: str
    source_revision: str
    gate_report_v4_sha256: str
    inventory_sha256: str
    classification_sha256: str
    chain_result_sha256: str
    non_runtime_binding_set_sha256: str
    inventory_surface_count: int
    classified_surface_count: int
    missing_surface_count: int
    authenticated_surface_count: int
    verified_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "binding_id",
                _identifier(self.binding_id, "binding_id"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field_name in (
                "gate_report_v4_sha256",
                "inventory_sha256",
                "classification_sha256",
                "chain_result_sha256",
                "non_runtime_binding_set_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            for field_name in (
                "inventory_surface_count",
                "classified_surface_count",
                "missing_surface_count",
                "authenticated_surface_count",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _non_negative(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "verified_at",
                _utc_timestamp(self.verified_at, "verified_at"),
            )
        except RepositoryWriteChainSnapshotBindingError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot receipt is malformed"
            ) from exc
        if self.classified_surface_count + self.missing_surface_count != self.inventory_surface_count:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot receipt surface counts are inconsistent"
            )
        if self.authenticated_surface_count > self.classified_surface_count:
            raise RepositoryWriteChainSnapshotBindingError(
                "authenticated count exceeds classified count"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot provenance must be exact ContractProvenance"
            )
        if self.provenance.origin != _SNAPSHOT_ORIGIN:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot provenance origin is invalid"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot revision contradicts provenance"
            )
        if self.provenance.created_at != self.verified_at:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot time contradicts provenance"
            )
        if self.provenance.trace_id != self.binding_id:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot trace_id must equal binding_id"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.inventory_sha256,
                    self.classification_sha256,
                    self.chain_result_sha256,
                    self.non_runtime_binding_set_sha256,
                ),
                "repository-write shared-snapshot receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteChainSnapshotBindingError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainSnapshotBindingReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainSnapshotBindingError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainSnapshotBindingError(
                "shared-snapshot receipt payload is malformed"
            ) from exc


def verify_repository_write_chain_shared_snapshot(
    report: GateReportV4,
    inventory: RepositoryWriteInventoryV2,
    classification_input: Mapping[str, object],
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    chain_result: RepositoryWriteChainResult,
    *,
    subjects: Mapping[str, object],
    collector_secrets: Mapping[str, bytes | str],
    binding_id: str,
    verified_at: str,
) -> RepositoryWriteChainSnapshotBindingReceipt:
    """Reconstruct and verify one exact shared repository-write snapshot."""

    if type(report) is not GateReportV4:
        raise RepositoryWriteChainSnapshotBindingError(
            "shared-snapshot report must be exact GateReportV4"
        )
    if type(inventory) is not RepositoryWriteInventoryV2:
        raise RepositoryWriteChainSnapshotBindingError(
            "shared-snapshot inventory must be exact inventory-v2"
        )
    if type(binding_set) is not RepositoryWriteNonRuntimeBindingSet:
        raise RepositoryWriteChainSnapshotBindingError(
            "shared-snapshot sidecar must be exact binding set"
        )
    if type(chain_result) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainSnapshotBindingError(
            "shared-snapshot chain result must be exact typed result"
        )
    try:
        projection = project_classification_input_with_non_runtime_sidecar(
            inventory,
            classification_input,
            binding_set,
            subjects=subjects,
            collector_secrets=collector_secrets,
        )
    except RepositoryWriteNonRuntimeSidecarError as exc:
        raise RepositoryWriteChainSnapshotBindingError(
            "shared-snapshot classification reconstruction refused"
        ) from exc
    _require_sidecar_projection_binding(projection, binding_set)
    try:
        bound = verify_repository_write_chain_result_binding(
            inventory,
            projection,
            chain_result,
        )
    except GateReportV4Error as exc:
        raise RepositoryWriteChainSnapshotBindingError(
            "chain result differs from reconstructed shared snapshot"
        ) from exc

    failures = tuple(
        sorted(
            set(_classification_failures(inventory, projection)).union(
                _authentication_failures(projection, bound)
            )
        )
    )
    _require_report_fields(
        report,
        inventory,
        projection,
        chain_result,
        failures,
    )
    report_sha256 = report.to_dict()["report_sha256"]
    provenance = ContractProvenance(
        origin=_SNAPSHOT_ORIGIN,
        source_revision=inventory.source_revision,
        created_at=verified_at,
        input_digests=tuple(
            sorted(
                {
                    report_sha256,
                    inventory.digest,
                    projection.digest,
                    chain_result.digest,
                    binding_set.digest,
                }
            )
        ),
        trace_id=binding_id,
    )
    return RepositoryWriteChainSnapshotBindingReceipt(
        binding_id=binding_id,
        source_revision=inventory.source_revision,
        gate_report_v4_sha256=report_sha256,
        inventory_sha256=inventory.digest,
        classification_sha256=projection.digest,
        chain_result_sha256=chain_result.digest,
        non_runtime_binding_set_sha256=binding_set.digest,
        inventory_surface_count=len(inventory.surfaces),
        classified_surface_count=len(projection.classifications),
        missing_surface_count=len(projection.missing_surfaces),
        authenticated_surface_count=sum(
            1 for record in bound.values() if record.authenticated
        ),
        verified_at=verified_at,
        provenance=provenance,
    )


__all__ = [
    "RepositoryWriteChainSnapshotBindingError",
    "RepositoryWriteChainSnapshotBindingReceipt",
    "verify_repository_write_chain_shared_snapshot",
]
