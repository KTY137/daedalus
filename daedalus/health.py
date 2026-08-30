# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Is the SYSTEM working, or is it merely PRESENT? -- the operator's glance.

WHY THIS EXISTS. In one day this repo shipped three live escapes under three
fully green suites. Every one of them was the same mistake wearing a different
hat:

    a task queue dropped tasks while 1756 unit tests were green
    semantic_route was listed as a feature while unwired AND broken if wired
    memory/vectors.db has never existed, and a planner weighted it at 0.35
    spine/containment.py shipped 11 measured properties and 0 callers
    docs/architecture-state.json described a tree 30 commits behind

    -> CAPABILITY PRESENT IN THE CODE WAS REPORTED AS CAPABILITY WORKING.

`daedalus doctor` prints ``[OK] claude CLI on PATH``. That is true and it is
not what an operator reads it as: it reads as "the senior lane works". A
surface with two symbols (OK / not-OK) cannot say the thing that was actually
true in all five cases -- *the code is here, and nothing has run it*. So this
module has five, and no way to collapse them.

FIVE STATES. Only ONE of them is good news.

    working    exercised JUST NOW by this run, and here is the measurement
    present    the code is here; NOTHING in this run exercised it
    degraded   it ran, and what came back is wrong -- with the reason
    absent     it is not here at all
    unknown    the check COULD NOT RUN. Never green, never silent, never a skip

``unknown`` is the load-bearing one. A check that cannot run is the single way
every collapsed surface in this repo has lied: it went quiet and the quiet read
as coverage. There is deliberately NO ``skipped`` in the vocabulary --
:func:`_coerce` rejects any word outside :data:`STATES`, so a future probe
cannot invent a sixth state that renders as a pass.

EVERY NUMBER CARRIES ITS PROVENANCE. Following the tag this repo already uses
in budget.py, canary.py and the handoffs:

    MEASURED    produced by THIS run, against the live thing
    INHERITED   read out of a file -- reported WITH the file's age
    ASSUMED     a default, a config or a doc; nothing checked it

:class:`Fact` refuses to be constructed as INHERITED without a source and an
age, so a file read cannot be smuggled in wearing a measurement's clothes.

    python -m daedalus.health              # the glance
    python -m daedalus.health --json       # machine-readable
    python -m daedalus.health --probe-remote   # also EXERCISE the bench host

NOT A SECOND tools/system_check.py. That harness clones the tree and RUNS the
product end to end; it answers "does the pipeline execute". This reads the LIVE
artefacts in the tree you are standing in and exercises only cheap read paths;
it answers "what is the state of this machine right now, and which parts of
that answer did anything actually check". They overlap nowhere: system_check
never looks at your real outbox, and this never runs an attempt.

NOTHING HERE SPENDS MONEY. No probe invokes a vendor CLI or a paid API. The
only network calls are ``/api/tags`` and one embedding of a fixed literal
string against Ollama hosts -- free, and carrying no repository content.

NOTHING HERE WRITES. The spine ledger is opened ``read_only=True`` (its normal
constructor mkdirs, sets WAL and migrates -- merely opening it writes). The
vector index is inspected with sqlite ``mode=ro`` and its existence is tested
BEFORE any store object is built, because EventVectorStore creates the file it
is pointed at. The room is read only if room.md already exists, because
``transcript()`` creates it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# the vocabulary -- closed on purpose                                          #
# --------------------------------------------------------------------------- #
WORKING = "working"
PRESENT = "present"
DEGRADED = "degraded"
ABSENT = "absent"
UNKNOWN = "unknown"

#: The ONLY five words a probe may return. There is no "skipped", no "n/a" and
#: no "ok": each of those is a way of not answering that has historically been
#: read as an answer.
STATES = (WORKING, PRESENT, DEGRADED, ABSENT, UNKNOWN)

#: States that mean "this run did not establish that the thing works".
NOT_PROVEN = (PRESENT, UNKNOWN, ABSENT)

MEASURED = "MEASURED"
INHERITED = "INHERITED"
ASSUMED = "ASSUMED"
PROVENANCE = (MEASURED, INHERITED, ASSUMED)

EXIT_OK, EXIT_BAD, EXIT_UNPROVEN = 0, 1, 2

#: Sent to embedding backends to prove the transport answers. A FIXED LITERAL,
#: never repository content: the bench host at 100.119.126.9 is outside this
#: machine and the safety fence refuses repo content there for good reason.
#: Changing this to anything derived from the tree is an egress regression.
PROBE_TEXT = "daedalus health probe"

LOCAL_OLLAMA = "http://127.0.0.1:11434"
BENCH_OLLAMA = os.environ.get("DAEDALUS_RTX_OLLAMA_HOST", "http://100.119.126.9:11434")
EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

#: The bench's ssh endpoint, for the two diagnostics Ollama's own HTTP API
#: cannot answer -- there is no /api free-space and no /api crash-history
#: call: is the auto-start task configured to survive a headless reboot, and
#: is llama-server.exe crash-looping. Read-only `Get-ScheduledTask` /
#: `Get-WinEvent` on the far end; nothing here stops or restarts anything.
BENCH_SSH_HOST = os.environ.get("DAEDALUS_RTX_SSH_HOST", "Administrator@100.119.126.9")
BENCH_TASK_NAME = os.environ.get("DAEDALUS_RTX_TASK_NAME", "DaedalusOllamaServe")
#: Wall-clock ceiling for the WHOLE ssh round trip (connect + remote query).
#: Kept short on purpose: this module is also a 10s VS Code status-bar
#: shell-out (see Ctx.deep), and an unreachable bench must fail FAST, not
#: spend that budget finding out.
BENCH_SSH_TIMEOUT_S = 9.0


class ProvenanceError(ValueError):
    """A fact was asserted without saying where it came from."""


# --------------------------------------------------------------------------- #
# facts                                                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Fact:
    """One number or string, and the reason you may believe it.

    The constructor is the guard. An INHERITED fact without a source and an age
    is exactly how "the map says the tree looks like this" became "the tree
    looks like this" -- so it cannot be built.
    """

    label: str
    value: Any
    provenance: str
    source: str | None = None
    age_s: float | None = None

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE:
            raise ProvenanceError(
                f"{self.label!r}: provenance {self.provenance!r} is not one of "
                f"{PROVENANCE}")
        if self.provenance == INHERITED:
            if not self.source:
                raise ProvenanceError(
                    f"{self.label!r}: INHERITED without naming the file it came from")
            if self.age_s is None:
                raise ProvenanceError(
                    f"{self.label!r}: INHERITED without an age -- a stale file "
                    f"read as fresh is the defect this surface exists to catch")
        if self.provenance == ASSUMED and not self.source:
            raise ProvenanceError(
                f"{self.label!r}: ASSUMED without naming where the assumption "
                f"is written")

    def tag(self) -> str:
        if self.provenance == INHERITED:
            return f"[{INHERITED} {_ago(self.age_s)} from {self.source}]"
        if self.provenance == ASSUMED:
            return f"[{ASSUMED}; declared in {self.source}]"
        return f"[{MEASURED} just now]"

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value,
                "provenance": self.provenance, "source": self.source,
                "age_s": None if self.age_s is None else round(self.age_s, 1)}


def measured(label: str, value: Any) -> Fact:
    """A number this run produced against the live thing."""
    return Fact(label, value, MEASURED)


def inherited(label: str, value: Any, source: str | Path,
              *, now: float | None = None) -> Fact:
    """A number read out of a file, carrying that file's age."""
    p = Path(source)
    try:
        age = max(0.0, (now if now is not None else time.time()) - p.stat().st_mtime)
    except OSError:
        age = None
    if age is None:
        # The file vanished between the read and the stat; that is itself worth
        # saying, and it must not be reported as a measurement.
        return Fact(label, value, INHERITED, source=_rel(p), age_s=float("inf"))
    return Fact(label, value, INHERITED, source=_rel(p), age_s=age)


def assumed(label: str, value: Any, where: str) -> Fact:
    """A default or a doc. Nothing checked it."""
    return Fact(label, value, ASSUMED, source=where)


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except (ValueError, OSError):
        return str(p)


def _ago(age_s: float | None) -> str:
    if age_s is None:
        return "age unknown"
    if age_s == float("inf"):
        return "file gone"
    if age_s < 90:
        return f"{age_s:.0f}s old"
    if age_s < 5400:
        return f"{age_s / 60:.0f}m old"
    if age_s < 172800:
        return f"{age_s / 3600:.1f}h old"
    return f"{age_s / 86400:.1f}d old"


# --------------------------------------------------------------------------- #
# reports                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    name: str
    state: str
    headline: str = ""
    facts: tuple[Fact, ...] = ()
    remedy: str = ""
    asks: str = ""
    required: bool = True
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "asks": self.asks, "state": self.state,
                "headline": self.headline, "remedy": self.remedy,
                "required": self.required,
                "facts": [f.to_dict() for f in self.facts],
                "seconds": round(self.seconds, 2)}


def working(name: str, headline: str, facts: Iterable[Fact], **kw) -> Report:
    return Report(name, WORKING, headline, tuple(facts), **kw)


def present(name: str, headline: str, facts: Iterable[Fact] = (), **kw) -> Report:
    return Report(name, PRESENT, headline, tuple(facts), **kw)


def degraded(name: str, headline: str, facts: Iterable[Fact] = (), **kw) -> Report:
    return Report(name, DEGRADED, headline, tuple(facts), **kw)


def absent(name: str, headline: str, facts: Iterable[Fact] = (), **kw) -> Report:
    return Report(name, ABSENT, headline, tuple(facts), **kw)


def unknown(name: str, headline: str, facts: Iterable[Fact] = (), **kw) -> Report:
    return Report(name, UNKNOWN, headline, tuple(facts), **kw)


# --------------------------------------------------------------------------- #
# the registry                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class ProbeSpec:
    name: str
    asks: str
    fn: Callable[["Ctx"], Report]
    required: bool = True


PROBES: list[ProbeSpec] = []


def probe(name: str, *, asks: str, required: bool = True):
    """Register a probe. ``required=False`` means "absent here is a legitimate
    configuration", never "soften this when it keeps coming back unknown"."""

    def deco(fn):
        PROBES.append(ProbeSpec(name=name, asks=asks, fn=fn, required=required))
        return fn

    return deco


