from __future__ import annotations

import argparse
import errno
import inspect
import json
import os
import re
import sqlite3
import uuid
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic import write_text_atomic
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

# Public reconciliation accepts only the same filename-stem alphabet the web
# task API accepts. Full-match, no separators, no drive prefix, no traversal.
_REQUEST_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}\Z")


class WatcherNotRunning(RuntimeError):
    """Raised by enqueue() when no watcher is alive to consume the request.

    MEASURED 2026-07-29, and the reason this exception exists: the watcher's
    last heartbeat was 2026-07-16T22:51:51Z (pid 9536, dead). The owner's own
    question -- "how is daedalus currently build and how does it function?" --
    was enqueued 2026-07-20T12:11:42Z, three and a half days AFTER the only
    consumer had stopped, and sat in the outbox for nine days. Nothing in the
    system objected: `enqueue` wrote the file, returned a path, and the caller
    had every reason to believe work had been queued.

    `daedalus doctor` did report the dead watcher -- correctly, and with the
    restart command -- but doctor is a thing you run when you already suspect
    something. The producer never ran it. A queue that accepts work no consumer
    will ever take is not a queue; it is a wastebasket with a receipt printer.

    So the check moved to the moment of the mistake. It carries the state, the
    age, and the exact restart command, because an error that does not say what
    to do next just relocates the confusion.
    """

    def __init__(self, hb: dict[str, Any], objective: str) -> None:
        self.hb = hb
        self.state = hb.get("state", "unknown")
        self.restart = hb.get("restart", "python -m daedalus.file_bridge watch --project <project>")
        if self.state == "stale":
            age = hb.get("age_s")
            why = (f"the bridge watcher is DEAD -- its last heartbeat was {age}s ago "
                   f"(> {STALE_AFTER_S:.0f}s)")
        else:  # "none"
            why = ("no bridge watcher has ever recorded a heartbeat here -- "
                   "none is running")
        super().__init__(
            f"REFUSED to enqueue: {why}.\n"
            f"  objective : {objective[:120]}\n"
            f"  Nothing would consume this task. It would sit in the outbox\n"
            f"  indefinitely while looking successfully queued.\n"
            f"  -> start the consumer:  {self.restart}\n"
            f"  -> or run the queue once, in the foreground:  "
            f"python -m daedalus.file_bridge once --project <project>\n"
            f"  -> or, if you are deliberately queueing ahead of a watcher you\n"
            f"     will start later:  enqueue(..., require_watcher=False)  /  --force"
        )


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
            f"{type(cause).__name__}: {cause}")


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
            f"{type(cause).__name__}: {cause}")


class TerminalBookkeepingPending(RuntimeError):
    """A durable terminal report still has unfinished local bookkeeping.

    The report is authoritative and must never be replaced by a quarantine
    report merely because its arrival log, memory projection or archive move
    failed.  The crash journal names the unfinished step; replay resumes below
    both provider dispatch and conversation projection.
    """

    def __init__(self, key: str, step: str, cause: BaseException) -> None:
        self.key = str(key)
        self.step = str(step)
        self.cause = cause
        super().__init__(
            f"terminal report bookkeeping pending for {self.key} "
            f"at {self.step}: {type(cause).__name__}: {cause}")


class RequestIdentityConflict(RuntimeError):
    """A filename key was reused for different canonical request bytes.

    The old journal/report remain authoritative and untouched.  Only the new,
    contradictory outbox file is moved to a digest-suffixed quarantine path.
    Watch/CLI recovery must surface this exception directly; routing it through
    :func:`quarantine_request` would overwrite the old report under the shared
    filename key.
    """

    def __init__(self, key: str, expected: str, observed: str,
                 quarantine_path: Path, *, moved: bool,
                 quarantine_error: BaseException | None = None) -> None:
        self.key = str(key)
        self.expected = str(expected)
        self.observed = str(observed)
        self.quarantine_path = Path(quarantine_path)
        self.moved = bool(moved)
        self.quarantine_error = quarantine_error
        state = "quarantined" if moved else "quarantine move pending"
        if quarantine_error is not None:
            state += (
                f": {type(quarantine_error).__name__}: {quarantine_error}"
            )
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
            f"{self.reason}")


class QuarantineMovePending(RuntimeError):
    """A quarantine report is durable but its source file is still queued.

    A Windows sharing violation can prevent the final move after every other
    quarantine fact has landed.  This state is neither successful completion
    nor poison input: callers must report it as pending and retry only the
    move, never rewrite the report or redispatch provider work.
    """

    def __init__(self, key: str, path: Path, destination: Path) -> None:
        self.key = str(key)
        self.path = Path(path)
        self.destination = Path(destination)
        super().__init__(
            f"quarantine move pending for {self.key!r}: "
            f"{self.path} -> {self.destination}")


