from __future__ import annotations

import inspect
import os
import sqlite3
import uuid
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import write_text_atomic
from .interfaces.bridge import cli as bridge_cli
from .interfaces.bridge import conversation as bridge_conversation
from .interfaces.bridge import dispatch as bridge_dispatch
from .interfaces.bridge import journal as bridge_journal
from .interfaces.bridge import projection as bridge_projection
from .interfaces.bridge import queue as bridge_queue
from .interfaces.bridge import watcher as bridge_watcher
from .memory import record_from_bridge_report
from .projects import resolve_repo_root
from .spine import envelope


ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "runs" / "processed"
# Watcher liveness marker (see heartbeat_status): written by the watch loop,
# read by `daedalus doctor` and `file_bridge status`.
HEARTBEAT_PATH = ROOT / "runs" / "bridge_heartbeat.json"

# Heartbeat policy: an idle watcher beats every poll (throttled to
# IDLE_BEAT_EVERY_S); a beat older than STALE_AFTER_S with no in-flight task
# means the watcher is dead. While a task is in flight the beat carries
# `current` and is allowed to age up to BUSY_BUDGET_S (codex real-task budget
# is 8-20 min, provider timeout 1500 s -- a 2 min rule would false-alarm).
IDLE_BEAT_EVERY_S = 15.0
STALE_AFTER_S = 120.0
BUSY_BUDGET_S = 1800.0

# Codex-lane protocol lesson (2026-07-11, cost ~2 h): objectives longer than
# this without a CODEX_QUEUE.md reference smell like an inline task brief and
# get a (non-blocking) warning from enqueue().
CODEX_INLINE_BRIEF_CHARS = 200

# A request interrupted before any durable Effect-Lease start is retried on
# restart, but not forever. Once a canonical execution has started, the
# filename-derived replay identity below makes the ledger refuse a second
# provider effect; this bound remains the last net for pre-start hard kills and
# non-provider work that never produced a report.
MAX_ATTEMPTS = 3

# A request whose JSON does not parse is only poison once it has stopped
# changing. A fresher one is probably still being written by a producer that
# does not publish atomically (a hand-drop, a foreign tool -- our own enqueue()
# does publish atomically), and destroying that would lose a perfectly good
# request whose only fault was being slow.
SETTLE_GRACE_S = 5.0

WatcherNotRunning = bridge_queue.WatcherNotRunning


ConversationProjectionPending = bridge_conversation.ConversationProjectionPending
ConversationProjectionFailed = bridge_conversation.ConversationProjectionFailed
TerminalBookkeepingPending = bridge_dispatch.TerminalBookkeepingPending


RequestIdentityConflict = bridge_dispatch.RequestIdentityConflict
TerminalReportPreserved = bridge_dispatch.TerminalReportPreserved
QuarantineMovePending = bridge_dispatch.QuarantineMovePending