@dataclass
class Ctx:
    """What every probe is given. No probe reaches around this for a path."""

    repo_root: Path = ROOT
    probe_remote: bool = False
    #: For cheap reads (``/api/tags``, git). Short on purpose.
    timeout_s: float = 6.0
    #: For the one embedding call. Generous, because a COLD model load is slow
    #: and a timeout would report `degraded` about the clock rather than about
    #: the backend -- a false alarm is the same lie as a false all-clear.
    embed_timeout_s: float = 15.0
    #: Run the probes that EXERCISE an expensive path (the latent router costs
    #: ~7s cold because it embeds every agent description). Off by default so
    #: the glance stays a glance -- and, crucially, so the VS Code status bar's
    #: 10s shell-out does not start timing out. A probe skipped for cost
    #: reports `present`, never `working`, so the default run still cannot
    #: claim anything it did not do.
    deep: bool = False
    now: float = field(default_factory=time.time)


# --------------------------------------------------------------------------- #
# the guards -- the reason a green line here means something                   #
# --------------------------------------------------------------------------- #
def _coerce(spec: ProbeSpec, value: Any, seconds: float) -> Report:
    """Turn whatever a probe did into a Report that cannot lie.

    FOUR SEPARATE WAYS A PROBE CAN FAIL TO ANSWER, all of which used to be a
    pass somewhere in this repo's history:

      1. it raised                      -> unknown, with the exception
      2. it returned None               -> unknown, "returned nothing"
      3. it returned a state we do not  -> unknown, naming the bad word
         recognise (e.g. "skipped")        so nobody can invent a sixth state
      4. it claimed WORKING with no     -> unknown, "claimed working with no
         MEASURED fact                     measurement"

    (4) is the one that matters most. "working" in this vocabulary means
    EXERCISED JUST NOW; a probe that reads a file and says working is doing the
    exact thing the map did when it described a tree thirty commits away. The
    only way to say working is to hand back something this run measured.
    """
    if isinstance(value, BaseException):
        rep = unknown(spec.name,
                      f"the probe itself raised: "
                      f"{type(value).__name__}: {value}")
    elif value is None:
        rep = unknown(spec.name, "the probe returned nothing, so nothing is known")
    elif not isinstance(value, Report):
        rep = unknown(spec.name,
                      f"the probe returned {type(value).__name__}, not a Report")
    elif value.state not in STATES:
        rep = unknown(spec.name,
                      f"the probe reported state {value.state!r}, which is not "
                      f"one of {STATES} -- refusing to render an unrecognised "
                      f"word as a pass",
                      value.facts)
    elif value.state == WORKING and not any(
            f.provenance == MEASURED for f in value.facts):
        rep = unknown(spec.name,
                      "claimed WORKING with no MEASURED evidence -- 'working' "
                      "means exercised by this run, and nothing was",
                      value.facts, remedy=value.remedy)
    else:
        rep = value
    rep.name = spec.name
    rep.asks = spec.asks
    rep.required = spec.required
    rep.seconds = seconds
    return rep


def assess(only: str | None = None, *, repo_root: str | Path | None = None,
           probe_remote: bool = False, deep: bool = False,
           timeout_s: float = 6.0) -> list[Report]:
    ctx = Ctx(repo_root=Path(repo_root).resolve() if repo_root else ROOT,
              probe_remote=probe_remote, deep=deep, timeout_s=timeout_s)
    _SOURCE_CACHE.clear()
    _SSH_CACHE.clear()
    out: list[Report] = []
    for spec in PROBES:
        if only and only not in spec.name:
            continue
        t0 = time.time()
        try:
            value: Any = spec.fn(ctx)
        except BaseException as exc:            # noqa: BLE001 - see _coerce
            if isinstance(exc, KeyboardInterrupt):
                raise
            value = exc
        out.append(_coerce(spec, value, time.time() - t0))
    return out


def verdict(reports: Sequence[Report]) -> int:
    """0 only when EVERY probe was exercised and held.

    ``unknown`` and ``present`` both land on 2 rather than 0 because both mean
    the same thing to an operator: this run did not establish that the thing
    works. Collapsing them into 0 is the whole defect.
    """
    bad = [r for r in reports
           if r.state == DEGRADED or (r.state == ABSENT and r.required)]
    if bad:
        return EXIT_BAD
    if any(r.state in NOT_PROVEN for r in reports):
        return EXIT_UNPROVEN
    return EXIT_OK


#: How each state prints. Deliberately NOT symmetric-looking: `working` is the
#: only lowercase-quiet one, everything else is visually louder, so a screen of
#: `present` cannot be skimmed as a screen of green.
MARKS = {
    WORKING: "  works ",
    PRESENT: "PRESENT?",
    DEGRADED: "DEGRADED",
    ABSENT: " ABSENT ",
    UNKNOWN: "UNKNOWN!",
}


def render(reports: Sequence[Report], *, verbose: bool = True) -> str:
    lines: list[str] = []
    for r in reports:
        lines.append(f"  [{MARKS.get(r.state, '???')}] {r.name:<24} {r.headline}")
        if verbose:
            for f in r.facts:
                lines.append(f"             - {f.label}: {f.value}   {f.tag()}")
        if r.remedy:
            lines.append(f"             -> {r.remedy}")
    counts = {s: sum(1 for r in reports if r.state == s) for s in STATES}
    code = verdict(reports)
    lines.append("")
    lines.append("  " + "-" * 68)
    lines.append(
        f"  {counts[WORKING]} working / {counts[DEGRADED]} degraded / "
        f"{counts[PRESENT]} present-but-unexercised / {counts[ABSENT]} absent / "
        f"{counts[UNKNOWN]} unknown   ({len(reports)} subsystems)")
    if counts[PRESENT] or counts[UNKNOWN]:
        lines.append(
            "  NOT PROVEN by this run (present/unknown are not pass): "
            + ", ".join(r.name for r in reports if r.state in (PRESENT, UNKNOWN)))
    lines.append("  VERDICT: " + {
        EXIT_OK: "every subsystem was exercised and held",
        EXIT_BAD: "at least one subsystem is DEGRADED or missing",
        EXIT_UNPROVEN: "nothing is broken that ran -- but not everything ran",
    }[code] + f"  (exit {code})")
    return "\n".join(lines)


def to_payload(reports: Sequence[Report]) -> dict:
    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "states": list(STATES),
        "counts": {s: sum(1 for r in reports if r.state == s) for s in STATES},
        "verdict": verdict(reports),
        "not_proven": [r.name for r in reports if r.state in (PRESENT, UNKNOWN)],
        "subsystems": [r.to_dict() for r in reports],
    }


