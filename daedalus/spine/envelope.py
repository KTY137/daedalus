"""spine/envelope.py -- one correlation id and one statement shape for six run formats.

THE PROBLEM THIS EXISTS FOR
---------------------------
MEASURED 2026-07-28: this tree writes run records in six hand-rolled formats
under six different id schemes -- ``intent_id`` (spine ledger), ``run_id``
(loop), ``council_id`` (council bus), ``entry_sha`` (memstore, since retired --
its ledger had never been written; ``council/bus.py`` carries that discipline
now and is the ``entry_sha`` referred to below), ``source_hash``
(canary), bridge ``epoch`` -- and **no id is shared between any two of them**.
Each id is correct locally and useless globally: a long run cannot be followed
across its own organs, because nothing a record carries appears in any other
record. "What did this run actually do" is currently answered by matching
timestamps by eye.

WHAT THIS MODULE DOES, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------------
It adds ONE field. It renames nothing.

The six id schemes keep their local meaning and their local uniqueness
guarantees -- they are load-bearing (``entry_sha`` chains a hash-chained
ledger; ``payload_sha`` pins what was decided) and re-keying six formats is a
migration nobody asked for. ``trace_id`` is added ALONGSIDE them, so records
JOIN without any record changing shape. Adding one field everywhere is Tuesday;
renaming six id fields is a quarter.

THREE PIECES
------------
1. **:func:`new_trace_id` / :func:`trace_context`** -- one correlation id,
   minted once at the top of a run and propagated AMBIENTLY (a
   :class:`contextvars.ContextVar`, plus ``DAEDALUS_TRACE_ID`` in the
   environment so a child process inherits it). Ambient, not a parameter,
   for a specific reason: the producers that need stamping are called from
   modules this change is not allowed to touch (``spine/attempt.py``,
   ``kairos/gated_writes.py``). A parameter would require editing every caller;
   an ambient read requires editing only the producer. Nothing auto-mints: with
   no run in scope :func:`current_trace_id` returns ``None`` and the field is
   OMITTED, so an untraced record is byte-identical to what it was before.

2. **:func:`statement`** -- the in-toto ITE-6 statement shape
   (``{_type, subject, predicateType, predicate}``): a claim, about a named
   artifact, pinned by digest. Every receipt in this tree already hand-rolls
   those three ideas in its own dialect (``gate_discrimination.json`` carries
   ``head`` and compares it to live HEAD; ``DSSReceipt`` carries
   ``forest_sha256``; ``PatchArtifact`` carries ``diff_sha256``). This is the
   shared spelling. See docs/ABSORPTION.md F2.

3. **:data:`GEN_AI`** -- OpenTelemetry GenAI semantic-convention attribute
   NAMES, and nothing else. See docs/ABSORPTION.md F3: the conventions are
   Development-status with no tag to pin, so this adoption is the weakest form
   available -- **borrow the names, claim no conformance, export nothing**.
   There is no OpenTelemetry import here, no SDK, no exporter, and no new
   dependency. The payoff is that a future exporter becomes a rename rather
   than a re-instrumentation.

WHAT THE ENVELOPE GRANTS: NOTHING. IT IS A SHAPE
-------------------------------------------------
ABSORPTION F2's threat model, restated here because a future reader will find
this module and mistake a shape for a guarantee: **it is JSON.** Wrapping a
payload in a statement verifies nothing, signs nothing and proves nothing. It
makes "which artifact is this claim about" a structural field instead of a
per-format convention. Signing is a separate, later, optional decision (I8).

KNOWN DEVIATION FROM in-toto, STATED SO A FUTURE EXPORTER KNOWS WHAT TO MOVE
----------------------------------------------------------------------------
``trace_id`` is carried as a TOP-LEVEL key on the statement. The in-toto v1
Statement has exactly four fields and ``trace_id`` is not one of them, so a
statement produced here is **ITE-6-shaped, not ITE-6-conformant**, and this
module never claims otherwise. The deviation is deliberate: the entire value of
the correlation id is that ``grep <trace_id>`` finds every record of a run, and
that requires the field to sit at ONE known position rather than nested inside
a predicate whose shape varies per producer. An exporter that later wants
strict conformance moves it into ``predicate`` or into span context; that is a
one-line change in :func:`statement` and this paragraph is the note it needs.

BACKWARD COMPATIBILITY IS A HARD REQUIREMENT
---------------------------------------------
Old records have no envelope and no trace id. New records carry both. **Every
existing reader must parse both**, which is what :func:`unwrap` and
:func:`trace_of` are for -- they accept an enveloped record and a bare legacy
record and return the same thing for the payload. A reader that calls
``unwrap()`` first is correct against every record ever written, in either
direction, and ``tests/test_envelope_join.py`` pins both directions.

THE LEDGER OF UNCONVERTED PRODUCERS
------------------------------------
FOUR producers are converted end-to-end, chosen so ONE run demonstrates a
join. The rest are listed rather than forgotten. MEASURED 2026-07-29 by scan,
plus ``lanes/fanout.py`` on 2026-07-30 -- caught by the drift detector rather
than declared, which is the mechanism working: the module was written that day,
its per-task result files were a new island, and the scan found it before a
reader six months out did. The count lives in this sentence AND in
``tests/test_envelope_coverage.py``, so a fifth conversion that forgets the
prose is caught;
``UNCONVERTED_PRODUCERS`` below is the machine-readable copy and
``tests/test_envelope_coverage.py`` goes RED when a producer appears in neither
table.

CONVERTED
=========
=================================  ===============  ==============  ===================================
module                             format           local id        how the trace is carried
=================================  ===============  ==============  ===================================
daedalus/spine/ledger.py           SQLite           intent_id       ``intents.trace_id`` column (v2)
daedalus/loop.py                   JSON doc         run_id          ``trace_id`` + per-attempt copy
daedalus/file_bridge.py            JSON per file    request key     ``trace_id`` in request AND report
daedalus/lanes/fanout.py           JSON per task    task key         ``trace_id``, resolved once per run
=================================  ===============  ==============  ===================================

UNCONVERTED -- module, format, id scheme, one line on conversion cost
MEASURED 2026-07-29 by the scan in ``tests/test_envelope_coverage.py``.
Ordered by value, not alphabetically: the top four are the ones worth doing.
=====================================  ==========  ==================  =========================================
module                                 format      id scheme           conversion cost
=====================================  ==========  ==================  =========================================
daedalus/council/bus.py                JSONL       council_id + seq    LOW-MEDIUM. Hash-chained: ``entry_sha``
                                                                       covers the body, so a new key changes
                                                                       every digest. Must be added BEFORE the
                                                                       chain is computed, or chained under a
                                                                       version bump. Highest value of all of
                                                                       them -- it is the only producer that
                                                                       already records per-call token counts,
                                                                       so it is where GEN_AI names pay off.
daedalus/build.py                      JSON/run    slug + created      LOW. ``BuildSession.save()`` ->
                                                                       ``runs/build/<slug>-<ts>.json``. The
                                                                       ORCHESTRATION record: a wave's own
                                                                       receipt. Converting it is what would
                                                                       let one trace span a whole build
                                                                       session rather than one loop run.
daedalus/progress.py                   JSONL       unit_id + batch_id  LOW. Six thin ``record_*`` helpers over
                                                                       one ``append``; stamp the append and all
                                                                       six inherit it. Best cost/benefit left.
daedalus/runbook.py                    JSON/run    run_id              LOW. ``runs/<run_id>.json``. Its
                                                                       ``run_id`` is literally one of the six
                                                                       colliding schemes this module exists to
                                                                       reconcile.
daedalus/memory/__init__.py            JSONL       task_id             LOW. One ``append_event``, additive dict.
daedalus/metrics.py                    JSONL       (none -- ts only)   LOW. Seven-key dict, no id at all today;
                                                                       trace_id would be its FIRST correlator.
daedalus/council/canary.py             JSONL       run_id + schema     LOW. Additive, but ``schema`` is pinned
                                                                       by a reader (canary.py:1180) so the
                                                                       version bump needs a both-versions read.
daedalus/kairos/drafts.py              JSON/run    id + created        LOW. ``runs/drafts/<ts>-<slug>-n.json``,
                                                                       additive, no chain.
runs/council/stream_hook.py            text log    ts + role           LOW. Append-only ``.stream_hook.log``;
                                                                       one field on the line, as the bridge's
                                                                       LATEST.log already does.
runs/council/summarize.py              markdown    turn_id             MEDIUM. Appends PROSE into room.md --
                                                                       the trace would have to live in the
                                                                       entry marker, not in a JSON key.
daedalus/adapters/transport.py         JSONL       caller-supplied     UNKNOWN. Path and record shape both come
                                                                       from the caller; needs a survey of sinks
                                                                       before it can be costed.
daedalus/file_bridge.py (heartbeat)    JSON        epoch               N/A BY DESIGN. Per-WATCHER liveness, not
                                                                       per-run; it outlives any one trace and
                                                                       has no run to correlate to.
=====================================  ==========  ==================  =========================================

The scan also flags nine modules that serialise JSON into ``runs/`` or
``memory/`` and are NOT run records -- latest-only mirrors, config scaffolds,
cursors, sealed fixtures. They are listed in :data:`UNCONVERTED_PRODUCERS` with
the reason, because a detector whose output is not fully accounted for is a
detector people learn to ignore.

WHICH SPINE DB PATH THIS READS THROUGH
---------------------------------------
``ledger.default_db_path()``, which honours ``DAEDALUS_SPINE_DB``. NOT
``picker.resolve_spine_db_path()``, which ignores that variable
(picker.py:438 vs ledger.py:157 -- a live divergence Codex owns; it is not
fixed here). The choice is forced rather than aesthetic: envelope work has to
be exercisable against a scratch database, and the picker's resolver would
silently send every test write into the real ``runs/spine/spine.sqlite3``.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

__all__ = [
    "GEN_AI",
    "IN_TOTO_STATEMENT_TYPE",
    "LOCAL_TO_GEN_AI",
    "PREDICATE_BRIDGE_REPORT",
    "PREDICATE_BRIDGE_REQUEST",
    "PREDICATE_LOOP_LEDGER",
    "PREDICATE_SPINE_INTENT",
    "TRACE_ID_ENV",
    "TRACE_KEY",
    "CONVERTED_PRODUCERS",
    "UNCONVERTED_PRODUCERS",
    "adopt_trace",
    "bind_trace_id",
    "canonical_json",
    "canonical_sha",
    "current_trace_id",
    "gen_ai_attributes",
    "is_statement",
    "new_trace_id",
    "stamp",
    "statement",
    "subject_for",
    "trace_context",
    "trace_of",
    "unwrap",
]


# --------------------------------------------------------------------------- #
# canonical JSON -- the one serialisation, so digests are stable               #
# --------------------------------------------------------------------------- #
# Lives HERE rather than in ledger.py, and ledger.py imports it back, for one
# structural reason: ledger.py is a CONSUMER of this module (its rows carry a
# trace and project to statements), so the dependency has to run
# envelope <- ledger or it is a cycle. The definition did not change; the names
# are still re-exported from ledger.py and from daedalus.spine, so every
# existing import path still resolves.
def canonical_json(obj: Any) -> str:
    """The single serialisation used for every stored blob and every digest.

    ``sort_keys`` makes two dicts built in different insertion orders produce
    byte-identical text; ``separators`` strips the whitespace a pretty-printer
    would vary; ``ensure_ascii`` pins the bytes so a digest does not depend on
    the reader's encoding. Mirrors ``council/bus.py``'s ``_body_sha``
    discipline: one place, one answer to "what bytes did we hash?".
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