def _is_transient_projection_failure(exc: BaseException) -> bool:
    """Whether retrying the *same report projection* can plausibly succeed.

    The distinction is load-bearing: :class:`ConversationProjectionPending`
    owns an automatic retry and may move an archived request back to OUTBOX.
    Integrity disagreements, unknown dispatches, malformed data and other
    permanent failures must retain their original exception type so the API
    can surface them without creating a retry loop.

    ConversationStore may wrap a SQLite setup failure in ``ConversationError``;
    inspect the exception chain so only SQLite BUSY/LOCKED survives that
    wrapper. An errno-less ``OSError`` is retryable only when its message says
    it is temporary/busy/locked/timed out; an unqualified I/O complaint is not
    enough to claim retry ownership. Known permanent filesystem failures such
    as missing paths, permissions, read-only media and invalid paths are not
    retry-owned here.
    """
    return bridge_conversation.is_transient_projection_failure(
        exc,
        sqlite_operational_error=sqlite3.OperationalError,
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seen_dir() -> Path:
    """Read-state ledger: one marker file per acknowledged report.

    Derived from INBOX at call time so tests that patch INBOX get a matching
    ledger for free."""
    return bridge_projection.seen_dir(INBOX)


def _latest_log() -> Path:
    """Single well-known append-only file -- one line per finished report --
    so an orchestrator can file-watch exactly one path instead of polling."""
    return bridge_projection.latest_log(INBOX)


# -- crash safety: one request -> one report, one conversation projection, ...
#
# process_request() applies five possible side effects in sequence (report ->
# linked-conversation projection -> arrival line -> memory record -> archive
# move). A crash between any two of the original four left the request sitting
# in the outbox with some effects already applied, and the restarted watcher
# redid ALL of them: it re-ran (and on a paid lane re-billed) the work, appended
# a SECOND LATEST.log line and a SECOND memory record.
#
# The cure is a per-request journal keyed by the request filename STEM. That
# stem is unique by construction only because enqueue() puts a uuid in it --
# which is precisely what makes it usable as an idempotency key. Each step is
# made exactly-once by a mechanism chosen so that the window between "did it"
# and "wrote down that I did it" cannot produce a duplicate:
#
#   report  -- fixed path + os.replace. Rewriting it is a no-op, and the
#              expensive work behind it is skipped whenever a COMPLETE report
#              for the key already exists.
#   conversation -- the request key is both the dispatch_ref and the stable
#              source-event identity. A partial unique index on the canonical
#              spine makes replay return the first fact; no file-journal flag
#              is asked to decide whether the authoritative write landed.
#   log     -- the arrival line carries `key=<stem>`; the append is skipped if
#              the log already contains that key. A content check, no window.
#   memory  -- two-phase journal flag. The one ambiguous state ("we died with
#              the append in flight") is resolved by scanning the memory log
#              for the key, which is why the report carries `request_file`.
#              That scan reads the whole memory log, so it is paid ONLY on
#              that recovery path and never on the happy path.
#   archive -- fixed destination path; os.replace overwrites, so even an
#              interrupted cross-device move resolves to one archived file.
#
# Leased Ikarus provider dispatch closes the otherwise ambiguous first window
# with the canonical Effect-Lease ledger: the journal retains only the stable
# identity needed to ask that ledger about the exact execution.  The local
# ``strategy=configure`` path is different: it starts no provider, network or
# spend effect, and its role write is a deterministic upsert.  A crash after
# that write but before this report can repeat the convergent local write; it
# is deliberately not advertised as leased exactly-once provider execution.


def _request_key(path: Path) -> str:
    """The idempotency key of a request: its filename stem.

    Safe as a key only because enqueue() embeds a uuid in the name -- the
    older second-resolution stamp was not unique, so neither was this."""
    return bridge_journal.request_key(path)


def _request_sha256(payload: dict[str, Any]) -> str:
    """Canonical identity of the normalized request body behind one key."""
    return bridge_journal.request_sha256(
        payload,
        canonical_sha=envelope.canonical_sha,
    )


def _raw_request_sha256(path: Path) -> str:
    """Byte identity used when poison input cannot be normalized as JSON."""
    return bridge_journal.raw_request_sha256(path)


def _report_request_binding(report: dict[str, Any], key: str) -> str:
    """Return the canonical request digest proven by one whole bridge report.

    The report is the terminal authority across the tiny crash window between
    its atomic publication and the following journal update.  Reusing it
    without checking its self-contained request binding would let an unrelated
    or malformed artifact suppress real work; ignoring a valid binding would
    let replay overwrite the original terminal outcome.  Both are fail-closed.
    """
    return bridge_journal.report_request_binding(
        report,
        key,
        request_sha=_request_sha256,
    )


def _quarantine_request_identity_conflict(
    path: Path,
    key: str,
    *,
    expected: str,
    observed: str,
) -> RequestIdentityConflict:
    """Evict only a contradictory NEW request; preserve the old key artifacts.

    ``quarantine_request`` deliberately is not reused: its report path is
    ``<key>.report.json``, which is exactly the completed artifact this conflict
    must not overwrite.  The observed digest gives the contradictory file and
    sidecar their own deterministic names without minting another authority.
    """
    return bridge_dispatch.quarantine_request_identity_conflict(
        path,
        key,
        expected=expected,
        observed=observed,
        ports=bridge_dispatch.IdentityConflictPorts(
            inbox=INBOX,
            quarantine_dir=_quarantine_dir,
            now_iso=_now_iso,
            write_json_atomic=_write_json_atomic,
            replace=os.replace,
            move=shutil.move,
            move_error=shutil.Error,
        ),
    )


def _effect_identity_for(key: str, entry: dict[str, Any]) -> dict[str, str]:
    """Return this request's internal, durable Effect-Lease identity.

    The attempt and lease ids are derived from the filename key, never from
    request JSON.  ``issued_at`` is the only clock input to the signed lease,
    so it is captured once in the existing per-request crash journal before
    dispatch.  A missing journal can safely recreate the deterministic ids:
    if the effect ledger already knows them, changed lease bytes conflict and
    fail closed instead of authorising a second provider call.
    """
    return bridge_journal.effect_identity_for(
        key,
        entry,
        now=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    )


def _journal_dir() -> Path:
    """Per-request processing journal. Derived from ARCHIVE at call time so a
    test that patches ARCHIVE gets a matching journal for free."""
    return bridge_journal.journal_dir(ARCHIVE)


def _mission_projection_dir(key: str) -> Path:
    """Internal disposable projection path derived only from the file key."""
    return bridge_journal.mission_projection_dir(
        key,
        journal=_journal_dir(),
    )


def _accepts_keyword(callable_object: Any, keyword: str) -> bool:
    """Keep old injected test/compatibility callables source-compatible."""

    # ``unittest.mock.Mock`` exposes ``(*args, **kwargs)`` even when its
    # side-effect function keeps the old narrow ABI.  Inspect that concrete
    # callable when present so adding this informational projection cannot
    # make an old injected worker fail after dispatch.
    side_effect = getattr(callable_object, "side_effect", None)
    if callable(side_effect):
        callable_object = side_effect
    try:
        parameters = inspect.signature(callable_object).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == keyword
        for parameter in parameters
    )


