"""Deterministic Gate-0 report and monotonic migration comparison."""
from __future__ import annotations

import hashlib
import json
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

_SCHEMA = "daedalus-gate-report/1"
_REPORT_ARRAY_FIELDS = (
    "unregistered_effectful_entrypoints",
    "unguarded_entrypoints",
    "inventory_only_production_entrypoints",
    "missing_guard_contracts",
    "runtime_conformance_failures",
    "fault_injection_failures",
    "primary_checkout_mutations",
    "diagnostics",
)
_REPORT_WIRE_FIELDS = frozenset(
    {
        "schema",
        "gate",
        "source_revision",
        "registry_sha256",
        "closed",
        "security_boundary_claimed",
        *_REPORT_ARRAY_FIELDS,
        "owner_approval_enforced",
        "blockers",
        "report_sha256",
    }
)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sorted_unique(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be an iterable of strings")
    retained = tuple(values)
    if any(not isinstance(value, str) or not value for value in retained):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return tuple(sorted(set(retained)))


def _wire_string_array(wire: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    value = wire[field_name]
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{field_name} must be an array of non-empty strings")
    return tuple(value)


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
    owner_approval_enforced: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.gate) is not int or self.gate != 0:
            raise ValueError("this report implementation currently supports integer Gate 0 only")
        if not isinstance(self.source_revision, str) or not self.source_revision or len(self.source_revision) > 200:
            raise ValueError("source_revision must be a non-empty bounded string")
        if not isinstance(self.registry_sha256, str) or len(self.registry_sha256) != 64:
            raise ValueError("registry_sha256 must be a sha256 hex digest")
        try:
            int(self.registry_sha256, 16)
        except ValueError as exc:
            raise ValueError("registry_sha256 must be a sha256 hex digest") from exc
        if type(self.security_boundary_claimed) is not bool:
            raise ValueError("security_boundary_claimed must be boolean")
        if type(self.owner_approval_enforced) is not bool:
            raise ValueError("owner_approval_enforced must be boolean")
        for name in _REPORT_ARRAY_FIELDS:
            object.__setattr__(
                self,
                name,
                _sorted_unique(getattr(self, name), name),
            )

    @property
    def closed(self) -> bool:
        return (
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
        ):
            rows.extend(f"{field_name}:{item}" for item in getattr(self, field_name))
        if not self.security_boundary_claimed:
            rows.append("security_boundary_claimed:false")
        if not self.owner_approval_enforced:
            rows.append("owner_approval_enforced:false")
        return tuple(sorted(rows))

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": _SCHEMA,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "registry_sha256": self.registry_sha256,
            "closed": self.closed,
            "security_boundary_claimed": self.security_boundary_claimed,
            "unregistered_effectful_entrypoints": list(self.unregistered_effectful_entrypoints),
            "unguarded_entrypoints": list(self.unguarded_entrypoints),
            "inventory_only_production_entrypoints": list(self.inventory_only_production_entrypoints),
            "missing_guard_contracts": list(self.missing_guard_contracts),
            "runtime_conformance_failures": list(self.runtime_conformance_failures),
            "fault_injection_failures": list(self.fault_injection_failures),
            "primary_checkout_mutations": list(self.primary_checkout_mutations),
            "owner_approval_enforced": self.owner_approval_enforced,
            "diagnostics": list(self.diagnostics),
            "blockers": list(self.blockers),
        }
        body["report_sha256"] = hashlib.sha256(_canonical_json(body).encode()).hexdigest()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateReport":
        if not isinstance(payload, Mapping):
            raise ValueError("gate report root must be an object")
        wire = dict(payload)
        if set(wire) != _REPORT_WIRE_FIELDS:
            missing = sorted(_REPORT_WIRE_FIELDS - set(wire))
            unknown = sorted(set(wire) - _REPORT_WIRE_FIELDS)
            raise ValueError(
                "gate report fields must match the canonical wire"
                f"; missing={missing}; unknown={unknown}"
            )
        if wire["schema"] != _SCHEMA:
            raise ValueError("unsupported gate report schema")
        if type(wire["gate"]) is not int:
            raise ValueError("gate must be an integer")
        if not isinstance(wire["source_revision"], str):
            raise ValueError("source_revision must be a string")
        if not isinstance(wire["registry_sha256"], str):
            raise ValueError("registry_sha256 must be a string")
        if type(wire["security_boundary_claimed"]) is not bool:
            raise ValueError("security_boundary_claimed must be boolean")
        if type(wire["owner_approval_enforced"]) is not bool:
            raise ValueError("owner_approval_enforced must be boolean")
        if type(wire["closed"]) is not bool:
            raise ValueError("closed must be boolean")
        if not isinstance(wire["report_sha256"], str) or len(wire["report_sha256"]) != 64:
            raise ValueError("report_sha256 must be a sha256 hex digest")
        try:
            int(wire["report_sha256"], 16)
        except ValueError as exc:
            raise ValueError("report_sha256 must be a sha256 hex digest") from exc
        arrays = {
            field_name: _wire_string_array(wire, field_name)
            for field_name in (*_REPORT_ARRAY_FIELDS, "blockers")
        }
        body = dict(wire)
        expected = body.pop("report_sha256")
        actual = hashlib.sha256(_canonical_json(body).encode()).hexdigest()
        if expected != actual:
            raise ValueError("gate report digest mismatch")
        value = cls(
            gate=wire["gate"],
            source_revision=wire["source_revision"],
            registry_sha256=wire["registry_sha256"],
            security_boundary_claimed=wire["security_boundary_claimed"],
            unregistered_effectful_entrypoints=arrays["unregistered_effectful_entrypoints"],
            unguarded_entrypoints=arrays["unguarded_entrypoints"],
            inventory_only_production_entrypoints=arrays["inventory_only_production_entrypoints"],
            missing_guard_contracts=arrays["missing_guard_contracts"],
            runtime_conformance_failures=arrays["runtime_conformance_failures"],
            fault_injection_failures=arrays["fault_injection_failures"],
            primary_checkout_mutations=arrays["primary_checkout_mutations"],
            owner_approval_enforced=wire["owner_approval_enforced"],
            diagnostics=arrays["diagnostics"],
        )
        if wire != value.to_dict():
            raise ValueError("gate report must use the exact canonical wire")
        return value


