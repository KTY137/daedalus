"""progress.py -- what is OBSERVED about in-flight work, versus what has
merely been STARTED.

WHY THIS EXISTS. This repo has three receipts for the same underlying mistake,
each wearing a different hat:

    the bench reported a green health check that was true when taken and
    false one second later (the process died with the ssh session that
    started it)
    a model narrated a file edit it never performed, and the harness read
    the narration as a finished report
    a spend ledger reported $48 that was worst-case RESERVATIONS, not money
    actually spent (see daedalus.budget: reserved_usd vs spent_usd)

    -> A CLAIM ABOUT WORK WAS REPORTED AS A MEASUREMENT OF WORK.

This module keeps those apart by construction. For one dispatched unit of
work it never collapses "running" into "progressing", "finished" into
"succeeded", or "wrote" into "verified" -- each is a separate fact, recorded
separately, and a caller has to read the actual fact rather than a summary
word that quietly picked one meaning for them.

THE VOCABULARY (:data:`EVENT_KINDS`) is closed, mirroring the discipline in
:mod:`daedalus.health` (five states, no "skipped", a guard that refuses a
sixth). It answers exactly the phases the brief for this module named:

    QUEUED          it was queued
    CLAIMED         it was claimed (something started acting on it)
    HEARTBEAT       the dispatching thread/process is still alive -- NOT
                    evidence of progress, only of the absence of a crash
    GENERATING      a model is producing output, MEASURED byte by byte
    TOOL_RAN        a tool ran and returned this
    GATE_VERDICT    a gate ran and its verdict was this
    DISK_CHANGED    bytes changed on disk (mechanically proven, see below)
    NO_CHANGE       nothing changed -- itself an observed fact, not a gap
    PATCH_PRODUCED  candidate bytes exist in an ISOLATED worktree -- this is
                    explicitly NOT a landed change (see
                    daedalus.spine.attempt's module docstring: "a patch that
                    exists is not a change that landed")
    DONE            terminal. carries succeeded (bool|None) and applied
                    (bool|None) as SEPARATE facts -- finished is not succeeded,
                    and succeeded is not applied.

PROVENANCE IS REUSED, NOT REINVENTED. :class:`daedalus.health.Fact` already
refuses to be constructed as INHERITED without naming its source and age; this
module imports that class and those constructors rather than building a
second provenance system that could drift from the first. Every
:class:`ProgressEvent` this module accepts is, by construction, a MEASURED
fact about the instant it was appended (we do not accept "it probably started
around then" as an event) -- staleness enters only at READ time, where
:func:`snapshot` computes every age fresh, from "now", against the immutable
timestamp on the event. A snapshot is never cached and never reused across
calls, which is the direct fix for the bench probe that was true when taken
and false a second later: this module's answer to "is it still running" is
always "as of THIS instant, here is what was last observed, and how long ago
that was" -- never a memoised verdict.

THE DISK-CHANGE REFUSAL HAS TEETH, not just a docstring. offload.py already
learned this lesson once (report["files_changed"] is the model's own claim,
and offload's verify() explicitly refuses to trust it -- see
daedalus/verifier.py). :func:`record_disk_change` requires ``basis`` to be one
of :data:`DISK_EVIDENCE_BASES` -- a mechanical diff, never a self-report -- and
:class:`ProgressEvent` enforces it in ``__post_init__``, so a caller cannot
construct a DISK_CHANGED/NO_CHANGE event any other way, not just "shouldn't".

NO FABRICATED PERCENTAGE. There is deliberately no ``percent_complete`` field
anywhere in this module. A single unit of work has no known total -- token
count against an unknown final length, or "step 3 of N" when N was never
declared, is exactly the invented progress bar the owning brief called out as
"the most tempting dishonest thing an assistant can render". The one
percentage this module DOES offer, :func:`batch_snapshot`'s ``fraction``, has
a real denominator: the caller's own declared count of units it dispatched.
Every :class:`UnitProgress` carries ``fraction_hint``, a plain-language
citation of this refusal, so a consumer sees WHY the number is absent instead
of a silently missing key.

RELATION TO OTHER STORES IN THIS REPO. This module keeps exactly one thing of
its own: an additive, best-effort JSONL trail (:class:`ProgressLog`,
matching the durability posture of ``daedalus/memory/__init__.py``'s
``append_event`` -- a plain buffered append, no WAL, no cross-process lock).
It does NOT re-implement crash-safe intent tracking: where this repo already
has that (``daedalus.spine.ledger``, committed intent-before-effect, WAL,
cross-process), :mod:`daedalus.progress_sources` reads it read-only instead of
duplicating it. Two disagreeing sources of truth for the same fact is the
exact shape of bug ``daedalus/health.py`` was written to catch elsewhere in
this tree; this module does not introduce a fresh instance of it.

    python -m daedalus.progress                 # every unit this log has seen
    python -m daedalus.progress <unit-id>        # one unit
    python -m daedalus.progress --json           # machine-readable
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .health import ASSUMED, INHERITED, MEASURED, Fact, assumed, measured

ROOT = Path(__file__).resolve().parents[1]

__all__ = [
    "EVENT_KINDS", "QUEUED", "CLAIMED", "HEARTBEAT", "GENERATING", "TOOL_RAN",
    "GATE_VERDICT", "DISK_CHANGED", "NO_CHANGE", "PATCH_PRODUCED", "DONE",
    "DISK_EVIDENCE_BASES", "DEFAULT_STALL_BUDGET_S",
    "ProgressError", "UnknownUnit",
    "ProgressEvent", "ProgressLog", "DEFAULT_LOG_PATH", "default_log", "reset_default_log",
    "open_unit", "claim_unit", "heartbeat", "record_generating", "record_tool_ran",
    "record_gate_verdict", "record_disk_change", "record_patch_produced", "record_done",
    "UnitProgress", "BatchProgress", "snapshot", "batch_snapshot",
    "render", "render_batch", "to_payload", "now_iso", "parse_iso", "format_age",
    "main",
]

# --------------------------------------------------------------------------- #
# the vocabulary -- closed on purpose, same discipline as daedalus.health      #
# --------------------------------------------------------------------------- #
QUEUED = "queued"
CLAIMED = "claimed"
HEARTBEAT = "heartbeat"
GENERATING = "generating"
TOOL_RAN = "tool_ran"
GATE_VERDICT = "gate_verdict"
DISK_CHANGED = "disk_changed"
NO_CHANGE = "no_change"
PATCH_PRODUCED = "patch_produced"
DONE = "done"

#: The ONLY event kinds a caller may record. An unrecognised kind is refused
#: at construction (see ProgressEvent.__post_init__), the same way
#: daedalus.health._coerce refuses an unrecognised state word rather than
#: rendering it as a pass.
EVENT_KINDS = (QUEUED, CLAIMED, HEARTBEAT, GENERATING, TOOL_RAN, GATE_VERDICT,
               DISK_CHANGED, NO_CHANGE, PATCH_PRODUCED, DONE)

#: What counts as REAL evidence for "bytes changed on disk". Deliberately
#: does NOT include anything named "self_report" or "model_claim" -- see
#: daedalus/offload.py's _content_hash/_repo_snapshot and
#: daedalus/verifier.py's refusal of report["files_changed"]. A caller with
#: only a model's own claim has no way to satisfy record_disk_change(); that
#: is the point.
DISK_EVIDENCE_BASES = ("content_hash_diff", "git_diff_capture")

#: A unit CLAIMED or GENERATING with no further event for longer than this is
#: rendered `stalled`, not silently left looking current. Chosen against this
#: repo's own measured latencies: ikarus_os.py's CLI calls carry a 150s hard
#: timeout and a ~4-6s ordinary round trip (see _neutral_cwd's docstring);
#: 90s is comfortably past normal and comfortably short of the hard timeout,
#: so a stall is flagged well before a caller would otherwise just time out
#: with no earlier warning.
DEFAULT_STALL_BUDGET_S = 90.0


class ProgressError(RuntimeError):
    """Base for every refusal this module makes."""


class UnknownUnit(ProgressError):
    """No events exist for a unit_id an operation required to be known."""


# --------------------------------------------------------------------------- #
# small time helpers -- public, so progress_sources.py and callers share one  #
# definition of "how old is this" rather than each rolling their own          #
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: str) -> float:
    """Epoch seconds for an ISO timestamp this module wrote. Naive timestamps
    (no tzinfo) are treated as UTC, matching every writer in this file."""
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def format_age(age_s: float | None) -> str:
    if age_s is None:
        return "age unknown"
    if age_s == float("inf"):
        return "a very long time"
    if age_s < 90:
        return f"{age_s:.0f}s"
    if age_s < 5400:
        return f"{age_s / 60:.0f}m"
    if age_s < 172800:
        return f"{age_s / 3600:.1f}h"
    return f"{age_s / 86400:.1f}d"


# --------------------------------------------------------------------------- #
# the event -- one observation, immutable                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProgressEvent:
    """One fact about one unit of work, at the instant it was recorded.

    ``ts`` is always "when THIS process appended the record" -- never a
    caller-supplied guess about when something "really" happened, so it can
    always be trusted as the append time and nothing more.
    """

    unit_id: str
    kind: str
    ts: str
    source: str
    detail: Mapping[str, Any] = field(default_factory=dict)
    batch_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ProgressError(
                f"{self.kind!r} is not one of {EVENT_KINDS} -- refusing to "
                f"record an event kind this module does not recognise")
        if not str(self.unit_id or "").strip():
            raise ProgressError("a ProgressEvent requires a non-empty unit_id")
        if not str(self.source or "").strip():
            raise ProgressError(
                f"{self.kind!r} event for unit {self.unit_id!r} names no "
                f"source -- an unattributed fact is exactly how a self-report "
                f"gets laundered into evidence")
        if self.kind in (DISK_CHANGED, NO_CHANGE):
            basis = (self.detail or {}).get("basis")
            if basis not in DISK_EVIDENCE_BASES:
                raise ProgressError(
                    f"{self.kind!r} requires detail['basis'] in "
                    f"{DISK_EVIDENCE_BASES}, got {basis!r}. A model's own "
                    f"claim about what it changed is explicitly not accepted "
                    f"here -- see daedalus.offload._repo_snapshot and "
                    f"daedalus.verifier.verify()'s refusal of "
                    f"report['files_changed']")

    def to_dict(self) -> dict:
        return {"unit_id": self.unit_id, "kind": self.kind, "ts": self.ts,
                "source": self.source, "detail": dict(self.detail or {}),
                "batch_id": self.batch_id}

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ProgressEvent":
        return ProgressEvent(unit_id=d["unit_id"], kind=d["kind"], ts=d["ts"],
                             source=d.get("source", "?"), detail=d.get("detail") or {},
                             batch_id=d.get("batch_id"))


# --------------------------------------------------------------------------- #
# the log -- additive, best-effort, matches memory/__init__.py's durability    #
# --------------------------------------------------------------------------- #
DEFAULT_LOG_PATH = ROOT / "runs" / "progress" / "events.jsonl"


class ProgressLog:
    """Append-only JSONL, one line per observation.

    DURABILITY POSTURE, STATED HONESTLY: this is a plain buffered append
    under a process-local lock -- the same posture as
    ``daedalus/memory/__init__.py::append_event``, and deliberately weaker
    than :mod:`daedalus.spine.ledger` (WAL, cross-process advisory locking,
    intent-before-effect). That is a considered choice, not an oversight:
    this log is ADDITIVE colour on top of work whose durable, crash-safe
    record (if it needs one) lives in the spine ledger already. Losing or
    corrupting the last line here loses one stale progress detail; it never
    loses a decision about an external effect. A unit whose correctness
    depends on crash-safe intent tracking belongs in the spine ledger, and
    this module reads that ledger read-only rather than re-deriving it (see
    ``daedalus.progress_sources.snapshot_from_ledger``).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_LOG_PATH
        self._lock = threading.Lock()

    def append(self, event: ProgressEvent) -> ProgressEvent:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def read_all(self) -> list[ProgressEvent]:
        if not self.path.exists():
            return []
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        out: list[ProgressEvent] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(ProgressEvent.from_dict(json.loads(line)))
            except (ValueError, KeyError, ProgressError):
                # A corrupt or foreign line is skipped, never crashes a
                # reader -- same posture as daedalus.status/health toward a
                # malformed journal line.
                continue
        return out

    def events_for(self, unit_id: str) -> list[ProgressEvent]:
        return [e for e in self.read_all() if e.unit_id == str(unit_id)]

    def units(self) -> list[str]:
        seen: list[str] = []
        s: set[str] = set()
        for e in self.read_all():
            if e.unit_id not in s:
                s.add(e.unit_id)
                seen.append(e.unit_id)
        return seen

    def batch(self, batch_id: str) -> list[ProgressEvent]:
        return [e for e in self.read_all() if e.batch_id == str(batch_id)]