def _quarantine_dir() -> Path:
    """Where requests the watcher cannot process go to be SEEN.

    Deliberately neither the outbox (leaving poison there crash-loops the
    watcher on it every poll, forever) nor the plain archive (which would hide
    a request that was never done among the ones that were). Not dot-prefixed:
    the whole point is that a human notices it."""
    return ARCHIVE / "quarantine"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish a small JSON file whole or not at all.

    Same trick as enqueue(): write under a name no consumer's glob matches,
    then os.replace. Consumers of the inbox glob `*.report.json`, which never
    matches `*.report.json.tmp`.

    Delegates to ``daedalus.atomic``, which adds two things this lacked:

    * the MEASURED win32 retry -- the watcher polls this directory, so it is
      holding these files open when the replace lands;
    * a RANDOM temp suffix. This used to be a fixed ``.tmp``, so two publishers
      racing on the same target wrote one scratch file and one could publish the
      other's half-written bytes. The suffix still ends in ``.tmp``, so no
      consumer glob starts matching it."""
    return bridge_journal.write_json_atomic(
        path,
        payload,
        write_text=write_text_atomic,
    )


def _read_journal(key: str) -> dict[str, Any]:
    """The journal for one request, or an empty dict if there is none.

    A truncated/corrupt journal reads as empty, i.e. as 'nothing has happened
    yet'. That direction is the safe one: it can cost a repeated step, whereas
    trusting garbage would skip a step that never ran."""
    return bridge_journal.read_journal(key, path_for=_journal_path)


def _journal_path(key: str) -> Path:
    return bridge_journal.journal_path(key, journal=_journal_dir())


def _request_lock_path(key: str) -> Path:
    """Cross-process claim for one filename-derived request identity."""
    return bridge_journal.request_lock_path(key, journal=_journal_dir())


def _crash_journal_decision(detail: str):
    """Run the ``file_bridge.crash_journal`` contract for one effect start.

    The mechanical check is the contract's real precondition: the durable
    journal directory exists (created idempotently) and is a directory, so a
    kill between dispatch and report lands in replayable state instead of a
    silent loss.  The decision names the journal location it verified.
    """
    from daedalus.spine.effect_boundary import GuardDecision

    allowed, evidence = bridge_journal.crash_journal_state(
        detail,
        journal=_journal_dir(),
    )
    return GuardDecision("file_bridge.crash_journal", allowed, evidence)


def _write_journal(key: str, entry: dict[str, Any]) -> None:
    bridge_journal.write_journal(
        key,
        entry,
        now=_now_iso,
        path_for=_journal_path,
        write_json=_write_json_atomic,
    )


def _completed_report(result_path: Path) -> dict[str, Any] | None:
    """A previous run's report, or None if it is absent or not a whole document.

    Reports are published with os.replace so on disk they are whole or missing
    -- but a report left by an older build (plain write_text) can be half a
    document, and reusing one of those would hand back a truncated result as
    if the work had succeeded. Parse before trusting."""
    return bridge_journal.completed_report(result_path)


def _memory_already_recorded(key: str) -> bool:
    """Did the memory append for this key already land?

    Costs a full read of the memory log, which is why it is consulted only when
    the journal says the append was in flight when the process died -- the one
    state where the flag alone cannot tell us. Never raises."""
    try:
        from .memory import EVENTS_PATH
    except ImportError:
        return False
    return bridge_dispatch.memory_already_recorded(
        key,
        events_path=EVENTS_PATH,
    )


def _archive_once(path: Path, key: str) -> bool:
    """Move a request into the archive at its fixed, key-derived destination.

    A FIXED destination is what makes "never two archived copies" true by
    construction: os.replace overwrites atomically, so an interrupted
    cross-device move (copy landed, source not yet unlinked) resolves to
    exactly one archived file instead of two. Returns False if the request
    could not be moved (locked file) so the caller can retry next poll."""
    return bridge_dispatch.archive_request_once(
        path,
        key,
        archive=ARCHIVE,
        replace=os.replace,
        move=shutil.move,
        move_error=shutil.Error,
    )


def codex_inline_brief_warning(objective: str, lane: str) -> str | None:
    """Return a warning string when a codex-lane objective smells like an
    inline task brief, else None. Never blocks the enqueue."""
    return bridge_queue.codex_inline_brief_warning(
        objective,
        lane,
        character_limit=CODEX_INLINE_BRIEF_CHARS,
    )


def enqueue(objective: str, repo_root: str, paths: list[str], model: str = "sonnet",
            lane: str = "auto", project: str | None = None,
            source: str = "unknown", strategy: str = "single",
            category: str | None = None, require_watcher: bool = True,
            trace_id: str | None = None) -> Path:
    """Drop one task request into the outbox for the watcher to dispatch.

    CARRIES THE RUN'S TRACE ACROSS THE PROCESS BOUNDARY. ``trace_id`` defaults
    to the ambient one, and it is written INTO THE REQUEST -- over the file
    bus, like everything else here, never a side channel. The watcher is a
    different process that may start hours later; the request file is the only
    thing that reaches it, so it is the only honest place to put the id. See
    :func:`process_request`, which re-binds it before dispatching so the
    watcher's own records land under the trace of whoever queued the work.

    REFUSES BY DEFAULT WHEN NOTHING IS LISTENING (see WatcherNotRunning).
    `require_watcher=False` is the deliberate "queue ahead, I will start the
    watcher myself" escape hatch -- it still prints the warning, because
    queueing into a dead queue on purpose is rare enough to be worth seeing.
    A `wedged` watcher is ALLOWED (a consumer exists, it is just slow) but
    warns loudly, since the queue behind it may not drain for a while.

    HISTORICAL CODEX-LANE PROTOCOL (learned 2026-07-11, cost ~2 h of bounced
    tasks): queue-file briefs worked better than inline briefs. The canonical
    watcher currently refuses this lane until its caller holds runtime-bound
    broker authority; the retained warning remains negative protocol evidence,
    not a claim that Codex dispatch is currently enabled.
    when an objective smells like an inline brief (> ~200 chars, no
    CODEX_QUEUE reference).
    """
    bridge_queue.admit_enqueue(
        objective,
        lane,
        require_watcher=require_watcher,
        stale_after_s=STALE_AFTER_S,
        busy_budget_s=BUSY_BUDGET_S,
        warning_for=codex_inline_brief_warning,
        heartbeat_snapshot=heartbeat_status,
        emit_warning=lambda message: print(message, file=sys.stderr),
    )

    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "file_bridge.enqueue",
        REGISTRY_BY_ID["file_bridge.enqueue"].effects,
        (_crash_journal_decision(f"enqueue objective={objective[:40]!r}"),),
    )
    return bridge_queue.publish_request(
        outbox=OUTBOX,
        objective=objective,
        repo_root=repo_root,
        paths=paths,
        model=model,
        lane=lane,
        project=project,
        source=source,
        strategy=strategy,
        category=category,
        trace_id=trace_id,
        clock=_stamp,
        unique_hex=lambda: uuid.uuid4().hex,
        stamp_trace=envelope.stamp,
        write_text=write_text_atomic,
    )


def _read_request(path: Path, default_repo_root: str | None) -> dict[str, Any]:
    return bridge_queue.read_request(path, default_repo_root)


def _reported_result(report: dict[str, Any]) -> tuple[str | None, str]:
    """The provider's own status/summary, labelled as reported rather than fact.

    Bridge lanes use two shapes: a top-level ``report`` or local assignments
    with one nested report each. This extraction is deliberately small and
    deterministic; the complete report remains the authoritative inbox
    artifact and is not copied into the conversation spine.
    """
    return bridge_projection.reported_result(report)


def report_application_truth(
        report: dict[str, Any]) -> tuple[bool | None, str]:
    """Return checkout-application truth from retained write evidence.

    This is intentionally owned beside the authoritative bridge report and is
    shared by the conversation projection and HTTP snapshot.  A terminal
    failure is not proof of a clean checkout: verify-fail rollback can itself
    fail and leave measured paths behind.
    """
    return bridge_projection.report_application_truth(report)


def _conversation_report_fields(
        key: str, report: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Conservative conversation projection of one terminal bridge report.

    ``bridge_status=done`` proves that the pipeline produced this report. It
    does not prove that a proposed patch was applied, verified, or promoted,
    so the strongest honest state here is PRESENT. Failed/quarantined work is
    DEGRADED. An unfamiliar terminal word stays UNKNOWN rather than becoming a
    sixth, accidentally-green state.
    """
    from .orchestration import conversation
    return bridge_projection.conversation_report_fields(
        key,
        report,
        reported=_reported_result,
        application_truth=report_application_truth,
        present=conversation.PRESENT,
        degraded=conversation.DEGRADED,
        unknown=conversation.UNKNOWN,
    )