# --------------------------------------------------------------------------- #
# the correlation id                                                           #
# --------------------------------------------------------------------------- #
#: The key every converted producer writes. One spelling, one position.
TRACE_KEY = "trace_id"

#: Cross-PROCESS propagation. The file bus carries the trace inside the record
#: for bridge hops (which is the standing rule -- no side channels), but a
#: plain subprocess has no record to carry it in, so the environment is the
#: only honest channel left. Read at :func:`current_trace_id` time rather than
#: cached at import, so a parent that binds after import still propagates.
TRACE_ID_ENV = "DAEDALUS_TRACE_ID"

#: Prefix chosen to be greppable and to collide with nothing else in the tree.
_TRACE_PREFIX = "tr-"

_TRACE_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "daedalus_trace_id", default=None)


def new_trace_id() -> str:
    """Mint a correlation id. Sortable by eye, unique in practice.

    Shape ``tr-<YYYYmmddTHHMMSS>-<8 hex>``, matching the house style already in
    ``loop.LoopDriver.run_id``. The stamp is for humans reading a directory
    listing; the uuid fragment is what makes it unique -- a collision needs two
    mints inside the same SECOND that also agree on 32 random bits. The
    ``tr-`` prefix exists so a partial id is still recognisable in a grep hit.
    """
    return (f"{_TRACE_PREFIX}{time.strftime('%Y%m%dT%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}")


