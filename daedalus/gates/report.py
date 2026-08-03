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


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


@dataclass(frozen=True)
class GateReport:
    gate: int
    source_revision: str
    registry_sha256: str
    security_boundary_claimed: bool
    unregistered_effectful_entrypoints: tuple[str, ...] = ()
    noncentral_entrypoints: tuple[str, ...] = ()
    unguarded_entrypoints: tuple[str, ...] = ()
    inventory_only_production_entrypoints: tuple[str, ...] = ()
    missing_guard_contracts: tuple[str, ...] = ()
    runtime_conformance_failures: tuple[str, ...] = ()
    fault_injection_failures: tuple[str, ...] = ()
    primary_checkout_mutations: tuple[str, ...] = ()
    owner_approval_enforced: bool = False
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.gate != 0:
            raise ValueError("this report implementation currently supports Gate 0 only")
        if not self.source_revision or len(self.source_revision) > 200:
            raise ValueError("source_revision must be a non-empty bounded string")
        if len(self.registry_sha256) != 64:
            raise ValueError("registry_sha256 must be a sha256 hex digest")
        int(self.registry_sha256, 16)
        for name in (
            "unregistered_effectful_entrypoints",
            "noncentral_entrypoints",
            "unguarded_entrypoints",
            "inventory_only_production_entrypoints",
            "missing_guard_contracts",
            "runtime_conformance_failures",
            "fault_injection_failures",
            "primary_checkout_mutations",
            "diagnostics",
        ):
            object.__setattr__(self, name, _sorted_unique(getattr(self, name)))

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
            "noncentral_entrypoints",
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
            "noncentral_entrypoints": list(self.noncentral_entrypoints),
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
        if payload.get("schema") != _SCHEMA:
            raise ValueError("unsupported gate report schema")
        expected = payload.get("report_sha256")
        if expected is not None:
            body = dict(payload)
            body.pop("report_sha256", None)
            actual = hashlib.sha256(_canonical_json(body).encode()).hexdigest()
            if expected != actual:
                raise ValueError("gate report digest mismatch")
        return cls(
            gate=int(payload["gate"]),
            source_revision=str(payload["source_revision"]),
            registry_sha256=str(payload["registry_sha256"]),
            security_boundary_claimed=bool(payload["security_boundary_claimed"]),
            unregistered_effectful_entrypoints=tuple(payload.get("unregistered_effectful_entrypoints", ())),
            noncentral_entrypoints=tuple(payload.get("noncentral_entrypoints", ())),
            unguarded_entrypoints=tuple(payload.get("unguarded_entrypoints", ())),
            inventory_only_production_entrypoints=tuple(payload.get("inventory_only_production_entrypoints", ())),
            missing_guard_contracts=tuple(payload.get("missing_guard_contracts", ())),
            runtime_conformance_failures=tuple(payload.get("runtime_conformance_failures", ())),
            fault_injection_failures=tuple(payload.get("fault_injection_failures", ())),
            primary_checkout_mutations=tuple(payload.get("primary_checkout_mutations", ())),
            owner_approval_enforced=bool(payload.get("owner_approval_enforced", False)),
            diagnostics=tuple(payload.get("diagnostics", ())),
        )


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
    noncentral = [row.id for row in conformance.matrix if row.wiring is not Wiring.CENTRAL]
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
        noncentral_entrypoints=tuple(noncentral),
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
