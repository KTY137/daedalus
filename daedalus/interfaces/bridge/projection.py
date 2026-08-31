"""Read-state and status projections for the local file bridge.

Paths and cross-projection calls are explicit inputs.  This keeps the module
free of watcher, queue, journal, scheduler, and effect-entrypoint authority and
lets the legacy facade preserve its established monkeypatch seams.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


PathPort = Callable[[], Path]
UnreadReportsPort = Callable[[], list[Path]]
ReportBriefPort = Callable[[Path], dict[str, Any]]
HeartbeatStatusPort = Callable[[], dict[str, Any]]
QuarantinedRequestsPort = Callable[[], list[dict[str, Any]]]
ProjectReportsPort = Callable[[str | None], list[dict[str, Any]]]
BridgeStatusPort = Callable[[str | None], dict[str, Any]]


def seen_dir(inbox: Path) -> Path:
    """Return the read-state projection directory for an inbox."""

    return inbox / ".seen"


def latest_log(inbox: Path) -> Path:
    """Return the single append-only report-arrival signal path."""

    return inbox / "LATEST.log"


def note_report_arrival(
    result_path: Path,
    report: dict[str, Any],
    *,
    key: str | None,
    latest_log: PathPort,
    now_iso: Callable[[], str],
    trace_of: Callable[[dict[str, Any]], str | None],
) -> None:
    """Append one idempotent arrival signal for a terminal report."""

    lane = report.get("lane") or (report.get("request") or {}).get("lane") or "?"
    marker = f" key={key}" if key else ""
    trace_id = trace_of(report)
    marker += f" trace={trace_id}" if trace_id else ""
    line = (
        f"{now_iso()} {result_path.name} "
        f"status={report.get('bridge_status', '?')} lane={lane}{marker}\n"
    )
    try:
        log = latest_log()
        if key and log.exists():
            for existing in log.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if existing.endswith(marker):
                    return
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def reported_result(report: dict[str, Any]) -> tuple[str | None, str]:
    """Extract the provider's reported status and bounded summary."""

    inner = report.get("report") if isinstance(report.get("report"), dict) else {}
    if inner:
        status = str(inner.get("status") or "").strip() or None
        return status, str(inner.get("summary") or "").strip()[:600]
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    statuses: list[str] = []
    summaries: list[str] = []
    for assignment in result.get("assignments") or []:
        if not isinstance(assignment, dict):
            continue
        nested = assignment.get("result")
        nested = nested if isinstance(nested, dict) else {}
        nested_report = nested.get("report")
        nested_report = nested_report if isinstance(nested_report, dict) else {}
        status = str(
            assignment.get("status") or nested_report.get("status") or ""
        ).strip()
        summary = str(
            nested_report.get("summary") or assignment.get("reason") or ""
        ).strip()
        if status == "gated_held":
            held = (
                "candidate passed its gate and is held; not applied to the "
                "primary checkout"
            )
            summary = f"{held}: {summary}" if summary else held
        if status:
            statuses.append(status)
        if summary:
            summaries.append(summary)
    reported_status = ",".join(dict.fromkeys(statuses))[:120] or None
    return reported_status, " ".join(summaries)[:600]


