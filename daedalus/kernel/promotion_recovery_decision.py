"""Authenticated but inert owner decision for one effect-only promotion recovery.

This module defines and verifies the exact signed decision required before a
future writer may cancel a persisted promotion Effect Lease whose start exists
but whose promotion execution never started.  It deliberately provides no
issuer, persistence ledger, cancellation writer, terminal writer, Git access or
promotion authority.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from daedalus.spine.envelope import canonical_sha

from .promotion_effects import PromotionEffectCapability
from .promotion_reconciliation import PromotionReconciliationDisposition
from .promotion_recovery import (
    PromotionRecoveryAction,
    PromotionRecoveryPlan,
)


_MAX_RECOVERY_DECISION_TTL = timedelta(hours=24)
_RECOVERY_OPERATION = "cancel-unentered-promotion-effect"


class PromotionRecoveryDecisionError(RuntimeError):
    """Base class for fail-closed owner recovery-decision rejection."""


class PromotionRecoveryDecisionSignatureError(PromotionRecoveryDecisionError):
    pass


class PromotionRecoveryDecisionExpired(PromotionRecoveryDecisionError):
    pass


class PromotionRecoveryDecisionBindingMismatch(PromotionRecoveryDecisionError):
    pass


@dataclass(frozen=True)
class PromotionRecoveryExpectation:
    """Exact effect-only recovery subject that a signed decision must bind."""

    promotion_authorization_sha256: str
    recovery_plan_sha256: str
    effect_start_receipt_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        for name in (
            "promotion_authorization_sha256",
            "recovery_plan_sha256",
            "effect_start_receipt_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "promotion_authorization_sha256": self.promotion_authorization_sha256,
            "recovery_plan_sha256": self.recovery_plan_sha256,
            "effect_start_receipt_sha256": self.effect_start_receipt_sha256,
            "source_revision": self.source_revision,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class PromotionRecoveryDecision(CanonicalContract):
    """Signed owner intent, inert until separately persisted and consumed."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-recovery-decision"

    decision_id: str
    owner_id: str
    key_id: str
    operation: str
    promotion_authorization_sha256: str
    recovery_plan_sha256: str
    effect_start_receipt_sha256: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("decision_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != _RECOVERY_OPERATION:
            raise ValueError(
                f"promotion recovery operation must be {_RECOVERY_OPERATION}"
            )
        for name in (
            "promotion_authorization_sha256",
            "recovery_plan_sha256",
            "effect_start_receipt_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
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
        if self.expires_at <= self.issued_at:
            raise ValueError("recovery decision expires_at must be after issued_at")
        _require_provenance_inputs(
            self.provenance,
            (
                self.promotion_authorization_sha256,
                self.recovery_plan_sha256,
                self.effect_start_receipt_sha256,
            ),
            "promotion recovery decision",
        )

    def signing_dict(self) -> dict[str, Any]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromotionRecoveryDecision":
        body = cls._contract_payload(payload)
        provenance = body.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ValueError("promotion recovery decision provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


@dataclass(frozen=True)
class VerifiedPromotionRecoveryDecision:
    """Authenticated exact recovery intent; still not writer authority."""

    decision_sha256: str
    decision_id: str
    owner_id: str
    key_id: str
    operation: str
    promotion_authorization_sha256: str
    recovery_plan_sha256: str
    effect_start_receipt_sha256: str
    source_revision: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "decision_sha256",
            "promotion_authorization_sha256",
            "recovery_plan_sha256",
            "effect_start_receipt_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for name in ("decision_id", "owner_id", "key_id", "nonce"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.operation != _RECOVERY_OPERATION:
            raise ValueError("verified recovery decision operation mismatch")
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
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
        if self.expires_at <= self.issued_at:
            raise ValueError("verified recovery decision expiry mismatch")

    def to_dict(self) -> dict[str, str]:
        return {
            "decision_sha256": self.decision_sha256,
            "decision_id": self.decision_id,
            "owner_id": self.owner_id,
            "key_id": self.key_id,
            "operation": self.operation,
            "promotion_authorization_sha256": self.promotion_authorization_sha256,
            "recovery_plan_sha256": self.recovery_plan_sha256,
            "effect_start_receipt_sha256": self.effect_start_receipt_sha256,
            "source_revision": self.source_revision,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature_sha256": self.signature_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PromotionRecoveryDecisionBindingMismatch(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionRecoveryDecisionBindingMismatch(
            f"{label} is not timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("owner recovery secret must contain at least 32 bytes")
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _verify_plan_digest(plan: PromotionRecoveryPlan) -> None:
    body = plan.to_dict()
    declared = body.pop("plan_sha256")
    if not hmac.compare_digest(declared, canonical_sha(body)):
        raise PromotionRecoveryDecisionBindingMismatch(
            "promotion recovery plan digest mismatch"
        )


def recovery_expectation(
    plan: PromotionRecoveryPlan,
    capability: PromotionEffectCapability,
) -> PromotionRecoveryExpectation:
    """Derive the sole owner-decision subject from a strict effect-only plan."""

    if not isinstance(plan, PromotionRecoveryPlan):
        raise TypeError("recovery expectation requires PromotionRecoveryPlan")
    if not isinstance(capability, PromotionEffectCapability):
        raise TypeError("recovery expectation requires PromotionEffectCapability")
    _verify_plan_digest(plan)

    if (
        plan.disposition
        != PromotionReconciliationDisposition.EFFECT_ONLY_PENDING.value
        or plan.action
        != PromotionRecoveryAction.OWNER_DECISION_BEFORE_EFFECT_CANCELLATION.value
        or plan.automatic_external_reexecution is not False
        or plan.manual_reconciliation_required is not True
        or plan.owner_decision_required is not True
        or plan.effect_start_receipt_sha256 is None
        or plan.effect_terminal_receipt_sha256 is not None
        or plan.promotion_start_sha256 is not None
        or plan.promotion_terminal_sha256 is not None
    ):
        raise PromotionRecoveryDecisionBindingMismatch(
            "owner recovery decision requires one exact effect-only pending plan"
        )

    authorization = capability.promotion
    if plan.promotion_authorization_sha256 != authorization.authorization_sha256:
        raise PromotionRecoveryDecisionBindingMismatch(
            "recovery plan does not bind the supplied promotion capability"
        )
    return PromotionRecoveryExpectation(
        promotion_authorization_sha256=authorization.authorization_sha256,
        recovery_plan_sha256=plan.plan_sha256,
        effect_start_receipt_sha256=plan.effect_start_receipt_sha256,
        source_revision=authorization.source_revision,
    )


def verify_promotion_recovery_decision(
    decision: PromotionRecoveryDecision,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expectation: PromotionRecoveryExpectation,
    now: datetime | None = None,
) -> VerifiedPromotionRecoveryDecision:
    """Authenticate one exact owner decision without persisting or consuming it."""

    if not isinstance(decision, PromotionRecoveryDecision):
        raise TypeError("verification requires PromotionRecoveryDecision")
    if not isinstance(expectation, PromotionRecoveryExpectation):
        raise TypeError("verification requires PromotionRecoveryExpectation")
    secret = keyring.get((decision.owner_id, decision.key_id))
    if secret is None:
        raise PromotionRecoveryDecisionSignatureError(
            "owner recovery decision key is unknown"
        )
    expected_signature = _signature(decision.signing_digest, secret)
    if not hmac.compare_digest(decision.signature_sha256, expected_signature):
        raise PromotionRecoveryDecisionSignatureError(
            "owner recovery decision signature mismatch"
        )

    instant = _as_utc(now, "now") if now is not None else datetime.now(timezone.utc)
    issued = _parse_utc(decision.issued_at, "decision.issued_at")
    expires = _parse_utc(decision.expires_at, "decision.expires_at")
    if expires - issued > _MAX_RECOVERY_DECISION_TTL:
        raise PromotionRecoveryDecisionExpired(
            "owner recovery decision TTL exceeds the Gate-0 maximum"
        )
    if instant < issued:
        raise PromotionRecoveryDecisionExpired(
            "owner recovery decision is not valid yet"
        )
    if instant >= expires:
        raise PromotionRecoveryDecisionExpired(
            "owner recovery decision has expired"
        )

    comparisons = {
        "operation": (decision.operation, _RECOVERY_OPERATION),
        "promotion_authorization_sha256": (
            decision.promotion_authorization_sha256,
            expectation.promotion_authorization_sha256,
        ),
        "recovery_plan_sha256": (
            decision.recovery_plan_sha256,
            expectation.recovery_plan_sha256,
        ),
        "effect_start_receipt_sha256": (
            decision.effect_start_receipt_sha256,
            expectation.effect_start_receipt_sha256,
        ),
        "source_revision": (
            decision.provenance.source_revision,
            expectation.source_revision,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise PromotionRecoveryDecisionBindingMismatch(
            "owner recovery decision binding mismatch: " + ", ".join(mismatches)
        )

    return VerifiedPromotionRecoveryDecision(
        decision_sha256=decision.digest,
        decision_id=decision.decision_id,
        owner_id=decision.owner_id,
        key_id=decision.key_id,
        operation=decision.operation,
        promotion_authorization_sha256=decision.promotion_authorization_sha256,
        recovery_plan_sha256=decision.recovery_plan_sha256,
        effect_start_receipt_sha256=decision.effect_start_receipt_sha256,
        source_revision=decision.provenance.source_revision,
        nonce=decision.nonce,
        issued_at=decision.issued_at,
        expires_at=decision.expires_at,
        signature_sha256=decision.signature_sha256,
    )


__all__ = [
    "PromotionRecoveryDecision",
    "PromotionRecoveryDecisionBindingMismatch",
    "PromotionRecoveryDecisionError",
    "PromotionRecoveryDecisionExpired",
    "PromotionRecoveryDecisionSignatureError",
    "PromotionRecoveryExpectation",
    "VerifiedPromotionRecoveryDecision",
    "recovery_expectation",
    "verify_promotion_recovery_decision",
]
