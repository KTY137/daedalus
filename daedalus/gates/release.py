"""Fail-closed Gate-0 release assembly over retained exact-head evidence.

This module does not close a gate, create OwnerApproval, promote a candidate or
invent evidence. It verifies an already-derived :class:`GateReport` against an
authenticated :class:`GateEvidenceIndex` trust bundle and emits a separately
signed mechanical receipt for the exact inputs it observed.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.writer_inventory import (
    WriterInventoryError,
    scan_event_store_writers,
)

from .evidence import ArtifactEvidence, GateEvidenceIndex
from .evidence_verifier import evidence_requirements_sha256
from .report import GateReport
from .trust_bundle import (
    EvidenceTrustBundle,
    EvidenceTrustBundleError,
    assert_strict_exact_head_with_bundle,
)

_RELEASE_RECEIPT_SCHEMA = "daedalus-gate0-release-receipt/1"
_RELEASE_RECEIPT_ORIGIN = "gates.gate0-release-verifier"
_REPORT_SCHEMA = "daedalus-gate-report/2"
_REPORT_FIELDS = {
    "schema",
    "gate",
    "source_revision",
    "registry_sha256",
    "closed",
    "security_boundary_claimed",
    "unregistered_effectful_entrypoints",
    "unguarded_entrypoints",
    "inventory_only_production_entrypoints",
    "missing_guard_contracts",
    "runtime_conformance_failures",
    "fault_injection_failures",
    "primary_checkout_mutations",
    "event_store_writer_inventory_sha256",
    "event_store_writer_failures",
    "owner_approval_enforced",
    "diagnostics",
    "blockers",
    "report_sha256",
}
_REPORT_ARRAY_FIELDS = (
    "unregistered_effectful_entrypoints",
    "unguarded_entrypoints",
    "inventory_only_production_entrypoints",
    "missing_guard_contracts",
    "runtime_conformance_failures",
    "fault_injection_failures",
    "primary_checkout_mutations",
    "event_store_writer_failures",
    "diagnostics",
    "blockers",
)
_REQUIRED_RELEASE_ARTIFACT_KINDS = frozenset(
    {"gate-report", "effect-inventory"}
)


class Gate0ReleaseError(RuntimeError):
    """Base error for exact-head Gate-0 release verification."""


class Gate0ReleaseBlocked(Gate0ReleaseError):
    """The report or retained evidence still has a release blocker."""


class Gate0ReleaseBindingError(Gate0ReleaseError):
    """The report, evidence, receipt or exact repository state disagree."""


class Gate0ReleaseSignatureError(Gate0ReleaseError):
    """The release-verifier signature cannot be authenticated."""


@dataclass(frozen=True)
class Gate0ReleaseReceipt(CanonicalContract):
    """Signed mechanical result for one exact Gate-0 release assessment."""

    CONTRACT_TYPE: ClassVar[str] = _RELEASE_RECEIPT_SCHEMA

    receipt_id: str
    verifier_id: str
    verifier_key_id: str
    source_revision: str
    source_tree_revision: str
    gate_report_sha256: str
    gate_report_artifact_sha256: str
    registry_sha256: str
    evidence_index_sha256: str
    trust_bundle_sha256: str
    requirements_sha256: str
    status: str
    verified_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receipt_id",
            _identifier(self.receipt_id, "receipt_id"),
        )
        object.__setattr__(
            self,
            "verifier_id",
            _identifier(self.verifier_id, "verifier_id"),
        )
        object.__setattr__(
            self,
            "verifier_key_id",
            _identifier(self.verifier_key_id, "verifier_key_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "source_tree_revision",
            _revision(self.source_tree_revision, "source_tree_revision"),
        )
        for field_name in (
            "gate_report_sha256",
            "gate_report_artifact_sha256",
            "registry_sha256",
            "evidence_index_sha256",
            "trust_bundle_sha256",
            "requirements_sha256",
            "signature_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        if self.status != "passed":
            raise ValueError("Gate-0 release receipt status must be passed")
        object.__setattr__(
            self,
            "verified_at",
            _utc_timestamp(self.verified_at, "verified_at"),
        )
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("provenance must be ContractProvenance")
        if self.provenance.origin != _RELEASE_RECEIPT_ORIGIN:
            raise ValueError("release receipt provenance origin is invalid")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("release receipt source revision contradicts provenance")
        if self.provenance.created_at != self.verified_at:
            raise ValueError("release receipt verified_at contradicts provenance")
        if self.provenance.trace_id != self.receipt_id:
            raise ValueError("release receipt trace_id must equal receipt_id")
        expected_inputs = _receipt_input_digests(self)
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise ValueError(
                "release receipt provenance must bind exactly all release inputs"
            )

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Gate0ReleaseReceipt":
        body = cls._contract_payload(payload)
        provenance = body["provenance"]
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


def _receipt_input_digests(
    receipt: Gate0ReleaseReceipt,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                receipt.gate_report_sha256,
                receipt.gate_report_artifact_sha256,
                receipt.registry_sha256,
                receipt.evidence_index_sha256,
                receipt.trust_bundle_sha256,
                receipt.requirements_sha256,
            }
        )
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Gate0ReleaseBindingError(f"{label} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Gate0ReleaseBindingError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("release verifier secret must contain at least 32 bytes")
    return value


def _signature(digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def validate_strict_gate_report_payload(
    payload: Mapping[str, Any],
) -> GateReport:
    """Validate the exact canonical GateReport-v2 wire form without coercion."""

    if not isinstance(payload, Mapping):
        raise ValueError("gate report must be an object")
    if set(payload) != _REPORT_FIELDS:
        raise ValueError("gate report fields are not exact")
    if payload["schema"] != _REPORT_SCHEMA:
        raise ValueError("unsupported gate report schema")
    if type(payload["gate"]) is not int or payload["gate"] != 0:
        raise ValueError("gate report gate must be integer zero")
    _revision(payload["source_revision"], "source_revision")
    _sha256(payload["registry_sha256"], "registry_sha256")
    writer_inventory_sha256 = payload["event_store_writer_inventory_sha256"]
    if writer_inventory_sha256 is not None:
        _sha256(
            writer_inventory_sha256,
            "event_store_writer_inventory_sha256",
        )
    for field_name in (
        "closed",
        "security_boundary_claimed",
        "owner_approval_enforced",
    ):
        if type(payload[field_name]) is not bool:
            raise ValueError(f"gate report {field_name} must be boolean")
    for field_name in _REPORT_ARRAY_FIELDS:
        values = payload[field_name]
        if not isinstance(values, list):
            raise ValueError(f"gate report {field_name} must be an array")
        if any(not isinstance(value, str) for value in values):
            raise ValueError(f"gate report {field_name} must contain strings")
        if values != sorted(set(values)):
            raise ValueError(f"gate report {field_name} must be canonical")
    _sha256(payload["report_sha256"], "report_sha256")

    report = GateReport(
        gate=payload["gate"],
        source_revision=payload["source_revision"],
        registry_sha256=payload["registry_sha256"],
        security_boundary_claimed=payload["security_boundary_claimed"],
        unregistered_effectful_entrypoints=tuple(
            payload["unregistered_effectful_entrypoints"]
        ),
        unguarded_entrypoints=tuple(payload["unguarded_entrypoints"]),
        inventory_only_production_entrypoints=tuple(
            payload["inventory_only_production_entrypoints"]
        ),
        missing_guard_contracts=tuple(payload["missing_guard_contracts"]),
        runtime_conformance_failures=tuple(
            payload["runtime_conformance_failures"]
        ),
        fault_injection_failures=tuple(payload["fault_injection_failures"]),
        primary_checkout_mutations=tuple(payload["primary_checkout_mutations"]),
        event_store_writer_inventory_sha256=writer_inventory_sha256,
        event_store_writer_failures=tuple(
            payload["event_store_writer_failures"]
        ),
        owner_approval_enforced=payload["owner_approval_enforced"],
        diagnostics=tuple(payload["diagnostics"]),
    )
    canonical = report.to_dict()
    if dict(payload) != canonical:
        if payload["closed"] != report.closed:
            raise ValueError("gate report closed value is not derived")
        if payload["blockers"] != list(report.blockers):
            raise ValueError("gate report blockers are not derived")
        body = dict(payload)
        claimed = body.pop("report_sha256")
        actual = hashlib.sha256(
            _canonical_json(body).encode("utf-8")
        ).hexdigest()
        if claimed != actual:
            raise ValueError("gate report digest mismatch")
        raise ValueError("gate report is not canonical")
    return report


def strict_gate_report_sha256(report: GateReport) -> str:
    payload = report.to_dict()
    validate_strict_gate_report_payload(payload)
    return payload["report_sha256"]


def strict_gate_report_artifact_sha256(report: GateReport) -> str:
    payload = report.to_dict()
    validate_strict_gate_report_payload(payload)
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_strict_gate_report(path: str | Path) -> GateReport:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("gate report must be an object")
    return validate_strict_gate_report_payload(payload)


def _required_release_artifacts(
    index: GateEvidenceIndex,
) -> tuple[ArtifactEvidence, ArtifactEvidence]:
    missing_requirements = sorted(
        _REQUIRED_RELEASE_ARTIFACT_KINDS
        - set(index.required_artifact_kinds)
    )
    if missing_requirements:
        raise Gate0ReleaseBlocked(
            "release evidence requirements omit artifact kinds: "
            + ", ".join(missing_requirements)
        )
    by_kind = {item.artifact_kind: item for item in index.artifacts}
    missing_artifacts = sorted(
        _REQUIRED_RELEASE_ARTIFACT_KINDS - set(by_kind)
    )
    if missing_artifacts:
        raise Gate0ReleaseBlocked(
            "release evidence omits artifacts: "
            + ", ".join(missing_artifacts)
        )
    return by_kind["gate-report"], by_kind["effect-inventory"]


def _live_writer_inventory(
    repo_root: Path,
    *,
    current_revision: str,
) -> tuple[str, tuple[str, ...]]:
    try:
        inventory = scan_event_store_writers(
            repo_root,
            source_revision=current_revision,
        )
    except WriterInventoryError as exc:
        raise Gate0ReleaseBindingError(
            f"live Event-Store writer inventory refused: {exc}"
        ) from exc
    failures = tuple(
        f"{site.path}:{site.line}:{site.column}:{site.kind}:{site.callee}"
        for site in inventory.blockers
    )
    return inventory.digest, failures


def _assert_gate0_release(
    report: GateReport,
    index: GateEvidenceIndex,
    bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> tuple[str, str]:
    report_sha256 = strict_gate_report_sha256(report)
    report_artifact_sha256 = strict_gate_report_artifact_sha256(report)
    current = _revision(current_revision, "current_revision")
    current_tree = _revision(current_tree_revision, "current_tree_revision")
    report_revision = _revision(report.source_revision, "report.source_revision")
    report_registry = _sha256(report.registry_sha256, "report.registry_sha256")
    mismatches = []
    if report_revision != current:
        mismatches.append("report_source_revision")
    if index.source_revision != current:
        mismatches.append("index_source_revision")
    if bundle.source_revision != current:
        mismatches.append("bundle_source_revision")
    if index.source_tree_revision != current_tree:
        mismatches.append("index_source_tree_revision")
    if bundle.source_tree_revision != current_tree:
        mismatches.append("bundle_source_tree_revision")
    if report_registry != index.registry_sha256:
        mismatches.append("report_registry_sha256")
    if bundle.registry_sha256 != index.registry_sha256:
        mismatches.append("bundle_registry_sha256")
    if mismatches:
        raise Gate0ReleaseBindingError(
            "Gate-0 release binding mismatch: " + ", ".join(sorted(mismatches))
        )

    try:
        assert_strict_exact_head_with_bundle(
            index,
            bundle,
            repo_root=repo_root,
            keyring=collector_keyring,
            expected_collector_id=expected_collector_id,
            expected_workflow_paths=expected_workflow_paths,
            current_revision=current,
            current_tree_revision=current_tree,
            now=now,
        )
    except EvidenceTrustBundleError as exc:
        raise Gate0ReleaseBindingError(
            f"authenticated evidence trust bundle refused: {exc}"
        ) from exc
    except ValueError as exc:
        raise Gate0ReleaseBlocked(
            f"exact-head evidence remains blocked: {exc}"
        ) from exc

    gate_report_artifact, effect_inventory_artifact = (
        _required_release_artifacts(index)
    )
    artifact_mismatches = []
    if gate_report_artifact.content_sha256 != report_artifact_sha256:
        artifact_mismatches.append("gate_report_artifact_sha256")
    if effect_inventory_artifact.content_sha256 != report_registry:
        artifact_mismatches.append("effect_inventory_artifact_sha256")
    if artifact_mismatches:
        raise Gate0ReleaseBindingError(
            "release artifact binding mismatch: "
            + ", ".join(artifact_mismatches)
        )

    live_writer_digest, live_writer_failures = _live_writer_inventory(
        repo_root,
        current_revision=current,
    )
    writer_mismatches = []
    if report.event_store_writer_inventory_sha256 != live_writer_digest:
        writer_mismatches.append("event_store_writer_inventory_sha256")
    if report.event_store_writer_failures != live_writer_failures:
        writer_mismatches.append("event_store_writer_failures")
    if writer_mismatches:
        raise Gate0ReleaseBindingError(
            "live Event-Store writer inventory mismatch: "
            + ", ".join(writer_mismatches)
        )
    if live_writer_failures:
        raise Gate0ReleaseBlocked(
            "live Event-Store writer blockers remain: "
            + ", ".join(live_writer_failures)
        )

    if not report.closed:
        raise Gate0ReleaseBlocked(
            "Gate report remains open: " + ", ".join(report.blockers)
        )
    if report.blockers:
        raise Gate0ReleaseBlocked(
            "Gate report retained blockers despite closed state"
        )
    if not report.security_boundary_claimed:
        raise Gate0ReleaseBlocked("Gate report lacks security boundary claim")
    if not report.owner_approval_enforced:
        raise Gate0ReleaseBlocked("Gate report lacks owner approval enforcement")
    return report_sha256, report_artifact_sha256


def issue_gate0_release_receipt(
    report: GateReport,
    index: GateEvidenceIndex,
    bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    current_revision: str,
    current_tree_revision: str,
    receipt_id: str,
    verifier_id: str,
    verifier_key_id: str,
    verifier_secret: bytes | str,
    verified_at: datetime,
) -> Gate0ReleaseReceipt:
    """Verify exact inputs and issue one signed mechanical release receipt."""

    instant = _as_utc(verified_at, "verified_at")
    report_sha256, report_artifact_sha256 = _assert_gate0_release(
        report,
        index,
        bundle,
        repo_root=repo_root,
        collector_keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        expected_workflow_paths=expected_workflow_paths,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=instant,
    )
    if instant < _parse_utc(bundle.issued_at, "bundle.issued_at"):
        raise Gate0ReleaseBindingError(
            "release receipt predates authenticated trust bundle"
        )
    requirements = evidence_requirements_sha256(index)
    placeholder = Gate0ReleaseReceipt(
        receipt_id=receipt_id,
        verifier_id=verifier_id,
        verifier_key_id=verifier_key_id,
        source_revision=current_revision,
        source_tree_revision=current_tree_revision,
        gate_report_sha256=report_sha256,
        gate_report_artifact_sha256=report_artifact_sha256,
        registry_sha256=index.registry_sha256,
        evidence_index_sha256=index.digest,
        trust_bundle_sha256=bundle.digest,
        requirements_sha256=requirements,
        status="passed",
        verified_at=instant.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
        provenance=ContractProvenance(
            origin=_RELEASE_RECEIPT_ORIGIN,
            source_revision=current_revision,
            created_at=instant.isoformat(timespec="microseconds"),
            input_digests=tuple(
                sorted(
                    {
                        report_sha256,
                        report_artifact_sha256,
                        index.registry_sha256,
                        index.digest,
                        bundle.digest,
                        requirements,
                    }
                )
            ),
            trace_id=receipt_id,
        ),
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            verifier_secret,
        ),
    )


def verify_gate0_release_receipt(
    receipt: Gate0ReleaseReceipt,
    report: GateReport,
    index: GateEvidenceIndex,
    bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    verifier_keyring: Mapping[tuple[str, str], bytes | str],
    expected_verifier_id: str,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> None:
    """Authenticate the receipt and re-run the complete exact-head assessment."""

    secret = verifier_keyring.get((receipt.verifier_id, receipt.verifier_key_id))
    if secret is None:
        raise Gate0ReleaseSignatureError("release verifier key is unknown")
    expected_signature = _signature(receipt.signing_digest, secret)
    if not hmac.compare_digest(receipt.signature_sha256, expected_signature):
        raise Gate0ReleaseSignatureError("release receipt signature mismatch")

    instant = _as_utc(now, "now")
    verified = _parse_utc(receipt.verified_at, "receipt.verified_at")
    if verified > instant:
        raise Gate0ReleaseBindingError("release receipt is from the future")
    report_sha256, report_artifact_sha256 = _assert_gate0_release(
        report,
        index,
        bundle,
        repo_root=repo_root,
        collector_keyring=collector_keyring,
        expected_collector_id=expected_collector_id,
        expected_workflow_paths=expected_workflow_paths,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=instant,
    )
    expected = {
        "verifier_id": (
            receipt.verifier_id,
            _identifier(expected_verifier_id, "expected_verifier_id"),
        ),
        "source_revision": (
            receipt.source_revision,
            _revision(current_revision, "current_revision"),
        ),
        "source_tree_revision": (
            receipt.source_tree_revision,
            _revision(current_tree_revision, "current_tree_revision"),
        ),
        "gate_report_sha256": (receipt.gate_report_sha256, report_sha256),
        "gate_report_artifact_sha256": (
            receipt.gate_report_artifact_sha256,
            report_artifact_sha256,
        ),
        "registry_sha256": (receipt.registry_sha256, index.registry_sha256),
        "evidence_index_sha256": (
            receipt.evidence_index_sha256,
            index.digest,
        ),
        "trust_bundle_sha256": (
            receipt.trust_bundle_sha256,
            bundle.digest,
        ),
        "requirements_sha256": (
            receipt.requirements_sha256,
            evidence_requirements_sha256(index),
        ),
    }
    mismatches = sorted(
        name for name, (actual, wanted) in expected.items() if actual != wanted
    )
    if mismatches:
        raise Gate0ReleaseBindingError(
            "release receipt binding mismatch: " + ", ".join(mismatches)
        )
    if verified < _parse_utc(bundle.issued_at, "bundle.issued_at"):
        raise Gate0ReleaseBindingError(
            "release receipt predates authenticated trust bundle"
        )


def parse_gate0_release_receipt(
    payload: Mapping[str, Any],
) -> Gate0ReleaseReceipt:
    if not isinstance(payload, Mapping):
        raise ValueError("Gate-0 release receipt must be an object")
    if not isinstance(payload.get("provenance"), Mapping):
        raise ValueError("provenance must be an object")
    return Gate0ReleaseReceipt.from_dict(payload)


def load_gate0_release_receipt(path: str | Path) -> Gate0ReleaseReceipt:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("Gate-0 release receipt must be an object")
    return parse_gate0_release_receipt(payload)


__all__ = [
    "Gate0ReleaseBindingError",
    "Gate0ReleaseBlocked",
    "Gate0ReleaseError",
    "Gate0ReleaseReceipt",
    "Gate0ReleaseSignatureError",
    "issue_gate0_release_receipt",
    "load_gate0_release_receipt",
    "load_strict_gate_report",
    "parse_gate0_release_receipt",
    "strict_gate_report_artifact_sha256",
    "strict_gate_report_sha256",
    "validate_strict_gate_report_payload",
    "verify_gate0_release_receipt",
]
