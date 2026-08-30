# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Exact repository-write artifact evidence for GateReport-v3.

This additive contract binds a content-addressed repository-write inventory
artifact to the logical inventory identity retained by one GateReport-v3.  It is
not an evidence index, signature verifier, release receipt, approval, or
promotion authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _locator_sha256,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

from .report_v3 import GateReportV3


_CONTRACT_TYPE = "daedalus-repository-write-artifact-evidence/1"


class RepositoryWriteArtifactEvidenceError(ValueError):
    """Repository-write artifact evidence is malformed or contradictory."""


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteArtifactEvidenceError(
            f"{name} must be a non-negative integer"
        )
    return value


def _positive_int(value: Any, name: str) -> int:
    result = _non_negative_int(value, name)
    if result < 1:
        raise RepositoryWriteArtifactEvidenceError(
            f"{name} must be a positive integer"
        )
    return result


@dataclass(frozen=True)
class RepositoryWriteArtifactEvidence(CanonicalContract):
    """Content and logical identity for one repository-write inventory artifact."""

    CONTRACT_TYPE: ClassVar[str] = _CONTRACT_TYPE

    artifact_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v3_sha256: str
    inventory_sha256: str
    scan_input_sha256: str
    files_scanned: int
    inventory_generation: int
    failure_set_sha256: str
    failure_count: int
    artifact_content_sha256: str
    locator: str
    built_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "artifact_id",
                _identifier(self.artifact_id, "artifact_id"),
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
                "inventory_sha256",
                "scan_input_sha256",
                "failure_set_sha256",
                "artifact_content_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "files_scanned",
                _positive_int(self.files_scanned, "files_scanned"),
            )
            generation = _positive_int(
                self.inventory_generation,
                "inventory_generation",
            )
            if generation != 2:
                raise RepositoryWriteArtifactEvidenceError(
                    "inventory_generation must be exactly 2"
                )
            object.__setattr__(self, "inventory_generation", generation)
            object.__setattr__(
                self,
                "failure_count",
                _non_negative_int(self.failure_count, "failure_count"),
            )
            object.__setattr__(
                self,
                "locator",
                _artifact_locator(self.locator, "locator"),
            )
            object.__setattr__(
                self,
                "built_at",
                _utc_timestamp(self.built_at, "built_at"),
            )
        except RepositoryWriteArtifactEvidenceError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactEvidenceError(
                "repository-write artifact evidence is malformed"
            ) from exc

        if _locator_sha256(self.locator) != self.artifact_content_sha256:
            raise RepositoryWriteArtifactEvidenceError(
                "artifact locator digest contradicts artifact content digest"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteArtifactEvidenceError(
                "provenance must be an exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteArtifactEvidenceError(
                "artifact source revision contradicts provenance"
            )
        if self.provenance.created_at != self.built_at:
            raise RepositoryWriteArtifactEvidenceError(
                "artifact built_at contradicts provenance.created_at"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v3_sha256,
                    self.inventory_sha256,
                    self.scan_input_sha256,
                    self.failure_set_sha256,
                    self.artifact_content_sha256,
                ),
                "repository-write artifact evidence",
            )
        except ValueError as exc:
            raise RepositoryWriteArtifactEvidenceError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteArtifactEvidence":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteArtifactEvidenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteArtifactEvidenceError(
                "repository-write artifact evidence payload is malformed"
            ) from exc

    def report_binding_blockers(self, report: GateReportV3) -> tuple[str, ...]:
        """Compare the artifact contract with one exact GateReport-v3."""

        if type(report) is not GateReportV3:
            raise RepositoryWriteArtifactEvidenceError(
                "report binding requires exact GateReportV3"
            )
        report_payload = report.to_dict()
        blockers: list[str] = []
        if self.source_revision != report.source_revision:
            blockers.append("repository-write-artifact:foreign-source-revision")
        if self.gate_report_v3_sha256 != report_payload["report_sha256"]:
            blockers.append("repository-write-artifact:foreign-gate-report")
        if self.inventory_sha256 != report.repository_write_inventory_sha256:
            blockers.append("repository-write-artifact:inventory-digest-mismatch")
        if self.scan_input_sha256 != report.repository_write_scan_input_sha256:
            blockers.append("repository-write-artifact:scan-input-digest-mismatch")
        if self.files_scanned != report.repository_write_files_scanned:
            blockers.append("repository-write-artifact:file-count-mismatch")
        if self.inventory_generation != report.repository_write_inventory_generation:
            blockers.append("repository-write-artifact:generation-mismatch")
        expected_failure_digest = canonical_sha(
            list(report.repository_write_failures)
        )
        if self.failure_set_sha256 != expected_failure_digest:
            blockers.append("repository-write-artifact:failure-set-digest-mismatch")
        if self.failure_count != len(report.repository_write_failures):
            blockers.append("repository-write-artifact:failure-count-mismatch")
        return tuple(sorted(set(blockers)))


__all__ = [
    "RepositoryWriteArtifactEvidence",
    "RepositoryWriteArtifactEvidenceError",
]
