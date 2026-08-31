"""Conversation projection ownership for terminal file-bridge reports.

The legacy :mod:`daedalus.file_bridge` module remains the registered effect
facade.  This module owns the deterministic projection/reconciliation logic
and receives the canonical conversation store plus file-bus operations as
ports, so it cannot mint a second event, retry, or persistence authority.
"""
from __future__ import annotations

import errno
import re
from pathlib import Path
from typing import Any, Callable


_REQUEST_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}\Z")
_TRANSIENT_OS_ERRNOS = {
    errno.EAGAIN,
    errno.EBUSY,
    errno.EINTR,
    errno.ETIMEDOUT,
    *({errno.ESTALE} if hasattr(errno, "ESTALE") else set()),
}


class ConversationProjectionPending(RuntimeError):
    """A terminal bridge report exists, but its linked chat projection is
    temporarily unavailable.

    This is not poison input and must never trigger quarantine or another
    provider call. The report remains the task's authoritative terminal fact;
    leaving the request unarchived makes the watcher retry only the idempotent
    canonical-spine projection on its next pass.
    """

    def __init__(self, key: str, cause: BaseException) -> None:
        self.key = str(key)
        self.cause = cause
        self.retry_queued = False
        super().__init__(
            f"conversation projection pending for {self.key}: "
            f"{type(cause).__name__}: {cause}"
        )


class ConversationProjectionFailed(RuntimeError):
    """A terminal report cannot be projected without contradicting state.

    Unlike :class:`ConversationProjectionPending`, this exception owns no
    projection retry. ``process_request`` preserves the report, records the
    diagnostic in the existing crash journal and archives the request before
    raising it. The watcher catches it separately from poison input so it can
    never overwrite the authoritative report with a quarantine report.
    """

    def __init__(self, key: str, cause: BaseException) -> None:
        self.key = str(key)
        self.cause = cause
        super().__init__(
            f"conversation projection failed permanently for {self.key}: "
            f"{type(cause).__name__}: {cause}"
        )


def is_transient_projection_failure(
    exc: BaseException,
    *,
    sqlite_operational_error: type[BaseException],
) -> bool:
    """Return whether retrying only the same report projection can succeed."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite_operational_error):
            message = str(current).lower()
            if "locked" in message or "busy" in message:
                return True
        elif type(current) is OSError and current.errno is None:
            message = str(current).lower()
            if any(
                marker in message
                for marker in (
                    "temporarily unavailable",
                    "temporary unavailable",
                    "timed out",
                    "locked",
                    "busy",
                )
            ):
                return True
        elif isinstance(current, (BlockingIOError, InterruptedError, TimeoutError)):
            return True
        elif isinstance(current, OSError):
            if current.errno in _TRANSIENT_OS_ERRNOS:
                return True
            if getattr(current, "winerror", None) in {32, 33}:
                return True
        current = current.__cause__ or current.__context__
    return False


def project_report(
    key: str,
    report: dict[str, Any],
    *,
    default_db_path: Callable[[], Path],
    default_store: Callable[[], Any],
    report_fields: Callable[
        [str, dict[str, Any]], tuple[str, str, dict[str, Any]]
    ],
    is_transient_failure: Callable[[BaseException], bool],
) -> Any:
    """Project a linked terminal report once onto the canonical spine."""

    try:
        if not default_db_path().exists():
            return None
        store = default_store()
        if store.dispatch_status(key) is None:
            return None
        outcome_state, summary, detail = report_fields(key, report)
        return store.record_dispatch_event(
            key,
            outcome_state=outcome_state,
            summary=summary,
            detail=detail,
            source_event_id=f"file_bridge.report:{key}",
        )
    except Exception as exc:
        if is_transient_failure(exc):
            raise ConversationProjectionPending(key, exc) from exc
        raise


def prepare_reconciliation(
    task_id: str,
    *,
    inbox: Path,
    completed_report: Callable[[Path], dict[str, Any] | None],
) -> tuple[str, dict[str, Any]] | None:
    """Validate a request key and load its complete fixed-path report."""

    key = str(task_id or "").strip()
    if not _REQUEST_KEY_RE.fullmatch(key):
        raise ValueError("task_id must be a plain file-bridge request key")
    report_path = inbox / f"{key}.report.json"
    try:
        report_path.resolve().relative_to(inbox.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("task_id resolves outside the file-bridge inbox") from exc
    report = completed_report(report_path)
    if report is None:
        return None
    recorded_key = str(report.get("request_file") or "").strip()
    if recorded_key and recorded_key != key:
        raise ValueError(
            f"terminal report identity mismatch: path key={key!r}, "
            f"report request_file={recorded_key!r}"
        )
    return key, report


def finish_reconciliation(
    key: str,
    report: dict[str, Any],
    *,
    project: Callable[[str, dict[str, Any]], Any],
    requeue: Callable[[str], bool],
) -> Any:
    """Project a prepared report and own projection-only retry classification."""

    try:
        return project(key, report)
    except ConversationProjectionPending as exc:
        exc.retry_queued = requeue(key)
        raise


def requeue_for_projection(
    key: str,
    *,
    archive: Path,
    outbox: Path,
    read_journal: Callable[[str], dict[str, Any]],
    replace: Callable[[Path, Path], Any],
    move: Callable[[str, str], Any],
    move_error: type[BaseException],
) -> bool:
    """Return an archived request to the existing projection-only retry bus."""

    entry = read_journal(key)
    steps = entry.get("steps") if isinstance(entry.get("steps"), dict) else {}
    if steps.get("report") is not True:
        return False
    source = archive / f"{key}.json"
    target = outbox / f"{key}.json"
    if target.exists():
        return True
    if not source.is_file():
        return False
    outbox.mkdir(parents=True, exist_ok=True)
    try:
        replace(source, target)
    except OSError:
        try:
            move(str(source), str(target))
        except (OSError, move_error):
            return target.is_file()
    return target.is_file()