def _project_report_to_conversation(key: str, report: dict[str, Any]):
    """Project a linked report once onto the canonical conversation spine.

    The queue's request key already is the conversation ``dispatch_ref`` and
    the report's crash-stable identity. Tasks with no link are a strict no-op.
    For linked tasks, :meth:`ConversationStore.record_dispatch_event` enforces
    the source identity in SQLite, so a crash/restart after the canonical write
    returns the existing fact instead of appending a duplicate. No second
    ledger or file-journal marker decides authoritative event identity.
    """
    from .orchestration import conversation

    return bridge_conversation.project_report(
        key,
        report,
        default_db_path=conversation.default_db_path,
        default_store=conversation.default_store,
        report_fields=_conversation_report_fields,
        is_transient_failure=_is_transient_projection_failure,
    )


def reconcile_conversation_report(task_id: str):
    """Project an already-published terminal report after a late dispatch link.

    This closes the enqueue -> link race without moving report ownership into
    the API. The task id is accepted only as a plain request key, the resolved
    path must stay inside ``INBOX``, and a missing/partial report is a no-op.
    When a complete report exists, the same report-owned projector and stable
    source identity used by :func:`process_request` are called, so concurrent
    arrival and post-link reconciliation still produce one canonical event.

    Returns that event when a linked report was projected (or replayed), else
    ``None``. A transient store/I/O/SQLite-lock failure raises
    :class:`ConversationProjectionPending`; when the existing journal proves
    report reuse is safe, the same archived request is returned to OUTBOX for
    projection-only retry. Integrity, attribution and malformed-data failures
    retain their original exception type and are never requeued. Failure is
    never confused with an absent report or an unlinked task.
    """
    prepared = bridge_conversation.prepare_reconciliation(
        task_id,
        inbox=INBOX,
        completed_report=_completed_report,
    )
    if prepared is None:
        return None
    key, report = prepared
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "file_bridge.process",
        REGISTRY_BY_ID["file_bridge.process"].effects,
        (_crash_journal_decision(f"reconcile terminal report={key}"),),
    )
    return bridge_conversation.finish_reconciliation(
        key,
        report,
        project=_project_report_to_conversation,
        requeue=_requeue_for_projection,
    )


