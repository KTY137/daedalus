"""Claimed request dispatch behind the File Bridge effect facade.

The registered ``file_bridge.process`` effect start remains in
``daedalus.file_bridge.process_request``.  This owner acquires the canonical
per-request OS claim and resolves the crash race where another consumer has
already archived the source while the loser waited.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager


CompletedReportPort = Callable[[Path], dict[str, Any] | None]
KeyPort = Callable[[Path], str]
LockPort = Callable[[Path, str], ContextManager[Any]]
ProcessClaimedPort = Callable[..., Path]
RequestLockPathPort = Callable[[str], Path]


@dataclass(frozen=True)
class ClaimedDispatchPorts:
    """All authority consumed by the claimed request state machine."""

    inbox: Path
    archive: Path
    max_attempts: int
    trace_key: str
    read_journal: Callable[[str], dict[str, Any]]
    raw_request_sha256: Callable[[Path], str]
    quarantine_identity_conflict: Callable[..., BaseException]
    quarantine_move: Callable[[Path, str], bool]
    quarantine_dir: Callable[[], Path]
    write_journal: Callable[[str, dict[str, Any]], None]
    quarantine_move_pending: Callable[..., BaseException]
    conversation_projection_failed: Callable[..., BaseException]
    quarantine_request: Callable[[Path, str, str], Path]
    read_request: Callable[[Path, str | None], dict[str, Any]]
    request_sha256: Callable[[dict[str, Any]], str]
    completed_report: Callable[[Path], dict[str, Any] | None]
    report_request_binding: Callable[[dict[str, Any], str], str]
    terminal_report_preserved: Callable[..., BaseException]
    terminal_bookkeeping_pending: type[BaseException]
    finish_terminal_report: Callable[..., None]
    effect_identity_for: Callable[[str, dict[str, Any]], dict[str, str]]
    write_json_atomic: Callable[[Path, dict[str, Any]], None]
    accepts_keyword: Callable[[Any, str], bool]
    mission_projection_dir: Callable[[str], Path]
    process_bridge_payload: Callable[..., dict[str, Any]]
    adopt_trace: Callable[[str | None], ContextManager[str | None]]
    stamp_report: Callable[..., dict[str, Any]]
    project_report: Callable[[str, dict[str, Any]], Any]
    conversation_projection_pending: type[BaseException]


def claim_and_dispatch_request(
    path: Path,
    default_repo_root: str | None,
    *,
    inbox: Path,
    key_for: KeyPort,
    lock_path_for: RequestLockPathPort,
    lock: LockPort,
    completed_report: CompletedReportPort,
    process_claimed: ProcessClaimedPort,
) -> Path:
    """Process one request under its filename-derived cross-process claim."""

    key = key_for(path)
    label = f"file-bridge request {key!r}"
    with lock(lock_path_for(key), label):
        if not path.exists():
            result_path = inbox / f"{key}.report.json"
            if completed_report(result_path) is not None:
                return result_path
            raise FileNotFoundError(path)
        return process_claimed(path, default_repo_root, key=key)


def process_claimed_request(
    path: Path,
    default_repo_root: str | None,
    *,
    key: str,
    ports: ClaimedDispatchPorts,
) -> Path:
    """Run the crash-safe request state machine under its existing OS claim."""

    ports.inbox.mkdir(parents=True, exist_ok=True)
    ports.archive.mkdir(parents=True, exist_ok=True)
    result_path = ports.inbox / f"{key}.report.json"
    entry = ports.read_journal(key)

    steps = entry.get("steps") if isinstance(entry.get("steps"), dict) else {}
    attempts = int(entry.get("attempts") or 0)
    entry.update(
        {
            "key": key,
            "steps": steps,
            "attempts": attempts,
            "state": entry.get("state") or "new",
        }
    )

    quarantine_record = entry.get("quarantine_record")
    quarantine_record = (
        quarantine_record if isinstance(quarantine_record, dict) else {}
    )
    if (
        entry.get("state")
        in {"quarantine_pending", "quarantine_move_pending", "quarantined"}
        and quarantine_record
    ):
        observed_raw_sha256 = ports.raw_request_sha256(path)
        expected_raw_sha256 = quarantine_record.get("request_raw_sha256")
        if expected_raw_sha256 != observed_raw_sha256:
            raise ports.quarantine_identity_conflict(
                path,
                key,
                expected=str(expected_raw_sha256),
                observed=observed_raw_sha256,
            )
        if entry.get("state") in {"quarantine_move_pending", "quarantined"}:
            if not ports.quarantine_move(path, key):
                raise ports.quarantine_move_pending(
                    key, path, ports.quarantine_dir() / path.name
                )
            if entry.get("state") != "quarantined":
                entry["state"] = "quarantined"
                ports.write_journal(key, entry)
            projection_error = entry.get("conversation_projection_error")
            if isinstance(projection_error, dict):
                cause = RuntimeError(
                    f"{projection_error.get('type', 'projection error')}: "
                    f"{projection_error.get('message', '')}"
                )
                raise ports.conversation_projection_failed(key, cause) from cause
            return result_path
        return ports.quarantine_request(
            path,
            str(quarantine_record.get("reason") or "quarantined"),
            str(quarantine_record.get("detail") or ""),
        )

    payload = ports.read_request(path, default_repo_root)
    observed_request_sha256 = ports.request_sha256(payload)
    expected_request_sha256 = entry.get("request_sha256")
    identity_report = ports.completed_report(result_path)
    report_request_sha256: str | None = None
    if identity_report is not None:
        try:
            report_request_sha256 = ports.report_request_binding(identity_report, key)
        except ValueError as exc:
            raise ports.terminal_report_preserved(
                key, result_path, str(exc)
            ) from exc
    if expected_request_sha256 is None and report_request_sha256 is not None:
        expected_request_sha256 = report_request_sha256
    if expected_request_sha256 is not None and (
        not isinstance(expected_request_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_request_sha256)
        or expected_request_sha256 != observed_request_sha256
    ):
        raise ports.quarantine_identity_conflict(
            path,
            key,
            expected=str(expected_request_sha256),
            observed=observed_request_sha256,
        )
    if entry.get("request_sha256") is None:
        entry["request_sha256"] = observed_request_sha256
        ports.write_journal(key, entry)
    elif (
        report_request_sha256 is not None
        and report_request_sha256 != observed_request_sha256
    ):
        raise ports.quarantine_identity_conflict(
            path,
            key,
            expected=report_request_sha256,
            observed=observed_request_sha256,
        )

    if entry.get("state") == "quarantined":
        if not ports.quarantine_move(path, key):
            raise ports.quarantine_move_pending(
                key, path, ports.quarantine_dir() / path.name
            )
        return result_path

    if entry.get("state") == "bookkeeping_pending":
        report = ports.completed_report(result_path)
        if report is None:
            cause = ValueError(
                "bookkeeping-pending journal state has no terminal report"
            )
            raise ports.terminal_bookkeeping_pending(key, "report", cause)
        ports.finish_terminal_report(
            path, key, result_path, report, entry, steps
        )
        return result_path

    if entry.get("state") in {"projection_failed", "done_with_projection_error"}:
        report = ports.completed_report(result_path)
        if report is None:
            cause = ValueError(
                "projection-failed journal state has no complete terminal report"
            )
            raise ports.conversation_projection_failed(key, cause)
        try:
            ports.finish_terminal_report(
                path,
                key,
                result_path,
                report,
                entry,
                steps,
                terminal_state="done_with_projection_error",
            )
        except ports.terminal_bookkeeping_pending as finish_exc:
            raise ports.conversation_projection_failed(key, finish_exc) from finish_exc
        except Exception as exc:
            raise ports.conversation_projection_failed(key, exc) from exc
        return result_path

    report = identity_report
    if report is not None and not steps.get("report"):
        steps["report"] = True
        entry["request_sha256"] = observed_request_sha256
        entry["state"] = "reported"
        ports.write_journal(key, entry)
    if report is None:
        if attempts >= ports.max_attempts:
            return ports.quarantine_request(
                path,
                "interrupted",
                f"dispatched {attempts} times without ever producing a report "
                "-- refusing to run it again (see runs/processed/.journal)",
            )
        effect_identity = ports.effect_identity_for(key, entry)
        entry["attempts"] = attempts + 1
        entry["state"] = "in_flight"
        entry["lane"] = payload.get("lane")
        entry["effect_identity"] = effect_identity
        entry[ports.trace_key] = payload.get(ports.trace_key)
        ports.write_journal(key, entry)

        with ports.adopt_trace(payload.get(ports.trace_key)) as trace_id:
            dispatch_kwargs: dict[str, Any] = {
                "effect_identity": effect_identity,
            }
            if ports.accepts_keyword(
                ports.process_bridge_payload, "mission_projection_dir"
            ):
                dispatch_kwargs["mission_projection_dir"] = (
                    ports.mission_projection_dir(key)
                )
            report = ports.process_bridge_payload(payload, **dispatch_kwargs)
        report["request_file"] = key
        report["request_sha256"] = observed_request_sha256
        if payload.get(ports.trace_key):
            report = ports.stamp_report(report, trace_id=trace_id)

        ports.write_json_atomic(result_path, report)
        steps["report"] = True
        entry["state"] = "reported"
        ports.write_journal(key, entry)

    try:
        ports.project_report(key, report)
    except ports.conversation_projection_pending:
        raise
    except Exception as exc:
        entry["state"] = "projection_failed"
        entry["conversation_projection_error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        }
        try:
            ports.write_journal(key, entry)
            ports.finish_terminal_report(
                path,
                key,
                result_path,
                report,
                entry,
                steps,
                terminal_state="done_with_projection_error",
            )
        except ports.terminal_bookkeeping_pending as finish_exc:
            raise ports.conversation_projection_failed(key, finish_exc) from exc
        except Exception as finish_exc:
            raise ports.conversation_projection_failed(key, finish_exc) from exc
        raise ports.conversation_projection_failed(key, exc) from exc

    ports.finish_terminal_report(path, key, result_path, report, entry, steps)
    return result_path
