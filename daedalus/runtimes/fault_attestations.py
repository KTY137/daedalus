"""Authenticate runtime-fault observations before they enter a trust set.

A :class:`RuntimeFaultObservation` is a canonical record, not proof. This module
adds an external issuer boundary. An attestation binds one complete observation
record to the canonical fault catalog, exact source revision, authority class,
issuer/key identity, nonce, and bounded validity window. HMAC keys are supplied
by the caller and are never read from repository configuration.

The resulting helper does not create test evidence. It verifies already retained
observations and attestations, delegates completeness/outcome checks to the
canonical matrix verifier, and returns a content-addressed receipt retaining the
exact attestation digests and verification time.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from daedalus.runtimes.fault_matrix import (
    RuntimeFaultCatalog,
    RuntimeFaultMatrix,
    RuntimeFaultObservation,
    RuntimeFaultVerification,
    verify_runtime_fault_matrix,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-runtime-fault-attestation/1"
_DOMAIN = (_SCHEMA + "\0").encode("utf-8")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_AUTHORITIES = frozenset({"deterministic-fixture", "linux-host", "live-runtime"})
_MAX_VALIDITY = timedelta(days=7)


class RuntimeFaultAttestationError(RuntimeError):
    """Base class for fault-attestation verification failures."""


class RuntimeFaultAttestationBindingMismatch(RuntimeFaultAttestationError):
    """An attestation does not bind the selected observation or authority."""


class RuntimeFaultAttestationSignatureError(RuntimeFaultAttestationError):
    """An attestation signature or signing key is invalid."""


class RuntimeFaultAttestationExpired(RuntimeFaultAttestationError):
    """An attestation is not valid at the requested verification time."""


class RuntimeFaultAttestationReplay(RuntimeFaultAttestationError):
    """The supplied attestation collection is ambiguous or duplicated."""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _revision(value: Any, name: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a full lowercase Git/SHA revision")
    return value


def _authority(value: Any, name: str = "authority") -> str:
    text = _identifier(value, name)
    if text not in _AUTHORITIES:
        raise ValueError(f"{name} must be one of {sorted(_AUTHORITIES)}")
    return text


def _timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _strict_payload(payload: Mapping[str, Any], cls: type, name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    expected = {item.name for item in fields(cls)}
    missing = sorted(expected - set(payload))
    extra = sorted(set(payload) - expected)
    if missing or extra:
        raise ValueError(f"{name} fields mismatch; missing={missing}, extra={extra}")
    return dict(payload)


def _secret(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError("attestation secret must contain at least 32 bytes")
    return value


def _normalize_now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("verification time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _signature(body: Mapping[str, Any], secret: bytes) -> str:
    payload = _DOMAIN + canonical_json(body).encode("utf-8")
    return hmac.new(_secret(secret), payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class RuntimeFaultAttestation:
    schema: str
    attestation_id: str
    issuer_id: str
    key_id: str
    authority: str
    catalog_sha256: str
    scenario_id: str
    observation_sha256: str
    source_revision: str
    nonce: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.schema != _SCHEMA:
            raise ValueError(f"schema must be {_SCHEMA}")
        object.__setattr__(self, "attestation_id", _identifier(self.attestation_id, "attestation_id"))
        object.__setattr__(self, "issuer_id", _identifier(self.issuer_id, "issuer_id"))
        object.__setattr__(self, "key_id", _identifier(self.key_id, "key_id"))
        object.__setattr__(self, "authority", _authority(self.authority))
        object.__setattr__(self, "catalog_sha256", _sha256(self.catalog_sha256, "catalog_sha256"))
        object.__setattr__(self, "scenario_id", _identifier(self.scenario_id, "scenario_id"))
        object.__setattr__(
            self,
            "observation_sha256",
            _sha256(self.observation_sha256, "observation_sha256"),
        )
        object.__setattr__(self, "source_revision", _revision(self.source_revision, "source_revision"))
        object.__setattr__(self, "nonce", _identifier(self.nonce, "nonce"))
        object.__setattr__(self, "issued_at", _timestamp(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        issued = _parse_timestamp(self.issued_at)
        expires = _parse_timestamp(self.expires_at)
        if expires <= issued:
            raise ValueError("expires_at must be after issued_at")
        if expires - issued > _MAX_VALIDITY:
            raise ValueError("attestation validity exceeds seven days")
        object.__setattr__(
            self,
            "signature_sha256",
            _sha256(self.signature_sha256, "signature_sha256"),
        )

    def signing_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "attestation_id": self.attestation_id,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "authority": self.authority,
            "catalog_sha256": self.catalog_sha256,
            "scenario_id": self.scenario_id,
            "observation_sha256": self.observation_sha256,
            "source_revision": self.source_revision,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.signing_payload(), "signature_sha256": self.signature_sha256}

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeFaultAttestation":
        return cls(**_strict_payload(payload, cls, "runtime fault attestation"))


@dataclass(frozen=True)
class AttestedRuntimeFaultVerification:
    """Content-addressed result retaining the exact trust derivation."""

    fault_verification: RuntimeFaultVerification
    attestation_sha256s: tuple[str, ...]
    verified_at: str

    def __post_init__(self) -> None:
        rows = tuple(
            sorted(
                _sha256(value, f"attestation_sha256s[{index}]")
                for index, value in enumerate(self.attestation_sha256s)
            )
        )
        if len(rows) != len(set(rows)):
            raise ValueError("attestation digests must be unique")
        if len(rows) != len(self.fault_verification.trusted_observation_sha256s):
            raise ValueError(
                "attestation digests must map one-to-one to trusted observations"
            )
        object.__setattr__(self, "attestation_sha256s", rows)
        object.__setattr__(self, "verified_at", _timestamp(self.verified_at, "verified_at"))

    @property
    def closed(self) -> bool:
        return self.fault_verification.closed

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.fault_verification.blockers

    @property
    def trusted_observation_sha256s(self) -> tuple[str, ...]:
        return self.fault_verification.trusted_observation_sha256s

    def to_dict(self) -> dict[str, Any]:
        return {
            "fault_verification": self.fault_verification.to_dict(),
            "attestation_sha256s": list(self.attestation_sha256s),
            "verified_at": self.verified_at,
            "closed": self.closed,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def issue_runtime_fault_attestation(
    observation: RuntimeFaultObservation,
    *,
    catalog: RuntimeFaultCatalog,
    attestation_id: str,
    issuer_id: str,
    key_id: str,
    nonce: str,
    issued_at: datetime,
    expires_at: datetime,
    secret: bytes,
) -> RuntimeFaultAttestation:
    issued = _normalize_now(issued_at)
    expires = _normalize_now(expires_at)
    unsigned = RuntimeFaultAttestation(
        schema=_SCHEMA,
        attestation_id=attestation_id,
        issuer_id=issuer_id,
        key_id=key_id,
        authority=observation.authority,
        catalog_sha256=catalog.digest,
        scenario_id=observation.scenario_id,
        observation_sha256=observation.digest,
        source_revision=observation.source_revision,
        nonce=nonce,
        issued_at=issued.isoformat(timespec="microseconds"),
        expires_at=expires.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
    )
    return RuntimeFaultAttestation(
        **{
            **unsigned.signing_payload(),
            "signature_sha256": _signature(unsigned.signing_payload(), secret),
        }
    )


def verify_runtime_fault_attestation(
    attestation: RuntimeFaultAttestation,
    *,
    observation: RuntimeFaultObservation,
    catalog: RuntimeFaultCatalog,
    expected_source_revision: str,
    keyring: Mapping[tuple[str, str], bytes],
    issuer_authorities: Mapping[str, Sequence[str]],
    now: datetime,
) -> str:
    revision = _revision(expected_source_revision, "expected_source_revision")
    current = _normalize_now(now)
    expected = {
        "catalog_sha256": (attestation.catalog_sha256, catalog.digest),
        "scenario_id": (attestation.scenario_id, observation.scenario_id),
        "observation_sha256": (attestation.observation_sha256, observation.digest),
        "source_revision": (attestation.source_revision, revision),
        "observation_source_revision": (observation.source_revision, revision),
        "authority": (attestation.authority, observation.authority),
    }
    mismatches = sorted(name for name, (actual, wanted) in expected.items() if actual != wanted)
    if mismatches:
        raise RuntimeFaultAttestationBindingMismatch(
            "runtime fault attestation binding mismatch: " + ", ".join(mismatches)
        )

    allowed = issuer_authorities.get(attestation.issuer_id)
    if allowed is None:
        raise RuntimeFaultAttestationBindingMismatch("unknown fault-attestation issuer")
    if isinstance(allowed, (str, bytes)):
        raise RuntimeFaultAttestationBindingMismatch(
            "issuer authority policy must be an array"
        )
    try:
        normalized_allowed = frozenset(_authority(row, "issuer authority") for row in allowed)
    except ValueError as exc:
        raise RuntimeFaultAttestationBindingMismatch(
            "issuer authority policy is malformed"
        ) from exc
    if attestation.authority not in normalized_allowed:
        raise RuntimeFaultAttestationBindingMismatch(
            "issuer is not authorized for the observation authority class"
        )

    secret = keyring.get((attestation.issuer_id, attestation.key_id))
    if secret is None:
        raise RuntimeFaultAttestationSignatureError("unknown fault-attestation key")
    try:
        expected_signature = _signature(attestation.signing_payload(), secret)
    except ValueError as exc:
        raise RuntimeFaultAttestationSignatureError(
            "fault-attestation key is invalid"
        ) from exc
    if not hmac.compare_digest(attestation.signature_sha256, expected_signature):
        raise RuntimeFaultAttestationSignatureError(
            "fault-attestation signature mismatch"
        )

    issued = _parse_timestamp(attestation.issued_at)
    expires = _parse_timestamp(attestation.expires_at)
    observed = _parse_timestamp(observation.observed_at)
    if issued < observed:
        raise RuntimeFaultAttestationBindingMismatch(
            "fault attestation predates the retained observation"
        )
    if current < issued:
        raise RuntimeFaultAttestationExpired("fault attestation is not valid yet")
    if current >= expires:
        raise RuntimeFaultAttestationExpired("fault attestation has expired")
    return observation.digest


def verify_attested_runtime_fault_matrix(
    matrix: RuntimeFaultMatrix,
    *,
    catalog: RuntimeFaultCatalog,
    expected_source_revision: str,
    attestations: Sequence[RuntimeFaultAttestation],
    keyring: Mapping[tuple[str, str], bytes],
    issuer_authorities: Mapping[str, Sequence[str]],
    now: datetime,
) -> AttestedRuntimeFaultVerification:
    current = _normalize_now(now)
    if isinstance(attestations, (str, bytes)):
        raise ValueError("attestations must be an array")
    rows = tuple(attestations)
    attestation_ids = tuple(row.attestation_id for row in rows)
    nonces = tuple((row.issuer_id, row.key_id, row.nonce) for row in rows)
    scenario_ids = tuple(row.scenario_id for row in rows)
    if len(attestation_ids) != len(set(attestation_ids)):
        raise RuntimeFaultAttestationReplay("duplicate fault-attestation id")
    if len(nonces) != len(set(nonces)):
        raise RuntimeFaultAttestationReplay("duplicate issuer/key/nonce")
    if len(scenario_ids) != len(set(scenario_ids)):
        raise RuntimeFaultAttestationReplay(
            "multiple fault attestations target the same scenario"
        )

    observations = {row.scenario_id: row for row in matrix.observations}
    trusted: list[str] = []
    verified_attestations: list[str] = []
    for attestation in sorted(rows, key=lambda row: row.scenario_id):
        observation = observations.get(attestation.scenario_id)
        if observation is None:
            raise RuntimeFaultAttestationBindingMismatch(
                "fault attestation targets an observation absent from the matrix"
            )
        trusted.append(
            verify_runtime_fault_attestation(
                attestation,
                observation=observation,
                catalog=catalog,
                expected_source_revision=expected_source_revision,
                keyring=keyring,
                issuer_authorities=issuer_authorities,
                now=current,
            )
        )
        verified_attestations.append(attestation.digest)

    fault_verification = verify_runtime_fault_matrix(
        matrix,
        catalog=catalog,
        expected_source_revision=expected_source_revision,
        trusted_observation_digests=tuple(trusted),
    )
    return AttestedRuntimeFaultVerification(
        fault_verification=fault_verification,
        attestation_sha256s=tuple(verified_attestations),
        verified_at=current.isoformat(timespec="microseconds"),
    )


__all__ = [
    "AttestedRuntimeFaultVerification",
    "RuntimeFaultAttestation",
    "RuntimeFaultAttestationBindingMismatch",
    "RuntimeFaultAttestationError",
    "RuntimeFaultAttestationExpired",
    "RuntimeFaultAttestationReplay",
    "RuntimeFaultAttestationSignatureError",
    "issue_runtime_fault_attestation",
    "verify_attested_runtime_fault_matrix",
    "verify_runtime_fault_attestation",
]