def report_application_truth(
    report: dict[str, Any],
) -> tuple[bool | None, str]:
    """Return checkout-application truth from retained write evidence."""

    if not isinstance(report, dict):
        return None, "no report to inspect"

    mutation_blocked = report.get("mutation_blocked")
    if mutation_blocked:
        return False, str(mutation_blocked)

    result = report.get("result")
    result = result if isinstance(result, dict) else {}
    assignments = result.get("assignments")
    assignments = assignments if isinstance(assignments, list) else []
    verdicts: list[bool | None] = []
    reasons: list[str] = []

    def list_evidence(
        containers: tuple[dict[str, Any], ...], key: str
    ) -> tuple[bool, list[Any] | None]:
        values = [container.get(key) for container in containers if key in container]
        if not values:
            return False, None
        if any(not isinstance(value, list) for value in values):
            return True, None
        merged: list[Any] = []
        for value in values:
            for item in value:
                if item not in merged:
                    merged.append(item)
        return True, merged

    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        nested = assignment.get("result")
        nested = nested if isinstance(nested, dict) else {}
        receipt = assignment.get("provider_receipt")
        receipt = receipt if isinstance(receipt, dict) else {}
        containers = (assignment, nested, receipt)
        owner = str(assignment.get("owner") or "?")
        status = str(assignment.get("status") or "").strip().lower()
        action = str(
            nested.get("action") or receipt.get("action") or ""
        ).strip().lower()
        mode = str(
            assignment.get("mode")
            or nested.get("mode")
            or receipt.get("mode")
            or ""
        ).strip().lower()
        blocked = (
            assignment.get("mutation_blocked")
            or nested.get("mutation_blocked")
            or receipt.get("mutation_blocked")
        )

        if blocked:
            verdicts.append(False)
            reasons.append(f"{owner}: {blocked}")
            continue
        if status in {"write_gate_failed", "escalated_after_verify_fail"} or action in {
            "write_gate_failed",
            "escalated_after_verify_fail",
        }:
            dirty_present, dirty = list_evidence(containers, "dirty_unreverted")
            wrote_present, wrote = list_evidence(containers, "wrote")
            if (dirty_present and dirty) or (wrote_present and wrote):
                count = len(dirty or wrote or [])
                verdicts.append(None)
                reasons.append(
                    f"{owner}: verification/rollback failed and {count} "
                    "unreverted on-disk path(s) remain; manual cleanup is "
                    "required and application to the primary checkout is "
                    "unproven"
                )
            elif (dirty_present and dirty is None) or (
                wrote_present and wrote is None
            ):
                verdicts.append(None)
                reasons.append(
                    f"{owner}: verification/rollback failed and retained "
                    "write evidence is malformed; the on-disk outcome is "
                    "unproven"
                )
            elif wrote_present and wrote == []:
                verdicts.append(False)
                reasons.append(
                    f"{owner}: verification failed, but the measured wrote "
                    "list proves no unreverted on-disk paths remain"
                )
            else:
                verdicts.append(None)
                reasons.append(
                    f"{owner}: verification/rollback failed without retained "
                    "evidence proving whether on-disk paths remain"
                )
            continue

        if status == "gated_held" or action == "gated_held":
            verdicts.append(False)
            reasons.append(
                f"{owner}: candidate is held for explicit promotion and was "
                "not applied to the primary checkout"
            )
            continue

        if status == "offloaded" or action == "offloaded":
            if mode == "advisory":
                verdicts.append(False)
                draft = nested.get("draft") or receipt.get("draft")
                if draft:
                    reasons.append(
                        f"{owner}: saved as advisory draft {draft}, not applied"
                    )
                else:
                    reasons.append(
                        f"{owner}: advisory work cannot apply checkout changes; "
                        "no persisted draft id was reported"
                    )
                continue
            if mode != "write":
                verdicts.append(None)
                reasons.append(
                    f"{owner}: status='offloaded' but execution mode is "
                    f"{mode or 'missing'}; application cannot be inferred"
                )
                continue
            wrote_present, wrote = list_evidence(containers, "wrote")
            verify_rows = [
                container.get("verify")
                for container in containers
                if "verify" in container
            ]
            verify_ok = bool(verify_rows) and all(
                isinstance(value, dict) and value.get("ok") is True
                for value in verify_rows
            )
            if not wrote_present or wrote is None:
                verdicts.append(None)
                reasons.append(
                    f"{owner}: write mode lacks the measured on-disk `wrote` list"
                )
            elif not wrote:
                verdicts.append(False)
                reasons.append(f"{owner}: write mode recorded no on-disk changes")
            elif verify_ok:
                verdicts.append(True)
                reasons.append(
                    f"{owner}: write mode measured {len(wrote)} changed path(s) "
                    "and the verification gate passed"
                )
            else:
                verdicts.append(None)
                reasons.append(
                    f"{owner}: on-disk changes were reported but a passed "
                    "verification gate was not retained"
                )
            continue

        verdicts.append(None)
        reasons.append(f"{owner}: status={status!r}, no verify signal")

    if verdicts:
        reason = "; ".join(reasons)
        if all(verdict is True for verdict in verdicts):
            return True, reason
        if all(verdict is False for verdict in verdicts):
            return False, reason
        return None, reason

    bridge_status = str(report.get("bridge_status") or "").strip().lower()
    if bridge_status in {"failed", "quarantined"}:
        return None, (
            f"bridge_status={bridge_status}, but the on-disk outcome is "
            "unproven because no write/rollback evidence was retained"
        )
    if bridge_status == "done":
        return None, "bridge completion alone is not application evidence"
    return None, "insufficient information to determine whether anything was applied"


