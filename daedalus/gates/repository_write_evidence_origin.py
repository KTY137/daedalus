# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Authenticated origin bundle for repository-write evidence materialization.

The materialization layer proves exact CAS bytes and subject binding. This
module authenticates one complete materialization projection against an
externally provisioned collector key. It deliberately does not replay the
semantic authority behind Effect-Lease, runtime, checkout-disjointness, guard,
source-anchor, or retirement receipts and cannot bind or close Gate 0.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from daedalus.gates.repository_write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
)
from daedalus.spine.envelope import canonical_json


_SCHEMA = "daedalus-gate0-repository-write-evidence-origin-attestation/1"
_REPORT_SCHEMA = "daedalus-gate0-repository-write-evidence-origin-report/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_MAX_TTL = timedelta(hours=24)
_MAX_ATTESTATION_BYTES = 1_048_576


class RepositoryWriteEvidenceOriginError(RuntimeError):
    """Origin attestation was malformed, stale, incomplete, or unauthenticated."""


class RepositoryWriteEvidenceOriginSignatureError(
    RepositoryWriteEvidenceOriginError
):
    """The selected collector key cannot authenticate the attestation."""


class RepositoryWriteEvidenceOriginBindingError(
    RepositoryWriteEvidenceOriginError
):
    """The attestation does not bind the exact live materialization projection."""


def _strict_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be a canonical identifier"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be a timestamp string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must include a timezone"
        )
    canonical = parsed.astimezone(timezone.utc)
    if canonical.isoformat(timespec="microseconds") != value:
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be canonical UTC microsecond ISO-8601"
        )
    return canonical


def _as_utc(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RepositoryWriteEvidenceOriginError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif type(secret) is bytes:
        value = secret
    else:
        raise RepositoryWriteEvidenceOriginError(
            "collector secret must be bytes or text"
        )
    if len(value) < 32:
        raise RepositoryWriteEvidenceOriginError(
            "collector secret must contain at least 32 bytes"
        )
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def materialized_record_sha256(record: MaterializedEvidenceRecord) -> str:
    """Hash one exact typed materialized evidence record."""

    if not isinstance(record, MaterializedEvidenceRecord):
        raise RepositoryWriteEvidenceOriginError(
            "record digest requires a typed materialized record"
        )
    return hashlib.sha256(
        canonical_json(record.to_dict()).encode("ascii")
    ).hexdigest()


def _projection(
    materialization: RepositoryWriteEvidenceMaterializationReport,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], str]:
    if not isinstance(
        materialization,
        RepositoryWriteEvidenceMaterializationReport,
    ):
        raise RepositoryWriteEvidenceOriginError(
            "materialization report type is invalid"
        )
    if not materialization.materialization_complete:
        raise RepositoryWriteEvidenceOriginBindingError(
            "origin authentication requires complete non-empty materialization"
        )
    record_digests = tuple(
        sorted(
            materialized_record_sha256(record)
            for record in materialization.records
        )
    )
    blob_digests = tuple(
        sorted(record.blob_sha256 for record in materialization.records)
    )
    payload_digests = tuple(
        sorted(record.payload_sha256 for record in materialization.records)
    )
    if len(record_digests) != materialization.binding_count:
        raise RepositoryWriteEvidenceOriginBindingError(
            "materialization record count is inconsistent"
        )
    if len(set(record_digests)) != len(record_digests):
        raise RepositoryWriteEvidenceOriginBindingError(
            "materialization record identities are not unique"
        )
    if len(set(blob_digests)) != len(blob_digests):
        raise RepositoryWriteEvidenceOriginBindingError(
            "materialization blob identities are not unique"
        )
    record_set_sha256 = hashlib.sha256(
        canonical_json(
            {
                "record_sha256s": list(record_digests),
                "blob_sha256s": list(blob_digests),
                "payload_sha256s": list(payload_digests),
            }
        ).encode("ascii")
    ).hexdigest()
    return (
        record_digests,
        blob_digests,
        payload_digests,
        record_set_sha256,
    )