_DEFAULT_LOG: ProgressLog | None = None
_DEFAULT_LOG_LOCK = threading.Lock()


def default_log() -> ProgressLog:
    """The process-wide default log, at :data:`DEFAULT_LOG_PATH`."""
    global _DEFAULT_LOG
    with _DEFAULT_LOG_LOCK:
        if _DEFAULT_LOG is None:
            _DEFAULT_LOG = ProgressLog()
        return _DEFAULT_LOG


def reset_default_log() -> None:
    """Drop the cached default log. For tests, and for a process that has
    just changed where it wants the log written."""
    global _DEFAULT_LOG
    with _DEFAULT_LOG_LOCK:
        _DEFAULT_LOG = None


# --------------------------------------------------------------------------- #
# recording -- the only way events enter a log                                #
# --------------------------------------------------------------------------- #
def _record(unit_id: str, kind: str, *, source: str, detail: Mapping[str, Any] | None = None,
           batch_id: str | None = None, log: ProgressLog | None = None) -> ProgressEvent:
    log = log or default_log()
    ev = ProgressEvent(unit_id=str(unit_id), kind=kind, ts=now_iso(), source=str(source),
                       detail=dict(detail or {}), batch_id=batch_id)
    return log.append(ev)


def open_unit(unit_id: str | None = None, *, source: str, detail: Mapping[str, Any] | None = None,
             batch_id: str | None = None, log: ProgressLog | None = None) -> str:
    """Record QUEUED. Mints a unit_id (uuid4 hex) when none is supplied and
    returns it -- the caller's handle for every later call, the same "you get
    an id back" contract as ``SpineLedger.record_intent``.

    PREFER AN EXISTING ID SPACE WHEN ONE ALREADY EXISTS FOR THIS WORK: the
    outbox/inbox stem ``daedalus.file_bridge.enqueue`` returns, or a spine
    ledger ``effect_key``. Minting a third id for work that already has one
    just makes it harder to find later; this parameter exists for genuinely
    new work (e.g. one chat turn) that has no other handle.
    """
    unit_id = str(unit_id) if unit_id else uuid.uuid4().hex
    _record(unit_id, QUEUED, source=source, detail=detail, batch_id=batch_id, log=log)
    return unit_id


