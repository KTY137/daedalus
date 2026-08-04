"""Authenticate externally produced repository-write guard behavior results.

The attestation binds one exact structural report, harness digest, runtime
manifest digest, and a non-vacuous allow/refuse case set for every guard
contract. Authentication is not execution: this module does not import or call
a guard, replay a harness, prove isolation, or establish runtime conformance.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from daedalus.gates.repository_write_guard_structure import (
    RepositoryWriteGuardStructureReport,
)
from daedalus.spine.envelope import canonical_json


_ATTESTATION_SCHEMA = "daedalus-gate0-guard-behavior-attestation/1"
_REPORT_SCHEMA = "daedalus-gate0-guard-behavior-attestation-report/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_OUTCOMES = frozenset({"allow", "refuse"})
_MAX_TTL = timedelta(hours=24)
_MAX_ATTESTATION_BYTES = 1_048_576


class GuardBehaviorAttestationError(RuntimeError):
    """The attestation was malformed, stale, incomplete, or unauthenticated."""


class GuardBehaviorAttestationSignatureError(GuardBehaviorAttestationError):
    """The selected external authority key cannot authenticate the result."""


class GuardBehaviorAttestationBindingError(GuardBehaviorAttestationError):
    """The result does not bind the expected exact-head subject."""


def _strict_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GuardBehaviorAttestationError(
            f"{label} must be a canonical identifier"
        )
    return value


def _strict_contract(value: object, label: str) -> str:
    if not isinstance(value, str) or _CONTRACT.fullmatch(value) is None:
        raise GuardBehaviorAttestationError(
            f"{label} must be a canonical contract name"
        )
    return value


def _strict_case_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _CASE_ID.fullmatch(value) is None:
        raise GuardBehaviorAttestationError(
            f"{label} must be a canonical case identifier"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GuardBehaviorAttestationError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise GuardBehaviorAttestationError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise GuardBehaviorAttestationError(
            f"{label} must be a strict integer"
        )
    return value


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise GuardBehaviorAttestationError(
            f"{label} must be a timestamp string"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GuardBehaviorAttestationError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GuardBehaviorAttestationError(
            f"{label} must include a timezone"
        )
    canonical = parsed.astimezone(timezone.utc)
    if canonical.isoformat(timespec="microseconds") != value:
        raise GuardBehaviorAttestationError(
            f"{label} must be canonical UTC microsecond ISO-8601"
        )
    return canonical


def _as_utc(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise GuardBehaviorAttestationError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    if isinstance(secret, str):
        value = secret.encode("utf-8")
    elif type(secret) is bytes:
        value = secret
    else:
        raise GuardBehaviorAttestationError(
            "authority secret must be bytes or text"
        )
    if len(value) < 32:
        raise GuardBehaviorAttestationError(
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
        raise GuardBehaviorAttestationError(
            f"{label} keys differ from the exact schema"
        )


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GuardBehaviorAttestationError(
                "attestation JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise GuardBehaviorAttestationError(
        f"attestation JSON contains non-finite number {value}"
    )


@dataclass(frozen=True)
class GuardBehaviorCaseResult:
    contract: str
    case_id: str
    vector_sha256: str
    expected_outcome: str
    observed_outcome: str
    transcript_sha256: str
    result_sha256: str

    def __post_init__(self) -> None:
        _strict_contract(self.contract, "contract")
        _strict_case_id(self.case_id, "case_id")
        _strict_sha(self.vector_sha256, "vector_sha256")
        if self.expected_outcome not in _OUTCOMES:
            raise GuardBehaviorAttestationError(
                "expected_outcome must be allow or refuse"
            )
        if self.observed_outcome not in _OUTCOMES:
            raise GuardBehaviorAttestationError(
                "observed_outcome must be allow or refuse"
            )
        _strict_sha(self.transcript_sha256, "transcript_sha256")
        _strict_sha(self.result_sha256, "result_sha256")
        expected = hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()
        if not hmac.compare_digest(self.result_sha256, expected):
            raise GuardBehaviorAttestationError(
                "result_sha256 does not bind the case result"
            )

    def _payload(self) -> dict[str, str]:
        return {
            "contract": self.contract,
            "case_id": self.case_id,
            "vector_sha256": self.vector_sha256,
            "expected_outcome": self.expected_outcome,
            "observed_outcome": self.observed_outcome,
            "transcript_sha256": self.transcript_sha256,
        }

    def sort_key(self) -> tuple[str, str]:
        return (self.contract, self.case_id)

    def to_dict(self) -> dict[str, str]:
        return {**self._payload(), "result_sha256": self.result_sha256}

    @classmethod
    def create(
        cls,
        *,
        contract: str,
        case_id: str,
        vector_sha256: str,
        expected_outcome: str,
        observed_outcome: str,
        transcript_sha256: str,
    ) -> "GuardBehaviorCaseResult":
        payload = {
            "contract": contract,
            "case_id": case_id,
            "vector_sha256": vector_sha256,
            "expected_outcome": expected_outcome,
            "observed_outcome": observed_outcome,
            "transcript_sha256": transcript_sha256,
        }
        return cls(
            **payload,
            result_sha256=hashlib.sha256(
                canonical_json(payload).encode("ascii")
            ).hexdigest(),
        )

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "GuardBehaviorCaseResult":
        if not isinstance(value, Mapping):
            raise GuardBehaviorAttestationError(
                "case result must be an object"
            )
        _require_exact_keys(
            value,
            {
                "contract",
                "case_id",
                "vector_sha256",
                "expected_outcome",
                "observed_outcome",
                "transcript_sha256",
                "result_sha256",
            },
            "case result",
        )
        return cls(
            contract=_strict_contract(value["contract"], "contract"),
            case_id=_strict_case_id(value["case_id"], "case_id"),
            vector_sha256=_strict_sha(
                value["vector_sha256"], "vector_sha256"
            ),
            expected_outcome=value["expected_outcome"],
            observed_outcome=value["observed_outcome"],
            transcript_sha256=_strict_sha(
                value["transcript_sha256"], "transcript_sha256"
            ),
            result_sha256=_strict_sha(
                value["result_sha256"], "result_sha256"
            ),
        )


@dataclass(frozen=True)
class GuardBehaviorAttestation:
    attestation_id: str
    authority_id: str
    authority_key_id: str
    source_revision: str
    classification_digest: str
    guard_structure_report_digest: str
    guard_structure_record_set_sha256: str
    harness_id: str
    harness_sha256: str
    runtime_manifest_digest: str
    cases: tuple[GuardBehaviorCaseResult, ...]
    case_set_sha256: str
    issued_at: str
    expires_at: str
    signature_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "attestation_id",
            "authority_id",
            "authority_key_id",
            "harness_id",
        ):
            _strict_identifier(getattr(self, field_name), field_name)
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "guard_structure_report_digest",
            "guard_structure_record_set_sha256",
            "harness_sha256",
            "runtime_manifest_digest",
            "case_set_sha256",
            "signature_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        if not isinstance(self.cases, tuple) or not self.cases:
            raise GuardBehaviorAttestationError(
                "cases must be a non-empty immutable tuple"
            )
        if any(
            not isinstance(case, GuardBehaviorCaseResult)
            for case in self.cases
        ):
            raise GuardBehaviorAttestationError("cases must be typed")
        if tuple(sorted(self.cases, key=GuardBehaviorCaseResult.sort_key)) != self.cases:
            raise GuardBehaviorAttestationError(
                "cases must be canonically sorted"
            )
        if len({case.sort_key() for case in self.cases}) != len(self.cases):
            raise GuardBehaviorAttestationError(
                "contract and case identities must be unique"
            )
        expected_set = hashlib.sha256(
            canonical_json([case.to_dict() for case in self.cases]).encode(
                "ascii"
            )
        ).hexdigest()
        if not hmac.compare_digest(self.case_set_sha256, expected_set):
            raise GuardBehaviorAttestationError(
                "case_set_sha256 does not bind the cases"
            )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise GuardBehaviorAttestationError(
                "expires_at must follow issued_at"
            )
        if expires - issued > _MAX_TTL:
            raise GuardBehaviorAttestationError(
                "attestation lifetime must not exceed 24 hours"
            )

    def _payload(self, *, signature_sha256: str) -> dict[str, object]:
        return {
            "schema": _ATTESTATION_SCHEMA,
            "attestation_id": self.attestation_id,
            "authority_id": self.authority_id,
            "authority_key_id": self.authority_key_id,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "guard_structure_report_digest": self.guard_structure_report_digest,
            "guard_structure_record_set_sha256": self.guard_structure_record_set_sha256,
            "harness_id": self.harness_id,
            "harness_sha256": self.harness_sha256,
            "runtime_manifest_digest": self.runtime_manifest_digest,
            "cases": [case.to_dict() for case in self.cases],
            "case_set_sha256": self.case_set_sha256,
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
    ) -> "GuardBehaviorAttestation":
        if not isinstance(value, Mapping):
            raise GuardBehaviorAttestationError(
                "attestation must be an object"
            )
        _require_exact_keys(
            value,
            {
                "schema",
                "attestation_id",
                "authority_id",
                "authority_key_id",
                "source_revision",
                "classification_digest",
                "guard_structure_report_digest",
                "guard_structure_record_set_sha256",
                "harness_id",
                "harness_sha256",
                "runtime_manifest_digest",
                "cases",
                "case_set_sha256",
                "issued_at",
                "expires_at",
                "signature_sha256",
            },
            "attestation",
        )
        if value["schema"] != _ATTESTATION_SCHEMA:
            raise GuardBehaviorAttestationError(
                "attestation schema is unsupported"
            )
        cases_raw = value["cases"]
        if isinstance(cases_raw, (str, bytes)) or not isinstance(
            cases_raw, Sequence
        ):
            raise GuardBehaviorAttestationError("cases must be an array")
        return cls(
            attestation_id=_strict_identifier(
                value["attestation_id"], "attestation_id"
            ),
            authority_id=_strict_identifier(
                value["authority_id"], "authority_id"
            ),
            authority_key_id=_strict_identifier(
                value["authority_key_id"], "authority_key_id"
            ),
            source_revision=_strict_revision(
                value["source_revision"], "source_revision"
            ),
            classification_digest=_strict_sha(
                value["classification_digest"], "classification_digest"
            ),
            guard_structure_report_digest=_strict_sha(
                value["guard_structure_report_digest"],
                "guard_structure_report_digest",
            ),
            guard_structure_record_set_sha256=_strict_sha(
                value["guard_structure_record_set_sha256"],
                "guard_structure_record_set_sha256",
            ),
            harness_id=_strict_identifier(value["harness_id"], "harness_id"),
            harness_sha256=_strict_sha(
                value["harness_sha256"], "harness_sha256"
            ),
            runtime_manifest_digest=_strict_sha(
                value["runtime_manifest_digest"], "runtime_manifest_digest"
            ),
            cases=tuple(
                GuardBehaviorCaseResult.from_dict(case)
                for case in cases_raw
            ),
            case_set_sha256=_strict_sha(
                value["case_set_sha256"], "case_set_sha256"
            ),
            issued_at=value["issued_at"],
            expires_at=value["expires_at"],
            signature_sha256=_strict_sha(
                value["signature_sha256"], "signature_sha256"
            ),
        )


@dataclass(frozen=True)
class GuardBehaviorAttestationReport:
    source_revision: str
    classification_digest: str
    guard_structure_report_digest: str
    guard_structure_record_set_sha256: str
    attestation_digest: str
    attestation_id: str
    authority_id: str
    authority_key_id: str
    harness_id: str
    harness_sha256: str
    runtime_manifest_digest: str
    contract_count: int
    case_count: int
    case_set_sha256: str

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "guard_structure_report_digest",
            "guard_structure_record_set_sha256",
            "attestation_digest",
            "harness_sha256",
            "runtime_manifest_digest",
            "case_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        for field_name in (
            "attestation_id",
            "authority_id",
            "authority_key_id",
            "harness_id",
        ):
            _strict_identifier(getattr(self, field_name), field_name)
        if _strict_int(self.contract_count, "contract_count") < 1:
            raise ValueError("contract_count must be positive")
        if _strict_int(self.case_count, "case_count") < 2:
            raise ValueError("case_count must be at least two")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "guard_structure_report_digest": self.guard_structure_report_digest,
            "guard_structure_record_set_sha256": self.guard_structure_record_set_sha256,
            "attestation_digest": self.attestation_digest,
            "attestation_id": self.attestation_id,
            "authority_id": self.authority_id,
            "authority_key_id": self.authority_key_id,
            "harness_id": self.harness_id,
            "harness_sha256": self.harness_sha256,
            "runtime_manifest_digest": self.runtime_manifest_digest,
            "contract_count": self.contract_count,
            "case_count": self.case_count,
            "case_set_sha256": self.case_set_sha256,
            "guard_behavior_attestation_authenticated": True,
            "positive_and_negative_vectors_complete": True,
            "guard_execution_replayed": False,
            "guard_contract_semantics_verified": False,
            "runtime_conformance_verified": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-guard-behavior-attestation",
            "blockers": [
                "effect-lease-semantic-verification-missing",
                "gate-report-binding-missing",
                "guard-behavior-harness-replay-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
                "runtime-conformance-semantic-verification-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def issue_guard_behavior_attestation(
    cases: Sequence[GuardBehaviorCaseResult],
    *,
    attestation_id: str,
    authority_id: str,
    authority_key_id: str,
    authority_secret: bytes | str,
    source_revision: str,
    classification_digest: str,
    guard_structure_report_digest: str,
    guard_structure_record_set_sha256: str,
    harness_id: str,
    harness_sha256: str,
    runtime_manifest_digest: str,
    issued_at: datetime,
    expires_at: datetime,
) -> GuardBehaviorAttestation:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise GuardBehaviorAttestationError("cases must be a sequence")
    if any(not isinstance(case, GuardBehaviorCaseResult) for case in cases):
        raise GuardBehaviorAttestationError("cases must be typed")
    canonical_cases = tuple(
        sorted(cases, key=GuardBehaviorCaseResult.sort_key)
    )
    issued = _as_utc(issued_at, "issued_at")
    expires = _as_utc(expires_at, "expires_at")
    case_set_sha256 = hashlib.sha256(
        canonical_json([case.to_dict() for case in canonical_cases]).encode(
            "ascii"
        )
    ).hexdigest()
    unsigned = GuardBehaviorAttestation(
        attestation_id=attestation_id,
        authority_id=authority_id,
        authority_key_id=authority_key_id,
        source_revision=source_revision,
        classification_digest=classification_digest,
        guard_structure_report_digest=guard_structure_report_digest,
        guard_structure_record_set_sha256=guard_structure_record_set_sha256,
        harness_id=harness_id,
        harness_sha256=harness_sha256,
        runtime_manifest_digest=runtime_manifest_digest,
        cases=canonical_cases,
        case_set_sha256=case_set_sha256,
        issued_at=issued.isoformat(timespec="microseconds"),
        expires_at=expires.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
    )
    return GuardBehaviorAttestation(
        **{
            **unsigned.__dict__,
            "signature_sha256": _signature(
                unsigned.signing_digest, authority_secret
            ),
        }
    )


def parse_guard_behavior_attestation(raw: bytes) -> GuardBehaviorAttestation:
    if type(raw) is not bytes:
        raise GuardBehaviorAttestationError(
            "attestation wire must be exact bytes"
        )
    if len(raw) > _MAX_ATTESTATION_BYTES:
        raise GuardBehaviorAttestationError(
            "attestation exceeds the bounded wire size"
        )
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise GuardBehaviorAttestationError(
            "attestation wire encoding is invalid"
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
        GuardBehaviorAttestationError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise GuardBehaviorAttestationError(
            "attestation wire is not strict canonical JSON"
        ) from exc
    if raw != canonical:
        raise GuardBehaviorAttestationError(
            "attestation wire is not canonical JSON"
        )
    if not isinstance(document, dict):
        raise GuardBehaviorAttestationError(
            "attestation wire must contain an object"
        )
    return GuardBehaviorAttestation.from_dict(document)


def verify_guard_behavior_attestation(
    attestation: GuardBehaviorAttestation,
    structure_report: RepositoryWriteGuardStructureReport,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_authority_id: str,
    current_revision: str,
    expected_harness_id: str,
    expected_harness_sha256: str,
    expected_runtime_manifest_digest: str,
    now: datetime,
) -> GuardBehaviorAttestationReport:
    if not isinstance(attestation, GuardBehaviorAttestation):
        raise GuardBehaviorAttestationError("attestation type is invalid")
    if not isinstance(structure_report, RepositoryWriteGuardStructureReport):
        raise GuardBehaviorAttestationError(
            "guard structure report type is invalid"
        )
    revision = _strict_revision(current_revision, "current_revision")
    authority_id = _strict_identifier(
        expected_authority_id, "expected_authority_id"
    )
    harness_id = _strict_identifier(
        expected_harness_id, "expected_harness_id"
    )
    harness_sha256 = _strict_sha(
        expected_harness_sha256, "expected_harness_sha256"
    )
    runtime_manifest_digest = _strict_sha(
        expected_runtime_manifest_digest,
        "expected_runtime_manifest_digest",
    )
    if not isinstance(keyring, Mapping):
        raise GuardBehaviorAttestationError("keyring must be a mapping")
    key = keyring.get(
        (attestation.authority_id, attestation.authority_key_id)
    )
    if key is None:
        raise GuardBehaviorAttestationSignatureError(
            "attestation authority key is unknown"
        )
    expected_signature = _signature(attestation.signing_digest, key)
    if not hmac.compare_digest(
        expected_signature, attestation.signature_sha256
    ):
        raise GuardBehaviorAttestationSignatureError(
            "attestation signature is invalid"
        )

    exact_bindings = {
        "authority_id": (attestation.authority_id, authority_id),
        "source_revision": (attestation.source_revision, revision),
        "classification_digest": (
            attestation.classification_digest,
            structure_report.classification_digest,
        ),
        "guard_structure_report_digest": (
            attestation.guard_structure_report_digest,
            structure_report.digest,
        ),
        "guard_structure_record_set_sha256": (
            attestation.guard_structure_record_set_sha256,
            structure_report.record_set_sha256,
        ),
        "harness_id": (attestation.harness_id, harness_id),
        "harness_sha256": (
            attestation.harness_sha256,
            harness_sha256,
        ),
        "runtime_manifest_digest": (
            attestation.runtime_manifest_digest,
            runtime_manifest_digest,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in exact_bindings.items()
        if actual != expected
    )
    if mismatches:
        raise GuardBehaviorAttestationBindingError(
            "guard behavior attestation binding mismatch: "
            + ", ".join(mismatches)
        )
    if structure_report.source_revision != revision:
        raise GuardBehaviorAttestationBindingError(
            "guard structure report source revision is stale"
        )
    instant = _as_utc(now, "now")
    issued = _parse_utc(attestation.issued_at, "issued_at")
    expires = _parse_utc(attestation.expires_at, "expires_at")
    if instant < issued:
        raise GuardBehaviorAttestationBindingError(
            "attestation is not yet valid"
        )
    if instant >= expires:
        raise GuardBehaviorAttestationBindingError(
            "attestation is expired"
        )

    required_contracts = {
        record.contract for record in structure_report.records
    }
    if not required_contracts:
        raise GuardBehaviorAttestationBindingError(
            "guard structure report has no contracts"
        )
    case_contracts = {case.contract for case in attestation.cases}
    if case_contracts != required_contracts:
        raise GuardBehaviorAttestationBindingError(
            "attestation contract set differs from guard structure"
        )
    for contract in sorted(required_contracts):
        contract_cases = tuple(
            case for case in attestation.cases if case.contract == contract
        )
        expected_outcomes = {
            case.expected_outcome for case in contract_cases
        }
        if expected_outcomes != _OUTCOMES:
            raise GuardBehaviorAttestationBindingError(
                f"guard contract {contract} lacks allow/refuse coverage"
            )
        if any(
            case.observed_outcome != case.expected_outcome
            for case in contract_cases
        ):
            raise GuardBehaviorAttestationBindingError(
                f"guard contract {contract} has a failed case"
            )

    return GuardBehaviorAttestationReport(
        source_revision=revision,
        classification_digest=structure_report.classification_digest,
        guard_structure_report_digest=structure_report.digest,
        guard_structure_record_set_sha256=structure_report.record_set_sha256,
        attestation_digest=attestation.digest,
        attestation_id=attestation.attestation_id,
        authority_id=attestation.authority_id,
        authority_key_id=attestation.authority_key_id,
        harness_id=attestation.harness_id,
        harness_sha256=attestation.harness_sha256,
        runtime_manifest_digest=attestation.runtime_manifest_digest,
        contract_count=len(required_contracts),
        case_count=len(attestation.cases),
        case_set_sha256=attestation.case_set_sha256,
    )


__all__ = [
    "GuardBehaviorAttestation",
    "GuardBehaviorAttestationBindingError",
    "GuardBehaviorAttestationError",
    "GuardBehaviorAttestationReport",
    "GuardBehaviorAttestationSignatureError",
    "GuardBehaviorCaseResult",
    "issue_guard_behavior_attestation",
    "parse_guard_behavior_attestation",
    "verify_guard_behavior_attestation",
]
