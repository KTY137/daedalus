"""conversation.py -- the chat seam's READ/WRITE FACADE over the canonical spine.

WHAT THIS IS. ``daedalus/ikarus_os.py`` is the assistant seam: ``ask()`` /
``ask_stream()`` classify one message, route it to a deterministic intent or a
freeform brain, and return a chat envelope (see :func:`daedalus.core.envelope`).
Every call is otherwise stateless. This module is the missing piece: a
conversation has an id, turns are appended durably, the assistant can be resumed
after a restart and know what it was doing, and work dispatched because of a
turn is linked back to it so a report arriving later attributes to the request
that caused it.

IT IS NOT A STORE. It owns no database, no schema and no file. Every write here
is a typed intent on :class:`daedalus.spine.ledger.SpineLedger`, the
repository's single canonical Event Store (see
``daedalus/kernel/promotion_execution.py``'s module docstring, which names it as
such, and ``daedalus/kernel/attempt_ledger.py``, the facade this one is shaped
after). Three kinds carry everything:

  * ``conversation.turn`` -- one recorded chat turn. ``effect_key`` is
    ``conversation:<conversation_id>``, so every turn of one conversation shares
    one indexed key and a conversation's history is a single indexed read.
  * ``conversation.dispatch`` -- work dispatched because of a turn.
    ``effect_key`` is the caller's opaque ``dispatch_ref``, unique within this
    kind (a partial unique index, installed the way ``attempt_ledger`` installs
    its own).
  * ``conversation.dispatch.report`` -- one honest update about a dispatch.
    ``effect_key`` is the same ``dispatch_ref``, deliberately NOT unique: a
    second report ("produced", then later "applied") is a legitimate update.
    A caller projecting an already durable external event may additionally
    supply its stable ``source_event_id``. Replaying that SAME source event is
    idempotent; a genuinely later event still gets its own row and identity.

WHY THE FOURTH LOG IS GONE
--------------------------
This module used to open its own SQLite file at ``runs/ikarus/conversations
.sqlite3``, and its own docstring argued the case for it: a turn is not one
intent with one terminal resolution, so forcing it into ``Intent``'s
single-terminal contract would either reject an honest second update or push the
spine into becoming a state machine it declines to be. That argument was right
about the shape and wrong about the conclusion -- it consolidated the fields but
forked the event spine, which Invariant 1 does not allow.

The shape objection dissolves once the three kinds above are separated. A turn
and a dispatch are both facts: by the time either is recorded the reply has
already been produced and the work has already been queued (``web_api`` calls
``core.queue_task`` FIRST and links afterwards), so neither has a
decided-but-not-yet-done window to protect and both are written with
:meth:`SpineLedger.record_fact` -- terminal at birth, in one transaction. A
report is then simply another fact carrying the same ``dispatch_ref``, so N
distinct reports are N rows and nothing is ever asked to resolve twice. A
crash replay of one stable ``source_event_id`` returns its existing row; it is
not a distinct report.

That choice is load-bearing beyond tidiness: an intent left INTENDED shows up in
``SpineLedger.open_intents`` -- the crash-recovery worklist -- and in
``health``'s stale-open probe, which calls an hour-old unresolved intent
DEGRADED. Chat traffic recorded as open intents would have made both readings
meaningless. Nothing this module writes is ever open.

WHAT IT STILL REFUSES TO BE
---------------------------
Chat is an interface, not orchestration state. Nothing here decides anything: a
dispatch's LIVE truth is the file bus (see ``web_api._task_snapshot``), and the
rows here are attribution and narrative only. ``open_dispatches`` is derived --
a dispatch with no report yet -- and is a display of what has not been heard
from, never an instruction to redo it.

THE HONESTY CONSTRAINT, made structural
----------------------------------------
``daedalus.health`` distinguishes WORKING / PRESENT / DEGRADED / ABSENT /
UNKNOWN and refuses a sixth word that could render as a pass. A dispatched piece
of work is reported here in exactly that vocabulary. Both surfaces re-export
the one :mod:`daedalus.kernel.contracts.observations` contract rather than
declaring parallel copies -- so "patch produced, not applied" is
representable as ``outcome_state=PRESENT, summary="patch produced, not
applied"`` and can never collapse into a bare "done". A turn's own status is a
separate, smaller closed set (:data:`TURN_STATUSES`): ``proposed`` (an action
was proposed, gated on confirmation, per ``ikarus_os._enqueue``) is distinct
from ``answered`` (a reply with no side effect) and ``error``. A turn that is
``proposed`` with no linked dispatch is, honestly, "planned, not dispatched" --
see :meth:`ConversationStore.resume`, whose narrative is built ONLY from these
closed vocabularies so it cannot say more than the rows prove.

SEQUENCE NUMBERS ARE DERIVED, NOT STORED
----------------------------------------
``Turn.seq`` is this turn's position among its conversation's turns, computed by
:meth:`SpineLedger.ordinal_by_effect` as a COUNT of committed rows below a known
intent id. The old store assigned it as ``MAX(seq)+1`` inside the insert's own
transaction; deriving it is the same guarantee without the write lock, and it is
still exact under the threaded HTTP server (two racing writers get two ids, and
each counts the other in or out by that id). A derived position also cannot
disagree with the durable order the way a stored one can.

WHAT THIS MODULE DOES NOT DO (stated, not left to be discovered)
--------------------------------------------------------------
It does not feed prior turns back into a model's prompt by itself -- that is
``ikarus_os.py``'s concern and is opt-in, only active when a caller passes
``conversation_id``. It does not dispatch anything: callers who actually enqueue
work call :meth:`ConversationStore.link_dispatch` at the moment they dispatch,
and :meth:`ConversationStore.record_dispatch_event` when a report lands. There
is no separate "create a conversation" write and never was one worth keeping:
the first :meth:`ConversationStore.append_turn` is what makes a conversation
exist, and a conversation with no turns does not exist.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kernel.contracts.observations import (
    ABSENT,
    DEGRADED,
    OBSERVATION_STATES as OUTCOME_STATES,
    PRESENT,
    UNKNOWN,
    WORKING,
)
from .spine.durability import open_gate0_spine_writer
from .spine.ledger import (
    DEFAULT_BUSY_TIMEOUT_MS,
    Intent,
    SpineLedger,
    default_db_path as spine_db_path,
)

__all__ = [
    "ConversationStore", "Turn", "DispatchLink", "DispatchEvent",
    "ConversationError", "UnknownConversation", "UnknownTurn", "UnknownDispatch",
    "DuplicateDispatchRef", "ConflictingDispatchEvent", "STATUS_ANSWERED",
    "STATUS_PROPOSED", "STATUS_ERROR",
    "TURN_STATUSES", "LIFECYCLE_DISPATCHED", "LIFECYCLE_REPORTED",
    "DISPATCH_LIFECYCLE", "OUTCOME_STATES", "WORKING", "PRESENT", "DEGRADED",
    "ABSENT", "UNKNOWN", "new_conversation_id",
    "KIND_TURN", "KIND_DISPATCH", "KIND_REPORT", "CONVERSATION_KINDS",
    "conversation_effect_key",
    "default_db_path", "default_store", "recent_turns_context",
]

# --------------------------------------------------------------------------- #
# constants                                                                    #
# --------------------------------------------------------------------------- #
#: The three canonical-spine intent kinds this module writes. Nothing else in
#: the tree writes them, and this module writes nothing else.
KIND_TURN = "conversation.turn"
KIND_DISPATCH = "conversation.dispatch"
KIND_REPORT = "conversation.dispatch.report"
CONVERSATION_KINDS = (KIND_TURN, KIND_DISPATCH, KIND_REPORT)

# A turn's own outcome, at the CHAT layer -- distinct from a dispatch's
# outcome (which reuses daedalus.health's vocabulary; see module docstring).
STATUS_ANSWERED = "answered"   # a reply was produced, no side effect proposed
STATUS_PROPOSED = "proposed"   # an action was proposed, gated on confirmation
STATUS_ERROR = "error"         # ask() caught an exception building the reply
TURN_STATUSES = (STATUS_ANSWERED, STATUS_PROPOSED, STATUS_ERROR)

# A dispatch's lifecycle: created (someone actually sent it somewhere), then
# zero or more reports. Deliberately NOT single-resolution -- a second
# "reported" event is a legitimate honest update ("produced" then later
# "applied"), not an error to reject. Each one is its own KIND_REPORT fact, so
# the spine is never asked to resolve anything twice.
LIFECYCLE_DISPATCHED = "dispatched"
LIFECYCLE_REPORTED = "reported"
DISPATCH_LIFECYCLE = (LIFECYCLE_DISPATCHED, LIFECYCLE_REPORTED)


class ConversationError(RuntimeError):
    """Base for every refusal this facade makes."""


class UnknownConversation(ConversationError):
    pass


class UnknownTurn(ConversationError):
    pass


class UnknownDispatch(ConversationError):
    """No dispatch is recorded under that dispatch_ref."""


class DuplicateDispatchRef(ConversationError):
    """dispatch_ref must be unique within ``conversation.dispatch``: it is the
    key a later report is looked up by (the spine's own effect_key discipline --
    "the caller supplies an identifier it can go and look for afterwards")."""


class ConflictingDispatchEvent(ConversationError):
    """One stable source-event identity was reused for different facts.

    Treating the second payload as a retry would silently discard a real
    disagreement; appending it would destroy exactly-once projection. Refuse
    both interpretations and leave the first canonical fact untouched.
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    """Where the records live: the canonical spine ledger, and nowhere else.

    Kept as a name because callers and status readers ask this module where its
    state is. The answer is now :func:`daedalus.spine.ledger.default_db_path`
    verbatim -- including its ``DAEDALUS_SPINE_DB`` override, which is what
    tests and isolated worktrees now point at. The old private
    ``DAEDALUS_CONVERSATION_DB`` override and the file it named
    (``runs/ikarus/conversations.sqlite3``) are gone: a second override would be
    a second way to fork the event spine, which is the defect this module was
    consolidated to remove.
    """
    return spine_db_path()