def claim_unit(unit_id: str, *, source: str, detail: Mapping[str, Any] | None = None,
              log: ProgressLog | None = None) -> ProgressEvent:
    """Record CLAIMED: something has started acting on this unit. This is a
    DISPATCH fact ("we began trying"), not a generation fact -- see
    daedalus.progress_sources.watch_stream's mapping of ask_stream's "start"
    event for the exact conflation this separation exists to prevent."""
    return _record(unit_id, CLAIMED, source=source, detail=detail, log=log)


def heartbeat(unit_id: str, *, source: str, detail: Mapping[str, Any] | None = None,
             log: ProgressLog | None = None) -> ProgressEvent:
    """Record HEARTBEAT: the dispatching thread/process has not crashed.
    Deliberately weaker than every other event kind here -- it is proof
    against a crash, never proof of forward motion. A hung call and a working
    one look identical on this signal alone; render() and UnitProgress.stalled
    both treat HEARTBEAT as insufficient, on its own, to clear a stall."""
    return _record(unit_id, HEARTBEAT, source=source, detail=detail, log=log)


def record_generating(unit_id: str, *, nbytes: int, source: str,
                      detail: Mapping[str, Any] | None = None,
                      log: ProgressLog | None = None) -> ProgressEvent:
    """Record GENERATING: ``nbytes`` bytes of real model output were just
    measured arriving. Never call this for "the process is running" alone --
    that is HEARTBEAT."""
    d = dict(detail or {})
    d["nbytes"] = int(nbytes)
    return _record(unit_id, GENERATING, source=source, detail=d, log=log)