@dataclass(frozen=True)
class RepositoryWriteEvidenceOriginAttestation:
    """Short-lived external signature over one complete materialization."""

    attestation_id: str
    collector_id: str
    collector_key_id: str
    source_revision: str
    classification_digest: str
    materialization_digest: str
    binding_count: int
    record_sha256s: tuple[str, ...]
    blob_sha256s: tuple[str, ...]
    payload_sha256s: tuple[str, ...]
    record_set_sha256: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "attestation_id",
            "collector_id",
            "collector_key_id",
        ):
            _strict_identifier(getattr(self, field_name), field_name)
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "materialization_digest",
            "record_set_sha256",
            "signature_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        if type(self.binding_count) is not int or self.binding_count < 1:
            raise RepositoryWriteEvidenceOriginError(
                "binding_count must be a positive integer"
            )
        self._validate_digest_tuple(
            self.record_sha256s,
            "record_sha256s",
            unique=True,
        )
        self._validate_digest_tuple(
            self.blob_sha256s,
            "blob_sha256s",
            unique=True,
        )
        self._validate_digest_tuple(
            self.payload_sha256s,
            "payload_sha256s",
            unique=False,
        )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise RepositoryWriteEvidenceOriginError(
                "expires_at must follow issued_at"
            )
        if expires - issued > _MAX_TTL:
            raise RepositoryWriteEvidenceOriginError(
                "attestation lifetime must not exceed 24 hours"
            )
        expected_set = hashlib.sha256(
            canonical_json(
                {
                    "record_sha256s": list(self.record_sha256s),
                    "blob_sha256s": list(self.blob_sha256s),
                    "payload_sha256s": list(self.payload_sha256s),
                }
            ).encode("ascii")
        ).hexdigest()
        if not hmac.compare_digest(self.record_set_sha256, expected_set):
            raise RepositoryWriteEvidenceOriginError(
                "record_set_sha256 does not bind the retained evidence sets"
            )

    def _validate_digest_tuple(
        self,
        values: tuple[str, ...],
        label: str,
        *,
        unique: bool,
    ) -> None:
        if not isinstance(values, tuple):
            raise RepositoryWriteEvidenceOriginError(
                f"{label} must be an immutable tuple"
            )
        if tuple(sorted(values)) != values:
            raise RepositoryWriteEvidenceOriginError(
                f"{label} must be sorted"
            )
        if len(values) != self.binding_count:
            raise RepositoryWriteEvidenceOriginError(
                f"{label} must contain one digest per binding"
            )
        if unique and len(set(values)) != len(values):
            raise RepositoryWriteEvidenceOriginError(
                f"{label} must contain unique digests"
            )
        for value in values:
            _strict_sha(value, label)

    def _payload(self, *, signature_sha256: str) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "attestation_id": self.attestation_id,
            "collector_id": self.collector_id,
            "collector_key_id": self.collector_key_id,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "binding_count": self.binding_count,
            "record_sha256s": list(self.record_sha256s),
            "blob_sha256s": list(self.blob_sha256s),
            "payload_sha256s": list(self.payload_sha256s),
            "record_set_sha256": self.record_set_sha256,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature_sha256": signature_sha256,
        }

    @property
    def signing_digest(self) -> str:
        return hashlib.sha256(
            canonical_json(
                self._payload(signature_sha256="0" * 64)
            ).encode("ascii")
        ).hexdigest()

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self.to_dict()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return self._payload(signature_sha256=self.signature_sha256)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "RepositoryWriteEvidenceOriginAttestation":
        if not isinstance(payload, Mapping):
            raise RepositoryWriteEvidenceOriginError(
                "attestation payload must be an object"
            )
        expected = {
            "schema",
            "attestation_id",
            "collector_id",
            "collector_key_id",
            "source_revision",
            "classification_digest",
            "materialization_digest",
            "binding_count",
            "record_sha256s",
            "blob_sha256s",
            "payload_sha256s",
            "record_set_sha256",
            "issued_at",
            "expires_at",
            "signature_sha256",
        }
        if set(payload) != expected:
            raise RepositoryWriteEvidenceOriginError(
                "attestation keys differ from the exact schema"
            )
        if payload["schema"] != _SCHEMA:
            raise RepositoryWriteEvidenceOriginError(
                "attestation schema is unsupported"
            )
        arrays: dict[str, tuple[str, ...]] = {}
        for field_name in (
            "record_sha256s",
            "blob_sha256s",
            "payload_sha256s",
        ):
            values = payload[field_name]
            if isinstance(values, (str, bytes)) or not isinstance(
                values,
                Sequence,
            ):
                raise RepositoryWriteEvidenceOriginError(
                    f"{field_name} must be an array"
                )
            if any(not isinstance(value, str) for value in values):
                raise RepositoryWriteEvidenceOriginError(
                    f"{field_name} must contain strings"
                )
            arrays[field_name] = tuple(values)
        return cls(
            attestation_id=payload["attestation_id"],
            collector_id=payload["collector_id"],
            collector_key_id=payload["collector_key_id"],
            source_revision=payload["source_revision"],
            classification_digest=payload["classification_digest"],
            materialization_digest=payload["materialization_digest"],
            binding_count=payload["binding_count"],
            record_sha256s=arrays["record_sha256s"],
            blob_sha256s=arrays["blob_sha256s"],
            payload_sha256s=arrays["payload_sha256s"],
            record_set_sha256=payload["record_set_sha256"],
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            signature_sha256=payload["signature_sha256"],
        )


