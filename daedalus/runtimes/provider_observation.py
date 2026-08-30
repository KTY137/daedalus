# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Authenticated, persisted provider-observation authority for runtime effects.

The signed authority is created before an external provider invocation and binds
one provider identity plus one exact observation issuer key set to the runtime
execution subject.  After the durable effect start, the broker persists an
authenticated binding record before invoking external code.  Recovery reads that
retained record and derives the provider identity and verification keyring; it
does not accept either value from the recovery caller.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.schemas import _identifier, _revision, _sha256, _utc_timestamp
from daedalus.spine.envelope import canonical_sha


if TYPE_CHECKING:
    from daedalus.runtimes.provider_executable_pre_admission import (
        ProviderExecutablePreAdmissionReceipt,
    )
    from daedalus.runtimes.provider_invocation_abi import ProviderInvocationABIContract
    from daedalus.runtimes.provider_invocation_authority import (
        ProviderInvocationObservationAuthority,
    )
    from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload


_MAX_AUTHORITY_TTL = timedelta(hours=24)
_MAX_RECORD_BYTES = 1024 * 1024


class ProviderObservationAuthorityError(RuntimeError):
    """Base class for provider-observation authority failures."""


class ProviderObservationAuthoritySignatureError(ProviderObservationAuthorityError):
    """A signed authority or persisted record failed authentication."""


class ProviderObservationAuthorityBindingError(ProviderObservationAuthorityError):
    """Authority material does not bind one exact provider execution."""


class ProviderObservationAuthorityStateError(ProviderObservationAuthorityError):
    """The durable provider-observation binding state is missing or conflicting."""