def record_tool_ran(unit_id: str, *, name: str, ok: bool, source: str,
                    detail: Mapping[str, Any] | None = None,
                    log: ProgressLog | None = None) -> ProgressEvent:
    d = dict(detail or {})
    d["name"] = name
    d["ok"] = bool(ok)
    return _record(unit_id, TOOL_RAN, source=source, detail=d, log=log)


def record_gate_verdict(unit_id: str, *, name: str, passed: bool, source: str,
                        detail: Mapping[str, Any] | None = None,
                        log: ProgressLog | None = None) -> ProgressEvent:
    d = dict(detail or {})
    d["name"] = name
    d["passed"] = bool(passed)
    return _record(unit_id, GATE_VERDICT, source=source, detail=d, log=log)


def record_disk_change(unit_id: str, *, changed_paths: Sequence[str], basis: str, source: str,
                       detail: Mapping[str, Any] | None = None,
                       log: ProgressLog | None = None) -> ProgressEvent:
    """The ONLY way this module accepts "bytes changed on disk". ``basis``
    must name a mechanical measurement (see :data:`DISK_EVIDENCE_BASES`);
    anything else is refused by :class:`ProgressEvent`'s own guard, not just
    by convention. Records NO_CHANGE (not silence) when ``changed_paths`` is
    empty -- "nothing changed" is itself an observed fact.
    """
    paths = [str(p) for p in (changed_paths or [])]
    d = dict(detail or {})
    d["basis"] = basis
    d["changed_paths"] = paths
    kind = DISK_CHANGED if paths else NO_CHANGE
    return _record(unit_id, kind, source=source, detail=d, log=log)