def current_trace_id() -> str | None:
    """The trace id in scope, or ``None``.

    Resolution order, and each step is a deliberate fallback:

    1. the :class:`~contextvars.ContextVar` -- set by :func:`trace_context` in
       this process, correct under threads and async;
    2. ``DAEDALUS_TRACE_ID`` -- set by a parent process, which is how a trace
       survives a ``subprocess`` boundary that carries no record.

    **This never mints.** Auto-minting on a miss would be the worst possible
    behaviour: every unrelated record would get its own fresh id, the field
    would be 100% populated, and the join would return exactly one row every
    time -- a correlation id that correlates nothing, while LOOKING healthy.
    ``None`` means "no run in scope", the field is omitted, and the absence is
    visible.
    """
    got = _TRACE_VAR.get()
    if got:
        return got
    env = os.environ.get(TRACE_ID_ENV, "").strip()
    return env or None


def bind_trace_id(trace_id: str | None) -> contextvars.Token:
    """Bind ``trace_id`` for this context. Returns the reset token.

    Prefer :func:`trace_context`. This is the escape hatch for a caller whose
    run does not fit a ``with`` block (a long-lived server binding per request).
    """
    return _TRACE_VAR.set(str(trace_id) if trace_id else None)


@contextmanager
def _scope(tid: str | None, export_env: bool) -> Iterator[str | None]:
    """Bind ``tid`` (possibly ``None``) for the duration. Restores on exit.

    Restoration is unconditional and covers the exception path, because a
    leaked trace id is worse than no trace at all: it would silently glue the
    NEXT run's records onto this one's, producing a join that looks complete
    and is wrong. A wrong join is harder to notice than a missing one.
    """
    token = _TRACE_VAR.set(str(tid) if tid else None)
    had_env = TRACE_ID_ENV in os.environ
    prior_env = os.environ.get(TRACE_ID_ENV)
    if export_env:
        if tid:
            os.environ[TRACE_ID_ENV] = str(tid)
        else:
            # An untraced scope must UNSET it, not leave the parent's id
            # behind for a child process to inherit and misattribute.
            os.environ.pop(TRACE_ID_ENV, None)
    try:
        yield tid
    finally:
        _TRACE_VAR.reset(token)
        if export_env:
            if had_env:
                os.environ[TRACE_ID_ENV] = prior_env or ""
            else:
                os.environ.pop(TRACE_ID_ENV, None)


