"""Strict byte verification for repository-write inventory artifacts.

The verifier accepts already-resolved immutable bytes, hashes and parses them,
reconstructs the canonical inventory-v2 object, and binds it to exact artifact
evidence plus one GateReport-v3.  It does not resolve locators, authenticate a
signer, inspect Git HEAD, issue OwnerApproval, or release/promote anything.
"""
from __future__ import annotations

import hashlib
import json
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
from daedalus.spine.envelope import canonical_json, canonical_sha

from .report_v3 import GateReportV3
from .repository_write_evidence import RepositoryWriteArtifactEvidence
from .repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_ROOT_FIELDS = {
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
_SURFACE_FIELDS = {
    "path",
    "line",
    "column",
    "origin",
    "kind",
    "callee",
    "operation",
    "blocking",
}
_COMPONENT_FIELDS = {"base_inventory_digest", "stdlib_delta_digest"}
_VERIFICATION_CHECKS = (
    "artifact-content-sha256",
    "artifact-report-binding",
    "canonical-inventory-v2",
    "failure-set-binding",
    "inventory-artifact-binding",
    "strict-json-bytes",
)


class RepositoryWriteArtifactVerificationError(ValueError):
    """The artifact bytes or their retained bindings are invalid."""


def _validated_artifact_bytes(raw: object) -> bytes:
    if type(raw) is not bytes:
        raise RepositoryWriteArtifactVerificationError(
            "artifact content must be exact immutable bytes"
        )
    if not raw or len(raw) > _MAX_ARTIFACT_BYTES:
        raise RepositoryWriteArtifactVerificationError(
            "artifact content size is invalid"
        )
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteArtifactVerificationError(
                f"duplicate repository-write artifact key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RepositoryWriteArtifactVerificationError(
        f"non-finite repository-write artifact constant: {value}"
    )


def _strict_inventory_from_bytes(raw: bytes) -> RepositoryWriteInventoryV2:
    exact = _validated_artifact_bytes(raw)
    try:
        text = exact.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryWriteArtifactVerificationError(
            "artifact content must be UTF-8"
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except RepositoryWriteArtifactVerificationError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteArtifactVerificationError(
            "artifact content is malformed JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory root fields are not exact"
        )
    if payload.get("schema") != "daedalus-gate0-repository-write-inventory/2":
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory schema is unsupported"
        )
    components = payload.get("components")
    if not isinstance(components, dict) or set(components) != _COMPONENT_FIELDS:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory component fields are not exact"
        )
    surface_rows = payload.get("surfaces")
    if not isinstance(surface_rows, list):
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory surfaces must be an array"
        )
    surfaces: list[RepositoryWriteSurface] = []
    try:
        for row in surface_rows:
            if not isinstance(row, dict) or set(row) != _SURFACE_FIELDS:
                raise RepositoryWriteArtifactVerificationError(
                    "artifact inventory surface fields are not exact"
                )
            surfaces.append(RepositoryWriteSurface(**row))
        inventory = RepositoryWriteInventoryV2(
            source_revision=payload["source_revision"],
            package_root=payload["package_root"],
            scan_input_sha256=payload["scan_input_sha256"],
            files_scanned=payload["files_scanned"],
            base_inventory_digest=components["base_inventory_digest"],
            stdlib_delta_digest=components["stdlib_delta_digest"],
            surfaces=tuple(surfaces),
        )
    except RepositoryWriteArtifactVerificationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory contract is malformed"
        ) from exc
    canonical_payload = inventory.to_dict()
    if payload != canonical_payload:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory payload is non-canonical"
        )
    if exact != canonical_json(canonical_payload).encode("ascii"):
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory bytes are non-canonical"
        )
    return inventory


def _inventory_failures(
    inventory: RepositoryWriteInventoryV2,
) -> tuple[str, ...]:
    return tuple(
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        for surface in inventory.blockers
    )