def record_patch_produced(unit_id: str, *, diff_sha256: str, changed_paths: Sequence[str],
                          byte_length: int, source: str, branch: str | None = None,
                          detail: Mapping[str, Any] | None = None,
                          log: ProgressLog | None = None) -> ProgressEvent:
    """Record PATCH_PRODUCED: candidate bytes exist in an ISOLATED worktree.

    NEVER call this for a change that landed in the primary checkout -- use
    :func:`record_disk_change` for that. See
    ``daedalus.spine.attempt``'s module docstring: "a patch that exists is
    not a change that landed." ``detail['applied']`` is hardcoded False here
    so a reader of the raw event, not just of the rendered summary, cannot
    mistake one for the other.
    """
    d = dict(detail or {})
    d.update(diff_sha256=diff_sha256, changed_paths=[str(p) for p in (changed_paths or [])],
             byte_length=int(byte_length), branch=branch, applied=False)
    return _record(unit_id, PATCH_PRODUCED, source=source, detail=d, log=log)


def record_done(unit_id: str, *, succeeded: bool | None, source: str, reason: str = "",
                applied: bool | None = None, detail: Mapping[str, Any] | None = None,
                log: ProgressLog | None = None) -> ProgressEvent:
    """Record DONE: terminal. ``succeeded`` and ``applied`` are independent
    facts and both may legitimately be ``None`` (e.g. a routing decision that
    never attempted anything has no verdict and nothing to apply) -- the
    caller must pass one explicitly rather than this function guessing.
    """
    d = dict(detail or {})
    d.update(succeeded=succeeded, applied=applied, reason=str(reason or ""))
    return _record(unit_id, DONE, source=source, detail=d, log=log)