@contextmanager
def trace_context(trace_id: str | None = None, *,
                  export_env: bool = True) -> Iterator[str]:
    """START a run. Mints an id when not given one; yields the id.

    This is the ONE place a trace is born: at the top of a run (a loop
    iteration, a wave, an offload, an ikarus ask). Nesting is honest -- an
    inner scope that passes no id gets a NEW id rather than silently adopting
    whatever happened to be in scope, because a fresh unlinked id is a visible
    hole while a silently reused one is a false join.

    Use :func:`adopt_trace` instead when CONTINUING someone else's run. The two
    are separate functions rather than one flag because the difference matters
    and a boolean at the call site would not say which is meant: this one mints
    on ``None``, that one never mints.

    ``export_env`` also sets ``DAEDALUS_TRACE_ID`` so children inherit it.
    """
    tid = str(trace_id) if trace_id else new_trace_id()
    with _scope(tid, export_env):
        yield tid


@contextmanager
def adopt_trace(trace_id: str | None, *,
                export_env: bool = True) -> Iterator[str | None]:
    """CONTINUE a run someone else started. **Never mints.**

    For the receiving side of a hop -- the bridge watcher picking a request off
    the outbox, a worker draining a queue. It binds exactly what it was handed,
    and binds ``None`` when it was handed nothing.

    Minting here would be the subtle disaster :func:`current_trace_id`
    describes: every untraced request would get a private id, the field would
    be 100% populated, every join would return one row, and the instrument
    would report perfect health while measuring nothing. An untraced request
    stays untraced, and its records carry no trace -- which is true, and
    visibly incomplete.
    """
    with _scope(trace_id, export_env) as tid:
        yield tid