# --------------------------------------------------------------------------- #
# small shared readers                                                         #
# --------------------------------------------------------------------------- #
def _git(root: Path, args: Sequence[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(root), text=True,
                           capture_output=True, check=False, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout or "").strip() or (p.stderr or "").strip()


def _http_json(url: str, timeout: float, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _age_of(path: Path, now: float) -> float | None:
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# 1 -- the tree we are standing in                                             #
# --------------------------------------------------------------------------- #
@probe("git.worktree", asks="which tree is every other answer about?")
def _p_git(ctx: Ctx) -> Report:
    rc, head = _git(ctx.repo_root, ["rev-parse", "HEAD"])
    if rc != 0:
        return unknown("git.worktree",
                       f"git could not report HEAD here: {head[:160]}",
                       remedy="every freshness answer below is relative to HEAD; "
                              "without it they are all unknown too")
    _, branch = _git(ctx.repo_root, ["branch", "--show-current"])
    _, porcelain = _git(ctx.repo_root, ["status", "--porcelain"])
    dirty = [l for l in porcelain.splitlines() if l.strip()]
    facts = [measured("head", head[:12]),
             measured("branch", branch or "(detached)"),
             measured("dirty paths", len(dirty))]
    if dirty:
        return working("git.worktree",
                       f"{head[:12]} on {branch or 'detached'}, "
                       f"{len(dirty)} uncommitted path(s)", facts)
    return working("git.worktree", f"{head[:12]} on {branch or 'detached'}, clean",
                   facts)


# --------------------------------------------------------------------------- #
# 2 -- the generated map: does it describe THIS tree?                          #
# --------------------------------------------------------------------------- #
@probe("map.snapshot", asks="does the architecture snapshot describe this tree?")
def _p_map(ctx: Ctx) -> Report:
    path = ctx.repo_root / "docs" / "architecture-state.json"
    if not path.exists():
        return absent("map.snapshot", f"{_rel(path)} does not exist",
                      remedy="daedalus map")
    try:
        from .mapping import drift
    except Exception as exc:                    # noqa: BLE001
        return unknown("map.snapshot",
                       f"the drift module will not import: "
                       f"{type(exc).__name__}: {exc}")
    doc = drift.load_snapshot(path)
    if doc is None or doc.get("__error__"):
        return degraded("map.snapshot",
                        f"the snapshot could not be parsed: "
                        f"{(doc or {}).get('__error__', 'unreadable')}",
                        [inherited("path", _rel(path), path, now=ctx.now)],
                        remedy="daedalus map")
    intact = drift.digest_ok(doc)
    fresh = drift.snapshot_freshness(doc, repo_root=ctx.repo_root)
    facts = [
        inherited("recorded head", fresh.get("recorded_head"), path, now=ctx.now),
        measured("actual head", fresh.get("actual_head")),
        measured("digest verifies", intact),
        inherited("modules described", len(doc.get("modules") or []), path,
                  now=ctx.now),
    ]
    if not intact:
        return degraded("map.snapshot",
                        "the snapshot's own digest does NOT cover its contents "
                        "-- it was hand-edited", facts,
                        remedy="python -m daedalus.mapping.drift --refresh")
    if not fresh.get("fresh"):
        return degraded("map.snapshot", str(fresh.get("reason")), facts,
                        remedy="daedalus map   (until then the picker withholds "
                               "every map-derived candidate)")
    return working("map.snapshot",
                   "the snapshot's digest verifies and it matches HEAD", facts)


# --------------------------------------------------------------------------- #
# 3 -- the picker: is there a queue, and did every source speak?               #
# --------------------------------------------------------------------------- #
@probe("picker.queue", asks="does the loop know what to do next, and why?")
def _p_picker(ctx: Ctx) -> Report:
    try:
        from .spine.picker import build_queue
    except Exception as exc:                    # noqa: BLE001
        return unknown("picker.queue",
                       f"the picker will not import: {type(exc).__name__}: {exc}")
    queue = build_queue(ctx.repo_root, limit=10)
    degraded_sources = list(queue.degraded_sources)
    healthy = sorted(set(queue.sources) - set(degraded_sources))
    facts = [
        measured("candidates ranked", len(queue.candidates)),
        measured("sources consulted", ", ".join(healthy) or "none"),
        measured("sources DEGRADED", ", ".join(degraded_sources) or "none"),
    ]
    if queue.candidates:
        top = queue.candidates[0]
        facts.append(measured("top candidate",
                              f"{top.task_id} ({top.source}, score {top.score})"))
    withheld = [n for n in queue.notes if "SUPPRESSED" in n]
    if degraded_sources:
        # THE CENTRAL DISTINCTION. "the sources are healthy and there is no
        # work" and "a source could not be read" produce the same empty list;
        # only this branch keeps them apart.
        return degraded("picker.queue",
                        f"{len(degraded_sources)} source(s) could not be used "
                        f"({', '.join(degraded_sources)}); "
                        f"{len(queue.candidates)} candidate(s) survive",
                        facts + [measured("withheld", w[:160]) for w in withheld],
                        remedy="the queue is not a picture of the work, it is a "
                               "picture of what could still be read")
    if not queue.candidates:
        return working("picker.queue",
                       "every source was read and none of them names any work",
                       facts)
    return working("picker.queue",
                   f"{len(queue.candidates)} candidate(s), every source readable",
                   facts)


# --------------------------------------------------------------------------- #
# 4 -- the spine ledger (READ ONLY: opening it normally would WRITE)           #
# --------------------------------------------------------------------------- #
@probe("spine.ledger", asks="is there an intent ledger, and did anything crash?")
def _p_ledger(ctx: Ctx) -> Report:
    try:
        from .spine.ledger import SpineLedger, default_db_path
    except Exception as exc:                    # noqa: BLE001
        return unknown("spine.ledger",
                       f"the ledger module will not import: "
                       f"{type(exc).__name__}: {exc}")
    path = default_db_path()
    if not Path(path).exists():
        # Do NOT construct the normal ledger to find this out: that path
        # mkdirs, flips the file to WAL and runs migrations, i.e. a status read
        # would CREATE the thing it was asked to observe.
        return absent("spine.ledger",
                      f"no ledger at {_rel(Path(path))} -- nothing has recorded "
                      f"an intent on this machine yet",
                      remedy="it is written on the first attempt; absent is "
                             "normal on a fresh clone, and is not 'working'")
    ledger = None
    try:
        ledger = SpineLedger(path, read_only=True)
        recent = ledger.recent_intents(limit=200)
        open_ = ledger.open_intents()
    except Exception as exc:                    # noqa: BLE001
        return unknown("spine.ledger",
                       f"the ledger exists but could not be read: "
                       f"{type(exc).__name__}: {exc}",
                       [inherited("path", _rel(Path(path)), Path(path), now=ctx.now)])
    finally:
        if ledger is not None:
            ledger.close()

    stale_open = [i for i in open_ if _iso_age(i.created_ts, ctx.now) > 3600]
    kinds = sorted({i.kind for i in recent})
    facts = [
        measured("intents recorded (last 200)", len(recent)),
        measured("kinds", ", ".join(kinds) or "none"),
        measured("open intents", len(open_)),
        inherited("ledger file", _rel(Path(path)), Path(path), now=ctx.now),
    ]
    if stale_open:
        return degraded("spine.ledger",
                        f"{len(stale_open)} intent(s) recorded but never "
                        f"resolved and older than an hour -- an effect was "
                        f"begun and its acknowledgement lost",
                        facts + [measured("oldest unresolved",
                                          f"#{stale_open[0].id} {stale_open[0].kind} "
                                          f"at {stale_open[0].created_ts}")],
                        remedy="these are the crash-recovery worklist; reconcile "
                               "each against the world before trusting the loop")
    if not recent:
        return present("spine.ledger",
                       "the ledger exists and is EMPTY -- the write path has "
                       "never run here", facts)
    return working("spine.ledger",
                   f"read {len(recent)} intent(s), {len(open_)} still open", facts)


def _iso_age(ts: str, now: float) -> float:
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, now - dt.timestamp())


# --------------------------------------------------------------------------- #
# 5 -- the file bridge: is anything queued that nobody will ever pick up?      #
# --------------------------------------------------------------------------- #
@probe("bridge.queue", asks="will a queued task actually be picked up?")
def _p_bridge(ctx: Ctx) -> Report:
    try:
        from . import file_bridge as fb
    except Exception as exc:                    # noqa: BLE001
        return unknown("bridge.queue",
                       f"the bridge will not import: {type(exc).__name__}: {exc}")
    pending = sorted(fb.OUTBOX.glob("*.json")) if fb.OUTBOX.exists() else []
    reports = sorted(fb.INBOX.glob("*.report.json")) if fb.INBOX.exists() else []
    archived = sorted(fb.ARCHIVE.glob("*.json")) if fb.ARCHIVE.exists() else []
    hb = fb.heartbeat_status(now=ctx.now)
    state = hb.get("state")
    try:
        unread = len(fb.unread_reports())
    except Exception:                            # noqa: BLE001
        unread = None

    facts = [
        measured("queued (outbox)", len(pending)),
        measured("reports (inbox)", len(reports)),
        measured("archived requests", len(archived)),
        measured("watcher state", state),
    ]
    if unread is not None:
        facts.append(measured("unread reports", unread))
    if hb.get("age_s") is not None:
        facts.append(measured("last heartbeat", _ago(hb["age_s"])))
    if hb.get("repo_root"):
        facts.append(measured("watcher repo", hb["repo_root"]))

    if state in ("stale", "none"):
        # THE MEASURED ESCAPE, in one line. A queue with no consumer is not an
        # idle queue; it is a queue that drops work, and nothing else in this
        # repo says so out loud.
        head = (f"{len(pending)} task(s) queued and the watcher is "
                f"{'DEAD' if state == 'stale' else 'NOT RUNNING'} -- they will "
                f"sit forever") if pending else (
            f"no watcher ({state}); anything enqueued now would sit unprocessed")
        return degraded("bridge.queue", head, facts,
                        remedy=hb.get("restart", ""))
    if state == "wedged":
        return degraded("bridge.queue",
                        f"the watcher has been on one task for "
                        f"{hb.get('busy_for_s')}s, past its budget", facts,
                        remedy=hb.get("restart", ""))
    if state == "busy":
        return working("bridge.queue",
                       f"watcher alive and working a task "
                       f"({hb.get('busy_for_s')}s in)", facts)
    return working("bridge.queue",
                   f"watcher alive, {len(pending)} queued", facts)


# --------------------------------------------------------------------------- #
# 6 -- the operational memory journal                                          #
# --------------------------------------------------------------------------- #
@probe("memory.journal", asks="is the append-only event log real and current?")
def _p_journal(ctx: Ctx) -> Report:
    try:
        from .memory import EVENTS_PATH
    except Exception as exc:                    # noqa: BLE001
        return unknown("memory.journal",
                       f"the memory package will not import: "
                       f"{type(exc).__name__}: {exc}")
    if not EVENTS_PATH.exists():
        return absent("memory.journal",
                      f"{_rel(EVENTS_PATH)} does not exist -- nothing has ever "
                      f"been recorded on this machine", required=False)
    bad = 0
    count = 0
    last: dict | None = None
    with EVENTS_PATH.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            count += 1
            try:
                last = json.loads(line)
            except ValueError:
                bad += 1
    age = _age_of(EVENTS_PATH, ctx.now)
    facts = [
        measured("events parsed", count),
        measured("unparsable lines", bad),
        inherited("last write", _ago(age), EVENTS_PATH, now=ctx.now),
    ]
    if last:
        facts.append(inherited("last event", f"{last.get('kind')} / "
                                             f"{str(last.get('summary'))[:60]}",
                               EVENTS_PATH, now=ctx.now))
    if bad:
        return degraded("memory.journal",
                        f"{bad} line(s) in the journal are not JSON", facts)
    return working("memory.journal",
                   f"{count} event(s) readable, last write {_ago(age)}", facts)


# --------------------------------------------------------------------------- #
# 7 -- the vector index. NEVER CREATE IT BY LOOKING.                           #
# --------------------------------------------------------------------------- #
@probe("memory.vector_index",
       asks="does the latent memory the planner weights actually exist?")
def _p_vectors(ctx: Ctx) -> Report:
    try:
        from .memory import VECTOR_DB_PATH
    except Exception as exc:                    # noqa: BLE001
        return unknown("memory.vector_index",
                       f"the memory package will not import: "
                       f"{type(exc).__name__}: {exc}")
    enabled = os.environ.get("DAEDALUS_VECTOR_INDEX", "").strip() in (
        "1", "true", "yes")
    if not VECTOR_DB_PATH.exists():
        # EventVectorStore(path) CREATES the file and its schema. Testing
        # existence first is the difference between observing the system and
        # becoming the reason it looks healthy.
        return absent("memory.vector_index",
                      f"{_rel(VECTOR_DB_PATH)} has never existed -- every "
                      f"latent-memory answer in this repo is empty by "
                      f"construction",
                      [assumed("ingestion enabled", enabled,
                               "DAEDALUS_VECTOR_INDEX env var")],
                      remedy="set DAEDALUS_VECTOR_INDEX=1 and re-ingest, or stop "
                             "weighting a source that has never spoken")
    try:
        uri = "file:" + str(VECTOR_DB_PATH).replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            # THE TABLE NAMES WERE GUESSED, AND THEY WERE WRONG.
            #
            # This looked for `agent_event_projections` and `agent_events`.
            # The schema the projection worker actually writes is
            # `event_projections` / `projection_sources`, so the probe fell
            # through both branches and reported n=0. Measured: the file held
            # 172 projections while this surface said "the index file exists
            # and holds ZERO projections -- it can answer nothing".
            #
            # That is a health surface manufacturing an ABSENT capability out
            # of a working one, which is the same failure it exists to catch,
            # pointed the other way. Resolved from the schema instead of from
            # memory, and a table this does not recognise is reported as such
            # rather than counted as zero.
            projection_tables = sorted(
                t for t in tables if t.endswith("event_projections"))
            n = 0
            unknown_shape = not projection_tables
            for t in projection_tables:
                n += con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            indexes = 0
            if "embedding_indexes" in tables:
                indexes = con.execute(
                    "SELECT COUNT(*) FROM embedding_indexes").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        return unknown("memory.vector_index",
                       f"the index exists but sqlite could not read it: {exc}")
    facts = [measured("projections", n), measured("declared indexes", indexes),
             inherited("db", _rel(VECTOR_DB_PATH), VECTOR_DB_PATH, now=ctx.now),
             assumed("ingestion enabled", enabled,
                     "DAEDALUS_VECTOR_INDEX env var")]
    if unknown_shape:
        # "I do not recognise this schema" is not "there is nothing in it".
        # Reporting zero here is how the previous version turned a populated
        # index into an ABSENT capability.
        return unknown("memory.vector_index",
                       f"the index exists but holds no table this probe "
                       f"recognises (found: {', '.join(sorted(tables)) or 'none'})",
                       facts)
    if n == 0:
        return present("memory.vector_index",
                       "the index file exists and holds ZERO projections -- it "
                       "can answer nothing", facts)
    return working("memory.vector_index", f"{n} projection(s) readable", facts)


# --------------------------------------------------------------------------- #
# 8/9 -- the embedding backends, on both hosts                                 #
# --------------------------------------------------------------------------- #
def _embed_probe(ctx: Ctx, name: str, host: str, *, exercise: bool,
                 why_not: str = "") -> Report:
    """Tags first (free, no content), then optionally ONE real embedding.

    The vector is what separates the two states this repo keeps confusing: a
    model TAG in `/api/tags` proves the weights are on disk, and nothing else.
    Only a returned vector proves the transport the product actually uses --
    ``POST /api/embed`` through OllamaEmbeddingBackend -- answers.
    """
    try:
        data = _http_json(host.rstrip("/") + "/api/tags", ctx.timeout_s)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return degraded(name, f"{host} did not answer /api/tags: {exc}",
                        [measured("host", host)],
                        remedy=f"start it:  OLLAMA_HOST={host} ollama serve")
    tags = [m.get("model") or m.get("name") for m in (data.get("models") or [])]
    stem = EMBED_MODEL.split(":")[0]
    has = [t for t in tags if stem in (t or "")]
    facts = [measured("host", host), measured("models pulled", len(tags)),
             measured(f"{EMBED_MODEL} pulled", bool(has))]
    if not has:
        return degraded(name,
                        f"{host} is up but has no {EMBED_MODEL}; "
                        f"{len(tags)} other model(s)", facts,
                        remedy=f"OLLAMA_HOST={host} ollama pull {EMBED_MODEL}")
    if not exercise:
        return present(name,
                       f"{host} lists {EMBED_MODEL}; NO vector was produced by "
                       f"this run ({why_not})", facts,
                       remedy="pass --probe-remote to actually embed against it")
    try:
        from .memory.embeddings import OllamaEmbeddingBackend
        backend = OllamaEmbeddingBackend(host, timeout=ctx.embed_timeout_s)
        t0 = time.time()
        vectors = backend.embed([PROBE_TEXT], model=EMBED_MODEL)
        took = time.time() - t0
    except Exception as exc:                     # noqa: BLE001
        return degraded(name,
                        f"{EMBED_MODEL} is pulled on {host} but the product's "
                        f"own transport failed: {type(exc).__name__}: {exc}",
                        facts)
    if not vectors or not isinstance(vectors[0], list) or not vectors[0]:
        return degraded(name, f"{host} answered with no usable vector", facts)
    facts += [measured("vector dimension", len(vectors[0])),
              measured("embed latency", f"{took * 1000:.0f}ms")]
    return working(name,
                   f"embedded a {len(vectors[0])}-dim vector through the "
                   f"product's own backend in {took * 1000:.0f}ms", facts)


@probe("embed.local", asks="can this machine turn text into a vector?")
def _p_embed_local(ctx: Ctx) -> Report:
    return _embed_probe(ctx, "embed.local", LOCAL_OLLAMA, exercise=True)


@probe("embed.bench", asks="can the bench host turn text into a vector?",
       required=False)
def _p_embed_bench(ctx: Ctx) -> Report:
    return _embed_probe(
        ctx, "embed.bench", BENCH_OLLAMA, exercise=ctx.probe_remote,
        why_not="off by default: the bench is off this machine and the fence "
                "refuses repo content there")


# --------------------------------------------------------------------------- #
# 9b -- free disk: the failure NONE of the other probes could see              #
# --------------------------------------------------------------------------- #
# MEASURED 2026-07-29. The bench's system volume reached 0.2 GB free of 921 GB
# because a 68 GB ollama model store sat on it. Large models began returning
# HTTP 500 on load. Every probe in this file returned green throughout:
# `/api/tags` lists already-known metadata, needs no free space, and answers 200
# on a full disk. The one probe that exercises real work (`embed.bench` with
# --probe-remote) is off by default. So the harness watched a disk fill up and
# had nothing to say about it.
#
# A free-space number is the cheapest possible probe and it is the one that was
# missing. Below ~1 GB Windows stops behaving predictably at all -- the pagefile
# cannot grow, services write into nothing -- so this degrades well before zero.
LOW_DISK_GIB = 5.0
CRITICAL_DISK_GIB = 1.0


@probe("disk.free", asks="can this machine still write anything at all?")
def _p_disk(ctx: Ctx) -> Report:
    import shutil as _shutil

    try:
        usage = _shutil.disk_usage(str(ctx.repo_root))
    except OSError as exc:
        return unknown("disk.free",
                       f"could not read free space for {ctx.repo_root}: "
                       f"{type(exc).__name__}: {exc}")
    free_gib = usage.free / (1024 ** 3)
    total_gib = usage.total / (1024 ** 3)
    facts = [measured("free GiB", round(free_gib, 1)),
             measured("total GiB", round(total_gib, 1)),
             measured("volume", str(ctx.repo_root.anchor or ctx.repo_root))]
    if free_gib < CRITICAL_DISK_GIB:
        return degraded(
            "disk.free", f"{free_gib:.1f} GiB free of {total_gib:.0f} -- "
                         f"below the point where writes start failing", facts,
            remedy="free space now; model loads, git operations and the pagefile "
                   "all fail quietly here, and they fail as HTTP 500s and "
                   "'slow' rather than as anything naming the disk")
    if free_gib < LOW_DISK_GIB:
        return degraded(
            "disk.free", f"{free_gib:.1f} GiB free of {total_gib:.0f}", facts,
            remedy=f"below {LOW_DISK_GIB:.0f} GiB; a single model pull or a "
                   f"worktree checkout can cross the remaining gap")
    return working("disk.free", f"{free_gib:.1f} GiB free of {total_gib:.0f}",
                   facts)


# --------------------------------------------------------------------------- #
# 9c -- bench residency: is the model on the GPU, or quietly in system RAM?    #
# --------------------------------------------------------------------------- #
# The dangerous bench failure is not the loud one. A model that exceeds VRAM is
# not refused -- llama.cpp splits layers into system RAM and keeps answering,
# roughly 20x slower. MEASURED: qwen2.5-coder:32b ran at 6.08 tok/s against
# 107-160 for models that fit. Nothing errors, so a capacity problem presents as
# a model-quality problem, and the fix people reach for is buying a GPU.
#
# `/api/ps` reports both `size` and `size_vram` per resident model. They are
# equal when a model is fully on the card and diverge the moment any layer
# spills. That divergence is the diagnostic, and it costs one HTTP GET.
#
# A second, nastier case this catches: MEASURED once, 13,390 MiB of VRAM held
# while /api/ps reported ZERO models -- orphaned llama-server.exe processes the
# parent had lost track of. Any capacity measurement taken on top of that is a
# measurement of a lie.
@probe("bench.residency",
       asks="are the bench's models on the GPU, or silently in system RAM?",
       required=False)
def _p_bench_residency(ctx: Ctx) -> Report:
    import json as _json
    import urllib.error
    import urllib.request

    url = BENCH_OLLAMA.rstrip("/") + "/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return unknown("bench.residency",
                       f"the bench did not answer /api/ps: {type(exc).__name__}",
                       remedy="unknown is not absent: the bench may be down, or "
                              "simply not configured on this machine")
    models = payload.get("models") or []
    if not models:
        return present("bench.residency", "no model resident on the bench",
                       [measured("resident models", 0)],
                       remedy="nothing is loaded; this is normal when idle, and "
                              "indistinguishable here from orphaned engine "
                              "processes still holding VRAM -- compare against "
                              "nvidia-smi if a load is expected")
    facts: list[Fact] = [measured("resident models", len(models))]
    spilled: list[str] = []
    for row in models:
        name = str(row.get("name") or row.get("model") or "?")
        size = int(row.get("size") or 0)
        vram = int(row.get("size_vram") or 0)
        facts.append(measured(f"{name} vram/total GiB",
                              f"{vram / (1024 ** 3):.1f}/{size / (1024 ** 3):.1f}"))
        # Exact equality is what "fully resident" means; allow a byte of slack
        # only for rounding in the server's own accounting.
        if size and vram < size:
            spilled.append(f"{name} ({100 * (size - vram) / size:.0f}% off-GPU)")
    if spilled:
        return degraded(
            "bench.residency",
            "model layers are in system RAM, not VRAM: " + ", ".join(spilled),
            facts,
            remedy="this does not error -- it runs ~20x slower and reads as a "
                   "model-quality problem. Load a smaller model, lower num_ctx, "
                   "reduce OLLAMA_NUM_PARALLEL (it pre-allocates KV per slot for "
                   "EVERY resident model), or quantise the KV cache")
    return working("bench.residency",
                   f"{len(models)} model(s) fully resident on the GPU", facts)