def render_gate_report(report: GateReport) -> str:
    """Return the exact UTF-8 text emitted by the read-only Gate-report CLI."""

    if not isinstance(report, GateReport):
        raise ValueError("report must be GateReport")
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


def gate_report_artifact_sha256(report: GateReport) -> str:
    """Hash the exact serialized Gate-report artifact bytes, not its inner digest."""

    return hashlib.sha256(render_gate_report(report).encode("utf-8")).hexdigest()


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
    unguarded = [row.id for row in conformance.matrix if row.wiring is Wiring.UNGUARDED]
    inventory = [row.id for row in conformance.matrix if row.wiring is Wiring.INVENTORY_ONLY]
    missing_guards = [
        finding.subject
        for finding in conformance.findings
        if finding.code in {"registry.guard_not_implemented", "registry.guard_unknown"}
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
        fault_failures = tuple(sorted(name for name, passed in fault_results.items() if not passed))

    promotion = REGISTRY_BY_ID.get("python.promote_candidates")
    promotion_findings = {
        finding.code
        for finding in conformance.findings
        if finding.subject == "python.promote_candidates" and finding.severity == "blocker"
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
        inventory_only_production_entrypoints=tuple(inventory),
        missing_guard_contracts=tuple(missing_guards),
        runtime_conformance_failures=runtime_failures,
        fault_injection_failures=fault_failures,
        primary_checkout_mutations=tuple(primary_checkout_mutations),
        owner_approval_enforced=owner_enforced,
        diagnostics=tuple(diagnostics),
    )


def load_gate_report(path: Path) -> GateReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("gate report root must be an object")
    return GateReport.from_dict(payload)


def assert_monotonic(current: GateReport, baseline: GateReport) -> tuple[str, ...]:
    if current.gate != baseline.gate:
        raise ValueError("cannot compare different gates")
    regressions = sorted(set(current.blockers) - set(baseline.blockers))
    return tuple(regressions)
