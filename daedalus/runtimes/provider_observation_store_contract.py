"""Signed guard contract for provider-observation store operations.

The pre-provisioned store separates schema publication from ordinary ledger
construction. This module adds the next non-executing boundary: one signed,
short-lived authority whose subject binds an exact store target, exact isolated
store path, exact local filesystem-write execution, exact persisted Effect
Lease digest and, for a provider-start binding, the exact provider-observation
authority and start receipt plus runtime manifest/conformance digests.

The contract deliberately does not verify or persist the Effect Lease, call
``begin_effect``, open SQLite, initialize a store, bind a row, execute a
provider, recover, promote or close a Gate. A central entrypoint must still
verify and begin the persisted lease, consume the returned GuardDecision, and
perform the operation in the isolated target.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.runtimes.provider_observation import ProviderObservationAuthority
from daedalus.runtimes.provider_observation_store import ProviderObservationStoreTarget
from daedalus.schemas import _identifier, _repo_path, _revision, _sha256, _utc_timestamp
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_sha


INITIALIZE_STORE = "initialize-store"
BIND_PROVIDER_START = "bind-provider-start"
STORE_GUARD_CONTRACT = "provider.observation_store"
_ENTRYPOINT_BY_OPERATION = {
    INITIALIZE_STORE: "provider.observation-store.initialize",
    BIND_PROVIDER_START: "provider.observation-store.bind-start",
}
_MAX_AUTHORITY_TTL = timedelta(minutes=15)


class ProviderObservationStoreContractError(RuntimeError):
    """Base class for provider-observation store contract failures."""


class ProviderObservationStoreContractBindingError(
    ProviderObservationStoreContractError
):
    """The requested store operation subjects do not bind exactly."""


class ProviderObservationStoreContractSignatureError(
    ProviderObservationStoreContractError
):
    """The signed store-operation authority did not authenticate."""


class ProviderObservationStoreContractExpired(
    ProviderObservationStoreContractError
):
    """The store-operation authority is not currently valid."""


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ProviderObservationStoreContractBindingError(
            f"{label} must be datetime"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderObservationStoreContractBindingError(
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
        raise ProviderObservationStoreContractBindingError(
            f"{label} must be bytes or str"
        )
    if len(value) < 32:
        raise ProviderObservationStoreContractBindingError(
            f"{label} must contain at least 32 bytes"
        )
    return value


def _normalized_keyring(
    keyring: Mapping[str, bytes | str],
) -> dict[str, bytes]:
    if not isinstance(keyring, Mapping) or not keyring:
        raise ProviderObservationStoreContractBindingError(
            "authority_keyring must be a non-empty mapping"
        )
    normalized: dict[str, bytes] = {}
    for raw_key, raw_secret in keyring.items():
        try:
            key_id = _identifier(raw_key, "authority_keyring key")
        except (TypeError, ValueError) as exc:
            raise ProviderObservationStoreContractBindingError(
                "authority_keyring contains a malformed key ID"
            ) from exc
        if key_id in normalized:
            raise ProviderObservationStoreContractBindingError(
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


def _target_scope_path(target: ProviderObservationStoreTarget) -> str:
    try:
        relative = Path(target.path).relative_to(Path(target.attempt_root)).as_posix()
        return _repo_path(relative, "store_scope_path")
    except (TypeError, ValueError) as exc:
        raise ProviderObservationStoreContractBindingError(
            "store target cannot be represented below its attempt root"
        ) from exc


def _validate_start_receipt(
    receipt: LeasedEffectStartReceipt,
    authority: ProviderObservationAuthority,
) -> None:
    if type(receipt) is not LeasedEffectStartReceipt:
        raise ProviderObservationStoreContractBindingError(
            "provider_start_receipt must be exact LeasedEffectStartReceipt"
        )
    expected_body = {
        "lease_sha256": receipt.lease_sha256,
        "execution_id": receipt.execution_id,
        "idempotency_key": receipt.idempotency_key,
        "execution_request_sha256": receipt.execution_request_sha256,
        "boundary_receipt_sha256": receipt.boundary_receipt_sha256,
        "started_at": receipt.started_at,
    }
    try:
        for field in (
            "lease_sha256",
            "execution_request_sha256",
            "boundary_receipt_sha256",
            "receipt_sha256",
        ):
            _sha256(getattr(receipt, field), field)
        _identifier(receipt.execution_id, "execution_id")
        _identifier(receipt.idempotency_key, "idempotency_key")
        _utc_timestamp(receipt.started_at, "started_at")
    except (TypeError, ValueError) as exc:
        raise ProviderObservationStoreContractBindingError(
            "provider_start_receipt is malformed"
        ) from exc
    if receipt.receipt_sha256 != canonical_sha(expected_body):
        raise ProviderObservationStoreContractBindingError(
            "provider_start_receipt digest mismatch"
        )
    comparisons = {
        "lease_sha256": (receipt.lease_sha256, authority.lease_sha256),
        "execution_id": (receipt.execution_id, authority.execution_id),
        "idempotency_key": (
            receipt.idempotency_key,
            authority.idempotency_key,
        ),
        "execution_request_sha256": (
            receipt.execution_request_sha256,
            authority.execution_request_sha256,
        ),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderObservationStoreContractBindingError(
            "provider start receipt and observation authority mismatch: "
            + ", ".join(mismatches)
        )


def _validate_store_write_subjects(
    *,
    operation: str,
    target: ProviderObservationStoreTarget,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
) -> tuple[str, str]:
    if operation not in _ENTRYPOINT_BY_OPERATION:
        raise ProviderObservationStoreContractBindingError(
            "unknown provider-observation store operation"
        )
    if type(target) is not ProviderObservationStoreTarget:
        raise ProviderObservationStoreContractBindingError(
            "target must be exact ProviderObservationStoreTarget"
        )
    if type(execution) is not EffectExecutionRequest:
        raise ProviderObservationStoreContractBindingError(
            "execution must be exact EffectExecutionRequest"
        )
    if type(effect_lease) is not EffectLease:
        raise ProviderObservationStoreContractBindingError(
            "effect_lease must be exact EffectLease"
        )
    expected_entrypoint = _ENTRYPOINT_BY_OPERATION[operation]
    scope_path = _target_scope_path(target)
    comparisons = {
        "entrypoint_id": (effect_lease.entrypoint_id, expected_entrypoint),
        "requested_effects": (
            effect_lease.requested_effects,
            ("filesystem_write",),
        ),
        "execution_effects": (
            execution.requested_effects,
            ("filesystem_write",),
        ),
        "execution_writable_paths": (
            execution.writable_paths,
            (scope_path,),
        ),
        "lease_writable_paths": (
            effect_lease.effect_scope.writable_paths,
            (scope_path,),
        ),
        "scope_read_only": (effect_lease.effect_scope.read_only, False),
        "source_revision": (
            effect_lease.provenance.source_revision,
            target.source_revision,
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
    }
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderObservationStoreContractBindingError(
            "store write lease/execution mismatch: " + ", ".join(mismatches)
        )
    if (
        execution.egress_endpoints
        or execution.tools
        or execution.secret_refs
        or execution.max_cost_microusd
        or effect_lease.effect_scope.egress_endpoints
        or effect_lease.effect_scope.tools
        or effect_lease.effect_scope.secret_refs
        or effect_lease.effect_scope.max_cost_microusd
    ):
        raise ProviderObservationStoreContractBindingError(
            "store write execution contains unrelated effect scope"
        )
    return expected_entrypoint, scope_path


@dataclass(frozen=True)
class ProviderObservationStoreOperationSubject:
    """Exact inert subject of one future guarded store mutation."""

    operation: str
    entrypoint_id: str
    store_target_sha256: str
    store_scope_path: str
    source_revision: str
    store_execution_id: str
    store_idempotency_key: str
    store_execution_request_sha256: str
    store_effect_lease_sha256: str
    provider_observation_authority_sha256: str | None
    provider_start_receipt_sha256: str | None
    runtime_manifest_sha256: str | None
    runtime_conformance_sha256: str | None

    def __post_init__(self) -> None:
        if self.operation not in _ENTRYPOINT_BY_OPERATION:
            raise ProviderObservationStoreContractBindingError(
                "unknown provider-observation store operation"
            )
        expected_entrypoint = _ENTRYPOINT_BY_OPERATION[self.operation]
        try:
            object.__setattr__(
                self,
                "entrypoint_id",
                _identifier(self.entrypoint_id, "entrypoint_id"),
            )
            if self.entrypoint_id != expected_entrypoint:
                raise ProviderObservationStoreContractBindingError(
                    "store operation entrypoint does not match operation"
                )
            object.__setattr__(
                self,
                "store_scope_path",
                _repo_path(self.store_scope_path, "store_scope_path"),
            )
            object.__setattr__(
                self,
                "source_revision",
                _revision(self.source_revision, "source_revision"),
            )
            for field in (
                "store_execution_id",
                "store_idempotency_key",
            ):
                object.__setattr__(
                    self,
                    field,
                    _identifier(getattr(self, field), field),
                )
            for field in (
                "store_target_sha256",
                "store_execution_request_sha256",
                "store_effect_lease_sha256",
            ):
                object.__setattr__(
                    self,
                    field,
                    _sha256(getattr(self, field), field),
                )
            for field in (
                "provider_observation_authority_sha256",
                "provider_start_receipt_sha256",
                "runtime_manifest_sha256",
                "runtime_conformance_sha256",
            ):
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(self, field, _sha256(value, field))
        except ProviderObservationStoreContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderObservationStoreContractBindingError(
                "provider-observation store operation subject is malformed"
            ) from exc
        provider_fields = (
            self.provider_observation_authority_sha256,
            self.provider_start_receipt_sha256,
            self.runtime_manifest_sha256,
            self.runtime_conformance_sha256,
        )
        if self.operation == INITIALIZE_STORE:
            if any(value is not None for value in provider_fields):
                raise ProviderObservationStoreContractBindingError(
                    "store initialization cannot attach provider runtime authority"
                )
        elif any(value is None for value in provider_fields):
            raise ProviderObservationStoreContractBindingError(
                "provider-start binding requires complete provider runtime authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProviderObservationStoreOperationSubject":
        expected = {
            "operation",
            "entrypoint_id",
            "store_target_sha256",
            "store_scope_path",
            "source_revision",
            "store_execution_id",
            "store_idempotency_key",
            "store_execution_request_sha256",
            "store_effect_lease_sha256",
            "provider_observation_authority_sha256",
            "provider_start_receipt_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProviderObservationStoreContractBindingError(
                "store operation subject fields are not exact"
            )
        try:
            return cls(**{field: payload[field] for field in expected})
        except ProviderObservationStoreContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderObservationStoreContractBindingError(
                "store operation subject is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderObservationStoreOperationAuthority:
    """Signed, short-lived authority for one exact operation subject."""

    authority_id: str
    authority_key_id: str
    nonce: str
    subject: ProviderObservationStoreOperationSubject
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if type(self.subject) is not ProviderObservationStoreOperationSubject:
            raise ProviderObservationStoreContractBindingError(
                "subject must be exact ProviderObservationStoreOperationSubject"
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
            raise ProviderObservationStoreContractBindingError(
                "store operation authority is malformed"
            ) from exc
        issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        if expires <= issued:
            raise ProviderObservationStoreContractBindingError(
                "store operation authority expires_at must follow issued_at"
            )
        if expires - issued > _MAX_AUTHORITY_TTL:
            raise ProviderObservationStoreContractBindingError(
                "store operation authority TTL exceeds 15 minutes"
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
    ) -> "ProviderObservationStoreOperationAuthority":
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
            raise ProviderObservationStoreContractBindingError(
                "store operation authority fields are not exact"
            )
        subject = payload["subject"]
        if not isinstance(subject, Mapping):
            raise ProviderObservationStoreContractBindingError(
                "store operation authority subject must be an object"
            )
        try:
            return cls(
                authority_id=payload["authority_id"],
                authority_key_id=payload["authority_key_id"],
                nonce=payload["nonce"],
                subject=ProviderObservationStoreOperationSubject.from_dict(subject),
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
                signature_sha256=payload["signature_sha256"],
            )
        except ProviderObservationStoreContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise ProviderObservationStoreContractBindingError(
                "store operation authority is malformed"
            ) from exc

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_provider_observation_store_operation_subject(
    *,
    operation: str,
    target: ProviderObservationStoreTarget,
    execution: EffectExecutionRequest,
    effect_lease: EffectLease,
    provider_observation_authority: ProviderObservationAuthority | None = None,
    provider_start_receipt: LeasedEffectStartReceipt | None = None,
    runtime_manifest_sha256: str | None = None,
    runtime_conformance_sha256: str | None = None,
) -> ProviderObservationStoreOperationSubject:
    """Build and cross-check one exact inert store-operation subject."""

    entrypoint_id, scope_path = _validate_store_write_subjects(
        operation=operation,
        target=target,
        execution=execution,
        effect_lease=effect_lease,
    )
    if operation == INITIALIZE_STORE:
        if any(
            value is not None
            for value in (
                provider_observation_authority,
                provider_start_receipt,
                runtime_manifest_sha256,
                runtime_conformance_sha256,
            )
        ):
            raise ProviderObservationStoreContractBindingError(
                "store initialization cannot attach provider runtime authority"
            )
        provider_authority_digest = None
        provider_start_digest = None
        manifest_digest = None
        conformance_digest = None
    else:
        if type(provider_observation_authority) is not ProviderObservationAuthority:
            raise ProviderObservationStoreContractBindingError(
                "provider-start binding requires exact ProviderObservationAuthority"
            )
        if type(provider_start_receipt) is not LeasedEffectStartReceipt:
            raise ProviderObservationStoreContractBindingError(
                "provider-start binding requires exact LeasedEffectStartReceipt"
            )
        if provider_observation_authority.source_revision != target.source_revision:
            raise ProviderObservationStoreContractBindingError(
                "provider observation and store target revisions differ"
            )
        _validate_start_receipt(
            provider_start_receipt,
            provider_observation_authority,
        )
        try:
            manifest_digest = _sha256(
                runtime_manifest_sha256,
                "runtime_manifest_sha256",
            )
            conformance_digest = _sha256(
                runtime_conformance_sha256,
                "runtime_conformance_sha256",
            )
        except (TypeError, ValueError) as exc:
            raise ProviderObservationStoreContractBindingError(
                "provider runtime manifest/conformance digests are malformed"
            ) from exc
        provider_authority_digest = provider_observation_authority.digest
        provider_start_digest = provider_start_receipt.receipt_sha256

    return ProviderObservationStoreOperationSubject(
        operation=operation,
        entrypoint_id=entrypoint_id,
        store_target_sha256=target.digest,
        store_scope_path=scope_path,
        source_revision=target.source_revision,
        store_execution_id=execution.execution_id,
        store_idempotency_key=execution.idempotency_key,
        store_execution_request_sha256=execution.digest,
        store_effect_lease_sha256=effect_lease.digest,
        provider_observation_authority_sha256=provider_authority_digest,
        provider_start_receipt_sha256=provider_start_digest,
        runtime_manifest_sha256=manifest_digest,
        runtime_conformance_sha256=conformance_digest,
    )


def issue_provider_observation_store_operation_authority(
    *,
    authority_id: str,
    authority_key_id: str,
    authority_secret: bytes | str,
    nonce: str,
    subject: ProviderObservationStoreOperationSubject,
    issued_at: datetime,
    expires_at: datetime,
) -> ProviderObservationStoreOperationAuthority:
    """Sign one exact store-operation subject without performing it."""

    placeholder = ProviderObservationStoreOperationAuthority(
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


def verify_provider_observation_store_operation_authority(
    authority: ProviderObservationStoreOperationAuthority,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    expected_subject: ProviderObservationStoreOperationSubject,
    at: datetime,
) -> None:
    """Authenticate and compare one exact store-operation authority."""

    if type(authority) is not ProviderObservationStoreOperationAuthority:
        raise ProviderObservationStoreContractBindingError(
            "authority must be exact ProviderObservationStoreOperationAuthority"
        )
    if type(expected_subject) is not ProviderObservationStoreOperationSubject:
        raise ProviderObservationStoreContractBindingError(
            "expected_subject must be exact ProviderObservationStoreOperationSubject"
        )
    try:
        authority_id = _identifier(expected_authority_id, "expected_authority_id")
    except (TypeError, ValueError) as exc:
        raise ProviderObservationStoreContractBindingError(
            "expected authority ID is malformed"
        ) from exc
    keyring = _normalized_keyring(authority_keyring)
    secret = keyring.get(authority.authority_key_id)
    if secret is None:
        raise ProviderObservationStoreContractSignatureError(
            "store operation authority key is unknown"
        )
    expected_signature = _signature(
        authority.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(authority.signature_sha256, expected_signature):
        raise ProviderObservationStoreContractSignatureError(
            "store operation authority signature mismatch"
        )
    instant = _as_utc(at, "at")
    issued = datetime.fromisoformat(
        authority.issued_at.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    expires = datetime.fromisoformat(
        authority.expires_at.replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    if instant < issued or instant >= expires:
        raise ProviderObservationStoreContractExpired(
            "store operation authority is not currently valid"
        )
    comparisons = {
        "authority_id": (authority.authority_id, authority_id),
        "subject": (authority.subject, expected_subject),
    }
    mismatches = tuple(
        sorted(
            field
            for field, (actual, expected) in comparisons.items()
            if actual != expected
        )
    )
    if mismatches:
        raise ProviderObservationStoreContractBindingError(
            "store operation authority binding mismatch: "
            + ", ".join(mismatches)
        )


def authorize_provider_observation_store_operation(
    authority: ProviderObservationStoreOperationAuthority,
    *,
    expected_authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    expected_subject: ProviderObservationStoreOperationSubject,
    at: datetime,
) -> GuardDecision:
    """Return guard evidence only after exact authority verification."""

    verify_provider_observation_store_operation_authority(
        authority,
        expected_authority_id=expected_authority_id,
        authority_keyring=authority_keyring,
        expected_subject=expected_subject,
        at=at,
    )
    return GuardDecision(
        contract=STORE_GUARD_CONTRACT,
        allowed=True,
        evidence=(
            f"authority_sha256={authority.digest};"
            f"subject_sha256={expected_subject.digest}"
        ),
    )


__all__ = [
    "BIND_PROVIDER_START",
    "INITIALIZE_STORE",
    "STORE_GUARD_CONTRACT",
    "ProviderObservationStoreContractBindingError",
    "ProviderObservationStoreContractError",
    "ProviderObservationStoreContractExpired",
    "ProviderObservationStoreContractSignatureError",
    "ProviderObservationStoreOperationAuthority",
    "ProviderObservationStoreOperationSubject",
    "authorize_provider_observation_store_operation",
    "build_provider_observation_store_operation_subject",
    "issue_provider_observation_store_operation_authority",
    "verify_provider_observation_store_operation_authority",
]
