"""Bind persisted runtime trust to one signed Effect Lease capability.

The generic EffectLease contract remains useful for non-runtime effects. A
runtime-bearing production entrypoint must instead consume the capability in
this module: it binds the signed lease to one exact, authenticated and active
RuntimeTrustRecord and rechecks that record before both grant and execution
start. The capability performs no provider call and grants no effect by itself.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Iterable, Mapping, Sequence

from daedalus.kernel.contracts import (
    EffectLease,
    EffectLeaseRequest,
    RuntimeTrustLedgerPort,
    RuntimeTrustRecordPort,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseLedger,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
    issue_effect_lease,
    verify_effect_lease,
)
from daedalus.kernel.contracts.base import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.kernel.contracts.policy import PolicyDecision
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    EntrypointSpec,
    GuardDecision,
)
from daedalus.spine.envelope import canonical_sha

_POST_START_TRUST_FAILURE_SHA256 = canonical_sha(
    {"reason": "runtime-trust-invalid-after-durable-start"}
)


class RuntimeLeaseAdmissionError(RuntimeError):
    """Base class for runtime-trust/lease composition failures."""


class RuntimeLeaseSignatureError(RuntimeLeaseAdmissionError):
    pass


class RuntimeLeaseBindingMismatch(RuntimeLeaseAdmissionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RuntimeLeaseBindingMismatch(f"{label} must be ISO-8601") from exc
    return _as_utc(parsed, label)


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("runtime lease authority secret must contain at least 32 bytes")
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret), signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()


@dataclass(frozen=True)
class RuntimeBoundEffectLease(CanonicalContract):
    """Authenticated binding between one EffectLease and live runtime evidence."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-bound-effect-lease"

    lease: EffectLease
    runtime_id: str
    runtime_envelope_sha256: str
    runtime_trust_record_sha256: str
    runtime_manifest_sha256: str
    runtime_conformance_sha256: str
    source_revision: str
    issued_at: str
    expires_at: str
    issuer_key_id: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.lease, EffectLease):
            raise ValueError("runtime-bound capability requires an EffectLease")
        object.__setattr__(self, "runtime_id", _identifier(self.runtime_id, "runtime_id"))
        object.__setattr__(
            self, "issuer_key_id", _identifier(self.issuer_key_id, "issuer_key_id")
        )
        for name in (
            "runtime_envelope_sha256",
            "runtime_trust_record_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
            "signature_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "issued_at", _utc_timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("runtime-bound lease expires_at must follow issued_at")
        comparisons = {
            "runtime_id": (self.runtime_id, self.lease.runtime_id),
            "runtime_manifest_sha256": (
                self.runtime_manifest_sha256,
                self.lease.runtime_manifest_sha256,
            ),
            "runtime_conformance_sha256": (
                self.runtime_conformance_sha256,
                self.lease.runtime_conformance_sha256,
            ),
            "source_revision": (
                self.source_revision,
                self.lease.provenance.source_revision,
            ),
            "issued_at": (self.issued_at, self.lease.issued_at),
            "expires_at": (self.expires_at, self.lease.expires_at),
        }
        mismatches = sorted(
            name for name, (actual, expected) in comparisons.items() if actual != expected
        )
        if mismatches:
            raise ValueError(
                "runtime-bound capability contradicts its EffectLease: "
                + ", ".join(mismatches)
            )
        if not self.runtime_id:
            raise ValueError("runtime-bound capability cannot wrap a non-runtime lease")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "runtime-bound capability source_revision must match provenance"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.lease.digest,
                self.runtime_envelope_sha256,
                self.runtime_trust_record_sha256,
                self.runtime_manifest_sha256,
                self.runtime_conformance_sha256,
            ),
            "runtime-bound effect lease",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            "lease": self.lease.to_dict(),
            "runtime_id": self.runtime_id,
            "runtime_envelope_sha256": self.runtime_envelope_sha256,
            "runtime_trust_record_sha256": self.runtime_trust_record_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "runtime_conformance_sha256": self.runtime_conformance_sha256,
            "source_revision": self.source_revision,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "issuer_key_id": self.issuer_key_id,
            "signature_sha256": self.signature_sha256,
            "provenance": self.provenance.to_dict(),
        }

    def signing_dict(self) -> dict[str, object]:
        body = self.to_dict()
        body.pop("signature_sha256")
        return body

    @property
    def signing_digest(self) -> str:
        return canonical_sha(self.signing_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RuntimeBoundEffectLease":
        body = cls._contract_payload(payload)
        body["lease"] = EffectLease.from_dict(body["lease"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _require_runtime_trust_ledger_port(
    value: object,
) -> RuntimeTrustLedgerPort:
    if not isinstance(value, RuntimeTrustLedgerPort):
        raise TypeError(
            "runtime_trust_ledger must implement RuntimeTrustLedgerPort"
        )
    return value


def _require_runtime_record(
    ledger: RuntimeTrustLedgerPort,
    *,
    runtime_id: str,
    envelope_sha256: str,
    manifest_sha256: str,
    conformance_sha256: str,
    source_revision: str,
    now: datetime,
) -> RuntimeTrustRecordPort:
    record = ledger.require_active(
        runtime_id=runtime_id,
        envelope_sha256=envelope_sha256,
        runtime_manifest_sha256=manifest_sha256,
        conformance_receipt_sha256=conformance_sha256,
        source_revision=source_revision,
        now=now,
    )
    if not isinstance(record, RuntimeTrustRecordPort):
        raise RuntimeLeaseBindingMismatch(
            "runtime trust ledger returned an invalid RuntimeTrustRecordPort"
        )
    return record


def issue_runtime_bound_effect_lease(
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    *,
    lease_id: str,
    lease_issuer_key_id: str,
    lease_issuer_secret: bytes | str,
    runtime_envelope_sha256: str,
    runtime_trust_ledger: RuntimeTrustLedgerPort,
    runtime_authority_key_id: str,
    runtime_authority_secret: bytes | str,
    issued_at: datetime,
    expires_at: datetime,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> RuntimeBoundEffectLease:
    """Issue a runtime lease only from one exact active persisted trust record."""

    trust_ledger = _require_runtime_trust_ledger_port(runtime_trust_ledger)
    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    lease = issue_effect_lease(
        request,
        policy_decision,
        lease_id=lease_id,
        issuer_key_id=lease_issuer_key_id,
        issued_at=issued,
        expires_at=expires,
        secret=lease_issuer_secret,
        registry=registry,
    )
    if not lease.runtime_id:
        raise RuntimeLeaseBindingMismatch(
            "runtime-bound issuance requires a runtime-bearing central entrypoint"
        )
    if request.runtime_manifest_sha256 is None or request.runtime_conformance_sha256 is None:
        raise RuntimeLeaseBindingMismatch(
            "runtime-bound issuance requires manifest and conformance digests"
        )
    envelope_digest = _sha256(
        runtime_envelope_sha256, "runtime_envelope_sha256"
    )
    record = _require_runtime_record(
        trust_ledger,
        runtime_id=lease.runtime_id,
        envelope_sha256=envelope_digest,
        manifest_sha256=request.runtime_manifest_sha256,
        conformance_sha256=request.runtime_conformance_sha256,
        source_revision=request.provenance.source_revision,
        now=issued,
    )
    if expires > _parse_utc(record.expires_at, "runtime trust expires_at"):
        raise RuntimeLeaseBindingMismatch(
            "effect lease cannot outlive the active runtime trust record"
        )
    provenance = ContractProvenance(
        origin="kernel.runtime-lease-admission",
        source_revision=request.provenance.source_revision,
        created_at=issued.isoformat(timespec="microseconds"),
        input_digests=tuple(
            sorted(
                {
                    lease.digest,
                    envelope_digest,
                    record.record_sha256,
                    request.runtime_manifest_sha256,
                    request.runtime_conformance_sha256,
                }
            )
        ),
        trace_id=request.provenance.trace_id,
    )
    placeholder = RuntimeBoundEffectLease(
        lease=lease,
        runtime_id=lease.runtime_id,
        runtime_envelope_sha256=envelope_digest,
        runtime_trust_record_sha256=record.record_sha256,
        runtime_manifest_sha256=request.runtime_manifest_sha256,
        runtime_conformance_sha256=request.runtime_conformance_sha256,
        source_revision=request.provenance.source_revision,
        issued_at=lease.issued_at,
        expires_at=lease.expires_at,
        issuer_key_id=runtime_authority_key_id,
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest, runtime_authority_secret
        ),
    )


def verify_runtime_bound_effect_lease(
    capability: RuntimeBoundEffectLease,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    lease_keyring: Mapping[str, bytes | str],
    runtime_authority_keyring: Mapping[str, bytes | str],
    runtime_trust_ledger: RuntimeTrustLedgerPort,
    current_kill_switch_generation: int,
    now: datetime,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> RuntimeTrustRecordPort:
    """Authenticate both authorities and require the exact runtime record active."""

    trust_ledger = _require_runtime_trust_ledger_port(runtime_trust_ledger)
    secret = runtime_authority_keyring.get(capability.issuer_key_id)
    if secret is None:
        raise RuntimeLeaseSignatureError("runtime lease authority key is unknown")
    expected = _signature(capability.signing_digest, secret)
    if not hmac.compare_digest(capability.signature_sha256, expected):
        raise RuntimeLeaseSignatureError("runtime-bound effect lease signature mismatch")
    instant = _as_utc(now, "now")
    verify_effect_lease(
        capability.lease,
        request=request,
        policy_decision=policy_decision,
        keyring=lease_keyring,
        current_kill_switch_generation=current_kill_switch_generation,
        now=instant,
        registry=registry,
    )
    comparisons = {
        "runtime_manifest_sha256": (
            capability.runtime_manifest_sha256,
            request.runtime_manifest_sha256,
        ),
        "runtime_conformance_sha256": (
            capability.runtime_conformance_sha256,
            request.runtime_conformance_sha256,
        ),
        "source_revision": (
            capability.source_revision,
            request.provenance.source_revision,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected_value) in comparisons.items()
        if actual != expected_value
    )
    if mismatches:
        raise RuntimeLeaseBindingMismatch(
            "runtime-bound request mismatch: " + ", ".join(mismatches)
        )
    record = _require_runtime_record(
        trust_ledger,
        runtime_id=capability.runtime_id,
        envelope_sha256=capability.runtime_envelope_sha256,
        manifest_sha256=capability.runtime_manifest_sha256,
        conformance_sha256=capability.runtime_conformance_sha256,
        source_revision=capability.source_revision,
        now=instant,
    )
    if record.record_sha256 != capability.runtime_trust_record_sha256:
        raise RuntimeLeaseBindingMismatch(
            "runtime trust record identity changed after capability issuance"
        )
    if _parse_utc(capability.expires_at, "capability expires_at") > _parse_utc(
        record.expires_at, "runtime trust expires_at"
    ):
        raise RuntimeLeaseBindingMismatch(
            "runtime-bound effect lease outlives current trust evidence"
        )
    return record


@dataclass(frozen=True)
class RuntimeBoundEffectAuthorization:
    """Capability bundle consumed by a runtime-bearing production entrypoint.

    The low-level verifier keeps an explicit ``now`` parameter for deterministic
    contract and fault tests. This production facade owns its clock so callers
    cannot backdate trust verification after lease or runtime-evidence expiry.
    """

    capability: RuntimeBoundEffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    effect_ledger: EffectLeaseLedger
    runtime_trust_ledger: RuntimeTrustLedgerPort
    lease_keyring: Mapping[str, bytes | str] = field(repr=False)
    runtime_authority_keyring: Mapping[str, bytes | str] = field(repr=False)
    guard_decisions: tuple[GuardDecision, ...]
    current_kill_switch_generation: int
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = field(
        default_factory=lambda: REGISTRY_BY_ID,
        repr=False,
    )

    def __post_init__(self) -> None:
        _require_runtime_trust_ledger_port(self.runtime_trust_ledger)
        if self.capability.lease.request_sha256 != self.request.digest:
            raise EffectLeaseBindingMismatch(
                "runtime authorization request does not match its lease"
            )
        if self.capability.lease.policy_decision_sha256 != self.policy_decision.digest:
            raise EffectLeaseBindingMismatch(
                "runtime authorization policy does not match its lease"
            )
        if not self.guard_decisions:
            raise EffectLeaseBindingMismatch(
                "runtime authorization requires concrete guard decisions"
            )
        object.__setattr__(self, "guard_decisions", tuple(self.guard_decisions))
        object.__setattr__(self, "lease_keyring", dict(self.lease_keyring))
        object.__setattr__(
            self, "runtime_authority_keyring", dict(self.runtime_authority_keyring)
        )

    def _verify_at(self, instant: datetime) -> RuntimeTrustRecordPort:
        return verify_runtime_bound_effect_lease(
            self.capability,
            request=self.request,
            policy_decision=self.policy_decision,
            lease_keyring=self.lease_keyring,
            runtime_authority_keyring=self.runtime_authority_keyring,
            runtime_trust_ledger=self.runtime_trust_ledger,
            current_kill_switch_generation=self.current_kill_switch_generation,
            now=instant,
            registry=self.registry,
        )

    def verify(self) -> RuntimeTrustRecordPort:
        """Require the exact runtime trust record active at the facade clock."""

        return self._verify_at(_utc_now())

    def grant(self) -> None:
        instant = _utc_now()
        self._verify_at(instant)
        self.effect_ledger.grant(
            self.capability.lease,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.lease_keyring,
            current_kill_switch_generation=self.current_kill_switch_generation,
            granted_at=instant,
            registry=self.registry,
        )

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        pre_start = _utc_now()
        self._verify_at(pre_start)
        result = self.effect_ledger.begin(
            self.capability.lease,
            execution,
            request=self.request,
            policy_decision=self.policy_decision,
            keyring=self.lease_keyring,
            guard_decisions=self.guard_decisions,
            current_kill_switch_generation=self.current_kill_switch_generation,
            started_at=pre_start,
            registry=self.registry,
        )
        if result.execute:
            try:
                # Recheck after the durable start receipt and before the caller
                # is allowed to perform the external effect.
                self._verify_at(_utc_now())
            except Exception:
                self.effect_ledger.finish(
                    result.receipt,
                    outcome="cancelled",
                    detail_sha256=_POST_START_TRUST_FAILURE_SHA256,
                    finished_at=_utc_now(),
                )
                raise
        return result

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests: Iterable[str] = (),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        if start_receipt.lease_sha256 != self.capability.lease.digest:
            raise EffectLeaseBindingMismatch(
                "start receipt belongs to a different runtime effect lease"
            )
        return self.effect_ledger.finish(
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )


__all__ = [
    "RuntimeBoundEffectAuthorization",
    "RuntimeBoundEffectLease",
    "RuntimeLeaseAdmissionError",
    "RuntimeLeaseBindingMismatch",
    "RuntimeLeaseSignatureError",
    "issue_runtime_bound_effect_lease",
    "verify_runtime_bound_effect_lease",
]