# --------------------------------------------------------------------------- #
# 9d/9e -- the two bench failures that are invisible to everything but ssh     #
# --------------------------------------------------------------------------- #
# MEASURED 2026-07-29, on the RTX bench. Two failures share one property: NO
# local HTTP probe can see them, because Ollama exposes no free-space and no
# crash-history endpoint, and both live entirely in Windows' own machinery.
#
#   1. the auto-start task was `LogonType=InteractiveToken` with only a Logon
#      trigger -- a reboot with nobody at the console or over RDP is not a
#      crash and not a delay, it is a PERMANENT no-op. Nothing polls for
#      this; it looks identical to "the bench is simply idle" until someone
#      needs it and it has been off since the last Windows Update.
#
#   2. llama-server.exe crashes 0xc0000409 in ucrtbase.dll at the SAME offset
#      every time (a second, rarer signature: 0xc0000005 in libllama.dll).
#      Ollama's own server.log shows NOTHING -- the parent process swallows
#      the child's death and silently relaunches it, so Task Scheduler's own
#      restart policy never even fires on this. Only Windows Error Reporting
#      catches it, in the Application log, and nothing before this read it.
#
#   3. MEASURED after the two probes below first shipped, by a sibling agent
#      (Metron) exercising this same bench under concurrent load: `ollama.exe`
#      ITSELF -- not merely the llama-server.exe child -- died mid-run with NO
#      WER record, no crash dump, and NO Application-log entry at all.
#      `Get-Process ollama` came back empty. Reproduced twice. A probe that
#      only scans crash records would have reported "0 crashes" over a dead
#      server -- true about what it measured, false about what a reader would
#      conclude, the exact shape of escape this whole module exists to catch,
#      one level up. `bench.engine_crashes` below therefore never reads
#      "no crash records" as `working` on its own -- it is corroborated
#      against `_bench_ollama_alive`, a live HTTP check, every time.
#
# Both ssh answers require ssh -- Get-ScheduledTask and Get-WinEvent have no
# HTTP equivalent -- so both probes below share the rule the rest of this
# file enforces everywhere else: a check that cannot run is `unknown`, never
# `absent`. Only a query that ACTUALLY REACHED the bench and came back
# empty-handed (the task genuinely is not there) may report `absent`; an ssh
# timeout, a missing client, or a remote exception all mean "this machine
# could not ask", which is a different fact from "the answer is no".
#
# ONE ssh round trip serves both probes; they are cached per :func:`assess`
# run (:data:`_SSH_CACHE`) so an unreachable bench costs one timeout, not two.
_SSH_CACHE: dict[str, tuple[bool, Any]] = {}


