"""conversation.py -- durable multi-turn state for the Ikarus assistant seam.

WHAT THIS IS. ``daedalus/ikarus_os.py`` is the assistant seam: ``ask()`` /
``ask_stream()`` classify one message, route it to a deterministic intent or a
freeform brain, and return a chat envelope (see :func:`daedalus.core.envelope`).
Established by reading it first, per brief: it earns the Ikarus name honestly --
it IS where a user's turn becomes a routed reply -- but every call is stateless.
There is no conversation id, no turn history, nothing that survives a restart.
This module is the missing piece: a conversation has an id, turns are appended
durably, the assistant can be resumed after a restart and know what it was
doing, and work dispatched because of a turn is linked back to it so a report
arriving later attributes to the request that caused it.

WHY A FOURTH APPEND-ONLY LOG, HAVING READ THE OTHER THREE
-----------------------------------------------------------
Three durable logs already exist in this tree. None fits without distortion:

  * ``daedalus/memory/events.local.jsonl`` (+ projection_worker.py) is a
    cross-session RECALL journal: flat events keyed by (kind, source, task_id),
    projected into a vector index for semantic search, with a Markdown TODO
    snapshot REWRITTEN IN FULL on every append. It has no conversation id, no
    turn sequence, and no notion of "this dispatch belongs to that turn" --
    and firing its full-file todo-snapshot rewrite on every chat message
    (routine, high-frequency) would be paying an O(events) cost per turn for a
    journal designed for occasional agent-handoff notes. Wrong grain.
  * ``daedalus/council/bus.py`` is a hash-chained, tamper-evident transcript
    for multi-VENDOR deliberation. Its own docstring is explicit that it
    "deliberately REIMPLEMENTS memstore.py's two-SHA discipline" for a named
    reason (council opinion must never be promoted to certified memory) and
    that "COUNCIL RECORDS ARE NEVER AN INPUT TO MEMORY RECALL". Its actor
    schema is ``council.<vendor>.<model>`` -- a user/assistant chat turn does
    not have a vendor+model identity to place there, and the tamper-evidence
    machinery (hash chain, secret-floor-at-write, refusal receipts) solves a
    threat model -- a deliberation participant lying about what was said --
    that a private local chat log does not have. Reusing it would be a
    category error the module's own docstring warns against.
  * ``daedalus/spine/ledger.py`` is the closest cousin and the one this module
    actually borrows from: a crash-safe SQLite/WAL intent ledger for the
    self-improvement loop's EXTERNAL effects (worktree, patch, commit, eval
    mint). Its docstring states its scope on purpose: "WHAT THIS IS NOT --
    Not a mission state machine [...] anything that exists only to arbitrate
    between workers is unbuilt weight." A conversation turn is not one intent
    with one terminal resolution: ONE turn can cause ZERO OR MORE dispatches,
    each evolving independently and each reportable MORE THAN ONCE (a patch
    can be "produced", then later "applied" -- two honest updates, not a
    double-resolution error). Forcing that shape into ``Intent``'s
    single-terminal-state contract would either reject the second honest
    update (spine's ``IntentAlreadyResolved``) or silently overload a module
    that deliberately does not want to become a state machine.

So: a fourth store, but it REUSES spine/ledger.py's proven durability recipe
verbatim (WAL, ``synchronous=NORMAL``, ``busy_timeout``, ``BEGIN IMMEDIATE``,
``foreign_keys=ON``, append-only event-sourced status -- current state derived
from the latest event, full history kept) rather than re-deriving it, and it
reuses ``daedalus.health``'s closed outcome vocabulary verbatim (imported, not
re-declared) rather than inventing a lookalike that could drift.

THE HONESTY CONSTRAINT, made structural
----------------------------------------
``daedalus.health`` distinguishes WORKING / PRESENT / DEGRADED / ABSENT /
UNKNOWN and refuses a sixth word that could render as a pass (see its module
docstring: "no way to collapse them"). A dispatched piece of work is reported
here in exactly that vocabulary -- imported from :mod:`daedalus.health`, not
re-declared -- so "patch produced, not applied" is representable as
``outcome_state=PRESENT, summary="patch produced, not applied"`` and can never
collapse into a bare "done". A turn's own status is a separate, smaller closed
set (:data:`TURN_STATUSES`): ``proposed`` (an action was proposed, gated on
confirmation, per ``ikarus_os._enqueue`` -- nothing has been dispatched yet)
is distinct from ``answered`` (a reply with no side effect) and ``error``. A
turn that is ``proposed`` with no linked dispatch is, honestly, "planned, not
dispatched" -- see :meth:`ConversationStore.resume`, whose narrative is built
ONLY from these closed vocabularies so it cannot say more than the rows prove.

WHAT THIS MODULE DOES NOT DO (stated, not left to be discovered)
--------------------------------------------------------------
It does not feed prior turns back into a model's prompt by itself -- that is
``ikarus_os.py``'s concern (see its use of :func:`recent_turns_context`) and is
opt-in, only active when a caller passes ``conversation_id``. It does not
dispatch anything -- callers who actually enqueue work (file_bridge / web_api,
outside this module's owner) call :meth:`ConversationStore.link_dispatch` at
the moment they dispatch, and :meth:`ConversationStore.record_dispatch_event`
when a report lands. This module has not verified those call sites exist; it
only guarantees the store-side contract they would use.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .health import ABSENT, DEGRADED, PRESENT, STATES as OUTCOME_STATES, UNKNOWN, WORKING

__all__ = [
    "ConversationStore", "Turn", "DispatchLink", "DispatchEvent",
    "ConversationError", "UnknownConversation", "UnknownTurn", "UnknownDispatch",
    "DuplicateDispatchRef", "STATUS_ANSWERED", "STATUS_PROPOSED", "STATUS_ERROR",
    "TURN_STATUSES", "LIFECYCLE_DISPATCHED", "LIFECYCLE_REPORTED",
    "DISPATCH_LIFECYCLE", "OUTCOME_STATES", "WORKING", "PRESENT", "DEGRADED",
    "ABSENT", "UNKNOWN", "new_conversation_id",
    "default_db_path", "default_store", "recent_turns_context",
]

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
SCHEMA_VERSION = 1

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "runs" / "ikarus" / "conversations.sqlite3"

DEFAULT_BUSY_TIMEOUT_MS = 30000

# A turn's own outcome, at the CHAT layer -- distinct from a dispatch's
# outcome (which reuses daedalus.health's vocabulary; see module docstring).
STATUS_ANSWERED = "answered"   # a reply was produced, no side effect proposed
STATUS_PROPOSED = "proposed"   # an action was proposed, gated on confirmation
STATUS_ERROR = "error"         # ask() caught an exception building the reply
TURN_STATUSES = (STATUS_ANSWERED, STATUS_PROPOSED, STATUS_ERROR)

# A dispatch's lifecycle: created (someone actually sent it somewhere), then
# zero or more reports. Deliberately NOT single-resolution like spine's
# Intent (see module docstring) -- a second "reported" event is a legitimate
# honest update ("produced" then later "applied"), not an error to reject.
LIFECYCLE_DISPATCHED = "dispatched"
LIFECYCLE_REPORTED = "reported"
DISPATCH_LIFECYCLE = (LIFECYCLE_DISPATCHED, LIFECYCLE_REPORTED)


class ConversationError(RuntimeError):
    """Base for every refusal this store makes."""


class UnknownConversation(ConversationError):
    pass


class UnknownTurn(ConversationError):
    pass


class UnknownDispatch(ConversationError):
    """No dispatch_link is recorded under that dispatch_ref."""


class DuplicateDispatchRef(ConversationError):
    """dispatch_ref must be unique: it is the key a later report is looked up
    by (mirrors spine.ledger's effect_key discipline -- "the caller supplies
    an identifier it can go and look for afterwards")."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uri_path(path: Path) -> str:
    return (str(path).replace("\\", "/").replace("?", "%3f").replace("#", "%23"))


def default_db_path() -> Path:
    """Where the store lives. ``DAEDALUS_CONVERSATION_DB`` overrides it (tests
    and isolated worktrees point this away from the real runs/ directory) --
    same override convention as ``spine.ledger.default_db_path``."""
    env = os.environ.get("DAEDALUS_CONVERSATION_DB", "").strip()
    return Path(env) if env else DEFAULT_DB_PATH


def new_conversation_id() -> str:
    """A fresh, filename-safe, sortable conversation id. Same house style as
    ``file_bridge._stamp() + uuid4().hex[:8]``: a uuid alone cannot collide and
    needs nobody to look first; the timestamp prefix keeps ids human-sortable
    and readable in a directory listing or a log line."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"conv_{stamp}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# records                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Turn:
    id: int
    conversation_id: str
    seq: int
    created_ts: str
    user_message: str
    intent: str
    status: str
    assistant_text: str | None = None
    provider_used: str | None = None
    model_used: str | None = None
    project: str | None = None
    source: str | None = None
    strategy: str | None = None
    proposed_action: Any = None
    envelope: dict | None = None


@dataclass(frozen=True)
class DispatchLink:
    id: int
    conversation_id: str
    turn_id: int
    dispatch_ref: str
    kind: str
    created_ts: str


@dataclass(frozen=True)
class DispatchEvent:
    id: int
    dispatch_link_id: int
    ts: str
    lifecycle: str
    summary: str
    outcome_state: str | None = None
    detail: Any = None


# --------------------------------------------------------------------------- #
# schema                                                                       #
# --------------------------------------------------------------------------- #
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS conv_meta ("
    " key TEXT PRIMARY KEY,"
    " value TEXT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS conversations ("
    " id TEXT PRIMARY KEY,"
    " created_ts TEXT NOT NULL)",

    "CREATE TABLE IF NOT EXISTS turns ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " conversation_id TEXT NOT NULL REFERENCES conversations(id),"
    " seq INTEGER NOT NULL,"
    " created_ts TEXT NOT NULL,"
    " source TEXT,"
    " strategy TEXT,"
    " project TEXT,"
    " user_message TEXT NOT NULL,"
    " intent TEXT NOT NULL,"
    " assistant_text TEXT,"
    " provider_used TEXT,"
    " model_used TEXT,"
    " status TEXT NOT NULL,"
    " proposed_action TEXT,"
    " envelope TEXT NOT NULL,"
    " UNIQUE(conversation_id, seq))",
    "CREATE INDEX IF NOT EXISTS idx_turns_conversation ON turns(conversation_id, seq)",

    "CREATE TABLE IF NOT EXISTS dispatch_links ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " conversation_id TEXT NOT NULL REFERENCES conversations(id),"
    " turn_id INTEGER NOT NULL REFERENCES turns(id),"
    " dispatch_ref TEXT NOT NULL UNIQUE,"
    " kind TEXT NOT NULL,"
    " created_ts TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_links_turn ON dispatch_links(turn_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_links_conversation"
    " ON dispatch_links(conversation_id)",

    "CREATE TABLE IF NOT EXISTS dispatch_events ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " dispatch_link_id INTEGER NOT NULL REFERENCES dispatch_links(id),"
    " ts TEXT NOT NULL,"
    " lifecycle TEXT NOT NULL,"
    " outcome_state TEXT,"
    " summary TEXT NOT NULL,"
    " detail TEXT)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_events_link"
    " ON dispatch_events(dispatch_link_id, id)",
)


# --------------------------------------------------------------------------- #
# the store                                                                    #
# --------------------------------------------------------------------------- #
class ConversationStore:
    """Crash-safe conversation/turn/dispatch store over one SQLite file.

    Durability settings and the transaction pattern are copied deliberately
    from :class:`daedalus.spine.ledger.SpineLedger` (see that module's
    docstring for the reasoning): ``journal_mode=WAL`` so a committed row
    survives process death, ``synchronous=NORMAL`` as WAL's documented safe
    pairing, ``busy_timeout`` so a second writer waits instead of erroring on
    ``BEGIN IMMEDIATE`` (which takes the write lock up front, so two writers
    never deadlock upgrading a read transaction), ``foreign_keys=ON``.
    """

    def __init__(self, path: str | Path | None = None, *,
                 busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
                 read_only: bool = False) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.read_only = bool(read_only)
        self._lock = threading.RLock()

        if self.read_only:
            uri = f"file:{_uri_path(self.path)}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, isolation_level=None,
                                         check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            self._conn.execute("PRAGMA query_only=ON")
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None,
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._migrate()

    def _apply_pragmas(self) -> None:
        c = self._conn
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        c.execute("PRAGMA foreign_keys=ON")

    def _migrate(self) -> None:
        with self._txn() as c:
            for stmt in _SCHEMA:
                c.execute(stmt)
            c.execute("INSERT OR IGNORE INTO conv_meta (key, value) VALUES (?,?)",
                      ("schema_version", str(SCHEMA_VERSION)))
        found = self.pragmas()
        if found["journal_mode"].lower() != "wal":
            raise ConversationError(
                f"conversation store at {self.path} is in journal_mode="
                f"{found['journal_mode']!r}, not WAL (network filesystem?); "
                f"refusing to run with weaker crash semantics than declared")

    def pragmas(self) -> dict[str, Any]:
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

    @contextmanager
    def _txn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # -- writes: conversations / turns -------------------------------------- #
    def ensure_conversation(self, conversation_id: str) -> None:
        """Idempotent create. Not normally needed directly: :meth:`append_turn`
        creates the conversation row itself on first use, in the same
        transaction as the first turn, so a caller need not sequence two
        calls to start a conversation."""
        conversation_id = _check_id(conversation_id, "conversation_id")
        with self._txn() as c:
            self._ensure_conversation(c, conversation_id)

    @staticmethod
    def _ensure_conversation(c: sqlite3.Connection, conversation_id: str) -> None:
        c.execute("INSERT OR IGNORE INTO conversations (id, created_ts) VALUES (?,?)",
                  (conversation_id, _now_iso()))

    def append_turn(self, conversation_id: str, *, user_message: str, intent: str,
                    status: str, assistant_text: str | None = None,
                    provider_used: str | None = None, model_used: str | None = None,
                    project: str | None = None, source: str | None = None,
                    strategy: str | None = None, proposed_action: Any = None,
                    envelope: dict | None = None) -> Turn:
        """Append one durable turn and COMMIT it. Creates the conversation row
        on first use. ``seq`` is assigned here (``MAX(seq)+1`` inside the same
        ``BEGIN IMMEDIATE`` transaction as the insert), never supplied by the
        caller, so it stays gap-free and monotonic even under concurrent
        callers on the same conversation."""
        conversation_id = _check_id(conversation_id, "conversation_id")
        if status not in TURN_STATUSES:
            raise ValueError(f"status must be one of {TURN_STATUSES!r}, got {status!r}")
        user_message = str(user_message or "")
        intent = str(intent or "chat")
        envelope_json = json.dumps(envelope if envelope is not None else {},
                                   ensure_ascii=False, default=str)
        action_json = (None if proposed_action is None else
                       json.dumps(proposed_action, ensure_ascii=False, default=str))
        ts = _now_iso()
        with self._txn() as c:
            self._ensure_conversation(c, conversation_id)
            row = c.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM turns WHERE conversation_id = ?",
                (conversation_id,)).fetchone()
            seq = int(row[0])
            cur = c.execute(
                "INSERT INTO turns (conversation_id, seq, created_ts, source, "
                " strategy, project, user_message, intent, assistant_text, "
                " provider_used, model_used, status, proposed_action, envelope)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (conversation_id, seq, ts, source, strategy, project, user_message,
                 intent, assistant_text, provider_used, model_used, status,
                 action_json, envelope_json))
            turn_id = int(cur.lastrowid)
        return Turn(id=turn_id, conversation_id=conversation_id, seq=seq,
                   created_ts=ts, user_message=user_message, intent=intent,
                   status=status, assistant_text=assistant_text,
                   provider_used=provider_used, model_used=model_used,
                   project=project, source=source, strategy=strategy,
                   proposed_action=proposed_action,
                   envelope=envelope if envelope is not None else {})

    # -- reads: conversations / turns ---------------------------------------- #
    def turns(self, conversation_id: str, *, limit: int | None = None) -> list[Turn]:
        """Turns oldest-first (replay order). ``limit`` returns the MOST
        RECENT ``limit`` turns, still oldest-first -- "tail -n" semantics, the
        shape a caller building prompt context or a UI scrollback wants."""
        conversation_id = _check_id(conversation_id, "conversation_id")
        with self._lock:
            if limit is None:
                rows = self._conn.execute(
                    "SELECT * FROM turns WHERE conversation_id = ? ORDER BY seq",
                    (conversation_id,)).fetchall()
            else:
                if int(limit) <= 0:
                    return []
                rows = self._conn.execute(
                    "SELECT * FROM turns WHERE conversation_id = ?"
                    " ORDER BY seq DESC LIMIT ?", (conversation_id, int(limit))
                ).fetchall()
                rows = list(reversed(rows))
        return [_row_to_turn(r) for r in rows]

    def get_turn(self, turn_id: int) -> Turn | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM turns WHERE id = ?", (int(turn_id),)).fetchone()
        return None if row is None else _row_to_turn(row)

    def last_turn(self, conversation_id: str) -> Turn | None:
        conversation_id = _check_id(conversation_id, "conversation_id")
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM turns WHERE conversation_id = ?"
                " ORDER BY seq DESC LIMIT 1", (conversation_id,)).fetchone()
        return None if row is None else _row_to_turn(row)

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (str(conversation_id),)).fetchone()
        return row is not None

    # -- writes: dispatch attribution ---------------------------------------- #
    def link_dispatch(self, conversation_id: str, dispatch_ref: str, *,
                      turn_id: int | None = None, kind: str = "dispatch",
                      summary: str = "dispatched", detail: Any = None) -> DispatchLink:
        """Record that a turn caused work to be dispatched. ``dispatch_ref`` is
        an OPAQUE, caller-supplied key (an outbox filename stem, a spine
        intent id, anything the dispatcher can go look for later) -- same
        after-the-fact-identification idea as ``spine.ledger``'s
        ``effect_key``. Must be unique: it is how a later report is found.

        ``turn_id`` defaults to the conversation's most recent turn when not
        given, so a caller that has not yet threaded turn ids through its own
        protocol can still link correctly in the common case.
        """
        conversation_id = _check_id(conversation_id, "conversation_id")
        dispatch_ref = str(dispatch_ref or "").strip()
        if not dispatch_ref:
            raise ValueError("dispatch_ref must be a non-empty string")
        ts = _now_iso()
        detail_json = None if detail is None else json.dumps(detail, ensure_ascii=False, default=str)
        with self._txn() as c:
            if not self._conn_has_conversation(c, conversation_id):
                raise UnknownConversation(conversation_id)
            resolved_turn_id = turn_id
            if resolved_turn_id is None:
                row = c.execute(
                    "SELECT id FROM turns WHERE conversation_id = ?"
                    " ORDER BY seq DESC LIMIT 1", (conversation_id,)).fetchone()
                if row is None:
                    raise UnknownTurn(
                        f"conversation {conversation_id!r} has no turns to link a "
                        f"dispatch to")
                resolved_turn_id = int(row["id"])
            else:
                row = c.execute(
                    "SELECT id FROM turns WHERE id = ? AND conversation_id = ?",
                    (int(resolved_turn_id), conversation_id)).fetchone()
                if row is None:
                    raise UnknownTurn(
                        f"turn {resolved_turn_id} does not belong to conversation "
                        f"{conversation_id!r}")
            try:
                cur = c.execute(
                    "INSERT INTO dispatch_links (conversation_id, turn_id, "
                    " dispatch_ref, kind, created_ts) VALUES (?,?,?,?,?)",
                    (conversation_id, resolved_turn_id, dispatch_ref, str(kind), ts))
            except sqlite3.IntegrityError as exc:
                raise DuplicateDispatchRef(
                    f"dispatch_ref {dispatch_ref!r} is already linked: a "
                    f"dispatch_ref must be unique because it is the key a "
                    f"later report is looked up by") from exc
            link_id = int(cur.lastrowid)
            c.execute(
                "INSERT INTO dispatch_events (dispatch_link_id, ts, lifecycle, "
                " outcome_state, summary, detail) VALUES (?,?,?,?,?,?)",
                (link_id, ts, LIFECYCLE_DISPATCHED, None, str(summary), detail_json))
        return DispatchLink(id=link_id, conversation_id=conversation_id,
                           turn_id=resolved_turn_id, dispatch_ref=dispatch_ref,
                           kind=str(kind), created_ts=ts)

    @staticmethod
    def _conn_has_conversation(c: sqlite3.Connection, conversation_id: str) -> bool:
        return c.execute("SELECT 1 FROM conversations WHERE id = ?",
                         (conversation_id,)).fetchone() is not None

    def record_dispatch_event(self, dispatch_ref: str, *, outcome_state: str,
                              summary: str, detail: Any = None) -> DispatchEvent:
        """Append a report against an existing dispatch. NOT single-resolution
        (see module docstring): a second, third, ... report is a legitimate
        honest update, not an error. ``outcome_state`` must be one of
        :data:`daedalus.health.STATES` -- imported, not re-declared, so this
        can never drift from the repo's one closed vocabulary for "did it
        actually work".
        """
        if outcome_state not in OUTCOME_STATES:
            raise ValueError(
                f"outcome_state must be one of {OUTCOME_STATES!r} (from "
                f"daedalus.health), got {outcome_state!r}")
        summary = str(summary or "").strip()
        if not summary:
            raise ValueError(
                "record_dispatch_event requires a non-empty summary -- an "
                "outcome with no explanation is the collapse this module "
                "exists to prevent")
        dispatch_ref = str(dispatch_ref or "")
        ts = _now_iso()
        detail_json = None if detail is None else json.dumps(detail, ensure_ascii=False, default=str)
        with self._txn() as c:
            row = c.execute(
                "SELECT id FROM dispatch_links WHERE dispatch_ref = ?",
                (dispatch_ref,)).fetchone()
            if row is None:
                raise UnknownDispatch(
                    f"no dispatch is linked under dispatch_ref {dispatch_ref!r} -- "
                    f"call link_dispatch() at the point the work was actually sent")
            link_id = int(row["id"])
            cur = c.execute(
                "INSERT INTO dispatch_events (dispatch_link_id, ts, lifecycle, "
                " outcome_state, summary, detail) VALUES (?,?,?,?,?,?)",
                (link_id, ts, LIFECYCLE_REPORTED, outcome_state, summary, detail_json))
            event_id = int(cur.lastrowid)
        return DispatchEvent(id=event_id, dispatch_link_id=link_id, ts=ts,
                            lifecycle=LIFECYCLE_REPORTED, summary=summary,
                            outcome_state=outcome_state, detail=detail)

    # -- reads: dispatch attribution ------------------------------------------ #
    def dispatch_events(self, dispatch_ref: str) -> list[DispatchEvent]:
        """Full append-only event history for one dispatch, oldest first."""
        with self._lock:
            link = self._conn.execute(
                "SELECT id FROM dispatch_links WHERE dispatch_ref = ?",
                (str(dispatch_ref),)).fetchone()
            if link is None:
                return []
            rows = self._conn.execute(
                "SELECT * FROM dispatch_events WHERE dispatch_link_id = ? ORDER BY id",
                (int(link["id"]),)).fetchall()
        return [_row_to_event(r) for r in rows]

    def dispatch_status(self, dispatch_ref: str) -> dict[str, Any] | None:
        """``{link, events, latest}`` for one dispatch_ref, or ``None`` when no
        such dispatch is recorded. ``latest`` is the current truth; ``events``
        is the full history so a caller can show "produced, then applied"
        rather than only the newest word."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM dispatch_links WHERE dispatch_ref = ?",
                (str(dispatch_ref),)).fetchone()
            if row is None:
                return None
            link = _row_to_link(row)
        events = self.dispatch_events(dispatch_ref)
        return {"link": link, "events": events, "latest": events[-1] if events else None}

    def open_dispatches(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        """Dispatches whose latest event is still ``dispatched`` (no report
        has landed yet) -- the crash-recovery / "what is still in flight"
        worklist, mirroring ``spine.ledger.open_intents``. Each item is
        ``{link, latest}``."""
        with self._lock:
            if conversation_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM dispatch_links ORDER BY id").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM dispatch_links WHERE conversation_id = ? ORDER BY id",
                    (str(conversation_id),)).fetchall()
        out = []
        for row in rows:
            link = _row_to_link(row)
            events = self.dispatch_events(link.dispatch_ref)
            latest = events[-1] if events else None
            if latest is not None and latest.lifecycle == LIFECYCLE_DISPATCHED:
                out.append({"link": link, "latest": latest})
        return out

    # -- resumability ---------------------------------------------------------- #
    def resume(self, conversation_id: str) -> dict[str, Any]:
        """The honest answer to "what was I doing", reconstructed entirely
        from durable rows. ``narrative`` is built only from the closed
        vocabularies (:data:`TURN_STATUSES`, dispatch lifecycle, and
        ``daedalus.health.STATES``) so it cannot claim more than the rows
        prove -- it will say "planned, not dispatched", never "done", for a
        proposed action with no linked dispatch.
        """
        conversation_id = _check_id(conversation_id, "conversation_id")
        turns = self.turns(conversation_id)
        last = turns[-1] if turns else None
        with self._lock:
            link_rows = self._conn.execute(
                "SELECT * FROM dispatch_links WHERE conversation_id = ? ORDER BY id",
                (conversation_id,)).fetchall()
        links = [_row_to_link(r) for r in link_rows]
        by_turn: dict[int, list[DispatchLink]] = {}
        for link in links:
            by_turn.setdefault(link.turn_id, []).append(link)

        dispatch_summaries = []
        for link in links:
            events = self.dispatch_events(link.dispatch_ref)
            latest = events[-1] if events else None
            dispatch_summaries.append({"link": link, "latest": latest})

        narrative = _narrate(conversation_id, turns, last,
                             by_turn.get(last.id, []) if last else [],
                             dispatch_summaries)
        return {
            "conversation_id": conversation_id,
            "exists": self.conversation_exists(conversation_id),
            "turn_count": len(turns),
            "last_turn": last,
            "dispatches": dispatch_summaries,
            "open_dispatches": [d for d in dispatch_summaries
                               if d["latest"] is not None
                               and d["latest"].lifecycle == LIFECYCLE_DISPATCHED],
            "narrative": narrative,
        }

    # -- lifecycle -------------------------------------------------------------- #
    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "ConversationStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# --------------------------------------------------------------------------- #
