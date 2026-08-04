"""Content-addressed materialization for repository-write evidence.

This module verifies exact canonical JSON bytes named by revision-and-surface
bound ``EvidenceBinding`` values. It deliberately does not authenticate an
external issuer or semantically replay Effect-Lease, runtime, checkout, or
retirement ledgers; those later verifiers remain mandatory for Gate 0.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    RepositoryWriteClassificationReport,
)
from daedalus.spine.envelope import canonical_json


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_CONTRACT = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_CAS_LOCATOR = re.compile(r"^cas:sha256:([0-9a-f]{64})$")
_REPOSITORY_PATH = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*//)[^\\\r\n]+$"
)
_SINGLE_LINE = re.compile(r"^[^\r\n]+$")
_MAX_EVIDENCE_BYTES = 1_048_576


class RepositoryWriteEvidenceMaterializationError(RuntimeError):
    """Evidence bytes were missing, malformed, stale, or ambiguously bound."""


def evidence_subject_sha256(binding: EvidenceBinding) -> str:
    """Return the non-circular subject digest for one evidence slot."""

    if not isinstance(binding, EvidenceBinding):
        raise ValueError("evidence subject requires a typed binding")
    payload = {
        "kind": binding.kind.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": binding.guard_contract,
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class MaterializedEvidenceRecord:
    kind: EvidenceKind
    source_revision: str
    surface_sha256: str
    guard_contract: str
    locator: str
    blob_sha256: str
    payload_sha256: str
    subject_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("materialized evidence kind must be typed")
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("materialized evidence revision must be lowercase 40-hex")
        for value, label in (
            (self.surface_sha256, "surface"),
            (self.blob_sha256, "blob"),
            (self.payload_sha256, "payload"),
            (self.subject_sha256, "subject"),
        ):
            if not _SHA256.fullmatch(value):
                raise ValueError(f"materialized {label} digest must be lowercase sha256")
        match = _CAS_LOCATOR.fullmatch(self.locator)
        if match is None or match.group(1) != self.blob_sha256:
            raise ValueError("materialized locator must name the exact blob digest")
        if self.kind is EvidenceKind.GUARD_CONTRACT:
            if not _CONTRACT.fullmatch(self.guard_contract):
                raise ValueError("guard evidence must retain its contract name")
        elif self.guard_contract:
            raise ValueError("non-guard materialization cannot name a guard contract")

    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_revision,
            self.surface_sha256,
            self.kind.value,
            self.guard_contract,
            self.locator,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "source_revision": self.source_revision,
            "surface_sha256": self.surface_sha256,
            "guard_contract": self.guard_contract,
            "locator": self.locator,
            "blob_sha256": self.blob_sha256,
            "payload_sha256": self.payload_sha256,
            "subject_sha256": self.subject_sha256,
        }


@dataclass(frozen=True)
class RepositoryWriteEvidenceMaterializationReport:
    source_revision: str
    classification_digest: str
    binding_count: int
    records: tuple[MaterializedEvidenceRecord, ...]
    missing_locators: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("materialization revision must be lowercase 40-hex")
        if not _SHA256.fullmatch(self.classification_digest):
            raise ValueError("classification digest must be lowercase sha256")
        if type(self.binding_count) is not int or self.binding_count < 0:
            raise ValueError("binding_count must be a non-negative integer")
        if not isinstance(self.records, tuple) or any(
            not isinstance(row, MaterializedEvidenceRecord) for row in self.records
        ):
            raise ValueError("records must be an immutable typed tuple")
        if tuple(sorted(self.records, key=MaterializedEvidenceRecord.sort_key)) != self.records:
            raise ValueError("records must be canonically sorted")
        if len(set(self.records)) != len(self.records):
            raise ValueError("records must be unique")
        if any(row.source_revision != self.source_revision for row in self.records):
            raise ValueError("record revision differs from report revision")
        if not isinstance(self.missing_locators, tuple):
            raise ValueError("missing_locators must be an immutable tuple")
        if tuple(sorted(self.missing_locators)) != self.missing_locators:
            raise ValueError("missing_locators must be sorted")
        if len(set(self.missing_locators)) != len(self.missing_locators):
            raise ValueError("missing_locators must be unique")
        if any(_CAS_LOCATOR.fullmatch(value) is None for value in self.missing_locators):
            raise ValueError("missing locator is not content-addressed")
        if self.binding_count != len(self.records) + len(self.missing_locators):
            raise ValueError("binding count does not match materialization projection")
        if {row.locator for row in self.records}.intersection(self.missing_locators):
            raise ValueError("materialized and missing locators must be disjoint")

    @property
    def materialization_complete(self) -> bool:
        return self.binding_count > 0 and not self.missing_locators

    def _payload(self) -> dict[str, object]:
        blockers = [
            "external-evidence-origin-authentication-missing",
            "external-evidence-semantic-verification-missing",
            "gate-report-binding-missing",
        ]
        if self.binding_count == 0:
            blockers.append("evidence-bindings-empty")
        if self.missing_locators:
            blockers.append("evidence-blobs-missing")
        return {
            "schema": "daedalus-gate0-repository-write-evidence-materialization/1",
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "binding_count": self.binding_count,
            "materialized_count": len(self.records),
            "records": [row.to_dict() for row in self.records],
            "missing_locators": list(self.missing_locators),
            "materialization_complete": self.materialization_complete,
            "content_addressed": True,
            "canonical_bytes_verified": self.materialization_complete,
            "binding_verified": self.materialization_complete,
            "origin_authenticated": False,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-evidence-materialization",
            "blockers": sorted(blockers),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self._payload()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def materialize_repository_write_evidence(
    classification: RepositoryWriteClassificationReport,
    blobs: Mapping[str, bytes],
) -> RepositoryWriteEvidenceMaterializationReport:
    """Verify exact CAS bytes for every evidence binding in a classification."""

    if not isinstance(classification, RepositoryWriteClassificationReport):
        raise RepositoryWriteEvidenceMaterializationError(
            "classification report type is invalid"
        )
    if not isinstance(blobs, Mapping):
        raise RepositoryWriteEvidenceMaterializationError("blobs must be a mapping")
    if any(not isinstance(key, str) for key in blobs):
        raise RepositoryWriteEvidenceMaterializationError(
            "blob locator keys must be strings"
        )
    if any(type(value) is not bytes for value in blobs.values()):
        raise RepositoryWriteEvidenceMaterializationError(
            "blob values must be exact bytes"
        )

    bindings = tuple(
        item for row in classification.classifications for item in row.evidence
    )
    expected_locators: set[str] = set()
    seen_blob_digests: set[str] = set()
    for binding in bindings:
        match = _CAS_LOCATOR.fullmatch(binding.locator)
        if match is None or match.group(1) != binding.sha256:
            raise RepositoryWriteEvidenceMaterializationError(
                "evidence locator does not name its declared digest"
            )
        if binding.locator in expected_locators:
            raise RepositoryWriteEvidenceMaterializationError(
                "evidence locator is reused across bindings"
            )
        if binding.sha256 in seen_blob_digests:
            raise RepositoryWriteEvidenceMaterializationError(
                "evidence blob digest is reused across bindings"
            )
        expected_locators.add(binding.locator)
        seen_blob_digests.add(binding.sha256)

    if set(blobs) - expected_locators:
        raise RepositoryWriteEvidenceMaterializationError(
            "unexpected evidence blob locators are present"
        )

    records: list[MaterializedEvidenceRecord] = []
    missing: list[str] = []
    for binding in bindings:
        raw = blobs.get(binding.locator)
        if raw is None:
            missing.append(binding.locator)
        else:
            records.append(_materialize_one(binding, raw))

    return RepositoryWriteEvidenceMaterializationReport(
        source_revision=classification.source_revision,
        classification_digest=classification.digest,
        binding_count=len(bindings),
        records=tuple(sorted(records, key=MaterializedEvidenceRecord.sort_key)),
        missing_locators=tuple(sorted(missing)),
    )


def _materialize_one(
    binding: EvidenceBinding, raw: bytes
) -> MaterializedEvidenceRecord:
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence blob exceeds the bounded materialization size"
        )
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    if raw_sha256 != binding.sha256:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence blob digest differs from its binding"
        )
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence blob encoding is invalid"
        )
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        canonical = canonical_json(document).encode("ascii")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RepositoryWriteEvidenceMaterializationError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence blob is not strict canonical JSON"
        ) from exc
    if not isinstance(document, dict) or any(
        not isinstance(key, str) for key in document
    ):
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence document must be an object"
        )
    if raw != canonical:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence blob bytes are not canonical JSON"
        )

    _require_exact_keys(
        document,
        {
            "schema",
            "kind",
            "source_revision",
            "surface_sha256",
            "guard_contract",
            "subject_sha256",
            "payload_sha256",
            "payload",
        },
        "evidence envelope",
    )
    if document["schema"] != "daedalus-gate0-repository-write-evidence-object/1":
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence envelope schema is unsupported"
        )
    exact_fields = {
        "kind": binding.kind.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": binding.guard_contract,
        "subject_sha256": evidence_subject_sha256(binding),
    }
    for field, expected in exact_fields.items():
        if document[field] != expected:
            raise RepositoryWriteEvidenceMaterializationError(
                f"evidence {field} differs from its binding"
            )

    payload = document["payload"]
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence payload must be an object"
        )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    if document["payload_sha256"] != payload_sha256:
        raise RepositoryWriteEvidenceMaterializationError(
            "evidence payload digest is invalid"
        )
    _validate_payload(binding, payload)
    return MaterializedEvidenceRecord(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        guard_contract=binding.guard_contract,
        locator=binding.locator,
        blob_sha256=raw_sha256,
        payload_sha256=payload_sha256,
        subject_sha256=exact_fields["subject_sha256"],
    )


def _validate_payload(
    binding: EvidenceBinding, payload: Mapping[str, object]
) -> None:
    if binding.kind is EvidenceKind.SOURCE_ANCHOR:
        _require_exact_keys(
            payload, {"path", "line", "column", "source_sha256"}, "source anchor"
        )
        if _REPOSITORY_PATH.fullmatch(
            _strict_str(payload["path"], "source anchor path")
        ) is None:
            raise RepositoryWriteEvidenceMaterializationError(
                "source anchor path is not normalized repository-relative"
            )
        if _strict_int(payload["line"], "source anchor line") < 1:
            raise RepositoryWriteEvidenceMaterializationError(
                "source anchor line must be positive"
            )
        if _strict_int(payload["column"], "source anchor column") < 0:
            raise RepositoryWriteEvidenceMaterializationError(
                "source anchor column must be non-negative"
            )
        _strict_sha(payload["source_sha256"], "source anchor source_sha256")
        return

    if binding.kind is EvidenceKind.GUARD_CONTRACT:
        _require_exact_keys(
            payload,
            {"contract", "implementation_target", "implementation_sha256"},
            "guard contract",
        )
        if payload["contract"] != binding.guard_contract:
            raise RepositoryWriteEvidenceMaterializationError(
                "guard payload contract differs from its binding"
            )
        _strict_single_line(
            payload["implementation_target"], "guard implementation target"
        )
        _strict_sha(
            payload["implementation_sha256"], "guard implementation sha256"
        )
        return

    if binding.kind is EvidenceKind.EFFECT_LEASE_RECEIPT:
        _require_exact_keys(
            payload,
            {"receipt_schema", "receipt_sha256", "entrypoint_id", "terminal_state"},
            "effect lease receipt",
        )
        _strict_single_line(payload["receipt_schema"], "effect receipt schema")
        _strict_sha(payload["receipt_sha256"], "effect receipt sha256")
        if _CONTRACT.fullmatch(
            _strict_str(payload["entrypoint_id"], "effect entrypoint id")
        ) is None:
            raise RepositoryWriteEvidenceMaterializationError(
                "effect entrypoint id is invalid"
            )
        if payload["terminal_state"] not in {"completed", "failed", "cancelled"}:
            raise RepositoryWriteEvidenceMaterializationError(
                "effect lease receipt is not terminal"
            )
        return

    if binding.kind is EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT:
        _require_exact_keys(
            payload,
            {"receipt_schema", "receipt_sha256", "runtime_id", "conformant"},
            "runtime conformance receipt",
        )
        _strict_single_line(payload["receipt_schema"], "runtime receipt schema")
        _strict_sha(payload["receipt_sha256"], "runtime receipt sha256")
        _strict_single_line(payload["runtime_id"], "runtime id")
        if payload["conformant"] is not True:
            raise RepositoryWriteEvidenceMaterializationError(
                "runtime conformance payload must assert strict true"
            )
        return

    if binding.kind is EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT:
        _require_exact_keys(
            payload,
            {
                "receipt_schema",
                "receipt_sha256",
                "primary_checkout_sha256",
                "target_root_sha256",
                "disjoint",
            },
            "checkout disjointness receipt",
        )
        _strict_single_line(payload["receipt_schema"], "disjointness receipt schema")
        _strict_sha(payload["receipt_sha256"], "disjointness receipt sha256")
        _strict_sha(
            payload["primary_checkout_sha256"], "primary checkout fingerprint"
        )
        _strict_sha(payload["target_root_sha256"], "target root fingerprint")
        if payload["disjoint"] is not True:
            raise RepositoryWriteEvidenceMaterializationError(
                "checkout disjointness payload must assert strict true"
            )
        return

    if binding.kind is EvidenceKind.RETIREMENT_RECEIPT:
        _require_exact_keys(
            payload,
            {
                "receipt_schema",
                "receipt_sha256",
                "retired_target",
                "production_reachable",
            },
            "retirement receipt",
        )
        _strict_single_line(payload["receipt_schema"], "retirement receipt schema")
        _strict_sha(payload["receipt_sha256"], "retirement receipt sha256")
        _strict_single_line(payload["retired_target"], "retired target")
        if payload["production_reachable"] is not False:
            raise RepositoryWriteEvidenceMaterializationError(
                "retirement payload must assert strict false reachability"
            )
        return

    raise RepositoryWriteEvidenceMaterializationError("evidence kind is unsupported")


def _reject_nonfinite(value: str) -> object:
    raise RepositoryWriteEvidenceMaterializationError(
        f"evidence JSON contains non-finite number {value}"
    )


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteEvidenceMaterializationError(
                "evidence JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _require_exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if set(value) != required:
        raise RepositoryWriteEvidenceMaterializationError(f"{label} keys are invalid")


def _strict_str(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RepositoryWriteEvidenceMaterializationError(
            f"{label} must be a string"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteEvidenceMaterializationError(
            f"{label} must be an integer"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    text = _strict_str(value, label)
    if _SHA256.fullmatch(text) is None:
        raise RepositoryWriteEvidenceMaterializationError(
            f"{label} must be lowercase sha256"
        )
    return text


def _strict_single_line(value: object, label: str) -> str:
    text = _strict_str(value, label)
    if _SINGLE_LINE.fullmatch(text) is None or not text.strip():
        raise RepositoryWriteEvidenceMaterializationError(
            f"{label} must be a non-empty single line"
        )
    return text
