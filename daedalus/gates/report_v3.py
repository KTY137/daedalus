"""Additive GateReport-v3 binding the canonical repository-write inventory.

The existing GateReport-v2 import path remains unchanged.  This strangler model
adds mandatory repository-write inventory identity and blocker fields so a
future release verifier cannot infer mutation safety from the entrypoint registry
alone.  It does not issue a release receipt, approval, promotion, or Gate close.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from daedalus.schemas import RuntimeConformanceReceipt
from daedalus.spine.envelope import canonical_json

from .report import GateReport, build_gate0_report
from .repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2Error,
    scan_repository_write_surfaces_v2,
)


_SCHEMA = "daedalus-gate-report/3"
_MAX_REPORT_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_V2_SHARED_FIELDS = {
    "gate",
    "source_revision",
    "registry_sha256",
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
}
_V3_FIELDS = frozenset(
    {
        "schema",
        "closed",
        "blockers",
        "report_sha256",
        "repository_write_inventory_sha256",
        "repository_write_scan_input_sha256",
        "repository_write_files_scanned",
        "repository_write_inventory_generation",
        "repository_write_failures",
        *_V2_SHARED_FIELDS,
    }
)


class GateReportV3Error(ValueError):
    """GateReport-v3 input is malformed or non-canonical."""


def _sha256_or_none(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GateReportV3Error(f"{label} must be lowercase sha256 or null")
    return value


def _strict_bool(payload: Mapping[str, Any], name: str) -> bool:
    value = payload.get(name)
    if type(value) is not bool:
        raise GateReportV3Error(f"{name} must be a boolean")
    return value


def _strict_int(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name)
    if type(value) is not int:
        raise GateReportV3Error(f"{name} must be an integer")
    return value


def _strict_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise GateReportV3Error(f"{name} must be a bounded non-empty string")
    return value


def _strict_rows(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise GateReportV3Error(f"{name} must be an array")
    if any(not isinstance(row, str) or not row or len(row) > 4000 for row in value):
        raise GateReportV3Error(f"{name} must contain bounded strings")
    if value != sorted(set(value)):
        raise GateReportV3Error(f"{name} must be sorted and unique")
    return tuple(value)


def _normalize_rows(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise GateReportV3Error(f"{label} must be a sequence of strings")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise GateReportV3Error(
            f"{label} must be a sequence of strings"
        ) from exc
    if any(not isinstance(row, str) or not row or len(row) > 4000 for row in rows):
        raise GateReportV3Error(f"{label} contains an invalid row")
    return tuple(sorted(set(rows)))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GateReportV3Error(f"duplicate GateReport-v3 key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise GateReportV3Error(f"non-finite GateReport-v3 constant: {value}")


@dataclass(frozen=True)
class GateReportV3(GateReport):
    """GateReport-v2 plus exact canonical repository-write inventory evidence."""

    repository_write_inventory_sha256: str | None = None
    repository_write_scan_input_sha256: str | None = None
    repository_write_files_scanned: int = 0
    repository_write_inventory_generation: int = 0
    repository_write_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "repository_write_inventory_sha256",
            _sha256_or_none(
                self.repository_write_inventory_sha256,
                "repository_write_inventory_sha256",
            ),
        )
        object.__setattr__(
            self,
            "repository_write_scan_input_sha256",
            _sha256_or_none(
                self.repository_write_scan_input_sha256,
                "repository_write_scan_input_sha256",
            ),
        )
        if (
            type(self.repository_write_files_scanned) is not int
            or self.repository_write_files_scanned < 0
        ):
            raise GateReportV3Error(
                "repository_write_files_scanned must be a non-negative integer"
            )
        if (
            type(self.repository_write_inventory_generation) is not int
            or self.repository_write_inventory_generation < 0
        ):
            raise GateReportV3Error(
                "repository_write_inventory_generation must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "repository_write_failures",
            _normalize_rows(
                self.repository_write_failures,
                "repository_write_failures",
            ),
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        base_property = GateReport.blockers.fget
        if base_property is None:  # pragma: no cover - property contract invariant
            raise GateReportV3Error("GateReport blockers property is unavailable")
        rows = list(base_property(self))
        if self.repository_write_inventory_sha256 is None:
            rows.append("repository_write_inventory_sha256:missing")
        if self.repository_write_scan_input_sha256 is None:
            rows.append("repository_write_scan_input_sha256:missing")
        if self.repository_write_files_scanned < 1:
            rows.append("repository_write_files_scanned:missing")
        if self.repository_write_inventory_generation != 2:
            rows.append(
                "repository_write_inventory_generation:unsupported:"
                f"{self.repository_write_inventory_generation}"
            )
        rows.extend(
            f"repository_write_failures:{row}"
            for row in self.repository_write_failures
        )
        return tuple(sorted(set(rows)))

    @property
    def closed(self) -> bool:
        return bool(
            self.security_boundary_claimed
            and self.owner_approval_enforced
            and not self.blockers
        )

    def _body_v3(self) -> dict[str, Any]:
        body = GateReport._body_v2(self)
        body["schema"] = _SCHEMA
        body["repository_write_inventory_sha256"] = (
            self.repository_write_inventory_sha256
        )
        body["repository_write_scan_input_sha256"] = (
            self.repository_write_scan_input_sha256
        )
        body["repository_write_files_scanned"] = (
            self.repository_write_files_scanned
        )
        body["repository_write_inventory_generation"] = (
            self.repository_write_inventory_generation
        )
        body["repository_write_failures"] = list(
            self.repository_write_failures
        )
        body["closed"] = self.closed
        body["blockers"] = list(self.blockers)
        return body

    def to_dict(self) -> dict[str, Any]:
        body = self._body_v3()
        body["report_sha256"] = hashlib.sha256(
            canonical_json(body).encode("ascii")
        ).hexdigest()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateReportV3":
        if not isinstance(payload, Mapping):
            raise GateReportV3Error("GateReport-v3 root must be an object")
        if set(payload) != _V3_FIELDS:
            raise GateReportV3Error("GateReport-v3 fields are not exact")
        if payload.get("schema") != _SCHEMA:
            raise GateReportV3Error("unsupported GateReport-v3 schema")
        claimed_digest = _sha256_or_none(payload.get("report_sha256"), "report_sha256")
        if claimed_digest is None:
            raise GateReportV3Error("report_sha256 is required")
        digest_body = dict(payload)
        digest_body.pop("report_sha256")
        actual_digest = hashlib.sha256(
            canonical_json(digest_body).encode("ascii")
        ).hexdigest()
        if claimed_digest != actual_digest:
            raise GateReportV3Error("GateReport-v3 digest mismatch")

        report = cls(
            gate=_strict_int(payload, "gate"),
            source_revision=_strict_string(payload, "source_revision"),
            registry_sha256=_strict_string(payload, "registry_sha256"),
            security_boundary_claimed=_strict_bool(
                payload, "security_boundary_claimed"
            ),
            unregistered_effectful_entrypoints=_strict_rows(
                payload, "unregistered_effectful_entrypoints"
            ),
            unguarded_entrypoints=_strict_rows(
                payload, "unguarded_entrypoints"
            ),
            inventory_only_production_entrypoints=_strict_rows(
                payload, "inventory_only_production_entrypoints"
            ),
            missing_guard_contracts=_strict_rows(
                payload, "missing_guard_contracts"
            ),
            runtime_conformance_failures=_strict_rows(
                payload, "runtime_conformance_failures"
            ),
            fault_injection_failures=_strict_rows(
                payload, "fault_injection_failures"
            ),
            primary_checkout_mutations=_strict_rows(
                payload, "primary_checkout_mutations"
            ),
            event_store_writer_inventory_sha256=_sha256_or_none(
                payload.get("event_store_writer_inventory_sha256"),
                "event_store_writer_inventory_sha256",
            ),
            event_store_writer_failures=_strict_rows(
                payload, "event_store_writer_failures"
            ),
            owner_approval_enforced=_strict_bool(
                payload, "owner_approval_enforced"
            ),
            diagnostics=_strict_rows(payload, "diagnostics"),
            repository_write_inventory_sha256=_sha256_or_none(
                payload.get("repository_write_inventory_sha256"),
                "repository_write_inventory_sha256",
            ),
            repository_write_scan_input_sha256=_sha256_or_none(
                payload.get("repository_write_scan_input_sha256"),
                "repository_write_scan_input_sha256",
            ),
            repository_write_files_scanned=_strict_int(
                payload, "repository_write_files_scanned"
            ),
            repository_write_inventory_generation=_strict_int(
                payload, "repository_write_inventory_generation"
            ),
            repository_write_failures=_strict_rows(
                payload, "repository_write_failures"
            ),
        )
        _strict_bool(payload, "closed")
        _strict_rows(payload, "blockers")
        if dict(payload) != report.to_dict():
            raise GateReportV3Error("GateReport-v3 is non-canonical")
        return report


def _repository_write_evidence(
    root: Path,
    *,
    source_revision: str,
) -> tuple[str | None, str | None, int, int, tuple[str, ...], tuple[str, ...]]:
    try:
        inventory = scan_repository_write_surfaces_v2(
            root,
            source_revision=source_revision,
        )
    except RepositoryWriteInventoryV2Error:
        return (
            None,
            None,
            0,
            0,
            ("inventory-refused",),
            ("blocker:repository_write_inventory:refused",),
        )
    failures = tuple(
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        for surface in inventory.blockers
    )
    return (
        inventory.digest,
        inventory.scan_input_sha256,
        inventory.files_scanned,
        2,
        failures,
        (),
    )


def build_gate0_report_v3(
    repo_root: Path,
    *,
    source_revision: str,
    runtime_receipts: Sequence[RuntimeConformanceReceipt] = (),
    fault_results: Mapping[str, bool] | None = None,
    primary_checkout_mutations: Iterable[str] = (),
    security_boundary_claimed: bool = False,
) -> GateReportV3:
    """Build v2 evidence plus the exact canonical repository-write inventory."""

    root = repo_root.resolve()
    base = build_gate0_report(
        root,
        source_revision=source_revision,
        runtime_receipts=runtime_receipts,
        fault_results=fault_results,
        primary_checkout_mutations=primary_checkout_mutations,
        security_boundary_claimed=security_boundary_claimed,
    )
    (
        inventory_digest,
        scan_input_digest,
        files_scanned,
        generation,
        failures,
        diagnostics,
    ) = _repository_write_evidence(root, source_revision=source_revision)
    base_fields = {
        field.name: getattr(base, field.name)
        for field in dataclasses.fields(GateReport)
    }
    base_fields["diagnostics"] = tuple(
        sorted(set(base.diagnostics).union(diagnostics))
    )
    return GateReportV3(
        **base_fields,
        repository_write_inventory_sha256=inventory_digest,
        repository_write_scan_input_sha256=scan_input_digest,
        repository_write_files_scanned=files_scanned,
        repository_write_inventory_generation=generation,
        repository_write_failures=failures,
    )


def load_gate_report_v3(path: str | Path) -> GateReportV3:
    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise GateReportV3Error("GateReport-v3 could not be read") from exc
    if len(raw) > _MAX_REPORT_BYTES:
        raise GateReportV3Error("GateReport-v3 exceeds maximum size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateReportV3Error("GateReport-v3 must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise GateReportV3Error("GateReport-v3 is malformed JSON") from exc
    return GateReportV3.from_dict(payload)


def assert_monotonic_v3(
    current: GateReportV3,
    baseline: GateReportV3,
) -> tuple[str, ...]:
    if type(current) is not GateReportV3 or type(baseline) is not GateReportV3:
        raise GateReportV3Error("monotonic comparison requires exact GateReportV3")
    if current.gate != baseline.gate:
        raise GateReportV3Error("cannot compare different gates")
    return tuple(sorted(set(current.blockers) - set(baseline.blockers)))


__all__ = [
    "GateReportV3",
    "GateReportV3Error",
    "assert_monotonic_v3",
    "build_gate0_report_v3",
    "load_gate_report_v3",
]
