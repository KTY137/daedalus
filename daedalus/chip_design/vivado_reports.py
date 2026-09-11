"""Strict, stdlib-only parsers for native AMD Vivado report text.

Every parser returns an explicit ``parsed``, ``missing`` or ``unparseable``
state.  A missing section is therefore never flattened into zero violations,
and process exit success cannot masquerade as timing, DRC, or routing evidence.
The original report bytes remain the authoritative audit artifact; SHA-256 and
byte length here bind normalized metrics back to those bytes.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping


_MAX_REPORT_BYTES = 64 * 1024 * 1024
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_TIMING_ROW = re.compile(
    rf"^\s*({_NUMBER})\s+({_NUMBER})\s+(\d+)\s+(\d+)\s+"
    rf"({_NUMBER})\s+({_NUMBER})\s+(\d+)\s+(\d+)\s+"
    rf"({_NUMBER})\s+({_NUMBER})\s+(\d+)\s+(\d+)\s*$"
)
_CHECK_TIMING = re.compile(r"^\s*\d+\.\s+checking\s+([A-Za-z0-9_]+)\s+\((\d+)\)\s*$")
_SUMMARY_RULE_ROW = re.compile(
    r"^\s*\|\s*([A-Za-z0-9_-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([0-9,]+)\s*\|\s*$"
)
_MESSAGE_SUMMARY = re.compile(
    r"(?m)^\s*([0-9,]+)\s+Infos?,\s*([0-9,]+)\s+Warnings?,\s*"
    r"([0-9,]+)\s+Critical Warnings?\s+and\s+([0-9,]+)\s+Errors?\s+encountered\.\s*$",
    re.IGNORECASE,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class VivadoReportResult:
    kind: str
    status: str
    path: str
    sha256: str | None
    byte_length: int | None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"parsed", "missing", "unparseable"}:
            raise ValueError("report status must be parsed, missing, or unparseable")
        if self.status == "parsed" and (self.sha256 is None or self.byte_length is None):
            raise ValueError("parsed report requires its byte identity")
        if self.status == "parsed" and self.error:
            raise ValueError("parsed report cannot carry a parse error")
        if self.status != "parsed" and self.metrics:
            raise ValueError("non-parsed report cannot carry normalized metrics")
        object.__setattr__(self, "metrics", _freeze(dict(self.metrics)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "path": self.path,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "metrics": _thaw(self.metrics),
            "error": self.error,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


@dataclass(frozen=True)
class _LoadedReport:
    path: Path
    display_path: str
    data: bytes
    text: str
    sha256: str


@dataclass(frozen=True)
class _RetainedReportBytes:
    payload: bytes
    display_path: str


def _load(
    path: str | os.PathLike[str] | _RetainedReportBytes,
    kind: str,
) -> tuple[_LoadedReport | None, VivadoReportResult | None]:
    if isinstance(path, _RetainedReportBytes):
        return _load_bytes(
            path.payload,
            kind=kind,
            display_path=path.display_path,
        )
    candidate = Path(path)
    display = str(candidate)
    if not candidate.exists():
        return None, VivadoReportResult(
            kind=kind,
            status="missing",
            path=display,
            sha256=None,
            byte_length=None,
            error="report does not exist",
        )
    if not candidate.is_file():
        return None, VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display,
            sha256=None,
            byte_length=None,
            error="report path is not a regular file",
        )
    try:
        data = candidate.read_bytes()
    except OSError as exc:
        return None, VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display,
            sha256=None,
            byte_length=None,
            error=f"cannot read report: {exc}",
        )
    return _load_bytes(data, kind=kind, display_path=display, path=candidate)


def _load_bytes(
    data: bytes,
    *,
    kind: str,
    display_path: str,
    path: Path | None = None,
) -> tuple[_LoadedReport | None, VivadoReportResult | None]:
    digest = hashlib.sha256(data).hexdigest()
    if len(data) > _MAX_REPORT_BYTES:
        return None, VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display_path,
            sha256=digest,
            byte_length=len(data),
            error=f"report exceeds the {_MAX_REPORT_BYTES}-byte parser bound",
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display_path,
            sha256=digest,
            byte_length=len(data),
            error=f"report is not UTF-8 text: {exc}",
        )
    return _LoadedReport(path or Path(display_path), display_path, data, text, digest), None


def _unparseable(report: _LoadedReport, kind: str, error: str) -> VivadoReportResult:
    return VivadoReportResult(
        kind=kind,
        status="unparseable",
        path=report.display_path,
        sha256=report.sha256,
        byte_length=len(report.data),
        error=error,
    )


def _parsed(report: _LoadedReport, kind: str, metrics: Mapping[str, Any]) -> VivadoReportResult:
    return VivadoReportResult(
        kind=kind,
        status="parsed",
        path=report.display_path,
        sha256=report.sha256,
        byte_length=len(report.data),
        metrics=metrics,
    )


def _integer(text: str, name: str) -> int:
    normalized = text.strip().replace(",", "")
    if not normalized.isdigit():
        raise ValueError(f"{name} is not a non-negative integer")
    return int(normalized)


def _floating(text: str, name: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{name} is not numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} is not finite")
    return value


def _metadata(text: str) -> dict[str, str]:
    fields = {
        "Tool Version": "tool_version",
        "Design": "design",
        "Device": "device",
        "Design State": "design_state",
    }
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*\|\s*([^:|]+?)\s*:\s*(.*?)\s*$", line)
        if match and match.group(1).strip() in fields:
            out[fields[match.group(1).strip()]] = match.group(2).strip()
    return out


def parse_vivado_timing_summary(path: str | os.PathLike[str]) -> VivadoReportResult:
    kind = "timing"
    report, early = _load(path, kind)
    if early is not None:
        return early
    assert report is not None
    if "Timing Summary Report" not in report.text or "Design Timing Summary" not in report.text:
        return _unparseable(report, kind, "missing Vivado timing-summary marker or section")
    lines = report.text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "WNS(ns)" in line and "TNS(ns)" in line and "WHS(ns)" in line and "THS(ns)" in line
        ),
        None,
    )
    if header_index is None:
        return _unparseable(report, kind, "missing timing metric header")
    row_match = None
    for line in lines[header_index + 1 : header_index + 12]:
        row_match = _TIMING_ROW.fullmatch(line)
        if row_match is not None:
            break
    if row_match is None:
        return _unparseable(report, kind, "timing metric row is missing or malformed")
    met_count = report.text.count("All user specified timing constraints are met.")
    failed_count = report.text.count("Timing constraints are not met.")
    if met_count + failed_count != 1:
        return _unparseable(report, kind, "timing constraint verdict is missing or ambiguous")
    check_timing: dict[str, int] = {}
    for line in lines:
        match = _CHECK_TIMING.fullmatch(line)
        if match is None:
            continue
        name, raw_count = match.groups()
        count = _integer(raw_count, f"check_timing.{name}")
        if name in check_timing and check_timing[name] != count:
            return _unparseable(report, kind, f"conflicting check_timing count for {name}")
        check_timing[name] = count
    required_checks = {"no_clock", "unconstrained_internal_endpoints"}
    if not required_checks.issubset(check_timing):
        return _unparseable(report, kind, "required check_timing counts are missing")
    values = row_match.groups()
    try:
        metrics: dict[str, Any] = {
            **_metadata(report.text),
            "wns_ns": _floating(values[0], "WNS"),
            "tns_ns": _floating(values[1], "TNS"),
            "tns_failing_endpoints": _integer(values[2], "TNS failing endpoints"),
            "tns_total_endpoints": _integer(values[3], "TNS total endpoints"),
            "whs_ns": _floating(values[4], "WHS"),
            "ths_ns": _floating(values[5], "THS"),
            "ths_failing_endpoints": _integer(values[6], "THS failing endpoints"),
            "ths_total_endpoints": _integer(values[7], "THS total endpoints"),
            "wpws_ns": _floating(values[8], "WPWS"),
            "tpws_ns": _floating(values[9], "TPWS"),
            "tpws_failing_endpoints": _integer(values[10], "TPWS failing endpoints"),
            "tpws_total_endpoints": _integer(values[11], "TPWS total endpoints"),
            "constraints_met": bool(met_count),
            "check_timing": dict(sorted(check_timing.items())),
        }
    except ValueError as exc:
        return _unparseable(report, kind, str(exc))

    # The prose verdict is not independent of the numeric table. Refuse a
    # report that says constraints are met while any setup, hold, or pulse-
    # width family still has negative slack/TNS or failing endpoints. Also
    # refuse the inverse contradiction and impossible endpoint totals; a
    # parser must not normalize inconsistent native evidence into a pass.
    timing_families = (
        (
            metrics["wns_ns"],
            metrics["tns_ns"],
            metrics["tns_failing_endpoints"],
            metrics["tns_total_endpoints"],
        ),
        (
            metrics["whs_ns"],
            metrics["ths_ns"],
            metrics["ths_failing_endpoints"],
            metrics["ths_total_endpoints"],
        ),
        (
            metrics["wpws_ns"],
            metrics["tpws_ns"],
            metrics["tpws_failing_endpoints"],
            metrics["tpws_total_endpoints"],
        ),
    )
    if any(failing > total for _slack, _negative, failing, total in timing_families):
        return _unparseable(
            report,
            kind,
            "timing failing endpoints exceed total endpoints",
        )
    if any(negative > 0 for _slack, negative, _failing, _total in timing_families):
        return _unparseable(
            report,
            kind,
            "timing negative-slack totals must not be positive",
        )
    numeric_violation = any(
        slack < 0 or negative < 0 or failing > 0
        for slack, negative, failing, _total in timing_families
    )
    if bool(metrics["constraints_met"]) == numeric_violation:
        return _unparseable(
            report,
            kind,
            "timing prose verdict contradicts numeric slack or endpoint metrics",
        )
    return _parsed(report, kind, metrics)


def _utilization_percent(text: str, name: str) -> tuple[float, bool]:
    raw = text.strip()
    upper_bound = raw.startswith("<")
    if upper_bound:
        raw = raw[1:].strip()
    return _floating(raw, name), upper_bound


def parse_vivado_utilization(path: str | os.PathLike[str]) -> VivadoReportResult:
    kind = "utilization"
    report, early = _load(path, kind)
    if early is not None:
        return early
    assert report is not None
    if "Utilization Design Information" not in report.text:
        return _unparseable(report, kind, "missing Vivado utilization marker")
    aliases = {
        "Slice LUTs": "lut",
        "CLB LUTs": "lut",
        "Slice Registers": "register",
        "CLB Registers": "register",
        "Block RAM Tile": "bram_tile",
        "DSPs": "dsp",
    }
    resources: dict[str, dict[str, Any]] = {}
    try:
        for line in report.text.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            columns = [column.strip() for column in line.strip().strip("|").split("|")]
            if len(columns) != 6 or columns[0] not in aliases:
                continue
            key = aliases[columns[0]]
            percent, upper_bound = _utilization_percent(columns[5], f"{key}.util_percent")
            row = {
                "label": columns[0],
                "used": _integer(columns[1], f"{key}.used"),
                "available": _integer(columns[4], f"{key}.available"),
                "util_percent": percent,
                "util_percent_is_upper_bound": upper_bound,
            }
            if key in resources and resources[key] != row:
                raise ValueError(f"conflicting utilization rows for {key}")
            resources[key] = row
    except ValueError as exc:
        return _unparseable(report, kind, str(exc))
    required = {"lut", "register", "bram_tile", "dsp"}
    if not required.issubset(resources):
        missing = ", ".join(sorted(required - set(resources)))
        return _unparseable(report, kind, f"missing utilization resources: {missing}")
    return _parsed(
        report,
        kind,
        {**_metadata(report.text), "resources": dict(sorted(resources.items()))},
    )


def _parse_rule_report(
    path: str | os.PathLike[str], *, kind: str, marker: str
) -> VivadoReportResult:
    report, early = _load(path, kind)
    if early is not None:
        return early
    assert report is not None
    if marker not in report.text:
        return _unparseable(report, kind, f"missing Vivado {kind} marker")
    count_matches = re.findall(r"(?m)^\s*Checks found:\s*([0-9,]+)\s*$", report.text)
    if len(set(count_matches)) != 1 or not count_matches:
        return _unparseable(report, kind, "Checks found count is missing or ambiguous")
    try:
        checks_found = _integer(count_matches[0], "Checks found")
        rules: dict[str, dict[str, Any]] = {}
        for line in report.text.splitlines():
            match = _SUMMARY_RULE_ROW.fullmatch(line)
            if match is None or match.group(1).lower() == "rule":
                continue
            rule, raw_severity, description, raw_checks = match.groups()
            severity = re.sub(r"\s+", "_", raw_severity.strip().lower())
            row = {
                "rule": rule,
                "severity": severity,
                "description": description.strip(),
                "checks": _integer(raw_checks, f"{rule}.checks"),
            }
            if rule in rules and rules[rule] != row:
                raise ValueError(f"conflicting summary rows for rule {rule}")
            rules[rule] = row
        row_total = sum(row["checks"] for row in rules.values())
        if row_total != checks_found:
            raise ValueError(
                f"rule counts sum to {row_total}, but Checks found is {checks_found}"
            )
        severity_counts: dict[str, int] = {}
        for row in rules.values():
            severity_counts[row["severity"]] = (
                severity_counts.get(row["severity"], 0) + row["checks"]
            )
    except ValueError as exc:
        return _unparseable(report, kind, str(exc))
    return _parsed(
        report,
        kind,
        {
            **_metadata(report.text),
            "checks_found": checks_found,
            "severity_counts": dict(sorted(severity_counts.items())),
            "rules": [rules[name] for name in sorted(rules)],
        },
    )


def parse_vivado_drc(path: str | os.PathLike[str]) -> VivadoReportResult:
    return _parse_rule_report(path, kind="drc", marker="Report DRC")


def parse_vivado_methodology(path: str | os.PathLike[str]) -> VivadoReportResult:
    return _parse_rule_report(path, kind="methodology", marker="Report Methodology")


def parse_vivado_route_status(path: str | os.PathLike[str]) -> VivadoReportResult:
    kind = "route_status"
    report, early = _load(path, kind)
    if early is not None:
        return early
    assert report is not None
    if "Design Route Status" not in report.text:
        return _unparseable(report, kind, "missing Vivado route-status marker")
    labels = {
        "# of logical nets": "logical_nets",
        "# of nets not needing routing": "nets_not_needing_routing",
        "# of routable nets": "routable_nets",
        "# of fully routed nets": "fully_routed_nets",
        "# of nets with routing errors": "routing_errors",
    }
    metrics: dict[str, int] = {}
    try:
        for line in report.text.splitlines():
            match = re.match(r"^\s*(# of [^.]+?)\.+\s*:\s*([0-9,]+)\s*:\s*$", line)
            if match is None or match.group(1).strip() not in labels:
                continue
            key = labels[match.group(1).strip()]
            value = _integer(match.group(2), key)
            if key in metrics and metrics[key] != value:
                raise ValueError(f"conflicting route metric {key}")
            metrics[key] = value
    except ValueError as exc:
        return _unparseable(report, kind, str(exc))
    required = {"routable_nets", "fully_routed_nets", "routing_errors"}
    if not required.issubset(metrics):
        return _unparseable(report, kind, "required route metrics are missing")
    if metrics["fully_routed_nets"] > metrics["routable_nets"]:
        return _unparseable(report, kind, "fully routed nets exceed routable nets")
    metrics["complete"] = (
        metrics["fully_routed_nets"] == metrics["routable_nets"]
        and metrics["routing_errors"] == 0
    )
    return _parsed(report, kind, metrics)


def _parse_vivado_message_report(
    report: _LoadedReport | None,
    early: VivadoReportResult | None,
) -> VivadoReportResult:
    kind = "messages"
    if early is not None:
        return early
    assert report is not None
    matches = list(_MESSAGE_SUMMARY.finditer(report.text))
    if not matches:
        return _unparseable(report, kind, "Vivado cumulative message summary is missing")
    last = matches[-1]
    try:
        infos, warnings, critical, errors = (
            _integer(value, name)
            for value, name in zip(
                last.groups(), ("infos", "warnings", "critical_warnings", "errors")
            )
        )
    except ValueError as exc:
        return _unparseable(report, kind, str(exc))
    return _parsed(
        report,
        kind,
        {
            "infos": infos,
            "warnings": warnings,
            "critical_warnings": critical,
            "errors": errors,
            "summary_count": len(matches),
        },
    )


def parse_vivado_message_counts(path: str | os.PathLike[str]) -> VivadoReportResult:
    return _parse_vivado_message_report(*_load(path, "messages"))


def parse_vivado_message_counts_bytes(
    payload: bytes,
    *,
    display_path: str = "retained:vivado-console",
) -> VivadoReportResult:
    """Parse message counts from exact retained console bytes, without a temp file."""

    if not isinstance(payload, bytes):
        raise TypeError("Vivado message payload must be bytes")
    return _parse_vivado_message_report(
        *_load_bytes(payload, kind="messages", display_path=str(display_path))
    )


def vivado_artifact_identity(
    path: str | os.PathLike[str], *, kind: str = "artifact"
) -> VivadoReportResult:
    """Bind arbitrary output bytes without interpreting them as UTF-8 text."""

    candidate = Path(path)
    display = str(candidate)
    if not candidate.exists():
        return VivadoReportResult(
            kind=kind,
            status="missing",
            path=display,
            sha256=None,
            byte_length=None,
            error="artifact does not exist",
        )
    if not candidate.is_file():
        return VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display,
            sha256=None,
            byte_length=None,
            error="artifact path is not a regular file",
        )
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            before = os.fstat(handle.fileno())
            byte_length = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                byte_length += len(chunk)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        return VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display,
            sha256=None,
            byte_length=None,
            error=f"cannot read artifact: {exc}",
        )
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or byte_length != after.st_size:
        return VivadoReportResult(
            kind=kind,
            status="unparseable",
            path=display,
            sha256=None,
            byte_length=None,
            error="artifact changed while its identity was computed",
        )
    return VivadoReportResult(
        kind=kind,
        status="parsed",
        path=display,
        sha256=digest.hexdigest(),
        byte_length=byte_length,
        metrics={},
    )


_PARSERS: Mapping[str, Callable[[str | os.PathLike[str]], VivadoReportResult]] = {
    "timing": parse_vivado_timing_summary,
    "utilization": parse_vivado_utilization,
    "drc": parse_vivado_drc,
    "methodology": parse_vivado_methodology,
    "route_status": parse_vivado_route_status,
    "messages": parse_vivado_message_counts,
}


def parse_vivado_report(
    kind: str, path: str | os.PathLike[str]
) -> VivadoReportResult:
    try:
        parser = _PARSERS[str(kind)]
    except KeyError as exc:
        raise ValueError(f"unknown Vivado report kind: {kind}") from exc
    return parser(path)


def parse_vivado_report_bytes(
    kind: str,
    payload: bytes,
    *,
    display_path: str = "retained:vivado-report",
) -> VivadoReportResult:
    """Parse exact CAS-retained report bytes without touching a live workspace."""

    if not isinstance(payload, bytes):
        raise TypeError("Vivado report payload must be bytes")
    try:
        parser = _PARSERS[str(kind)]
    except KeyError as exc:
        raise ValueError(f"unknown Vivado report kind: {kind}") from exc
    return parser(
        _RetainedReportBytes(
            payload=payload,
            display_path=str(display_path),
        )
    )


parse_timing_summary = parse_vivado_timing_summary
parse_utilization = parse_vivado_utilization
parse_drc = parse_vivado_drc
parse_methodology = parse_vivado_methodology
parse_route_status = parse_vivado_route_status
parse_message_counts = parse_vivado_message_counts


__all__ = [
    "VivadoReportResult",
    "parse_drc",
    "parse_message_counts",
    "parse_methodology",
    "parse_route_status",
    "parse_timing_summary",
    "parse_utilization",
    "parse_vivado_drc",
    "parse_vivado_message_counts",
    "parse_vivado_message_counts_bytes",
    "parse_vivado_methodology",
    "parse_vivado_report",
    "parse_vivado_report_bytes",
    "parse_vivado_route_status",
    "parse_vivado_timing_summary",
    "parse_vivado_utilization",
    "vivado_artifact_identity",
]