def _requeue_for_projection(key: str) -> bool:
    """Return an archived request to OUTBOX for projection-only retry.

    ``key`` has already passed :data:`_REQUEST_KEY_RE`. The fixed archive and
    outbox names make this idempotent under concurrent reconciliation: either
    the request is already queued, or exactly one move makes it queued. This is
    the existing file bus and existing per-request journal, not another retry
    ledger.
    """
    return bridge_conversation.requeue_for_projection(
        key,
        archive=ARCHIVE,
        outbox=OUTBOX,
        read_journal=_read_journal,
        replace=os.replace,
        move=shutil.move,
        move_error=shutil.Error,
    )


def _note_report_arrival(result_path: Path, report: dict[str, Any],
                         key: str | None = None) -> None:
    """Append one line per finished report to inbox/LATEST.log (best-effort).

    Exactly one well-known path an orchestrator can watch or tail instead of
    remembering to poll the whole inbox. New reports are unread by definition
    (no .seen marker) until `file_bridge mark-read` acknowledges them.

    Passing ``key`` makes the append EXACTLY ONCE for that request: the line
    carries ``key=<key>`` and is skipped when the log already announced it.
    This is a content check against the log itself, so unlike a "did I already
    log this?" flag there is no window between appending and recording it in
    which a crash produces a duplicate line. Without a key (the ad-hoc/manual
    call) it appends unconditionally, as it always did."""
    return bridge_projection.note_report_arrival(
        result_path,
        report,
        key=key,
        latest_log=_latest_log,
        now_iso=_now_iso,
        trace_of=envelope.trace_of,
    )


def quarantine_request(path: Path, reason: str, detail: str) -> Path:
    """Take a request out of the watcher's way, permanently and visibly.

    Writes a `bridge_status: quarantined` report into the inbox (so it shows up
    as UNREAD and in `file_bridge status`), drops a `.error.json` sidecar next
    to the request, and moves the request into runs/processed/quarantine/.
    If a whole terminal report already occupies that request key, only an
    exact journal-bound quarantine continuation may resume around it; every
    other attempt refuses via :class:`TerminalReportPreserved`.  A locked final
    move is journaled and raised as :class:`QuarantineMovePending`: the next
    poll retries only that move and cannot rewrite the report or log line."""
    return bridge_dispatch.quarantine_request(
        path,
        reason,
        detail,
        ports=bridge_dispatch.QuarantinePorts(
            inbox=INBOX,
            trace_key=envelope.TRACE_KEY,
            request_key=_request_key,
            quarantine_dir=_quarantine_dir,
            read_journal=_read_journal,
            raw_request_sha256=_raw_request_sha256,
            canonical_sha=envelope.canonical_sha,
            completed_report=_completed_report,
            stamp_report=envelope.stamp,
            now_iso=_now_iso,
            write_journal=_write_journal,
            write_json_atomic=_write_json_atomic,
            project_report=_project_report_to_conversation,
            conversation_projection_pending=ConversationProjectionPending,
            conversation_projection_failed=ConversationProjectionFailed,
            note_report_arrival=_note_report_arrival,
            quarantine_move=_quarantine_move,
        ),
    )


def _quarantine_move(path: Path, key: str) -> bool:
    return bridge_dispatch.move_quarantined_request(
        path,
        key,
        quarantine_dir=_quarantine_dir,
        replace=os.replace,
        move=shutil.move,
        move_error=shutil.Error,
    )