# --------------------------------------------------------------------------- #
# reading -- a snapshot is always fresh, never cached                         #
# --------------------------------------------------------------------------- #
@dataclass
class UnitProgress:
    """What is known about one unit of work, AS OF ``observed_at``.

    Deliberately not frozen: it is a report built fresh on every call to
    :func:`snapshot`, mirroring ``daedalus.health.Report`` (mutable) rather
    than ``daedalus.health.Fact`` (frozen, a single immutable value).
    """

    unit_id: str
    observed_at: str
    found: bool
    events_seen: int
    kinds_seen: tuple[str, ...]
    latest_kind: str | None
    latest_source: str | None
    latest_ts: str | None
    age_s: float | None
    claimed_ts: str | None
    claimed_age_s: float | None
    terminal: bool
    succeeded: bool | None
    applied: bool | None
    stalled: bool
    fraction_hint: str
    facts: tuple[Fact, ...] = ()
    narrative: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id, "observed_at": self.observed_at,
            "found": self.found, "events_seen": self.events_seen,
            "kinds_seen": list(self.kinds_seen), "latest_kind": self.latest_kind,
            "latest_source": self.latest_source, "latest_ts": self.latest_ts,
            "age_s": None if self.age_s is None else round(self.age_s, 1),
            "claimed_ts": self.claimed_ts,
            "claimed_age_s": None if self.claimed_age_s is None else round(self.claimed_age_s, 1),
            "terminal": self.terminal, "succeeded": self.succeeded, "applied": self.applied,
            "stalled": self.stalled, "fraction_hint": self.fraction_hint,
            "facts": [f.to_dict() for f in self.facts],
            "narrative": list(self.narrative),
        }


def _unit_progress_from_events(unit_id: str, events: list[ProgressEvent], *, now: float,
                               stall_budget_s: float) -> UnitProgress:
    observed_at = now_iso()
    if not events:
        return UnitProgress(
            unit_id=unit_id, observed_at=observed_at, found=False, events_seen=0,
            kinds_seen=(), latest_kind=None, latest_source=None, latest_ts=None,
            age_s=None, claimed_ts=None, claimed_age_s=None, terminal=False,
            succeeded=None, applied=None, stalled=False,
            fraction_hint="no events recorded for this unit_id",
            facts=(assumed("unit_id", unit_id,
                           "caller-supplied; this log has nothing recorded for it"),),
            narrative=())

    events = sorted(events, key=lambda e: e.ts)
    latest = events[-1]
    kinds_seen = tuple(dict.fromkeys(e.kind for e in events))
    claimed = next((e for e in events if e.kind == CLAIMED), None)
    latest_age = max(0.0, now - parse_iso(latest.ts))
    claimed_age = max(0.0, now - parse_iso(claimed.ts)) if claimed else None

    done_events = [e for e in events if e.kind == DONE]
    terminal = bool(done_events)
    succeeded: bool | None = None
    applied: bool | None = None
    if done_events:
        last_done = done_events[-1].detail or {}
        succeeded = last_done.get("succeeded")
        applied = last_done.get("applied")
    if applied is None:
        disk_events = [e for e in events if e.kind in (DISK_CHANGED, NO_CHANGE)]
        if disk_events:
            applied = disk_events[-1].kind == DISK_CHANGED
        elif any(e.kind == PATCH_PRODUCED for e in events):
            applied = False  # a candidate patch is explicitly not landed

    # STALLED: claimed or actively working, no terminal event, and nothing
    # observed for longer than the budget. HEARTBEAT alone does not clear
    # this -- see the module docstring: aliveness is not progress.
    stalled = (not terminal and latest_age > stall_budget_s
              and latest.kind in (CLAIMED, GENERATING, HEARTBEAT, TOOL_RAN))

    facts: list[Fact] = []
    for kind in kinds_seen:
        last_of_kind = [e for e in events if e.kind == kind][-1]
        facts.append(measured(f"last {kind}", last_of_kind.detail or True))
    if GENERATING in kinds_seen:
        total_bytes = sum(int((e.detail or {}).get("nbytes", 0))
                          for e in events if e.kind == GENERATING)
        n_deltas = sum(1 for e in events if e.kind == GENERATING)
        facts.append(measured("bytes observed generating",
                              f"{total_bytes} across {n_deltas} delta(s)"))
    facts.append(Fact(label="last observed", value=f"{latest.kind} via {latest.source}",
                      provenance=INHERITED,
                      source=f"progress event ({latest.kind}, unit {unit_id})",
                      age_s=latest_age))

    return UnitProgress(
        unit_id=unit_id, observed_at=observed_at, found=True, events_seen=len(events),
        kinds_seen=kinds_seen, latest_kind=latest.kind, latest_source=latest.source,
        latest_ts=latest.ts, age_s=latest_age, claimed_ts=(claimed.ts if claimed else None),
        claimed_age_s=claimed_age, terminal=terminal, succeeded=succeeded, applied=applied,
        stalled=stalled,
        fraction_hint=("no percent-complete for a single unit: no task here declares a "
                      "total amount of work, so any number would be invented; see "
                      "batch_snapshot() for a real N-of-M fraction across a declared "
                      "set of units"),
        facts=tuple(facts),
        narrative=tuple(e.to_dict() for e in events))


