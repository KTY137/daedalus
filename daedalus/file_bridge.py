from __future__ import annotations

import argparse
import json
import os
import uuid
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import record_from_bridge_report
from .projects import resolve_repo_root


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

# A request that was interrupted mid-flight is retried on restart, but not
# forever. A request that reliably HARD-kills the process (a segfault or an OOM
# inside a provider, not an exception we could catch) would otherwise be
# re-dispatched -- and on a paid lane re-billed -- on every single restart.
# After this many dispatches with nothing to show for them it is quarantined.
MAX_ATTEMPTS = 3

# A request whose JSON does not parse is only poison once it has stopped
# changing. A fresher one is probably still being written by a producer that
# does not publish atomically (a hand-drop, a foreign tool -- our own enqueue()
# does publish atomically), and destroying that would lose a perfectly good
# request whose only fault was being slow.
SETTLE_GRACE_S = 5.0


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


# -- crash safety: one request -> one report, one log line, one memory record -
#
# process_request() applies four side effects in sequence (report -> arrival
# line -> memory record -> archive move). A crash between any two of them left
# the request sitting in the outbox with some effects already applied, and the
# restarted watcher redid ALL of them: it re-ran (and on a paid lane re-billed)
# the work, appended a SECOND LATEST.log line and a SECOND memory record.
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
#   log     -- the arrival line carries `key=<stem>`; the append is skipped if
#              the log already contains that key. A content check, no window.
#   memory  -- two-phase journal flag. The one ambiguous state ("we died with
#              the append in flight") is resolved by scanning the memory log
#              for the key, which is why the report carries `request_file`.
#              That scan reads the whole memory log, so it is paid ONLY on
#              that recovery path and never on the happy path.
#   archive -- fixed destination path; os.replace overwrites, so even an
#              interrupted cross-device move resolves to one archived file.


def _request_key(path: Path) -> str:
    """The idempotency key of a request: its filename stem.

    Safe as a key only because enqueue() embeds a uuid in the name -- the
    older second-resolution stamp was not unique, so neither was this."""
    return path.stem


