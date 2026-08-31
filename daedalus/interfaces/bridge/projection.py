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
    "mark_read",
    "project_report_briefs",
    "quarantined_requests",
    "report_brief",
    "stream_state",
    "unread_reports",
]
