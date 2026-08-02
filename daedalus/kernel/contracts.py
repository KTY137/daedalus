"""Additive trust-kernel contracts built on the canonical Gate-0 wire language.

These records inherit :class:`daedalus.schemas.CanonicalContract`; they do not
create a second serialization or digest authority. They live under ``kernel``
so the Filetree migration can proceed strangler-style without a semantic and
mechanical rewrite of the legacy schema module in the same security packet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
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


_OWNER_APPROVAL_OPERATIONS = frozenset(
    {
        "close-gate-2",
        "promote-candidate",
        "review-corpus-repository",
    }
)


@dataclass(frozen=True)
class OwnerApproval(CanonicalContract):
    """Authenticated, bounded and single-decision owner authorization.

    The operation is explicitly allowlisted. The contract remains inert until
    a verifier authenticates the signature and a replay ledger consumes its
    nonce. It never applies a candidate, closes a gate, or upgrades corpus
    review state by itself.
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
        if self.operation not in _OWNER_APPROVAL_OPERATIONS:
            raise ValueError(
                "owner approval operation must be one of "
                + repr(sorted(_OWNER_APPROVAL_OPERATIONS))
            )
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

    request_id: str
    mission_id: str
    attempt_id: str
    entrypoint: str
    requested_effects: tuple[str, ...]
    scope: EffectScope
    idempotency_namespace: str
    policy_decision_sha256: str
    registry_sha256: str
    runtime_evidence_sha256: str
    kill_switch_generation: int
    source_revision: str
    requested_at: str
    provenance: ContractProvenance

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease-request"

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "mission_id",
            "attempt_id",
            "entrypoint",
            "idempotency_namespace",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "requested_effects",
            _sorted_strings(self.requested_effects, "requested_effects"),
        )
        if not self.requested_effects:
            raise ValueError("requested_effects must not be empty")
        if not isinstance(self.scope, EffectScope):
            raise ValueError("scope must be an EffectScope")
        for name in (
            "policy_decision_sha256",
            "registry_sha256",
            "runtime_evidence_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ):
            raise ValueError("kill_switch_generation must be an integer")
        if self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be non-negative")
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self, "requested_at", _utc_timestamp(self.requested_at, "requested_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "effect lease request source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.policy_decision_sha256,
                self.registry_sha256,
                self.runtime_evidence_sha256,
            ),
            "effect lease request",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectLeaseRequest":
        body = cls._contract_payload(payload)
        body["requested_effects"] = tuple(body["requested_effects"])
        body["scope"] = EffectScope.from_dict(body["scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class EffectLease(CanonicalContract):
    """Authenticated capability authorizing one bounded effect envelope."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.effect-lease"

    lease_id: str
    issuer_id: str
    key_id: str
    request_sha256: str
    mission_id: str
    attempt_id: str
    entrypoint: str
    allowed_effects: tuple[str, ...]
    scope: EffectScope
    idempotency_namespace: str
    policy_decision_sha256: str
    registry_sha256: str
    runtime_evidence_sha256: str
    kill_switch_generation: int
    source_revision: str
    issued_at: str
    expires_at: str
    max_concurrency: int
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in (
            "lease_id",
            "issuer_id",
            "key_id",
            "mission_id",
            "attempt_id",
            "entrypoint",
            "idempotency_namespace",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "request_sha256",
            "policy_decision_sha256",
            "registry_sha256",
            "runtime_evidence_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "allowed_effects",
            _sorted_strings(self.allowed_effects, "allowed_effects"),
        )
        if not self.allowed_effects:
            raise ValueError("allowed_effects must not be empty")
        if not isinstance(self.scope, EffectScope):
            raise ValueError("scope must be an EffectScope")
        if isinstance(self.kill_switch_generation, bool) or not isinstance(
            self.kill_switch_generation, int
        ):
            raise ValueError("kill_switch_generation must be an integer")
        if self.kill_switch_generation < 0:
            raise ValueError("kill_switch_generation must be non-negative")
        if isinstance(self.max_concurrency, bool) or not isinstance(
            self.max_concurrency, int
        ):
            raise ValueError("max_concurrency must be an integer")
        if self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("effect lease expires_at must be after issued_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("effect lease source_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance,
            (
                self.request_sha256,
                self.policy_decision_sha256,
                self.registry_sha256,
                self.runtime_evidence_sha256,
            ),
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
        body["allowed_effects"] = tuple(body["allowed_effects"])
        body["scope"] = EffectScope.from_dict(body["scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)