def _journal_dir() -> Path:
    """Per-request processing journal. Derived from ARCHIVE at call time so a
    test that patches ARCHIVE gets a matching journal for free."""
    return ARCHIVE / ".journal"


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
    matches `*.report.json.tmp`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_journal(key: str) -> dict[str, Any]:
    """The journal for one request, or an empty dict if there is none.

    A truncated/corrupt journal reads as empty, i.e. as 'nothing has happened
    yet'. That direction is the safe one: it can cost a repeated step, whereas
    trusting garbage would skip a step that never ran."""
    try:
        entry = json.loads(_journal_path(key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return entry if isinstance(entry, dict) else {}


def _journal_path(key: str) -> Path:
    return _journal_dir() / f"{key}.json"


def _write_journal(key: str, entry: dict[str, Any]) -> None:
    entry["updated"] = _now_iso()
    _write_json_atomic(_journal_path(key), entry)


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
    if lane != "codex":
        return None
    if len(objective) <= CODEX_INLINE_BRIEF_CHARS:
        return None
    if "codex_queue" in objective.lower().replace(" ", "_"):
        return None
    return (
        f"codex-lane objective is {len(objective)} chars with no CODEX_QUEUE.md "
        "reference -- inline briefs bounce on this lane (protocol lesson "
        "2026-07-11). Put the full brief in docs/CODEX_QUEUE.md in the target "
        'repo and enqueue a short pointer instead, e.g. '
        '"Execute task C9 from docs/CODEX_QUEUE.md".'
    )


def enqueue(objective: str, repo_root: str, paths: list[str], model: str = "sonnet",
            lane: str = "auto", project: str | None = None,
            source: str = "unknown", strategy: str = "single",
            category: str | None = None) -> Path:
    """Drop one task request into the outbox for the watcher to dispatch.

    CODEX-LANE PROTOCOL (learned 2026-07-11, cost ~2 h of bounced tasks):
    the codex lane executes best from a *queue-file task*, not an inline
    brief. The working pattern is: write the full brief as a task entry in
    ``docs/CODEX_QUEUE.md`` inside the target repo, then enqueue a short
    objective that names it ("Execute task C9 from docs/CODEX_QUEUE.md").
    Long inline objectives on ``--lane codex`` bounce or underperform;
    :func:`codex_inline_brief_warning` prints a stderr warning (non-blocking)
    when an objective smells like an inline brief (> ~200 chars, no
    CODEX_QUEUE reference).
    """
    warning = codex_inline_brief_warning(objective, lane)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in objective)[:48].strip("-")
    # UNIQUENESS FROM THE NAME ITSELF, not from looking first.
    #
    # Two earlier versions were both wrong, and the second was mine:
    #   * `{stamp}-{slug}.json` with SECOND resolution -- two enqueues of one
    #     objective inside a second produced the same path and the later one
    #     silently overwrote the earlier. A queue that drops a task under load.
    #   * then an existence check with a counter, which is check-then-use: two
    #     PARALLEL producers both see the same free name and both write it.
    #     Serial callers never notice, which is exactly why the acceptance
    #     check (which enqueues serially) went green over it.
    # A uuid cannot collide and needs nobody to look. The stamp and slug stay
    # because they are what makes the outbox readable to a human.
    base = f"{_stamp()}-{slug or 'task'}-{uuid.uuid4().hex[:8]}"
    path = OUTBOX / f"{base}.json"
    payload = {
        "objective": objective,
        "repo_root": repo_root,
        "paths": paths,
        "model": model,
        "source": source,
        # Ikarus strategy:
        #   single -> route this one task through Ikarus
        #   spawn  -> let Ikarus decompose the objective and dispatch the bench
        "strategy": strategy,
        # Which lane the watcher may dispatch to:
        #   auto       -> route; run on the free bench when eligible, else Claude
        #   local      -> same as auto (prefer the bench), else fall back to Claude
        #   local_only -> local bench only; never fall back to Claude
        #   claude     -> always the trusted Claude lane
        #   codex      -> always the Codex CLI (external, egress-gated; no fallback)
        "lane": lane,
    }
    if project:
        payload["project"] = project
    if category:
        # Additive metadata only -- the role-category tag of the routed/owning
        # agent, carried through for the UI/bus/reports. Never consulted by
        # the lane gate in core.process_bridge_payload.
        payload["category"] = category
    # PUBLISH ATOMICALLY. `write_text` is not one operation to a reader: the
    # watcher polls this directory, and a plain write lets it glob a file that
    # is half a JSON document. Writing to a name the watcher's `*.json` glob
    # cannot match and then `os.replace`-ing it means the request either is not
    # there or is there complete -- there is no observable in-between.
    tmp = OUTBOX / f"{base}.json.tmp"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_request(path: Path, default_repo_root: str | None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "objective" not in payload:
        raise ValueError("request needs an objective")
    if "repo_root" not in payload:
        if not default_repo_root:
            raise ValueError("request needs repo_root or bridge needs --repo-root")
        payload["repo_root"] = default_repo_root
    payload.setdefault("paths", [])
    payload.setdefault("model", "sonnet")
    payload.setdefault("lane", "local_only")  # fail-closed: an unlabeled file (hand-dropped/legacy) never spends unattended
    payload.setdefault("source", "unknown")
    payload.setdefault("strategy", "single")
    return payload


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
    Marking the journal is what stops the retry loop if the move itself fails
    on a locked file: the next poll only retries the move, it does not rewrite
    the report or the log line."""
    key = _request_key(path)
    dest = _quarantine_dir() / path.name
    report = {
        "request_file": key,
        "bridge_status": "quarantined",
        "error": f"{reason}: {detail}",
        "reason": reason,
        "quarantined_at": _now_iso(),
        "quarantine_path": str(dest),
    }
    result_path = INBOX / f"{key}.report.json"
    _write_json_atomic(result_path, report)
    _note_report_arrival(result_path, report, key=key)
    _write_json_atomic(_quarantine_dir() / f"{key}.error.json", report)
    entry = _read_journal(key)
    entry["state"] = "quarantined"
    entry["key"] = key
    entry["reason"] = reason
    _write_journal(key, entry)
    _quarantine_move(path, key)
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


def process_request(path: Path, default_repo_root: str | None = None) -> Path:
    """Process one request, EXACTLY ONCE, across crashes.

    Reprocessing the same request -- which is what a restarted watcher does
    with anything still in the outbox -- must not yield two reports, two
    LATEST.log lines, two memory records or two archived copies. See the
    "crash safety" note above _request_key for how each of the four steps is
    made idempotent, and by which mechanism.

    Note what is NOT closed: if the process dies between dispatching the work
    and the report landing, we cannot know whether the provider ran, so the
    work is retried -- up to MAX_ATTEMPTS, after which the request is
    quarantined rather than re-dispatched forever."""
    INBOX.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    key = _request_key(path)
    result_path = INBOX / f"{key}.report.json"
    entry = _read_journal(key)

    if entry.get("state") == "quarantined":
        # Already given up on; the only thing left to do is finish evicting it.
        _quarantine_move(path, key)
        return result_path

    steps = entry.get("steps") if isinstance(entry.get("steps"), dict) else {}
    attempts = int(entry.get("attempts") or 0)
    entry.update({"key": key, "steps": steps, "attempts": attempts,
                  "state": entry.get("state") or "new"})

    # -- step 1: the work, and the report that commits it -------------------
    # A complete report for this key IS the receipt that the work happened.
    # Reusing it is the whole point: re-running is what spends money twice.
    report = _completed_report(result_path) if steps.get("report") else None
    if report is None:
        if attempts >= MAX_ATTEMPTS:
            return quarantine_request(
                path, "interrupted",
                f"dispatched {attempts} times without ever producing a report "
                "-- refusing to run it again (see runs/processed/.journal)")
        payload = _read_request(path, default_repo_root)  # poison raises here
        entry["attempts"] = attempts + 1
        entry["state"] = "in_flight"
        entry["lane"] = payload.get("lane")
        _write_journal(key, entry)  # durable BEFORE the work: survives a kill

        from .core import process_bridge_payload
        report = process_bridge_payload(payload)
        # The idempotency key, carried on the artifact itself, so the memory
        # log can be asked "did this request's record already land?".
        report["request_file"] = key

        _write_json_atomic(result_path, report)
        steps["report"] = True
        entry["state"] = "reported"
        _write_journal(key, entry)

    # -- step 2: arrival line (deduped by key, inside _note_report_arrival) --
    if not steps.get("log"):
        _note_report_arrival(result_path, report, key=key)
        steps["log"] = True
        _write_journal(key, entry)

    # -- step 3: memory record ----------------------------------------------
    memory_step = steps.get("memory")
    if memory_step is not True:
        # "pending" means we died with the append in flight -- the only state
        # the flag cannot resolve, and the only time we pay for a log scan.
        if memory_step != "pending" or not _memory_already_recorded(key):
            steps["memory"] = "pending"
            _write_journal(key, entry)
            record_from_bridge_report(report)
        steps["memory"] = True
        _write_journal(key, entry)

    # -- step 4: archive ----------------------------------------------------
    if _archive_once(path, key):
        steps["archive"] = True
        entry["state"] = "done"
        _write_journal(key, entry)
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
    except Exception as inner:  # noqa: BLE001 -- never let recovery kill the loop
        print(f"QUARANTINE FAILED {path.name}: {inner}", flush=True)
        return None


# -- watcher heartbeat ------------------------------------------------------

_last_idle_beat = 0.0


def write_heartbeat(project: str | None = None, repo_root: str | None = None,
                    interval_s: float | None = None,
                    current: dict[str, Any] | None = None,
                    force: bool = False) -> None:
    """Best-effort liveness marker written by the watch loop.

    Idle beats are throttled to one per IDLE_BEAT_EVERY_S; task start/finish
    beats (``force=True``) always land. Written via temp-file + os.replace so
    a concurrent doctor read never sees a half-written file. Never raises."""
    global _last_idle_beat
    now = time.time()
    if not force and current is None and now - _last_idle_beat < IDLE_BEAT_EVERY_S:
        return
    payload = {
        "ts": _now_iso(),
        "epoch": now,
        "pid": os.getpid(),
        "project": project,
        "repo_root": repo_root,
        "interval_s": interval_s,
        "current": current,
    }
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEARTBEAT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, HEARTBEAT_PATH)
        if current is None:
            _last_idle_beat = now
    except OSError:
        pass  # liveness signal only -- never let it kill or slow the watcher


def restart_hint(hb: dict[str, Any] | None = None) -> str:
    """The exact one-liner to (re)start the watcher, from heartbeat context."""
    hb = hb or {}
    if hb.get("project"):
        return f"python -m daedalus.file_bridge watch --project {hb['project']}"
    if hb.get("repo_root"):
        return f'python -m daedalus.file_bridge watch --repo-root "{hb["repo_root"]}"'
    return "python -m daedalus.file_bridge watch --project <project>"


def heartbeat_status(now: float | None = None) -> dict[str, Any]:
    """Classify the watcher heartbeat. States:

    * ``none``   -- no heartbeat file: watcher not running, or it predates the
                    heartbeat feature (cross-check: `daedalus watcher status`).
    * ``alive``  -- idle beat fresher than STALE_AFTER_S.
    * ``busy``   -- a task is in flight, within BUSY_BUDGET_S.
    * ``wedged`` -- a task has been in flight longer than BUSY_BUDGET_S.
    * ``stale``  -- idle beat older than STALE_AFTER_S: watcher is dead.
    """
    now = time.time() if now is None else now
    try:
        hb = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"state": "none", "restart": restart_hint(),
                "detail": "no heartbeat recorded (watcher not running, or "
                          "started before the heartbeat feature landed)"}
    age = max(0.0, now - float(hb.get("epoch") or 0.0))
    out = {
        "age_s": round(age, 1),
        "pid": hb.get("pid"),
        "project": hb.get("project"),
        "repo_root": hb.get("repo_root"),
        "current": hb.get("current"),
        "restart": restart_hint(hb),
    }
    current = hb.get("current")
    if current:
        busy_for = max(0.0, now - float(current.get("started_epoch") or 0.0))
        out["busy_for_s"] = round(busy_for, 1)
        out["state"] = "busy" if busy_for <= BUSY_BUDGET_S else "wedged"
        return out
    out["state"] = "alive" if age <= STALE_AFTER_S else "stale"
    return out


# -- report read-state + status ---------------------------------------------

def unread_reports() -> list[Path]:
    """Reports in the inbox with no .seen marker, oldest first."""
    if not INBOX.exists():
        return []
    seen = _seen_dir()
    return [p for p in sorted(INBOX.glob("*.report.json"))
            if not (seen / p.name).exists()]


def mark_read(names: list[str] | None = None, all_reports: bool = False) -> list[str]:
    """Acknowledge reports by dropping a marker per report into inbox/.seen/.
    Returns the report names actually marked."""
    targets: list[Path] = []
    if all_reports:
        targets = unread_reports()
    else:
        for name in names or []:
            path = INBOX / name
            if not path.exists() and not name.endswith(".report.json"):
                path = INBOX / f"{name}.report.json"
            if path.exists():
                targets.append(path)
    marked = []
    if targets:
        _seen_dir().mkdir(parents=True, exist_ok=True)
    for path in targets:
        try:
            (_seen_dir() / path.name).touch()
            marked.append(path.name)
        except OSError:
            pass
    return marked


def quarantined_requests() -> list[dict[str, Any]]:
    """Requests the watcher gave up on, with why. Surfaced by `status` so a
    quarantine is a thing an operator SEES, not a directory nobody opens."""
    qdir = _quarantine_dir()
    if not qdir.exists():
        return []
    out = []
    for path in sorted(qdir.glob("*.json")):
        if path.name.endswith(".error.json"):
            continue
        try:
            sidecar = json.loads(
                (qdir / f"{path.stem}.error.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            sidecar = {}
        out.append({"name": path.name, "reason": sidecar.get("reason") or "?",
                    "error": sidecar.get("error") or "", "path": str(path)})
    return out


def _report_brief(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        payload = {}
    request = payload.get("request") or {}
    summary = ((payload.get("report") or {}).get("summary")
               or payload.get("error") or "")
    return {
        "name": path.name,
        "status": payload.get("bridge_status") or "?",
        "lane": payload.get("lane") or request.get("lane") or "?",
        "project": request.get("project") or "",
        "summary": " ".join(str(summary).split())[:160],  # one line for the console
    }


def bridge_status(project: str | None = None) -> dict[str, Any]:
    """One-call answer to: is anything queued, is anything running, and are
    there finished reports I have not read yet?"""
    queued = []
    for path in sorted(OUTBOX.glob("*.json")) if OUTBOX.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            payload = {}
        if project and payload.get("project") not in (project, None, ""):
            continue
        queued.append({"name": path.name, "lane": payload.get("lane") or "?",
                       "project": payload.get("project") or ""})
    unread = []
    for path in unread_reports():
        brief = _report_brief(path)
        if project and brief["project"] not in (project, ""):
            continue
        unread.append(brief)
    hb = heartbeat_status()
    in_flight = hb.get("current") if hb.get("state") in ("busy", "wedged") else None
    quarantined = quarantined_requests()
    return {
        "project": project,
        "watcher": hb,
        "queued": queued,
        "queue_depth": len(queued),
        "in_flight": in_flight,
        "unread": unread,
        "unread_count": len(unread),
        "quarantined": quarantined,
        "quarantined_count": len(quarantined),
        "reports_total": len(list(INBOX.glob("*.report.json"))) if INBOX.exists() else 0,
        "latest_log": str(_latest_log()),
    }


def stream_state(project: str | None = None) -> dict[str, Any]:
    """Compact, CHEAP snapshot for the SSE live stream. Reads ONLY the file bus
    (outbox/inbox/heartbeat) — no git, PowerShell or Ollama — so it can be polled
    once a second to drive the cockpit's live badges without the heavy dashboard.
    """
    st = bridge_status(project)
    newest = None
    if INBOX.exists():
        reports = sorted(INBOX.glob("*.report.json"), key=lambda p: p.stat().st_mtime)
        if reports:
            newest = _report_brief(reports[-1])
    return {
        "queue_depth": st["queue_depth"],
        "in_flight": bool(st["in_flight"]),
        "unread_count": st["unread_count"],
        "quarantined_count": st["quarantined_count"],
        "watcher_state": (st["watcher"] or {}).get("state"),
        "reports_total": st["reports_total"],
        "latest_report": newest,
    }


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
          project: str | None = None) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    print("AGENT_BRIDGE_START", flush=True)
    print(f"Watching {OUTBOX}", flush=True)
    print("AGENT_BRIDGE_READY", flush=True)

    def _beat(current: dict[str, Any] | None = None, force: bool = False) -> None:
        write_heartbeat(project=project, repo_root=default_repo_root,
                        interval_s=interval_s, current=current, force=force)

    while True:
        _beat()
        for path in sorted(OUTBOX.glob("*.json")):
            print(f"Processing {path.name}", flush=True)
            _beat(current={"file": path.name, "started_epoch": time.time(),
                           "started_ts": _now_iso()}, force=True)
            try:
                result = process_request(path, default_repo_root)
                print(f"Wrote {result}", flush=True)
            except Exception as exc:
                handle_poison_request(path, exc)
            _beat(force=True)
        time.sleep(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="File bridge between Codex and Claude.")
    sub = parser.add_subparsers(dest="command")

    watch_p = sub.add_parser("watch", help="Watch outbox and process Claude requests.")
    watch_p.add_argument("--repo-root")
    watch_p.add_argument("--project")
    watch_p.add_argument("--interval-s", type=float, default=2.0)

    enqueue_p = sub.add_parser("enqueue", help="Create a Claude request in outbox.")
    enqueue_p.add_argument("objective")
    enqueue_p.add_argument("--repo-root")
    enqueue_p.add_argument("--project")
    enqueue_p.add_argument("--paths", nargs="*", default=[])
    enqueue_p.add_argument("--model", default="sonnet")
    enqueue_p.add_argument("--lane", default="auto",
                           choices=["auto", "claude", "local", "local_only", "codex"],
                           help="auto/local prefer the free bench; local_only never calls Claude; "
                                "claude forces the trusted lane; codex forces the external "
                                "Codex CLI (egress-gated, no fallback)")
    enqueue_p.add_argument("--source", default="unknown",
                           choices=["unknown", "codex", "claude", "user", "ikarus"],
                           help="who queued the request")
    enqueue_p.add_argument("--strategy", default="single", choices=["single", "spawn"],
                           help="single routes one task; spawn lets Ikarus decompose and fan out")

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
    if args.command == "watch":
        watch(resolve_repo_root(args.repo_root, args.project), args.interval_s,
              project=args.project)
    elif args.command == "enqueue":
        print(enqueue(args.objective, resolve_repo_root(args.repo_root, args.project),
                      args.paths, args.model, args.lane, args.project,
                      args.source, args.strategy))
    elif args.command == "once":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None
        for path in sorted(OUTBOX.glob("*.json")):
            # Same recovery as the watcher: one poison request must not abort
            # the requests queued behind it.
            try:
                print(process_request(path, repo_root))
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