_TRANSIENT_OS_ERRNOS = {
    errno.EAGAIN,
    errno.EBUSY,
    errno.EINTR,
    errno.ETIMEDOUT,
    *({errno.ESTALE} if hasattr(errno, "ESTALE") else set()),
}


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
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite3.OperationalError):
            message = str(current).lower()
            if "locked" in message or "busy" in message:
                return True
        elif type(current) is OSError and current.errno is None:
            message = str(current).lower()
            if any(marker in message for marker in (
                    "temporarily unavailable", "temporary unavailable",
                    "timed out", "locked", "busy")):
                return True
        elif isinstance(current, (BlockingIOError, InterruptedError, TimeoutError)):
            return True
        elif isinstance(current, OSError):
            if current.errno in _TRANSIENT_OS_ERRNOS:
                return True
            # Windows sharing and lock violations are transient even though
            # Python commonly presents them as PermissionError/EACCES.
            if getattr(current, "winerror", None) in {32, 33}:
                return True
        current = current.__cause__ or current.__context__
    return False


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seen_dir() -> Path:
    """Read-state ledger: one marker file per acknowledged report.

    Derived from INBOX at call time so tests that patch INBOX get a matching
    ledger for free."""
    return INBOX / ".seen"


def _latest_log() -> Path:
    """Single well-known append-only file -- one line per finished report --
    so an orchestrator can file-watch exactly one path instead of polling."""
    return INBOX / "LATEST.log"


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
    directory = _quarantine_dir()
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
        "preserved_report": str(INBOX / f"{key}.report.json"),
        "quarantine_path": str(destination),
        "quarantined_at": _now_iso(),
    }
    moved = False
    quarantine_error: BaseException | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Publish the diagnostic before evicting the only copy of the
        # contradictory request.  If this fails, leave the request queued for
        # a retry and keep the failure inside RequestIdentityConflict so the
        # watcher can never route it through generic report-overwriting poison
        # handling.
        _write_json_atomic(sidecar, detail)
        moved = not path.exists()
        if not moved:
            try:
                os.replace(path, destination)
                moved = True
            except OSError as replace_exc:
                try:
                    shutil.move(str(path), str(destination))
                    moved = True
                except (OSError, shutil.Error) as move_exc:
                    quarantine_error = RuntimeError(
                        f"atomic move failed ({replace_exc}); fallback move "
                        f"failed ({move_exc})"
                    )
    except (OSError, shutil.Error) as exc:
        quarantine_error = exc
    return RequestIdentityConflict(
        key, expected, observed, destination, moved=moved,
        quarantine_error=quarantine_error,
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
    write_text_atomic(path, json.dumps(payload, indent=2))


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
    try:
        report = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _memory_already_recorded(key: str) -> bool:
    """Did the memory append for this key already land?

    Costs a full read of the memory log, which is why it is consulted only when
    the journal says the append was in flight when the process died -- the one
    state where the flag alone cannot tell us. Never raises."""
    try:
        from .memory import EVENTS_PATH

        if not EVENTS_PATH.exists():
            return False
        needle = json.dumps(key)  # the quoted key, as it appears in the record
        for line in EVENTS_PATH.read_text(
                encoding="utf-8", errors="replace").splitlines():
            if needle not in line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if (record.get("payload") or {}).get("request_file") == key:
                return True
    except (OSError, ImportError):
        pass
    return False


def _archive_once(path: Path, key: str) -> bool:
    """Move a request into the archive at its fixed, key-derived destination.

    A FIXED destination is what makes "never two archived copies" true by
    construction: os.replace overwrites atomically, so an interrupted
    cross-device move (copy landed, source not yet unlinked) resolves to
    exactly one archived file instead of two. Returns False if the request
    could not be moved (locked file) so the caller can retry next poll."""
    if not path.exists():
        return True
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE / f"{key}{path.suffix}"
    try:
        os.replace(path, dest)
    except OSError:
        try:
            shutil.move(str(path), str(dest))  # cross-device: copy + unlink
        except (OSError, shutil.Error):
            return False
    return True


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
    warning = codex_inline_brief_warning(objective, lane)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)

    # CONSUMER CHECK BEFORE THE WRITE, never after: a refusal must leave no
    # file behind, or we would have invented a third state ("queued, but we
    # told you not to count on it") that no reader of the outbox can see.
    hb = heartbeat_status()
    if hb["state"] in ("stale", "none"):
        if require_watcher:
            raise WatcherNotRunning(hb, objective)
        print(f"WARNING: queueing with NO live watcher (state={hb['state']}); "
              f"this task will sit until you run:  {hb['restart']}", file=sys.stderr)
    elif hb["state"] == "wedged":
        cur = (hb.get("current") or {}).get("file", "?")
        print(f"WARNING: the watcher is WEDGED on {cur} "
              f"({hb.get('busy_for_s')}s > {BUSY_BUDGET_S:.0f}s budget); this task is "
              f"queued behind it and may not run soon.", file=sys.stderr)

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
    from . import conversation
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
    from . import conversation

    try:
        # Do not create the canonical database merely because a legacy/unlinked
        # file-bridge task completed. If it does not exist, no dispatch link can
        # exist in it either. Keep the path probe inside the classification
        # boundary because filesystem availability itself can be transient.
        if not conversation.default_db_path().exists():
            return None
        store = conversation.default_store()
        if store.dispatch_status(key) is None:
            return None
        outcome_state, summary, detail = _conversation_report_fields(key, report)
        return store.record_dispatch_event(
            key, outcome_state=outcome_state, summary=summary, detail=detail,
            source_event_id=f"file_bridge.report:{key}")
    except Exception as exc:
        # Automatic retry is deliberately narrow. A source-id conflict is an
        # integrity fact, not temporary unavailability; retrying it forever
        # would spin the watcher and could keep shuffling an archived request.
        # The same is true for UnknownDispatch, malformed payloads and schema
        # failures other than an actual SQLite BUSY/LOCKED condition.
        if _is_transient_projection_failure(exc):
            raise ConversationProjectionPending(key, exc) from exc
        raise


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
    key = str(task_id or "").strip()
    if not _REQUEST_KEY_RE.fullmatch(key):
        raise ValueError("task_id must be a plain file-bridge request key")
    report_path = INBOX / f"{key}.report.json"
    try:
        report_path.resolve().relative_to(INBOX.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("task_id resolves outside the file-bridge inbox") from exc
    report = _completed_report(report_path)
    if report is None:
        return None
    recorded_key = str(report.get("request_file") or "").strip()
    if recorded_key and recorded_key != key:
        raise ValueError(
            f"terminal report identity mismatch: path key={key!r}, "
            f"report request_file={recorded_key!r}")
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "file_bridge.process",
        REGISTRY_BY_ID["file_bridge.process"].effects,
        (_crash_journal_decision(f"reconcile terminal report={key}"),),
    )
    try:
        return _project_report_to_conversation(key, report)
    except ConversationProjectionPending as exc:
        # In the enqueue->link race the ordinary watcher may already have
        # archived the request. Put that SAME request back on the canonical
        # outbox so its next pass retries only the idempotent projection: the
        # journal's durable report step prevents another provider invocation.
        exc.retry_queued = _requeue_for_projection(key)
        raise


