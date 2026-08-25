"""Strict byte verification for canonical repository-write chain results.

The verifier accepts already-resolved immutable bytes, reconstructs the exact
chain-result/1 object, and binds it to chain artifact evidence plus one exact
GateReport-v4.  It does not resolve locators, authenticate a signer, inspect
Git HEAD, issue OwnerApproval, or release/promote anything.
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

from .report_v4 import GateReportV4
from .repository_write_chain_evidence import (
    RepositoryWriteChainArtifactEvidence,
)
from .repository_write_chain_result import RepositoryWriteChainResult


_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
_VERIFICATION_CHECKS = (
    "artifact-content-sha256",
    "artifact-report-v4-binding",
    "canonical-chain-result",
    "chain-evidence-binding",
    "strict-json-bytes",
)


class RepositoryWriteChainArtifactVerificationError(ValueError):
    """The chain-result bytes or their retained bindings are invalid."""


def _validated_artifact_bytes(raw: object) -> bytes:
    if type(raw) is not bytes:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact content must be exact immutable bytes"
        )
    if not raw or len(raw) > _MAX_ARTIFACT_BYTES:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact content size is invalid"
        )
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteChainArtifactVerificationError(
                f"duplicate chain-result artifact key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RepositoryWriteChainArtifactVerificationError(
        f"non-finite chain-result artifact constant: {value}"
    )


def _strict_chain_result_from_bytes(raw: bytes) -> RepositoryWriteChainResult:
    exact = _validated_artifact_bytes(raw)
    try:
        payload = json.loads(
            exact.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact content must be UTF-8"
        ) from exc
    except RepositoryWriteChainArtifactVerificationError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact content is malformed JSON"
        ) from exc
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise RepositoryWriteChainArtifactVerificationError(
            "chain-result artifact root must be an object"
        )
    try:
        result = RepositoryWriteChainResult.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise RepositoryWriteChainArtifactVerificationError(
            "chain-result artifact contract is malformed"
        ) from exc
    canonical = canonical_json(result.to_dict()).encode("ascii")
    if exact != canonical:
        raise RepositoryWriteChainArtifactVerificationError(
            "chain-result artifact bytes are non-canonical"
        )
    return result


@dataclass(frozen=True)
class RepositoryWriteChainArtifactVerificationReceipt(CanonicalContract):
    """Mechanical receipt for one exact byte/report/evidence tuple."""

    CONTRACT_TYPE: ClassVar[str] = (
        "daedalus-repository-write-chain-artifact-verification-receipt/1"
    )

    verification_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    artifact_evidence_sha256: str
    artifact_content_sha256: str
    chain_result_sha256: str
    inventory_sha256: str
    classification_sha256: str
    stage_digest_set_sha256: str
    evidence_authenticated: bool
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
                "gate_report_v4_sha256",
                "artifact_evidence_sha256",
                "artifact_content_sha256",
                "chain_result_sha256",
                "inventory_sha256",
                "classification_sha256",
                "stage_digest_set_sha256",
            ):
                object.__setattr__(
                    self,
                    field_name,
                    _sha256(getattr(self, field_name), field_name),
                )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainArtifactVerificationError(
                    "evidence_authenticated must be a boolean"
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
        except RepositoryWriteChainArtifactVerificationError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainArtifactVerificationError(
                "chain artifact verification receipt is malformed"
            ) from exc
        if self.checks != _VERIFICATION_CHECKS:
            raise RepositoryWriteChainArtifactVerificationError(
                "chain artifact verification checks are not exact"
            )
        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainArtifactVerificationError(
                "receipt provenance must be an exact ContractProvenance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainArtifactVerificationError(
                "receipt source revision contradicts provenance"
            )
        if self.provenance.created_at != self.verified_at:
            raise RepositoryWriteChainArtifactVerificationError(
                "receipt verified_at contradicts provenance.created_at"
            )
        try:
            _require_provenance_inputs(
                self.provenance,
                (
                    self.gate_report_v4_sha256,
                    self.artifact_evidence_sha256,
                    self.artifact_content_sha256,
                    self.chain_result_sha256,
                    self.inventory_sha256,
                    self.classification_sha256,
                    self.stage_digest_set_sha256,
                ),
                "repository-write chain artifact verification receipt",
            )
        except ValueError as exc:
            raise RepositoryWriteChainArtifactVerificationError(str(exc)) from exc

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainArtifactVerificationReceipt":
        try:
            body = cls._contract_payload(payload)
            body["provenance"] = ContractProvenance.from_dict(body["provenance"])
            return cls(**body)
        except RepositoryWriteChainArtifactVerificationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryWriteChainArtifactVerificationError(
                "chain artifact verification receipt payload is malformed"
            ) from exc


def verify_repository_write_chain_artifact(
    artifact: RepositoryWriteChainArtifactEvidence,
    report: GateReportV4,
    artifact_bytes: bytes,
    *,
    verification_id: str,
    verified_at: str,
) -> RepositoryWriteChainArtifactVerificationReceipt:
    """Verify exact chain-result bytes and logical bindings."""

    if type(artifact) is not RepositoryWriteChainArtifactEvidence:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact must be exact RepositoryWriteChainArtifactEvidence"
        )
    if type(report) is not GateReportV4:
        raise RepositoryWriteChainArtifactVerificationError(
            "report must be exact GateReportV4"
        )
    exact_bytes = _validated_artifact_bytes(artifact_bytes)
    content_sha256 = hashlib.sha256(exact_bytes).hexdigest()
    if content_sha256 != artifact.artifact_content_sha256:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact byte digest contradicts artifact evidence"
        )
    blockers = artifact.report_binding_blockers(report)
    if blockers:
        raise RepositoryWriteChainArtifactVerificationError(
            "artifact evidence contradicts GateReport-v4: "
            + ", ".join(blockers)
        )
    result = _strict_chain_result_from_bytes(exact_bytes)
    stage_digest_set_sha256 = canonical_sha(dict(result.stage_digests))
    expected = {
        "source_revision": result.source_revision,
        "chain_result_sha256": result.digest,
        "inventory_sha256": result.inventory_digest,
        "classification_sha256": result.classification_digest,
        "stage_digest_set_sha256": stage_digest_set_sha256,
        "inventory_surface_count": result.inventory_surface_count,
        "classified_surface_count": len(result.surfaces),
        "missing_surface_count": result.missing_surface_count,
        "authenticated_surface_count": result.authenticated_surface_count,
        "evidence_authenticated": result.evidence_authenticated,
    }
    for field_name, expected_value in expected.items():
        if getattr(artifact, field_name) != expected_value:
            raise RepositoryWriteChainArtifactVerificationError(
                f"chain-result artifact contradicts evidence field {field_name}"
            )
    report_has_failures = bool(report.repository_write_failures)
    if result.evidence_authenticated == report_has_failures:
        raise RepositoryWriteChainArtifactVerificationError(
            "chain authentication contradicts repository-write failure state"
        )

    report_sha256 = report.to_dict()["report_sha256"]
    provenance = ContractProvenance(
        origin="gate0.repository-write-chain-artifact-verifier",
        source_revision=artifact.source_revision,
        created_at=verified_at,
        input_digests=(
            report_sha256,
            artifact.digest,
            content_sha256,
            result.digest,
            result.inventory_digest,
            result.classification_digest,
            stage_digest_set_sha256,
        ),
    )
    return RepositoryWriteChainArtifactVerificationReceipt(
        verification_id=verification_id,
        source_revision=artifact.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v4_sha256=report_sha256,
        artifact_evidence_sha256=artifact.digest,
        artifact_content_sha256=content_sha256,
        chain_result_sha256=result.digest,
        inventory_sha256=result.inventory_digest,
        classification_sha256=result.classification_digest,
        stage_digest_set_sha256=stage_digest_set_sha256,
        evidence_authenticated=result.evidence_authenticated,
        verified_at=verified_at,
        checks=_VERIFICATION_CHECKS,
        provenance=provenance,
    )


__all__ = [
    "RepositoryWriteChainArtifactVerificationError",
    "RepositoryWriteChainArtifactVerificationReceipt",
    "verify_repository_write_chain_artifact",
]