def snapshot(unit_id: str, *, log: ProgressLog | None = None, now: float | None = None,
            stall_budget_s: float = DEFAULT_STALL_BUDGET_S) -> UnitProgress:
    """The current, honestly-aged picture of one unit. Recomputes everything
    from the raw events every call -- nothing here is cached across calls, on
    purpose (see the module docstring)."""
    log = log or default_log()
    events = log.events_for(str(unit_id))
    now = now if now is not None else time.time()
    return _unit_progress_from_events(str(unit_id), events, now=now, stall_budget_s=stall_budget_s)


@dataclass
class BatchProgress:
    """N-of-M terminal across a caller-declared (or batch-tagged) set of
    units -- the one place this module offers a real fraction."""

    batch_id: str
    observed_at: str
    total: int
    terminal: int
    succeeded: int
    fraction: Fact
    units: tuple[UnitProgress, ...]

    def to_dict(self) -> dict:
        return {"batch_id": self.batch_id, "observed_at": self.observed_at,
                "total": self.total, "terminal": self.terminal, "succeeded": self.succeeded,
                "fraction": self.fraction.to_dict(),
                "units": [u.to_dict() for u in self.units]}


def batch_snapshot(batch_id: str, unit_ids: Sequence[str] | None = None, *,
                   log: ProgressLog | None = None, now: float | None = None,
                   stall_budget_s: float = DEFAULT_STALL_BUDGET_S) -> BatchProgress:
    """A real N-of-M terminal fraction.

    ``unit_ids``, when given, is the honest denominator: "I dispatched
    exactly these M". Without it, the denominator is every unit_id this log
    has ever seen tagged with ``batch_id`` -- weaker, because it can only
    grow (a fraction read mid-dispatch under-counts M until the last unit is
    opened), and :attr:`fraction`'s ``detail`` says so rather than hiding it.
    """
    log = log or default_log()
    now = now if now is not None else time.time()
    if unit_ids:
        ids = list(dict.fromkeys(str(u) for u in unit_ids))
        basis = "caller-declared unit set (a firm denominator)"
    else:
        ids = sorted({e.unit_id for e in log.batch(batch_id)})
        basis = ("every unit_id observed under this batch_id so far -- this total "
                "can still grow; pass unit_ids explicitly for a firm denominator")
    units = tuple(snapshot(u, log=log, now=now, stall_budget_s=stall_budget_s) for u in ids)
    total = len(units)
    terminal = sum(1 for u in units if u.terminal)
    succeeded = sum(1 for u in units if u.succeeded)
    # Full precision, unrounded -- matching daedalus.health.Fact's own
    # posture (it rounds age_s only in to_dict()'s display form, never the
    # live value). Rounding a MEASURED number at construction time would
    # throw away precision a caller might legitimately want.
    frac_value = (terminal / total) if total else None
    fraction = Fact(label="terminal_fraction", value=frac_value, provenance=MEASURED)
    return BatchProgress(batch_id=str(batch_id), observed_at=now_iso(), total=total,
                         terminal=terminal, succeeded=succeeded, fraction=fraction, units=units)


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #
MARKS = {
    QUEUED: " queued ",
    CLAIMED: "claimed ",
    HEARTBEAT: "  alive ",
    GENERATING: " active ",
    TOOL_RAN: "tool ran",
    GATE_VERDICT: "  gated ",
    DISK_CHANGED: " wrote! ",
    NO_CHANGE: "no write",
    PATCH_PRODUCED: " patch  ",
    DONE: "  done  ",
}