def conversation_report_fields(
    key: str,
    report: dict[str, Any],
    *,
    reported: Callable[[dict[str, Any]], tuple[str | None, str]],
    application_truth: Callable[[dict[str, Any]], tuple[bool | None, str]],
    present: str,
    degraded: str,
    unknown: str,
) -> tuple[str, str, dict[str, Any]]:
    """Conservatively project one terminal report into conversation fields."""

    bridge_status = str(report.get("bridge_status") or "").strip().lower()
    reported_status, reported_summary = reported(report)
    reported_states = {
        value.strip().lower()
        for value in str(reported_status or "").split(",")
        if value.strip()
    }
    error = str(report.get("error") or "").strip()[:1000]
    lane = report.get("lane") or (
        (report.get("request") or {}).get("lane")
        if isinstance(report.get("request"), dict)
        else None
    )
    requested_lane = report.get("requested_lane") or (
        (report.get("request") or {}).get("lane")
        if isinstance(report.get("request"), dict)
        else None
    )
    actual_providers = (
        list(report.get("actual_providers") or [])
        if isinstance(report.get("actual_providers"), list)
        else []
    )
    applied, application_reason = application_truth(report)

    if bridge_status in ("failed", "quarantined"):
        outcome_state = degraded
        reason = error or reported_summary or str(report.get("reason") or "").strip()
        summary = f"bridge {bridge_status}"
        if reason:
            summary += f": {reason[:600]}"
        if applied is None and (
            "unreverted" in application_reason
            or "manual cleanup" in application_reason
        ):
            summary += f"; {application_reason[:600]}"
    elif bridge_status == "done" and reported_states.intersection(
        {"failed", "blocked", "error"}
    ):
        outcome_state = degraded
        summary = (
            "bridge produced a report, but its reported result was "
            f"{reported_status}"
        )
    elif bridge_status == "done" and "gated_held" in reported_states:
        outcome_state = present
        summary = (
            "bridge produced a gated candidate that is held for explicit "
            "promotion; it was not applied to the primary checkout"
        )
    elif bridge_status == "done":
        outcome_state = present
        if applied is True:
            summary = (
                "bridge finished; measured checkout changes were applied "
                "and the verification gate passed"
            )
        elif applied is False:
            summary = "bridge finished; no checkout changes were applied"
        else:
            summary = (
                "bridge finished and produced a report; whether changes "
                "were applied is not inferred"
            )
    else:
        outcome_state = unknown
        summary = (
            "bridge produced a terminal report with an unrecognized "
            f"status {bridge_status!r}"
        )

    detail = {
        "source": "file_bridge.report",
        "request_file": key,
        "bridge_status": bridge_status or None,
        "lane": str(lane) if lane else None,
        "requested_lane": str(requested_lane) if requested_lane else None,
        "actual_providers": actual_providers,
        "reported_status": reported_status,
        "reported_summary": reported_summary or None,
        "error": error or None,
        "applied": applied,
        "application_reason": application_reason,
    }
    return outcome_state, summary, detail


def unread_reports(*, inbox: Path, seen_dir: PathPort) -> list[Path]:
    """Return unseen report paths in deterministic name order."""

    if not inbox.exists():
        return []
    seen = seen_dir()
    return [
        path
        for path in sorted(inbox.glob("*.report.json"))
        if not (seen / path.name).exists()
    ]


def mark_read(
    names: list[str] | None = None,
    all_reports: bool = False,
    *,
    inbox: Path,
    seen_dir: PathPort,
    unread: UnreadReportsPort,
) -> list[str]:
    """Create acknowledgement markers for reports that currently exist."""

    targets: list[Path] = []
    if all_reports:
        targets = unread()
    else:
        for name in names or []:
            path = inbox / name
            if not path.exists() and not name.endswith(".report.json"):
                path = inbox / f"{name}.report.json"
            if path.exists():
                targets.append(path)
    marked: list[str] = []
    if targets:
        seen_dir().mkdir(parents=True, exist_ok=True)
    for path in targets:
        try:
            (seen_dir() / path.name).touch()
            marked.append(path.name)
        except OSError:
            pass
    return marked