@dataclass(frozen=True)
class RepositoryWriteArtifactVerificationReceipt(CanonicalContract):
    """Mechanical receipt for one exact byte/report/evidence tuple."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-artifact-verification-receipt/1"
    )

    verification_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v3_sha256: str
    artifact_evidence_sha256: str
    artifact_content_sha256: str
    inventory_sha256: str
    verified_at: str
    checks: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "verification_id",
                _identifier(self.verification_id, "verification_id"),
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
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "verified_at",
                _utc_timestamp(self.verified_at, "verified_at"),
            )
            object.__setattr__(
                self,
                "checks",
                _sorted_strings(self.checks, "checks", identifiers=True),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactVerificationError(
                "artifact verification receipt is malformed"
            ) from exc
        if self.checks != _VERIFICATION_CHECKS:
            raise RepositoryWriteArtifactVerificationError(
                "artifact verification checks are not exact"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteArtifactVerificationError(
                "receipt provenance must be an exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteArtifactVerificationError(
                "receipt source revision contradicts provenance"
            )
        if self.provenance.created_at != self.verified_at:
            raise RepositoryWriteArtifactVerificationError(
                "receipt verified_at contradicts provenance.created_at"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v3_sha256,
                    self.artifact_evidence_sha256,
                    self.artifact_content_sha256,
                    self.inventory_sha256,
                ),
                "repository-write artifact verification receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteArtifactVerificationError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteArtifactVerificationReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteArtifactVerificationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactVerificationError(
                "artifact verification receipt payload is malformed"
            ) from exc


def verify_repository_write_artifact(
    artifact: RepositoryWriteArtifactEvidence,
    report: GateReportV3,
    artifact_bytes: bytes,
    *,
    verification_id: str,
    verified_at: str,
) -> RepositoryWriteArtifactVerificationReceipt:
    """Verify exact bytes and logical bindings without resolving a locator."""

    if type(artifact) is not RepositoryWriteArtifactEvidence:
        raise RepositoryWriteArtifactVerificationError(
            "artifact must be exact RepositoryWriteArtifactEvidence"
        )
    if type(report) is not GateReportV3:
        raise RepositoryWriteArtifactVerificationError(
            "report must be exact GateReportV3"
        )
    exact_bytes = _validated_artifact_bytes(artifact_bytes)
    content_sha256 = hashlib.sha256(exact_bytes).hexdigest()
    if content_sha256 != artifact.artifact_content_sha256:
        raise RepositoryWriteArtifactVerificationError(
            "artifact byte digest contradicts artifact evidence"
        )
    report_blockers = artifact.report_binding_blockers(report)
    if report_blockers:
        raise RepositoryWriteArtifactVerificationError(
            "artifact evidence contradicts GateReport-v3: "
            + ", ".join(report_blockers)
        )
    inventory = _strict_inventory_from_bytes(exact_bytes)
    if inventory.source_revision != artifact.source_revision:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory source revision contradicts evidence"
        )
    if inventory.digest != artifact.inventory_sha256:
        raise RepositoryWriteArtifactVerificationError(
            "artifact inventory digest contradicts evidence"
        )
    if inventory.scan_input_sha256 != artifact.scan_input_sha256:
        raise RepositoryWriteArtifactVerificationError(
            "artifact scan-input digest contradicts evidence"
        )
    if inventory.files_scanned != artifact.files_scanned:
        raise RepositoryWriteArtifactVerificationError(
            "artifact file count contradicts evidence"
        )
    failures = _inventory_failures(inventory)
    if canonical_sha(list(failures)) != artifact.failure_set_sha256:
        raise RepositoryWriteArtifactVerificationError(
            "artifact failure-set digest contradicts evidence"
        )
    if len(failures) != artifact.failure_count:
        raise RepositoryWriteArtifactVerificationError(
            "artifact failure count contradicts evidence"
        )

    report_sha256 = report.to_dict()["report_sha256"]
    provenance = ContractProvenance(
        origin="gate0.repository-write-artifact-verifier",
        source_revision=artifact.source_revision,
        created_at=verified_at,
        input_digests=(
            report_sha256,
            artifact.digest,
            content_sha256,
            inventory.digest,
        ),
    )
    return RepositoryWriteArtifactVerificationReceipt(
        verification_id=verification_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v3_sha256=report_sha256,
        artifact_evidence_sha256=artifact.digest,
        artifact_content_sha256=content_sha256,
        inventory_sha256=inventory.digest,
        verified_at=verified_at,
        checks=_VERIFICATION_CHECKS,
        provenance=provenance,
    )


__all__ = [
    "RepositoryWriteArtifactVerificationError",
    "RepositoryWriteArtifactVerificationReceipt",
    "verify_repository_write_artifact",
]