def conversation_effect_key(conversation_id: str) -> str:
    """The indexed spine key every turn of one conversation shares."""
    return f"conversation:{_check_id(conversation_id, 'conversation_id')}"


def new_conversation_id() -> str:
    """A fresh, filename-safe, sortable conversation id. Same house style as
    ``file_bridge._stamp() + uuid4().hex[:8]``: a uuid alone cannot collide and
    needs nobody to look first; the timestamp prefix keeps ids human-sortable
    and readable in a directory listing or a log line."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"conv_{stamp}_{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# records -- unchanged shapes, now projections of spine intents                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Turn:
    """One ``conversation.turn`` intent, read back.

    ``id`` is the spine intent id (globally unique, not a per-conversation
    rowid); ``seq`` is the derived 0-based position within the conversation.
    """
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
    """One ``conversation.dispatch`` intent, read back. ``turn_id`` is the spine
    intent id of the turn that caused it."""
    id: int
    conversation_id: str
    turn_id: int
    dispatch_ref: str
    kind: str
    created_ts: str


@dataclass(frozen=True)
class DispatchEvent:
    """One point on a dispatch's timeline.

    The ``dispatched`` event is DERIVED from the dispatch intent itself (there
    is no separate row for it: the intent's own existence is the event).
    Every ``reported`` event is one ``conversation.dispatch.report`` intent.
    """
    id: int
    dispatch_link_id: int
    ts: str
    lifecycle: str
    summary: str
    outcome_state: str | None = None
    detail: Any = None
    source_event_id: str | None = None


# --------------------------------------------------------------------------- #
# the facade                                                                   #
# --------------------------------------------------------------------------- #
class ConversationStore:
    """Conversation/turn/dispatch facade over the single canonical event spine.

    Accepts a path (opens its own :class:`SpineLedger`) or an already-open
    ``SpineLedger`` to share, the same two-way constructor
    ``kernel.attempt_ledger.AttemptLedger`` takes -- so a caller that already
    holds the spine does not open a second connection to the same file.

    Durability is not re-derived here and cannot drift: it is whatever the
    canonical ledger enforces (WAL, ``synchronous=NORMAL``, ``busy_timeout``,
    ``BEGIN IMMEDIATE``, ``foreign_keys=ON``), asserted by that module's own
    migration check.
    """

    def __init__(self, path: str | Path | SpineLedger | None = None, *,
                 busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
                 read_only: bool = False) -> None:
        self._owns_spine = not isinstance(path, SpineLedger)
        if isinstance(path, SpineLedger):
            self.spine: SpineLedger = path
        elif read_only:
            # A reader opens no writer and migrates nothing, so it is not a
            # Gate-0 writer seam; the inventory classifies this site `read_only`
            # and does not block on it.
            self.spine = SpineLedger(path, busy_timeout_ms=busy_timeout_ms,
                                     read_only=True)
        else:
            # THE GATE-0 WRITER SEAM. The durability factory is the only
            # sanctioned way to OPEN a writable Event Store (WAL +
            # synchronous=FULL with a machine readback, fail-closed), exactly as
            # `spine.attempt.TaskAttempt._get_ledger` does it.
            #
            # HERACLES 2026-08-24. This branch was one `SpineLedger(path, ...,
            # read_only=read_only)` call covering both cases, and it came in with
            # the conversation-to-spine consolidation (83e41fcc). Because
            # `read_only` was a NAME and not a boolean constant, the writer
            # inventory could not tell a reader from a writer and classified the
            # site `ambiguous_direct` -- a blocker on
            # `scan_event_store_writers`, which the gate report's
            # `event_store_writer_failures` field binds. Splitting the branch is
            # what makes the two cases separately legible; routing the writer
            # half through the factory is what makes it admitted.
            #
            # `None` resolves to the same default path a bare `SpineLedger()`
            # used, so nothing about where the file lives changes.
            self.spine = open_gate0_spine_writer(path, busy_timeout_ms=busy_timeout_ms)
        self.path = self.spine.path
        self.busy_timeout_ms = self.spine.busy_timeout_ms
        self.read_only = bool(getattr(self.spine, "read_only", read_only))
        if not self.read_only:
            self._install_uniqueness_guards()

    def _install_uniqueness_guards(self) -> None:
        """Enforce caller-owned identities in SQLite, never with check-then-use.

        A dispatch ref names one dispatch. A non-null report
        ``source_event_id`` names one already durable external event. The
        latter is deliberately optional: callers without a source identity
        retain the existing append-many timeline semantics.

        Installed through the ledger's own transaction seam rather than a second
        connection, for the reason ``attempt_ledger`` gives for the same move: a
        separate connection carries its own pragmas and could apply weaker
        durability to a write against the canonical file.

        Both indexes are partial. Reports deliberately reuse their dispatch's
        effect key, and source-less reports may repeat; a whole-table or whole-
        kind constraint would forbid the honest later updates this design
        exists to allow.
        """
        try:
            with self.spine._txn() as connection:
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_conversation_dispatch_ref "
                    "ON intents(effect_key) "
                    f"WHERE kind = '{KIND_DISPATCH}'")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_conversation_report_source_event "
                    "ON intents(json_extract(payload, '$.source_event_id')) "
                    f"WHERE kind = '{KIND_REPORT}' "
                    "AND json_extract(payload, '$.source_event_id') IS NOT NULL")
        except (sqlite3.DatabaseError, AttributeError) as exc:
            raise ConversationError(
                "the canonical event spine cannot enforce conversation event "
                f"identities: {type(exc).__name__}: {exc}") from exc

    def pragmas(self) -> dict[str, Any]:
        """The canonical ledger's durability settings, verbatim."""
        return self.spine.pragmas()

    # -- writes: turns ------------------------------------------------------- #
    def append_turn(self, conversation_id: str, *, user_message: str, intent: str,
                    status: str, assistant_text: str | None = None,
                    provider_used: str | None = None, model_used: str | None = None,
                    project: str | None = None, source: str | None = None,
                    strategy: str | None = None, proposed_action: Any = None,
                    envelope: dict | None = None) -> Turn:
        """Append one durable turn and COMMIT it, as a ``conversation.turn``
        fact on the canonical spine.

        A conversation needs no prior creation step: the first turn is what
        makes it exist. ``seq`` is assigned by derivation, never by the caller,
        and stays gap-free and monotonic under concurrent callers on the same
        conversation (see the module docstring).
        """
        key = conversation_effect_key(conversation_id)
        conversation_id = str(conversation_id).strip()
        if status not in TURN_STATUSES:
            raise ValueError(f"status must be one of {TURN_STATUSES!r}, got {status!r}")
        payload = {
            "conversation_id": conversation_id,
            "user_message": str(user_message or ""),
            "intent": str(intent or "chat"),
            "status": status,
            "assistant_text": assistant_text,
            "provider_used": provider_used,
            "model_used": model_used,
            "project": project,
            "source": source,
            "strategy": strategy,
            "proposed_action": _jsonable(proposed_action),
            "envelope": _jsonable(envelope if envelope is not None else {}),
        }
        recorded = self.spine.record_fact(
            KIND_TURN, payload, effect_key=key, effect_id=conversation_id,
            result={"status": status, "intent": payload["intent"]})
        seq = self.spine.ordinal_by_effect(key, recorded.id, kind=KIND_TURN)
        return _turn_from_intent(recorded, seq)

    # -- reads: turns -------------------------------------------------------- #
    def turns(self, conversation_id: str, *, limit: int | None = None) -> list[Turn]:
        """Turns oldest-first (replay order). ``limit`` returns the MOST
        RECENT ``limit`` turns, still oldest-first -- "tail -n" semantics, the
        shape a caller building prompt context or a UI scrollback wants, and
        the reason the bounded spine read exists: the tail must not cost the
        whole conversation."""
        key = conversation_effect_key(conversation_id)
        if limit is None:
            intents = self.spine.intents_by_effect_key(key, kind=KIND_TURN)
            base = 0
        else:
            if int(limit) <= 0:
                return []
            intents = list(reversed(self.spine.intents_by_effect_key(
                key, kind=KIND_TURN, limit=int(limit), newest_first=True)))
            if not intents:
                return []
            base = self.spine.ordinal_by_effect(key, intents[0].id, kind=KIND_TURN)
        return [_turn_from_intent(i, base + offset)
                for offset, i in enumerate(intents)]

    def get_turn(self, turn_id: int) -> Turn | None:
        """One turn by its spine intent id, or ``None``. An id that names an
        intent of another kind is ``None`` too, not a mis-decoded turn."""
        intent = self.spine.get(int(turn_id))
        if intent is None or intent.kind != KIND_TURN:
            return None
        seq = self.spine.ordinal_by_effect(
            intent.effect_key or "", intent.id, kind=KIND_TURN)
        return _turn_from_intent(intent, seq)

    def last_turn(self, conversation_id: str) -> Turn | None:
        key = conversation_effect_key(conversation_id)
        newest = self.spine.intents_by_effect_key(
            key, kind=KIND_TURN, limit=1, newest_first=True)
        if not newest:
            return None
        seq = self.spine.ordinal_by_effect(key, newest[0].id, kind=KIND_TURN)
        return _turn_from_intent(newest[0], seq)

    def conversation_exists(self, conversation_id: str) -> bool:
        """True once at least one turn has been appended. There is no other
        kind of existence: nothing writes a conversation without a turn."""
        try:
            key = conversation_effect_key(conversation_id)
        except ValueError:
            return False
        return bool(self.spine.intents_by_effect_key(
            key, kind=KIND_TURN, limit=1, newest_first=True))

    # -- writes: dispatch attribution ---------------------------------------- #
    def link_dispatch(self, conversation_id: str, dispatch_ref: str, *,
                      turn_id: int | None = None, kind: str = "dispatch",
                      summary: str = "dispatched", detail: Any = None) -> DispatchLink:
        """Record that a turn caused work to be dispatched. ``dispatch_ref`` is
        an OPAQUE, caller-supplied key (an outbox filename stem, a spine intent
        id, anything the dispatcher can go look for later) and becomes the
        intent's ``effect_key``. Must be unique within ``conversation.dispatch``:
        it is how a later report is found.

        ``turn_id`` defaults to the conversation's most recent turn when not
        given, so a caller that has not yet threaded turn ids through its own
        protocol can still link correctly in the common case.

        Recorded as a FACT, not an open intent: every caller in this tree queues
        the work first and links afterwards, so there is no window to protect --
        and an unreported dispatch left INTENDED would incorrectly sit in the
        spine's crash-recovery worklist even though the dispatch itself already
        happened. ``file_bridge.process_request`` now projects a later terminal
        report as its own idempotent FACT; it does not resolve or redo this
        attribution row, and a report that never arrives must not turn chat
        linkage into orchestration recovery state.
        """
        conversation_id = _check_id(conversation_id, "conversation_id")
        dispatch_ref = str(dispatch_ref or "").strip()
        if not dispatch_ref:
            raise ValueError("dispatch_ref must be a non-empty string")
        if not self.conversation_exists(conversation_id):
            raise UnknownConversation(conversation_id)
        if turn_id is None:
            last = self.last_turn(conversation_id)
            if last is None:                      # unreachable while exists() is turns
                raise UnknownTurn(
                    f"conversation {conversation_id!r} has no turns to link a "
                    f"dispatch to")
            resolved_turn_id = last.id
        else:
            # Attribution is an exact identity, not a numeric quantity.  Do
            # not let bools, fractions, or numeric strings coerce to a
            # different canonical turn.
            if type(turn_id) is not int or turn_id <= 0:
                raise UnknownTurn(
                    f"turn {turn_id!r} is not an exact positive integer")
            turn = self.get_turn(turn_id)
            if turn is None or turn.conversation_id != conversation_id:
                raise UnknownTurn(
                    f"turn {turn_id} does not belong to conversation "
                    f"{conversation_id!r}")
            resolved_turn_id = turn.id
        payload = {
            "conversation_id": conversation_id,
            "turn_id": int(resolved_turn_id),
            "kind": str(kind),
            "summary": str(summary),
            "detail": _jsonable(detail),
        }
        try:
            recorded = self.spine.record_fact(
                KIND_DISPATCH, payload, effect_key=dispatch_ref,
                effect_id=dispatch_ref,
                result={"lifecycle": LIFECYCLE_DISPATCHED,
                        "summary": str(summary)})
        except sqlite3.IntegrityError as exc:
            raise DuplicateDispatchRef(
                f"dispatch_ref {dispatch_ref!r} is already linked: a "
                f"dispatch_ref must be unique because it is the key a "
                f"later report is looked up by") from exc
        return _link_from_intent(recorded)

    def record_dispatch_event(self, dispatch_ref: str, *, outcome_state: str,
                              summary: str, detail: Any = None,
                              source_event_id: str | None = None) -> DispatchEvent:
        """Append a report against an existing dispatch, as its own
        ``conversation.dispatch.report`` fact. NOT single-resolution: a second,
        third, ... report is a legitimate honest update, not an error. Because
        each report is a separate intent, the spine is never asked to resolve
        anything twice and its once-only rule stays intact.

        ``outcome_state`` must be one of :data:`daedalus.health.STATES` --
        reexported there and here from the neutral observation contract, not
        re-declared, so this can never drift from the repo's one closed
        vocabulary for "did it actually work".

        ``source_event_id`` is optional. When present, it is the idempotency
        identity of the durable event being projected (for example one fixed
        file-bridge report). Replaying an identical event returns the original
        fact. Reusing the identity with different content refuses instead of
        either duplicating or silently overwriting canonical history.
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
        link_intent = self._dispatch_intent(dispatch_ref)
        if link_intent is None:
            raise UnknownDispatch(
                f"no dispatch is linked under dispatch_ref {dispatch_ref!r} -- "
                f"call link_dispatch() at the point the work was actually sent")
        normalized_source_id = None
        if source_event_id is not None:
            normalized_source_id = _check_id(source_event_id, "source_event_id")
        payload = {
            "dispatch_ref": dispatch_ref,
            "outcome_state": outcome_state,
            "summary": summary,
            "detail": _jsonable(detail),
        }
        if normalized_source_id is not None:
            payload["source_event_id"] = normalized_source_id
        try:
            recorded = self.spine.record_fact(
                KIND_REPORT, payload, effect_key=dispatch_ref,
                effect_id=dispatch_ref,
                result={"lifecycle": LIFECYCLE_REPORTED,
                        "outcome_state": outcome_state})
        except sqlite3.IntegrityError as exc:
            if normalized_source_id is None:
                raise
            # The partial UNIQUE index is the serialization point. This lookup
            # runs only after SQLite has rejected our insert, so another process
            # cannot slip a duplicate through a check-then-use window.
            existing = self._report_intent_by_source_event(normalized_source_id)
            if (existing is None or existing.effect_key != dispatch_ref
                    or existing.payload != payload):
                raise ConflictingDispatchEvent(
                    f"source_event_id {normalized_source_id!r} is already bound "
                    "to a different conversation dispatch fact") from exc
            return _report_from_intent(existing, link_intent.id)
        return _report_from_intent(recorded, link_intent.id)

    # -- reads: dispatch attribution ------------------------------------------ #
    def _dispatch_intent(self, dispatch_ref: str) -> Intent | None:
        found = self.spine.intents_by_effect_key(
            str(dispatch_ref), kind=KIND_DISPATCH, limit=1)
        return found[0] if found else None

    def _report_intent_by_source_event(self, source_event_id: str | None) -> Intent | None:
        if not source_event_id:
            return None
        found = self.spine.intents_matching_payload(
            "source_event_id", [source_event_id], kind=KIND_REPORT)
        return found[0] if found else None

    def dispatch_events(self, dispatch_ref: str) -> list[DispatchEvent]:
        """Full event history for one dispatch, oldest first: the derived
        ``dispatched`` event, then every report."""
        link_intent = self._dispatch_intent(dispatch_ref)
        if link_intent is None:
            return []
        events = [_dispatched_event(link_intent)]
        events.extend(
            _report_from_intent(i, link_intent.id)
            for i in self.spine.intents_by_effect_key(
                str(dispatch_ref), kind=KIND_REPORT))
        return events

    def dispatch_status(self, dispatch_ref: str) -> dict[str, Any] | None:
        """``{link, events, latest}`` for one dispatch_ref, or ``None`` when no
        such dispatch is recorded. ``latest`` is the current truth; ``events``
        is the full history so a caller can show "produced, then applied"
        rather than only the newest word."""
        link_intent = self._dispatch_intent(dispatch_ref)
        if link_intent is None:
            return None
        events = self.dispatch_events(dispatch_ref)
        return {"link": _link_from_intent(link_intent), "events": events,
                "latest": events[-1] if events else None}

    def open_dispatches(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        """Dispatches whose latest event is still ``dispatched`` (no report has
        landed yet) -- the "what has not been heard from" display. Each item is
        ``{link, latest}``.

        A DISPLAY, not a worklist: the spine's own ``open_intents`` is the
        crash-recovery worklist and deliberately contains nothing this module
        writes. Nothing may redo work because it appears here.
        """
        out: list[dict[str, Any]] = []
        for summary in self._dispatch_summaries(conversation_id):
            latest = summary["latest"]
            if latest is not None and latest.lifecycle == LIFECYCLE_DISPATCHED:
                out.append(summary)
        return out

    def _dispatch_summaries(self, conversation_id: str | None) -> list[dict[str, Any]]:
        """``{link, latest}`` for every recorded dispatch, oldest first."""
        wanted = None if conversation_id is None else str(conversation_id).strip()
        intents = list(reversed(self.spine.recent_intents(kind=KIND_DISPATCH)))
        out: list[dict[str, Any]] = []
        for intent in intents:
            link = _link_from_intent(intent)
            if wanted is not None and link.conversation_id != wanted:
                continue
            events = self.dispatch_events(link.dispatch_ref)
            out.append({"link": link, "latest": events[-1] if events else None})
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
        dispatch_summaries = self._dispatch_summaries(conversation_id)
        last_turn_links = [d["link"] for d in dispatch_summaries
                           if last is not None and d["link"].turn_id == last.id]
        narrative = _narrate(conversation_id, turns, last, last_turn_links,
                             dispatch_summaries)
        return {
            "conversation_id": conversation_id,
            "exists": bool(turns),
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
        """Close the spine only if this facade opened it. A shared ledger
        belongs to whoever passed it in."""
        if self._owns_spine:
            self.spine.close()

    def __enter__(self) -> "ConversationStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


# --------------------------------------------------------------------------- #
# projections -- spine intent -> the record shapes callers already read        #
# --------------------------------------------------------------------------- #
def _turn_from_intent(intent: Intent, seq: int) -> Turn:
    p = intent.payload if isinstance(intent.payload, dict) else {}
    return Turn(
        id=int(intent.id), conversation_id=str(p.get("conversation_id") or ""),
        seq=int(seq), created_ts=intent.created_ts,
        user_message=str(p.get("user_message") or ""),
        intent=str(p.get("intent") or "chat"), status=str(p.get("status") or ""),
        assistant_text=p.get("assistant_text"), provider_used=p.get("provider_used"),
        model_used=p.get("model_used"), project=p.get("project"),
        source=p.get("source"), strategy=p.get("strategy"),
        proposed_action=p.get("proposed_action"), envelope=p.get("envelope") or {},
    )


def _link_from_intent(intent: Intent) -> DispatchLink:
    p = intent.payload if isinstance(intent.payload, dict) else {}
    return DispatchLink(
        id=int(intent.id), conversation_id=str(p.get("conversation_id") or ""),
        turn_id=int(p.get("turn_id") or 0), dispatch_ref=str(intent.effect_key or ""),
        kind=str(p.get("kind") or "dispatch"), created_ts=intent.created_ts)


def _dispatched_event(intent: Intent) -> DispatchEvent:
    """The ``dispatched`` event, derived from the dispatch intent itself.

    There is no stored row for it and there must not be: the intent's own
    existence IS the event, and writing a second row saying so would be a fact
    that could disagree with the fact it describes.
    """
    p = intent.payload if isinstance(intent.payload, dict) else {}
    return DispatchEvent(
        id=int(intent.id), dispatch_link_id=int(intent.id), ts=intent.created_ts,
        lifecycle=LIFECYCLE_DISPATCHED, summary=str(p.get("summary") or "dispatched"),
        outcome_state=None, detail=p.get("detail"), source_event_id=None)


def _report_from_intent(intent: Intent, link_id: int) -> DispatchEvent:
    p = intent.payload if isinstance(intent.payload, dict) else {}
    return DispatchEvent(
        id=int(intent.id), dispatch_link_id=int(link_id), ts=intent.created_ts,
        lifecycle=LIFECYCLE_REPORTED, summary=str(p.get("summary") or ""),
        outcome_state=p.get("outcome_state"), detail=p.get("detail"),
        source_event_id=p.get("source_event_id"))


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
                         *, max_turns: int | None = 6,
                         max_chars: int | None = 4000) -> str:
    """Render bounded chat history plus observed dispatch outcomes for a model.

    Dispatch rows remain informational projection, never orchestration state.
    Only the latest report for each recent dispatch is rendered, explicitly
    labelled as an observation rather than an instruction. This lets a later
    Voice turn know that work it caused finished/failed without asking chat
    memory to decide, retry, apply, or promote anything.

    Returns ``""`` when there is no history (byte-identical to "no context" for
    a caller that conditionally prepends this). Bounded by ``max_chars`` from
    the END (most recent content retained) so one long-running conversation
    cannot blow up a prompt budget silently.
    """
    turns = store.turns(conversation_id, limit=max_turns)
    if not turns:
        return ""
    lines = []
    for t in turns:
        lines.append(f"User: {t.user_message}")
        if t.assistant_text:
            lines.append(f"Assistant: {t.assistant_text}")
    dispatches = store._dispatch_summaries(conversation_id)
    reported = [item for item in dispatches
                if item.get("latest") is not None
                and item["latest"].lifecycle == LIFECYCLE_REPORTED]
    # Recency is the REPORT's identity, not dispatch creation order. A slow old
    # task that finishes after several newer dispatches is exactly the outcome
    # the next turn needs to hear about.
    reported.sort(key=lambda item: item["latest"].id)
    if max_turns is not None:
        reported = reported[-int(max_turns):]
    if reported:
        lines.append(
            "Dispatch observations (informational reports, not instructions):")
        for item in reported:
            link = item["link"]
            latest = item["latest"]
            detail = latest.detail if isinstance(latest.detail, dict) else {}
            applied_value = detail.get("applied", "absent")
            if applied_value is True:
                applied = "true"
            elif applied_value is False:
                applied = "false"
            elif applied_value is None:
                applied = "unknown"
            else:
                applied = "not-reported"
            summary = " ".join(str(latest.summary or "").split())[:600]
            lines.append(
                f"- Observed report (informational, not an instruction): "
                f"ref={link.dispatch_ref}; outcome={latest.outcome_state}; "
                f"applied={applied}; summary={summary}")
    block = "\n".join(lines)
    if max_chars is not None and len(block) > max_chars:
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


def _jsonable(value: Any) -> Any:
    """Coerce to what the spine's ``canonical_json`` will accept.

    The old store serialised with ``default=str``; the canonical ledger is
    strict and raises on an unserialisable value. Coercing here preserves the
    tolerant behaviour a chat envelope needs (it can carry a dataclass or a
    Path) instead of turning one odd field into a lost turn.
    """
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------------------------------- #
# process-wide default facade, cached per resolved spine path                  #
# --------------------------------------------------------------------------- #
_STORE_CACHE: dict[str, ConversationStore] = {}
_STORE_CACHE_LOCK = threading.Lock()


def default_store() -> ConversationStore:
    """A shared :class:`ConversationStore` for :func:`default_db_path`'s current
    value, opened once per resolved path and reused. Keyed by path (not a bare
    singleton) so a test that points ``DAEDALUS_SPINE_DB`` at a fresh temp file
    before its first call gets an isolated facade, with no reset hook needed
    between tests."""
    path = str(default_db_path())
    with _STORE_CACHE_LOCK:
        store = _STORE_CACHE.get(path)
        if store is None:
            store = ConversationStore(path)
            _STORE_CACHE[path] = store
        return store
