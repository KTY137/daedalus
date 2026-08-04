"""Semantic replay of repository-write runtime-conformance evidence.

This verifier extends the authenticated repository-write guard-structure chain
with the existing live-runtime trust authority.  Every production-reachable
surface must be centrally guarded, retain exactly one runtime-conformance
evidence binding, and resolve to one exact typed runtime subject whose envelope
is present as an active authenticated record in the persisted trust ledger.

The verifier is deliberately read-only with respect to the trust ledger: it
uses the public audit projection and never calls admission, quarantine, or
lease issuance.  It proves the retained runtime receipt and all eight canonical
vendor-neutral checks are current, passed, revision-bound, envelope-bound, and
backed by an active persisted trust record.  It does not yet semantically replay
effect leases, checkout disjointness, retirement, or guard behavior, and cannot
bind or close Gate 0.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from daedalus.gates.guard_implementation_manifest import (
    GuardImplementationManifest,
)
from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
)
from daedalus.gates.repository_write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_evidence_origin import (
    RepositoryWriteEvidenceOriginAttestation,
)
from daedalus.gates.repository_write_guard_structure import (
    RepositoryWriteGuardStructureReport,
    verify_repository_write_guard_structure,
)
from daedalus.runtimes.profiles import (
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
)
from daedalus.runtimes.trust import verify_production_runtime_envelope
from daedalus.runtimes.trust_store import (
    RuntimeTrustLedger,
    RuntimeTrustRecord,
    RuntimeTrustStoreError,
)
from daedalus.schemas import (
    RuntimeConformanceReceipt,
    RuntimeManifest,
)
from daedalus.spine.envelope import canonical_json


_REPORT_SCHEMA = "daedalus-gate0-repository-write-runtime-conformance/1"
_EVIDENCE_SCHEMA = "daedalus-gate0-repository-write-evidence-object/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CAS_LOCATOR = re.compile(r"^cas:sha256:[0-9a-f]{64}$")
_RUNTIME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class RepositoryWriteRuntimeConformanceError(RuntimeError):
    """Runtime-conformance replay was malformed, stale, or incomplete."""


class RepositoryWriteRuntimeConformanceBindingError(
    RepositoryWriteRuntimeConformanceError
):
    """Authenticated runtime and repository-write subjects do not agree."""


class RepositoryWriteRuntimeConformancePayloadError(
    RepositoryWriteRuntimeConformanceError
):
    """A materialized runtime-conformance payload cannot be replayed exactly."""


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise RepositoryWriteRuntimeConformanceError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryWriteRuntimeConformanceError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_runtime_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _RUNTIME_ID.fullmatch(value) is None:
        raise RepositoryWriteRuntimeConformanceError(
            f"{label} must be a canonical runtime identifier"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteRuntimeConformanceError(
            f"{label} must be a strict integer"
        )
    return value


def _as_utc(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RepositoryWriteRuntimeConformanceError(
            f"{label} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise RepositoryWriteRuntimeConformanceBindingError(
            f"{label} must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RepositoryWriteRuntimeConformanceBindingError(
            f"{label} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _snapshot_bytes(blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(blobs, Mapping):
        raise RepositoryWriteRuntimeConformanceError(
            "blobs must be a mapping"
        )
    try:
        snapshot = dict(blobs.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteRuntimeConformanceError(
            "blobs could not be snapshotted"
        ) from exc
    if any(not isinstance(key, str) for key in snapshot):
        raise RepositoryWriteRuntimeConformanceError(
            "blob locator keys must be strings"
        )
    if any(type(value) is not bytes for value in snapshot.values()):
        raise RepositoryWriteRuntimeConformanceError(
            "blob values must be exact bytes"
        )
    return snapshot


def _snapshot_subjects(
    subjects: Mapping[str, "RuntimeConformanceSubject"],
) -> dict[str, "RuntimeConformanceSubject"]:
    if not isinstance(subjects, Mapping):
        raise RepositoryWriteRuntimeConformanceError(
            "runtime_subjects must be a mapping"
        )
    try:
        snapshot = dict(subjects.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteRuntimeConformanceError(
            "runtime_subjects could not be snapshotted"
        ) from exc
    for digest, subject in snapshot.items():
        _strict_sha(digest, "runtime subject key")
        if not isinstance(subject, RuntimeConformanceSubject):
            raise RepositoryWriteRuntimeConformanceError(
                "runtime subject values must be typed"
            )
        if digest != subject.receipt.digest:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "runtime subject key differs from its receipt digest"
            )
    return snapshot


def _snapshot_ledgers(
    ledgers: Mapping[str, RuntimeTrustLedger],
) -> dict[str, RuntimeTrustLedger]:
    if not isinstance(ledgers, Mapping):
        raise RepositoryWriteRuntimeConformanceError(
            "runtime_trust_ledgers must be a mapping"
        )
    try:
        snapshot = dict(ledgers.items())
    except (TypeError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteRuntimeConformanceError(
            "runtime_trust_ledgers could not be snapshotted"
        ) from exc
    for runtime_id, ledger in snapshot.items():
        _strict_runtime_id(runtime_id, "runtime trust ledger key")
        if not isinstance(ledger, RuntimeTrustLedger):
            raise RepositoryWriteRuntimeConformanceError(
                "runtime trust ledger values must be typed"
            )
    return snapshot


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteRuntimeConformancePayloadError(
                "runtime evidence JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise RepositoryWriteRuntimeConformancePayloadError(
        f"runtime evidence JSON contains non-finite number {value}"
    )


@dataclass(frozen=True)
class RuntimeConformanceSubject:
    envelope: RuntimeConformanceEnvelope
    identity: RuntimeProbeIdentity
    receipt: RuntimeConformanceReceipt
    manifest: RuntimeManifest

    def __post_init__(self) -> None:
        expected = (
            (self.envelope, RuntimeConformanceEnvelope, "envelope"),
            (self.identity, RuntimeProbeIdentity, "identity"),
            (self.receipt, RuntimeConformanceReceipt, "receipt"),
            (self.manifest, RuntimeManifest, "manifest"),
        )
        for value, type_, label in expected:
            if not isinstance(value, type_):
                raise ValueError(f"runtime subject {label} type is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "runtime_id": self.manifest.runtime_id,
            "envelope_sha256": self.envelope.digest,
            "probe_identity_sha256": self.identity.digest,
            "conformance_receipt_sha256": self.receipt.digest,
            "runtime_manifest_sha256": self.manifest.digest,
            "source_revision": self.manifest.source_revision,
        }


@dataclass(frozen=True)
class RuntimeConformanceReplayRecord:
    surface_sha256: str
    locator: str
    runtime_id: str
    envelope_sha256: str
    trust_record_sha256: str
    probe_identity_sha256: str
    conformance_receipt_sha256: str
    runtime_manifest_sha256: str
    observed_at: str
    expires_at: str
    check_set_sha256: str
    replay_sha256: str

    def __post_init__(self) -> None:
        _strict_sha(self.surface_sha256, "surface_sha256")
        if (
            not isinstance(self.locator, str)
            or _CAS_LOCATOR.fullmatch(self.locator) is None
        ):
            raise ValueError("locator must be content-addressed")
        _strict_runtime_id(self.runtime_id, "runtime_id")
        for field_name in (
            "envelope_sha256",
            "trust_record_sha256",
            "probe_identity_sha256",
            "conformance_receipt_sha256",
            "runtime_manifest_sha256",
            "check_set_sha256",
            "replay_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        _parse_utc(self.observed_at, "observed_at")
        _parse_utc(self.expires_at, "expires_at")
        expected = hashlib.sha256(
            canonical_json(self._replay_payload()).encode("ascii")
        ).hexdigest()
        if self.replay_sha256 != expected:
            raise ValueError("replay_sha256 does not bind the record")

    def _replay_payload(self) -> dict[str, object]:
        return {
            "surface_sha256": self.surface_sha256,
            "locator": self.locator,
            "runtime_id": self.runtime_id,
            "envelope_sha256": self.envelope_sha256,
            "trust_record_sha256": self.trust_record_sha256,
            "probe_identity_sha256": self.probe_identity_sha256,
            "conformance_receipt_sha256": self.conformance_receipt_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "check_set_sha256": self.check_set_sha256,
        }

    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.runtime_id,
            self.surface_sha256,
            self.conformance_receipt_sha256,
            self.locator,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._replay_payload(), "replay_sha256": self.replay_sha256}

    @classmethod
    def from_subject(
        cls,
        *,
        surface_sha256: str,
        locator: str,
        subject: RuntimeConformanceSubject,
        trust_record: RuntimeTrustRecord,
    ) -> "RuntimeConformanceReplayRecord":
        checks = [
            {
                "name": check.name,
                "passed": check.passed,
                "evidence_sha256": check.evidence_sha256,
                "evidence_locator": check.evidence_locator,
            }
            for check in subject.receipt.checks
        ]
        check_set_sha256 = hashlib.sha256(
            canonical_json(checks).encode("ascii")
        ).hexdigest()
        payload = {
            "surface_sha256": surface_sha256,
            "locator": locator,
            "runtime_id": subject.manifest.runtime_id,
            "envelope_sha256": subject.envelope.digest,
            "trust_record_sha256": trust_record.record_sha256,
            "probe_identity_sha256": subject.identity.digest,
            "conformance_receipt_sha256": subject.receipt.digest,
            "runtime_manifest_sha256": subject.manifest.digest,
            "observed_at": trust_record.observed_at,
            "expires_at": trust_record.expires_at,
            "check_set_sha256": check_set_sha256,
        }
        replay_sha256 = hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest()
        return cls(**payload, replay_sha256=replay_sha256)


@dataclass(frozen=True)
class RepositoryWriteRuntimeConformanceReport:
    source_revision: str
    classification_digest: str
    materialization_digest: str
    guard_structure_report_digest: str
    origin_attestation_digest: str
    production_classification_count: int
    runtime_subject_count: int
    runtime_binding_count: int
    runtime_set_sha256: str
    records: tuple[RuntimeConformanceReplayRecord, ...]

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "materialization_digest",
            "guard_structure_report_digest",
            "origin_attestation_digest",
            "runtime_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        for field_name in (
            "production_classification_count",
            "runtime_subject_count",
            "runtime_binding_count",
        ):
            if _strict_int(getattr(self, field_name), field_name) < 1:
                raise ValueError(f"{field_name} must be positive")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, RuntimeConformanceReplayRecord)
            for record in self.records
        ):
            raise ValueError("records must be an immutable typed tuple")
        if tuple(
            sorted(self.records, key=RuntimeConformanceReplayRecord.sort_key)
        ) != self.records:
            raise ValueError("records must be canonically sorted")
        if len(set(self.records)) != len(self.records):
            raise ValueError("records must be unique")
        if len(self.records) != self.runtime_binding_count:
            raise ValueError("runtime_binding_count differs from records")
        if (
            len({record.conformance_receipt_sha256 for record in self.records})
            != self.runtime_subject_count
        ):
            raise ValueError("runtime_subject_count differs from records")
        expected = hashlib.sha256(
            canonical_json([record.to_dict() for record in self.records]).encode(
                "ascii"
            )
        ).hexdigest()
        if self.runtime_set_sha256 != expected:
            raise ValueError("runtime_set_sha256 does not bind records")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "guard_structure_report_digest": self.guard_structure_report_digest,
            "origin_attestation_digest": self.origin_attestation_digest,
            "production_classification_count": self.production_classification_count,
            "runtime_subject_count": self.runtime_subject_count,
            "runtime_binding_count": self.runtime_binding_count,
            "runtime_set_sha256": self.runtime_set_sha256,
            "records": [record.to_dict() for record in self.records],
            "origin_authenticated": True,
            "source_anchor_semantics_verified": True,
            "guard_contract_structure_verified": True,
            "runtime_conformance_semantics_verified": True,
            "guard_contract_semantics_verified": False,
            "effect_lease_semantics_verified": False,
            "primary_checkout_disjointness_verified": False,
            "retirement_semantics_verified": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-runtime-conformance",
            "blockers": [
                "effect-lease-semantic-verification-missing",
                "gate-report-binding-missing",
                "guard-contract-behavioral-verification-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def verify_repository_write_runtime_conformance(
    classification: RepositoryWriteClassificationReport,
    blobs: Mapping[str, bytes],
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
    guard_manifest: GuardImplementationManifest,
    runtime_subjects: Mapping[str, RuntimeConformanceSubject],
    runtime_trust_ledgers: Mapping[str, RuntimeTrustLedger],
    *,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    guard_keyring: Mapping[tuple[str, str], bytes | str],
    expected_guard_authority_id: str,
    current_revision: str,
    now: datetime,
    repository_root: Path,
) -> RepositoryWriteRuntimeConformanceReport:
    """Replay every production runtime receipt against active persisted trust."""

    if not isinstance(classification, RepositoryWriteClassificationReport):
        raise RepositoryWriteRuntimeConformanceError(
            "classification report type is invalid"
        )
    revision = _strict_revision(current_revision, "current_revision")
    if classification.source_revision != revision:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "classification source revision is stale"
        )
    instant = _as_utc(now, "now")
    blob_snapshot = _snapshot_bytes(blobs)
    subject_snapshot = _snapshot_subjects(runtime_subjects)
    ledger_snapshot = _snapshot_ledgers(runtime_trust_ledgers)

    guard_report = verify_repository_write_guard_structure(
        classification,
        blob_snapshot,
        origin_attestation,
        guard_manifest,
        collector_keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        guard_keyring=guard_keyring,
        expected_guard_authority_id=expected_guard_authority_id,
        current_revision=revision,
        now=instant,
        repository_root=repository_root,
    )
    materialization = materialize_repository_write_evidence(
        classification,
        blob_snapshot,
    )
    _verify_predecessor_chain(
        classification,
        materialization,
        guard_report,
        origin_attestation,
    )

    production_rows = tuple(
        row for row in classification.classifications if row.production_reachable
    )
    if not production_rows:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime replay requires production-reachable classifications"
        )
    noncentral = tuple(
        row for row in production_rows if row.guard is not GuardDisposition.CENTRAL
    )
    if noncentral:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "every production classification must be centrally guarded"
        )
    for row in classification.classifications:
        runtime_bindings = tuple(
            binding
            for binding in row.evidence
            if binding.kind is EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT
        )
        if row.production_reachable:
            if len(runtime_bindings) != 1:
                raise RepositoryWriteRuntimeConformanceBindingError(
                    "every production classification requires exactly one runtime receipt"
                )
        elif runtime_bindings:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "non-production classification retains runtime-conformance evidence"
            )

    materialized_by_locator = {
        record.locator: record for record in materialization.records
    }
    required_receipts: set[str] = set()
    payload_by_binding: dict[EvidenceBinding, tuple[str, str]] = {}
    for row in production_rows:
        binding = next(
            item
            for item in row.evidence
            if item.kind is EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT
        )
        record = materialized_by_locator.get(binding.locator)
        if record is None:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "runtime materialization record is missing"
            )
        raw = blob_snapshot.get(binding.locator)
        if raw is None:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "runtime evidence blob is missing after materialization"
            )
        receipt_sha256, runtime_id = _runtime_payload(
            binding,
            record,
            raw,
        )
        required_receipts.add(receipt_sha256)
        payload_by_binding[binding] = (receipt_sha256, runtime_id)

    if set(subject_snapshot) != required_receipts:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime subject set differs from retained runtime receipt evidence"
        )
    required_runtime_ids = {
        runtime_id for _, runtime_id in payload_by_binding.values()
    }
    if set(ledger_snapshot) != required_runtime_ids:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime trust ledger set differs from retained runtime identities"
        )

    verified: dict[str, tuple[RuntimeConformanceSubject, RuntimeTrustRecord]] = {}
    for receipt_sha256 in sorted(required_receipts):
        subject = subject_snapshot[receipt_sha256]
        payload_runtime_ids = {
            runtime_id
            for binding, (digest, runtime_id) in payload_by_binding.items()
            if digest == receipt_sha256
        }
        if len(payload_runtime_ids) != 1:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "one runtime receipt is bound to inconsistent runtime identities"
            )
        payload_runtime_id = next(iter(payload_runtime_ids))
        if subject.manifest.runtime_id != payload_runtime_id:
            raise RepositoryWriteRuntimeConformanceBindingError(
                "runtime evidence identity differs from the typed manifest"
            )
        trust_record = _verify_runtime_subject(
            subject,
            ledger_snapshot[payload_runtime_id],
            revision=revision,
            now=instant,
        )
        verified[receipt_sha256] = (subject, trust_record)

    replay_records: list[RuntimeConformanceReplayRecord] = []
    for binding, (receipt_sha256, _) in payload_by_binding.items():
        subject, trust_record = verified[receipt_sha256]
        replay_records.append(
            RuntimeConformanceReplayRecord.from_subject(
                surface_sha256=binding.surface_sha256,
                locator=binding.locator,
                subject=subject,
                trust_record=trust_record,
            )
        )
    records = tuple(
        sorted(replay_records, key=RuntimeConformanceReplayRecord.sort_key)
    )
    runtime_set_sha256 = hashlib.sha256(
        canonical_json([record.to_dict() for record in records]).encode("ascii")
    ).hexdigest()
    return RepositoryWriteRuntimeConformanceReport(
        source_revision=revision,
        classification_digest=classification.digest,
        materialization_digest=materialization.digest,
        guard_structure_report_digest=guard_report.digest,
        origin_attestation_digest=origin_attestation.digest,
        production_classification_count=len(production_rows),
        runtime_subject_count=len(required_receipts),
        runtime_binding_count=len(records),
        runtime_set_sha256=runtime_set_sha256,
        records=records,
    )


def _runtime_payload(
    binding: EvidenceBinding,
    record: MaterializedEvidenceRecord,
    raw: bytes,
) -> tuple[str, str]:
    if binding.kind is not EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT:
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime payload requires a runtime-conformance binding"
        )
    if record.kind is not EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime materialization kind differs from its binding"
        )
    if type(raw) is not bytes:
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime evidence must be exact bytes"
        )
    if hashlib.sha256(raw).hexdigest() != record.blob_sha256:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime evidence bytes changed after materialization"
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
        RepositoryWriteRuntimeConformancePayloadError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime evidence cannot be replayed as strict JSON"
        ) from exc
    if raw != canonical or not isinstance(document, dict):
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime evidence is not a canonical object"
        )
    if set(document) != {
        "schema",
        "kind",
        "source_revision",
        "surface_sha256",
        "guard_contract",
        "subject_sha256",
        "payload_sha256",
        "payload",
    }:
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime evidence envelope keys differ from the exact schema"
        )
    exact = {
        "schema": _EVIDENCE_SCHEMA,
        "kind": EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": "",
        "subject_sha256": evidence_subject_sha256(binding),
    }
    for field, expected in exact.items():
        if document[field] != expected:
            raise RepositoryWriteRuntimeConformanceBindingError(
                f"runtime evidence {field} differs from its binding"
            )
    payload = document["payload"]
    if not isinstance(payload, dict) or set(payload) != {
        "receipt_schema",
        "receipt_sha256",
        "runtime_id",
        "conformant",
    }:
        raise RepositoryWriteRuntimeConformancePayloadError(
            "runtime evidence payload keys differ from the exact schema"
        )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    if document["payload_sha256"] != payload_sha256:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime evidence payload digest is invalid"
        )
    if record.payload_sha256 != payload_sha256:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime evidence payload differs from materialization"
        )
    if payload["receipt_schema"] != RuntimeConformanceReceipt.CONTRACT_TYPE:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime receipt schema is not canonical"
        )
    receipt_sha256 = _strict_sha(
        payload["receipt_sha256"],
        "runtime receipt sha256",
    )
    runtime_id = _strict_runtime_id(payload["runtime_id"], "runtime id")
    if payload["conformant"] is not True:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime evidence does not assert strict conformance"
        )
    return receipt_sha256, runtime_id


def _verify_runtime_subject(
    subject: RuntimeConformanceSubject,
    ledger: RuntimeTrustLedger,
    *,
    revision: str,
    now: datetime,
) -> RuntimeTrustRecord:
    comparisons = {
        "envelope_revision": (subject.envelope.source_revision, revision),
        "identity_revision": (subject.identity.source_revision, revision),
        "receipt_revision": (subject.receipt.source_revision, revision),
        "manifest_revision": (subject.manifest.source_revision, revision),
        "envelope_runtime": (
            subject.envelope.runtime_id,
            subject.manifest.runtime_id,
        ),
        "identity_runtime": (
            subject.identity.runtime_id,
            subject.manifest.runtime_id,
        ),
        "envelope_manifest": (
            subject.envelope.runtime_manifest_sha256,
            subject.manifest.digest,
        ),
        "identity_manifest": (
            subject.identity.runtime_manifest_sha256,
            subject.manifest.digest,
        ),
        "receipt_manifest": (
            subject.receipt.runtime_manifest_sha256,
            subject.manifest.digest,
        ),
        "envelope_identity": (
            subject.envelope.probe_identity_sha256,
            subject.identity.digest,
        ),
        "envelope_receipt": (
            subject.envelope.conformance_receipt_sha256,
            subject.receipt.digest,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime subject binding mismatch: " + ", ".join(mismatches)
        )
    if subject.envelope.authority != "live-runtime":
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime subject is not live-runtime evidence"
        )
    if subject.envelope.status != "passed" or subject.receipt.status != "passed":
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime subject did not pass conformance"
        )
    try:
        candidates = tuple(
            record
            for record in ledger.records(subject.manifest.runtime_id)
            if record.envelope_sha256 == subject.envelope.digest
        )
    except RuntimeTrustStoreError as exc:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime trust audit projection failed authentication"
        ) from exc
    if len(candidates) != 1:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime envelope does not have exactly one persisted trust record"
        )
    record = candidates[0]
    trust_comparisons = {
        "state": (record.state, "ACTIVE"),
        "runtime_id": (record.runtime_id, subject.manifest.runtime_id),
        "envelope_sha256": (record.envelope_sha256, subject.envelope.digest),
        "probe_identity_sha256": (
            record.probe_identity_sha256,
            subject.identity.digest,
        ),
        "conformance_receipt_sha256": (
            record.conformance_receipt_sha256,
            subject.receipt.digest,
        ),
        "runtime_manifest_sha256": (
            record.runtime_manifest_sha256,
            subject.manifest.digest,
        ),
        "source_revision": (record.source_revision, revision),
    }
    trust_mismatches = sorted(
        name
        for name, (actual, expected) in trust_comparisons.items()
        if actual != expected
    )
    if trust_mismatches:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "persisted runtime trust binding mismatch: "
            + ", ".join(trust_mismatches)
        )
    if now >= _parse_utc(record.expires_at, "runtime trust expires_at"):
        raise RepositoryWriteRuntimeConformanceBindingError(
            "persisted runtime trust record is expired"
        )
    if _parse_utc(record.observed_at, "runtime trust observed_at") != _parse_utc(
        subject.receipt.finished_at,
        "runtime receipt finished_at",
    ):
        raise RepositoryWriteRuntimeConformanceBindingError(
            "persisted runtime observation differs from the receipt"
        )
    try:
        verify_production_runtime_envelope(
            subject.envelope,
            subject.identity,
            subject.receipt,
            subject.manifest,
            trusted_envelope_sha256s=(record.envelope_sha256,),
            now=now,
        )
    except Exception as exc:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "runtime subject failed live conformance replay"
        ) from exc
    return record


def _verify_predecessor_chain(
    classification: RepositoryWriteClassificationReport,
    materialization: RepositoryWriteEvidenceMaterializationReport,
    guard_report: RepositoryWriteGuardStructureReport,
    origin_attestation: RepositoryWriteEvidenceOriginAttestation,
) -> None:
    comparisons = {
        "materialization_revision": (
            materialization.source_revision,
            classification.source_revision,
        ),
        "materialization_classification": (
            materialization.classification_digest,
            classification.digest,
        ),
        "guard_revision": (
            guard_report.source_revision,
            classification.source_revision,
        ),
        "guard_classification": (
            guard_report.classification_digest,
            classification.digest,
        ),
        "guard_materialization": (
            guard_report.materialization_digest,
            materialization.digest,
        ),
        "guard_origin": (
            guard_report.origin_attestation_digest,
            origin_attestation.digest,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteRuntimeConformanceBindingError(
            "repository-write runtime predecessor chain mismatch: "
            + ", ".join(mismatches)
        )


__all__ = [
    "RepositoryWriteRuntimeConformanceBindingError",
    "RepositoryWriteRuntimeConformanceError",
    "RepositoryWriteRuntimeConformancePayloadError",
    "RepositoryWriteRuntimeConformanceReport",
    "RuntimeConformanceReplayRecord",
    "RuntimeConformanceSubject",
    "verify_repository_write_runtime_conformance",
]
