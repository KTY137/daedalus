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


class RequestIdentityConflict(RuntimeError):
    """A filename key was reused for different canonical request bytes.

    The old journal/report remain authoritative and untouched. Only the new,
    contradictory outbox file is moved to a digest-suffixed quarantine path.
    Watch/CLI recovery must surface this exception directly; routing it through
    quarantine would overwrite the old report under the shared filename key.
    """

    def __init__(
        self,
        key: str,
        expected: str,
        observed: str,
        quarantine_path: Path,
        *,
        moved: bool,
        quarantine_error: BaseException | None = None,
    ) -> None:
        self.key = str(key)
        self.expected = str(expected)
        self.observed = str(observed)
        self.quarantine_path = Path(quarantine_path)
        self.moved = bool(moved)
        self.quarantine_error = quarantine_error
        state = "quarantined" if moved else "quarantine move pending"
        if quarantine_error is not None:
            state += f": {type(quarantine_error).__name__}: {quarantine_error}"
        super().__init__(
            f"request filename key {self.key!r} is already bound to "
            f"sha256:{self.expected}; received sha256:{self.observed} "
            f"({state} at {self.quarantine_path})"
        )


class TerminalReportPreserved(RuntimeError):
    """Poison recovery refused to overwrite an already durable report."""

    def __init__(self, key: str, report_path: Path, reason: str) -> None:
        self.key = str(key)
        self.report_path = Path(report_path)
        self.reason = str(reason)
        super().__init__(
            f"terminal report for {self.key!r} remains authoritative at "
            f"{self.report_path}; destructive quarantine was refused: "
            f"{self.reason}"
        )


class QuarantineMovePending(RuntimeError):
    """A quarantine report is durable but its source file is still queued.

    A Windows sharing violation can prevent the final move after every other
    quarantine fact has landed. This state is neither successful completion
    nor poison input: callers must report it as pending and retry only the
    move, never rewrite the report or redispatch provider work.
    """

    def __init__(self, key: str, path: Path, destination: Path) -> None:
        self.key = str(key)
        self.path = Path(path)
        self.destination = Path(destination)
        super().__init__(
            f"quarantine move pending for {self.key!r}: "
            f"{self.path} -> {self.destination}"
        )


@dataclass(frozen=True)
class IdentityConflictPorts:
    """Authority used to retain one contradictory request outside the key."""

    inbox: Path
    quarantine_dir: Callable[[], Path]
    now_iso: Callable[[], str]
    write_json_atomic: Callable[[Path, dict[str, Any]], None]
    replace: Callable[[Path, Path], Any]
    move: Callable[[str, str], Any]
    move_error: type[BaseException]


@dataclass(frozen=True)
class QuarantinePorts:
    """All persistence and projection authority consumed by quarantine."""

    inbox: Path
    trace_key: str
    request_key: Callable[[Path], str]
    quarantine_dir: Callable[[], Path]
    read_journal: Callable[[str], dict[str, Any]]
    raw_request_sha256: Callable[[Path], str]
    canonical_sha: Callable[[Any], str]
    completed_report: Callable[[Path], dict[str, Any] | None]
    stamp_report: Callable[..., dict[str, Any]]
    now_iso: Callable[[], str]
    write_journal: Callable[[str, dict[str, Any]], None]
    write_json_atomic: Callable[[Path, dict[str, Any]], None]
    project_report: Callable[[str, dict[str, Any]], Any]
    conversation_projection_pending: type[BaseException]
    conversation_projection_failed: Callable[..., BaseException]
    note_report_arrival: Callable[..., None]
    quarantine_move: Callable[[Path, str], bool]


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