def _secret_bytes(secret: bytes | str, label: str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        value = secret
    else:
        raise ValueError(f"{label} must be bytes or str")
    if len(value) < 32:
        raise ValueError(f"{label} must contain at least 32 bytes")
    return value


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ProviderObservationAuthorityBindingError(
            f"{label} is not canonical ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderObservationAuthorityBindingError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _signature(digest: str, secret: bytes | str, label: str) -> str:
    return hmac.new(
        _secret_bytes(secret, label),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _normalize_keyring(
    keyring: Mapping[str, bytes | str],
    *,
    label: str,
) -> tuple[tuple[str, bytes], ...]:
    if not isinstance(keyring, Mapping):
        raise ValueError(f"{label} must be a mapping")
    rows: list[tuple[str, bytes]] = []
    for key_id, secret in keyring.items():
        try:
            normalized_id = _identifier(key_id, f"{label}.key_id")
            normalized_secret = _secret_bytes(secret, f"{label}[{normalized_id}]")
        except ValueError as exc:
            raise ValueError(f"{label} is malformed") from exc
        rows.append((normalized_id, normalized_secret))
    if not rows:
        raise ValueError(f"{label} must not be empty")
    rows.sort(key=lambda row: row[0])
    if len({key_id for key_id, _ in rows}) != len(rows):
        raise ValueError(f"{label} contains duplicate key ids")
    return tuple(rows)


def observation_keyring_digest(keyring: Mapping[str, bytes | str]) -> str:
    """Return a secret-free digest of one exact observation verification key set."""

    rows = _normalize_keyring(keyring, label="observation_keyring")
    return canonical_sha(
        {
            "keys": [
                {
                    "key_id": key_id,
                    "key_sha256": hashlib.sha256(secret).hexdigest(),
                }
                for key_id, secret in rows
            ]
        }
    )


@dataclass(frozen=True)
class ProviderObservationAuthority:
    """Short-lived signed authority for one provider execution subject."""

    authority_id: str
    authority_key_id: str
    binding_id: str
    provider_id: str
    observation_issuer_key_ids: tuple[str, ...]
    observation_keyring_sha256: str
    entrypoint_id: str
    runtime_id: str
    execution_id: str
    idempotency_key: str
    execution_request_sha256: str
    lease_sha256: str
    source_revision: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "authority_id",
            "authority_key_id",
            "binding_id",
            "provider_id",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _identifier(getattr(self, field_name), field_name),
            )
        if isinstance(self.observation_issuer_key_ids, (str, bytes)) or not isinstance(
            self.observation_issuer_key_ids, Sequence
        ):
            raise ValueError("observation_issuer_key_ids must be a sequence")
        normalized_keys = tuple(
            _identifier(value, "observation_issuer_key_ids")
            for value in self.observation_issuer_key_ids
        )
        if not normalized_keys:
            raise ValueError("observation_issuer_key_ids must not be empty")
        if normalized_keys != tuple(sorted(normalized_keys)):
            raise ValueError("observation_issuer_key_ids must be sorted")
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError("observation_issuer_key_ids must be unique")
        object.__setattr__(self, "observation_issuer_key_ids", normalized_keys)
        for field_name in (
            "observation_keyring_sha256",
            "execution_request_sha256",
            "lease_sha256",
            "signature_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
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
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("provider observation authority must expire after issue")
        if expires - issued > _MAX_AUTHORITY_TTL:
            raise ValueError("provider observation authority lifetime exceeds 24 hours")

    def to_dict(self) -> dict[str, Any]:
        return {
            **dataclasses.asdict(self),
            "observation_issuer_key_ids": list(self.observation_issuer_key_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderObservationAuthority":
        expected = {
            "authority_id",
            "authority_key_id",
            "binding_id",
            "provider_id",
            "observation_issuer_key_ids",
            "observation_keyring_sha256",
            "entrypoint_id",
            "runtime_id",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "lease_sha256",
            "source_revision",
            "issued_at",
            "expires_at",
            "signature_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("provider observation authority fields are not exact")
        values = dict(payload)
        key_ids = values["observation_issuer_key_ids"]
        if isinstance(key_ids, (str, bytes)) or not isinstance(key_ids, Sequence):
            raise ValueError("observation_issuer_key_ids must be a sequence")
        values["observation_issuer_key_ids"] = tuple(key_ids)
        return cls(**values)

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class ProviderObservationBindingRecord:
    """Authenticated durable link between an authority and one effect start."""

    authority: ProviderObservationAuthority
    start_receipt: LeasedEffectStartReceipt
    bound_at: str
    record_hmac_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.authority, ProviderObservationAuthority):
            raise ValueError("authority must be ProviderObservationAuthority")
        if not isinstance(self.start_receipt, LeasedEffectStartReceipt):
            raise ValueError("start_receipt must be LeasedEffectStartReceipt")
        object.__setattr__(
            self,
            "bound_at",
            _utc_timestamp(self.bound_at, "bound_at"),
        )
        object.__setattr__(
            self,
            "record_hmac_sha256",
            _sha256(self.record_hmac_sha256, "record_hmac_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.to_dict(),
            "start_receipt": dataclasses.asdict(self.start_receipt),
            "bound_at": self.bound_at,
            "record_hmac_sha256": self.record_hmac_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProviderObservationBindingRecord":
        if not isinstance(payload, Mapping) or set(payload) != {
            "authority",
            "start_receipt",
            "bound_at",
            "record_hmac_sha256",
        }:
            raise ValueError("provider observation binding fields are not exact")
        authority_payload = payload["authority"]
        start_payload = payload["start_receipt"]
        if not isinstance(authority_payload, Mapping):
            raise ValueError("authority must be an object")
        if not isinstance(start_payload, Mapping):
            raise ValueError("start_receipt must be an object")
        expected_start = {
            "lease_sha256",
            "execution_id",
            "idempotency_key",
            "execution_request_sha256",
            "boundary_receipt_sha256",
            "started_at",
            "receipt_sha256",
        }
        if set(start_payload) != expected_start:
            raise ValueError("start_receipt fields are not exact")
        return cls(
            authority=ProviderObservationAuthority.from_dict(authority_payload),
            start_receipt=LeasedEffectStartReceipt(**dict(start_payload)),
            bound_at=payload["bound_at"],
            record_hmac_sha256=payload["record_hmac_sha256"],
        )

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["record_hmac_sha256"] = "0" * 64
        return canonical_sha(body)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def issue_provider_observation_authority(
    *,
    authority_id: str,
    authority_key_id: str,
    authority_secret: bytes | str,
    binding_id: str,
    provider_id: str,
    observation_keyring: Mapping[str, bytes | str],
    entrypoint_id: str,
    runtime_id: str,
    execution: EffectExecutionRequest,
    lease_sha256: str,
    source_revision: str,
    issued_at: datetime,
    expires_at: datetime,
) -> ProviderObservationAuthority:
    """Issue a signed authority without executing or persisting any effect."""

    if not isinstance(execution, EffectExecutionRequest):
        raise ValueError("execution must be EffectExecutionRequest")
    normalized_keyring = _normalize_keyring(
        observation_keyring,
        label="observation_keyring",
    )
    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    placeholder = ProviderObservationAuthority(
        authority_id=authority_id,
        authority_key_id=authority_key_id,
        binding_id=binding_id,
        provider_id=provider_id,
        observation_issuer_key_ids=tuple(key_id for key_id, _ in normalized_keyring),
        observation_keyring_sha256=observation_keyring_digest(observation_keyring),
        entrypoint_id=entrypoint_id,
        runtime_id=runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=lease_sha256,
        source_revision=source_revision,
        issued_at=issued.isoformat(timespec="microseconds"),
        expires_at=expires.isoformat(timespec="microseconds"),
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


def verify_provider_observation_authority(
    authority: ProviderObservationAuthority,
    *,
    authority_id: str,
    authority_keyring: Mapping[str, bytes | str],
    observation_keyring: Mapping[str, bytes | str],
    entrypoint_id: str,
    runtime_id: str,
    execution: EffectExecutionRequest,
    lease_sha256: str,
    source_revision: str,
    at: datetime,
) -> None:
    """Authenticate one exact provider and observation-key subject."""

    if type(authority) is not ProviderObservationAuthority:
        raise ProviderObservationAuthorityBindingError(
            "authority must be an exact ProviderObservationAuthority"
        )
    try:
        authority_rows = dict(
            _normalize_keyring(authority_keyring, label="authority_keyring")
        )
        observation_rows = _normalize_keyring(
            observation_keyring,
            label="observation_keyring",
        )
    except ValueError as exc:
        raise ProviderObservationAuthorityBindingError(
            "provider observation authority keyring is malformed"
        ) from exc
    secret = authority_rows.get(authority.authority_key_id)
    if secret is None:
        raise ProviderObservationAuthoritySignatureError(
            "provider observation authority key is unknown"
        )
    expected_signature = _signature(
        authority.signing_digest,
        secret,
        "authority_keyring secret",
    )
    if not hmac.compare_digest(authority.signature_sha256, expected_signature):
        raise ProviderObservationAuthoritySignatureError(
            "provider observation authority signature mismatch"
        )
    if not isinstance(execution, EffectExecutionRequest):
        raise ProviderObservationAuthorityBindingError(
            "execution must be EffectExecutionRequest"
        )
    try:
        instant = _as_utc(at, "at")
        expected_authority_id = _identifier(authority_id, "authority_id")
        expected_entrypoint = _identifier(entrypoint_id, "entrypoint_id")
        expected_runtime = _identifier(runtime_id, "runtime_id")
        expected_lease = _sha256(lease_sha256, "lease_sha256")
        expected_revision = _revision(source_revision, "source_revision")
    except ValueError as exc:
        raise ProviderObservationAuthorityBindingError(
            "provider observation authority expected subject is malformed"
        ) from exc
    issued = _parse_utc(authority.issued_at, "authority.issued_at")
    expires = _parse_utc(authority.expires_at, "authority.expires_at")
    if instant < issued:
        raise ProviderObservationAuthorityBindingError(
            "provider observation authority is not yet valid"
        )
    if instant >= expires:
        raise ProviderObservationAuthorityBindingError(
            "provider observation authority is expired"
        )
    observed_ids = tuple(key_id for key_id, _ in observation_rows)
    comparisons = {
        "authority_id": (authority.authority_id, expected_authority_id),
        "entrypoint_id": (authority.entrypoint_id, expected_entrypoint),
        "runtime_id": (authority.runtime_id, expected_runtime),
        "execution_id": (authority.execution_id, execution.execution_id),
        "idempotency_key": (
            authority.idempotency_key,
            execution.idempotency_key,
        ),
        "execution_request_sha256": (
            authority.execution_request_sha256,
            execution.digest,
        ),
        "lease_sha256": (authority.lease_sha256, expected_lease),
        "source_revision": (authority.source_revision, expected_revision),
        "observation_issuer_key_ids": (
            authority.observation_issuer_key_ids,
            observed_ids,
        ),
        "observation_keyring_sha256": (
            authority.observation_keyring_sha256,
            observation_keyring_digest(observation_keyring),
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise ProviderObservationAuthorityBindingError(
            "provider observation authority binding mismatch: "
            + ", ".join(mismatches)
        )


class ProviderObservationBindingLedger:
    """SQLite-backed authenticated binding store and observation trust root."""

    def __init__(
        self,
        path: str | Path,
        *,
        authority_id: str,
        authority_keyring: Mapping[str, bytes | str],
        observation_keyring: Mapping[str, bytes | str],
        record_secret: bytes | str,
    ) -> None:
        self.path = Path(path)
        try:
            self.authority_id = _identifier(authority_id, "authority_id")
            self._authority_keyring = dict(
                _normalize_keyring(authority_keyring, label="authority_keyring")
            )
            self._observation_keyring = dict(
                _normalize_keyring(
                    observation_keyring,
                    label="observation_keyring",
                )
            )
            self._record_secret = _secret_bytes(record_secret, "record_secret")
        except ValueError as exc:
            raise ProviderObservationAuthorityBindingError(
                "provider observation binding ledger configuration is malformed"
            ) from exc
        self.observation_keyring_sha256 = observation_keyring_digest(
            self._observation_keyring
        )
        self._initialize()

    @property
    def observation_keyring(self) -> Mapping[str, bytes]:
        return dict(self._observation_keyring)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_observation_bindings (
                    execution_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL,
                    record_hmac_sha256 TEXT NOT NULL
                )
                """
            )

    def _record_hmac(self, signing_digest: str) -> str:
        return hmac.new(
            self._record_secret,
            signing_digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def verify_authority(
        self,
        authority: ProviderObservationAuthority,
        *,
        entrypoint_id: str,
        runtime_id: str,
        execution: EffectExecutionRequest,
        lease_sha256: str,
        source_revision: str,
        at: datetime,
    ) -> None:
        verify_provider_observation_authority(
            authority,
            authority_id=self.authority_id,
            authority_keyring=self._authority_keyring,
            observation_keyring=self._observation_keyring,
            entrypoint_id=entrypoint_id,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=source_revision,
            at=at,
        )

    def verify_invocation_abi_contract(
        self,
        contract: "ProviderInvocationABIContract",
        authority: "ProviderInvocationObservationAuthority",
        payload: "ProviderInvocationPayload",
        pre_admission: "ProviderExecutablePreAdmissionReceipt",
        *,
        execution: EffectExecutionRequest,
        at: datetime,
    ) -> None:
        """Verify one invocation ABI without exporting either private keyring."""

        # Local import keeps the lower-level observation module free of an
        # import-time cycle while the ledger remains the sole secret holder.
        from daedalus.runtimes.provider_invocation_abi import (
            verify_provider_invocation_abi_contract,
        )

        verify_provider_invocation_abi_contract(
            contract,
            authority,
            payload,
            pre_admission,
            authority_id=self.authority_id,
            authority_keyring=self._authority_keyring,
            observation_keyring=self._observation_keyring,
            execution=execution,
            at=at,
        )

    @staticmethod
    def _validate_start(
        authority: ProviderObservationAuthority,
        start_receipt: LeasedEffectStartReceipt,
    ) -> None:
        if type(start_receipt) is not LeasedEffectStartReceipt:
            raise ProviderObservationAuthorityBindingError(
                "start_receipt must be an exact LeasedEffectStartReceipt"
            )
        comparisons = {
            "lease_sha256": (
                start_receipt.lease_sha256,
                authority.lease_sha256,
            ),
            "execution_id": (
                start_receipt.execution_id,
                authority.execution_id,
            ),
            "idempotency_key": (
                start_receipt.idempotency_key,
                authority.idempotency_key,
            ),
            "execution_request_sha256": (
                start_receipt.execution_request_sha256,
                authority.execution_request_sha256,
            ),
        }
        mismatches = sorted(
            name
            for name, (actual, expected) in comparisons.items()
            if actual != expected
        )
        if mismatches:
            raise ProviderObservationAuthorityBindingError(
                "provider observation start binding mismatch: "
                + ", ".join(mismatches)
            )

    @staticmethod
    def _strict_object(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate provider observation binding key")
            result[key] = value
        return result

    @classmethod
    def _parse_record_json(cls, raw: str) -> ProviderObservationBindingRecord:
        if not isinstance(raw, str):
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row is not text"
            )
        encoded = raw.encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row is oversized"
            )
        if "\x00" in raw:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row contains NUL"
            )
        try:
            payload = json.loads(
                raw,
                object_pairs_hook=cls._strict_object,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError("non-finite provider observation binding value")
                ),
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row is malformed"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row must be an object"
            )
        try:
            record = ProviderObservationBindingRecord.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row has invalid fields"
            ) from exc
        canonical = json.dumps(
            record.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if raw != canonical:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row is not canonical JSON"
            )
        return record

    def _authenticate_row(self, row: sqlite3.Row) -> ProviderObservationBindingRecord:
        try:
            record = self._parse_record_json(row["record_json"])
            stored_digest = _sha256(row["record_sha256"], "record_sha256")
            stored_hmac = _sha256(row["record_hmac_sha256"], "record_hmac_sha256")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding row is malformed"
            ) from exc
        if record.digest != stored_digest:
            raise ProviderObservationAuthoritySignatureError(
                "provider observation binding digest mismatch"
            )
        if record.record_hmac_sha256 != stored_hmac:
            raise ProviderObservationAuthoritySignatureError(
                "provider observation binding HMAC column mismatch"
            )
        expected_hmac = self._record_hmac(record.signing_digest)
        if not hmac.compare_digest(record.record_hmac_sha256, expected_hmac):
            raise ProviderObservationAuthoritySignatureError(
                "provider observation binding HMAC mismatch"
            )
        return record

    def bind_start(
        self,
        authority: ProviderObservationAuthority,
        start_receipt: LeasedEffectStartReceipt,
        *,
        bound_at: datetime,
    ) -> ProviderObservationBindingRecord:
        self._validate_start(authority, start_receipt)
        instant = _as_utc(bound_at, "bound_at")
        issued = _parse_utc(authority.issued_at, "authority.issued_at")
        expires = _parse_utc(authority.expires_at, "authority.expires_at")
        if instant < issued or instant >= expires:
            raise ProviderObservationAuthorityBindingError(
                "provider observation binding time is outside authority lifetime"
            )
        started = _parse_utc(start_receipt.started_at, "start_receipt.started_at")
        if instant < started:
            raise ProviderObservationAuthorityBindingError(
                "provider observation binding predates the durable effect start"
            )
        placeholder = ProviderObservationBindingRecord(
            authority=authority,
            start_receipt=start_receipt,
            bound_at=instant.isoformat(timespec="microseconds"),
            record_hmac_sha256="0" * 64,
        )
        record = dataclasses.replace(
            placeholder,
            record_hmac_sha256=self._record_hmac(placeholder.signing_digest),
        )
        raw = json.dumps(
            record.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM provider_observation_bindings WHERE execution_id=?",
                (authority.execution_id,),
            ).fetchone()
            if row is not None:
                existing = self._authenticate_row(row)
                if existing != record:
                    raise ProviderObservationAuthorityStateError(
                        "provider observation binding conflicts with retained execution"
                    )
                connection.execute("ROLLBACK")
                return existing
            connection.execute(
                """
                INSERT INTO provider_observation_bindings (
                    execution_id,
                    record_json,
                    record_sha256,
                    record_hmac_sha256
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    authority.execution_id,
                    raw,
                    record.digest,
                    record.record_hmac_sha256,
                ),
            )
            connection.commit()
            return record
        except sqlite3.Error as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding SQLite operation failed"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()

    def load(self, execution_id: str) -> ProviderObservationBindingRecord | None:
        try:
            normalized_execution = _identifier(execution_id, "execution_id")
        except ValueError as exc:
            raise ProviderObservationAuthorityBindingError(
                "execution_id is malformed"
            ) from exc
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM provider_observation_bindings WHERE execution_id=?",
                    (normalized_execution,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding SQLite read failed"
            ) from exc
        if row is None:
            return None
        return self._authenticate_row(row)

    def require_bound(
        self,
        authority: ProviderObservationAuthority,
        start_receipt: LeasedEffectStartReceipt,
        *,
        entrypoint_id: str,
        runtime_id: str,
        execution: EffectExecutionRequest,
        lease_sha256: str,
        source_revision: str,
    ) -> ProviderObservationBindingRecord:
        record = self.load(execution.execution_id)
        if record is None:
            raise ProviderObservationAuthorityStateError(
                "provider observation binding is missing for the durable start"
            )
        if record.authority != authority:
            raise ProviderObservationAuthorityBindingError(
                "retained provider observation authority differs"
            )
        if record.start_receipt != start_receipt:
            raise ProviderObservationAuthorityBindingError(
                "retained provider observation start receipt differs"
            )
        bound_at = _parse_utc(record.bound_at, "binding.bound_at")
        self.verify_authority(
            record.authority,
            entrypoint_id=entrypoint_id,
            runtime_id=runtime_id,
            execution=execution,
            lease_sha256=lease_sha256,
            source_revision=source_revision,
            at=bound_at,
        )
        self._validate_start(record.authority, record.start_receipt)
        return record


__all__ = [
    "ProviderObservationAuthority",
    "ProviderObservationAuthorityBindingError",
    "ProviderObservationAuthorityError",
    "ProviderObservationAuthoritySignatureError",
    "ProviderObservationAuthorityStateError",
    "ProviderObservationBindingLedger",
    "ProviderObservationBindingRecord",
    "issue_provider_observation_authority",
    "observation_keyring_digest",
    "verify_provider_observation_authority",
]