# narrative -- honest, closed-vocabulary-only prose                            #
# --------------------------------------------------------------------------- #
def _narrate(conversation_id: str, turns: list[Turn], last: Turn | None,
            last_turn_links: list[DispatchLink],
            dispatch_summaries: list[dict[str, Any]]) -> list[str]:
    if last is None:
        return [f"No turns recorded for conversation {conversation_id}."]
    lines: list[str] = []
    if last.status == STATUS_ERROR:
        lines.append(f"Turn {last.seq} hit an error: {last.assistant_text or 'no detail recorded'}.")
    elif last.status == STATUS_PROPOSED:
        kind = None
        if isinstance(last.proposed_action, dict):
            kind = last.proposed_action.get("kind")
        tag = f" ({kind})" if kind else ""
        if not last_turn_links:
            lines.append(
                f"Turn {last.seq} proposed an action{tag} awaiting confirmation; "
                f"nothing has been dispatched.")
        else:
            # Proposed AND acted on: do not say "answered directly" (it wasn't
            # a plain reply) and do not say "done" (the per-dispatch lines
            # below carry the actual, possibly non-terminal, outcome).
            lines.append(
                f"Turn {last.seq} proposed an action{tag} that was dispatched; "
                f"see below for its reported status.")
    else:
        lines.append(f"Turn {last.seq} answered directly (intent={last.intent}).")

    for d in dispatch_summaries:
        link, latest = d["link"], d["latest"]
        if latest is None:
            continue
        if latest.lifecycle == LIFECYCLE_DISPATCHED:
            lines.append(
                f"Turn {link.turn_id}'s dispatch (ref={link.dispatch_ref}, "
                f"kind={link.kind}) is still awaiting a report.")
        else:
            lines.append(
                f"Turn {link.turn_id}'s dispatch (ref={link.dispatch_ref}) "
                f"reported {latest.outcome_state}: {latest.summary}.")
    return lines