def stamp(record: Mapping[str, Any] | None = None, *,
          trace_id: str | None = None) -> dict[str, Any]:
    """A COPY of ``record`` carrying the trace id, or unchanged when there is none.

    Additive and non-destructive by contract: the caller's dict is never
    mutated (a producer that stamped its own argument would corrupt a payload
    the caller still holds), and an existing ``trace_id`` already on the record
    WINS over the ambient one -- a record that arrived over the bus carrying a
    trace belongs to the run that sent it, not to whatever run happens to be
    draining the queue. That precedence is the whole reason a bridge report can
    be joined back to the loop iteration that queued it.
    """
    out = dict(record or {})
    if out.get(TRACE_KEY):
        return out
    tid = trace_id or current_trace_id()
    if tid:
        out[TRACE_KEY] = str(tid)
    return out


# --------------------------------------------------------------------------- #
# the in-toto ITE-6 statement shape                                            #
# --------------------------------------------------------------------------- #
#: in-toto's own identifier for the v1 Statement. Used verbatim because the
#: SHAPE is genuinely theirs; conformance is still not claimed (see the module
#: docstring's KNOWN DEVIATION).
IN_TOTO_STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

#: Predicate types are URIs used purely as identifiers. ``.invalid`` is
#: reserved by RFC 2606 and can never resolve, which is the honest spelling
#: for "this names a local schema that is not published anywhere". A domain we
#: do not own would be a lie; a bare string would collide with someone's.
_PREDICATE_BASE = "https://daedalus.invalid/predicate"

PREDICATE_SPINE_INTENT = f"{_PREDICATE_BASE}/spine-intent/v1"
PREDICATE_LOOP_LEDGER = f"{_PREDICATE_BASE}/loop-ledger/v1"
PREDICATE_BRIDGE_REQUEST = f"{_PREDICATE_BASE}/bridge-request/v1"
PREDICATE_BRIDGE_REPORT = f"{_PREDICATE_BASE}/bridge-report/v1"


def subject_for(name: str, *, payload: Any = None,
                sha256: str | None = None) -> dict[str, Any]:
    """One in-toto subject: ``{"name": ..., "digest": {"sha256": ...}}``.

    Pass ``sha256`` when the digest ALREADY EXISTS -- the spine ledger stores
    ``payload_sha`` in the row, and recomputing it here would silently paper
    over the one disagreement worth surfacing (a stored digest that no longer
    matches its stored payload). Pass ``payload`` only when no digest has been
    computed yet; it is hashed through :func:`canonical_json`, so the digest
    does not depend on dict insertion order.
    """
    if sha256 is None:
        if payload is None:
            raise ValueError("subject_for needs either payload or sha256")
        sha256 = canonical_sha(payload)
    return {"name": str(name), "digest": {"sha256": str(sha256)}}


def statement(*, subject: Mapping[str, Any] | list, predicate_type: str,
              predicate: Any, trace_id: str | None = None) -> dict[str, Any]:
    """Wrap a payload in the ITE-6 statement shape. The payload is NOT altered.

    ``predicate`` is placed under the ``predicate`` key exactly as given -- no
    key is added to it, removed from it or renamed inside it. That is the
    contract that makes conversion cheap: a producer wraps, and every field its
    existing readers know is still there, one level down, reachable by
    :func:`unwrap`.

    ``subject`` accepts one subject or a list; in-toto's field is a list and it
    is normalised to one here so callers do not each remember to wrap.
    """
    subjects = list(subject) if isinstance(subject, list) else [dict(subject)]
    out: dict[str, Any] = {
        "_type": IN_TOTO_STATEMENT_TYPE,
        "subject": subjects,
        "predicateType": str(predicate_type),
        "predicate": predicate,
    }
    tid = trace_id or current_trace_id()
    if tid:
        # Top level, NOT inside the predicate: see KNOWN DEVIATION. One grep,
        # one position, regardless of which producer wrote the record.
        out[TRACE_KEY] = str(tid)
    return out


def is_statement(obj: Any) -> bool:
    """Is this an envelope, or a bare pre-envelope record?

    Tested on ``_type`` plus the presence of ``predicate``, not on ``_type``
    alone: a legacy payload that happens to carry a ``_type`` string must not
    be mistaken for a statement and unwrapped down to nothing.
    """
    return (isinstance(obj, Mapping)
            and obj.get("_type") == IN_TOTO_STATEMENT_TYPE
            and "predicate" in obj)