@dataclass(frozen=True)
class RepositoryWriteEvidenceOriginReport:
    """Authenticated-origin result that remains semantically untrusted."""

    source_revision: str
    classification_digest: str
    materialization_digest: str
    attestation_digest: str
    attestation_id: str
    collector_id: str
    collector_key_id: str
    binding_count: int
    record_set_sha256: str
    issued_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "materialization_digest",
            "attestation_digest",
            "record_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        for field_name in (
            "attestation_id",
            "collector_id",
            "collector_key_id",
        ):
            _strict_identifier(getattr(self, field_name), field_name)
        if type(self.binding_count) is not int or self.binding_count < 1:
            raise RepositoryWriteEvidenceOriginError(
                "binding_count must be positive"
            )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued or expires - issued > _MAX_TTL:
            raise RepositoryWriteEvidenceOriginError(
                "origin report time window is invalid"
            )

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "attestation_digest": self.attestation_digest,
            "attestation_id": self.attestation_id,
            "collector_id": self.collector_id,
            "collector_key_id": self.collector_key_id,
            "binding_count": self.binding_count,
            "record_set_sha256": self.record_set_sha256,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "origin_authenticated": True,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-evidence-origin-authentication",
            "blockers": [
                "external-evidence-semantic-verification-missing",
                "gate-report-binding-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def issue_repository_write_evidence_origin_attestation(
    materialization: RepositoryWriteEvidenceMaterializationReport,
    *,
    attestation_id: str,
    collector_id: str,
    collector_key_id: str,
    collector_secret: bytes | str,
    issued_at: datetime,
    expires_at: datetime,
) -> RepositoryWriteEvidenceOriginAttestation:
    """Issue one short-lived attestation for a complete materialization report."""

    (
        record_digests,
        blob_digests,
        payload_digests,
        record_set_sha256,
    ) = _projection(materialization)
    instant = _as_utc(issued_at, "issued_at")
    expiry = _as_utc(expires_at, "expires_at")
    placeholder = RepositoryWriteEvidenceOriginAttestation(
        attestation_id=attestation_id,
        collector_id=collector_id,
        collector_key_id=collector_key_id,
        source_revision=materialization.source_revision,
        classification_digest=materialization.classification_digest,
        materialization_digest=materialization.digest,
        binding_count=materialization.binding_count,
        record_sha256s=record_digests,
        blob_sha256s=blob_digests,
        payload_sha256s=payload_digests,
        record_set_sha256=record_set_sha256,
        issued_at=instant.isoformat(timespec="microseconds"),
        expires_at=expiry.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            collector_secret,
        ),
    )


def parse_repository_write_evidence_origin_attestation(
    raw: bytes,
) -> RepositoryWriteEvidenceOriginAttestation:
    """Parse exact canonical bytes without duplicate-key ambiguity."""

    if type(raw) is not bytes:
        raise RepositoryWriteEvidenceOriginError(
            "attestation input must be exact bytes"
        )
    if len(raw) > _MAX_ATTESTATION_BYTES:
        raise RepositoryWriteEvidenceOriginError(
            "attestation exceeds the bounded input size"
        )
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise RepositoryWriteEvidenceOriginError(
            "attestation encoding is invalid"
        )
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        canonical = canonical_json(payload).encode("ascii")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RepositoryWriteEvidenceOriginError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepositoryWriteEvidenceOriginError(
            "attestation is not strict canonical JSON"
        ) from exc
    if raw != canonical:
        raise RepositoryWriteEvidenceOriginError(
            "attestation bytes are not canonical JSON"
        )
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise RepositoryWriteEvidenceOriginError(
            "attestation document must be an object"
        )
    return RepositoryWriteEvidenceOriginAttestation.from_dict(payload)