# --------------------------------------------------------------------------- #
# prompt-context helper (opt-in; see module docstring)                         #
# --------------------------------------------------------------------------- #
def recent_turns_context(store: "ConversationStore", conversation_id: str,
                         *, max_turns: int = 6, max_chars: int = 4000) -> str:
    """Render the last ``max_turns`` turns as a compact transcript block, for a
    caller that wants prior turns to inform the NEXT model call. Returns ``""``
    when there is no history (byte-identical to "no context" for a caller that
    conditionally prepends this). Bounded by ``max_chars`` from the END (most
    recent turns kept whole) so one long-running conversation cannot blow up a
    prompt budget silently.
    """
    turns = store.turns(conversation_id, limit=max_turns)
    if not turns:
        return ""
    lines = []
    for t in turns:
        lines.append(f"User: {t.user_message}")
        if t.assistant_text:
            lines.append(f"Assistant: {t.assistant_text}")
    block = "\n".join(lines)
    if len(block) > max_chars:
        block = block[-max_chars:]
        nl = block.find("\n")
        if nl != -1:
            block = block[nl + 1:]
    return block


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _check_id(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _row_to_turn(row: sqlite3.Row) -> Turn:
    action = row["proposed_action"]
    envelope = row["envelope"]
    return Turn(
        id=int(row["id"]), conversation_id=row["conversation_id"], seq=int(row["seq"]),
        created_ts=row["created_ts"], user_message=row["user_message"],
        intent=row["intent"], status=row["status"],
        assistant_text=row["assistant_text"], provider_used=row["provider_used"],
        model_used=row["model_used"], project=row["project"], source=row["source"],
        strategy=row["strategy"],
        proposed_action=(None if action is None else json.loads(action)),
        envelope=(json.loads(envelope) if envelope else {}),
    )


def _row_to_link(row: sqlite3.Row) -> DispatchLink:
    return DispatchLink(id=int(row["id"]), conversation_id=row["conversation_id"],
                        turn_id=int(row["turn_id"]), dispatch_ref=row["dispatch_ref"],
                        kind=row["kind"], created_ts=row["created_ts"])


def _row_to_event(row: sqlite3.Row) -> DispatchEvent:
    detail = row["detail"]
    return DispatchEvent(id=int(row["id"]), dispatch_link_id=int(row["dispatch_link_id"]),
                         ts=row["ts"], lifecycle=row["lifecycle"],
                         outcome_state=row["outcome_state"], summary=row["summary"],
                         detail=(None if detail is None else json.loads(detail)))


# --------------------------------------------------------------------------- #
# process-wide default store, cached per resolved path                        #
# --------------------------------------------------------------------------- #
_STORE_CACHE: dict[str, ConversationStore] = {}
_STORE_CACHE_LOCK = threading.Lock()


def default_store() -> ConversationStore:
    """A shared :class:`ConversationStore` for :data:`default_db_path`'s
    current value, opened once per resolved path and reused. Keyed by path
    (not a bare singleton) so a test that points ``DAEDALUS_CONVERSATION_DB``
    at a fresh temp file before its first call gets an isolated store, with no
    reset hook needed between tests."""
    path = str(default_db_path())
    with _STORE_CACHE_LOCK:
        store = _STORE_CACHE.get(path)
        if store is None:
            store = ConversationStore(path)
            _STORE_CACHE[path] = store
        return store