def unwrap(obj: Any) -> Any:
    """The payload, whether ``obj`` is an envelope or a bare legacy record.

    **This is the backward-compatibility primitive.** A reader that calls this
    first is correct against every record this repo has ever written and every
    record it will write: old records pass through untouched, new records are
    unwrapped to exactly the payload the old reader expected. Both directions
    are pinned by ``tests/test_envelope_join.py``.
    """
    return obj["predicate"] if is_statement(obj) else obj


def trace_of(obj: Any) -> str | None:
    """The trace id of a record, enveloped or bare, or ``None``.

    Checks the top level first (where :func:`statement` puts it), then the
    payload (where :func:`stamp` puts it on producers that write a flat record
    rather than an envelope). One accessor for both conversion styles, so a
    reader never has to know which one a given producer chose.
    """
    if not isinstance(obj, Mapping):
        return None
    got = obj.get(TRACE_KEY)
    if got:
        return str(got)
    inner = obj.get("predicate")
    if isinstance(inner, Mapping) and inner.get(TRACE_KEY):
        return str(inner[TRACE_KEY])
    return None


# --------------------------------------------------------------------------- #
# OpenTelemetry GenAI attribute NAMES -- names only, no runtime                #
# --------------------------------------------------------------------------- #
class GEN_AI:
    """The subset of ``gen_ai.*`` attribute names this repo can actually fill.

    NAMES ONLY. There is no ``opentelemetry`` import in this file, no SDK, no
    OTLP exporter, no span, and no claim of conformance -- ABSORPTION F3 records
    why: as of 2026-07-17 no GenAI attribute is marked Stable, the conventions
    moved to a repo with **no releases and no tags**, and ADR-017's bar
    ("an unpinned standard is a moving target wearing a stable name") therefore
    cannot be met. Borrowing the spelling costs one line of documentation and
    turns a future exporter into a rename; claiming conformance would be a
    promise nothing can check.

    Only names with a real source in this tree are listed. An attribute nobody
    can populate is not adoption, it is decoration.
    """

    SYSTEM = "gen_ai.system"                       # "anthropic" | "openai" | "ollama"
    OPERATION_NAME = "gen_ai.operation.name"       # "chat" | "execute_tool"
    REQUEST_MODEL = "gen_ai.request.model"
    REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
    REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    RESPONSE_MODEL = "gen_ai.response.model"
    RESPONSE_ID = "gen_ai.response.id"
    RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    # Not gen_ai.*, but the conventions' own spelling for these two, and both
    # are already recorded here under other names.
    SERVER_ADDRESS = "server.address"
    ERROR_TYPE = "error.type"


#: The rename table, from what this repo calls a thing today to what the
#: ecosystem calls it. MEASURED: ``council/bus.py`` records exactly these per
#: turn in ``meta{}``, which is why the conversion is a rename and not an
#: instrumentation project.
#:
#: TWO FIELDS ARE DELIBERATELY ABSENT, and saying so is the point of a table
#: like this. ``latency_ms`` has no GenAI attribute -- OTel models duration as
#: the SPAN, not as an attribute, and inventing ``gen_ai.latency_ms`` would be
#: fabricating a convention while claiming to follow one. ``cost_usd`` likewise
#: has no stable attribute. Both keep their local names, on purpose, and a
#: future exporter maps latency onto span duration.
LOCAL_TO_GEN_AI = {
    "model": GEN_AI.REQUEST_MODEL,
    "prompt_tokens": GEN_AI.USAGE_INPUT_TOKENS,
    "completion_tokens": GEN_AI.USAGE_OUTPUT_TOKENS,
    "input_tokens": GEN_AI.USAGE_INPUT_TOKENS,
    "output_tokens": GEN_AI.USAGE_OUTPUT_TOKENS,
    "vendor": GEN_AI.SYSTEM,
    "provider": GEN_AI.SYSTEM,
    "endpoint": GEN_AI.SERVER_ADDRESS,
    "finish_reason": GEN_AI.RESPONSE_FINISH_REASONS,
}