def quarantined_requests(*, quarantine_dir: PathPort) -> list[dict[str, Any]]:
    """Project quarantined request files and their diagnostic sidecars."""

    directory = quarantine_dir()
    if not directory.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".error.json"):
            continue
        try:
            sidecar = json.loads(
                (directory / f"{path.stem}.error.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError, ValueError):
            sidecar = {}
        rows.append(
            {
                "name": path.name,
                "reason": sidecar.get("reason") or "?",
                "error": sidecar.get("error") or "",
                "path": str(path),
            }
        )
    return rows


def report_brief(path: Path) -> dict[str, Any]:
    """Decode the stable one-line report projection."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        payload = {}
    request = payload.get("request") or {}
    summary = (
        (payload.get("report") or {}).get("summary")
        or payload.get("error")
        or ""
    )
    return {
        "name": path.name,
        "status": payload.get("bridge_status") or "?",
        "lane": payload.get("lane") or request.get("lane") or "?",
        "project": request.get("project") or "",
        "summary": " ".join(str(summary).split())[:160],
    }


def project_report_briefs(
    project: str | None = None,
    *,
    inbox: Path,
    brief: ReportBriefPort,
) -> list[dict[str, Any]]:
    """Return finished reports in deterministic arrival order."""

    if not inbox.exists():
        return []
    rows: list[tuple[int, str, dict[str, Any]]] = []
    for path in inbox.glob("*.report.json"):
        try:
            arrived_ns = path.stat().st_mtime_ns
        except OSError:
            continue
        item = brief(path)
        if project is not None and item.get("project") != project:
            continue
        rows.append((arrived_ns, path.name, item))
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in rows]


def bridge_status(
    project: str | None = None,
    *,
    outbox: Path,
    unread: UnreadReportsPort,
    brief: ReportBriefPort,
    heartbeat: HeartbeatStatusPort,
    quarantined: QuarantinedRequestsPort,
    reports: ProjectReportsPort,
    latest_log: PathPort,
) -> dict[str, Any]:
    """Project queue, watcher, unread, quarantine, and report state."""

    queued: list[dict[str, Any]] = []
    for path in sorted(outbox.glob("*.json")) if outbox.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            payload = {}
        if project and payload.get("project") not in (project, None, ""):
            continue
        queued.append(
            {
                "name": path.name,
                "lane": payload.get("lane") or "?",
                "project": payload.get("project") or "",
            }
        )
    unseen: list[dict[str, Any]] = []
    for path in unread():
        item = brief(path)
        if project and item["project"] not in (project, ""):
            continue
        unseen.append(item)
    watcher = heartbeat()
    in_flight = (
        watcher.get("current")
        if watcher.get("state") in ("busy", "wedged")
        else None
    )
    quarantined_rows = quarantined()
    report_rows = reports(project)
    return {
        "project": project,
        "watcher": watcher,
        "queued": queued,
        "queue_depth": len(queued),
        "in_flight": in_flight,
        "unread": unseen,
        "unread_count": len(unseen),
        "quarantined": quarantined_rows,
        "quarantined_count": len(quarantined_rows),
        "reports_total": len(report_rows),
        "latest_log": str(latest_log()),
    }


def stream_state(
    project: str | None = None,
    *,
    status: BridgeStatusPort,
    reports: ProjectReportsPort,
) -> dict[str, Any]:
    """Return the compact project-filtered SSE bridge projection."""

    current = status(project)
    report_rows = reports(project)
    newest = report_rows[-1] if report_rows else None
    return {
        "queue_depth": current["queue_depth"],
        "in_flight": 1 if current["in_flight"] else 0,
        "unread_count": current["unread_count"],
        "quarantined_count": current["quarantined_count"],
        "watcher_state": (current["watcher"] or {}).get("state"),
        "reports_total": len(report_rows),
        "latest_report": newest,
    }


__all__ = [
    "bridge_status",
    "latest_log",
    "mark_read",
    "note_report_arrival",
    "project_report_briefs",
    "quarantined_requests",
    "report_brief",
    "seen_dir",
    "stream_state",
    "unread_reports",
]