def _ps_quote(value: str) -> str:
    """Escape a value for embedding inside a PowerShell single-quoted string."""
    return "'" + str(value).replace("'", "''") + "'"


def _ssh_powershell(host: str, script: str, timeout: float) -> tuple[bool, Any]:
    """Run ``script`` on ``host`` non-interactively, quoting-proof.

    The remote default shell here is cmd.exe, which tokenises on the ``|``
    and ``&`` that any nontrivial PowerShell script is full of -- the first
    version of this probe learned that the hard way (``findstr`` receiving
    ``echo``, ``reg``, ``add`` as literal filenames because a `;`-joined
    command line was never a cmd.exe separator). ``-EncodedCommand`` sends
    the script as base64 instead: nothing is left for cmd.exe, ssh's own
    argv-join, or anything in between to misparse.

    Returns ``(ok, payload)``. ``ok=False`` means the SSH CALL ITSELF could
    not be trusted -- no client, unreachable, timed out, or the reply was not
    JSON -- and the caller MUST report ``unknown``, never ``absent``, for
    that case. ``ok=True`` means ssh worked and ``payload`` is the remote
    script's own JSON, which may separately carry ``{"ok": false, ...}`` for
    a remote-side failure that DID get reported cleanly (e.g. the Task
    Scheduler RPC service unreachable) -- still not the same fact as "the
    task does not exist", so callers must keep that distinction too.
    """
    ssh = shutil.which("ssh")
    if not ssh:
        return False, "no ssh client on PATH"
    b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        p = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
             "-o", "ConnectionAttempts=1", host,
             "powershell", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", b64],
            capture_output=True, text=True, timeout=timeout, check=False,
            encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if p.returncode != 0:
        return False, (f"ssh exited {p.returncode}: "
                       f"{(p.stderr or p.stdout or '').strip()[:200]}")
    out = (p.stdout or "").strip()
    if not out:
        return False, "ssh produced no output"
    try:
        return True, json.loads(out)
    except ValueError as exc:
        return False, f"remote output was not JSON: {exc} ({out[:200]!r})"


# Two read-only PowerShell queries in one round trip.
#
# Task facts come from `Get-ScheduledTask` with NO name filter, then a
# `Where-Object` match -- deliberately not `-TaskName X -ErrorAction
# SilentlyContinue`, because that collapses "the Task Scheduler RPC service
# is unreachable" and "no task by that name" into the same $null. The
# unfiltered call still THROWS on the former (-> ok=false -> unknown) while a
# `Where-Object` miss is a clean, measured "not found" (-> taskFound=false ->
# absent).
#
# Crash facts come from the event's own `ToXml()`, never the localised
# `.Message` text -- this box reports in German ("Fehlerhafter
# Anwendungsname"), and matching the schema's stable `Data Name=` attributes
# instead of the rendered string is what keeps the probe working regardless
# of the box's display language. VERIFIED live against this bench: `$d.
# '#text'` on each `<Data Name="AppName">llama-server.exe</Data>` node is
# what actually recovers the value; a bare `$d.AppName` does not exist.
_BENCH_SNAPSHOT_SCRIPT = """
$ErrorActionPreference = 'Stop'

function Get-TaskFacts {
    try {
        $t = Get-ScheduledTask | Where-Object { $_.TaskName -eq __TASK_NAME__ } |
            Select-Object -First 1
        if (-not $t) { return @{ ok = $true; taskFound = $false } }
        $info = $t | Get-ScheduledTaskInfo
        $triggerTypes = @($t.Triggers | ForEach-Object { $_.CimClass.CimClassName })
        $bootCapable = @($triggerTypes | Where-Object {
            $_ -notmatch 'MSFT_TaskLogonTrigger|MSFT_TaskSessionStateChangeTrigger'
        }).Count -gt 0
        $headlessLogon = $t.Principal.LogonType.ToString() -in @('S4U', 'Password', 'ServiceAccount')
        $restartIv = $null
        if ($t.Settings.RestartInterval) {
            $restartIv = [Xml.XmlConvert]::ToTimeSpan($t.Settings.RestartInterval).TotalMinutes
        }
        return @{
            ok = $true; taskFound = $true
            enabled = [bool]$t.Settings.Enabled
            state = $t.State.ToString()
            logonType = $t.Principal.LogonType.ToString()
            runLevel = $t.Principal.RunLevel.ToString()
            triggerTypes = $triggerTypes
            bootCapableTrigger = [bool]$bootCapable
            headlessLogon = [bool]$headlessLogon
            lastRunTime = $info.LastRunTime.ToUniversalTime().ToString('o')
            lastTaskResult = $info.LastTaskResult
            restartCount = $t.Settings.RestartCount
            restartIntervalMinutes = $restartIv
        }
    } catch {
        return @{ ok = $false; error = $_.Exception.Message }
    }
}

function Get-CrashFacts {
    try {
        try {
            $events = @(Get-WinEvent -FilterHashtable @{
                LogName = 'Application'; ProviderName = 'Application Error'
            } -MaxEvents 300 -ErrorAction Stop)
        } catch {
            if ($_.Exception.Message -match 'No events were found') { $events = @() }
            else { throw }
        }
        $rows = New-Object System.Collections.ArrayList
        foreach ($e in $events) {
            $xml = [xml]$e.ToXml()
            $data = @{}
            foreach ($d in $xml.Event.EventData.Data) { $data[$d.Name] = $d.'#text' }
            if ($data['AppName'] -like 'llama-server.exe*' -or $data['AppName'] -like 'ollama.exe*') {
                [void]$rows.Add(@{
                    time = $e.TimeCreated.ToUniversalTime().ToString('o')
                    binary = $data['AppName']
                    moduleName = $data['ModuleName']
                    exceptionCode = $data['ExceptionCode']
                    faultingOffset = $data['FaultingOffset']
                })
            }
        }
        return @{
            ok = $true; scanned = $events.Count; matches = $rows.Count
            records = @($rows | Select-Object -First 20)
        }
    } catch {
        return @{ ok = $false; error = $_.Exception.Message }
    }
}

@{ task = (Get-TaskFacts); crashes = (Get-CrashFacts) } | ConvertTo-Json -Compress -Depth 6
""".replace("__TASK_NAME__", _ps_quote(BENCH_TASK_NAME))


def _ssh_bench_snapshot(ctx: Ctx) -> tuple[bool, Any]:
    """The one ssh round trip both bench probes below need, cached per run."""
    if BENCH_SSH_HOST in _SSH_CACHE:
        return _SSH_CACHE[BENCH_SSH_HOST]
    result = _ssh_powershell(BENCH_SSH_HOST, _BENCH_SNAPSHOT_SCRIPT,
                             BENCH_SSH_TIMEOUT_S)
    _SSH_CACHE[BENCH_SSH_HOST] = result
    return result


def _bench_task_report(payload: dict) -> Report:
    t = payload.get("task") or {}
    if not t.get("ok"):
        return unknown("bench.scheduled_task",
                       f"ssh reached the bench but the task query failed: "
                       f"{t.get('error')}",
                       remedy="unknown is not absent: this proves the QUERY "
                              "failed, not that the task is gone")
    if not t.get("taskFound"):
        return absent("bench.scheduled_task",
                      f"no scheduled task named {BENCH_TASK_NAME!r} on the "
                      f"bench -- Ollama only starts if someone runs it by hand",
                      [measured("ssh host", BENCH_SSH_HOST)],
                      remedy="recreate the DaedalusOllamaServe task")
    facts = [
        measured("enabled", t.get("enabled")),
        measured("state", t.get("state")),
        measured("logon type", t.get("logonType")),
        measured("run level", t.get("runLevel")),
        measured("trigger types",
                 ", ".join(t.get("triggerTypes") or []) or "none"),
        measured("boot-capable trigger", t.get("bootCapableTrigger")),
        measured("headless-capable logon", t.get("headlessLogon")),
        measured("last run (UTC)", t.get("lastRunTime")),
        measured("last task result", t.get("lastTaskResult")),
        measured("restart policy",
                 f"{t.get('restartCount')}x / "
                 f"{t.get('restartIntervalMinutes')}min"),
    ]
    if not t.get("enabled"):
        return degraded("bench.scheduled_task",
                        "the task exists but is DISABLED -- Ollama will "
                        "never auto-start", facts,
                        remedy=f"Enable-ScheduledTask -TaskName {BENCH_TASK_NAME}")
    survives = t.get("bootCapableTrigger") and t.get("headlessLogon")
    if not survives:
        missing = []
        if not t.get("bootCapableTrigger"):
            missing.append("every trigger requires an interactive logon "
                           "(no boot/time trigger present)")
        if not t.get("headlessLogon"):
            missing.append(f"LogonType={t.get('logonType')} needs an active "
                           f"session token to run the action")
        return degraded("bench.scheduled_task",
                        "a reboot with no console/RDP logon will NOT start "
                        "Ollama -- " + "; ".join(missing), facts,
                        remedy="add a boot trigger and set the principal's "
                               "LogonType to S4U (or Password/ServiceAccount)")
    return working("bench.scheduled_task",
                   f"present, enabled, and survives a headless reboot "
                   f"(logon type {t.get('logonType')})", facts)


