"""Authenticated guard-implementation manifest for repository-write evidence.

This preparatory layer authenticates a short-lived, revision- and
classification-bound manifest that maps guard-contract names to exact Daedalus
Python targets and source digests. It does not inspect source files or replay
guard semantics, so it cannot authenticate the complete evidence set, bind a
GateReport, or close Gate 0.
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

from daedalus.spine.envelope import canonical_json


_MANIFEST_SCHEMA = "daedalus-gate0-guard-implementation-manifest/1"
_REPORT_SCHEMA = "daedalus-gate0-guard-implementation-manifest-report/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_TARGET = re.compile(
    r"^daedalus(?:\.[A-Za-z_][A-Za-z0-9_]*)*:"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
_MAX_TTL = timedelta(hours=24)
_MAX_MANIFEST_BYTES = 1_048_576


class GuardImplementationManifestError(RuntimeError):
    """A manifest was malformed, stale, incomplete, or unauthenticated."""


class GuardImplementationManifestSignatureError(
    GuardImplementationManifestError
):
    """The selected authority key cannot authenticate the manifest."""


class GuardImplementationManifestBindingError(
    GuardImplementationManifestError
):
    """The manifest does not bind the expected revision and classification."""


def _strict_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GuardImplementationManifestError(
            f"{label} must be a canonical identifier"
        )
    return value


def _strict_contract(value: object, label: str) -> str:
    if not isinstance(value, str) or _CONTRACT.fullmatch(value) is None:
        raise GuardImplementationManifestError(
            f"{label} must be a canonical contract name"
        )
    return value


def _strict_target(value: object, label: str) -> str:
    if not isinstance(value, str) or _TARGET.fullmatch(value) is None:
        raise GuardImplementationManifestError(
            f"{label} must be a canonical Daedalus Python target"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GuardImplementationManifestError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise GuardImplementationManifestError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise GuardImplementationManifestError(
            f"{label} must be a strict integer"
        )
    return value


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise GuardImplementationManifestError(
            f"{label} must be a timestamp string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuardImplementationManifestError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GuardImplementationManifestError(
            f"{label} must include a timezone"
        )
    canonical = parsed.astimezone(timezone.utc)
    if canonical.isoformat(timespec="microseconds") != value:
        raise GuardImplementationManifestError(
            f"{label} must be canonical UTC microsecond ISO-8601"
        )
    return canonical


def _as_utc(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise GuardImplementationManifestError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif type(secret) is bytes:
        value = secret
    else:
        raise GuardImplementationManifestError(
            "authority secret must be bytes or text"
        )
    if len(value) < 32:
        raise GuardImplementationManifestError(
            "authority secret must contain at least 32 bytes"
        )
    return value


def _signature(signing_digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _require_exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if set(value) != required:
        raise GuardImplementationManifestError(
            f"{label} keys differ from the exact schema"
        )


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GuardImplementationManifestError(
                "manifest JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise GuardImplementationManifestError(
        f"manifest JSON contains non-finite number {value}"
    )


@dataclass(frozen=True)
class GuardImplementationRecord:
    contract: str
    implementation_target: str
    implementation_sha256: str

    def __post_init__(self) -> None:
        _strict_contract(self.contract, "contract")
        _strict_target(self.implementation_target, "implementation_target")
        _strict_sha(self.implementation_sha256, "implementation_sha256")

    def sort_key(self) -> tuple[str, str, str]:
        return (
            self.contract,
            self.implementation_target,
            self.implementation_sha256,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "contract": self.contract,
            "implementation_target": self.implementation_target,
            "implementation_sha256": self.implementation_sha256,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "GuardImplementationRecord":
        if not isinstance(value, Mapping):
            raise GuardImplementationManifestError(
                "guard implementation record must be an object"
            )
        _require_exact_keys(
            value,
            {"contract", "implementation_target", "implementation_sha256"},
            "guard implementation record",
        )
        return cls(
            contract=_strict_contract(value["contract"], "contract"),
            implementation_target=_strict_target(
                value["implementation_target"], "implementation_target"
            ),
            implementation_sha256=_strict_sha(
                value["implementation_sha256"], "implementation_sha256"
            ),
        )


@dataclass(frozen=True)
class GuardImplementationManifest:
    manifest_id: str
    authority_id: str
    authority_key_id: str
    source_revision: str
    classification_digest: str
    entries: tuple[GuardImplementationRecord, ...]
    entry_set_sha256: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("manifest_id", "authority_id", "authority_key_id"):
            _strict_identifier(getattr(self, field_name), field_name)
        _strict_revision(self.source_revision, "source_revision")
        _strict_sha(self.classification_digest, "classification_digest")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise GuardImplementationManifestError(
                "entries must be a non-empty immutable tuple"
            )
        if any(
            not isinstance(entry, GuardImplementationRecord)
            for entry in self.entries
        ):
            raise GuardImplementationManifestError("entries must be typed")
        if tuple(sorted(self.entries, key=GuardImplementationRecord.sort_key)) != self.entries:
            raise GuardImplementationManifestError(
                "entries must be canonically sorted"
            )
        if len({entry.contract for entry in self.entries}) != len(self.entries):
            raise GuardImplementationManifestError(
                "contract identities must be unique"
            )
        _strict_sha(self.entry_set_sha256, "entry_set_sha256")
        _strict_sha(self.signature_sha256, "signature_sha256")
        expected_set = hashlib.sha256(
            canonical_json([entry.to_dict() for entry in self.entries]).encode(
                "ascii"
            )
        ).hexdigest()
        if not hmac.compare_digest(self.entry_set_sha256, expected_set):
            raise GuardImplementationManifestError(
                "entry_set_sha256 does not bind the entries"
            )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise GuardImplementationManifestError(
                "expires_at must follow issued_at"
            )
        if expires - issued > _MAX_TTL:
            raise GuardImplementationManifestError(
                "manifest lifetime must not exceed 24 hours"
            )

    def _payload(self, *, signature_sha256: str) -> dict[str, object]:
        return {
            "schema": _MANIFEST_SCHEMA,
            "manifest_id": self.manifest_id,
            "authority_id": self.authority_id,
            "authority_key_id": self.authority_key_id,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "entries": [entry.to_dict() for entry in self.entries],
            "entry_set_sha256": self.entry_set_sha256,
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
        cls, value: Mapping[str, object]
    ) -> "GuardImplementationManifest":
        if not isinstance(value, Mapping):
            raise GuardImplementationManifestError(
                "manifest must be an object"
            )
        _require_exact_keys(
            value,
            {
                "schema",
                "manifest_id",
                "authority_id",
                "authority_key_id",
                "source_revision",
                "classification_digest",
                "entries",
                "entry_set_sha256",
                "issued_at",
                "expires_at",
                "signature_sha256",
            },
            "manifest",
        )
        if value["schema"] != _MANIFEST_SCHEMA:
            raise GuardImplementationManifestError(
                "manifest schema is unsupported"
            )
        entries_raw = value["entries"]
        if isinstance(entries_raw, (str, bytes)) or not isinstance(
            entries_raw, Sequence
        ):
            raise GuardImplementationManifestError(
                "entries must be an array"
            )
        return cls(
            manifest_id=_strict_identifier(value["manifest_id"], "manifest_id"),
            authority_id=_strict_identifier(value["authority_id"], "authority_id"),
            authority_key_id=_strict_identifier(
                value["authority_key_id"], "authority_key_id"
            ),
            source_revision=_strict_revision(
                value["source_revision"], "source_revision"
            ),
            classification_digest=_strict_sha(
                value["classification_digest"], "classification_digest"
            ),
            entries=tuple(
                GuardImplementationRecord.from_dict(entry)
                for entry in entries_raw
            ),
            entry_set_sha256=_strict_sha(
                value["entry_set_sha256"], "entry_set_sha256"
            ),
            issued_at=value["issued_at"],
            expires_at=value["expires_at"],
            signature_sha256=_strict_sha(
                value["signature_sha256"], "signature_sha256"
            ),
        )


@dataclass(frozen=True)
class GuardImplementationManifestReport:
    source_revision: str
    classification_digest: str
    manifest_digest: str
    manifest_id: str
    authority_id: str
    authority_key_id: str
    entry_count: int
    entry_set_sha256: str

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "manifest_digest",
            "entry_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        for field_name in ("manifest_id", "authority_id", "authority_key_id"):
            _strict_identifier(getattr(self, field_name), field_name)
        if _strict_int(self.entry_count, "entry_count") < 1:
            raise ValueError("entry_count must be positive")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "manifest_digest": self.manifest_digest,
            "manifest_id": self.manifest_id,
            "authority_id": self.authority_id,
            "authority_key_id": self.authority_key_id,
            "entry_count": self.entry_count,
            "entry_set_sha256": self.entry_set_sha256,
            "guard_manifest_authenticated": True,
            "guard_contract_semantics_verified": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "guard-implementation-manifest-authentication",
            "blockers": [
                "effect-lease-semantic-verification-missing",
                "gate-report-binding-missing",
                "guard-contract-semantic-replay-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
                "runtime-conformance-semantic-verification-missing",
                "source-anchor-chain-binding-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def issue_guard_implementation_manifest(
    entries: Sequence[GuardImplementationRecord],
    *,
    manifest_id: str,
    authority_id: str,
    authority_key_id: str,
    authority_secret: bytes | str,
    source_revision: str,
    classification_digest: str,
    issued_at: datetime,
    expires_at: datetime,
) -> GuardImplementationManifest:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise GuardImplementationManifestError(
            "entries must be a sequence"
        )
    if any(
        not isinstance(entry, GuardImplementationRecord)
        for entry in entries
    ):
        raise GuardImplementationManifestError("entries must be typed")
    canonical_entries = tuple(
        sorted(entries, key=GuardImplementationRecord.sort_key)
    )
    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    entry_set_sha256 = hashlib.sha256(
        canonical_json([entry.to_dict() for entry in canonical_entries]).encode(
            "ascii"
        )
    ).hexdigest()
    unsigned = GuardImplementationManifest(
        manifest_id=manifest_id,
        authority_id=authority_id,
        authority_key_id=authority_key_id,
        source_revision=_strict_revision(source_revision, "source_revision"),
        classification_digest=_strict_sha(
            classification_digest, "classification_digest"
        ),
        entries=canonical_entries,
        entry_set_sha256=entry_set_sha256,
        issued_at=issued.isoformat(timespec="microseconds"),
        expires_at=expires.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
    )
    return dataclasses.replace(
        unsigned,
        signature_sha256=_signature(
            unsigned.signing_digest,
            authority_secret,
        ),
    )


def parse_guard_implementation_manifest(
    raw: bytes,
) -> GuardImplementationManifest:
    if type(raw) is not bytes:
        raise GuardImplementationManifestError(
            "manifest wire must be exact bytes"
        )
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise GuardImplementationManifestError(
            "manifest exceeds the bounded wire size"
        )
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise GuardImplementationManifestError(
            "manifest wire encoding is invalid"
        )
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        canonical = canonical_json(document).encode("ascii")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        GuardImplementationManifestError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise GuardImplementationManifestError(
            "manifest wire is not strict canonical JSON"
        ) from exc
    if raw != canonical:
        raise GuardImplementationManifestError(
            "manifest wire is not canonical JSON"
        )
    if not isinstance(document, dict):
        raise GuardImplementationManifestError(
            "manifest wire must contain an object"
        )
    return GuardImplementationManifest.from_dict(document)


def verify_guard_implementation_manifest(
    manifest: GuardImplementationManifest,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_authority_id: str,
    current_revision: str,
    expected_classification_digest: str,
    now: datetime,
) -> GuardImplementationManifestReport:
    if not isinstance(manifest, GuardImplementationManifest):
        raise GuardImplementationManifestError(
            "manifest type is invalid"
        )
    revision = _strict_revision(current_revision, "current_revision")
    classification_digest = _strict_sha(
        expected_classification_digest,
        "expected_classification_digest",
    )
    authority_id = _strict_identifier(
        expected_authority_id, "expected_authority_id"
    )
    if not isinstance(keyring, Mapping):
        raise GuardImplementationManifestError(
            "keyring must be a mapping"
        )
    key = keyring.get((manifest.authority_id, manifest.authority_key_id))
    if key is None:
        raise GuardImplementationManifestSignatureError(
            "manifest authority key is unknown"
        )
    expected_signature = _signature(manifest.signing_digest, key)
    if not hmac.compare_digest(
        expected_signature,
        manifest.signature_sha256,
    ):
        raise GuardImplementationManifestSignatureError(
            "manifest signature is invalid"
        )
    if manifest.authority_id != authority_id:
        raise GuardImplementationManifestBindingError(
            "manifest authority differs from expectation"
        )
    if manifest.source_revision != revision:
        raise GuardImplementationManifestBindingError(
            "manifest source revision is stale"
        )
    if manifest.classification_digest != classification_digest:
        raise GuardImplementationManifestBindingError(
            "manifest classification digest is stale"
        )
    instant = _as_utc(now, "now")
    issued = _parse_utc(manifest.issued_at, "issued_at")
    expires = _parse_utc(manifest.expires_at, "expires_at")
    if instant < issued:
        raise GuardImplementationManifestBindingError(
            "manifest is not yet valid"
        )
    if instant >= expires:
        raise GuardImplementationManifestBindingError(
            "manifest is expired"
        )
    return GuardImplementationManifestReport(
        source_revision=revision,
        classification_digest=classification_digest,
        manifest_digest=manifest.digest,
        manifest_id=manifest.manifest_id,
        authority_id=manifest.authority_id,
        authority_key_id=manifest.authority_key_id,
        entry_count=len(manifest.entries),
        entry_set_sha256=manifest.entry_set_sha256,
    )


__all__ = [
    "GuardImplementationManifest",
    "GuardImplementationManifestBindingError",
    "GuardImplementationManifestError",
    "GuardImplementationManifestReport",
    "GuardImplementationManifestSignatureError",
    "GuardImplementationRecord",
    "issue_guard_implementation_manifest",
    "parse_guard_implementation_manifest",
    "verify_guard_implementation_manifest",
]
