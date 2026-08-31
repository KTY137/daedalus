"""CAS-only semantic derivation for one retained Vivado publication.

The execution receipt and native CAS objects are observations.  This module is
the single deterministic projection that turns those observations into parsed
reports, assurance dimensions, a verdict, and the exact limitations carried by
``ChipRunReceipt``.  It owns no authority and performs no live project reads.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from daedalus.spine.envelope import canonical_json
from daedalus.storage import ArtifactStore

from .contracts import default_dimensions
from .execution_plan import EdaExecutionPlan
from .executor import ExecutionResult
from .vivado_reports import (
    VivadoReportResult,
    parse_vivado_message_counts_bytes,
    parse_vivado_report_bytes,
)


_SUMMARY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VIVADO_SHORT_VERSION = re.compile(r"^\d{4}\.\d+(?:\.\d+)?$")
_LOCATOR_PREFIX = "artifact-locator:sha256:"
_REPORT_FILENAMES = {
    "utilization": "utilization.rpt",
    "timing": "timing_summary.rpt",
    "drc": "drc.rpt",
    "methodology": "methodology.rpt",
    "route_status": "route_status.rpt",
}


CANONICAL_PUBLICATION_LIMITATIONS = tuple(
    sorted(
        {
            "A successful Vivado process or generated bitstream is not FPGA signoff.",
            "Simulation, formal, CDC/RDC, equivalence, power, Vitis software, hardware-in-loop, and FPGA programming were not run.",
            "The in-process guard and isolated workspace are not an operating-system sandbox.",
            "The kernel lease requests no egress endpoint, but this does not prove offline or no-egress execution.",
            "Declared XDC is executable Tcl; Vivado, XDC, and vendor support processes retain ambient host filesystem, network, and secret access outside OS confinement.",
            "Vivado support binaries and vendor catalog resources are a trusted-but-unbound vendor TCB beyond the byte-bound launcher.",
            "The authority HEAD receipt does not bind the imported Python adapter/parser bytes, commit object, or worktree cleanliness.",
            "Concurrent host mutation outside the retained source/workspace snapshots can invalidate conclusions.",
            "No merge or promotion is authorized by this evidence.",
        }
    )
)


def _retained_absolute_path_identity(value: str | Path) -> str:
    """Compare retained absolute path text without consulting the live path."""

    text = os.fspath(value)
    if not text or "\x00" in text or not os.path.isabs(text):
        raise ValueError("retained path identity must be an absolute non-NUL path")
    return os.path.normcase(os.path.normpath(text))


def parse_vivado_flow_summary_bytes(
    payload: bytes,
    *,
    display_path: str,
    phase: str,
    project_file: str | Path,
    part: str,
    board_part: str,
    top: str,
    synth_run: str,
    impl_run: str,
    jobs: int,
    path_identity: Callable[[str | Path], str] | None = None,
) -> dict[str, Any]:
    """Parse exact flow-summary bytes against the signed execution-plan values."""

    display = str(display_path)
    try:
        if not isinstance(payload, bytes):
            raise TypeError("retained flow summary payload must be bytes")
        if len(payload) > 1024 * 1024:
            raise ValueError("flow summary exceeds the parser bound")
        text = payload.decode("utf-8-sig")
    except (TypeError, UnicodeError, ValueError) as exc:
        return {
            "identity": {
                "kind": "flow_summary",
                "status": "unparseable",
                "path": display,
                "sha256": None,
                "byte_length": None,
                "metrics": {},
                "error": str(exc),
            },
            "values": {},
            "error": str(exc),
        }

    digest = hashlib.sha256(payload).hexdigest()
    byte_length = len(payload)

    def unparseable(error: str) -> dict[str, Any]:
        return {
            "identity": {
                "kind": "flow_summary",
                "status": "unparseable",
                "path": display,
                "sha256": digest,
                "byte_length": byte_length,
                "metrics": {},
                "error": error,
            },
            "values": {},
            "error": error,
        }

    identity = {
        "kind": "flow_summary",
        "status": "parsed",
        "path": display,
        "sha256": digest,
        "byte_length": byte_length,
        "metrics": {},
        "error": "",
    }
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            return unparseable("flow summary contains a malformed line")
        key, value = line.split("=", 1)
        if not _SUMMARY_KEY.fullmatch(key):
            return unparseable("flow summary contains an invalid key")
        if key in values:
            return unparseable(f"flow summary repeats key {key}")
        values[key] = value

    common = {
        "schema": "daedalus-vivado-flow-summary/1",
        "phase": phase,
        "part": str(part),
        "board_part": str(board_part),
        "top": str(top),
        "synth_run": str(synth_run),
        "impl_run": str(impl_run),
    }
    for key, expected in common.items():
        if values.get(key) != expected:
            return unparseable(
                f"flow summary {key} does not match the execution plan"
            )
    tool = values.get("tool", "")
    if not _VIVADO_SHORT_VERSION.fullmatch(tool):
        return unparseable("flow summary has no parseable Vivado version")
    try:
        identify = path_identity or _retained_absolute_path_identity
        if identify(values.get("project", "")) != identify(project_file):
            return unparseable(
                "flow summary project does not match the execution plan"
            )
    except (OSError, TypeError, ValueError):
        return unparseable("flow summary project path is invalid")

    phase_keys = {
        "inspect": {
            "synth_status",
            "synth_progress",
            "impl_status",
            "impl_progress",
            "ip_count",
            "locked_ip_count",
        },
        "synth": {
            "ip_cache",
            "regenerated_ip_source_count",
            "status",
            "progress",
            "jobs",
        },
        "impl": {
            "fresh_synthesis",
            "ip_cache",
            "regenerated_ip_source_count",
            "synth_status",
            "synth_progress",
            "status",
            "progress",
            "jobs",
        },
    }
    if phase not in phase_keys:
        return unparseable("flow summary phase is unsupported")
    expected_keys = set(common) | {"tool", "project"} | phase_keys[phase]
    if set(values) != expected_keys:
        return unparseable(
            "flow summary keys do not match the package-owned phase schema"
        )

    if phase == "inspect":
        for key in (
            "synth_status",
            "synth_progress",
            "impl_status",
            "impl_progress",
        ):
            if not values[key]:
                return unparseable(f"flow summary {key} is empty")
        for key in ("ip_count", "locked_ip_count"):
            if not values[key].isdigit():
                return unparseable(f"flow summary {key} is not an integer")
        if int(values["locked_ip_count"]) > int(values["ip_count"]):
            return unparseable("flow summary locked IP count exceeds total IP count")
    else:
        if values["ip_cache"] != "disabled":
            return unparseable("flow summary does not prove disabled IP cache")
        if not values["regenerated_ip_source_count"].isdigit():
            return unparseable(
                "flow summary regenerated IP source count is not an integer"
            )
        if values["jobs"] != str(jobs):
            return unparseable("flow summary jobs does not match the execution plan")
        if (
            "complete" not in values["status"].casefold()
            or values["progress"] != "100%"
        ):
            return unparseable("flow summary phase did not reach Complete/100%")
        if phase == "impl" and (
            values["fresh_synthesis"] != "1"
            or "complete" not in values["synth_status"].casefold()
            or values["synth_progress"] != "100%"
        ):
            return unparseable(
                "flow summary does not prove fresh synthesis Complete/100%"
            )
    return {"identity": identity, "values": dict(sorted(values.items()))}


def _locator_digest(uri: str, *, label: str) -> str:
    text = str(uri)
    if not text.startswith(_LOCATOR_PREFIX):
        raise ValueError(f"{label} locator URI is invalid")
    return text[len(_LOCATOR_PREFIX) :]


def _payload_from_locator(
    store: ArtifactStore,
    *,
    locator_uri: str,
    expected_sha256: str,
    label: str,
) -> tuple[bytes, str]:
    locator = store.verify(
        store.load_locator(_locator_digest(locator_uri, label=label))
    )
    if locator.locator_uri != locator_uri or locator.artifact_sha256 != expected_sha256:
        raise ValueError(f"{label} locator disagrees with its retained identity")
    return store.get_bytes(locator.artifact_sha256), locator.locator_uri


def _retained_native_payload(
    store: ArtifactStore,
    result: ExecutionResult,
    filename: str,
) -> tuple[bytes | None, str]:
    unexpected = set(result.unexpected_artifact_paths)
    matches = tuple(
        artifact
        for artifact in result.artifacts
        if artifact.path not in unexpected and Path(artifact.path).name == filename
    )
    missing = tuple(
        path for path in result.missing_artifact_paths if Path(path).name == filename
    )
    if not matches and len(missing) == 1:
        return None, f"retained-missing:{missing[0]}"
    if len(matches) != 1 or missing:
        raise ValueError(
            f"retained EDA result has no unique output state for {filename!r}"
        )
    artifact = matches[0]
    payload, locator_uri = _payload_from_locator(
        store,
        locator_uri=artifact.locator,
        expected_sha256=artifact.sha256,
        label=filename,
    )
    if len(payload) != artifact.byte_length:
        raise ValueError(f"retained EDA locator disagrees with {filename!r} size")
    return payload, locator_uri


def _missing_report(kind: str, display: str) -> VivadoReportResult:
    return VivadoReportResult(
        kind=kind,
        status="missing",
        path=display,
        sha256=None,
        byte_length=None,
        error="declared Vivado report was not retained",
    )


def _parse_retained_reports(
    store: ArtifactStore,
    result: ExecutionResult,
    plan: EdaExecutionPlan,
) -> tuple[dict[str, VivadoReportResult], dict[str, Any]]:
    phase = plan.phase
    if len(plan.argv) < 19:
        raise ValueError("retained EDA plan has no complete Vivado Tcl argument vector")
    summary_payload, summary_display = _retained_native_payload(
        store, result, f"{phase}_summary.txt"
    )
    if summary_payload is None:
        summary = {
            "identity": {
                "kind": "flow_summary",
                "status": "missing",
                "path": summary_display,
                "sha256": None,
                "byte_length": None,
                "metrics": {},
                "error": "declared Vivado summary was not retained",
            },
            "values": {},
        }
    else:
        summary = parse_vivado_flow_summary_bytes(
            summary_payload,
            display_path=summary_display,
            phase=phase,
            project_file=plan.argv[11],
            part=plan.argv[13],
            board_part=plan.argv[14],
            top=plan.argv[15],
            synth_run=plan.argv[16],
            impl_run=plan.argv[17],
            jobs=int(plan.argv[18]),
        )

    reports: dict[str, VivadoReportResult] = {}
    if phase != "inspect":
        kinds = ["utilization", "timing", "drc", "methodology"]
        if phase == "impl":
            kinds.append("route_status")
        for kind in kinds:
            filename = _REPORT_FILENAMES[kind]
            payload, display = _retained_native_payload(store, result, filename)
            reports[kind] = (
                _missing_report(kind, display)
                if payload is None
                else parse_vivado_report_bytes(kind, payload, display_path=display)
            )

    if result.stdout_sha256 is None or result.stdout_locator is None:
        raise ValueError("terminal EDA result lacks retained stdout")
    stdout, stdout_display = _payload_from_locator(
        store,
        locator_uri=result.stdout_locator,
        expected_sha256=result.stdout_sha256,
        label="Vivado stdout",
    )
    reports["messages"] = parse_vivado_message_counts_bytes(
        stdout,
        display_path=stdout_display,
    )
    return reports, summary


def _phase_artifact_binding(
    *,
    phase: str,
    result: ExecutionResult,
    reports: Mapping[str, VivadoReportResult],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    by_leaf: dict[str, list[Any]] = {}
    unexpected = set(result.unexpected_artifact_paths)
    for artifact in result.artifacts:
        if artifact.path in unexpected:
            continue
        by_leaf.setdefault(Path(artifact.path).name, []).append(artifact)
    checks: dict[str, Any] = {
        "unexpected_outputs": {
            "status": "passed" if not unexpected else "failed",
            "paths": sorted(unexpected),
        }
    }

    def bind(name: str, filename: str, identity: Mapping[str, Any]) -> None:
        retained = by_leaf.get(filename, [])
        parsed_sha = identity.get("sha256")
        parsed_size = identity.get("byte_length")
        passed = (
            len(retained) == 1
            and identity.get("status") == "parsed"
            and isinstance(parsed_sha, str)
            and parsed_sha == retained[0].sha256
            and isinstance(parsed_size, int)
            and not isinstance(parsed_size, bool)
            and parsed_size == retained[0].byte_length
        )
        checks[name] = {
            "status": "passed" if passed else "failed",
            "filename": filename,
            "parsed_sha256": parsed_sha,
            "parsed_byte_length": parsed_size,
            "retained_sha256": retained[0].sha256 if len(retained) == 1 else None,
            "retained_byte_length": (
                retained[0].byte_length if len(retained) == 1 else None
            ),
            "retained_matches": len(retained),
        }

    summary_identity = summary.get("identity", {})
    bind(
        "summary",
        f"{phase}_summary.txt",
        summary_identity if isinstance(summary_identity, Mapping) else {},
    )
    for name, report in reports.items():
        if name == "messages":
            critical_warnings = report.metrics.get("critical_warnings")
            errors = report.metrics.get("errors")
            passed = (
                isinstance(result.stdout_sha256, str)
                and report.sha256 == result.stdout_sha256
                and vivado_message_report_passed(report)
            )
            checks[name] = {
                "status": "passed" if passed else "failed",
                "parsed_status": report.status,
                "parsed_sha256": report.sha256,
                "retained_sha256": result.stdout_sha256,
                "retained_locator": result.stdout_locator,
                "critical_warnings": critical_warnings,
                "errors": errors,
            }
            continue
        filename = _REPORT_FILENAMES.get(name)
        if filename is not None:
            bind(name, filename, report.to_dict())
    return {
        "status": (
            "passed"
            if checks and all(row["status"] == "passed" for row in checks.values())
            else "failed"
        ),
        "checks": dict(sorted(checks.items())),
    }


def vivado_rule_report_passed(report: VivadoReportResult) -> bool:
    if report.status != "parsed":
        return False
    checks_found = report.metrics.get("checks_found")
    if isinstance(checks_found, bool) or not isinstance(checks_found, int):
        return False
    if checks_found != 0:
        return False
    counts = report.metrics.get("severity_counts", {})
    if not isinstance(counts, Mapping):
        return False
    return not any(int(value or 0) > 0 for value in counts.values())


def vivado_message_report_passed(report: VivadoReportResult) -> bool:
    """Require a parsed cumulative console summary without criticals or errors."""

    if report.status != "parsed":
        return False
    for name in ("critical_warnings", "errors"):
        value = report.metrics.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            return False
    return True


def _verdict_and_dimensions(
    phase: str,
    result: ExecutionResult,
    reports: Mapping[str, VivadoReportResult],
) -> tuple[str, dict[str, str]]:
    dimensions = default_dimensions(phase)
    pending = tuple(name for name, value in dimensions.items() if value == "pending")
    if result.status in {"timeout", "cancelled"}:
        replacement = "cancelled" if result.executed else "not_run"
        for name in pending:
            dimensions[name] = replacement
        return "cancelled", dimensions
    if result.status in {"missing", "error"}:
        replacement = "failed" if result.executed else "not_run"
        for name in pending:
            dimensions[name] = replacement
        return "error", dimensions
    if result.status != "ok":
        replacement = "failed" if result.executed else "not_run"
        for name in pending:
            dimensions[name] = replacement
        return "failed", dimensions
    if phase == "inspect":
        return "inconclusive", dimensions

    dimensions["synthesis"] = "passed"
    timing = reports["timing"]
    if timing.status == "parsed":
        checks = timing.metrics.get("check_timing", {})
        checks_clean = isinstance(checks, Mapping) and not any(
            int(value or 0) > 0 for value in checks.values()
        )
        dimensions["timing"] = (
            "passed"
            if bool(timing.metrics.get("constraints_met")) and checks_clean
            else "failed"
        )
    else:
        dimensions["timing"] = "failed"
    dimensions["drc"] = (
        "passed" if vivado_rule_report_passed(reports["drc"]) else "failed"
    )
    dimensions["methodology"] = (
        "passed"
        if vivado_rule_report_passed(reports["methodology"])
        else "failed"
    )
    if phase == "impl":
        route = reports["route_status"]
        dimensions["implementation"] = (
            "passed"
            if route.status == "parsed" and bool(route.metrics.get("complete"))
            else "failed"
        )
    failed = any(value == "failed" for value in dimensions.values())
    return ("failed" if failed else "inconclusive"), dimensions


@dataclass(frozen=True)
class ChipPublicationDerivation:
    """Exact semantic projection derived from retained execution evidence."""

    summary: Mapping[str, Any]
    reports: Mapping[str, VivadoReportResult]
    artifact_binding: Mapping[str, Any]
    verdict: str
    dimensions: Mapping[str, str]
    limitations: tuple[str, ...]
    tool: Mapping[str, Any]
    manifest_metrics: Mapping[str, Any]

    def metrics(self, *, runtime_manifest_sha256: str) -> dict[str, Any]:
        report_payload = {
            name: report.to_dict() for name, report in self.reports.items()
        }
        return {
            **dict(self.manifest_metrics),
            "runtime_manifest_sha256": str(runtime_manifest_sha256),
            "summary": dict(self.summary),
            "reports": report_payload,
            "messages": self.reports["messages"].to_dict(),
            "artifact_binding": dict(self.artifact_binding),
        }


def derive_chip_publication(
    result: ExecutionResult,
    plan: EdaExecutionPlan,
    artifact_store: ArtifactStore,
) -> ChipPublicationDerivation:
    """Recompute publication semantics solely from plan, receipt, and CAS bytes."""

    if type(result) is not ExecutionResult or type(plan) is not EdaExecutionPlan:
        raise TypeError("chip publication derivation requires canonical execution types")
    if type(artifact_store) is not ArtifactStore:
        raise TypeError("chip publication derivation requires canonical ArtifactStore")
    if tuple(result.argv) != plan.argv or result.cwd != plan.cwd:
        raise ValueError("retained EDA result is not bound to its execution plan")
    expected_store = Path(plan.artifact_store_root).resolve(strict=False)
    observed_store = Path(artifact_store.root).resolve(strict=False)
    if os.path.normcase(str(expected_store)) != os.path.normcase(str(observed_store)):
        raise ValueError("retained EDA CAS is not the execution-plan artifact store")

    reports, summary = _parse_retained_reports(artifact_store, result, plan)
    binding = _phase_artifact_binding(
        phase=plan.phase,
        result=result,
        reports=reports,
        summary=summary,
    )
    verdict, dimensions = _verdict_and_dimensions(plan.phase, result, reports)
    if binding["status"] != "passed" and verdict not in {"error", "cancelled"}:
        verdict = "failed"

    summary_values = summary.get("values", {})
    reported_version = (
        str(summary_values.get("tool", ""))
        if isinstance(summary_values, Mapping)
        else ""
    )
    tool = {
        "id": "vivado",
        "label": "AMD Vivado",
        "selected_command": str(plan.argv[0]),
        "launcher_sha256": plan.launcher_sha256,
        "reported_version": reported_version,
        "ambient_probe_status": "not_run",
        "security_boundary_claimed": False,
    }
    manifest_metrics = {
        "source_manifest_sha256": plan.source_manifest_sha256,
        "workspace_manifest_sha256": plan.workspace_manifest_sha256,
        "post_authoritative_manifest_sha256": (
            result.post_authoritative_manifest_sha256
        ),
        "post_authoritative_source_identity_sha256": (
            result.post_authoritative_source_identity_sha256
        ),
        "authoritative_source_unchanged": (
            result.post_authoritative_manifest_sha256 is not None
            and result.post_authoritative_manifest_sha256
            == plan.source_manifest_sha256
        ),
        "post_workspace_manifest_sha256": result.post_workspace_manifest_sha256,
        "post_source_identity_sha256": result.post_source_identity_sha256,
        "authored_source_identity_unchanged": (
            result.post_source_identity_sha256 is not None
            and result.post_source_identity_sha256 == plan.source_identity_sha256
        ),
        "execution_plan": plan.to_dict(),
        "execution_plan_sha256": plan.digest,
        "missing_artifact_paths": list(result.missing_artifact_paths),
        "unexpected_artifact_paths": list(result.unexpected_artifact_paths),
        "publication_inputs": "authenticated-ledger-and-cas-only",
    }
    # Fail early if a future parser accidentally returns a non-canonical value.
    canonical_json(manifest_metrics)
    return ChipPublicationDerivation(
        summary=summary,
        reports=dict(sorted(reports.items())),
        artifact_binding=binding,
        verdict=verdict,
        dimensions=dict(sorted(dimensions.items())),
        limitations=CANONICAL_PUBLICATION_LIMITATIONS,
        tool=tool,
        manifest_metrics=manifest_metrics,
    )


__all__ = [
    "CANONICAL_PUBLICATION_LIMITATIONS",
    "ChipPublicationDerivation",
    "derive_chip_publication",
    "parse_vivado_flow_summary_bytes",
    "vivado_message_report_passed",
    "vivado_rule_report_passed",
]