@probe("bench.scheduled_task",
       asks="will the Ollama auto-start task survive a headless reboot?",
       required=False)
def _p_bench_task(ctx: Ctx) -> Report:
    ok, payload = _ssh_bench_snapshot(ctx)
    if not ok:
        return unknown("bench.scheduled_task",
                       f"could not reach the bench over ssh: {payload}",
                       remedy="unknown is not absent: this only proves THIS "
                              "machine could not ask")
    return _bench_task_report(payload)


def _ollama_alive(host: str, timeout_s: float) -> tuple[bool, str, str]:
    """Does the Ollama HTTP endpoint at ``host`` answer, right now?

    THE ONE LIVENESS PREDICATE. Both callers below bind it to a host —
    :func:`_bench_ollama_alive` to the RTX bench, :func:`hand_state` to whatever
    endpoint the tool-bearing executor will actually be dispatched to. This
    repo's recurring disease is two predicates for one question, each drifting
    until "is it up" has two different answers; there is deliberately no second
    implementation to drift from.

    Returns ``(alive, detail, exc_kind)``. ``exc_kind`` names the underlying
    failure (``ConnectionRefusedError``, ``TimeoutError``, …) so a caller that
    must distinguish "definitively not there" from "the check could not run"
    can, without re-parsing ``detail``. It is ``""`` on success.
    """
    try:
        _http_json(host.rstrip("/") + "/api/version", timeout_s)
        return True, "answered", ""
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or exc
        kind = "TimeoutError" if isinstance(reason, TimeoutError) else type(reason).__name__
        return False, f"{type(exc).__name__}: {exc}", kind


#: The endpoint the tool-bearing local executor ("the Hand") is dispatched to.
#: Read from the environment at call time, NOT at import, because it is the same
#: ``OLLAMA_HOST`` the provider resolves per request — a liveness answer about a
#: different host than the one that will be called is worse than no answer.
def _hand_host(host: str | None = None) -> str:
    return host or os.environ.get("OLLAMA_HOST", LOCAL_OLLAMA)


#: (state, detail, host) — ``state`` is one of this module's five words.
HandState = namedtuple("HandState", "state detail host")


def hand_admission(host: str | None = None) -> tuple[bool, str, str]:
    """May this process open a socket to the Hand's endpoint at all?

    THE DECISION IS NOT TAKEN HERE. It delegates to
    :func:`daedalus.providers.ollama.ollama_endpoint_admission`, the one
    implementation of "may bytes reach this endpoint" for everything that
    speaks the Ollama HTTP transport — ``lane_for_host`` plus exact-endpoint
    operator consent via ``DAEDALUS_OLLAMA_REMOTE_OK``. ``ikarus_os``'s
    ``_egress_decision`` and ``memory.embeddings`` already call it; a second
    copy of that answer living in the health module would be free to drift, and
    the drift would be silent in exactly the direction that matters (health
    says "reachable" about a host the write lane refuses, or the reverse).

    Returns the admission tuple unchanged: ``(allowed, lane, why)``.

    Imported inside the function, not at module top: ``daedalus.providers``
    pulls the provider stack in, and ``health`` must stay importable — and
    answerable — on a machine where that stack is broken. A health module that
    cannot load because the thing it reports on is sick is the one failure mode
    it may not have.
    """
    from .providers.ollama import ollama_endpoint_admission

    return ollama_endpoint_admission(_hand_host(host))


def hand_state(host: str | None = None, timeout_s: float = 4.0) -> HandState:
    """Is the tool-bearing local executor there, in the five-word vocabulary?

    Composed from :func:`_ollama_alive`, never a second liveness check.

      ``working``  it answered ``/api/version`` just now — MEASURED, this call
      ``degraded`` the endpoint was REFUSED before connect by
                   ``provider.egress_policy`` (see :func:`hand_admission`).
                   Nothing left this process, so nothing is known about whether
                   the executor is up; what IS known is that ``OLLAMA_HOST``
                   names a host this machine may not speak to.
      ``absent``   a definitive rejection from a known endpoint (refused,
                   unreachable, no route). That is evidence, not an absence of
                   evidence, exactly as ``_embed_probe`` already treats a failed
                   ``/api/tags``.
      ``unknown``  the check itself could not conclude — a timeout says nothing
                   about whether the executor exists, only that we did not find
                   out. ``unknown`` is never ``absent`` and never green.

    ``present`` is not producible here on purpose: this asks one yes/no
    question and has no way to observe a half-working executor.

    WHY ``degraded`` AND NOT A RAISE, AND NOT ``absent``. This module is
    read-only status; every probe answers a question and none of them may
    become the reason a caller crashes, so the refusal is a state, never an
    exception. It is not ``absent`` because ``absent`` is a claim ABOUT THE
    EXECUTOR ("nothing answers there"), and a refused probe never asked — the
    executor may be perfectly healthy behind a host nobody consented to. It is
    not ``unknown`` either: ``unknown`` means the check could not conclude,
    while this check concluded firmly and the conclusion is a policy refusal an
    operator can act on. ``degraded`` is also the only one of the three that
    :func:`verdict` scores as EXIT_BAD regardless of ``required``, which is
    right: a misconfigured egress lane is a fault, not a legitimate shape.

    Ordering is load-bearing: admission runs BEFORE :func:`_ollama_alive`, so a
    disallowed host reaches no ``urlopen`` and opens no socket. A check that
    connects first and judges after has already leaked the thing it refuses.
    """
    resolved = _hand_host(host)
    allowed, lane, why = hand_admission(resolved)
    if not allowed:
        # The deny receipt, in the shape the embedding backend's refusal uses:
        # contract, host, lane, evidence, and the fact that no connection was
        # made -- a refusal whose host a reader cannot see is one nobody can fix.
        return HandState(
            DEGRADED,
            f"refused before connect by provider.egress_policy "
            f"(host={resolved!r}, lane={lane}, connected=false): {why}",
            resolved,
        )
    alive, detail, kind = _ollama_alive(resolved, timeout_s)
    if alive:
        return HandState(WORKING, detail, resolved)
    if kind in ("TimeoutError", "socket.timeout"):
        return HandState(UNKNOWN, detail, resolved)
    return HandState(ABSENT, detail, resolved)


# NOT named "hand.local". The host comes from OLLAMA_HOST, an environment
# variable, so the tool-bearing executor is local only until someone points that
# at a bench across a tailnet -- the same trap `_local_lane` in ikarus_os.py
# documents. The probe therefore names the HOST it actually reached in its
# facts, and claims nothing about where that host is.
@probe("hand.executor",
       asks="does the host the tool-bearing executor is dispatched to answer right now?",
       required=False)
def _p_hand_executor(ctx: Ctx) -> Report:
    st = hand_state(timeout_s=ctx.timeout_s)
    facts = [measured("host", st.host), measured("/api/version", st.detail)]
    if st.state == WORKING:
        return working("hand.executor", f"the executor answers at {st.host}", facts)
    if st.state == DEGRADED:
        # A refusal must not print as `absent`. `absent` says "nothing answers
        # there"; this probe never asked, and the executor behind that host may
        # be perfectly healthy. Reporting the refusal as absence would send the
        # operator to `ollama serve` for a problem that lives in OLLAMA_HOST.
        return degraded(
            "hand.executor",
            f"the egress policy refused {st.host} before connect, so this "
            f"probe opened no socket and knows nothing about the executor",
            facts,
            remedy=(
                "either point OLLAMA_HOST at this machine, or name that exact "
                "endpoint in DAEDALUS_OLLAMA_REMOTE_OK (a HOST, never =1) to "
                "declare the egress lane. Until one of those, every ollama "
                "lane in this process refuses the same host for the same "
                "reason -- this probe is not the only thing being stopped"
            ),
        )
    if st.state == UNKNOWN:
        return unknown("hand.executor",
                       f"the check could not conclude: {st.detail}", facts,
                       remedy="a timeout is not an absence: retry, or raise the "
                              "timeout before concluding anything")
    return absent("hand.executor", f"nothing answers at {st.host}: {st.detail}", facts,
                  remedy=f"start it:  OLLAMA_HOST={st.host} ollama serve  "
                         "(absent here is legitimate on a machine that only "
                         "chats; it means act-cleared work has nowhere to run)")


def _bench_ollama_alive(ctx: Ctx) -> tuple[bool, str]:
    """Does the bench's Ollama HTTP endpoint answer, right now?

    THE FACT THAT CLOSES THE BLIND SPOT. MEASURED: `ollama.exe` itself died
    mid-run under concurrent load with NO WER record, no crash dump, and NO
    Application-log entry at all -- `Get-Process ollama` came back empty.
    "Zero crash records" and "the server is alive" are DIFFERENT FACTS, and
    :func:`_bench_crash_report` must never infer the second from the first.
    A live GET is the only thing that can tell them apart, so it is always
    performed, never skipped as an optimisation.

    Returns ``(alive, detail)``. Any failure -- refused, timed out, or a
    reply that is not the JSON `/api/version` returns -- is treated as "not
    answering", the same way ``_embed_probe`` already treats a failed
    `/api/tags` as ``degraded`` rather than ``unknown``: a definitive
    rejection from a specific, known endpoint is evidence, not an absence of
    evidence. The caller (:func:`_bench_crash_report`) is structured so that
    an exception here can only ever push the verdict toward ``degraded``,
    never toward ``working`` -- uncertainty about liveness must never read
    as health.
    """
    alive, detail, _kind = _ollama_alive(BENCH_OLLAMA, ctx.timeout_s)
    return alive, detail


