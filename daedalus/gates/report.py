"""Deterministic Gate-0 report and monotonic migration comparison."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from daedalus.schemas import RuntimeConformanceReceipt
from daedalus.spine.effect_boundary import (
    GUARD_CONTRACT_IMPLEMENTED,
    REGISTRY_BY_ID,
    Wiring,
    check_conformance,
)
from daedalus.spine.writer_inventory import (
    WriterInventoryError,
    scan_event_store_writers,
)

_SCHEMA = "daedalus-gate-report/2"
_LEGACY_SCHEMA = "daedalus-gate-report/1"
_SUPPORTED_SCHEMAS = frozenset({_SCHEMA, _LEGACY_SCHEMA})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_REPORT_BYTES = 4 * 1024 * 1024
_SEQUENCE_FIELDS = (
    "unregistered_effectful_entrypoints",
    "unguarded_entrypoints",
    "inventory_only_production_entrypoints",
    "missing_guard_contracts",
    "runtime_conformance_failures",
    "fault_injection_failures",
    "primary_checkout_mutations",
    "event_store_writer_failures",
    "diagnostics",
)
_V1_FIELDS = frozenset(
    {
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
        "owner_approval_enforced",
        "diagnostics",
        "blockers",
        "report_sha256",
    }
)
_V2_FIELDS = frozenset(
    set(_V1_FIELDS)
    | {
        "event_store_writer_inventory_sha256",
        "event_store_writer_failures",
    }
)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_rows(values: Iterable[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of strings") from exc
    for row in rows:
        if not isinstance(row, str) or not row or len(row) > 4000:
            raise ValueError(f"{name} contains an invalid string")
    return tuple(sorted(set(rows)))


def _sha256_value(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256 hex digest")
    return value


def _sha256_or_none(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _sha256_value(value, name)


def _string_field(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise ValueError(f"{name} must be a non-empty bounded string")
    return value


def _bool_field(payload: Mapping[str, Any], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _int_field(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _sequence_field(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array of strings")
    return _normalize_rows(value, name)


def _verify_serialized_digest(payload: Mapping[str, Any]) -> None:
    expected = _sha256_value(payload.get("report_sha256"), "report_sha256")
    body = dict(payload)
    body.pop("report_sha256")
    actual = hashlib.sha256(_canonical_json(body).encode()).hexdigest()
    if expected != actual:
        raise ValueError("gate report digest mismatch")


def _object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"gate report contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"gate report contains non-finite JSON constant: {value}")


@dataclass(frozen=True)
class GateReport:
    gate: int
    source_revision: str
    registry_sha256: str
    security_boundary_claimed: bool
    unregistered_effectful_entrypoints: tuple[str, ...] = ()
    unguarded_entrypoints: tuple[str, ...] = ()
    inventory_only_production_entrypoints: tuple[str, ...] = ()
    missing_guard_contracts: tuple[str, ...] = ()
    runtime_conformance_failures: tuple[str, ...] = ()
    fault_injection_failures: tuple[str, ...] = ()
    primary_checkout_mutations: tuple[str, ...] = ()
    event_store_writer_inventory_sha256: str | None = None
    event_store_writer_failures: tuple[str, ...] = ()
    owner_approval_enforced: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.gate) is not int or self.gate != 0:
            raise ValueError("this report implementation currently supports Gate 0 only")
        if (
            not isinstance(self.source_revision, str)
            or not _SOURCE_REVISION.fullmatch(self.source_revision)
        ):
            raise ValueError(
                "source_revision must be a lowercase 40-hex commit"
            )
        object.__setattr__(
            self,
            "registry_sha256",
            _sha256_value(self.registry_sha256, "registry_sha256"),
        )
        if type(self.security_boundary_claimed) is not bool:
            raise ValueError("security_boundary_claimed must be a boolean")
        if type(self.owner_approval_enforced) is not bool:
            raise ValueError("owner_approval_enforced must be a boolean")
        object.__setattr__(
            self,
            "event_store_writer_inventory_sha256",
            _sha256_or_none(
                self.event_store_writer_inventory_sha256,
                "event_store_writer_inventory_sha256",
            ),
        )
        for name in _SEQUENCE_FIELDS:
            object.__setattr__(
                self,
                name,
                _normalize_rows(getattr(self, name), name),
            )

    @property
    def closed(self) -> bool:
        return bool(
            self.security_boundary_claimed
            and self.owner_approval_enforced
            and not self.blockers
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        rows: list[str] = []
        for field_name in (
            "unregistered_effectful_entrypoints",
            "unguarded_entrypoints",
            "inventory_only_production_entrypoints",
            "missing_guard_contracts",
            "runtime_conformance_failures",
            "fault_injection_failures",
            "primary_checkout_mutations",
            "event_store_writer_failures",
        ):
            rows.extend(
                f"{field_name}:{item}" for item in getattr(self, field_name)
            )
        if self.event_store_writer_inventory_sha256 is None:
            rows.append("event_store_writer_inventory_sha256:missing")
        if not self.security_boundary_claimed:
            rows.append("security_boundary_claimed:false")
        if not self.owner_approval_enforced:
            rows.append("owner_approval_enforced:false")
        return tuple(sorted(rows))

    def _body_v2(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "registry_sha256": self.registry_sha256,
            "closed": self.closed,
            "security_boundary_claimed": self.security_boundary_claimed,
            "unregistered_effectful_entrypoints": list(
                self.unregistered_effectful_entrypoints
            ),
            "unguarded_entrypoints": list(self.unguarded_entrypoints),
            "inventory_only_production_entrypoints": list(
                self.inventory_only_production_entrypoints
            ),
            "missing_guard_contracts": list(self.missing_guard_contracts),
            "runtime_conformance_failures": list(
                self.runtime_conformance_failures
            ),
            "fault_injection_failures": list(self.fault_injection_failures),
            "primary_checkout_mutations": list(self.primary_checkout_mutations),
            "event_store_writer_inventory_sha256": (
                self.event_store_writer_inventory_sha256
            ),
            "event_store_writer_failures": list(self.event_store_writer_failures),
            "owner_approval_enforced": self.owner_approval_enforced,
            "diagnostics": list(self.diagnostics),
            "blockers": list(self.blockers),
        }

    def to_dict(self) -> dict[str, Any]:
        body = self._body_v2()
        body["report_sha256"] = hashlib.sha256(
            _canonical_json(body).encode()
        ).hexdigest()
        return body

    def _legacy_dict(self) -> dict[str, Any]:
        legacy_blockers = tuple(
            row
            for row in self.blockers
            if row != "event_store_writer_inventory_sha256:missing"
            and not row.startswith("event_store_writer_failures:")
        )
        legacy_closed = bool(
            self.security_boundary_claimed
            and self.owner_approval_enforced
            and not legacy_blockers
        )
        body: dict[str, Any] = {
            "schema": _LEGACY_SCHEMA,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "registry_sha256": self.registry_sha256,
            "closed": legacy_closed,
            "security_boundary_claimed": self.security_boundary_claimed,
            "unregistered_effectful_entrypoints": list(
                self.unregistered_effectful_entrypoints
            ),
            "unguarded_entrypoints": list(self.unguarded_entrypoints),
            "inventory_only_production_entrypoints": list(
                self.inventory_only_production_entrypoints
            ),
            "missing_guard_contracts": list(self.missing_guard_contracts),
            "runtime_conformance_failures": list(
                self.runtime_conformance_failures
            ),
            "fault_injection_failures": list(self.fault_injection_failures),
            "primary_checkout_mutations": list(self.primary_checkout_mutations),
            "owner_approval_enforced": self.owner_approval_enforced,
            "diagnostics": list(self.diagnostics),
            "blockers": list(legacy_blockers),
        }
        body["report_sha256"] = hashlib.sha256(
            _canonical_json(body).encode()
        ).hexdigest()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateReport":
        if not isinstance(payload, Mapping):
            raise ValueError("gate report root must be an object")
        schema = payload.get("schema")
        if not isinstance(schema, str) or schema not in _SUPPORTED_SCHEMAS:
            raise ValueError("unsupported gate report schema")
        expected_fields = _V2_FIELDS if schema == _SCHEMA else _V1_FIELDS
        if set(payload) != expected_fields:
            raise ValueError("gate report shape does not match its schema")
        _verify_serialized_digest(payload)
        if _int_field(payload, "gate") != 0:
            raise ValueError("this report implementation currently supports Gate 0 only")
        report = cls(
            gate=0,
            source_revision=_string_field(payload, "source_revision"),
            registry_sha256=_sha256_value(
                payload.get("registry_sha256"),
                "registry_sha256",
            ),
            security_boundary_claimed=_bool_field(
                payload,
                "security_boundary_claimed",
            ),
            unregistered_effectful_entrypoints=_sequence_field(
                payload,
                "unregistered_effectful_entrypoints",
            ),
            unguarded_entrypoints=_sequence_field(
                payload,
                "unguarded_entrypoints",
            ),
            inventory_only_production_entrypoints=_sequence_field(
                payload,
                "inventory_only_production_entrypoints",
            ),
            missing_guard_contracts=_sequence_field(
                payload,
                "missing_guard_contracts",
            ),
            runtime_conformance_failures=_sequence_field(
                payload,
                "runtime_conformance_failures",
            ),
            fault_injection_failures=_sequence_field(
                payload,
                "fault_injection_failures",
            ),
            primary_checkout_mutations=_sequence_field(
                payload,
                "primary_checkout_mutations",
            ),
            event_store_writer_inventory_sha256=(
                _sha256_or_none(
                    payload.get("event_store_writer_inventory_sha256"),
                    "event_store_writer_inventory_sha256",
                )
                if schema == _SCHEMA
                else None
            ),
            event_store_writer_failures=(
                _sequence_field(payload, "event_store_writer_failures")
                if schema == _SCHEMA
                else ()
            ),
            owner_approval_enforced=_bool_field(
                payload,
                "owner_approval_enforced",
            ),
            diagnostics=_sequence_field(payload, "diagnostics"),
        )
        serialized_closed = _bool_field(payload, "closed")
        serialized_blockers = _sequence_field(payload, "blockers")
        if schema == _SCHEMA:
            if serialized_closed != report.closed:
                raise ValueError("gate report closed flag is inconsistent")
            if serialized_blockers != report.blockers:
                raise ValueError("gate report blockers are inconsistent")
            if dict(payload) != report.to_dict():
                raise ValueError("gate report v2 is noncanonical")
        else:
            expected_legacy = report._legacy_dict()
            if serialized_closed != expected_legacy["closed"]:
                raise ValueError("legacy gate report closed flag is inconsistent")
            if serialized_blockers != tuple(expected_legacy["blockers"]):
                raise ValueError("legacy gate report blockers are inconsistent")
            if dict(payload) != expected_legacy:
                raise ValueError("legacy gate report is noncanonical")
        return report


def _writer_inventory_evidence(
    root: Path,
    source_revision: str,
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    try:
        inventory = scan_event_store_writers(
            root,
            source_revision=source_revision,
        )
    except WriterInventoryError:
        return (
            None,
            ("inventory-refused",),
            ("blocker:event_store_writer_inventory:refused",),
        )
    failures = tuple(
        f"{site.path}:{site.line}:{site.column}:{site.kind}:{site.callee}"
        for site in inventory.blockers
    )
    return inventory.digest, failures, ()


def build_gate0_report(
    repo_root: Path,
    *,
    source_revision: str,
    runtime_receipts: Sequence[RuntimeConformanceReceipt] = (),
    fault_results: Mapping[str, bool] | None = None,
    primary_checkout_mutations: Iterable[str] = (),
    security_boundary_claimed: bool = False,
) -> GateReport:
    root = repo_root.resolve()
    conformance = check_conformance(root)
    unregistered = [
        finding.subject
        for finding in conformance.findings
        if finding.code == "entrypoint.unregistered"
    ]
    unguarded = [
        row.id for row in conformance.matrix if row.wiring is Wiring.UNGUARDED
    ]
    inventory_only = [
        row.id
        for row in conformance.matrix
        if row.wiring is Wiring.INVENTORY_ONLY
    ]
    missing_guards = [
        finding.subject
        for finding in conformance.findings
        if finding.code
        in {"registry.guard_not_implemented", "registry.guard_unknown"}
    ]
    diagnostics = [
        f"{finding.severity}:{finding.code}:{finding.subject}"
        for finding in conformance.findings
    ]
    if runtime_receipts:
        runtime_failures = tuple(
            sorted(
                f"{receipt.receipt_id}:{receipt.status}"
                for receipt in runtime_receipts
                if receipt.status != "passed"
            )
        )
    else:
        runtime_failures = ("runtime-conformance-receipts:not-yet-bound",)
    if fault_results is None:
        fault_failures = ("fault-matrix:not-yet-bound",)
    else:
        fault_failures = tuple(
            sorted(name for name, passed in fault_results.items() if not passed)
        )

    writer_digest, writer_failures, writer_diagnostics = _writer_inventory_evidence(
        root,
        source_revision,
    )
    diagnostics.extend(writer_diagnostics)

    promotion = REGISTRY_BY_ID.get("python.promote_candidates")
    promotion_findings = {
        finding.code
        for finding in conformance.findings
        if finding.subject == "python.promote_candidates"
        and finding.severity == "blocker"
    }
    owner_enforced = bool(
        promotion is not None
        and promotion.wiring in {Wiring.LOCAL_GUARDS, Wiring.CENTRAL}
        and "promotion.owner_approval" in promotion.guard_contracts
        and GUARD_CONTRACT_IMPLEMENTED.get("promotion.owner_approval", False)
        and not promotion_findings
    )
    return GateReport(
        gate=0,
        source_revision=source_revision,
        registry_sha256=conformance.registry_sha256,
        security_boundary_claimed=security_boundary_claimed,
        unregistered_effectful_entrypoints=tuple(unregistered),
        unguarded_entrypoints=tuple(unguarded),
        inventory_only_production_entrypoints=tuple(inventory_only),
        missing_guard_contracts=tuple(missing_guards),
        runtime_conformance_failures=runtime_failures,
        fault_injection_failures=fault_failures,
        primary_checkout_mutations=tuple(primary_checkout_mutations),
        event_store_writer_inventory_sha256=writer_digest,
        event_store_writer_failures=writer_failures,
        owner_approval_enforced=owner_enforced,
        diagnostics=tuple(diagnostics),
    )


def load_gate_report(path: Path) -> GateReport:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError("gate report could not be read") from exc
    if len(raw) > _MAX_REPORT_BYTES:
        raise ValueError("gate report exceeds maximum size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("gate report must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("gate report is malformed JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("gate report root must be an object")
    return GateReport.from_dict(payload)


def assert_monotonic(current: GateReport, baseline: GateReport) -> tuple[str, ...]:
    if current.gate != baseline.gate:
        raise ValueError("cannot compare different gates")
    regressions = sorted(set(current.blockers) - set(baseline.blockers))
    return tuple(regressions)