def render(p: UnitProgress) -> str:
    lines: list[str] = []
    if not p.found:
        lines.append(f"  [ unknown] {p.unit_id}: no events recorded "
                     f"(checked at {p.observed_at})")
        return "\n".join(lines)

    mark = MARKS.get(p.latest_kind or "", "????????")
    if p.terminal:
        verdict = ("succeeded" if p.succeeded else
                   "FAILED" if p.succeeded is False else "resolved, no verdict recorded")
        applied_txt = ("landed on disk" if p.applied else
                       "NOT applied (candidate only, or rolled back)" if p.applied is False else
                       "applied: not recorded")
        headline = f"DONE -- {verdict}; {applied_txt}"
    elif p.stalled:
        headline = (f"STALLED -- last observed {p.latest_kind} "
                    f"{format_age(p.age_s)} ago, past the stall budget, no terminal event")
    else:
        headline = f"in flight -- last observed: {p.latest_kind}"

    lines.append(f"  [{mark}] {p.unit_id:<28} {headline}")
    lines.append(f"             claimed {format_age(p.claimed_age_s)} ago; "
                f"last observed {format_age(p.age_s)} ago via {p.latest_source}")
    for f in p.facts:
        lines.append(f"             - {f.label}: {f.value}   {f.tag()}")
    lines.append(f"             % complete: not offered -- {p.fraction_hint}")
    return "\n".join(lines)


def render_batch(b: BatchProgress) -> str:
    lines = [f"  batch {b.batch_id}: {b.terminal}/{b.total} terminal, "
            f"{b.succeeded}/{b.total} succeeded   {b.fraction.tag()}"]
    for u in b.units:
        lines.append("  " + render(u).replace("\n", "\n  "))
    return "\n".join(lines)


def to_payload(snaps: Sequence[UnitProgress]) -> dict:
    return {"schema": 1, "generated_at": now_iso(), "units": [s.to_dict() for s in snaps]}


# --------------------------------------------------------------------------- #
# cli                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Honest in-flight progress: what was OBSERVED, vs what "
                    "merely STARTED.")
    ap.add_argument("unit_id", nargs="?",
                    help="one unit id; omitted = every unit this log has seen")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--log-path", help="override the JSONL log path")
    ap.add_argument("--ledger", action="store_true",
                    help="also poll the spine ledger for open attempt.candidate "
                         "intents (concurrent TaskAttempt writes)")
    args = ap.parse_args(argv)

    log = ProgressLog(args.log_path) if args.log_path else default_log()
    if args.unit_id:
        snaps = [snapshot(args.unit_id, log=log)]
    else:
        snaps = [snapshot(u, log=log) for u in log.units()]

    if args.ledger:
        from . import progress_sources
        snaps += progress_sources.open_attempts()

    if args.json:
        print(json.dumps(to_payload(snaps), indent=2, default=str))
        return 0

    print("daedalus progress -- observed, not narrated\n")
    if not snaps:
        print("  no in-flight units recorded "
             f"(log: {log.path if not args.log_path else args.log_path})")
    for s in snaps:
        print(render(s))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