def quarantine_request_identity_conflict(
    path: Path,
    key: str,
    *,
    expected: str,
    observed: str,
    ports: IdentityConflictPorts,
) -> RequestIdentityConflict:
    """Evict only the contradictory request and preserve old key artifacts."""

    directory = ports.quarantine_dir()
    suffix = observed[:16]
    destination = directory / f"{key}.identity-conflict-{suffix}{path.suffix}"
    sidecar = directory / f"{destination.stem}.error.json"
    detail = {
        "request_file": key,
        "reason": "request_identity_conflict",
        "error": (
            f"filename key is bound to sha256:{expected}; "
            f"contradictory request is sha256:{observed}"
        ),
        "expected_request_sha256": expected,
        "observed_request_sha256": observed,
        "preserved_report": str(ports.inbox / f"{key}.report.json"),
        "quarantine_path": str(destination),
        "quarantined_at": ports.now_iso(),
    }
    moved = False
    quarantine_error: BaseException | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        ports.write_json_atomic(sidecar, detail)
        moved = not path.exists()
        if not moved:
            try:
                ports.replace(path, destination)
                moved = True
            except OSError as replace_exc:
                try:
                    ports.move(str(path), str(destination))
                    moved = True
                except (OSError, ports.move_error) as move_exc:
                    quarantine_error = RuntimeError(
                        f"atomic move failed ({replace_exc}); fallback move "
                        f"failed ({move_exc})"
                    )
    except (OSError, ports.move_error) as exc:
        quarantine_error = exc
    return RequestIdentityConflict(
        key,
        expected,
        observed,
        destination,
        moved=moved,
        quarantine_error=quarantine_error,
    )


def move_quarantined_request(
    path: Path,
    key: str,
    *,
    quarantine_dir: Callable[[], Path],
    replace: Callable[[Path, Path], Any],
    move: Callable[[str, str], Any],
    move_error: type[BaseException],
) -> bool:
    """Move one request to its fixed quarantine location, with fallback."""

    if not path.exists():
        return True
    directory = quarantine_dir()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{key}{path.suffix}"
    try:
        replace(path, destination)
    except OSError:
        try:
            move(str(path), str(destination))
        except (OSError, move_error):
            return False
    return True


def quarantine_request(
    path: Path,
    reason: str,
    detail: str,
    *,
    ports: QuarantinePorts,
) -> Path:
    """Publish and finish one crash-replayable quarantine transaction."""

    key = ports.request_key(path)
    destination = ports.quarantine_dir() / path.name
    entry = ports.read_journal(key)
    result_path = ports.inbox / f"{key}.report.json"
    raw_sha256 = ports.raw_request_sha256(path)
    identity = ports.canonical_sha(
        {
            "request_file": key,
            "request_raw_sha256": raw_sha256,
            "reason": str(reason),
            "detail": str(detail),
        }
    )
    pending = entry.get("quarantine_record")
    pending = pending if isinstance(pending, dict) else {}
    pending_report = pending.get("report")
    pending_report = pending_report if isinstance(pending_report, dict) else None
    pending_matches = (
        pending.get("identity") == identity
        and pending.get("request_raw_sha256") == raw_sha256
        and pending.get("reason") == str(reason)
        and pending.get("detail") == str(detail)
        and pending_report is not None
    )
    existing = ports.completed_report(result_path)
    if existing is not None:
        if not pending_matches or ports.canonical_sha(existing) != (
            ports.canonical_sha(pending_report)
        ):
            raise TerminalReportPreserved(
                key, result_path, f"{reason}: {detail}"
            )
        report = existing
    else:
        if pending_matches:
            report = pending_report
        else:
            report = ports.stamp_report(
                {
                    "request_file": key,
                    "bridge_status": "quarantined",
                    "error": f"{reason}: {detail}",
                    "reason": reason,
                    "quarantined_at": ports.now_iso(),
                    "quarantine_path": str(destination),
                },
                trace_id=entry.get(ports.trace_key),
            )
            entry["quarantine_record"] = {
                "identity": identity,
                "request_raw_sha256": raw_sha256,
                "reason": str(reason),
                "detail": str(detail),
                "report": report,
            }
            entry["state"] = "quarantine_pending"
            entry["key"] = key
            ports.write_journal(key, entry)
        ports.write_json_atomic(result_path, report)

    projection_failure: BaseException | None = None
    try:
        ports.project_report(key, report)
    except ports.conversation_projection_pending:
        raise
    except Exception as exc:
        projection_failure = exc
        entry["conversation_projection_error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        }
    ports.note_report_arrival(result_path, report, key=key)
    ports.write_json_atomic(ports.quarantine_dir() / f"{key}.error.json", report)
    entry["state"] = "quarantine_move_pending"
    entry["key"] = key
    entry["reason"] = reason
    ports.write_journal(key, entry)
    if not ports.quarantine_move(path, key):
        raise QuarantineMovePending(key, path, destination)
    entry["state"] = "quarantined"
    ports.write_journal(key, entry)
    if projection_failure is not None:
        raise ports.conversation_projection_failed(
            key, projection_failure
        ) from projection_failure
    return result_path


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
