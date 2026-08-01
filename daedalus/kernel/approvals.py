"""Evidence-bound, single-use owner approval contracts.

These records never create an approval automatically. They only make the
required bindings explicit and provide a fail-closed verifier for a separately
supplied human-owner decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, Collection, Mapping, Any

from daedalus.schemas import CanonicalContract, ContractProvenance

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_ALLOWED_OPERATIONS = frozenset({"promote-candidate"})


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256 digest")
    return value


def _revision(value: str, name: str) -> str:
    if not isinstance(value, str) or not _REVISION_RE.fullmatch(value):
        raise ValueError(f"{name} must be an exact lowercase git commit SHA")
    return value


def _timestamp(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _contract_body(cls: type, payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("contract_type") != cls.CONTRACT_TYPE:
        raise ValueError(f"contract_type must be {cls.CONTRACT_TYPE}")
    if payload.get("contract_version") != cls.CONTRACT_VERSION:
        raise ValueError("unsupported contract version")
    body = dict(payload)
    body.pop("contract_type", None)
    body.pop("contract_version", None)
    return body


@dataclass(frozen=True)
class NominationReceipt(CanonicalContract):
    """Records that a candidate is eligible for human consideration."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.nomination-receipt"

    nomination_id: str
    candidate_sha256: str
    evidence_packet_sha256: str
    base_head: str
    expected_target_head: str
    nominated_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "nomination_id", _identifier(self.nomination_id, "nomination_id"))
        object.__setattr__(self, "candidate_sha256", _sha256(self.candidate_sha256, "candidate_sha256"))
        object.__setattr__(self, "evidence_packet_sha256", _sha256(self.evidence_packet_sha256, "evidence_packet_sha256"))
        object.__setattr__(self, "base_head", _revision(self.base_head, "base_head"))
        object.__setattr__(self, "expected_target_head", _revision(self.expected_target_head, "expected_target_head"))
        object.__setattr__(self, "nominated_at", _timestamp(self.nominated_at, "nominated_at"))
        required = {self.candidate_sha256, self.evidence_packet_sha256}
        if not required.issubset(set(self.provenance.input_digests)):
            raise ValueError("nomination provenance must bind candidate and evidence")
        if self.provenance.source_revision != self.base_head:
            raise ValueError("nomination provenance must bind base_head")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NominationReceipt":
        body = _contract_body(cls, payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OwnerApproval(CanonicalContract):
    """A narrow, expiring, single-candidate human-owner authorization."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.owner-approval"

    approval_id: str
    owner_id: str
    nomination_sha256: str
    candidate_sha256: str
    evidence_packet_sha256: str
    base_head: str
    expected_target_head: str
    operation: str
    nonce: str
    issued_at: str
    expires_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("approval_id", "owner_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("nomination_sha256", "candidate_sha256", "evidence_packet_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(self, "base_head", _revision(self.base_head, "base_head"))
        object.__setattr__(self, "expected_target_head", _revision(self.expected_target_head, "expected_target_head"))
        if self.operation not in _ALLOWED_OPERATIONS:
            raise ValueError("approval operation is not allowed")
        object.__setattr__(self, "issued_at", _timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        if _parse_timestamp(self.expires_at) <= _parse_timestamp(self.issued_at):
            raise ValueError("approval expires_at must be after issued_at")
        required = {
            self.nomination_sha256,
            self.candidate_sha256,
            self.evidence_packet_sha256,
        }
        if not required.issubset(set(self.provenance.input_digests)):
            raise ValueError("approval provenance must bind nomination, candidate, and evidence")
        if self.provenance.source_revision != self.base_head:
            raise ValueError("approval provenance must bind base_head")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OwnerApproval":
        body = _contract_body(cls, payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class PromotionReceipt(CanonicalContract):
    """Records one completed promotion; it is not itself an authorization."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-receipt"

    promotion_id: str
    approval_sha256: str
    owner_id: str
    nonce: str
    candidate_sha256: str
    evidence_packet_sha256: str
    base_head: str
    previous_target_head: str
    resulting_target_head: str
    promoted_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("promotion_id", "owner_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("approval_sha256", "candidate_sha256", "evidence_packet_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for name in ("base_head", "previous_target_head", "resulting_target_head"):
            object.__setattr__(self, name, _revision(getattr(self, name), name))
        object.__setattr__(self, "promoted_at", _timestamp(self.promoted_at, "promoted_at"))
        if self.resulting_target_head == self.previous_target_head:
            raise ValueError("promotion receipt must record a changed target head")
        required = {self.approval_sha256, self.candidate_sha256, self.evidence_packet_sha256}
        if not required.issubset(set(self.provenance.input_digests)):
            raise ValueError("promotion provenance must bind approval, candidate, and evidence")
        if self.provenance.source_revision != self.base_head:
            raise ValueError("promotion provenance must bind base_head")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromotionReceipt":
        body = _contract_body(cls, payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def validate_owner_approval(
    approval: OwnerApproval,
    *,
    nomination: NominationReceipt,
    candidate_sha256: str,
    evidence_packet_sha256: str,
    base_head: str,
    current_target_head: str,
    now: str,
    consumed_nonces: Collection[str] = (),
) -> None:
    """Fail closed unless every promotion-critical binding is exact."""

    candidate_sha256 = _sha256(candidate_sha256, "candidate_sha256")
    evidence_packet_sha256 = _sha256(evidence_packet_sha256, "evidence_packet_sha256")
    base_head = _revision(base_head, "base_head")
    current_target_head = _revision(current_target_head, "current_target_head")
    now_value = _parse_timestamp(_timestamp(now, "now"))

    mismatches: list[str] = []
    if approval.nomination_sha256 != nomination.digest:
        mismatches.append("nomination")
    if approval.candidate_sha256 != candidate_sha256 or nomination.candidate_sha256 != candidate_sha256:
        mismatches.append("candidate")
    if approval.evidence_packet_sha256 != evidence_packet_sha256 or nomination.evidence_packet_sha256 != evidence_packet_sha256:
        mismatches.append("evidence")
    if approval.base_head != base_head or nomination.base_head != base_head:
        mismatches.append("base_head")
    if approval.expected_target_head != current_target_head or nomination.expected_target_head != current_target_head:
        mismatches.append("target_head")
    if approval.nonce in set(consumed_nonces):
        mismatches.append("nonce_reused")
    if now_value < _parse_timestamp(approval.issued_at):
        mismatches.append("not_yet_valid")
    if now_value >= _parse_timestamp(approval.expires_at):
        mismatches.append("expired")
    if mismatches:
        raise PermissionError("owner approval refused: " + ",".join(sorted(set(mismatches))))