def _finish_terminal_report(
        path: Path, key: str, result_path: Path, report: dict[str, Any],
        entry: dict[str, Any], steps: dict[str, Any], *,
        terminal_state: str = "done") -> None:
    """Finish non-provider effects for one already durable terminal report.

    This is shared by the happy path and the permanent conversation-projection
    path. Keeping it below the report boundary is what lets the latter archive
    cleanly without either rerunning paid work or routing a valid report
    through poison quarantine.
    """
    return bridge_dispatch.finish_terminal_report(
        path,
        key,
        result_path,
        report,
        entry,
        steps,
        ports=bridge_dispatch.TerminalBookkeepingPorts(
            now_iso=_now_iso,
            write_journal=_write_journal,
            note_report_arrival=_note_report_arrival,
            memory_already_recorded=_memory_already_recorded,
            record_from_bridge_report=record_from_bridge_report,
            archive_once=_archive_once,
        ),
        terminal_state=terminal_state,
    )


def process_request(path: Path, default_repo_root: str | None = None) -> Path:
    """Process one request, EXACTLY ONCE, across crashes.

    Reprocessing the same request -- which is what a restarted watcher does
    with anything still in the outbox -- must not yield two reports, two
    linked-conversation events, two LATEST.log lines, two memory records or two
    archived copies. See the "crash safety" note above _request_key for how
    each of the five possible steps is made idempotent, and by which mechanism.

    Lease-bearing Ikarus work also survives the formerly ambiguous provider ->
    report window: a filename-derived identity is journalled before dispatch,
    and a retry presents that exact identity to the canonical Effect-Lease
    ledger.  A durable start therefore returns ``execute=False`` instead of
    invoking the provider again. ``MAX_ATTEMPTS`` remains the bound for work
    that never reached a durable effect start.

    Every caller -- the managed watcher, CLI ``once`` and direct recovery --
    takes the same blocking per-request OS lock.  The global watcher lock alone
    cannot protect against ``once`` or a second direct consumer; without this
    claim, both could publish journal/report state for the same key while the
    Effect ledger correctly allowed only one provider invocation.
    """
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "file_bridge.process",
        REGISTRY_BY_ID["file_bridge.process"].effects,
        (_crash_journal_decision(f"process request={path.name}"),),
    )
    return bridge_dispatch.claim_and_dispatch_request(
        path,
        default_repo_root,
        inbox=INBOX,
        key_for=_request_key,
        lock_path_for=_request_lock_path,
        lock=lambda lock_path, label: _BridgeWatcherLock(
            lock_path,
            blocking=True,
            label=label,
        ),
        completed_report=_completed_report,
        process_claimed=_process_request_claimed,
    )


def _process_request_claimed(
    path: Path,
    default_repo_root: str | None = None,
    *,
    key: str,
) -> Path:
    """Implementation of :func:`process_request` under its OS claim."""
    from .core import process_bridge_payload

    return bridge_dispatch.process_claimed_request(
        path,
        default_repo_root,
        key=key,
        ports=bridge_dispatch.ClaimedDispatchPorts(
            inbox=INBOX,
            archive=ARCHIVE,
            max_attempts=MAX_ATTEMPTS,
            trace_key=envelope.TRACE_KEY,
            read_journal=_read_journal,
            raw_request_sha256=_raw_request_sha256,
            quarantine_identity_conflict=_quarantine_request_identity_conflict,
            quarantine_move=_quarantine_move,
            quarantine_dir=_quarantine_dir,
            write_journal=_write_journal,
            quarantine_move_pending=QuarantineMovePending,
            conversation_projection_failed=ConversationProjectionFailed,
            quarantine_request=quarantine_request,
            read_request=_read_request,
            request_sha256=_request_sha256,
            completed_report=_completed_report,
            report_request_binding=_report_request_binding,
            terminal_report_preserved=TerminalReportPreserved,
            terminal_bookkeeping_pending=TerminalBookkeepingPending,
            finish_terminal_report=_finish_terminal_report,
            effect_identity_for=_effect_identity_for,
            write_json_atomic=_write_json_atomic,
            accepts_keyword=_accepts_keyword,
            mission_projection_dir=_mission_projection_dir,
            process_bridge_payload=process_bridge_payload,
            adopt_trace=envelope.adopt_trace,
            stamp_report=envelope.stamp,
            project_report=_project_report_to_conversation,
            conversation_projection_pending=ConversationProjectionPending,
        ),
    )

def _looks_unfinished(path: Path, exc: BaseException) -> bool:
    """True when the failure is "this is not JSON yet" rather than "this is
    not a request".

    Our own enqueue() publishes atomically, so a half-written file can only
    come from a hand-drop or a foreign producer -- but treating one as poison
    DESTROYS a request whose only fault was being slow to write, which is a
    worse outcome than one extra poll of latency. A structural complaint
    (missing objective, missing repo_root) is not a partial write and is not
    excused here."""
    return bridge_watcher.looks_unfinished(
        path,
        exc,
        settle_grace_s=SETTLE_GRACE_S,
        now_epoch=time.time,
    )


