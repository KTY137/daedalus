"""Revision-bound Gate-0 baseline and monotonic blocker assessment.

The baseline is a deterministic, tamper-evident projection of one canonical
GateReport-v2.  It is not self-authenticating: callers must pin its digest in a
separate trusted revision, evidence index or owner decision.  The comparison
API therefore requires the expected baseline digest explicitly and never
accepts an unpinned baseline as release evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .report import GateReport, load_gate_report


_BASELINE_SCHEMA = "daedalus-gate-baseline/2"
_MONOTONICITY_SCHEMA = "daedalus-gate-monotonicity/2"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MAX_BASELINE_BYTES = 2 * 1024 * 1024
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024


class GateBaselineError(RuntimeError):
    """A Gate baseline or monotonicity assessment is malformed or unbound."""


class GateBaselineBindingError(GateBaselineError):
    """A supplied report, revision or externally pinned digest disagrees."""


@dataclass(frozen=True)
class GateBaseline:
    baseline_id: str
    gate: int
    source_revision: str
    source_tree_revision: str
    gate_report_sha256: str
    gate_report_artifact_sha256: str
    registry_sha256: str
    event_store_writer_inventory_sha256: str
    blockers: tuple[str, ...]
    blocker_set_sha256: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "baseline_id",
            _identifier(self.baseline_id, "baseline_id"),
        )
        if type(self.gate) is not int or self.gate != 0:
            raise ValueError("Gate baseline currently supports Gate 0 only")
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
        for name in (
            "gate_report_sha256",
            "gate_report_artifact_sha256",
            "registry_sha256",
            "event_store_writer_inventory_sha256",
            "blocker_set_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "blockers",
            _rows(self.blockers, "blockers"),
        )
        expected_blocker_sha = _sha256_json(list(self.blockers))
        if self.blocker_set_sha256 != expected_blocker_sha:
            raise ValueError("blocker_set_sha256 does not bind blockers")
        object.__setattr__(
            self,
            "created_at",
            _utc_timestamp(self.created_at, "created_at"),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": _BASELINE_SCHEMA,
            "baseline_id": self.baseline_id,
            "gate": self.gate,
            "source_revision": self.source_revision,
            "source_tree_revision": self.source_tree_revision,
            "gate_report_sha256": self.gate_report_sha256,
            "gate_report_artifact_sha256": self.gate_report_artifact_sha256,
            "registry_sha256": self.registry_sha256,
            "event_store_writer_inventory_sha256": (
                self.event_store_writer_inventory_sha256
            ),
            "blockers": list(self.blockers),
            "blocker_set_sha256": self.blocker_set_sha256,
            "created_at": self.created_at,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "baseline_sha256": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GateBaseline":
        expected_fields = {
            "schema",
            "baseline_id",
            "gate",
            "source_revision",
            "source_tree_revision",
            "gate_report_sha256",
            "gate_report_artifact_sha256",
            "registry_sha256",
            "event_store_writer_inventory_sha256",
            "blockers",
            "blocker_set_sha256",
            "created_at",
            "baseline_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_fields:
            raise ValueError("Gate baseline shape is not exact")
        if payload.get("schema") != _BASELINE_SCHEMA:
            raise ValueError("unsupported Gate baseline schema")
        baseline = cls(
            baseline_id=payload["baseline_id"],
            gate=payload["gate"],
            source_revision=payload["source_revision"],
            source_tree_revision=payload["source_tree_revision"],
            gate_report_sha256=payload["gate_report_sha256"],
            gate_report_artifact_sha256=payload[
                "gate_report_artifact_sha256"
            ],
            registry_sha256=payload["registry_sha256"],
            event_store_writer_inventory_sha256=payload[
                "event_store_writer_inventory_sha256"
            ],
            blockers=_json_rows(payload["blockers"], "blockers"),
            blocker_set_sha256=payload["blocker_set_sha256"],
            created_at=payload["created_at"],
        )
        claimed = _sha256(payload["baseline_sha256"], "baseline_sha256")
        if not _constant_time_equal(claimed, baseline.digest):
            raise ValueError("Gate baseline digest mismatch")
        if dict(payload) != baseline.to_dict():
            raise ValueError("Gate baseline is not canonical")
        return baseline


@dataclass(frozen=True)
class GateMonotonicityReceipt:
    assessment_id: str
    gate: int
    baseline_sha256: str
    baseline_source_revision: str
    baseline_source_tree_revision: str
    current_source_revision: str
    current_source_tree_revision: str
    current_gate_report_sha256: str
    current_gate_report_artifact_sha256: str
    current_registry_sha256: str
    current_event_store_writer_inventory_sha256: str | None
    retained_blockers: tuple[str, ...]
    resolved_blockers: tuple[str, ...]
    new_blockers: tuple[str, ...]
    status: str
    assessed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assessment_id",
            _identifier(self.assessment_id, "assessment_id"),
        )
        if type(self.gate) is not int or self.gate != 0:
            raise ValueError("monotonicity receipt currently supports Gate 0 only")
        object.__setattr__(
            self,
            "baseline_sha256",
            _sha256(self.baseline_sha256, "baseline_sha256"),
        )
        for name in (
            "baseline_source_revision",
            "baseline_source_tree_revision",
            "current_source_revision",
            "current_source_tree_revision",
        ):
            object.__setattr__(self, name, _revision(getattr(self, name), name))
        for name in (
            "current_gate_report_sha256",
            "current_gate_report_artifact_sha256",
            "current_registry_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if self.current_event_store_writer_inventory_sha256 is not None:
            object.__setattr__(
                self,
                "current_event_store_writer_inventory_sha256",
                _sha256(
                    self.current_event_store_writer_inventory_sha256,
                    "current_event_store_writer_inventory_sha256",
                ),
            )
        for name in (
            "retained_blockers",
            "resolved_blockers",
            "new_blockers",
        ):
            object.__setattr__(self, name, _rows(getattr(self, name), name))
        blocker_sets = (
            set(self.retained_blockers),
            set(self.resolved_blockers),
            set(self.new_blockers),
        )
        if any(
            left & right
            for index, left in enumerate(blocker_sets)
            for right in blocker_sets[index + 1 :]
        ):
            raise ValueError("monotonicity blocker partitions must be disjoint")
        expected_status = "passed" if not self.new_blockers else "failed"
        if self.status != expected_status:
            raise ValueError("monotonicity status does not match new blockers")
        object.__setattr__(
            self,
            "assessed_at",
            _utc_timestamp(self.assessed_at, "assessed_at"),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": _MONOTONICITY_SCHEMA,
            "assessment_id": self.assessment_id,
            "gate": self.gate,
            "baseline_sha256": self.baseline_sha256,
            "baseline_source_revision": self.baseline_source_revision,
            "baseline_source_tree_revision": self.baseline_source_tree_revision,
            "current_source_revision": self.current_source_revision,
            "current_source_tree_revision": self.current_source_tree_revision,
            "current_gate_report_sha256": self.current_gate_report_sha256,
            "current_gate_report_artifact_sha256": (
                self.current_gate_report_artifact_sha256
            ),
            "current_registry_sha256": self.current_registry_sha256,
            "current_event_store_writer_inventory_sha256": (
                self.current_event_store_writer_inventory_sha256
            ),
            "retained_blockers": list(self.retained_blockers),
            "resolved_blockers": list(self.resolved_blockers),
            "new_blockers": list(self.new_blockers),
            "status": self.status,
            "assessed_at": self.assessed_at,
        }

    @property
    def digest(self) -> str:
        return _sha256_json(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_sha256": self.digest}

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "GateMonotonicityReceipt":
        expected_fields = {
            "schema",
            "assessment_id",
            "gate",
            "baseline_sha256",
            "baseline_source_revision",
            "baseline_source_tree_revision",
            "current_source_revision",
            "current_source_tree_revision",
            "current_gate_report_sha256",
            "current_gate_report_artifact_sha256",
            "current_registry_sha256",
            "current_event_store_writer_inventory_sha256",
            "retained_blockers",
            "resolved_blockers",
            "new_blockers",
            "status",
            "assessed_at",
            "receipt_sha256",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_fields:
            raise ValueError("monotonicity receipt shape is not exact")
        if payload.get("schema") != _MONOTONICITY_SCHEMA:
            raise ValueError("unsupported monotonicity receipt schema")
        receipt = cls(
            assessment_id=payload["assessment_id"],
            gate=payload["gate"],
            baseline_sha256=payload["baseline_sha256"],
            baseline_source_revision=payload["baseline_source_revision"],
            baseline_source_tree_revision=payload[
                "baseline_source_tree_revision"
            ],
            current_source_revision=payload["current_source_revision"],
            current_source_tree_revision=payload[
                "current_source_tree_revision"
            ],
            current_gate_report_sha256=payload[
                "current_gate_report_sha256"
            ],
            current_gate_report_artifact_sha256=payload[
                "current_gate_report_artifact_sha256"
            ],
            current_registry_sha256=payload["current_registry_sha256"],
            current_event_store_writer_inventory_sha256=payload[
                "current_event_store_writer_inventory_sha256"
            ],
            retained_blockers=_json_rows(
                payload["retained_blockers"],
                "retained_blockers",
            ),
            resolved_blockers=_json_rows(
                payload["resolved_blockers"],
                "resolved_blockers",
            ),
            new_blockers=_json_rows(payload["new_blockers"], "new_blockers"),
            status=payload["status"],
            assessed_at=payload["assessed_at"],
        )
        claimed = _sha256(payload["receipt_sha256"], "receipt_sha256")
        if not _constant_time_equal(claimed, receipt.digest):
            raise ValueError("monotonicity receipt digest mismatch")
        if dict(payload) != receipt.to_dict():
            raise ValueError("monotonicity receipt is not canonical")
        return receipt


def create_gate0_baseline(
    report: GateReport,
    *,
    baseline_id: str,
    source_tree_revision: str,
    created_at: str,
) -> GateBaseline:
    """Create an immutable baseline projection from one canonical v2 report."""
    if not isinstance(report, GateReport):
        raise GateBaselineBindingError("report must be GateReport")
    writer_digest = report.event_store_writer_inventory_sha256
    if writer_digest is None:
        raise GateBaselineBindingError(
            "Gate baseline requires a bound Event-Store writer inventory"
        )
    payload = report.to_dict()
    return GateBaseline(
        baseline_id=baseline_id,
        gate=report.gate,
        source_revision=report.source_revision,
        source_tree_revision=source_tree_revision,
        gate_report_sha256=payload["report_sha256"],
        gate_report_artifact_sha256=_sha256_json(payload),
        registry_sha256=report.registry_sha256,
        event_store_writer_inventory_sha256=writer_digest,
        blockers=report.blockers,
        blocker_set_sha256=_sha256_json(list(report.blockers)),
        created_at=created_at,
    )


def assess_gate0_monotonicity(
    baseline: GateBaseline,
    current: GateReport,
    *,
    expected_baseline_sha256: str,
    current_source_tree_revision: str,
    assessment_id: str,
    assessed_at: str,
) -> GateMonotonicityReceipt:
    """Compare blocker sets against one externally pinned baseline digest."""
    if not isinstance(baseline, GateBaseline):
        raise GateBaselineBindingError("baseline must be GateBaseline")
    if not isinstance(current, GateReport):
        raise GateBaselineBindingError("current must be GateReport")
    expected_digest = _sha256(
        expected_baseline_sha256,
        "expected_baseline_sha256",
    )
    if not _constant_time_equal(expected_digest, baseline.digest):
        raise GateBaselineBindingError("expected baseline digest mismatch")
    if current.gate != baseline.gate:
        raise GateBaselineBindingError("baseline and current gate differ")
    current_payload = current.to_dict()
    baseline_blockers = set(baseline.blockers)
    current_blockers = set(current.blockers)
    retained = tuple(sorted(baseline_blockers & current_blockers))
    resolved = tuple(sorted(baseline_blockers - current_blockers))
    new = tuple(sorted(current_blockers - baseline_blockers))
    return GateMonotonicityReceipt(
        assessment_id=assessment_id,
        gate=current.gate,
        baseline_sha256=baseline.digest,
        baseline_source_revision=baseline.source_revision,
        baseline_source_tree_revision=baseline.source_tree_revision,
        current_source_revision=current.source_revision,
        current_source_tree_revision=current_source_tree_revision,
        current_gate_report_sha256=current_payload["report_sha256"],
        current_gate_report_artifact_sha256=_sha256_json(current_payload),
        current_registry_sha256=current.registry_sha256,
        current_event_store_writer_inventory_sha256=(
            current.event_store_writer_inventory_sha256
        ),
        retained_blockers=retained,
        resolved_blockers=resolved,
        new_blockers=new,
        status="passed" if not new else "failed",
        assessed_at=assessed_at,
    )


def load_gate0_baseline(path: str | Path) -> GateBaseline:
    payload = _load_json_object(path, max_bytes=_MAX_BASELINE_BYTES)
    return GateBaseline.from_dict(payload)


def load_gate0_monotonicity_receipt(
    path: str | Path,
) -> GateMonotonicityReceipt:
    payload = _load_json_object(path, max_bytes=_MAX_RECEIPT_BYTES)
    return GateMonotonicityReceipt.from_dict(payload)


def load_current_gate_report(path: str | Path) -> GateReport:
    report = load_gate_report(Path(path))
    if report.event_store_writer_inventory_sha256 is None:
        raise GateBaselineBindingError(
            "current Gate report must be v2 with writer inventory evidence"
        )
    return report


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identifier")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase sha256 digest")
    return value


def _revision(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase 40-hex revision")
    return value


def _rows(values: Iterable[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence of strings")
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a sequence of strings") from exc
    if any(
        not isinstance(row, str) or not row or len(row) > 4000
        for row in rows
    ):
        raise ValueError(f"{name} contains an invalid string")
    canonical = tuple(sorted(set(rows)))
    return canonical


def _json_rows(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    rows = _rows(value, name)
    if list(rows) != value:
        raise ValueError(f"{name} must be sorted and unique")
    return rows


def _utc_timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _load_json_object(path: str | Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise GateBaselineError("evidence file could not be read") from exc
    if len(raw) > max_bytes:
        raise GateBaselineError("evidence file exceeds maximum size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateBaselineError("evidence file must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise GateBaselineError("evidence file is malformed JSON") from exc
    if not isinstance(payload, dict):
        raise GateBaselineError("evidence root must be an object")
    return payload


__all__ = [
    "GateBaseline",
    "GateBaselineBindingError",
    "GateBaselineError",
    "GateMonotonicityReceipt",
    "assess_gate0_monotonicity",
    "create_gate0_baseline",
    "load_current_gate_report",
    "load_gate0_baseline",
    "load_gate0_monotonicity_receipt",
]
