"""Externally authenticated replay attestation for repository-write chain results.

Canonical chain bytes and artifact verification prove content identity, not that
the six repository-write verifiers ran.  This module lets a separately
controlled collector rerun the canonical builder from raw authentication
inputs, compare the replay with the admitted chain result, and sign the exact
result/artifact/report/toolchain identity.

The attestation is evidence only.  It grants no effect authority, OwnerApproval,
release, promotion, merge, or Gate transition.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Iterable, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

from .report_v4 import GateReportV4
from .repository_write_chain_artifact_verifier import (
    RepositoryWriteChainArtifactVerificationReceipt,
    verify_repository_write_chain_artifact,
)
from .repository_write_chain_evidence import RepositoryWriteChainArtifactEvidence
from .repository_write_chain_result import (
    RepositoryWriteChainResult,
    build_repository_write_chain_result,
)
from .repository_write_classification import (
    NonRuntimeConformityBinding,
    RepositoryWriteAuthenticationInputs,
    RepositoryWriteClassificationReport,
)

_ATTESTATION_SCHEMA = (
    "daedalus-repository-write-chain-collector-replay-attestation/1"
)
_ATTESTATION_ORIGIN = "gate0.repository-write-chain-collector-replay"
_BUILDER_ID = "gate0.repository-write-chain-result-builder/1"
_MAX_ATTESTATION_TTL = timedelta(hours=24)


class RepositoryWriteChainCollectorAttestationError(RuntimeError):
    """Base error for collector replay attestation."""


class RepositoryWriteChainCollectorSignatureError(
    RepositoryWriteChainCollectorAttestationError
):
    """The collector identity or signature cannot be authenticated."""


class RepositoryWriteChainCollectorBindingError(
    RepositoryWriteChainCollectorAttestationError
):
    """The attestation, replay, or retained artifact identities disagree."""


def _non_negative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteChainCollectorBindingError(
            f"{name} must be a non-negative integer"
        )
    return value


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepositoryWriteChainCollectorBindingError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryWriteChainCollectorBindingError(
            f"{label} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RepositoryWriteChainCollectorBindingError(
            f"{label} must be a datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise RepositoryWriteChainCollectorBindingError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif type(secret) is bytes:
        value = secret
    else:
        raise RepositoryWriteChainCollectorSignatureError(
            "collector secret must be bytes or text"
        )
    if len(value) < 32:
        raise RepositoryWriteChainCollectorSignatureError(
            "collector secret must contain at least 32 bytes"
        )
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _stage_digest_set_sha256(result: RepositoryWriteChainResult) -> str:
    return canonical_sha(dict(result.stage_digests))


@dataclass(frozen=True)
class RepositoryWriteChainCollectorAttestation(CanonicalContract):
    """A signed claim that an external collector reproduced one exact chain."""

    CONTRACT_TYPE: ClassVar[str] = _ATTESTATION_SCHEMA

    attestation_id: str
    collector_id: str
    collector_key_id: str
    builder_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_v4_sha256: str
    artifact_evidence_sha256: str
    artifact_verification_sha256: str
    artifact_content_sha256: str
    chain_result_sha256: str
    inventory_sha256: str
    classification_sha256: str
    stage_digest_set_sha256: str
    collector_toolchain_sha256: str
    inventory_surface_count: int
    classified_surface_count: int
    missing_surface_count: int
    authenticated_surface_count: int
    evidence_authenticated: bool
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "attestation_id",
                "collector_id",
                "collector_key_id",
                "builder_id",
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
                "artifact_verification_sha256",
                "artifact_content_sha256",
                "chain_result_sha256",
                "inventory_sha256",
                "classification_sha256",
                "stage_digest_set_sha256",
                "collector_toolchain_sha256",
                "signature_sha256",
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
                    _non_negative_int(getattr(self, field_name), field_name),
                )
            if type(self.evidence_authenticated) is not bool:
                raise RepositoryWriteChainCollectorBindingError(
                    "evidence_authenticated must be a boolean"
                )
            object.__setattr__(
                self,
                "issued_at",
                _utc_timestamp(self.issued_at, "issued_at"),
            )
            object.__setattr__(
                self,
                "expires_at",
                _utc_timestamp(self.expires_at, "expires_at"),
            )
        except RepositoryWriteChainCollectorAttestationError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise RepositoryWriteChainCollectorBindingError(
                "collector replay attestation is malformed"
            ) from exc

        if self.builder_id != _BUILDER_ID:
            raise RepositoryWriteChainCollectorBindingError(
                "collector attestation builder_id is unsupported"
            )
        if (
            self.classified_surface_count + self.missing_surface_count
            != self.inventory_surface_count
        ):
            raise RepositoryWriteChainCollectorBindingError(
                "attestation surface counts do not cover the inventory"
            )
        if self.authenticated_surface_count > self.classified_surface_count:
            raise RepositoryWriteChainCollectorBindingError(
                "authenticated surface count exceeds classified count"
            )
        derived_authenticated = (
            self.classified_surface_count > 0
            and self.missing_surface_count == 0
            and self.authenticated_surface_count
            == self.classified_surface_count
        )
        if self.evidence_authenticated != derived_authenticated:
            raise RepositoryWriteChainCollectorBindingError(
                "evidence_authenticated is not derived from retained counts"
            )

        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation expires_at must follow issued_at"
            )
        if expires - issued > _MAX_ATTESTATION_TTL:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation lifetime must not exceed 24 hours"
            )

        if type(self.provenance) is not ContractProvenance:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation provenance must be exact ContractProvenance"
            )
        if self.provenance.origin != _ATTESTATION_ORIGIN:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation provenance origin is invalid"
            )
        if self.provenance.source_revision != self.source_revision:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation source revision contradicts provenance"
            )
        if self.provenance.created_at != self.issued_at:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation issued_at contradicts provenance.created_at"
            )
        if self.provenance.trace_id != self.attestation_id:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation trace_id must equal attestation_id"
            )
        if self.provenance.input_digests != self.input_digests:
            raise RepositoryWriteChainCollectorBindingError(
                "attestation provenance must bind exactly all replay inputs"
            )

    @property
    def input_digests(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.gate_report_v4_sha256,
                    self.artifact_evidence_sha256,
                    self.artifact_verification_sha256,
                    self.artifact_content_sha256,
                    self.chain_result_sha256,
                    self.inventory_sha256,
                    self.classification_sha256,
                    self.stage_digest_set_sha256,
                    self.collector_toolchain_sha256,
                }
            )
        )

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "RepositoryWriteChainCollectorAttestation":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise RepositoryWriteChainCollectorBindingError(
                "attestation provenance must be an object"
            )
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


def _verify_replay_bindings(
    result: RepositoryWriteChainResult,
    artifact: RepositoryWriteChainArtifactEvidence,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
) -> None:
    if type(result) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainCollectorBindingError(
            "retained result must be exact RepositoryWriteChainResult"
        )
    if type(artifact) is not RepositoryWriteChainArtifactEvidence:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact must be exact RepositoryWriteChainArtifactEvidence"
        )
    if type(verification) is not RepositoryWriteChainArtifactVerificationReceipt:
        raise RepositoryWriteChainCollectorBindingError(
            "verification must be exact chain artifact verification receipt"
        )

    stage_set = _stage_digest_set_sha256(result)
    expected_artifact = {
        "source_revision": result.source_revision,
        "chain_result_sha256": result.digest,
        "inventory_sha256": result.inventory_digest,
        "classification_sha256": result.classification_digest,
        "stage_digest_set_sha256": stage_set,
        "inventory_surface_count": result.inventory_surface_count,
        "classified_surface_count": len(result.surfaces),
        "missing_surface_count": result.missing_surface_count,
        "authenticated_surface_count": result.authenticated_surface_count,
        "evidence_authenticated": result.evidence_authenticated,
    }
    mismatches = sorted(
        name
        for name, expected in expected_artifact.items()
        if getattr(artifact, name) != expected
    )
    if mismatches:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact evidence differs from replayed chain: "
            + ", ".join(mismatches)
        )

    expected_verification = {
        "source_revision": result.source_revision,
        "source_tree_revision": artifact.source_tree_revision,
        "gate_report_v4_sha256": artifact.gate_report_v4_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": result.digest,
        "inventory_sha256": result.inventory_digest,
        "classification_sha256": result.classification_digest,
        "stage_digest_set_sha256": stage_set,
        "evidence_authenticated": result.evidence_authenticated,
    }
    verification_mismatches = sorted(
        name
        for name, expected in expected_verification.items()
        if getattr(verification, name) != expected
    )
    if verification_mismatches:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact verification differs from replayed chain: "
            + ", ".join(verification_mismatches)
        )


def issue_repository_write_chain_collector_attestation(
    projection: RepositoryWriteClassificationReport,
    *,
    inputs: RepositoryWriteAuthenticationInputs,
    retained_result: RepositoryWriteChainResult,
    artifact: RepositoryWriteChainArtifactEvidence,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
    report: GateReportV4,
    artifact_bytes: bytes,
    non_runtime_bindings: Iterable[NonRuntimeConformityBinding] = (),
    non_runtime_collector_secrets: Mapping[str, bytes | str] | None = None,
    attestation_id: str,
    collector_id: str,
    collector_key_id: str,
    collector_secret: bytes | str,
    collector_toolchain_sha256: str,
    issued_at: datetime,
    expires_at: datetime,
) -> RepositoryWriteChainCollectorAttestation:
    """Rerun all six verifiers, require exact equality, and sign the replay."""

    if type(projection) is not RepositoryWriteClassificationReport:
        raise RepositoryWriteChainCollectorBindingError(
            "projection must be exact RepositoryWriteClassificationReport"
        )
    if type(inputs) is not RepositoryWriteAuthenticationInputs:
        raise RepositoryWriteChainCollectorBindingError(
            "inputs must be exact RepositoryWriteAuthenticationInputs"
        )
    if type(report) is not GateReportV4:
        raise RepositoryWriteChainCollectorBindingError(
            "report must be exact GateReportV4"
        )
    if type(verification) is not RepositoryWriteChainArtifactVerificationReceipt:
        raise RepositoryWriteChainCollectorBindingError(
            "verification must be exact chain artifact verification receipt"
        )
    try:
        replayed_verification = verify_repository_write_chain_artifact(
            artifact,
            report,
            artifact_bytes,
            verification_id=verification.verification_id,
            verified_at=verification.verified_at,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteChainCollectorBindingError(
            "collector could not reproduce artifact verification"
        ) from exc
    if replayed_verification.to_dict() != verification.to_dict():
        raise RepositoryWriteChainCollectorBindingError(
            "retained artifact verification differs from collector replay"
        )

    bindings = tuple(non_runtime_bindings)
    secrets = dict(non_runtime_collector_secrets or {})
    try:
        replayed = build_repository_write_chain_result(
            projection,
            inputs=inputs,
            non_runtime_bindings=bindings,
            collector_secrets=secrets,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteChainCollectorBindingError(
            "collector could not reproduce the verifier chain"
        ) from exc
    if type(replayed) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainCollectorBindingError(
            "collector builder returned a non-exact chain result"
        )
    if type(retained_result) is not RepositoryWriteChainResult:
        raise RepositoryWriteChainCollectorBindingError(
            "retained result must be exact RepositoryWriteChainResult"
        )
    if replayed.to_dict() != retained_result.to_dict():
        raise RepositoryWriteChainCollectorBindingError(
            "retained chain result differs from collector replay"
        )
    _verify_replay_bindings(replayed, artifact, verification)

    instant = _as_utc(issued_at, "issued_at")
    expiry = _as_utc(expires_at, "expires_at")
    artifact_time = _parse_utc(artifact.built_at, "artifact.built_at")
    verification_time = _parse_utc(
        verification.verified_at,
        "verification.verified_at",
    )
    if verification_time < artifact_time:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact verification predates artifact construction"
        )
    latest_input = max(artifact_time, verification_time)
    if instant < latest_input:
        raise RepositoryWriteChainCollectorBindingError(
            "attestation issuance predates retained verification evidence"
        )
    if expiry <= instant:
        raise RepositoryWriteChainCollectorBindingError(
            "attestation expires_at must follow issued_at"
        )
    if expiry - instant > _MAX_ATTESTATION_TTL:
        raise RepositoryWriteChainCollectorBindingError(
            "attestation lifetime must not exceed 24 hours"
        )

    stage_set = _stage_digest_set_sha256(replayed)
    toolchain = _sha256(
        collector_toolchain_sha256,
        "collector_toolchain_sha256",
    )
    issued_text = instant.isoformat(timespec="microseconds")
    expires_text = expiry.isoformat(timespec="microseconds")
    input_digests = tuple(
        sorted(
            {
                artifact.gate_report_v4_sha256,
                artifact.digest,
                verification.digest,
                artifact.artifact_content_sha256,
                replayed.digest,
                replayed.inventory_digest,
                replayed.classification_digest,
                stage_set,
                toolchain,
            }
        )
    )
    placeholder = RepositoryWriteChainCollectorAttestation(
        attestation_id=attestation_id,
        collector_id=collector_id,
        collector_key_id=collector_key_id,
        builder_id=_BUILDER_ID,
        source_revision=replayed.source_revision,
        source_tree_revision=artifact.source_tree_revision,
        gate_report_v4_sha256=artifact.gate_report_v4_sha256,
        artifact_evidence_sha256=artifact.digest,
        artifact_verification_sha256=verification.digest,
        artifact_content_sha256=artifact.artifact_content_sha256,
        chain_result_sha256=replayed.digest,
        inventory_sha256=replayed.inventory_digest,
        classification_sha256=replayed.classification_digest,
        stage_digest_set_sha256=stage_set,
        collector_toolchain_sha256=toolchain,
        inventory_surface_count=replayed.inventory_surface_count,
        classified_surface_count=len(replayed.surfaces),
        missing_surface_count=replayed.missing_surface_count,
        authenticated_surface_count=replayed.authenticated_surface_count,
        evidence_authenticated=replayed.evidence_authenticated,
        issued_at=issued_text,
        expires_at=expires_text,
        signature_sha256="0" * 64,
        provenance=ContractProvenance(
            origin=_ATTESTATION_ORIGIN,
            source_revision=replayed.source_revision,
            created_at=issued_text,
            input_digests=input_digests,
            trace_id=attestation_id,
        ),
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            collector_secret,
        ),
    )


def verify_repository_write_chain_collector_attestation(
    attestation: RepositoryWriteChainCollectorAttestation,
    artifact: RepositoryWriteChainArtifactEvidence,
    verification: RepositoryWriteChainArtifactVerificationReceipt,
    retained_result: RepositoryWriteChainResult,
    report: GateReportV4,
    artifact_bytes: bytes,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_collector_toolchain_sha256: str,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> None:
    """Authenticate one replay attestation and recheck every retained binding."""

    if type(attestation) is not RepositoryWriteChainCollectorAttestation:
        raise RepositoryWriteChainCollectorBindingError(
            "attestation must be exact collector replay attestation"
        )
    if not isinstance(keyring, Mapping):
        raise RepositoryWriteChainCollectorSignatureError(
            "collector keyring must be a mapping"
        )
    secret = keyring.get((attestation.collector_id, attestation.collector_key_id))
    if secret is None:
        raise RepositoryWriteChainCollectorSignatureError(
            "collector key is unknown"
        )
    expected_signature = _signature(attestation.signing_digest, secret)
    if not hmac.compare_digest(
        attestation.signature_sha256,
        expected_signature,
    ):
        raise RepositoryWriteChainCollectorSignatureError(
            "collector signature mismatch"
        )

    instant = _as_utc(now, "now")
    issued = _parse_utc(attestation.issued_at, "attestation.issued_at")
    expires = _parse_utc(attestation.expires_at, "attestation.expires_at")
    if issued > instant:
        raise RepositoryWriteChainCollectorBindingError(
            "collector attestation is from the future"
        )
    if instant >= expires:
        raise RepositoryWriteChainCollectorBindingError(
            "collector attestation is expired"
        )

    if type(report) is not GateReportV4:
        raise RepositoryWriteChainCollectorBindingError(
            "report must be exact GateReportV4"
        )
    try:
        replayed_verification = verify_repository_write_chain_artifact(
            artifact,
            report,
            artifact_bytes,
            verification_id=verification.verification_id,
            verified_at=verification.verified_at,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact verification could not be reproduced"
        ) from exc
    if replayed_verification.to_dict() != verification.to_dict():
        raise RepositoryWriteChainCollectorBindingError(
            "retained artifact verification differs from verifier replay"
        )

    _verify_replay_bindings(retained_result, artifact, verification)
    current = _revision(current_revision, "current_revision")
    current_tree = _revision(
        current_tree_revision,
        "current_tree_revision",
    )
    subject_mismatches: list[str] = []
    if retained_result.source_revision != current:
        subject_mismatches.append("retained_result.source_revision")
    if artifact.source_revision != current:
        subject_mismatches.append("artifact.source_revision")
    if verification.source_revision != current:
        subject_mismatches.append("verification.source_revision")
    if report.source_revision != current:
        subject_mismatches.append("report.source_revision")
    if artifact.source_tree_revision != current_tree:
        subject_mismatches.append("artifact.source_tree_revision")
    if verification.source_tree_revision != current_tree:
        subject_mismatches.append("verification.source_tree_revision")
    if subject_mismatches:
        raise RepositoryWriteChainCollectorBindingError(
            "collector attestation retained subject mismatch: "
            + ", ".join(subject_mismatches)
        )

    stage_set = _stage_digest_set_sha256(retained_result)
    expected = {
        "collector_id": _identifier(
            expected_collector_id,
            "expected_collector_id",
        ),
        "builder_id": _BUILDER_ID,
        "source_revision": current,
        "source_tree_revision": current_tree,
        "gate_report_v4_sha256": artifact.gate_report_v4_sha256,
        "artifact_evidence_sha256": artifact.digest,
        "artifact_verification_sha256": verification.digest,
        "artifact_content_sha256": artifact.artifact_content_sha256,
        "chain_result_sha256": retained_result.digest,
        "inventory_sha256": retained_result.inventory_digest,
        "classification_sha256": retained_result.classification_digest,
        "stage_digest_set_sha256": stage_set,
        "collector_toolchain_sha256": _sha256(
            expected_collector_toolchain_sha256,
            "expected_collector_toolchain_sha256",
        ),
        "inventory_surface_count": retained_result.inventory_surface_count,
        "classified_surface_count": len(retained_result.surfaces),
        "missing_surface_count": retained_result.missing_surface_count,
        "authenticated_surface_count": (
            retained_result.authenticated_surface_count
        ),
        "evidence_authenticated": retained_result.evidence_authenticated,
    }
    mismatches = sorted(
        name
        for name, expected_value in expected.items()
        if getattr(attestation, name) != expected_value
    )
    if mismatches:
        raise RepositoryWriteChainCollectorBindingError(
            "collector attestation binding mismatch: " + ", ".join(mismatches)
        )
    artifact_time = _parse_utc(artifact.built_at, "artifact.built_at")
    verification_time = _parse_utc(
        verification.verified_at,
        "verification.verified_at",
    )
    if verification_time < artifact_time:
        raise RepositoryWriteChainCollectorBindingError(
            "artifact verification predates artifact construction"
        )
    latest_input = max(artifact_time, verification_time)
    if issued < latest_input:
        raise RepositoryWriteChainCollectorBindingError(
            "collector attestation predates retained verification evidence"
        )


__all__ = [
    "RepositoryWriteChainCollectorAttestation",
    "RepositoryWriteChainCollectorAttestationError",
    "RepositoryWriteChainCollectorBindingError",
    "RepositoryWriteChainCollectorSignatureError",
    "issue_repository_write_chain_collector_attestation",
    "verify_repository_write_chain_collector_attestation",
]
