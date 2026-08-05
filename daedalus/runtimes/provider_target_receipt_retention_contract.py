"""Signed guard contract for provider-target receipt retention.

The contract is deliberately inert. It binds one exact receipt-retention
request to a separate local filesystem-write Effect Lease, the authenticated
provider-target receipt identity, and the exact revision/byte identities of the
retention inventory. It does not authenticate the receipt or inventory, begin
an Effect Lease, open SQLite, write CAS/Event-Store state, execute a provider,
promote a candidate, or close a Gate.

A future central entrypoint must independently authenticate the receipt and
inventory, verify and begin the persisted retention lease, prove concrete
CAS/Event-Store targets are outside the Primary Checkout, consume the returned
guard decision, and only then call the retention ledger.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
)
from daedalus.schemas import _identifier, _repo_path, _revision, _sha256, _utc_timestamp
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_sha

RETAIN_RECEIPT = "retain-receipt"
RETENTION_ENTRYPOINT = "provider.target-receipt.retain"
RETENTION_GUARD_CONTRACT = "provider.target_receipt_retention"
_MAX_AUTHORITY_TTL = timedelta(minutes=15)


class ProviderTargetReceiptRetentionContractError(RuntimeError):
    """Base class for retention-contract refusal."""


class ProviderTargetReceiptRetentionContractBindingError(
    ProviderTargetReceiptRetentionContractError
):
    """The signed authority, receipt, inventory, or effect scope disagrees."""


class ProviderTargetReceiptRetentionContractSignatureError(
    ProviderTargetReceiptRetentionContractError
):
    """The retention-operation authority did not authenticate."""


class ProviderTargetReceiptRetentionContractExpired(
    ProviderTargetReceiptRetentionContractError
):
    """The retention-operation authority is not currently valid."""


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ProviderTargetReceiptRetentionContractBindingError(
            f"{label} must be datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderTargetReceiptRetentionContractBindingError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime, label: str) -> str:
    return _utc_timestamp(
        _as_utc(value, label).isoformat(timespec="microseconds"),
        label,
    )


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ProviderTargetReceiptRetentionContractBindingError(
            f"{label} must be bytes or str"
        )
    if len(value) < 32:
        raise ProviderTargetReceiptRetentionContractBindingError(
            f"{label} must contain at least 32 bytes"
        )
    return value


def _normalized_keyring(keyring: Mapping[str, bytes | str]) -> dict[str, bytes]:
    if not isinstance(keyring, Mapping) or not keyring:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "authority_keyring must be a non-empty mapping"
        )
    normalized: dict[str, bytes] = {}
    for raw_key, raw_secret in keyring.items():
        try:
            key_id = _identifier(raw_key, "authority_keyring key")
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "authority_keyring contains a malformed key ID"
            ) from exc
        if key_id in normalized:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "authority_keyring contains duplicate normalized key IDs"
            )
        normalized[key_id] = _secret_bytes(
            raw_secret,
            f"authority_keyring[{key_id}]",
        )
    return normalized


def _signature(digest: str, secret: bytes | str, label: str) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _paths_overlap(left: str, right: str) -> bool:
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def _validate_retention_effect_scope(
    *,
    receipt: ProviderExecutableTargetVerificationReceipt,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
) -> tuple[str, str]:
    if type(receipt) is not ProviderExecutableTargetVerificationReceipt:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "receipt must be exact ProviderExecutableTargetVerificationReceipt"
        )
    if type(execution) is not EffectExecutionRequest:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "execution must be exact EffectExecutionRequest"
        )
    if type(effect_lease) is not EffectLease:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "effect_lease must be exact EffectLease"
        )
    try:
        event_path = _repo_path(event_store_scope_path, "event_store_scope_path")
        cas_path = _repo_path(receipt_cas_scope_path, "receipt_cas_scope_path")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention writable paths are malformed"
        ) from exc
    if event_path == "." or cas_path == "." or _paths_overlap(event_path, cas_path):
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention Event Store and receipt CAS scopes must be disjoint"
        )

    expected_paths = tuple(sorted((event_path, cas_path)))
    comparisons = {
        "entrypoint_id": (effect_lease.entrypoint_id, RETENTION_ENTRYPOINT),
        "execution_effects": (
            execution.requested_effects,
            ("filesystem_write",),
        ),
        "lease_effects": (
            effect_lease.requested_effects,
            ("filesystem_write",),
        ),
        "execution_writable_paths": (execution.writable_paths, expected_paths),
        "lease_writable_paths": (
            effect_lease.effect_scope.writable_paths,
            expected_paths,
        ),
        "scope_read_only": (effect_lease.effect_scope.read_only, False),
        "source_revision": (
            effect_lease.provenance.source_revision,
            receipt.source_revision,
        ),
        "kill_switch_generation": (
            execution.kill_switch_generation,
            effect_lease.kill_switch_generation,
        ),
        "kill_switch_ref": (
            execution.kill_switch_ref,
            effect_lease.effect_scope.kill_switch_ref,
        ),
        "runtime_id": (effect_lease.runtime_id, ""),
        "runtime_manifest_sha256": (
            effect_lease.runtime_manifest_sha256,
            None,
        ),
        "runtime_conformance_sha256": (
            effect_lease.runtime_conformance_sha256,
            None,
        ),
        "max_concurrency": (effect_lease.effect_scope.max_concurrency, 1),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention lease/execution mismatch: " + ", ".join(mismatches)
        )
    if not execution.kill_switch_ref or not effect_lease.effect_scope.kill_switch_ref:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention execution requires a kill switch"
        )
    if (
        execution.egress_endpoints
        or execution.tools
        or execution.secret_refs
        or execution.max_cost_microusd
        or effect_lease.effect_scope.egress_endpoints
        or effect_lease.effect_scope.tools
        or effect_lease.effect_scope.secret_refs
        or effect_lease.effect_scope.max_cost_microusd is not None
    ):
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention execution contains unrelated effect scope"
        )
    if effect_lease.digest == receipt.lease_sha256:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "provider execution lease cannot be reused for receipt retention"
        )
    if execution.execution_id == receipt.execution_id:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "provider and retention executions must have distinct identities"
        )
    if execution.idempotency_key == receipt.idempotency_key:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "provider and retention idempotency keys must be distinct"
        )
    if receipt.entrypoint_id == RETENTION_ENTRYPOINT:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "provider receipt entrypoint cannot be the retention entrypoint"
        )
    return event_path, cas_path


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionOperationSubject:
    """Exact inert subject of one future guarded receipt-retention mutation."""

    operation: str
    entrypoint_id: str
    source_revision: str
    receipt_sha256: str
    receipt_artifact_locator: str
    provider_id: str
    provider_runtime_id: str
    provider_execution_id: str
    provider_idempotency_key: str
    provider_effect_lease_sha256: str
    retention_inventory_sha256: str
    retention_inventory_source_revision: str
    retention_inventory_source_sha256: str
    retention_execution_id: str
    retention_idempotency_key: str
    retention_execution_request_sha256: str
    retention_effect_lease_sha256: str
    event_store_scope_path: str
    receipt_cas_scope_path: str

    def __post_init__(self) -> None:
        if self.operation != RETAIN_RECEIPT:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "unknown receipt-retention operation"
            )
        try:
            object.__setattr__(
                self,
                "entrypoint_id",
                _identifier(self.entrypoint_id, "entrypoint_id"),
            )
            if self.entrypoint_id != RETENTION_ENTRYPOINT:
                raise ProviderTargetReceiptRetentionContractBindingError(
                    "retention entrypoint does not match operation"
                )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            object.__setattr__(
                self,
                "retention_inventory_source_revision",
                _revision(
                    self.retention_inventory_source_revision,
                    "retention_inventory_source_revision",
                ),
            )
            for field in (
                "provider_id",
                "provider_runtime_id",
                "provider_execution_id",
                "provider_idempotency_key",
                "retention_execution_id",
                "retention_idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in (
                "receipt_sha256",
                "provider_effect_lease_sha256",
                "retention_inventory_sha256",
                "retention_inventory_source_sha256",
                "retention_execution_request_sha256",
                "retention_effect_lease_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            object.__setattr__(
                self,
                "event_store_scope_path",
                _repo_path(self.event_store_scope_path, "event_store_scope_path"),
            )
            object.__setattr__(
                self,
                "receipt_cas_scope_path",
                _repo_path(self.receipt_cas_scope_path, "receipt_cas_scope_path"),
            )
        except ProviderTargetReceiptRetentionContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "receipt-retention operation subject is malformed"
            ) from exc

        if self.retention_inventory_source_revision != self.source_revision:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention inventory and receipt source revisions differ"
            )
        expected_locator = ArtifactRef.from_sha256(self.receipt_sha256).locator
        if self.receipt_artifact_locator != expected_locator:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "receipt artifact locator does not match receipt digest"
            )
        if (
            self.event_store_scope_path == "."
            or self.receipt_cas_scope_path == "."
            or _paths_overlap(
                self.event_store_scope_path,
                self.receipt_cas_scope_path,
            )
        ):
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention subject writable paths are not disjoint"
            )
        if self.provider_effect_lease_sha256 == self.retention_effect_lease_sha256:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "provider and retention lease identities must differ"
            )
        if self.provider_execution_id == self.retention_execution_id:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "provider and retention execution identities must differ"
            )
        if self.provider_idempotency_key == self.retention_idempotency_key:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "provider and retention idempotency keys must differ"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-provider-target-receipt-retention-operation/1",
            **dataclasses.asdict(self),
            "provider_execution_allowed": False,
            "retention_effect_started": False,
            "primary_checkout_disjointness_verified": False,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionOperationSubject":
        fields = {field.name for field in dataclasses.fields(cls)}
        expected = {
            "schema",
            *fields,
            "provider_execution_allowed",
            "retention_effect_started",
            "primary_checkout_disjointness_verified",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation subject fields are not exact"
            )
        if payload["schema"] != "daedalus-provider-target-receipt-retention-operation/1":
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation subject schema does not match"
            )
        if payload["provider_execution_allowed"] is not False:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention subject cannot authorize provider execution"
            )
        if payload["retention_effect_started"] is not False:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention subject cannot claim an effect start"
            )
        if payload["primary_checkout_disjointness_verified"] is not False:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention subject cannot claim checkout disjointness"
            )
        try:
            return cls(**{field: payload[field] for field in fields})
        except ProviderTargetReceiptRetentionContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation subject is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionOperationAuthority:
    """Signed, short-lived authority for one exact retention subject."""

    authority_id: str
    authority_key_id: str
    nonce: str
    subject: ProviderTargetReceiptRetentionOperationSubject
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if type(self.subject) is not ProviderTargetReceiptRetentionOperationSubject:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "subject must be exact retention operation subject"
            )
        try:
            for field in ("authority_id", "authority_key_id", "nonce"):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
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
            object.__setattr__(
                self,
                "signature_sha256",
                _sha256(self.signature_sha256, "signature_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation authority is malformed"
            ) from exc
        issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if expires <= issued:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention authority expires_at must follow issued_at"
            )
        if expires - issued > _MAX_AUTHORITY_TTL:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention authority TTL exceeds 15 minutes"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "authority_key_id": self.authority_key_id,
            "nonce": self.nonce,
            "subject": self.subject.to_dict(),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature_sha256": self.signature_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderTargetReceiptRetentionOperationAuthority":
        expected = {
            "authority_id",
            "authority_key_id",
            "nonce",
            "subject",
            "issued_at",
            "expires_at",
            "signature_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation authority fields are not exact"
            )
        if not isinstance(payload["subject"], Mapping):
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation authority subject must be an object"
            )
        try:
            return cls(
                authority_id=payload["authority_id"],
                authority_key_id=payload["authority_key_id"],
                nonce=payload["nonce"],
                subject=ProviderTargetReceiptRetentionOperationSubject.from_dict(
                    payload["subject"]
                ),
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
                signature_sha256=payload["signature_sha256"],
            )
        except ProviderTargetReceiptRetentionContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderTargetReceiptRetentionContractBindingError(
                "retention operation authority is malformed"
            ) from exc

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_provider_target_receipt_retention_operation_subject(
    *,
    receipt: ProviderExecutableTargetVerificationReceipt,
    retention_inventory_sha256: str,
    retention_inventory_source_revision: str,
    retention_inventory_source_sha256: str,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
    event_store_scope_path: str,
    receipt_cas_scope_path: str,
) -> ProviderTargetReceiptRetentionOperationSubject:
    """Build and cross-check one exact inert retention-operation subject."""

    event_path, cas_path = _validate_retention_effect_scope(
        receipt=receipt,
        execution=execution,
        effect_lease=effect_lease,
        event_store_scope_path=event_store_scope_path,
        receipt_cas_scope_path=receipt_cas_scope_path,
    )
    try:
        inventory_digest = _sha256(
            retention_inventory_sha256,
            "retention_inventory_sha256",
        )
        inventory_revision = _revision(
            retention_inventory_source_revision,
            "retention_inventory_source_revision",
        )
        inventory_source_digest = _sha256(
            retention_inventory_source_sha256,
            "retention_inventory_source_sha256",
        )
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention inventory identities are malformed"
        ) from exc
    if inventory_revision != receipt.source_revision:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention inventory and receipt source revisions differ"
        )

    return ProviderTargetReceiptRetentionOperationSubject(
        operation=RETAIN_RECEIPT,
        entrypoint_id=RETENTION_ENTRYPOINT,
        source_revision=receipt.source_revision,
        receipt_sha256=receipt.digest,
        receipt_artifact_locator=ArtifactRef.from_sha256(receipt.digest).locator,
        provider_id=receipt.provider_id,
        provider_runtime_id=receipt.runtime_id,
        provider_execution_id=receipt.execution_id,
        provider_idempotency_key=receipt.idempotency_key,
        provider_effect_lease_sha256=receipt.lease_sha256,
        retention_inventory_sha256=inventory_digest,
        retention_inventory_source_revision=inventory_revision,
        retention_inventory_source_sha256=inventory_source_digest,
        retention_execution_id=execution.execution_id,
        retention_idempotency_key=execution.idempotency_key,
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=effect_lease.digest,
        event_store_scope_path=event_path,
        receipt_cas_scope_path=cas_path,
    )


def issue_provider_target_receipt_retention_operation_authority(
    *,
    authority_id: str,
    authority_key_id: str,
    authority_secret: bytes | str,
    nonce: str,
    subject: ProviderTargetReceiptRetentionOperationSubject,
    issued_at: datetime,
    expires_at: datetime,
) -> ProviderTargetReceiptRetentionOperationAuthority:
    """Sign one exact retention subject without performing the write."""

    if type(subject) is not ProviderTargetReceiptRetentionOperationSubject:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "subject must be exact retention operation subject"
        )
    placeholder = ProviderTargetReceiptRetentionOperationAuthority(
        authority_id=authority_id,
        authority_key_id=authority_key_id,
        nonce=nonce,
        subject=subject,
        issued_at=_timestamp(issued_at, "issued_at"),
        expires_at=_timestamp(expires_at, "expires_at"),
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            authority_secret,
            "authority_secret",
        ),
    )


def verify_provider_target_receipt_retention_operation_authority(
    authority: ProviderTargetReceiptRetentionOperationAuthority,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    expected_subject: ProviderTargetReceiptRetentionOperationSubject,
    at: datetime,
) -> None:
    """Authenticate and compare one exact retention-operation authority."""

    if type(authority) is not ProviderTargetReceiptRetentionOperationAuthority:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "authority must be exact retention operation authority"
        )
    if type(expected_subject) is not ProviderTargetReceiptRetentionOperationSubject:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "expected_subject must be exact retention operation subject"
        )
    try:
        authority_id = _identifier(expected_authority_id, "expected_authority_id")
    except (TypeError, ValueError) as exc:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "expected authority ID is malformed"
        ) from exc
    keyring = _normalized_keyring(authority_keyring)
    secret = keyring.get(authority.authority_key_id)
    if secret is None:
        raise ProviderTargetReceiptRetentionContractSignatureError(
            "retention operation authority key is unknown"
        )
    expected_signature = _signature(
        authority.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(authority.signature_sha256, expected_signature):
        raise ProviderTargetReceiptRetentionContractSignatureError(
            "retention operation authority signature mismatch"
        )

    instant = _as_utc(at, "at")
    issued = datetime.fromisoformat(
        authority.issued_at.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    expires = datetime.fromisoformat(
        authority.expires_at.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    if instant < issued or instant >= expires:
        raise ProviderTargetReceiptRetentionContractExpired(
            "retention operation authority is not currently valid"
        )
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in {
                "authority_id": (authority.authority_id, authority_id),
                "subject": (authority.subject, expected_subject),
            }.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderTargetReceiptRetentionContractBindingError(
            "retention operation authority binding mismatch: "
            + ", ".join(mismatches)
        )


def authorize_provider_target_receipt_retention_operation(
    authority: ProviderTargetReceiptRetentionOperationAuthority,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    expected_subject: ProviderTargetReceiptRetentionOperationSubject,
    at: datetime,
) -> GuardDecision:
    """Return one guard decision only after exact authority verification."""

    verify_provider_target_receipt_retention_operation_authority(
        authority,
        expected_authority_id=expected_authority_id,
        authority_keyring=authority_keyring,
        expected_subject=expected_subject,
        at=at,
    )
    return GuardDecision(
        contract=RETENTION_GUARD_CONTRACT,
        allowed=True,
        evidence=(
            f"authority_sha256={authority.digest};"
            f"subject_sha256={expected_subject.digest}"
        ),
    )


__all__ = [
    "RETAIN_RECEIPT",
    "RETENTION_ENTRYPOINT",
    "RETENTION_GUARD_CONTRACT",
    "ProviderTargetReceiptRetentionContractBindingError",
    "ProviderTargetReceiptRetentionContractError",
    "ProviderTargetReceiptRetentionContractExpired",
    "ProviderTargetReceiptRetentionContractSignatureError",
    "ProviderTargetReceiptRetentionOperationAuthority",
    "ProviderTargetReceiptRetentionOperationSubject",
    "authorize_provider_target_receipt_retention_operation",
    "build_provider_target_receipt_retention_operation_subject",
    "issue_provider_target_receipt_retention_operation_authority",
    "verify_provider_target_receipt_retention_operation_authority",
]
