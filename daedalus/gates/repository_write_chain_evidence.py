"""Exact artifact evidence for one retained repository-write verifier chain.

The contract binds canonical chain-result bytes to their logical chain identity
and one exact GateReport-v4. ``artifact_content_sha256`` names the immutable
blob bytes. ``locator`` names the canonical ArtifactStore locator manifest and
therefore has an independent SHA-256 identity. This module does not resolve the
locator, verify artifact bytes, authenticate a signer, issue OwnerApproval, or
authorize release.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _non_empty,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)

from .report_v4 import GateReportV4
from .repository_write_chain_result import CHAIN_RESULT_SCHEMA
from .repository_write_classification import CLASSIFICATION_SCHEMA


_CONTRACT_TYPE = "daedalus-repository-write-chain-artifact-evidence/1"


class RepositoryWriteChainArtifactEvidenceError(ValueError):
    """The chain-result artifact evidence is malformed or contradictory."""


def _non_negative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteChainArtifactEvidenceError(
            f"{name} must be a non-negative integer"
        )
    return value


@dataclass(frozen=True)
class RepositoryWriteChainArtifactEvidence(CanonicalContract):
    """Content and logical identity for one canonical chain-result artifact.

    Blob identity and locator-manifest identity are deliberately distinct.  A
    caller must not infer the blob digest from the locator digest or vice versa;
    the store-resolution boundary verifies the relationship mechanically.
    """

    CONTRACT_TYPE: ClassVar[str] = _CONTRACT_TYPE

    artifact_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    chain_result_schema: str
    chain_result_sha256: str
    classification_schema: str
    inventory_sha256: str
    classification_sha256: str
    stage_digest_set_sha256: str
    inventory_surface_count: int
    classified_surface_count: int
    missing_surface_count: int
    authenticated_surface_count: int
    evidence_authenticated: bool
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
                "gate_report_v4_sha256",
                "chain_result_sha256",
                "inventory_sha256",
                "classification_sha256",
                "stage_digest_set_sha256",
                "artifact_content_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            object.__setattr__(
                self,
                "chain_result_schema",
                _non_empty(
                    self.chain_result_schema,
                    "chain_result_schema",
                    max_length=200,
                ),
            )
            object.__setattr__(
                self,
                "classification_schema",
                _non_empty(
                    self.classification_schema,
                    "classification_schema",
                    max_length=200,
                ),
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
                    _non_negative_int(getattr(self, field_name), field_name),
                )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainArtifactEvidenceError(
                    "evidence_authenticated must be a boolean"
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
        except RepositoryWriteChainArtifactEvidenceError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainArtifactEvidenceError(
                "repository-write chain artifact evidence is malformed"
            ) from exc

        if self.chain_result_schema != CHAIN_RESULT_SCHEMA:
            raise RepositoryWriteChainArtifactEvidenceError(
                "chain_result_schema is unsupported"
            )
        if self.classification_schema != CLASSIFICATION_SCHEMA:
            raise RepositoryWriteChainArtifactEvidenceError(
                "classification_schema is unsupported"
            )
        if (
            self.classified_surface_count + self.missing_surface_count
            != self.inventory_surface_count
        ):
            raise RepositoryWriteChainArtifactEvidenceError(
                "surface counts do not cover the inventory"
            )
        if self.authenticated_surface_count > self.classified_surface_count:
            raise RepositoryWriteChainArtifactEvidenceError(
                "authenticated surface count exceeds classified count"
            )
        derived_authenticated = (
            self.classified_surface_count > 0
            and self.missing_surface_count == 0
            and self.authenticated_surface_count
            == self.classified_surface_count
        )
        if self.evidence_authenticated != derived_authenticated:
            raise RepositoryWriteChainArtifactEvidenceError(
                "evidence_authenticated is not derived from retained counts"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainArtifactEvidenceError(
                "provenance must be an exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainArtifactEvidenceError(
                "artifact source revision contradicts provenance"
            )
        if self.provenance.created_at != self.built_at:
            raise RepositoryWriteChainArtifactEvidenceError(
                "artifact built_at contradicts provenance.created_at"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.chain_result_sha256,
                    self.inventory_sha256,
                    self.classification_sha256,
                    self.stage_digest_set_sha256,
                    self.artifact_content_sha256,
                ),
                "repository-write chain artifact evidence",
            )
        except ValueError as exc:
            raise RepositoryWriteChainArtifactEvidenceError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainArtifactEvidence":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainArtifactEvidenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainArtifactEvidenceError(
                "repository-write chain artifact evidence payload is malformed"
            ) from exc

    def report_binding_blockers(self, report: GateReportV4) -> tuple[str, ...]:
        """Compare this artifact identity with one exact GateReport-v4."""

        if type(report) is not GateReportV4:
            raise RepositoryWriteChainArtifactEvidenceError(
                "report binding requires exact GateReportV4"
            )
        payload = report.to_dict()
        blockers: list[str] = []
        if self.source_revision != report.source_revision:
            blockers.append("repository-write-chain-artifact:foreign-source-revision")
        if self.gate_report_v4_sha256 != payload["report_sha256"]:
            blockers.append("repository-write-chain-artifact:foreign-gate-report")
        if self.chain_result_schema != report.repository_write_chain_result_schema:
            blockers.append("repository-write-chain-artifact:chain-schema-mismatch")
        if self.chain_result_sha256 != report.repository_write_chain_result_sha256:
            blockers.append("repository-write-chain-artifact:chain-digest-mismatch")
        if self.classification_schema != report.repository_write_classification_schema:
            blockers.append(
                "repository-write-chain-artifact:classification-schema-mismatch"
            )
        if self.inventory_sha256 != report.repository_write_inventory_sha256:
            blockers.append("repository-write-chain-artifact:inventory-digest-mismatch")
        if self.inventory_surface_count != report.repository_write_surfaces_total:
            blockers.append("repository-write-chain-artifact:surface-count-mismatch")
        return tuple(sorted(set(blockers)))


__all__ = [
    "RepositoryWriteChainArtifactEvidence",
    "RepositoryWriteChainArtifactEvidenceError",
]