def handle_poison_request(path: Path, exc: BaseException) -> Path | None:
    """Deal with a request the watcher could not process, without dying.

    Three outcomes, in order of preference:
      * still settling -- leave it alone and look again next poll;
      * poison -- quarantine it (report + sidecar + move out of the outbox),
        so it is visible instead of silently retried forever;
      * the quarantine itself failed -- say so and carry on. The recovery path
        is the last thing that may take the watcher down with it, so it
        catches everything, not just OSError.

    Returns the report path, or None when nothing was written."""
    return bridge_watcher.handle_poison_request(
        path,
        exc,
        ports=bridge_watcher.PoisonHandlingPorts(
            settle_grace_s=SETTLE_GRACE_S,
            inbox=INBOX,
            looks_unfinished=_looks_unfinished,
            quarantine_request=quarantine_request,
            quarantine_dir=_quarantine_dir,
            request_key=_request_key,
            conversation_projection_pending=ConversationProjectionPending,
            conversation_projection_failed=ConversationProjectionFailed,
            quarantine_move_pending=QuarantineMovePending,
            terminal_report_preserved=TerminalReportPreserved,
            emit=print,
        ),
    )


# -- watcher heartbeat ------------------------------------------------------

_last_idle_beat = 0.0
_process_identity_pid = os.getpid()
_process_identity_nonce = uuid.uuid4().hex


WatcherOwnershipBusy = bridge_watcher.WatcherOwnershipBusy
_BridgeWatcherLock = bridge_watcher._BridgeWatcherLock


def current_process_identity() -> str:
    """Return a process-lifetime identity that survives neither restart nor fork.

    A PID by itself is reusable.  The per-process nonce makes a heartbeat from
    an earlier process distinguishable even when the operating system assigns
    its PID to the replacement backend.  Refresh after ``fork()`` because the
    child inherits module globals while acquiring a different PID.
    """

    global _process_identity_pid, _process_identity_nonce
    identity, _process_identity_pid, _process_identity_nonce = (
        bridge_watcher.current_process_identity(
            pid=os.getpid(),
            recorded_pid=_process_identity_pid,
            nonce=_process_identity_nonce,
            new_nonce=lambda: uuid.uuid4().hex,
        )
    )
    return identity


def _watcher_lock_path() -> Path:
    # Derive this from HEARTBEAT_PATH at call time so tests and deployments
    # which relocate the canonical bridge state relocate its lock as well.
    return bridge_watcher.watcher_lock_path(HEARTBEAT_PATH)


def write_heartbeat(project: str | None = None, repo_root: str | None = None,
                    interval_s: float | None = None,
                    current: dict[str, Any] | None = None,
                    force: bool = False,
                    owner_token: str | None = None,
                    process_identity: str | None = None) -> None:
    """Best-effort liveness marker written by the watch loop.

    Idle beats are throttled to one per IDLE_BEAT_EVERY_S; task start/finish
    beats (``force=True``) always land. Written via temp-file + os.replace so
    a concurrent doctor read never sees a half-written file. Never raises."""
    global _last_idle_beat
    _last_idle_beat = bridge_watcher.write_heartbeat(
        heartbeat_path=HEARTBEAT_PATH,
        project=project,
        repo_root=repo_root,
        interval_s=interval_s,
        current=current,
        force=force,
        owner_token=owner_token,
        process_identity=process_identity,
        last_idle_beat=_last_idle_beat,
        idle_beat_every_s=IDLE_BEAT_EVERY_S,
        now_epoch=time.time,
        now_iso=_now_iso,
        pid=os.getpid(),
        write_text=write_text_atomic,
    )


def restart_hint(hb: dict[str, Any] | None = None) -> str:
    """The exact one-liner to (re)start the watcher, from heartbeat context."""
    return bridge_watcher.restart_hint(hb)


def heartbeat_status(now: float | None = None) -> dict[str, Any]:
    """Classify the watcher heartbeat. States:

    * ``none``   -- no heartbeat file: watcher not running, or it predates the
                    heartbeat feature (cross-check: `daedalus watcher status`).
    * ``alive``  -- idle beat fresher than STALE_AFTER_S.
    * ``busy``   -- a task is in flight, within BUSY_BUDGET_S.
    * ``wedged`` -- a task has been in flight longer than BUSY_BUDGET_S.
    * ``stale``  -- idle beat older than STALE_AFTER_S: watcher is dead.
    """
    return bridge_watcher.heartbeat_status(
        heartbeat_path=HEARTBEAT_PATH,
        now=time.time() if now is None else now,
        stale_after_s=STALE_AFTER_S,
        busy_budget_s=BUSY_BUDGET_S,
        restart=restart_hint,
    )


# -- report read-state + status ---------------------------------------------

def unread_reports() -> list[Path]:
    """Reports in the inbox with no .seen marker, oldest first."""
    return bridge_projection.unread_reports(inbox=INBOX, seen_dir=_seen_dir)


def mark_read(names: list[str] | None = None, all_reports: bool = False) -> list[str]:
    """Acknowledge reports by dropping a marker per report into inbox/.seen/.
    Returns the report names actually marked."""
    return bridge_projection.mark_read(
        names,
        all_reports,
        inbox=INBOX,
        seen_dir=_seen_dir,
        unread=unread_reports,
    )


