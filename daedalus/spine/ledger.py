"""spine/ledger.py -- Mission Spine light: the durable intent ledger.

The self-improvement loop performs EXTERNAL effects (create a worktree, write a
patch, land a commit, mint an eval task). A crash between "decided to do it" and
"did it" is the only failure mode that cannot be recovered by re-reading the
repo, because nothing on disk records the decision. This module is the durable
record of the decision -- and deliberately nothing more.

WHAT THIS IS NOT
----------------
Not a mission state machine. No leases, no heartbeats, no worker contention, no
scheduling. There is exactly ONE worker until a remote node lands, so anything
that exists only to arbitrate between workers is unbuilt weight. What is here is
the one property a single worker still cannot get for free: crash-safe
intent-before-effect recording.

INTENT BEFORE EFFECT
--------------------
``record_intent`` writes an INTENDED row and COMMITS IT BEFORE the caller
performs the external effect. The ordering is the whole contract, so the ledger
can never be BEHIND reality: every effect that happened has a row.

CLOSING THE CRASH WINDOW -- BY IDENTIFICATION, NOT BY THE KEY
-------------------------------------------------------------
The ledger CAN be ahead of reality: a crash after the effect lands and before
``mark_completed`` commits leaves an INTENDED row whose effect already happened.
No key discipline fixes that from inside the database -- the row cannot know
what the outside world did.

What closes that window is EFFECT IDENTIFICATION. The caller supplies an
``effect_key`` it can go and LOOK FOR afterwards (a patch sha256, a commit
trailer token, a worktree branch name), so recovery is a handshake with the
world:

    for intent in ledger.open_intents():          # unresolved on startup
        if world_contains(intent.effect_key):     # the caller's own check
            ledger.mark_completed(intent.id, effect_id=..., result=...)
        else:
            redo(intent.payload)

``resolve_by_effect`` is the ledger half of that handshake -- given a key found
in the world, which intent claimed it. The key is a QUESTION YOU CAN ASK, not a
promise the effect happened at most once: it delivers no idempotency on its own.
A caller whose effect is NOT identifiable after the fact gets no crash safety
here and must not pretend otherwise -- such a caller should make its effect
identifiable (stamp the token INTO the artifact) before using this ledger.

APPEND-ONLY IN SPIRIT
---------------------
``intents`` rows are written once and never UPDATEd -- a recorded intent's kind,
payload and effect_key are immutable facts about what was decided. Every state
transition APPENDS a row to ``intent_events``; the current state is derived from
the latest event, so the full history (and its timestamps) survives. There is no
UPDATE statement in this module.

DOUBLE RESOLUTION IS REJECTED, NOT ABSORBED
-------------------------------------------
``mark_completed`` / ``mark_failed`` on an already-terminal intent raise
:class:`IntentAlreadyResolved`. Silent idempotency was the alternative and is
worse here: a second completion carrying a DIFFERENT effect_id means the caller
believes something the ledger does not, and swallowing it destroys the
disagreement. The check runs inside the same BEGIN IMMEDIATE transaction as the
append, so it cannot be raced.

DURABILITY SETTINGS
-------------------
``journal_mode=WAL`` (readers never block the writer, and a committed row
survives process death without a clean close), ``synchronous=NORMAL`` (WAL's
documented safe pairing: durable across process crash, which is the failure this
module exists for; a power cut can lose the last commits), ``busy_timeout``
(every write is BEGIN IMMEDIATE, which DOES honour the busy handler, so a second
writer waits instead of erroring), ``foreign_keys=ON`` (an event can never
reference a vanished intent).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1

STATE_INTENDED = "INTENDED"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
TERMINAL_STATES = (STATE_COMPLETED, STATE_FAILED)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "runs" / "spine" / "spine.sqlite3"

# Long enough that a second writer waits out any realistic single-transaction
# hold rather than surfacing "database is locked" to the loop.
DEFAULT_BUSY_TIMEOUT_MS = 30000


class SpineError(RuntimeError):
    """Base for every refusal this ledger makes."""


class UnknownIntent(SpineError):
    """No intent with that id exists."""


class IntentAlreadyResolved(SpineError):
    """The intent already carries a terminal event; resolution is once-only."""


# --------------------------------------------------------------------------- #
# canonical JSON -- the one serialisation, so digests are stable               #
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    """The single serialisation used for every stored blob.

    ``sort_keys`` makes two dicts built in different insertion orders produce
    byte-identical text; ``separators`` strips the whitespace a pretty-printer
    would vary; ``ensure_ascii`` pins the bytes so a digest does not depend on
    the reader's encoding. Mirrors ``memstore._body_sha``'s discipline: one
    place, one answer to "what bytes did we hash?".
    """
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"spine ledger stores JSON-serialisable values only: {e}") from e


def canonical_sha(obj: Any) -> str:
    """sha256 over :func:`canonical_json` -- stable across insertion order."""
    return hashlib.sha256(canonical_json(obj).encode("ascii")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uri_path(path: Path) -> str:
    """A filesystem path as the path part of a SQLite ``file:`` URI.

    Backslashes are not URI separators, and ``?``/``#`` would start the query
    and fragment -- on Windows all three turn up in real paths.
    """
    return (str(path).replace("\\", "/")
            .replace("?", "%3f").replace("#", "%23"))


def default_db_path() -> Path:
    """Where the ledger lives. ``DAEDALUS_SPINE_DB`` overrides it (tests and
    isolated worktrees point this away from the real runs/ directory)."""
    env = os.environ.get("DAEDALUS_SPINE_DB", "").strip()
    return Path(env) if env else DEFAULT_DB_PATH


# --------------------------------------------------------------------------- #
# records                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Intent:
    """One recorded intent plus its derived current state.

    ``payload_json`` is the exact text stored in the row (not a re-render), so a
    caller can digest or diff it without guessing the serialisation.
    """
    id: int
    kind: str
    effect_key: str | None
    payload: Any
    payload_json: str
    payload_sha: str
    created_ts: str
    state: str
    resolved_ts: str | None = None
    effect_id: str | None = None
    result: Any = None
    error: str | None = None

    @property
    def is_open(self) -> bool:
        return self.state == STATE_INTENDED


@dataclass(frozen=True)
class IntentEvent:
    id: int
    intent_id: int
    state: str
    ts: str
    detail: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# schema                                                                       #
# --------------------------------------------------------------------------- #
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS spine_meta ("
    " key TEXT PRIMARY KEY,"
    " value TEXT NOT NULL)",

    # Written once, never updated. Everything that changes lives in the events
    # table, so the decision as recorded stays readable forever.
    "CREATE TABLE IF NOT EXISTS intents ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " kind TEXT NOT NULL,"
    " effect_key TEXT,"
    " payload TEXT NOT NULL,"
    " payload_sha TEXT NOT NULL,"
    " created_ts TEXT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS intent_events ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " intent_id INTEGER NOT NULL REFERENCES intents(id),"
    " state TEXT NOT NULL,"
    " ts TEXT NOT NULL,"
    " detail TEXT NOT NULL)",

    "CREATE INDEX IF NOT EXISTS idx_intents_effect_key"
    " ON intents(effect_key)",
    "CREATE INDEX IF NOT EXISTS idx_intent_events_intent"
    " ON intent_events(intent_id, id)",
    # open_intents scans for the ABSENCE of a terminal event; index the states
    # that can end a life so that probe stays a lookup.
    "CREATE INDEX IF NOT EXISTS idx_intent_events_terminal"
    " ON intent_events(intent_id) WHERE state IN ('COMPLETED','FAILED')",
)


# --------------------------------------------------------------------------- #
# the ledger                                                                   #
# --------------------------------------------------------------------------- #
class SpineLedger:
    """Crash-safe intent ledger over one SQLite file.

    One connection per instance. ``check_same_thread=False`` plus an internal
    lock lets a single instance be shared across threads (the loop's worker and
    a status reader) without two statements interleaving on one connection;
    separate instances on the same file are arbitrated by SQLite itself under
    ``busy_timeout``.
    """

    def __init__(self, path: str | Path | None = None, *,
                 busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
                 read_only: bool = False) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.read_only = bool(read_only)
        self._lock = threading.RLock()

        if self.read_only:
            # A READER MUST NOT WRITE. The normal path creates the parent
            # directory, sets journal_mode=WAL (which writes the file header)
            # and runs migrations inside BEGIN IMMEDIATE -- so merely OPENING a
            # ledger to look at it mutates it. That is intolerable for callers
            # whose whole contract is that they change nothing (the picker's
            # --dry-run ranks a queue and must stay a read). SQLite enforces it
            # here rather than this class promising it: mode=ro fails any write
            # at the engine, so a future edit that adds one cannot pass tests.
            #
            # HONEST LIMIT: opening a WAL database read-only still creates the
            # ``-wal``/``-shm`` sidecars, because the shared-memory index is how
            # WAL reads work. The ledger's CONTENTS are untouched (a test pins
            # the file's sha256 across a read), but this is not "touches
            # nothing on disk", and a genuinely read-only filesystem will fail
            # the open -- which callers surface as an error rather than as a
            # silently empty history.
            uri = f"file:{_uri_path(self.path)}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, isolation_level=None,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Per-connection only; neither touches the file.
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA query_only=ON")
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None,
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._migrate()

    # -- setup ------------------------------------------------------------- #
    def _apply_pragmas(self) -> None:
        c = self._conn
        # journal_mode is persistent in the FILE (not per connection); the rest
        # are per connection and must be re-applied on every open, which is why
        # they live here rather than in _migrate.
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        c.execute("PRAGMA foreign_keys=ON")

    def _migrate(self) -> None:
        with self._txn() as c:
            for stmt in _SCHEMA:
                c.execute(stmt)
            c.execute("INSERT OR IGNORE INTO spine_meta (key, value) VALUES (?,?)",
                      ("schema_version", str(SCHEMA_VERSION)))
        found = self.pragmas()
        if found["journal_mode"].lower() != "wal":
            # A ledger without WAL loses the durability posture this module is
            # built on; that must be loud, not a quietly weaker guarantee.
            raise SpineError(
                f"spine ledger at {self.path} is in journal_mode="
                f"{found['journal_mode']!r}, not WAL (network filesystem?); "
                f"refusing to run with weaker crash semantics than declared")

    def pragmas(self) -> dict[str, Any]:
        """The durability settings AS THE DATABASE REPORTS THEM -- read back,
        not echoed from what we asked for. A pragma that silently failed to
        apply is exactly the failure worth surfacing."""
        with self._lock:
            def one(name: str):
                row = self._conn.execute(f"PRAGMA {name}").fetchone()
                return row[0] if row else None
            return {
                "journal_mode": one("journal_mode"),
                "synchronous": one("synchronous"),
                "busy_timeout": one("busy_timeout"),
                "foreign_keys": one("foreign_keys"),
            }

    # -- transactions ------------------------------------------------------- #
    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        """Every write runs here. BEGIN IMMEDIATE takes the write lock UP FRONT
        instead of on first write, so two writers never deadlock upgrading a
        read transaction (which returns SQLITE_BUSY without consulting the busy
        handler -- unlike BEGIN IMMEDIATE, which waits out busy_timeout)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # -- writes ------------------------------------------------------------- #
    def record_intent(self, kind: str, payload: Any = None, *,
                      effect_key: str | None = None) -> Intent:
        """Record an intent and COMMIT it. Call this BEFORE the effect.

        ``effect_key`` is the caller's after-the-fact identifier for the effect
        (see the module docstring). It is NOT unique-constrained: a retried
        intent legitimately reuses the key, and the ledger records both attempts
        rather than hiding one.
        """
        kind = str(kind or "").strip()
        if not kind:
            raise ValueError("record_intent requires a non-empty kind")
        if effect_key is not None:
            effect_key = str(effect_key)
        payload_json = canonical_json(payload)
        payload_sha = hashlib.sha256(payload_json.encode("ascii")).hexdigest()
        ts = _now_iso()
        with self._txn() as c:
            cur = c.execute(
                "INSERT INTO intents"
                " (kind, effect_key, payload, payload_sha, created_ts)"
                " VALUES (?,?,?,?,?)",
                (kind, effect_key, payload_json, payload_sha, ts))
            intent_id = int(cur.lastrowid)
            self._append_event(c, intent_id, STATE_INTENDED, ts,
                               {"payload_sha": payload_sha})
        # payload is re-read from the canonical text, not echoed: what the
        # caller gets back is what a later reader will get back (a tuple stored
        # is a list read), so no code path is written against a shape that only
        # exists in the writing process.
        return Intent(
            id=intent_id, kind=kind, effect_key=effect_key,
            payload=json.loads(payload_json), payload_json=payload_json,
            payload_sha=payload_sha, created_ts=ts, state=STATE_INTENDED)

    def mark_completed(self, intent_id: int, effect_id: str | None = None,
                       result: Any = None) -> Intent:
        """Close an open intent as COMPLETED. Rejects a second resolution."""
        return self._resolve(intent_id, STATE_COMPLETED, {
            "effect_id": None if effect_id is None else str(effect_id),
            "result": result,
        })

    def mark_failed(self, intent_id: int, error: str) -> Intent:
        """Close an open intent as FAILED. Rejects a second resolution."""
        return self._resolve(intent_id, STATE_FAILED, {"error": str(error)})

    def _resolve(self, intent_id: int, state: str, detail: dict) -> Intent:
        intent_id = int(intent_id)
        ts = _now_iso()
        # canonical_json before opening the transaction: an unserialisable
        # result must fail without leaving a half-open write lock.
        canonical_json(detail)
        with self._txn() as c:
            row = c.execute(
                "SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
            if row is None:
                raise UnknownIntent(f"no intent with id {intent_id}")
            prior = self._terminal_event(c, intent_id)
            if prior is not None:
                raise IntentAlreadyResolved(
                    f"intent {intent_id} is already {prior['state']} "
                    f"(at {prior['ts']}); resolution is once-only, so a second "
                    f"{state} is refused rather than silently absorbed")
            self._append_event(c, intent_id, state, ts, detail)
            return _row_to_intent(row, state=state, ts=ts, detail=detail)

    @staticmethod
    def _append_event(conn: sqlite3.Connection, intent_id: int, state: str,
                      ts: str, detail: dict) -> int:
        cur = conn.execute(
            "INSERT INTO intent_events (intent_id, state, ts, detail)"
            " VALUES (?,?,?,?)",
            (intent_id, state, ts, canonical_json(detail)))
        return int(cur.lastrowid)

    @staticmethod
    def _terminal_event(conn: sqlite3.Connection, intent_id: int):
        return conn.execute(
            "SELECT state, ts, detail FROM intent_events"
            " WHERE intent_id = ? AND state IN (?,?)"
            " ORDER BY id DESC LIMIT 1",
            (intent_id, STATE_COMPLETED, STATE_FAILED)).fetchone()

    # -- reads -------------------------------------------------------------- #
    def get(self, intent_id: int) -> Intent | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM intents WHERE id = ?", (int(intent_id),)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate(row)

    def open_intents(self, kind: str | None = None) -> list[Intent]:
        """Every intent with no terminal event, oldest first.

        This is the crash-recovery worklist: anything here either never had its
        effect performed, or had it performed and lost the acknowledgement --
        the caller distinguishes the two by looking for ``effect_key`` in the
        world (see the module docstring).
        """
        sql = ("SELECT i.* FROM intents i WHERE NOT EXISTS ("
               "  SELECT 1 FROM intent_events e"
               "  WHERE e.intent_id = i.id AND e.state IN (?,?))")
        args: list[Any] = [STATE_COMPLETED, STATE_FAILED]
        if kind is not None:
            sql += " AND i.kind = ?"
            args.append(str(kind))
        sql += " ORDER BY i.id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [_row_to_intent(r, state=STATE_INTENDED) for r in rows]

    def recent_intents(self, kind: str | None = None, *,
                       limit: int | None = None) -> list[Intent]:
        """Every intent, RESOLVED OR NOT, newest first.

        The read that closes the loop's return path. ``open_intents`` is a
        crash-recovery worklist and deliberately excludes anything terminal, so
        before this existed a COMPLETED attempt was reachable only by an id or
        an effect_key the caller had to already know -- which meant nothing
        could ask the ledger the one question a self-improving loop has to ask:
        *what have I already tried, and how did it end?* Without it the picker
        re-selects the same candidate forever (measured: five recorded
        gate-failed attempts left the top five of the queue unchanged).

        Newest first because every caller wants recency; ``limit`` is applied in
        SQL so a long-lived ledger does not have to be hydrated in full to
        answer "what happened lately". A non-positive limit returns nothing,
        which is the truthful answer to "give me zero rows" and keeps a caller's
        arithmetic (``limit=n-1``) from silently meaning "all".
        """
        if limit is not None and int(limit) <= 0:
            return []
        sql = "SELECT * FROM intents"
        args: list[Any] = []
        if kind is not None:
            sql += " WHERE kind = ?"
            args.append(str(kind))
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
            return [self._hydrate(r) for r in rows]

    def intents_matching_payload(self, key: str, values: Sequence[str], *,
                                 kind: str | None = None) -> list[Intent]:
        """Intents whose payload records ``key`` as one of ``values``.

        The targeted alternative to ``recent_intents(limit=N)``. A row limit is
        a WINDOW, not a bound: with it, the oldest attempts silently fall out of
        memory and their tasks become selectable again, so a loop would slowly
        start repeating work it had already done -- the exact defect the memory
        exists to prevent, reintroduced by the thing meant to make it cheap.
        Asking for the specific values a caller cares about has no such edge.

        Matching is a substring test against the payload TEXT, which is exact
        here rather than approximate because every payload is written through
        ``canonical_json``: sorted keys, no whitespace, ``ensure_ascii``. So a
        recorded ``key``/``value`` pair always appears verbatim as
        ``"key":"value"``. LIKE metacharacters in either are escaped, so a value
        containing ``%`` matches only a literal ``%``.
        """
        wanted = [str(v) for v in values if str(v)]
        if not wanted:
            return []
        clauses, args = [], []
        for value in wanted:
            fragment = canonical_json({str(key): value})[1:-1]  # drop the braces
            escaped = (fragment.replace("\\", "\\\\").replace("%", "\\%")
                       .replace("_", "\\_"))
            clauses.append("payload LIKE ? ESCAPE '\\'")
            args.append(f"%{escaped}%")
        sql = f"SELECT * FROM intents WHERE ({' OR '.join(clauses)})"
        if kind is not None:
            sql += " AND kind = ?"
            args.append(str(kind))
        sql += " ORDER BY id DESC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
            return [self._hydrate(r) for r in rows]

    def resolve_by_effect(self, effect_key: str) -> list[Intent]:
        """Every intent recorded under ``effect_key``, oldest first.

        A LOOKUP, not a mutation: given a token found in the world, this answers
        "which intent claimed it" so the caller can close that intent. It
        returns a list because retries legitimately reuse a key, and collapsing
        them to one would hide an attempt.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM intents WHERE effect_key = ? ORDER BY id",
                (str(effect_key),)).fetchall()
            return [self._hydrate(r) for r in rows]

    def events(self, intent_id: int) -> list[IntentEvent]:
        """The full append-only transition history for one intent."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, intent_id, state, ts, detail FROM intent_events"
                " WHERE intent_id = ? ORDER BY id", (int(intent_id),)).fetchall()
        return [IntentEvent(id=r["id"], intent_id=r["intent_id"],
                            state=r["state"], ts=r["ts"],
                            detail=json.loads(r["detail"])) for r in rows]

    def _hydrate(self, row: sqlite3.Row) -> Intent:
        term = self._terminal_event(self._conn, int(row["id"]))
        if term is None:
            return _row_to_intent(row, state=STATE_INTENDED)
        return _row_to_intent(row, state=term["state"], ts=term["ts"],
                              detail=json.loads(term["detail"]))

    # -- lifecycle ---------------------------------------------------------- #
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "SpineLedger":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


def _row_to_intent(row: sqlite3.Row, *, state: str, ts: str | None = None,
                   detail: dict | None = None) -> Intent:
    detail = detail or {}
    return Intent(
        id=int(row["id"]),
        kind=row["kind"],
        effect_key=row["effect_key"],
        payload=json.loads(row["payload"]),
        payload_json=row["payload"],
        payload_sha=row["payload_sha"],
        created_ts=row["created_ts"],
        state=state,
        resolved_ts=ts if state in TERMINAL_STATES else None,
        effect_id=detail.get("effect_id"),
        result=detail.get("result"),
        error=detail.get("error"),
    )