def _requeue_for_projection(key: str) -> bool:
    """Return an archived request to OUTBOX for projection-only retry.

    ``key`` has already passed :data:`_REQUEST_KEY_RE`. The fixed archive and
    outbox names make this idempotent under concurrent reconciliation: either
    the request is already queued, or exactly one move makes it queued. This is
    the existing file bus and existing per-request journal, not another retry
    ledger.
    """
    entry = _read_journal(key)
    steps = entry.get("steps") if isinstance(entry.get("steps"), dict) else {}
    if steps.get("report") is not True:
        # Requeue is safe only when the existing crash journal proves that
        # process_request will reuse the durable report. Otherwise a damaged
        # journal could turn a projection retry into another provider bill.
        return False
    source = ARCHIVE / f"{key}.json"
    target = OUTBOX / f"{key}.json"
    if target.exists():
        return True
    if not source.is_file():
        return False
    OUTBOX.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:
        try:
            shutil.move(str(source), str(target))
        except (OSError, shutil.Error):
            return target.is_file()
    return target.is_file()


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
    lane = report.get("lane") or (report.get("request") or {}).get("lane") or "?"
    marker = f" key={key}" if key else ""
    # Appended LAST and only when present, so the line an existing reader
    # already parses is unchanged up to the point it stops caring. This is the
    # cheapest surface the join gets: one tail-able file where a trace id shows
    # up next to the report that carries it.
    tid = envelope.trace_of(report)
    marker += f" trace={tid}" if tid else ""
    line = (f"{_now_iso()} {result_path.name} "
            f"status={report.get('bridge_status', '?')} lane={lane}{marker}\n")
    try:
        log = _latest_log()
        if key and log.exists():
            for existing in log.read_text(
                    encoding="utf-8", errors="replace").splitlines():
                if existing.endswith(marker):
                    return  # already announced -- one arrival line per request
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # signal channel only -- never fail the report write over it


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
    key = _request_key(path)
    dest = _quarantine_dir() / path.name
    # THE TRACE COMES FROM THE JOURNAL, not from the request. A quarantine is
    # exactly the case where the request may be unreadable (poison) or already
    # moved, so the only surviving record of which run asked for this work is
    # the journal entry process_request wrote BEFORE dispatching. A give-up is
    # the report a human most wants to trace back, so it is worth the extra
    # read.
    entry = _read_journal(key)
    result_path = INBOX / f"{key}.report.json"
    raw_sha256 = _raw_request_sha256(path)
    identity = envelope.canonical_sha({
        "request_file": key,
        "request_raw_sha256": raw_sha256,
        "reason": str(reason),
        "detail": str(detail),
    })
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
    existing = _completed_report(result_path)
    if existing is not None:
        if not pending_matches or envelope.canonical_sha(existing) != (
                envelope.canonical_sha(pending_report)):
            # Central report-authority fence. Any generic error on a replay
            # can reach poison handling. A whole terminal artifact remains
            # evidence even if its recovery journal is unreadable; only an
            # exact journal-bound continuation may resume around it.
            raise TerminalReportPreserved(
                key, result_path, f"{reason}: {detail}")
        report = existing
    else:
        if pending_matches:
            report = pending_report
        else:
            report = envelope.stamp({
                "request_file": key,
                "bridge_status": "quarantined",
                "error": f"{reason}: {detail}",
                "reason": reason,
                "quarantined_at": _now_iso(),
                "quarantine_path": str(dest),
            }, trace_id=entry.get(envelope.TRACE_KEY))
            entry["quarantine_record"] = {
                "identity": identity,
                "request_raw_sha256": raw_sha256,
                "reason": str(reason),
                "detail": str(detail),
                "report": report,
            }
            entry["state"] = "quarantine_pending"
            entry["key"] = key
            _write_journal(key, entry)
        _write_json_atomic(result_path, report)
    projection_failure: BaseException | None = None
    try:
        _project_report_to_conversation(key, report)
    except ConversationProjectionPending:
        raise
    except Exception as exc:
        # Quarantine is itself a terminal report. A permanent disagreement in
        # its chat projection must not prevent the poison request from being
        # evicted, or the watcher would retry the same contradiction forever.
        projection_failure = exc
        entry["conversation_projection_error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        }
    _note_report_arrival(result_path, report, key=key)
    _write_json_atomic(_quarantine_dir() / f"{key}.error.json", report)
    entry["state"] = "quarantine_move_pending"
    entry["key"] = key
    entry["reason"] = reason
    _write_journal(key, entry)
    if not _quarantine_move(path, key):
        raise QuarantineMovePending(key, path, dest)
    entry["state"] = "quarantined"
    _write_journal(key, entry)
    if projection_failure is not None:
        raise ConversationProjectionFailed(
            key, projection_failure) from projection_failure
    return result_path


def _quarantine_move(path: Path, key: str) -> bool:
    if not path.exists():
        return True
    _quarantine_dir().mkdir(parents=True, exist_ok=True)
    dest = _quarantine_dir() / f"{key}{path.suffix}"
    try:
        os.replace(path, dest)
    except OSError:
        try:
            shutil.move(str(path), str(dest))
        except (OSError, shutil.Error):
            return False
    return True


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
    def pending(step: str, cause: Exception) -> TerminalBookkeepingPending:
        diagnostic = {
            "step": step,
            "type": type(cause).__name__,
            "message": str(cause)[:1000],
            "at": _now_iso(),
        }
        failures = entry.get("terminal_bookkeeping_failures")
        history = list(failures) if isinstance(failures, list) else []
        history.append(diagnostic)
        # Retain bounded negative evidence without making an unhealthy watcher
        # grow its recovery journal forever.
        entry["terminal_bookkeeping_failures"] = history[-20:]
        entry["terminal_bookkeeping_error"] = diagnostic
        entry["state"] = (
            "projection_failed"
            if terminal_state == "done_with_projection_error"
            else "bookkeeping_pending"
        )
        try:
            _write_journal(key, entry)
        except Exception as journal_exc:
            # The report is already durable, so even an unavailable journal is
            # not authority to overwrite it.  Keep the original failure as the
            # retry reason and expose the secondary diagnostic on the raised
            # exception object below.
            diagnostic["journal_error"] = {
                "type": type(journal_exc).__name__,
                "message": str(journal_exc)[:1000],
            }
        return TerminalBookkeepingPending(key, step, cause)

    # -- arrival line (deduped by key, inside _note_report_arrival) ----------
    try:
        if not steps.get("log"):
            _note_report_arrival(result_path, report, key=key)
            steps["log"] = True
            _write_journal(key, entry)
    except Exception as exc:
        raise pending("log", exc) from exc

    # -- memory record ------------------------------------------------------
    try:
        memory_step = steps.get("memory")
        if memory_step is not True:
            # "pending" means we died with the append in flight -- the only
            # state the flag cannot resolve, and the only time we pay for a
            # log scan.
            if memory_step != "pending" or not _memory_already_recorded(key):
                steps["memory"] = "pending"
                _write_journal(key, entry)
                record_from_bridge_report(report)
            steps["memory"] = True
            _write_journal(key, entry)
    except Exception as exc:
        raise pending("memory", exc) from exc

    # -- archive ------------------------------------------------------------
    try:
        if not _archive_once(path, key):
            raise OSError(f"could not archive request {path}")
        steps["archive"] = True
        entry["state"] = terminal_state
        entry.pop("terminal_bookkeeping_error", None)
        _write_journal(key, entry)
    except Exception as exc:
        raise pending("archive", exc) from exc


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
    key = _request_key(path)
    with _BridgeWatcherLock(
        _request_lock_path(key),
        blocking=True,
        label=f"file-bridge request {key!r}",
    ):
        if not path.exists():
            # The winner may have archived the request while this consumer was
            # blocked.  Returning its whole terminal artifact is safe; a
            # missing source with no report remains an error rather than an
            # invented success.
            result_path = INBOX / f"{key}.report.json"
            if _completed_report(result_path) is not None:
                return result_path
            raise FileNotFoundError(path)
        return _process_request_claimed(
            path, default_repo_root, key=key
        )


def _process_request_claimed(
    path: Path,
    default_repo_root: str | None = None,
    *,
    key: str,
) -> Path:
    """Implementation of :func:`process_request` under its OS claim."""
    INBOX.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    result_path = INBOX / f"{key}.report.json"
    entry = _read_journal(key)

    steps = entry.get("steps") if isinstance(entry.get("steps"), dict) else {}
    attempts = int(entry.get("attempts") or 0)
    entry.update({"key": key, "steps": steps, "attempts": attempts,
                  "state": entry.get("state") or "new"})

    # Poison requests cannot be normalized below, so their quarantine replay
    # is bound to exact raw bytes instead. Resume before JSON parsing only
    # when those bytes match the journaled request; a different body under the
    # same stem is an identity conflict and never inherits the old report.
    quarantine_record = entry.get("quarantine_record")
    quarantine_record = (
        quarantine_record if isinstance(quarantine_record, dict) else {})
    if entry.get("state") in {
            "quarantine_pending", "quarantine_move_pending", "quarantined"} \
            and quarantine_record:
        observed_raw_sha256 = _raw_request_sha256(path)
        expected_raw_sha256 = quarantine_record.get("request_raw_sha256")
        if expected_raw_sha256 != observed_raw_sha256:
            raise _quarantine_request_identity_conflict(
                path, key, expected=str(expected_raw_sha256),
                observed=observed_raw_sha256)
        if entry.get("state") in {"quarantine_move_pending", "quarantined"}:
            if not _quarantine_move(path, key):
                raise QuarantineMovePending(
                    key, path, _quarantine_dir() / path.name)
            if entry.get("state") != "quarantined":
                entry["state"] = "quarantined"
                _write_journal(key, entry)
            projection_error = entry.get("conversation_projection_error")
            if isinstance(projection_error, dict):
                cause = RuntimeError(
                    f"{projection_error.get('type', 'projection error')}: "
                    f"{projection_error.get('message', '')}")
                raise ConversationProjectionFailed(key, cause) from cause
            return result_path
        return quarantine_request(
            path,
            str(quarantine_record.get("reason") or "quarantined"),
            str(quarantine_record.get("detail") or ""),
        )

    # Bind the human-readable filename key to the canonical, normalized body.
    # The key is caller-controlled for supported hand-drops, so the stem alone
    # is not request identity.  Persisting this digest before dispatch makes an
    # exact restored copy replayable while a different body using an old stem
    # is quarantined without touching that stem's report/journal/artifacts.
    payload = _read_request(path, default_repo_root)  # poison raises here
    observed_request_sha256 = _request_sha256(payload)
    expected_request_sha256 = entry.get("request_sha256")
    identity_report = _completed_report(result_path)
    report_request_sha256: str | None = None
    if identity_report is not None:
        try:
            report_request_sha256 = _report_request_binding(
                identity_report, key)
        except ValueError as exc:
            # A whole report is retained evidence even when its own binding is
            # corrupt or from a legacy writer.  Never overwrite it by running
            # work under the same filename key; a human must reconcile it.
            raise TerminalReportPreserved(key, result_path, str(exc)) from exc
    if expected_request_sha256 is None and report_request_sha256 is not None:
        expected_request_sha256 = report_request_sha256
    if expected_request_sha256 is not None and (
        not isinstance(expected_request_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_request_sha256)
        or expected_request_sha256 != observed_request_sha256
    ):
        raise _quarantine_request_identity_conflict(
            path,
            key,
            expected=str(expected_request_sha256),
            observed=observed_request_sha256,
        )
    if entry.get("request_sha256") is None:
        entry["request_sha256"] = observed_request_sha256
        _write_journal(key, entry)  # durable before any provider dispatch
    elif report_request_sha256 is not None and (
            report_request_sha256 != observed_request_sha256):
        raise _quarantine_request_identity_conflict(
            path,
            key,
            expected=report_request_sha256,
            observed=observed_request_sha256,
        )

    if entry.get("state") == "quarantined":
        # A valid request that previously exhausted its retries is still bound
        # to its body.  Check that binding above before evicting a restored copy;
        # otherwise a different body under the same quarantined key could
        # overwrite the first request's retained quarantine artifact.
        if not _quarantine_move(path, key):
            raise QuarantineMovePending(
                key, path, _quarantine_dir() / path.name)
        return result_path

    if entry.get("state") == "bookkeeping_pending":
        # Projection already returned successfully before downstream
        # bookkeeping entered this state.  Resume only the unfinished local
        # step; replaying the provider or even the idempotent projector would
        # give a bookkeeping failure more authority than it owns.
        report = _completed_report(result_path)
        if report is None:
            cause = ValueError(
                "bookkeeping-pending journal state has no terminal report")
            raise TerminalBookkeepingPending(key, "report", cause)
        _finish_terminal_report(path, key, result_path, report, entry, steps)
        return result_path

    if entry.get("state") in {"projection_failed",
                               "done_with_projection_error"}:
        # The report is already terminal and the projection was classified as
        # permanent on an earlier pass. Resume only the downstream bookkeeping
        # and archive move; never call the provider or the projector again.
        report = _completed_report(result_path)
        if report is None:
            cause = ValueError(
                "projection-failed journal state has no complete terminal report")
            raise ConversationProjectionFailed(key, cause)
        try:
            _finish_terminal_report(
                path, key, result_path, report, entry, steps,
                terminal_state="done_with_projection_error")
        except TerminalBookkeepingPending as finish_exc:
            # The originating defect is still a permanent projection conflict;
            # the cleanup failure is retained on the journal and retried below
            # both provider dispatch and projection.  Do not let the secondary
            # archive/log/memory problem erase that classification for callers.
            raise ConversationProjectionFailed(key, finish_exc) from finish_exc
        except Exception as exc:
            raise ConversationProjectionFailed(key, exc) from exc
        return result_path

    # -- step 1: the work, and the report that commits it -------------------
    # A complete report for this key IS the receipt that the work happened.
    # Reusing it is the whole point: re-running is what spends money twice.
    report = identity_report
    if report is not None and not steps.get("report"):
        # The process may have died after the atomic report replace but before
        # committing this journal bit.  The report's independently validated
        # request digest is sufficient proof to heal the lagging journal; the
        # provider/lease path must never be entered merely to rediscover it.
        steps["report"] = True
        entry["request_sha256"] = observed_request_sha256
        entry["state"] = "reported"
        _write_journal(key, entry)
    if report is None:
        if attempts >= MAX_ATTEMPTS:
            return quarantine_request(
                path, "interrupted",
                f"dispatched {attempts} times without ever producing a report "
                "-- refusing to run it again (see runs/processed/.journal)")
        effect_identity = _effect_identity_for(key, entry)
        entry["attempts"] = attempts + 1
        entry["state"] = "in_flight"
        entry["lane"] = payload.get("lane")
        entry["effect_identity"] = effect_identity
        # The journal is a crash-recovery record of THIS request, so it gets
        # the trace too -- a request that died in flight is exactly the one a
        # human will be tracing.
        entry[envelope.TRACE_KEY] = payload.get(envelope.TRACE_KEY)
        _write_journal(key, entry)  # durable BEFORE the work: survives a kill

        from .core import process_bridge_payload
        # THE CROSS-PROCESS HOP. The trace was minted in the ENQUEUER'S
        # process, possibly hours ago and possibly on the other side of a
        # crash; re-binding it here is what makes the watcher's own downstream
        # records (spine intents, memory events, anything Ikarus writes) land
        # under the run that ASKED for the work rather than under nothing.
        # Binding around the dispatch and not wider keeps a request's trace
        # from leaking onto the next request in the same watcher process.
        # adopt_trace, NOT trace_context: an untraced request must stay
        # untraced. Minting here would give every legacy/hand-dropped request a
        # private id nothing else shares -- the field would look fully
        # populated while joining nothing.
        with envelope.adopt_trace(payload.get(envelope.TRACE_KEY)) as tid:
            dispatch_kwargs: dict[str, Any] = {
                "effect_identity": effect_identity,
            }
            if _accepts_keyword(
                process_bridge_payload, "mission_projection_dir"
            ):
                # Request JSON has no authority over this path.  It is a
                # filename-derived, deletable view beside the existing crash
                # journal and cannot select an arbitrary filesystem root.
                dispatch_kwargs["mission_projection_dir"] = (
                    _mission_projection_dir(key)
                )
            report = process_bridge_payload(payload, **dispatch_kwargs)
        # The idempotency key, carried on the artifact itself, so the memory
        # log can be asked "did this request's record already land?".
        report["request_file"] = key
        report["request_sha256"] = observed_request_sha256
        # Stamp the REPORT with the REQUEST's trace, not the ambient one: the
        # report is a statement about that request, and the join a human wants
        # is request -> report. envelope.stamp lets a report that already named
        # its own trace keep it.
        if payload.get(envelope.TRACE_KEY):
            report = envelope.stamp(report, trace_id=tid)

        _write_json_atomic(result_path, report)
        steps["report"] = True
        entry["state"] = "reported"
        _write_journal(key, entry)

    # -- step 2: linked conversation outcome --------------------------------
    # The canonical spine's source_event_id uniqueness, not this file journal,
    # closes the crash window: if the process dies immediately after the write,
    # replay returns that same fact. An unlinked task is a strict no-op.
    try:
        _project_report_to_conversation(key, report)
    except ConversationProjectionPending:
        raise
    except Exception as exc:
        # The report itself is a complete terminal fact. An integrity or
        # attribution error in its informational chat projection must not turn
        # that report into poison: preserve it, flag the diagnostic on the
        # existing recovery record, and evict the request from the watch loop.
        entry["state"] = "projection_failed"
        entry["conversation_projection_error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        }
        try:
            _write_journal(key, entry)
            _finish_terminal_report(
                path, key, result_path, report, entry, steps,
                terminal_state="done_with_projection_error")
        except TerminalBookkeepingPending as finish_exc:
            # Preserve the permanent projection-conflict classification.  The
            # journal still records the unfinished bookkeeping step, and the
            # next pass resumes below provider dispatch and projection.
            raise ConversationProjectionFailed(key, finish_exc) from exc
        except Exception as finish_exc:
            raise ConversationProjectionFailed(key, finish_exc) from exc
        raise ConversationProjectionFailed(key, exc) from exc

    # -- steps 3-5: arrival line, memory record, archive --------------------
    _finish_terminal_report(path, key, result_path, report, entry, steps)
    return result_path


def _looks_unfinished(path: Path, exc: BaseException) -> bool:
    """True when the failure is "this is not JSON yet" rather than "this is
    not a request".

    Our own enqueue() publishes atomically, so a half-written file can only
    come from a hand-drop or a foreign producer -- but treating one as poison
    DESTROYS a request whose only fault was being slow to write, which is a
    worse outcome than one extra poll of latency. A structural complaint
    (missing objective, missing repo_root) is not a partial write and is not
    excused here."""
    if not isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return False
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < SETTLE_GRACE_S


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
    if _looks_unfinished(path, exc):
        print(f"SETTLING {path.name}: not valid JSON yet and modified "
              f"<{SETTLE_GRACE_S:.0f}s ago -- retrying next poll", flush=True)
        return None
    print(f"FAILED {path.name}: {exc}", flush=True)
    try:
        result = quarantine_request(path, type(exc).__name__, str(exc))
        print(f"QUARANTINED {path.name} -> {_quarantine_dir()}", flush=True)
        return result
    except ConversationProjectionPending as inner:
        print(f"PROJECTION PENDING {path.name}: {inner}", flush=True)
        return INBOX / f"{_request_key(path)}.report.json"
    except ConversationProjectionFailed as inner:
        # quarantine_request already wrote the report, sidecar and journal and
        # evicted the poison request. Surface the projection disagreement, but
        # do not call quarantine a failure or leave the item spinning.
        print(f"QUARANTINED {path.name} -> {_quarantine_dir()}", flush=True)
        print(f"PROJECTION ERROR {path.name}: {inner}", flush=True)
        return INBOX / f"{_request_key(path)}.report.json"
    except QuarantineMovePending as inner:
        print(f"QUARANTINE MOVE PENDING {path.name}: {inner}", flush=True)
        return INBOX / f"{_request_key(path)}.report.json"
    except TerminalReportPreserved as inner:
        print(f"REPORT PRESERVED {path.name}: {inner}", flush=True)
        return inner.report_path
    except Exception as inner:  # noqa: BLE001 -- never let recovery kill the loop
        print(f"QUARANTINE FAILED {path.name}: {inner}", flush=True)
        return None


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
    hb = status["watcher"]
    state = hb["state"]
    if state == "alive":
        watcher = f"alive (heartbeat {hb['age_s']}s ago, pid {hb.get('pid')})"
    elif state == "busy":
        cur = hb.get("current") or {}
        watcher = f"busy on {cur.get('file', '?')} for {hb.get('busy_for_s')}s (pid {hb.get('pid')})"
    elif state == "wedged":
        cur = hb.get("current") or {}
        watcher = (f"POSSIBLY WEDGED on {cur.get('file', '?')} for {hb.get('busy_for_s')}s "
                   f"-- investigate, then restart: {hb['restart']}")
    elif state == "stale":
        watcher = (f"STALE (last heartbeat {hb['age_s']}s ago > {STALE_AFTER_S:.0f}s) "
                   f"-- restart: {hb['restart']}")
    else:
        watcher = f"{hb.get('detail', 'unknown')} -- start: {hb['restart']}"
    print(f"Watcher : {watcher}")
    print(f"Queue   : {status['queue_depth']} queued")
    for item in status["queued"]:
        print(f"  {item['name']}  lane={item['lane']}")
    if status["in_flight"]:
        print(f"In-flight: {status['in_flight'].get('file', '?')}")
    print(f"Reports : {status['reports_total']} total, {status['unread_count']} UNREAD")
    for item in status["unread"]:
        print(f"  UNREAD {item['name']}  status={item['status']} lane={item['lane']}")
        if item["summary"]:
            print(f"         {item['summary']}")
    if status["unread_count"]:
        print("Acknowledge: python -m daedalus.file_bridge mark-read --all "
              "(or name specific reports)")
    if status.get("quarantined_count"):
        print(f"QUARANTINED: {status['quarantined_count']} request(s) the watcher "
              "could not process -- they are NOT queued and will not run")
        for item in status["quarantined"]:
            print(f"  {item['name']}  {item['reason']}: {item['error'][:120]}")
    print(f"Arrival log: {status['latest_log']}")


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
    parser = argparse.ArgumentParser(description="File bridge between Codex and Claude.")
    sub = parser.add_subparsers(dest="command")

    watch_p = sub.add_parser("watch", help="Watch outbox and process Claude requests.")
    watch_p.add_argument("--repo-root")
    watch_p.add_argument("--project")
    watch_p.add_argument("--interval-s", type=float, default=2.0)

    enqueue_p = sub.add_parser("enqueue", help="Create a task request in outbox.")
    enqueue_p.add_argument("objective")
    enqueue_p.add_argument("--repo-root")
    enqueue_p.add_argument("--project")
    enqueue_p.add_argument("--paths", nargs="*", default=[])
    enqueue_p.add_argument("--model", default="sonnet")
    enqueue_p.add_argument("--lane", default="auto",
                           choices=["auto", "claude", "local", "local_only", "codex"],
                           help=("auto/local run accepted assignments through the leased "
                                 "executor with no direct Claude fallback; local_only exposes "
                                 "only trusted local Ollama; claude/codex are refused until "
                                 "the queue caller holds broker authority"))
    enqueue_p.add_argument("--source", default="unknown",
                           choices=["unknown", "codex", "claude", "user", "ikarus"],
                           help="who queued the request")
    enqueue_p.add_argument("--strategy", default="single", choices=["single", "spawn"],
                           help=("single routes one task; spawn is currently refused until a "
                                 "leased multi-task adapter exists"))
    enqueue_p.add_argument("--force", action="store_true",
                           help="queue even though no watcher is alive to run it "
                                "(default: REFUSE, because such a task just sits)")

    once_p = sub.add_parser("once", help="Process current outbox requests once.")
    once_p.add_argument("--repo-root")
    once_p.add_argument("--project")

    status_p = sub.add_parser(
        "status", help="Queue depth, in-flight task, watcher liveness, UNREAD reports.")
    status_p.add_argument("--project", help="filter queue/reports to one project")
    status_p.add_argument("--json", action="store_true")

    mark_p = sub.add_parser(
        "mark-read", help="Acknowledge finished reports (drops markers in inbox/.seen/).")
    mark_p.add_argument("names", nargs="*", help="report file names (with or without .report.json)")
    mark_p.add_argument("--all", action="store_true", help="mark every unread report as read")

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
    if args.command == "watch":
        try:
            watch(resolve_repo_root(args.repo_root, args.project), args.interval_s,
                  project=args.project)
        except WatcherOwnershipBusy as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            raise SystemExit(2) from None
    elif args.command == "enqueue":
        try:
            print(enqueue(args.objective, resolve_repo_root(args.repo_root, args.project),
                          args.paths, args.model, args.lane, args.project,
                          args.source, args.strategy,
                          require_watcher=not args.force))
        except WatcherNotRunning as exc:
            # A refusal is a normal, expected outcome here -- report it as a
            # message and a non-zero exit, not as an unhandled traceback that
            # buries the remedy under a stack.
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
    elif args.command == "once":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None
        for path in sorted(OUTBOX.glob("*.json")):
            # Same recovery as the watcher: one poison request must not abort
            # the requests queued behind it.
            try:
                print(process_request(path, repo_root))
            except TerminalBookkeepingPending as exc:
                print(f"BOOKKEEPING PENDING {path.name}: {exc}", file=sys.stderr)
            except ConversationProjectionPending as exc:
                print(f"PROJECTION PENDING {path.name}: {exc}", file=sys.stderr)
            except ConversationProjectionFailed as exc:
                print(f"PROJECTION ERROR {path.name}: {exc}", file=sys.stderr)
            except QuarantineMovePending as exc:
                print(f"QUARANTINE MOVE PENDING {path.name}: {exc}",
                      file=sys.stderr)
            except RequestIdentityConflict as exc:
                print(f"REQUEST IDENTITY CONFLICT {path.name}: {exc}",
                      file=sys.stderr)
            except WatcherOwnershipBusy as exc:
                print(f"REQUEST CLAIM PENDING {path.name}: {exc}",
                      file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                handle_poison_request(path, exc)
    elif args.command == "status":
        status = bridge_status(args.project)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            _print_status(status)
    elif args.command == "mark-read":
        if not args.names and not args.all:
            print("nothing to do: pass report names or --all")
        else:
            marked = mark_read(args.names, all_reports=args.all)
            print(f"marked {len(marked)} report(s) read")
            for name in marked:
                print(f"  {name}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