def quarantined_requests() -> list[dict[str, Any]]:
    """Requests the watcher gave up on, with why. Surfaced by `status` so a
    quarantine is a thing an operator SEES, not a directory nobody opens."""
    return bridge_projection.quarantined_requests(
        quarantine_dir=_quarantine_dir
    )


def _report_brief(path: Path) -> dict[str, Any]:
    return bridge_projection.report_brief(path)


def _project_report_briefs(project: str | None = None) -> list[dict[str, Any]]:
    """Return finished reports in arrival order for exactly one project.

    A report with no project remains visible to the unfiltered operator status,
    but it is not silently assigned to every project-specific SSE subscriber.
    The mtime/name tuple makes the newest projection deterministic when two
    reports land within the filesystem timestamp resolution.
    """
    return bridge_projection.project_report_briefs(
        project,
        inbox=INBOX,
        brief=_report_brief,
    )


def bridge_status(project: str | None = None) -> dict[str, Any]:
    """One-call answer to: is anything queued, is anything running, and are
    there finished reports I have not read yet?"""
    return bridge_projection.bridge_status(
        project,
        outbox=OUTBOX,
        unread=unread_reports,
        brief=_report_brief,
        heartbeat=heartbeat_status,
        quarantined=quarantined_requests,
        reports=_project_report_briefs,
        latest_log=_latest_log,
    )


def stream_state(project: str | None = None) -> dict[str, Any]:
    """Compact, CHEAP snapshot for the SSE live stream. Reads ONLY the file bus
    (outbox/inbox/heartbeat) — no git, PowerShell or Ollama — so it can be polled
    once a second to drive the cockpit's live badges without the heavy dashboard.
    """
    return bridge_projection.stream_state(
        project,
        status=bridge_status,
        reports=_project_report_briefs,
    )


def _print_status(status: dict[str, Any]) -> None:
    bridge_cli.print_status(status, stale_after_s=STALE_AFTER_S)


def watch(default_repo_root: str | None, interval_s: float,
          project: str | None = None, *, owner_token: str | None = None,
          process_identity: str | None = None,
          stop_event: Any | None = None) -> None:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "file_bridge.watch",
        REGISTRY_BY_ID["file_bridge.watch"].effects,
        (
            _crash_journal_decision("watch loop start"),
            process_guard_boundary_decision(),
        ),
    )
    token = owner_token or uuid.uuid4().hex
    identity = process_identity or current_process_identity()
    bridge_watcher.watch_loop(
        outbox=OUTBOX,
        inbox=INBOX,
        watcher_lock_path=_watcher_lock_path(),
        default_repo_root=default_repo_root,
        interval_s=interval_s,
        project=project,
        owner_token=token,
        process_identity=identity,
        stop_event=stop_event,
        heartbeat=write_heartbeat,
        watcher_lock=lambda path: _BridgeWatcherLock(path),
        process_request=process_request,
        handle_poison=handle_poison_request,
        pending_exceptions=(
            (TerminalBookkeepingPending, "BOOKKEEPING PENDING"),
            (ConversationProjectionPending, "PROJECTION PENDING"),
            (ConversationProjectionFailed, "PROJECTION ERROR"),
            (QuarantineMovePending, "QUARANTINE MOVE PENDING"),
            (RequestIdentityConflict, "REQUEST IDENTITY CONFLICT"),
            (WatcherOwnershipBusy, "REQUEST CLAIM PENDING"),
        ),
        now_epoch=time.time,
        now_iso=_now_iso,
        sleep=time.sleep,
    )


def main() -> None:
    parser = bridge_cli.build_parser()
    args = parser.parse_args()
    if args.command in ("watch", "enqueue", "once", "mark-read"):
        # Queue status stays fail-open read-only inspection; every mutating
        # subcommand starts at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.file_bridge",
            REGISTRY_BY_ID["cli.file_bridge"].effects,
            (process_guard_boundary_decision(),),
        )
    bridge_cli.dispatch(
        args,
        parser=parser,
        ports=bridge_cli.BridgeCliPorts(
            outbox=OUTBOX,
            resolve_repo_root=resolve_repo_root,
            watch=watch,
            enqueue=enqueue,
            process_request=process_request,
            handle_poison_request=handle_poison_request,
            bridge_status=bridge_status,
            print_status=_print_status,
            mark_read=mark_read,
            watcher_ownership_busy=WatcherOwnershipBusy,
            watcher_not_running=WatcherNotRunning,
            pending_exceptions=(
                (TerminalBookkeepingPending, "BOOKKEEPING PENDING"),
                (ConversationProjectionPending, "PROJECTION PENDING"),
                (ConversationProjectionFailed, "PROJECTION ERROR"),
                (QuarantineMovePending, "QUARANTINE MOVE PENDING"),
                (RequestIdentityConflict, "REQUEST IDENTITY CONFLICT"),
                (WatcherOwnershipBusy, "REQUEST CLAIM PENDING"),
            ),
        ),
    )


if __name__ == "__main__":
    main()