def verify_repository_write_evidence_origin(
    attestation: RepositoryWriteEvidenceOriginAttestation,
    materialization: RepositoryWriteEvidenceMaterializationReport,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    current_revision: str,
    now: datetime,
) -> RepositoryWriteEvidenceOriginReport:
    """Authenticate the collector and exact live materialization projection."""

    if not isinstance(attestation, RepositoryWriteEvidenceOriginAttestation):
        raise RepositoryWriteEvidenceOriginError(
            "attestation type is invalid"
        )
    if not isinstance(keyring, Mapping):
        raise RepositoryWriteEvidenceOriginError(
            "keyring must be a mapping"
        )
    collector = _strict_identifier(
        expected_collector_id,
        "expected_collector_id",
    )
    revision = _strict_revision(current_revision, "current_revision")
    secret = keyring.get(
        (attestation.collector_id, attestation.collector_key_id)
    )
    if secret is None:
        raise RepositoryWriteEvidenceOriginSignatureError(
            "collector key is unknown"
        )
    expected_signature = _signature(attestation.signing_digest, secret)
    if not hmac.compare_digest(
        attestation.signature_sha256,
        expected_signature,
    ):
        raise RepositoryWriteEvidenceOriginSignatureError(
            "collector signature mismatch"
        )

    instant = _as_utc(now, "now")
    issued = _parse_utc(attestation.issued_at, "issued_at")
    expires = _parse_utc(attestation.expires_at, "expires_at")
    if issued > instant:
        raise RepositoryWriteEvidenceOriginBindingError(
            "attestation is from the future"
        )
    if instant >= expires:
        raise RepositoryWriteEvidenceOriginBindingError(
            "attestation is expired"
        )
    (
        record_digests,
        blob_digests,
        payload_digests,
        record_set_sha256,
    ) = _projection(materialization)
    comparisons = {
        "collector_id": (attestation.collector_id, collector),
        "source_revision": (attestation.source_revision, revision),
        "materialization_source_revision": (
            materialization.source_revision,
            revision,
        ),
        "classification_digest": (
            attestation.classification_digest,
            materialization.classification_digest,
        ),
        "materialization_digest": (
            attestation.materialization_digest,
            materialization.digest,
        ),
        "binding_count": (
            attestation.binding_count,
            materialization.binding_count,
        ),
        "record_sha256s": (
            attestation.record_sha256s,
            record_digests,
        ),
        "blob_sha256s": (
            attestation.blob_sha256s,
            blob_digests,
        ),
        "payload_sha256s": (
            attestation.payload_sha256s,
            payload_digests,
        ),
        "record_set_sha256": (
            attestation.record_set_sha256,
            record_set_sha256,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteEvidenceOriginBindingError(
            "origin attestation binding mismatch: " + ", ".join(mismatches)
        )
    return RepositoryWriteEvidenceOriginReport(
        source_revision=revision,
        classification_digest=materialization.classification_digest,
        materialization_digest=materialization.digest,
        attestation_digest=attestation.digest,
        attestation_id=attestation.attestation_id,
        collector_id=collector,
        collector_key_id=attestation.collector_key_id,
        binding_count=materialization.binding_count,
        record_set_sha256=record_set_sha256,
        issued_at=attestation.issued_at,
        expires_at=attestation.expires_at,
    )


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteEvidenceOriginError(
                "attestation contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise RepositoryWriteEvidenceOriginError(
        f"attestation contains non-finite number {value}"
    )


__all__ = [
    "RepositoryWriteEvidenceOriginAttestation",
    "RepositoryWriteEvidenceOriginBindingError",
    "RepositoryWriteEvidenceOriginError",
    "RepositoryWriteEvidenceOriginReport",
    "RepositoryWriteEvidenceOriginSignatureError",
    "issue_repository_write_evidence_origin_attestation",
    "materialized_record_sha256",
    "parse_repository_write_evidence_origin_attestation",
    "verify_repository_write_evidence_origin",
]