def gen_ai_attributes(meta: Mapping[str, Any] | None = None,
                      **overrides: Any) -> dict[str, Any]:
    """Re-spell a local model-call ``meta`` dict under the GenAI names.

    Keys absent from :data:`LOCAL_TO_GEN_AI` are dropped rather than passed
    through: the return value is a set of ATTRIBUTES under a named convention,
    and quietly mixing local spellings into it would recreate the six-dialect
    problem inside the thing built to fix it. Keep the local dict too -- this
    is a projection, not a replacement.

    ``None`` values are dropped: an attribute present-but-null is
    indistinguishable from a measured zero to most consumers.
    """
    out: dict[str, Any] = {}
    for key, value in dict(meta or {}).items():
        name = LOCAL_TO_GEN_AI.get(str(key))
        if name is not None and value is not None:
            out[name] = value
    for name, value in overrides.items():
        if value is not None:
            out[str(name).replace("__", ".")] = value
    return out


# --------------------------------------------------------------------------- #
# the producer ledger -- machine-readable copy of the docstring tables         #
# --------------------------------------------------------------------------- #
#: Producers wired end-to-end. The value is HOW the trace is carried, because
#: "converted" alone does not tell a reader where to look for the field.
CONVERTED_PRODUCERS = {
    "daedalus/spine/ledger.py":
        "intents.trace_id column (schema v2) + Intent.to_statement()",
    "daedalus/loop.py":
        "LoopLedger.trace_id + per-attempt trace_ids, schema daedalus.loop.ledger/2",
    "daedalus/file_bridge.py":
        "trace_id in the outbox request, propagated into the inbox report",
    "daedalus/lanes/fanout.py":
        "FanoutResult.trace_id, resolved ONCE per fan_out and written into every "
        "per-task result file. NOT re-stamped on the resume path: a cached answer "
        "keeps the trace of the run that PAID for it, because overwriting it "
        "would claim this run produced something it read off disk. These records "
        "are a paid external call and its answer, so the trace is what joins a "
        "bill to the run that incurred it.",
}