def _bench_crash_report(payload: dict, *, alive: bool, alive_detail: str) -> Report:
    c = payload.get("crashes") or {}
    if not c.get("ok"):
        return unknown("bench.engine_crashes",
                       f"ssh reached the bench but the event log query "
                       f"failed: {c.get('error')}")
    n = int(c.get("matches") or 0)
    scanned = int(c.get("scanned") or 0)
    records = c.get("records") or []
    facts = [measured("Application-log entries scanned", scanned),
             measured("engine crash records found", n),
             measured("Ollama HTTP endpoint answers right now", alive
                      if alive else f"NO ({alive_detail})")]
    if records:
        sigs = sorted({f"{r.get('binary')}: {r.get('moduleName')} "
                       f"{r.get('exceptionCode')}@{r.get('faultingOffset')}"
                       for r in records})
        facts.append(measured("most recent crash (UTC)", records[0].get("time")))
        facts.append(measured("distinct signatures", "; ".join(sigs)))
    if n > 0:
        return degraded("bench.engine_crashes",
                        f"{n} engine crash record(s) in the last {scanned} "
                        f"Application-log entries -- Ollama's own server.log "
                        f"shows none of this; only Windows Error Reporting "
                        f"caught it" + ("" if alive else
                        f"; AND it is NOT answering right now ({alive_detail})"),
                        facts,
                        remedy="Ollama is being updated on the bench to address "
                               "this; if the signature above still appears "
                               "afterward, that is the starting point, not a "
                               "fresh investigation")
    # n == 0 FROM HERE. This is the exact point the blind spot lived: a crash
    # scan finding nothing is NOT evidence of health on its own -- it is only
    # evidence that THIS failure mode did not leave a record. It must be
    # corroborated against a live signal before it is allowed to read as
    # `working`, or `ollama.exe` can die with no WER entry, no dump, and no
    # Application-log line, and this probe would report "0 crashes" over a
    # dead server -- true about what it measured, false about what a reader
    # would conclude.
    if alive:
        return working("bench.engine_crashes",
                       f"0 engine crash records in the last {scanned} "
                       f"Application-log entries, AND the server answers "
                       f"right now", facts)
    return degraded("bench.engine_crashes",
                    f"0 engine crash records in the last {scanned} "
                    f"Application-log entries, but the server is NOT "
                    f"answering ({alive_detail}) -- it died WITHOUT LEAVING "
                    f"A RECORD, which is worse than crashing loudly: nothing "
                    f"short of a live check would ever have caught it",
                    facts,
                    remedy="check `Get-Process ollama` on the bench by hand; "
                           "this failure mode leaves no WER entry and no "
                           "Application-log record for any log-only probe "
                           "to find")


@probe("bench.engine_crashes",
       asks="is the engine crash-looping, or dead without a trace, where "
            "only a live check would see it?",
       required=False)
def _p_bench_crashes(ctx: Ctx) -> Report:
    ok, payload = _ssh_bench_snapshot(ctx)
    if not ok:
        return unknown("bench.engine_crashes",
                       f"could not reach the bench over ssh: {payload}",
                       remedy="unknown is not absent: this only proves THIS "
                              "machine could not ask")
    alive, alive_detail = _bench_ollama_alive(ctx)
    return _bench_crash_report(payload, alive=alive, alive_detail=alive_detail)


# --------------------------------------------------------------------------- #
# 10 -- the planner's latent half: is the weight describing a live source?     #
# --------------------------------------------------------------------------- #
@probe("context.latent_seed",
       asks="does the weight the planner puts on latent memory describe anything?")
def _p_latent(ctx: Ctx) -> Report:
    plan_path = ctx.repo_root / "daedalus" / "context_plan.py"
    try:
        import inspect

        from . import context_plan
        weight = inspect.signature(
            context_plan.fuse_seed_scores).parameters["latent_weight"].default
    except Exception as exc:                     # noqa: BLE001
        return unknown("context.latent_seed",
                       f"could not read the planner's latent weight: "
                       f"{type(exc).__name__}: {exc}")
    try:
        from .memory import VECTOR_DB_PATH
        index_exists = VECTOR_DB_PATH.exists()
    except Exception as exc:                     # noqa: BLE001
        return unknown("context.latent_seed",
                       f"could not locate the vector index: "
                       f"{type(exc).__name__}: {exc}")
    facts = [
        inherited("latent_weight default", weight, plan_path, now=ctx.now),
        measured("index backing it exists", index_exists),
    ]
    if float(weight) > 0 and not index_exists:
        return degraded("context.latent_seed",
                        f"the fusion weights latent memory at {weight} and the "
                        f"index it reads has never existed -- the weight "
                        f"describes a source that has never spoken", facts,
                        remedy="either build the index or set latent_weight to 0; "
                               "a configured weight is not a working source")
    if float(weight) == 0:
        return present("context.latent_seed",
                       "latent seeding is weighted at 0 -- present in the code, "
                       "contributing nothing by configuration", facts)
    return present("context.latent_seed",
                   f"an index exists and the weight is {weight}; this run did "
                   f"not run a fusion, so nothing here proves it contributes",
                   facts)


# --------------------------------------------------------------------------- #
# 10b -- the latent router: wired is not the same as working                   #
# --------------------------------------------------------------------------- #
@probe("route.latent",
       asks="does the stage-1 latent router actually route, or only exist?")
def _p_route(ctx: Ctx) -> Report:
    """The archetype this whole surface was built for.

    ``semantic_route`` was listed as a shipped feature while being unwired AND
    broken if wired. Two separate facts have to hold, and only the second is a
    measurement: something in the product must IMPORT it, and it must RETURN A
    ROUTE when called. The module reports its own mechanism honestly --
    ``keyword_fallback`` means the latent half could not be used -- so a
    fallback is degraded here rather than a quiet success.
    """
    path = ctx.repo_root / "daedalus" / "semantic_route.py"
    if not path.exists():
        return absent("route.latent", f"{_rel(path)} is not present")
    callers = production_importers("daedalus.semantic_route", ctx.repo_root)
    wiring = [measured("production callers",
                       ", ".join(callers) if callers else "NONE")]
    if not callers:
        return degraded("route.latent",
                        "the latent router exists and NOTHING in the product "
                        "calls it", wiring,
                        remedy="a routing brain nobody consults is a routing "
                               "brain that cannot be wrong, or right")
    if not ctx.deep:
        return present("route.latent",
                       f"wired into {callers[0]}; this run did NOT call it "
                       f"(~7s cold, see --deep)", wiring,
                       remedy="python -m daedalus.health --deep --only route")
    try:
        from .semantic_route import FALLBACK, semantic_route_explained
        t0 = time.time()
        result = semantic_route_explained(PROBE_TEXT, [],
                                          repo_root=str(ctx.repo_root))
        took = time.time() - t0
    except Exception as exc:                     # noqa: BLE001
        return degraded("route.latent",
                        f"the latent router is wired and RAISED when called: "
                        f"{type(exc).__name__}: {exc}", wiring,
                        remedy="every route silently falls back to keywords "
                               "until this is fixed")
    facts = wiring + [measured("mechanism", result.mechanism),
                      measured("chose", (result.agent or {}).get("name")),
                      measured("latency", f"{took:.1f}s")]
    if result.mechanism == FALLBACK:
        return degraded("route.latent",
                        f"the latent route FELL BACK to keywords: "
                        f"{result.explain()[:160]}", facts)
    return working("route.latent",
                   f"routed a live objective by {result.mechanism} in "
                   f"{took:.1f}s -> {(result.agent or {}).get('name')}", facts)


# --------------------------------------------------------------------------- #
# 11 -- the room's tamper-evident chain                                        #
# --------------------------------------------------------------------------- #
@probe("room.chain", asks="does the room's hash chain still match its markdown?",
       required=False)
def _p_room(ctx: Ctx) -> Report:
    room_py = ctx.repo_root / "runs" / "council" / "room.py"
    room_md = ctx.repo_root / "runs" / "council" / "room.md"
    if not room_py.exists():
        return absent("room.chain", f"{_rel(room_py)} is not present",
                      required=False)
    if not room_md.exists():
        # room.transcript() CREATES room.md via _ensure(); asking the question
        # must not manufacture the artefact.
        return present("room.chain",
                       "the room module is here and no transcript exists yet",
                       [inherited("module", _rel(room_py), room_py, now=ctx.now)])
    added = str(room_py.parent)
    inserted = added not in sys.path
    if inserted:
        sys.path.insert(0, added)
    try:
        import room as room_mod                  # type: ignore
        ok, problems = room_mod.verify_room()
        attested, total = room_mod.chain_coverage()
    except Exception as exc:                     # noqa: BLE001
        return unknown("room.chain",
                       f"the chain could not be verified: "
                       f"{type(exc).__name__}: {exc}")
    finally:
        if inserted and added in sys.path:
            sys.path.remove(added)
    facts = [measured("turns in markdown", total),
             measured("turns attested by the chain", attested),
             measured("verification problems", len(problems))]
    if not ok:
        return degraded("room.chain",
                        f"the chain does NOT verify: {len(problems)} problem(s), "
                        f"first: {problems[0]}",
                        facts + [measured(f"problem {i + 1}", p)
                                 for i, p in enumerate(problems[1:4], start=1)],
                        remedy="python runs/council/room.py verify   (the "
                               "markdown and the chain disagree; the chain is "
                               "the evidence, the markdown is the artefact)",
                        required=False)
    if attested < total:
        return degraded("room.chain",
                        f"the chain verifies but covers only {attested}/{total} "
                        f"turns", facts, required=False)
    return working("room.chain", f"chain verifies over all {total} turn(s)", facts)


# --------------------------------------------------------------------------- #
# 12 -- capability islands: code with eleven properties and zero callers        #
# --------------------------------------------------------------------------- #
#: Modules that DECLARE a capability. Each one is here because something in the
#: product is supposed to use it; a module with no production importer is the
#: "present but unexercised" case in its purest form -- containment.py shipped
#: with eleven measured properties and nothing at all called it.
CAPABILITY_MODULES = (
    "daedalus.spine.containment",
    "daedalus.spine.cancel",
    "daedalus.semantic_route",
    # "daedalus.compaction" was here until 2026-07-29, when it was DELETED
    # rather than wired. It was not merely uncalled -- it was superseded. The
    # only place in the repo that accumulates a message list, the Ollama
    # tool-call loop in daedalus/providers/ollama.py, already bounds context
    # with the real cl100k tokenizer against the real measured server window
    # (effective_input_window) and evicts via _forced_report inside a loop
    # capped at MAX_AGENT_STEPS=6. compaction.py offered chars//4 against a
    # hardcoded 30_000. Wiring it into the one plausible caller would have
    # REPLACED a measured guard with a guess. See the deletion commit.
    "daedalus.memory.embeddings",
    "daedalus.context_plan",
)

