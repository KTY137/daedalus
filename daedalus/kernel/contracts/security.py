"""Additive trust-kernel contracts built on the canonical Gate-0 wire language.

These records inherit :class:`daedalus.schemas.CanonicalContract`; they do not
create a second serialization or digest authority. They live under ``kernel``
so the Filetree migration can proceed strangler-style without a semantic and
mechanical rewrite of the legacy schema module in the same security packet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Mapping, Protocol, runtime_checkable

from daedalus.kernel.contracts.canonical import (
    CanonicalContract,
    ContractProvenance,
    EffectScope,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha


class RuntimeTrustPortError(RuntimeError):
    """Neutral failure domain for injected runtime-trust authorities."""


@runtime_checkable
class RuntimeTrustRecordPort(Protocol):
    """Authenticated runtime-trust record fields consumed by the kernel."""

    runtime_id: str
    envelope_sha256: str
    conformance_receipt_sha256: str
    runtime_manifest_sha256: str
    source_revision: str
    expires_at: str
    record_sha256: str


@runtime_checkable
class RuntimeTrustLedgerPort(Protocol):
    """Read-only active-trust lookup required by runtime effect admission."""

    def require_active(
        self,
        *,
        runtime_id: str,
        envelope_sha256: str,
        runtime_manifest_sha256: str,
        conformance_receipt_sha256: str,
        source_revision: str,
        now: datetime,
    ) -> RuntimeTrustRecordPort: ...


@dataclass(frozen=True)
class OwnerApproval(CanonicalContract):
    """Authenticated, bounded and single-candidate owner authorization.

    The contract remains inert until a verifier authenticates the signature
    and a replay ledger consumes its nonce. It never applies a candidate.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.owner-approval"

    approval_id: str
    owner_id: str
    key_id: str
    operation: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    target_ref: str
    expected_target_revision: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("approval_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != "promote-candidate":
            raise ValueError("owner approval operation must be promote-candidate")
        for name in (
            "nomination_receipt_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "base_revision", _revision(self.base_revision, "base_revision")
        )
        object.__setattr__(
            self,
            "expected_target_revision",
            _revision(self.expected_target_revision, "expected_target_revision"),
        )
        object.__setattr__(self, "target_ref", _identifier(self.target_ref, "target_ref"))
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("owner approval expires_at must be after issued_at")
        if self.provenance.source_revision != self.base_revision:
            raise ValueError(
                "owner approval base_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.nomination_receipt_sha256,
                self.candidate_artifact_sha256,
                self.evidence_packet_sha256,
            ),
            "owner approval",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OwnerApproval":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectLeaseRequest(CanonicalContract):
    """The exact effect scope submitted to the policy authority.

    A policy decision must bind this request's digest and identifier.  The
    request grants nothing by itself and is safe to persist or inspect.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease-request"

    request_id: str
    mission_id: str
    attempt_id: str
    entrypoint_id: str
    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    idempotency_namespace: str
    kill_switch_generation: int
    runtime_manifest_sha256: str | None
    runtime_conformance_sha256: str | None
    provenance: ContractProvenance
    # Optional for generic compatibility.  A specialized non-runtime door may
    # bind one concrete operation before the lease is signed.  Omitted values
    # retain the historical wire bytes and digests.
    operation_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "mission_id",
            "attempt_id",
            "entrypoint_id",
            "idempotency_namespace",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("effect lease request must name at least one effect")
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        for name in ("runtime_manifest_sha256", "runtime_conformance_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        if (self.runtime_manifest_sha256 is None) != (
            self.runtime_conformance_sha256 is None
        ):
            raise ValueError(
                "runtime manifest and conformance digests must be supplied together"
            )
        if self.operation_sha256 is not None:
            object.__setattr__(
                self,
                "operation_sha256",
                _sha256(self.operation_sha256, "operation_sha256"),
            )
        if not self.effect_scope.has_effects:
            raise ValueError("effect lease request must carry a bounded effect scope")
        if not self.effect_scope.kill_switch_ref:
            raise ValueError("effect lease request requires a kill_switch_ref")
        required = []
        if self.runtime_manifest_sha256 is not None:
            required.extend(
                [self.runtime_manifest_sha256, self.runtime_conformance_sha256]
            )
        if self.operation_sha256 is not None:
            required.append(self.operation_sha256)
        _require_provenance_inputs(
            self.provenance,
            tuple(value for value in required if value is not None),
            "effect lease request",
        )

    def to_dict(self) -> dict[str, Any]:
        body = super().to_dict()
        if self.operation_sha256 is None:
            body.pop("operation_sha256")
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLeaseRequest":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectLease(CanonicalContract):
    """Authenticated, persisted and expiring authorization for one scope.

    The lease is inert until :class:`daedalus.kernel.effects.EffectLeaseLedger`
    validates and records an execution start.  It never performs the effect.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease"

    lease_id: str
    request_id: str
    request_sha256: str
    policy_decision_id: str
    policy_decision_sha256: str
    registry_sha256: str
    entrypoint_id: str
    requested_effects: tuple[str, ...]
    effect_scope: EffectScope
    idempotency_namespace: str
    kill_switch_generation: int
    runtime_id: str
    runtime_manifest_sha256: str | None
    runtime_conformance_sha256: str | None
    issuer_key_id: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "lease_id",
            "request_id",
            "policy_decision_id",
            "entrypoint_id",
            "idempotency_namespace",
            "issuer_key_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.runtime_id:
            object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        for name in (
            "request_sha256",
            "policy_decision_sha256",
            "registry_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects", identifiers=True),
        )
        if not self.requested_effects:
            raise ValueError("effect lease must name at least one effect")
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ) or self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be a non-negative integer")
        for name in ("runtime_manifest_sha256", "runtime_conformance_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        if (self.runtime_manifest_sha256 is None) != (
            self.runtime_conformance_sha256 is None
        ):
            raise ValueError(
                "runtime manifest and conformance digests must be supplied together"
            )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("effect lease expires_at must be after issued_at")
        required = [self.request_sha256, self.policy_decision_sha256, self.registry_sha256]
        if self.runtime_manifest_sha256 is not None:
            required.extend(
                [self.runtime_manifest_sha256, self.runtime_conformance_sha256]
            )
        _require_provenance_inputs(
            self.provenance,
            tuple(value for value in required if value is not None),
            "effect lease",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLease":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)