#: Producers NOT wired, each with the reason it is affordable to defer. This is
#: a WORKLIST, not an excuse list: ``tests/test_envelope_coverage.py`` fails
#: when a producer appears in neither table, so the remaining work stays
#: visible instead of being rediscovered by someone grepping for a trace id
#: that was never written.
UNCONVERTED_PRODUCERS = {
    # -- MEASUREMENT ARTEFACTS, not run records. Listed first because the
    #    distinction matters: these are corpus-level reports about the tree,
    #    reproducible from the tree alone, and NOT records of something that
    #    happened during a run. A trace id would correlate them to nothing. ---#
    "daedalus/shift.py":
        "OPERATOR STATE, NOT A RUN RECORD. runs/shift.json, one declared working "
        "window with checkpoints. It is the operator's intent for a session, not "
        "a record of an effect, so there is no run for a trace id to name. Written "
        "atomically and appended under a lock because a ticker, a prompt hook and "
        "the agent all touch it concurrently.",
    "daedalus/arch_memory.py":
        "DERIVED SUMMARY, NOT A RUN RECORD. runs/arch_memory.json plus a "
        "runs/arch_memory.shown cursor. Regenerated from the tree on commit; "
        "reproducible from a revision with no run involved, so the honest "
        "correlator is the head it was built at, which the file already carries.",
    "daedalus/eval/graph_delta.py":
        "MEASUREMENT ARTEFACT, NOT A RUN RECORD. runs/eval/graph_delta.json, keyed "
        "by mutation id "
        "from tools/gate_discrimination.py. NOT a run record: it is a corpus "
        "measurement, reproducible from the tree at a revision with no run "
        "involved, so there is no run for a trace id to point at. Conversion "
        "cost is therefore not LOW or HIGH but MEANINGLESS -- the honest "
        "correlator here is the revision it was measured at, which the report "
        "already carries. Revisit if it is ever called per-candidate inside a "
        "loop iteration, which WOULD make it a run record.",
    "daedalus/gui/lint.py":
        "MEASUREMENT ARTEFACT, NOT A RUN RECORD. runs/gui/report.json, keyed by "
        "capture label. Same reasoning: it scores a rendered surface against the design rules "
        "and is reproducible from that surface. If the GUI lane ever gates a "
        "candidate, the gate result becomes a run record and this entry moves "
        "to the worklist above with a real conversion cost.",

    # -- genuine run records, in value order. THIS IS THE WORKLIST. --------- #
    "daedalus/council/bus.py":
        "RUN RECORD. JSONL, council_id+seq. LOW-MEDIUM. HASH-CHAINED: "
        "entry_sha covers the body, so a new key changes every digest -- must "
        "be stamped before the chain is computed, under a version bump. "
        "Highest value of all of them: the only producer already recording "
        "per-call token counts, so it is where the GEN_AI names pay off.",
    "daedalus/build.py":
        "RUN RECORD. runs/build/<slug>-<ts>.json, keyed slug+created. LOW. The "
        "ORCHESTRATION receipt -- converting it is what would let one trace "
        "span a whole build session instead of one loop run.",
    "daedalus/progress.py":
        "RUN RECORD. JSONL, unit_id+batch_id. LOW: six record_* helpers over "
        "one append(); stamp the append and all six inherit it. Best "
        "cost/benefit left.",
    "daedalus/runbook.py":
        "RUN RECORD. runs/<run_id>.json. LOW. Its run_id is literally one of "
        "the six colliding id schemes this module exists to reconcile.",
    "daedalus/memory/__init__.py":
        "RUN RECORD. JSONL, task_id. LOW: one append_event, additive, no chain.",
    "daedalus/metrics.py":
        "RUN RECORD. JSONL, no id at all (ts only). LOW: seven-key dict; "
        "trace_id would be its first correlator of any kind.",
    "daedalus/council/canary.py":
        "RUN RECORD. JSONL, run_id+schema. LOW but schema is pinned by a "
        "reader at canary.py:1180, so the bump needs a both-versions read.",
    "daedalus/kairos/drafts.py":
        "RUN RECORD. runs/drafts/<ts>-<slug>-n.json, keyed id+created. LOW, "
        "additive, no chain.",
    "runs/council/stream_hook.py":
        "RUN RECORD. Append-only .stream_hook.log, keyed ts+role. LOW: one "
        "field on the line, exactly as the bridge's LATEST.log now does.",
    "runs/council/summarize.py":
        "RUN RECORD. Appends PROSE into room.md, keyed turn_id. MEDIUM: the "
        "trace would have to live in the entry marker, not in a JSON key.",
    "daedalus/adapters/transport.py":
        "RUN RECORD. JSONL, caller-supplied. UNKNOWN cost: path and record "
        "shape both come from the caller; needs a survey of sinks to cost.",

    # -- NOT run records. Listed so the scan's output is fully accounted for, #
    # -- because a detector whose hits are unexplained gets ignored. -------- #
    "daedalus/claude_bridge.py":
        "NOT A RUN RECORD: runs/last_claude_report.json is a latest-only "
        "mirror, overwritten each time and accumulating nothing.",
    "daedalus/providers/codex_cli.py":
        "NOT A RUN RECORD: runs/last_codex_report.json, same latest-only "
        "mirror as claude_bridge.",
    "daedalus/token_monitor.py":
        "NOT A RUN RECORD: memory/token_status.local.json is current "
        "checkpoint state, overwritten in place.",
    "daedalus/config.py":
        "NOT A RUN RECORD: one-time .agentenv/agentenv.json scaffold, skipped "
        "when it already exists.",
    "runs/council/room.py":
        "NOT A RUN RECORD: cursors.json is per-speaker read position and floor "
        "state -- a lock, not a log.",
    "runs/ab/blind.py":
        "NOT A RUN RECORD: SEALED_MAPPING.json is a one-time sealed fixture "
        "that refuses to be re-sealed.",
    "runs/ab/oracle_check.py":
        "NOT A RUN RECORD: oracle_check.json is a rendered result set, "
        "overwritten per run with no accumulation.",
    "daedalus/mapping/inventory.py":
        "NOT A RUN RECORD: docs/FEATURE_INVENTORY.json is a repo-state "
        "snapshot with no run to correlate to.",
    "daedalus/mapping/drift.py":
        "NOT A RUN RECORD: docs/architecture-state.json, same reason.",
    "daedalus/budget.py":
        "NOT A RUN RECORD: a running spend total per PERIOD, deliberately not "
        "per-run -- correlating it to a trace would misrepresent what it is.",
    "daedalus/conversation.py":
        "NOT A RUN RECORD: it produces no records of its own any more. Every "
        "turn, dispatch and report is a typed intent on spine/ledger.py, which "
        "is already converted and stamps trace_id at record time -- so this "
        "module inherits the join instead of needing its own conversion.",
}
