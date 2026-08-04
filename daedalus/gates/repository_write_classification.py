"""Revision-bound classification contract for repository write surfaces.

This module is deliberately preparatory.  It can bind reviewed declarations to
one generation-2 inventory, but it cannot authenticate external receipts, alter
the canonical effect registry, prove Primary-Checkout disjointness, or close
Gate 0.  Later packets may consume the report only after independently
verifying the referenced evidence and binding it into the release GateReport.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.spine.envelope import canonical_json


_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class RepositoryWriteClassificationError(RuntimeError):
    """A classification projection was malformed, stale, or ambiguous."""


class TargetDisposition(str, Enum):
    PRIMARY_CHECKOUT = "primary_checkout"
    CHECKOUT_EXTERNAL = "checkout_external"
    NON_REPOSITORY = "non_repository"
    UNKNOWN = "unknown"


class GuardDisposition(str, Enum):
    CENTRAL = "central"
    LOCAL_GUARDS = "local_guards"
    INVENTORY_ONLY = "inventory_only"
    UNGUARDED = "unguarded"
    RETIRED = "retired"


class EvidenceKind(str, Enum):
    SOURCE_ANCHOR = "source_anchor"
    GUARD_CONTRACT = "guard_contract"
    EFFECT_LEASE_RECEIPT = "effect_lease_receipt"
    RUNTIME_CONFORMANCE_RECEIPT = "runtime_conformance_receipt"
    PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT = (
        "primary_checkout_disjointness_receipt"
    )
    RETIREMENT_RECEIPT = "retirement_receipt"


@dataclass(frozen=True)
class EvidenceBinding:
    kind: EvidenceKind
    source_revision: str
    sha256: str
    locator: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("evidence kind must be typed")
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("evidence source_revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("evidence sha256 must be lowercase 64-hex")
        if (
            not isinstance(self.locator, str)
            or not self.locator.strip()
            or any(ch in self.locator for ch in "\r\n")
        ):
            raise ValueError("evidence locator must be a non-empty single line")

    def sort_key(self) -> tuple[str, str, str, str]:
        return (self.kind.value, self.source_revision, self.sha256, self.locator)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "source_revision": self.source_revision,
            "sha256": self.sha256,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "EvidenceBinding":
        _require_exact_keys(
            value,
            {"kind", "source_revision", "sha256", "locator"},
            "evidence binding",
        )
        try:
            kind = EvidenceKind(_strict_str(value["kind"], "evidence kind"))
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "evidence kind is unknown"
            ) from exc
        try:
            return cls(
                kind=kind,
                source_revision=_strict_str(
                    value["source_revision"], "evidence source_revision"
                ),
                sha256=_strict_str(value["sha256"], "evidence sha256"),
                locator=_strict_str(value["locator"], "evidence locator"),
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "evidence binding is invalid"
            ) from exc


@dataclass(frozen=True)
class SurfaceClassification:
    source_revision: str
    surface: RepositoryWriteSurface
    target: TargetDisposition
    guard: GuardDisposition
    production_reachable: bool
    guard_contracts: tuple[str, ...]
    evidence: tuple[EvidenceBinding, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("classification source_revision must be lowercase 40-hex")
        if not isinstance(self.surface, RepositoryWriteSurface):
            raise ValueError("classification surface must be typed")
        if not isinstance(self.target, TargetDisposition):
            raise ValueError("target disposition must be typed")
        if not isinstance(self.guard, GuardDisposition):
            raise ValueError("guard disposition must be typed")
        if type(self.production_reachable) is not bool:
            raise ValueError("production_reachable must be a strict boolean")
        if not isinstance(self.guard_contracts, tuple):
            raise ValueError("guard_contracts must be an immutable tuple")
        if tuple(sorted(self.guard_contracts)) != self.guard_contracts:
            raise ValueError("guard_contracts must be sorted")
        if len(set(self.guard_contracts)) != len(self.guard_contracts):
            raise ValueError("guard_contracts must be unique")
        if any(not _CONTRACT.fullmatch(name) for name in self.guard_contracts):
            raise ValueError("guard contract name is invalid")
        if not isinstance(self.evidence, tuple):
            raise ValueError("evidence must be an immutable tuple")
        if tuple(sorted(self.evidence, key=EvidenceBinding.sort_key)) != self.evidence:
            raise ValueError("evidence must be canonically sorted")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("evidence must be unique")
        if any(item.source_revision != self.source_revision for item in self.evidence):
            raise ValueError("evidence revision differs from classification revision")
        if not isinstance(self.notes, str) or any(ch in self.notes for ch in "\r\n"):
            raise ValueError("notes must be a single line")

        kinds = {item.kind for item in self.evidence}
        if self.target in {
            TargetDisposition.CHECKOUT_EXTERNAL,
            TargetDisposition.NON_REPOSITORY,
        } and EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT not in kinds:
            raise ValueError(
                "disjoint target classification requires a disjointness receipt"
            )
        if self.guard is GuardDisposition.CENTRAL:
            required = {
                EvidenceKind.GUARD_CONTRACT,
                EvidenceKind.EFFECT_LEASE_RECEIPT,
                EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
                EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            }
            if self.target in {
                TargetDisposition.PRIMARY_CHECKOUT,
                TargetDisposition.UNKNOWN,
            }:
                raise ValueError("central classification requires a disjoint target")
            if not self.guard_contracts:
                raise ValueError("central classification requires guard contracts")
            if not required.issubset(kinds):
                raise ValueError("central classification lacks required evidence kinds")
        elif self.guard is GuardDisposition.LOCAL_GUARDS:
            if not self.guard_contracts:
                raise ValueError("local_guards requires guard contracts")
            if EvidenceKind.GUARD_CONTRACT not in kinds:
                raise ValueError("local_guards requires guard-contract evidence")
        elif self.guard is GuardDisposition.RETIRED:
            if self.production_reachable:
                raise ValueError("retired classification cannot remain production reachable")
            if self.guard_contracts:
                raise ValueError("retired classification cannot declare guard contracts")
            if EvidenceKind.RETIREMENT_RECEIPT not in kinds:
                raise ValueError("retired classification requires a retirement receipt")

    def sort_key(self) -> tuple[str, int, int, str]:
        return (
            self.surface.path,
            self.surface.line,
            self.surface.column,
            self.surface.origin,
        )

    @property
    def candidate_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.target is TargetDisposition.PRIMARY_CHECKOUT:
            blockers.append("primary-checkout-write-target")
        elif self.target is TargetDisposition.UNKNOWN:
            blockers.append("write-target-unknown")
        if self.production_reachable and self.guard is not GuardDisposition.CENTRAL:
            blockers.append(f"production-write-{self.guard.value}")
        return tuple(blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_revision": self.source_revision,
            "surface": self.surface.to_dict(),
            "target": self.target.value,
            "guard": self.guard.value,
            "production_reachable": self.production_reachable,
            "guard_contracts": list(self.guard_contracts),
            "evidence": [item.to_dict() for item in self.evidence],
            "notes": self.notes,
            "candidate_blockers": list(self.candidate_blockers),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SurfaceClassification":
        _require_exact_keys(
            value,
            {
                "source_revision",
                "surface",
                "target",
                "guard",
                "production_reachable",
                "guard_contracts",
                "evidence",
                "notes",
            },
            "surface classification",
        )
        surface = _surface_from_dict(_strict_mapping(value["surface"], "surface"))
        try:
            target = TargetDisposition(
                _strict_str(value["target"], "target disposition")
            )
            guard = GuardDisposition(
                _strict_str(value["guard"], "guard disposition")
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "classification disposition is unknown"
            ) from exc
        contracts_raw = _strict_list(value["guard_contracts"], "guard_contracts")
        evidence_raw = _strict_list(value["evidence"], "evidence")
        try:
            return cls(
                source_revision=_strict_str(
                    value["source_revision"], "classification source_revision"
                ),
                surface=surface,
                target=target,
                guard=guard,
                production_reachable=_strict_bool(
                    value["production_reachable"], "production_reachable"
                ),
                guard_contracts=tuple(
                    _strict_str(item, "guard contract") for item in contracts_raw
                ),
                evidence=tuple(
                    EvidenceBinding.from_dict(
                        _strict_mapping(item, "evidence binding")
                    )
                    for item in evidence_raw
                ),
                notes=_strict_str(value["notes"], "notes"),
            )
        except ValueError as exc:
            raise RepositoryWriteClassificationError(
                "surface classification is invalid"
            ) from exc


@dataclass(frozen=True)
class RepositoryWriteClassificationReport:
    source_revision: str
    inventory_digest: str
    scan_input_sha256: str
    inventory_surface_count: int
    classifications: tuple[SurfaceClassification, ...]
    missing_surfaces: tuple[RepositoryWriteSurface, ...]

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("report source_revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.inventory_digest):
            raise ValueError("inventory_digest must be lowercase sha256")
        if not _SHA256.fullmatch(self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if type(self.inventory_surface_count) is not int or self.inventory_surface_count < 0:
            raise ValueError("inventory_surface_count must be a non-negative integer")
        if not isinstance(self.classifications, tuple):
            raise ValueError("classifications must be an immutable tuple")
        if any(not isinstance(row, SurfaceClassification) for row in self.classifications):
            raise ValueError("classification row type is invalid")
        if not isinstance(self.missing_surfaces, tuple):
            raise ValueError("missing_surfaces must be an immutable tuple")
        if any(not isinstance(row, RepositoryWriteSurface) for row in self.missing_surfaces):
            raise ValueError("missing surface type is invalid")
        if tuple(sorted(self.classifications, key=SurfaceClassification.sort_key)) != self.classifications:
            raise ValueError("classifications must be sorted")
        if tuple(sorted(self.missing_surfaces)) != self.missing_surfaces:
            raise ValueError("missing_surfaces must be sorted")
        classified = tuple(row.surface for row in self.classifications)
        if len(set(classified)) != len(classified):
            raise ValueError("classification surfaces must be unique")
        if len(set(self.missing_surfaces)) != len(self.missing_surfaces):
            raise ValueError("missing surfaces must be unique")
        if set(classified).intersection(self.missing_surfaces):
            raise ValueError("classified and missing surfaces must be disjoint")
        if any(row.source_revision != self.source_revision for row in self.classifications):
            raise ValueError("classification revision differs from report revision")
        if self.inventory_surface_count != len(classified) + len(self.missing_surfaces):
            raise ValueError("inventory surface count does not match report projection")

    @property
    def candidate_blockers(self) -> tuple[str, ...]:
        values: set[str] = set()
        if self.missing_surfaces:
            values.add("unclassified-production-write-surfaces")
        for row in self.classifications:
            values.update(row.candidate_blockers)
        return tuple(sorted(values))

    @property
    def classification_ready(self) -> bool:
        return not self.missing_surfaces and not self.candidate_blockers

    def _payload(self) -> dict[str, object]:
        blockers = list(self.candidate_blockers)
        blockers.extend(
            [
                "authenticated-evidence-verification-missing",
                "gate-report-binding-missing",
            ]
        )
        return {
            "schema": "daedalus-gate0-repository-write-classification/1",
            "source_revision": self.source_revision,
            "inventory_digest": self.inventory_digest,
            "scan_input_sha256": self.scan_input_sha256,
            "inventory_surface_count": self.inventory_surface_count,
            "classification_count": len(self.classifications),
            "classifications": [row.to_dict() for row in self.classifications],
            "missing_surfaces": [row.to_dict() for row in self.missing_surfaces],
            "classification_ready": self.classification_ready,
            "evidence_authenticated": False,
            "primary_checkout_target_proven": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-classification-preparation",
            "blockers": sorted(set(blockers)),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def project_repository_write_classifications(
    inventory: RepositoryWriteInventoryV2,
    classifications: Iterable[SurfaceClassification],
) -> RepositoryWriteClassificationReport:
    if not isinstance(inventory, RepositoryWriteInventoryV2):
        raise RepositoryWriteClassificationError("inventory type is invalid")
    rows_unsorted = tuple(classifications)
    if any(not isinstance(row, SurfaceClassification) for row in rows_unsorted):
        raise RepositoryWriteClassificationError("classification type is invalid")
    rows = tuple(sorted(rows_unsorted, key=SurfaceClassification.sort_key))
    if any(row.source_revision != inventory.source_revision for row in rows):
        raise RepositoryWriteClassificationError(
            "classification source revision differs from inventory"
        )
    by_surface: dict[RepositoryWriteSurface, SurfaceClassification] = {}
    inventory_surfaces = set(inventory.surfaces)
    for row in rows:
        if row.surface not in inventory_surfaces:
            raise RepositoryWriteClassificationError(
                "classification surface is absent from the bound inventory"
            )
        if row.surface in by_surface:
            raise RepositoryWriteClassificationError(
                "classification surface is duplicated"
            )
        by_surface[row.surface] = row
    missing = tuple(sorted(inventory_surfaces - set(by_surface)))
    return RepositoryWriteClassificationReport(
        source_revision=inventory.source_revision,
        inventory_digest=inventory.digest,
        scan_input_sha256=inventory.scan_input_sha256,
        inventory_surface_count=len(inventory.surfaces),
        classifications=rows,
        missing_surfaces=missing,
    )


def parse_inventory_v2(value: Mapping[str, object]) -> RepositoryWriteInventoryV2:
    required = {
        "schema",
        "source_revision",
        "package_root",
        "scan_input_sha256",
        "files_scanned",
        "components",
        "surfaces",
        "surface_count",
        "blocker_count",
        "closed",
        "canonical_scanner_integrated",
        "inventory_generation",
        "scope",
        "inventory_only",
        "primary_checkout_target_proven",
        "blockers",
        "digest",
    }
    _require_exact_keys(value, required, "inventory v2")
    if value["schema"] != "daedalus-gate0-repository-write-inventory/2":
        raise RepositoryWriteClassificationError("inventory schema is unsupported")
    components = _strict_mapping(value["components"], "inventory components")
    _require_exact_keys(
        components,
        {"base_inventory_digest", "stdlib_delta_digest"},
        "inventory components",
    )
    surfaces_raw = _strict_list(value["surfaces"], "inventory surfaces")
    try:
        inventory = RepositoryWriteInventoryV2(
            source_revision=_strict_str(value["source_revision"], "source_revision"),
            package_root=_strict_str(value["package_root"], "package_root"),
            scan_input_sha256=_strict_str(
                value["scan_input_sha256"], "scan_input_sha256"
            ),
            files_scanned=_strict_int(value["files_scanned"], "files_scanned"),
            base_inventory_digest=_strict_str(
                components["base_inventory_digest"], "base_inventory_digest"
            ),
            stdlib_delta_digest=_strict_str(
                components["stdlib_delta_digest"], "stdlib_delta_digest"
            ),
            surfaces=tuple(
                _surface_from_dict(_strict_mapping(item, "inventory surface"))
                for item in surfaces_raw
            ),
        )
    except ValueError as exc:
        raise RepositoryWriteClassificationError("inventory v2 is invalid") from exc
    if inventory.to_dict() != dict(value):
        raise RepositoryWriteClassificationError(
            "inventory derived fields or digest do not match canonical material"
        )
    return inventory


def project_classification_input(
    inventory: RepositoryWriteInventoryV2,
    value: Mapping[str, object],
) -> RepositoryWriteClassificationReport:
    _require_exact_keys(
        value,
        {"schema", "source_revision", "inventory_digest", "classifications"},
        "classification input",
    )
    if value["schema"] != "daedalus-gate0-repository-write-classification-input/1":
        raise RepositoryWriteClassificationError(
            "classification input schema is unsupported"
        )
    if value["source_revision"] != inventory.source_revision:
        raise RepositoryWriteClassificationError(
            "classification input source revision is stale"
        )
    if value["inventory_digest"] != inventory.digest:
        raise RepositoryWriteClassificationError(
            "classification input inventory digest is stale"
        )
    rows = tuple(
        SurfaceClassification.from_dict(
            _strict_mapping(item, "surface classification")
        )
        for item in _strict_list(value["classifications"], "classifications")
    )
    return project_repository_write_classifications(inventory, rows)


def _surface_from_dict(value: Mapping[str, object]) -> RepositoryWriteSurface:
    _require_exact_keys(
        value,
        {
            "path",
            "line",
            "column",
            "origin",
            "kind",
            "callee",
            "operation",
            "blocking",
        },
        "repository write surface",
    )
    try:
        return RepositoryWriteSurface(
            path=_strict_str(value["path"], "surface path"),
            line=_strict_int(value["line"], "surface line"),
            column=_strict_int(value["column"], "surface column"),
            origin=_strict_str(value["origin"], "surface origin"),
            kind=_strict_str(value["kind"], "surface kind"),
            callee=_strict_str(value["callee"], "surface callee"),
            operation=_strict_str(value["operation"], "surface operation"),
            blocking=_strict_bool(value["blocking"], "surface blocking"),
        )
    except ValueError as exc:
        raise RepositoryWriteClassificationError(
            "repository write surface is invalid"
        ) from exc


def _require_exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise RepositoryWriteClassificationError(f"{label} keys are invalid")


def _strict_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RepositoryWriteClassificationError(f"{label} must be an object")
    return value


def _strict_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RepositoryWriteClassificationError(f"{label} must be an array")
    return value


def _strict_str(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RepositoryWriteClassificationError(f"{label} must be a string")
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteClassificationError(f"{label} must be an integer")
    return value


def _strict_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise RepositoryWriteClassificationError(f"{label} must be a boolean")
    return value