#: Directories that are not the product: a test importing a module is exactly
#: the evidence that misled this repo, and tools/ is the acceptance harness.
_NON_PRODUCTION = ("tests", "tools", "build", "__pycache__", ".venv", "node_modules")

#: THE OBSERVER IS NOT A CALLER. This module imports half the product in order
#: to look at it; counting those imports as wiring would let the health surface
#: report an island as connected because the health surface touched it. That is
#: the same self-certifying loop the surface exists to break.
_OBSERVERS = ("daedalus/health.py", "daedalus/status.py")


#: Cleared at the top of every :func:`assess`, never persisted. A cache that
#: outlives a run would be exactly the "read a stale description of the tree"
#: failure this file reports on, committed by this file.
_SOURCE_CACHE: dict[str, list[tuple[str, str, str]]] = {}


def _production_sources(repo_root: Path) -> list[tuple[str, str, str]]:
    """``(posix path, relative path, text)`` for every product .py file.

    Read ONCE per run and reused across modules: the first version re-walked
    the tree per capability and cost 4.5s of an 8.5s run, which is how a status
    surface stops being run.
    """
    key = str(Path(repo_root).resolve())
    if key in _SOURCE_CACHE:
        return _SOURCE_CACHE[key]
    out: list[tuple[str, str, str]] = []
    for base in ("daedalus", "runs", "apps"):
        root = repo_root / base
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if any(part in _NON_PRODUCTION for part in p.parts):
                continue
            rel = _rel(p)
            if rel in _OBSERVERS:
                continue
            try:
                out.append((p.as_posix(), rel,
                            p.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    _SOURCE_CACHE[key] = out
    return out


def production_importers(module: str, repo_root: Path,
                         sources: Sequence[tuple[str, str, str]] | None = None
                         ) -> list[str]:
    """Files in the PRODUCT that import ``module``. Tests do not count.

    "It has tests" and "something runs it" are different facts, and this repo
    has now twice mistaken the first for the second.
    """
    leaf = module.rsplit(".", 1)[-1]
    self_rel = module.replace(".", "/") + ".py"
    # THREE IMPORT FORMS, AND THE FIRST VERSION SAW ONLY TWO.
    #
    #   import daedalus.spine.containment        <- leaf in the PATH
    #   from daedalus.spine.containment import X <- leaf in the PATH
    #   from daedalus.spine import containment   <- leaf in the NAME LIST
    #
    # The old pattern required the leaf inside `[.\w]*`, which cannot span the
    # space before `import`, so it missed the third form entirely. Measured
    # consequence: `daedalus/spine/attempt.py:849` does exactly that to reach
    # containment, and this probe reported the module as having ZERO production
    # callers -- HOURS AFTER IT WAS WIRED. A health surface that under-reports
    # wiring sends somebody to fix a thing that is not broken, and it does it
    # while claiming to be the instrument that catches exactly this.
    esc = re.escape(leaf)
    pattern = re.compile(
        rf"(?m)^\s*(?:"
        rf"import\s+[.\w]*\b{esc}\b"                       # form 1
        rf"|from\s+[.\w]*\b{esc}\b\s+import"               # form 2
        rf"|from\s+[.\w]+\s+import\s+[^\n#]*\b{esc}\b"     # form 3
        rf")")
    rows = _production_sources(repo_root) if sources is None else sources
    hits = [rel for posix, rel, text in rows
            if not posix.endswith(self_rel) and rel not in _OBSERVERS
            and pattern.search(text)]
    return sorted(hits)


@probe("wiring.islands",
       asks="is any declared capability wired to nothing in the product?")
def _p_islands(ctx: Ctx) -> Report:
    found: dict[str, list[str]] = {}
    missing: list[str] = []
    sources = _production_sources(ctx.repo_root)
    for mod in CAPABILITY_MODULES:
        path = ctx.repo_root / (mod.replace(".", "/") + ".py")
        if not path.exists():
            missing.append(mod)
            continue
        found[mod] = production_importers(mod, ctx.repo_root, sources)
    islands = sorted(m for m, hits in found.items() if not hits)
    facts = [measured("capabilities checked", len(found))]
    for mod, hits in sorted(found.items()):
        facts.append(measured(mod, f"{len(hits)} production importer(s)"
                                   + (f": {', '.join(hits[:3])}" if hits else "")))
    if missing:
        facts.append(measured("declared but not on disk", ", ".join(missing)))
    if missing:
        return degraded("wiring.islands",
                        f"{len(missing)} capability module(s) in this list do "
                        f"not exist: {', '.join(missing)}", facts,
                        remedy="the list in health.CAPABILITY_MODULES is stale, "
                               "or the module was deleted while still claimed")
    if islands:
        return degraded("wiring.islands",
                        f"{len(islands)} capability module(s) have ZERO "
                        f"production callers: {', '.join(islands)}", facts,
                        remedy="an island is code that passes its own tests and "
                               "runs for nobody; wire it or say it is dormant")
    return working("wiring.islands",
                   f"all {len(found)} declared capabilities have a production "
                   f"caller", facts)


# --------------------------------------------------------------------------- #
# 13 -- the vendor lanes. PRESENCE ONLY, and it says so.                       #
# --------------------------------------------------------------------------- #
@probe("vendors.cli", asks="are the paid lanes installed? (installed != working)")
def _p_vendors(ctx: Ctx) -> Report:
    found = {name: shutil.which(name) for name in ("claude", "codex", "agy")}
    on_path = sorted(n for n, p in found.items() if p)
    facts = [measured(f"{n} on PATH", bool(found[n])) for n in sorted(found)]
    facts.append(assumed("what PATH presence proves", "the binary exists",
                         "this module: no vendor is ever invoked here"))
    if not on_path:
        return absent("vendors.cli",
                      "no vendor CLI is on PATH; every external lane is "
                      "unreachable from this shell", facts, required=False)
    # NEVER 'working'. Running one costs money, so this surface can only ever
    # report that the binary is there -- which is precisely the claim `doctor`
    # renders as [OK] and an operator reads as "the lane works".
    return present("vendors.cli",
                   f"{', '.join(on_path)} on PATH; NOTHING was invoked "
                   f"(a vendor call is billable, so this run cannot prove a "
                   f"lane works)", facts,
                   remedy="to actually prove a lane: daedalus lanes --live "
                          "(spends money, deliberately not done here)")


# --------------------------------------------------------------------------- #
# 14 -- the acceptance harness: present is not passed                          #
# --------------------------------------------------------------------------- #
@probe("acceptance.receipt",
       asks="has the end-to-end harness ever passed ON THIS MACHINE?",
       required=False)
def _p_acceptance(ctx: Ctx) -> Report:
    harness = ctx.repo_root / "tools" / "system_check.py"
    if not harness.exists():
        return absent("acceptance.receipt",
                      "tools/system_check.py is not present", required=False)
    runs = ctx.repo_root / "runs"
    receipts: list[Path] = []
    if runs.is_dir():
        receipts = sorted(runs.glob("acceptance*.json"))
        if (runs / "acceptance").is_dir():
            receipts += sorted((runs / "acceptance").glob("*.json"))
    facts = [inherited("harness", _rel(harness), harness, now=ctx.now),
             measured("receipts on disk", len(receipts))]
    if not receipts:
        return present("acceptance.receipt",
                       "the harness exists and this machine holds NO receipt "
                       "that it has ever passed here", facts,
                       remedy="python tools/system_check.py --json > "
                              "runs/acceptance-$(date +%s).json",
                       required=False)
    newest = max(receipts, key=lambda p: p.stat().st_mtime)
    try:
        payload = json.loads(newest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return unknown("acceptance.receipt",
                       f"the newest receipt could not be read: {exc}", facts,
                       required=False)
    v = payload.get("verdict")
    facts.append(inherited("verdict", v, newest, now=ctx.now))
    if v != 0:
        return degraded("acceptance.receipt",
                        f"the last acceptance run on this machine exited {v}",
                        facts, required=False)
    return present("acceptance.receipt",
                   f"a passing receipt exists, {_ago(_age_of(newest, ctx.now))} "
                   f"-- that is a record of a PAST run, not of this tree", facts,
                   required=False)


# --------------------------------------------------------------------------- #
# cli                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape. This
    # module has two doors, `daedalus health` through cli.main's dispatch and
    # `python -m daedalus.health` straight past it, and the static scanner
    # rediscovers neither: main()'s own AST holds no sink, because every probe
    # reaches its effect through a helper. So it looked read-only and is not --
    # _git and _ssh_powershell spawn children, _http_json opens a socket.
    #
    # process_guard_boundary_decision installs the process-wide spend net and
    # returns the GuardDecision naming what it interposed; begin_effect
    # performs no effect, it authorises one, and refuses unless the cli.health
    # row, the declared effects and that decision agree. The registry anchor
    # pins this call.
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.health",
        REGISTRY_BY_ID["cli.health"].effects,
        (process_guard_boundary_decision(),),
    )

    ap = argparse.ArgumentParser(
        description="What is working, what is merely present, and what nobody "
                    "checked.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="substring filter on subsystem name")
    ap.add_argument("--repo-root")
    ap.add_argument("--probe-remote", action="store_true",
                    help="also EXERCISE the bench host's embedding backend "
                         "(a fixed literal string; never repo content)")
    ap.add_argument("--deep", action="store_true",
                    help="also exercise the expensive paths (the latent "
                         "router, ~7s cold); without it they report `present`")
    ap.add_argument("--quiet", action="store_true",
                    help="one line per subsystem, no evidence")
    ap.add_argument("--exit-zero", action="store_true",
                    help="always exit 0 (for callers that treat non-zero as a "
                         "crash); the VERDICT line still tells the truth")
    args = ap.parse_args(argv)

    reports = assess(args.only, repo_root=args.repo_root,
                     probe_remote=args.probe_remote, deep=args.deep)
    code = verdict(reports)
    if args.json:
        print(json.dumps(to_payload(reports), indent=2, default=str))
    else:
        print("daedalus health -- working / present / degraded / absent / unknown")
        print(f"repo: {args.repo_root or ROOT}\n")
        print(render(reports, verbose=not args.quiet))
    return 0 if args.exit_zero else code


if __name__ == "__main__":
    raise SystemExit(main())
