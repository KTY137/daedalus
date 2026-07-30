"""The loop driver: pick -> attempt -> gate -> promote -> re-pick, repeatedly.

Every other entry point in this tree runs ONE attempt and exits. This one runs
until a stated stopping condition says otherwise. That single difference is
what makes the failure modes different, and this module is mostly about those
failure modes rather than about the loop, which is twenty lines.

WHAT IT REUSES (it implements none of this):

* :func:`daedalus.spine.picker.build_queue` -- what to work on next, ranked
  from measured sources. The loop never invents its own ranking.
* :meth:`daedalus.build_exec.WaveExecutor.run_wave` -- attempt + gate +
  promote, via ``daedalus.kairos.gated_writes.run_write_wave``. The loop never
  calls ``run_attempt`` or ``promote_candidates`` directly, so it inherits
  worktree isolation, the cross-process promotion lock, and the governance AND
  for free rather than re-deriving them.
* :class:`daedalus.spine.killswitch.KillSwitch` -- the stop.
* :mod:`daedalus.budget` -- the ceiling.
* :mod:`daedalus.progress` -- per-iteration observability, into the log
  ``daedalus.web_api``'s ``/api/events`` already serves.

THE FOUR BOUNDS. Three are dimensions of "how much", and any ONE of them alone
halts the loop: iteration count, wall clock, and spend. The fourth is
convergence -- ``max_attempts_per_candidate`` -- and it is the one that stops
the loop from spending its whole budget re-attempting a single candidate that
will never pass. See :class:`LoopLedger` for why that bound cannot currently
be delegated to the picker's own attempt memory.

RUNNING WHILE GOVERNANCE IS RED IS THE NORMAL CASE, NOT A FAULT. When
``daedalus.core.get_governance()`` reports ``promotion_allowed: False`` the
loop still picks, still attempts, still gates -- and promotes nothing. The
work is not wasted: every candidate that clears its gate is a real patch
sitting in an integration worktree, and the receipt that would let it be
promoted is a separate, human-owned artifact. A loop that refused to run in
this state would look broken; a loop that promoted anyway would be promoting
unverified work. So it runs, and it says loudly which of the two it is doing
(``LoopReport.mode`` is ``"inert"`` rather than ``"promoting"``).

NEVER WRITES THE PRIMARY CHECKOUT, at any setting. There is no code path from
this module to a write in ``repo_root`` -- it holds no git subprocess of its
own, and its one write path (``run_wave``) lands candidates in disposable
worktrees and promotes, at most, to the integration branch. Integration ->
primary stays a human ``git merge``.

KNOWN GAPS, stated here because a loop is where each of them stops being
theoretical. None is fixable from this module; all three are visible in the
report rather than papered over:

* STOP LATENCY WAS NOT UNIFORM; closed 2026-07-29. The cumulative re-gate in
  ``gated_writes._promote_one_inner`` used to hard-code
  ``is_cancelled=lambda: False``; it now receives the same ``cancel`` token as
  everything else and a cancelled re-gate raises a DISTINCT type
  (``_CumulativeGateCancelled``), so "I was asked to stop" is never reported
  as "this candidate failed its gate". Safe because that function's ``except``
  already did an unconditional ``git reset --hard`` + ``clean -fd`` on ANY
  failure, cancellation included -- stopping mid-apply cannot leave the
  integration worktree dirtier than a real gate failure always could.
* SIBLING INTEGRATION BRANCHES. ``promote_candidates`` mints a fresh branch
  per call off a freshly read primary HEAD, and primary never moves during a
  run, so N iterations leave N unmerged siblings that cannot see each other.
  Two of them touching one file can both pass their gates and still conflict
  at merge -- a success report a human cannot act on. :meth:`LoopLedger.claim`
  is the guard; it is honest about being a declared-path heuristic.
* THE CANDIDATE'S OWN GATE IS DROPPED. See :meth:`LoopDriver._session_for`.

Run it::

    python -m daedalus.loop --max-iterations 5 --max-spend-usd 2.00
    python -m daedalus.loop --dry-run          # picks and previews, spends nothing

Stop it, from anywhere, at any time::

    python -m daedalus.spine.killswitch stop "enough"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import progress
from .atomic import write_text_atomic
from .spine.attempt import ATTEMPT_STATES, STATE_CANCELLED
from .spine.envelope import (
    PREDICATE_LOOP_LEDGER,
    canonical_sha,
    current_trace_id,
    new_trace_id,
    statement,
    subject_for,
    trace_context,
    unwrap,
)
from .spine.killswitch import KillSwitch, LoopHalted

ROOT = Path(__file__).resolve().parents[1]

__all__ = [
    "DEFAULT_MAX_ATTEMPTS_PER_CANDIDATE",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_SPEND_USD",
    "DEFAULT_MAX_WALL_CLOCK_S",
    "IterationResult",
    "LoopBounds",
    "LoopDriver",
    "LoopLedger",
    "LoopReport",
    "STOP_REASONS",
    "PROGRESS_SOURCE",
]

# --------------------------------------------------------------------------- #
# bounds                                                                       #
# --------------------------------------------------------------------------- #
# Deliberately SMALL. A loop driver's defaults are the numbers that apply when
# an operator did not think about it, and the cost of "too small" is one more
# command; the cost of "too large" is an unattended machine spending all night.
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_WALL_CLOCK_S = 1800.0          # 30 minutes
DEFAULT_MAX_SPEND_USD = 2.0
# 2, not 1: one failure can be a flake (a timeout, a locked worktree, a vendor
# 5xx), and refusing a candidate on a single bad sample would let one transient
# failure permanently retire real work. 2 distinguishes "unlucky" from "this
# does not pass".
DEFAULT_MAX_ATTEMPTS_PER_CANDIDATE = 2

PROGRESS_SOURCE = "daedalus.loop"

#: Every reason this loop can stop, as a closed vocabulary. Closed so that
#: "why did it stop" is answerable from the report alone, and so a new stop
#: condition cannot be added without appearing here.
STOP_REASONS = (
    "killswitch",             # a human revoked the permit
    "max_iterations",         # bound 1
    "max_wall_clock",         # bound 2
    "max_spend",              # bound 3
    "queue_exhausted",        # convergence: nothing admissible left to try
    "picker_unusable",        # refused to start/continue -- see the note
    "error",                  # an unhandled failure, reported not swallowed
)


class LoopMisconfigured(ValueError):
    """A bound is missing or non-positive. Refused at construction."""


@dataclass(frozen=True)
class LoopBounds:
    """The three independent "how much" bounds, plus the convergence bound.

    Each of the first three is INDEPENDENTLY sufficient to halt. They are not
    alternatives to each other and none is optional: iterations bound the work,
    wall clock bounds a single hung iteration's blast radius, and spend bounds
    the only one of the three that cannot be undone.
    """

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_wall_clock_s: float = DEFAULT_MAX_WALL_CLOCK_S
    max_spend_usd: float = DEFAULT_MAX_SPEND_USD
    max_attempts_per_candidate: int = DEFAULT_MAX_ATTEMPTS_PER_CANDIDATE

    def __post_init__(self) -> None:
        # NO SENTINEL FOR "UNLIMITED". Not an oversight: an unbounded loop is
        # the failure this module exists to prevent, and offering `0` or `None`
        # as "no limit" would make it one keystroke away. An operator who wants
        # a long run states a large number and can see it in the report.
        for name in ("max_iterations", "max_wall_clock_s", "max_spend_usd",
                     "max_attempts_per_candidate"):
            value = getattr(self, name)
            if value is None or float(value) <= 0:
                raise LoopMisconfigured(
                    f"{name}={value!r}: every bound must be positive. This loop "
                    "has no 'unlimited' setting by design -- state a large "
                    "number instead, so the report can show what you chose.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_iterations": int(self.max_iterations),
            "max_wall_clock_s": float(self.max_wall_clock_s),
            "max_spend_usd": float(self.max_spend_usd),
            "max_attempts_per_candidate": int(self.max_attempts_per_candidate),
        }


# --------------------------------------------------------------------------- #
# convergence memory                                                           #
# --------------------------------------------------------------------------- #
def _path_key(p: Any) -> str:
    """Normalize a declared path for comparison.

    MIRRORS ``daedalus.kairos.scheduler._paths_overlap``'s key exactly
    (``str(p).replace("\\\\", "/")``) and must keep mirroring it. That function
    answers "do two assignments in one wave collide?" and returns a bool; this
    module needs the colliding key's IDENTITY to name it in a report, so the
    shapes differ -- but if the two ever normalized differently, one surface
    would call a pair of paths the same file and the other would not, which is
    precisely the two-predicates-one-question drift this tree keeps paying for.
    Same key, two questions.
    """
    return str(p).replace("\\", "/").strip()


class LoopLedger:
    """What this loop has attempted, keyed by PICKER CANDIDATE id.

    WHY THIS IS NOT ``daedalus.spine.picker``'S ATTEMPT MEMORY, stated
    carefully because adding a second memory to a tree with a documented
    duplicate-predicate problem needs a better excuse than "convenient":

    1. attempt memory is a PENALTY, not a filter -- its own docstring says so,
       and says why (dropping attempted work would let one transient failure
       delete real work from the queue forever). Sinking a candidate reorders a
       list. When the admissible list has ONE entry, reordering it is a no-op
       and the loop re-picks the same candidate forever. Ranking and admission
       are different questions and the picker only answers the first.

    2. MEASURED, and decisive: THE ID SPACES DO NOT JOIN. ``attempt_history``
       looks up exactly the candidate ids it is given
       (``intents_matching_payload("task_id", ...)``), but a wave routed
       through the gated write path attempts under a spec whose id
       ``gated_writes._spec_for`` mints fresh per call --
       ``f"kairos-{lane}-{uuid4().hex[:10]}"``. So an attempt this loop makes
       is recorded in the spine ledger under an id no future picker query will
       ever ask about. ``prior_attempts_same_definition`` therefore stays 0
       across iterations no matter how many times the loop tries, and the
       picker's memory -- which is correct, and works for the human ``--once``
       path it was built for -- cannot see this loop's own history at all.

    So the two are not two answers to one question; they answer different
    questions off different keys, and they cannot diverge because neither is
    derived from the other and neither is consulted for the other's question.
    That is the ONLY shape in which a second mechanism is defensible here.

    THE GAP IS RECORDED, NOT PAPERED OVER. Every record keeps the wave's
    minted ``attempt_task_ids``, which is the join key the picker cannot
    compute. A human (or a later fix that gives ``_spec_for`` a stable id) can
    reconcile this ledger against the spine ledger from that field alone.

    THE SECOND JOIN KEY, AND WHY IT DOES NOT REPLACE THE FIRST.
    ``attempt_task_ids`` answers *which attempt* -- it is the id the spine
    ledger actually filed the row under, and it exists because
    ``gated_writes._spec_for`` mints an id the picker can never predict. It
    stays exactly as it was. ``trace_id`` answers a different question --
    *which run* -- and needs no computing by anyone: it is the same value the
    spine ledger and the bridge records carry, so the reconciliation that
    ``attempt_task_ids`` makes POSSIBLE for a human, ``trace_id`` makes a
    grep. Neither is derived from the other; both are recorded.
    """

    #: /2 added ``trace_id`` (file level and per attempt) and wrapped the saved
    #: document in an ITE-6 statement. MEASURED 2026-07-29: nothing outside
    #: this module reads the file, so the bump breaks no reader -- and
    #: :meth:`load` accepts /1 and /2, wrapped or bare, either way.
    SCHEMA = "daedalus.loop.ledger/2"

    def __init__(self, path: str | Path | None = None, *,
                 trace_id: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.attempts: dict[str, dict[str, Any]] = {}
        #: path key -> the claim that owns it. See :meth:`claim`.
        self.claims: dict[str, dict[str, Any]] = {}
        #: The run this ledger belongs to. Captured at CONSTRUCTION rather than
        #: read at save time, because the driver builds the ledger before it
        #: enters its traced scope and a save-time read would find nothing.
        self.trace_id = str(trace_id) if trace_id else current_trace_id()

    # -- reading ----------------------------------------------------------- #
    def n_attempts(self, candidate_id: str) -> int:
        rec = self.attempts.get(str(candidate_id))
        return int(rec.get("n", 0)) if rec else 0

    def outcomes(self, candidate_id: str) -> list[str]:
        rec = self.attempts.get(str(candidate_id))
        return list(rec.get("outcomes", [])) if rec else []

    def verdict(self, candidate_id: str, paths: Sequence[str],
                bounds: LoopBounds) -> tuple[bool, str]:
        """``(admissible, why_not)``. The loop's ONLY admission predicate.

        Two grounds for refusal, and they are different failures: the candidate
        has had its chances (convergence), or its files are already spoken for
        by an earlier iteration of this run (mergeability -- see :meth:`claim`).
        """
        n = self.n_attempts(candidate_id)
        if n >= int(bounds.max_attempts_per_candidate):
            return False, (
                f"attempted {n}x in this run with outcome(s) "
                f"{', '.join(self.outcomes(candidate_id)) or 'unknown'}; "
                f"max_attempts_per_candidate={bounds.max_attempts_per_candidate}")
        hit = self.claimed_by(paths)
        if hit is not None:
            key, claim = hit
            return False, (
                f"path {key!r} is already claimed by iteration "
                f"{claim['iteration']} ({claim['candidate_id']}, branch "
                f"{claim.get('integration_branch') or 'n/a'}, basis="
                f"{claim['basis']}). Both would be cut from the SAME primary "
                "HEAD into sibling integration branches that cannot see each "
                "other, so both could pass their gates and still conflict when "
                "a human merges them.")
        return True, ""

    def claimed_by(self, paths: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
        """The first prior claim these paths collide with, or ``None``."""
        for p in paths or ():
            key = _path_key(p)
            if key in self.claims:
                return key, self.claims[key]
        return None

    def claim(self, candidate_id: str, paths: Sequence[str], *, iteration: int,
              basis: str, integration_branch: str | None = None) -> list[str]:
        """Reserve ``paths`` for the rest of this run. Returns the keys taken.

        WHY A RUN NEEDS THIS AT ALL, measured rather than assumed:
        ``gated_writes.promote_candidates`` mints a FRESH integration branch
        per call -- ``f"kairos-integration-{uuid4().hex[:10]}"``, rooted at a
        freshly read primary HEAD. This loop calls it once per iteration, and
        promotion is structurally capped at candidate -> integration branch at
        every policy level, so primary HEAD never moves underneath the run.
        N iterations therefore produce N SIBLING branches off one base, none
        aware of any other. That module's cumulative re-gate reconciles
        candidates promoted within ONE call; across calls it does nothing.

        Without this guard the loop's most dangerous output is not a failure
        but a SUCCESS REPORT: two iterations that fixed the same file both
        pass their own gates, and a human discovers at merge time that only
        one of them can land. The loop would have reported two wins.

        ``basis`` names where the paths came from, because the two sources are
        not equally trustworthy: ``"changed_paths"`` is MEASURED (the promote
        report's record of what the patch actually touched) while
        ``"declared"`` is the task's path hint, which an agentic worker is not
        bound by -- the same caveat ``kairos.scheduler._paths_overlap`` and
        ``build.wave_path_conflicts`` both carry. A declared-path claim can
        therefore miss a real collision; it cannot invent a false one.
        """
        taken: list[str] = []
        for p in paths or ():
            key = _path_key(p)
            if not key or key in self.claims:
                continue
            self.claims[key] = {
                "candidate_id": str(candidate_id), "iteration": int(iteration),
                "basis": basis, "integration_branch": integration_branch,
            }
            taken.append(key)
        return taken

    # -- writing ----------------------------------------------------------- #
    def record(self, candidate_id: str, *, outcome: str, iteration: int,
               attempt_task_ids: Sequence[str] = (),
               detail: Mapping[str, Any] | None = None) -> None:
        rec = self.attempts.setdefault(
            str(candidate_id),
            {"n": 0, "outcomes": [], "attempt_task_ids": [], "iterations": [],
             "trace_ids": []})
        rec["n"] = int(rec["n"]) + 1
        rec["outcomes"].append(str(outcome))
        rec["iterations"].append(int(iteration))
        # The join key the picker cannot compute for itself -- see the class
        # docstring. Kept even when empty, so "we got no id back" is visible
        # rather than looking like "we never recorded one".
        rec["attempt_task_ids"].append([str(t) for t in attempt_task_ids])
        # Parallel to it, one per attempt, so an attempt record LIFTED OUT of
        # this file is still joinable on its own. Normally identical to the
        # file-level trace; recorded per attempt anyway because a record that
        # depends on its container to be interpretable is the exact failure
        # this whole feature exists to fix.
        # setdefault, not [...]: a ledger restored from a /1 document has
        # attempt records with no such list.
        rec.setdefault("trace_ids", []).append(
            current_trace_id() or self.trace_id)
        if detail:
            rec.setdefault("detail", []).append(dict(detail))

    # -- the document, and reading it back --------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        """The ledger BODY -- what :meth:`save` puts inside the envelope.

        Still flat, still carrying ``schema``/``attempts``/``claims`` under
        their original names, so this remains the shape every existing caller
        of ``to_dict()`` expects. ``trace_id`` is additive.
        """
        body = {"schema": self.SCHEMA, "attempts": self.attempts,
                "claims": self.claims}
        if self.trace_id:
            body["trace_id"] = self.trace_id
        return body

    @staticmethod
    def load(path: str | Path) -> dict[str, Any]:
        """The ledger body from a file, ENVELOPED OR NOT.

        The both-directions reader. A /1 document is a bare body and comes
        back untouched; a /2 document is an ITE-6 statement and comes back
        unwrapped to the same shape. A caller never has to know which it got,
        which is the property that lets the envelope land without a migration.
        """
        return unwrap(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self) -> Path | None:
        """Persist as an ITE-6 statement. Returns the path, or ``None`` when
        there is nowhere to write (a dry run passes no path, because a dry run
        changes nothing).

        The body goes into ``predicate`` UNALTERED -- no key of it is renamed,
        added to or removed -- so :meth:`load` hands back exactly what a /1
        reader would have read. The subject digest is over the canonical
        rendering of the body, not over the pretty-printed bytes on disk: the
        file stays ``indent=2`` for humans, and the digest stays stable against
        a reformat.
        """
        if self.path is None:
            return None
        body = self.to_dict()
        doc = statement(
            subject=subject_for(self.path.name, sha256=canonical_sha(body)),
            predicate_type=PREDICATE_LOOP_LEDGER,
            predicate=body,
            trace_id=self.trace_id)
        # Atomic publish with the win32 retry -- see daedalus.atomic. The ledger
        # is polled by the web loop endpoint and the mission-control view, which
        # is the concurrent-reader case the bare replace loses.
        write_text_atomic(self.path, json.dumps(doc, indent=2))
        return self.path


def _curated_gate(candidate: Any) -> dict[str, Any]:
    """The per-candidate execution hints the picker carries, or ``{}``.

    WHAT TRAVELS. ``Candidate`` carries four curated gate things
    (``gate_argv``, ``gate_cwd``/``gate_timeout_s``, ``gate_paths``,
    ``base_revision``), plus measured evidence. The command-gate triple and the
    measured ``rewrite_windows`` evidence are forwarded:

    * ``gate_argv`` (+ cwd/timeout) -- the whole point. Without it a docref
      candidate is judged by ``offload()``'s project-wide test command, which
      says nothing about whether the document's references now resolve.
    * ``rewrite_windows`` -- the docref scanner already measured which lines
      are broken. Without this hint the isolated write-wave seam asks Ollama
      for a full-file rewrite; a 2,496-line HANDOFF is then correctly refused
      as too large and every attempt becomes a fast, unexplained no-op.
    * ``gate_paths`` is deliberately DROPPED, not forgotten. It only feeds the
      default pytest gate, which the curated argv replaces outright -- and
      ``spine/picker.py`` documents that forwarding it is what produced
      ``pytest docs/THAT.md``: a gate that failed every docref attempt for a
      reason unrelated to the fix, fail-closed and indistinguishable from a
      real finding.
    * ``base_revision`` is deliberately DROPPED. The picker observed it when it
      ranked; ``gated_writes`` re-reads HEAD at dispatch. Substituting the
      older value would attempt on ground that may have moved and would cut
      across the promotion lock's staleness handling -- a correctness change to
      the write path, not an observability one, and out of scope here.

    A gate whose ``cwd`` is not "." is also dropped: ``TaskAttempt.__init__``
    rejects that combination outright (subdirectory execution is unimplemented),
    so forwarding one would convert a task that runs today into a hard
    ValueError. Falling back to the existing gate is the degradation; crashing
    the attempt is not.
    """
    out: dict[str, Any] = {}
    evidence = getattr(candidate, "evidence", {})
    if isinstance(evidence, Mapping):
        rewrite_windows = evidence.get("rewrite_windows")
        if isinstance(rewrite_windows, Mapping) and rewrite_windows:
            out["rewrite_windows"] = dict(rewrite_windows)

    argv = tuple(getattr(candidate, "gate_argv", ()) or ())
    if not argv:
        return out
    cwd = str(getattr(candidate, "gate_cwd", ".") or ".")
    if cwd != ".":
        return out
    out.update({
        "argv": [str(a) for a in argv],
        "cwd": cwd,
        "timeout_s": float(getattr(candidate, "gate_timeout_s", 900.0) or 900.0),
    })
    return out


def _model_of(raw: Mapping[str, Any]) -> str:
    """The model id a wave result REPORTS, or ``""``.

    Best-effort by construction, and deliberately not clever: it reads the two
    places a model id could legitimately appear (the result dict itself, and
    the nested raw ``offload()`` report under "result") and otherwise gives up.

    It never falls back to a routing PREFERENCE. `daedalus.offload` passes a
    `preferred_model` into its provider call but does not report back what
    actually answered, so a preference is a request, not an observation --
    recording one here would put an unmeasured claim in the ledger under a
    field a reader would reasonably trust as measured. Empty is the honest
    answer until a provider seam reports the real thing.
    """
    for key in ("model", "model_id"):
        got = raw.get(key)
        if got:
            return str(got)
    nested = raw.get("result")
    if isinstance(nested, Mapping):
        for key in ("model", "model_id"):
            got = nested.get(key)
            if got:
                return str(got)
    return ""


# --------------------------------------------------------------------------- #
# results                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IterationResult:
    """One pick -> attempt -> gate -> (promote) cycle."""

    index: int
    candidate_id: str
    instruction: str
    source: str
    score: float
    #: One of ``daedalus.spine.attempt.ATTEMPT_STATES``, or ``"not_attempted"``
    #: when classification never routed this candidate to an attempt at all.
    outcome: str
    #: ``run_write_wave``'s own status string, verbatim -- "gated_promoted",
    #: "gated_held", "gated_refused", "gated_artifact_lost",
    #: "write_gate_failed", or a dispatch status.
    status: str
    promoted: bool
    reason: str
    #: WHO actually ran it, read from the wave result rather than from this
    #: loop's own routing guess -- ``_session_for`` proposes a lane, but
    #: ``KairosScheduler.accept`` is what decides, and a bounce ("belongs to
    #: the senior crew -> return to Adam") is exactly the case where the two
    #: disagree. Empty when the result carried none.
    lane: str = ""
    worker: str = ""
    #: Best-effort ONLY: no result shape in this repo carries a model id today
    #: (neither KairosScheduler.dispatch's dict nor gated_writes' `base`), so
    #: this is normally "". Kept as a declared field so the day a provider seam
    #: does report one it lands here instead of needing another schema change.
    #: Never back-filled from a routing preference -- a preferred model is not
    #: evidence of the model that ran.
    model: str = ""
    #: Narrow provider-side activation receipt. This explains whether a
    #: requested window actually ran or why it was skipped; prompts and file
    #: content are deliberately excluded upstream.
    provider_receipt: dict[str, Any] | None = None
    #: Durable raw patch bytes for a clean candidate that governance held.
    #: This lives outside the primary checkout; the attempt branch is reaped.
    artifact_path: str | None = None
    artifact_sha256: str = ""
    attempt_task_ids: tuple[str, ...] = ()
    integration_branch: str | None = None
    duration_s: float = 0.0
    spend_usd: float | None = None
    counted: bool = True
    dry_run: bool = False
    claimed_paths: tuple[str, ...] = ()
    claim_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "candidate_id": self.candidate_id,
            "instruction": self.instruction, "source": self.source,
            "score": self.score, "outcome": self.outcome, "status": self.status,
            "promoted": self.promoted, "reason": self.reason,
            "lane": self.lane, "worker": self.worker, "model": self.model,
            "provider_receipt": self.provider_receipt,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "attempt_task_ids": list(self.attempt_task_ids),
            "integration_branch": self.integration_branch,
            "duration_s": round(self.duration_s, 3),
            "spend_usd": self.spend_usd, "counted": self.counted,
            "dry_run": self.dry_run,
            "claimed_paths": list(self.claimed_paths),
            "claim_basis": self.claim_basis,
        }


@dataclass
class LoopReport:
    run_id: str
    repo_root: str
    project: str | None
    bounds: LoopBounds
    dry_run: bool
    #: The run's correlation id. On the REPORT because the report is what an
    #: operator actually reads, and a trace id nobody is told is a trace id
    #: nobody greps. Defaulted so every existing construction of LoopReport
    #: (including the tests') still works.
    trace_id: str = ""
    #: ``"promoting"`` or ``"inert"``. See the module docstring: inert is a
    #: correct, productive state, not a failure.
    mode: str = "inert"
    promotion_allowed: bool = False
    governance_state: str = "unknown"
    governance_verdict: str = ""
    stop_reason: str = "error"
    stop_detail: str = ""
    iterations: list[IterationResult] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_ts: str = ""
    finished_ts: str = ""
    wall_clock_s: float = 0.0
    spend_usd: float | None = None
    ledger_path: str | None = None
    killswitch_path: str | None = None

    @property
    def promoted(self) -> int:
        return sum(1 for it in self.iterations if it.promoted)

    @property
    def integration_branches(self) -> list[str]:
        """Every distinct integration branch this run left behind, in order.

        Each is a SIBLING of the others: ``promote_candidates`` mints a fresh
        ``kairos-integration-<uuid>`` per call off a freshly read primary HEAD,
        and this loop calls it once per iteration. Nothing merges them.
        """
        seen: list[str] = []
        for it in self.iterations:
            b = it.integration_branch
            if b and b not in seen:
                seen.append(b)
        return seen

    @property
    def gated_clean(self) -> int:
        """Iterations that produced a patch which PASSED its gates -- the real
        measure of a productive-but-inert run."""
        return sum(1 for it in self.iterations if it.outcome == "clean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus.loop.report/1",
            "run_id": self.run_id, "trace_id": self.trace_id,
            "repo_root": self.repo_root,
            "project": self.project, "bounds": self.bounds.to_dict(),
            "dry_run": self.dry_run, "mode": self.mode,
            "promotion_allowed": self.promotion_allowed,
            "governance_state": self.governance_state,
            "governance_verdict": self.governance_verdict,
            "stop_reason": self.stop_reason, "stop_detail": self.stop_detail,
            "iterations_run": len(self.iterations),
            "gated_clean": self.gated_clean, "promoted": self.promoted,
            "integration_branches": self.integration_branches,
            "iterations": [it.to_dict() for it in self.iterations],
            "skipped": self.skipped, "notes": self.notes,
            "started_ts": self.started_ts, "finished_ts": self.finished_ts,
            "wall_clock_s": round(self.wall_clock_s, 3),
            "spend_usd": self.spend_usd, "ledger_path": self.ledger_path,
            "killswitch_path": self.killswitch_path,
        }


# --------------------------------------------------------------------------- #
# spend                                                                        #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Spend:
    """One reading of the budget ledger, with the period it belongs to."""

    period_key: str
    spent_usd: float
    readable: bool
    error: str = ""


def read_spend() -> _Spend:
    """Current cumulative spend. NEVER raises: an unreadable budget ledger must
    not crash a loop, but it must also never read as ``$0.00 spent``, which
    would silently disable the spend bound. ``readable=False`` is the signal,
    and the caller treats it as a reason to STOP rather than to continue."""
    try:
        from . import budget

        state = budget.ledger().state()
        return _Spend(period_key=str(state.period_key),
                      spent_usd=float(state.spent_usd), readable=True)
    except Exception as e:  # noqa: BLE001 - see docstring
        return _Spend(period_key="", spent_usd=0.0, readable=False,
                      error=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# the driver                                                                   #
# --------------------------------------------------------------------------- #
class LoopDriver:
    """Runs pick -> attempt -> gate -> promote -> re-pick until a bound says stop.

    Construction does not start anything. :meth:`run` is the only method with
    effects, and every effect it has goes through a module named in the module
    docstring's "what it reuses" list.
    """

    def __init__(self, repo_root: str | Path | None = None, *,
                 project: str | None = None,
                 bounds: LoopBounds | None = None,
                 switch: KillSwitch | None = None,
                 executor: Any = None,
                 dry_run: bool = False,
                 runs_dir: str | Path | None = None,
                 progress_log: Any = None,
                 queue_limit: int = 25) -> None:
        self.repo_root = str(Path(repo_root).resolve() if repo_root else ROOT)
        self.project = project
        self.bounds = bounds or LoopBounds()
        self.dry_run = bool(dry_run)
        self.queue_limit = max(1, int(queue_limit))
        self.run_id = f"loop-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        # THE TRACE IS MINTED HERE, ONCE, and this is the top of a run.
        # ADOPTED rather than minted when one is already in scope: a driver
        # constructed inside an outer traced scope (a wave, an ikarus ask)
        # belongs to that run, and minting a fresh id there would cut the loop
        # out of the very trace that dispatched it. run_id is NOT reused as the
        # trace: run_id means "this LoopDriver", trace_id means "this run and
        # everything downstream of it", and collapsing the two would make the
        # loop the only thing that could ever start a trace.
        self.trace_id = current_trace_id() or new_trace_id()
        self._progress_log = progress_log

        # THE STOP IS BUILT FIRST, before the executor, before the picker,
        # before anything that could spend. If constructing the switch fails,
        # the loop must not exist at all.
        self.switch = switch if switch is not None else KillSwitch(
            repo_root=self.repo_root)

        if executor is None:
            from .build_exec import WaveExecutor

            # ONE LOG FOR THE WHOLE RUN. The executor emits the attempt-level
            # lifecycle and this driver emits the iteration-level one; handing
            # it this loop's log keeps both in a single file, so "what happened
            # in iteration 3" is one read rather than a join across two.
            executor = WaveExecutor(progress_log=self._progress_log)
        self.executor = executor

        base = Path(runs_dir) if runs_dir else Path(self.repo_root) / "runs" / "loop"
        # A DRY RUN GETS NO PATH. Its contract is that it changes nothing, and
        # a persisted convergence ledger is a change.
        self.ledger = LoopLedger(None if self.dry_run else base / f"{self.run_id}.json",
                                 trace_id=self.trace_id)

    # -- observability ----------------------------------------------------- #
    def _emit(self, fn: Any, unit_id: str, **kw: Any) -> None:
        """Emit into the existing progress log. Best-effort by design: losing
        an observation must never take down the run being observed."""
        try:
            fn(unit_id, source=PROGRESS_SOURCE, log=self._progress_log, **kw)
        except Exception:  # noqa: BLE001
            pass

    # -- the bounds, in one place ------------------------------------------ #
    def _stop_reason(self, *, iterations_done: int, started_monotonic: float,
                     spend_at_start: _Spend) -> tuple[str, str] | None:
        """``(reason, detail)`` if the loop must stop now, else ``None``.

        ONE function, called at exactly one point (the top of each iteration),
        so "why would this loop stop" has a single answer and a new bound
        cannot be added somewhere the others are not checked.
        """
        # 1. THE HUMAN FIRST. Checked before the arithmetic bounds because a
        #    human who pressed stop should not have to lose a race with a
        #    counter to be obeyed.
        if self.switch.should_stop():
            return "killswitch", (self.switch.reason
                                  or "the permit is not armed")

        if iterations_done >= int(self.bounds.max_iterations):
            return "max_iterations", (
                f"{iterations_done} iteration(s) completed, bound is "
                f"{self.bounds.max_iterations}")

        elapsed = time.monotonic() - started_monotonic
        if elapsed >= float(self.bounds.max_wall_clock_s):
            return "max_wall_clock", (
                f"{elapsed:.1f}s elapsed, bound is "
                f"{self.bounds.max_wall_clock_s:.1f}s")

        # 3. SPEND. Skipped in a dry run, which cannot spend by construction.
        if not self.dry_run:
            now = read_spend()
            if not now.readable:
                # FAIL CLOSED. An unreadable budget ledger means the spend
                # bound is not enforceable, and a loop that keeps spending
                # while it cannot measure spending is the exact thing three
                # separate bounds exist to prevent.
                return "max_spend", (
                    f"REFUSING TO CONTINUE: the budget ledger is unreadable "
                    f"({now.error}), so the spend bound cannot be enforced. "
                    "Stopping is the only safe reading of 'I do not know how "
                    "much I have spent'.")
            if not spend_at_start.readable:
                return "max_spend", (
                    "REFUSING TO CONTINUE: spend was unreadable at loop start, "
                    "so there is no baseline to measure this run against.")
            if now.period_key != spend_at_start.period_key:
                # The ledger rolled to a new budget period mid-run. `spent_usd`
                # restarted from zero, so `now - start` is now a meaningless
                # (and possibly negative) number. Stop rather than compute a
                # delta that would under-report this run's spend forever after.
                return "max_spend", (
                    f"budget period rolled over mid-run "
                    f"({spend_at_start.period_key!r} -> {now.period_key!r}); "
                    "this run's spend delta is no longer measurable, so the "
                    "bound can no longer be enforced")
            spent = now.spent_usd - spend_at_start.spent_usd
            if spent >= float(self.bounds.max_spend_usd):
                return "max_spend", (
                    f"${spent:.4f} spent by this run, bound is "
                    f"${self.bounds.max_spend_usd:.2f}")
        return None

    # -- picking ------------------------------------------------------------ #
    def _pick(self) -> tuple[Any, list[dict[str, Any]], str]:
        """``(candidate, skipped, note)``. ``candidate`` is ``None`` when the
        queue holds nothing this loop may still attempt."""
        from .spine.picker import build_queue

        queue = build_queue(self.repo_root, limit=self.queue_limit)

        skipped: list[dict[str, Any]] = []
        for cand in queue.candidates:
            ok, why = self.ledger.verdict(
                cand.task_id, list(cand.target_paths), self.bounds)
            if ok:
                return cand, skipped, ""
            # VISIBLE, NOT SILENT. Every candidate this loop declines to
            # re-pick is reported with the evidence that declined it.
            skipped.append({"candidate_id": cand.task_id, "reason": why,
                            "score": cand.score, "source": cand.source,
                            "instruction": cand.instruction[:200]})
        if not queue.candidates:
            return None, skipped, "the picker returned an empty queue"
        return None, skipped, (
            f"none of the {len(queue.candidates)} ranked candidate(s) is still "
            "admissible: each has either exhausted "
            f"max_attempts_per_candidate={self.bounds.max_attempts_per_candidate} "
            "or targets a file an earlier iteration already claimed (see "
            "`skipped` for which, per candidate)")

    # -- one iteration ------------------------------------------------------ #
    def _session_for(self, candidate: Any) -> Any:
        """Wrap ONE picker candidate as a one-task, one-wave BuildSession.

        NOT ``daedalus.build.plan_build``: that decomposes a FEATURE into
        subtasks, and a picker candidate is already a subtask -- the picker
        decided the unit of work, and re-decomposing it would both re-plan
        settled work and add a model call per iteration.

        THE CURATED GATE NOW TRAVELS; THE BASE STILL DOES NOT. This used to
        drop all three of ``Candidate``'s curated fields, because the gated
        write path builds its own ``TaskSpec`` from the Assignment. The
        command gate (``gate_argv`` + cwd/timeout) is now forwarded --
        ``_curated_gate`` explains exactly what is carried and what is not --
        so a docref candidate is judged by its own re-scan instead of by the
        project's whole test command.

        Still dropped, deliberately: ``gate_paths`` (inert once a command gate
        exists, and actively harmful if forwarded -- see ``_curated_gate``) and
        ``base_revision`` (``gated_writes`` re-reads HEAD; overriding it is a
        correctness change to the write path, not an observability one). No
        second attempt path was forked, so the promotion lock, the governance
        AND and worktree isolation are all still the existing ones.
        """
        from .build import BuildSession, BuildTask, Wave, assign_builder
        from .categories import preset_for
        from .kairos.scheduler import KairosScheduler
        from .router import route_task

        foreman = KairosScheduler(project=self.project)
        agent = route_task(candidate.instruction, list(candidate.target_paths),
                           repo_root=self.repo_root,
                           active_agents=foreman.active_agents)
        preset = preset_for(agent, self.repo_root)
        lane, tier = preset["lane"], preset["tier"]
        builder, frontier = assign_builder(lane)
        task = BuildTask(
            objective=candidate.instruction,
            agent=agent.get("name", "unknown"),
            category=agent.get("category", "") or "",
            lane=lane, tier=tier, builder=builder, frontier=frontier,
            paths=list(candidate.target_paths),
        )
        return BuildSession(
            feature=candidate.instruction[:120],
            repo_root=self.repo_root, project=self.project,
            waves=[Wave(index=0, tasks=[task])],
            slug=self.run_id, created="", max_workers=foreman.max_workers,
        )

    @staticmethod
    def _outcome_of(result: Mapping[str, Any]) -> str:
        """The attempt state for one wave result, in the ledger's OWN
        vocabulary (``daedalus.spine.attempt.ATTEMPT_STATES``) -- read from the
        result, never re-derived from the status string. A result with no
        ``attempt_state`` never reached an attempt (classification routed it
        advisory, or it was a dry-run preview); that is its own outcome and is
        never quietly folded into one of the real states."""
        state = str(result.get("attempt_state") or "")
        if state in ATTEMPT_STATES:
            return state
        return "not_attempted"

    def _run_iteration(self, index: int, candidate: Any) -> IterationResult:
        from .kairos.scheduler import KairosScheduler

        started = time.monotonic()
        spend_before = read_spend() if not self.dry_run else None

        unit = candidate.task_id  # reuse the picker's id space, do not mint one
        self._emit(progress.open_unit, unit,
                   detail={"loop_run": self.run_id, "iteration": index,
                           "score": candidate.score,
                           "picker_source": candidate.source,
                           "dry_run": self.dry_run})
        self._emit(progress.claim_unit, unit,
                   detail={"loop_run": self.run_id, "iteration": index})

        session = self._session_for(candidate)
        scheduler = KairosScheduler(availability=self.executor.availability,
                                    project=self.project)
        wave = session.waves[0]

        # parallel=False is not "run sequentially" -- for a live write wave it
        # means "let run_wave choose the safe path", which is the gated,
        # isolated-worktree one. See WaveExecutor.run_wave's own error text.
        wave_kwargs: dict[str, Any] = {
            "dry_run": self.dry_run,
            "parallel": False,
            "cancel": self.switch,
        }
        curated_gate = _curated_gate(candidate)
        if curated_gate:
            # THE CANDIDATE'S OWN GATE, carried instead of dropped. One task in
            # this wave (see _session_for), so position 0 is the whole mapping.
            #
            # Keep the kwarg absent when there is no curated gate. Besides
            # preserving the pre-feature call byte-for-byte, this matters for
            # injected WaveExecutor-compatible adapters: the hint is an
            # additive capability, not a new mandatory protocol method.
            wave_kwargs["curated_gates"] = {0: curated_gate}
        wave_result = self.executor.run_wave(
            scheduler, wave, self.repo_root, **wave_kwargs)

        raw = wave_result.results[0] if wave_result.results else {}
        provider_receipt = (dict(raw["provider_receipt"])
                            if isinstance(raw.get("provider_receipt"), Mapping)
                            else None)
        outcome = self._outcome_of(raw)
        status = str(raw.get("status") or "")
        promoted = status == "gated_promoted"
        attempt_ids = (str(raw["task_id"]),) if raw.get("task_id") else ()

        # PREFER MEASURED PATHS OVER DECLARED ONES. `changed_paths` is what the
        # patch actually touched (present once a candidate is promoted);
        # `paths` is the task's hint, which an agentic worker is not bound by.
        changed = [str(p) for p in (raw.get("changed_paths") or [])]
        claim_paths = changed or [str(p) for p in (raw.get("paths") or [])]
        claim_basis = "changed_paths" if changed else "declared"

        spend_delta: float | None = None
        if spend_before is not None and spend_before.readable:
            after = read_spend()
            if after.readable and after.period_key == spend_before.period_key:
                spend_delta = round(after.spent_usd - spend_before.spent_usd, 6)

        # DID A HUMAN STOP US MID-WAVE? If so this outcome is not evidence
        # about the candidate. Killing a gate child races that gate's own poll,
        # and the loser reports `gates_failed` for a candidate whose tests were
        # never judged (measured ~50/50; killswitch.py's _watch_loop documents
        # it). Believing that would teach this loop -- permanently, in a file --
        # that innocent work is bad. `counted=False` keeps it out of the
        # convergence ledger while keeping it fully visible in the report.
        interrupted = self.switch.should_stop()
        counted = not interrupted

        self._emit(progress.record_gate_verdict, unit,
                   name="write_wave", passed=(outcome == "clean"),
                   detail={"loop_run": self.run_id, "iteration": index,
                           "attempt_state": outcome, "status": status,
                           "promoted": promoted, "counted": counted,
                           "provider_receipt": provider_receipt})
        self._emit(progress.record_done, unit,
                   succeeded=(True if promoted else
                              (True if outcome == "clean" else False)),
                   reason=f"{status or outcome}"
                          f"{' (interrupted)' if interrupted else ''}")

        # CLAIM THE FILES, but only for work that actually produced a patch.
        # A candidate whose attempt failed outright changed nothing and must
        # not lock its files away from a later, better attempt. A candidate
        # that reached `clean` DID produce bytes -- promoted or merely held --
        # and those bytes are preserved in the checkout-external candidate
        # archive a human can inspect/apply, so the files are genuinely spoken
        # for either way.
        claimed: list[str] = []
        if counted and not self.dry_run and outcome == "clean":
            claimed = self.ledger.claim(
                candidate.task_id, claim_paths, iteration=index,
                basis=claim_basis,
                integration_branch=raw.get("integration_branch"))

        return IterationResult(
            index=index, candidate_id=candidate.task_id,
            instruction=candidate.instruction, source=candidate.source,
            score=float(candidate.score),
            outcome=(STATE_CANCELLED if interrupted and outcome == "not_attempted"
                     else outcome),
            status=status, promoted=promoted,
            reason=str(raw.get("reason") or ""),
            lane=str(raw.get("lane") or ""), worker=str(raw.get("worker") or ""),
            model=_model_of(raw),
            provider_receipt=provider_receipt,
            artifact_path=(str(raw["artifact_path"])
                           if raw.get("artifact_path") else None),
            artifact_sha256=str(raw.get("artifact_sha256") or ""),
            attempt_task_ids=attempt_ids,
            integration_branch=raw.get("integration_branch"),
            duration_s=time.monotonic() - started, spend_usd=spend_delta,
            counted=counted, dry_run=self.dry_run,
            claimed_paths=tuple(claimed), claim_basis=claim_basis,
        )

    # -- the loop ----------------------------------------------------------- #
    def run(self) -> LoopReport:
        from . import core

        gov = core.get_governance(self.project)
        promotion_allowed = bool(gov.get("promotion_allowed"))
        report = LoopReport(
            run_id=self.run_id, trace_id=self.trace_id,
            repo_root=self.repo_root, project=self.project,
            bounds=self.bounds, dry_run=self.dry_run,
            mode="promoting" if promotion_allowed else "inert",
            promotion_allowed=promotion_allowed,
            governance_state=str(gov.get("state") or "unknown"),
            governance_verdict=str(gov.get("verdict") or ""),
            started_ts=progress.now_iso(),
            killswitch_path=str(self.switch.path),
        )
        if not promotion_allowed:
            report.notes.append(
                f"RUNNING PRODUCTIVELY BUT INERTLY: governance state="
                f"{report.governance_state!r} blocks promotion, so this loop "
                "will pick, attempt and gate normally and promote NOTHING. "
                "Every candidate that clears its gate is a real patch waiting "
                f"in an integration worktree. Verdict: {report.governance_verdict}")

        spend_at_start = read_spend() if not self.dry_run else _Spend("", 0.0, True)
        if not self.dry_run and not spend_at_start.readable:
            report.notes.append(
                f"budget ledger unreadable at start ({spend_at_start.error})")

        started_monotonic = time.monotonic()
        try:
            # THE WATCHER IS THE OUTERMOST SCOPE OF THE RUN. Inside it, a
            # revoked permit both latches this object and reaps every live
            # managed child process -- so a stop takes effect even in the
            # middle of a wave, not only between iterations.
            #
            # The trace is bound INSIDE it, deliberately: the watcher keeps
            # its documented place as the outermost scope, and everything the
            # run reaches from here -- spine.attempt's record_intent, any
            # file_bridge.enqueue, any child process -- reads the same id
            # ambiently. That is what converts three producers without
            # editing gated_writes.py or attempt.py, neither of which is in
            # this change's fence.
            with self.switch.watch(), trace_context(self.trace_id):
                while True:
                    stop = self._stop_reason(
                        iterations_done=len(report.iterations),
                        started_monotonic=started_monotonic,
                        spend_at_start=spend_at_start)
                    if stop is not None:
                        report.stop_reason, report.stop_detail = stop
                        break

                    candidate, skipped, note = self._pick()
                    report.skipped.extend(skipped)
                    if candidate is None:
                        report.stop_reason = "queue_exhausted"
                        report.stop_detail = note
                        break

                    iteration = self._run_iteration(len(report.iterations), candidate)
                    report.iterations.append(iteration)
                    if iteration.counted:
                        self.ledger.record(
                            candidate.task_id, outcome=iteration.outcome,
                            iteration=iteration.index,
                            attempt_task_ids=iteration.attempt_task_ids,
                            # THE REASON RIDES WITH THE RECORD. A detail of
                            # {"status": "bounced"} is what cost an hour of
                            # ledger archaeology: "bounced" names the shape of
                            # the outcome and nothing about its cause, while
                            # the cause ("belongs to the senior crew -> return
                            # to Adam") was sitting unread on the wave result.
                            # lane/worker travel with it because "who was this
                            # even given to" is the very next question a reader
                            # asks, and answering it should not need a join
                            # against a second file.
                            detail={"status": iteration.status,
                                    "promoted": iteration.promoted,
                                    "reason": iteration.reason,
                                    "lane": iteration.lane,
                                    "worker": iteration.worker,
                                    "model": iteration.model,
                                    "provider_receipt": iteration.provider_receipt,
                                    "artifact_path": iteration.artifact_path,
                                    "artifact_sha256": iteration.artifact_sha256})
                        self.ledger.save()
                    else:
                        report.notes.append(
                            f"iteration {iteration.index} ({candidate.task_id}): "
                            "interrupted by the kill switch; its outcome is NOT "
                            "recorded as evidence about this candidate, because "
                            "a cancelled gate cannot be distinguished from a "
                            "failed one on this path")
        except LoopHalted as e:
            report.stop_reason = "killswitch"
            report.stop_detail = str(e)
        except KeyboardInterrupt:
            report.stop_reason = "killswitch"
            report.stop_detail = "KeyboardInterrupt (operator)"
        except Exception as e:  # noqa: BLE001 - reported, never swallowed
            report.stop_reason = "error"
            report.stop_detail = f"{type(e).__name__}: {e}"

        report.finished_ts = progress.now_iso()
        report.wall_clock_s = time.monotonic() - started_monotonic
        if not self.dry_run and spend_at_start.readable:
            end = read_spend()
            if end.readable and end.period_key == spend_at_start.period_key:
                report.spend_usd = round(end.spent_usd - spend_at_start.spent_usd, 6)

        # WHAT A HUMAN HAS TO DO NEXT, spelled out rather than left implicit.
        # Every branch here is a sibling of every other, cut from the same
        # primary HEAD, and none of them is merged. The loop cannot merge them
        # (integration -> primary is a human `git merge`, at every policy
        # level) and it deliberately does not try.
        branches = report.integration_branches
        if branches:
            report.notes.append(
                f"{len(branches)} integration branch(es) are waiting for a "
                f"human: {', '.join(branches)}. They are SIBLINGS off the same "
                "primary HEAD -- each was gated independently and none can see "
                "the others -- so merging them is not guaranteed to be "
                "conflict-free even though each passed its own gate. Inspect "
                "with `git diff <base>..<branch>`. The path-claim guard kept "
                "them off each other's declared files within this run; it "
                "cannot speak for undeclared edits or for branches left by a "
                "previous run.")

        saved = self.ledger.save()
        report.ledger_path = str(saved) if saved else None
        return report


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #
def render(report: LoopReport) -> str:
    lines: list[str] = []
    head = f"loop {report.run_id}  [{report.mode.upper()}]"
    if report.dry_run:
        head += "  (dry run -- nothing attempted, nothing spent)"
    lines.append(head)
    if report.trace_id:
        # Printed as a ready-to-run grep rather than as a bare field: the id is
        # only useful to someone who knows it is greppable, and telling them
        # costs one line.
        lines.append(f"  trace: {report.trace_id}   "
                     f"(grep -r {report.trace_id} runs/)")
    lines.append(f"  stopped: {report.stop_reason} -- {report.stop_detail}")
    lines.append(
        f"  governance: state={report.governance_state} "
        f"promotion_allowed={report.promotion_allowed}")
    lines.append(
        f"  iterations: {len(report.iterations)}/{report.bounds.max_iterations}"
        f"   gated-clean: {report.gated_clean}   promoted: {report.promoted}")
    spend = "n/a" if report.spend_usd is None else f"${report.spend_usd:.4f}"
    lines.append(
        f"  wall clock: {report.wall_clock_s:.1f}s/"
        f"{report.bounds.max_wall_clock_s:.0f}s   spend: {spend}/"
        f"${report.bounds.max_spend_usd:.2f}")
    lines.append(f"  kill switch: {report.killswitch_path}")
    for it in report.iterations:
        flag = "" if it.counted else "  [INTERRUPTED - not counted]"
        # WHO, then WHY, on the same line as the verdict. An operator reading
        # this is asking "why did that produce nothing?", and every earlier
        # version of this line answered only "it produced nothing". The reason
        # is truncated, not dropped: the untruncated text is in the report JSON
        # and the ledger detail, and a line that wraps the terminal is a line
        # nobody scans.
        who = f"  [{it.lane or '?'}/{it.worker or '?'}]" if (it.lane or it.worker) else ""
        why = ""
        if it.reason:
            r = " ".join(str(it.reason).split())
            why = f"\n         why: {r[:200]}{'...' if len(r) > 200 else ''}"
        lines.append(
            f"    #{it.index} {it.candidate_id}  {it.outcome}/{it.status or '-'}"
            f"  {it.duration_s:.1f}s{who}{flag}{why}")
    branches = report.integration_branches
    if branches:
        lines.append(f"  awaiting a human `git merge` ({len(branches)} sibling "
                     f"branch(es), same base, unmerged):")
        for b in branches:
            lines.append(f"    {b}")
    if report.skipped:
        lines.append(f"  not re-picked ({len(report.skipped)}):")
        for s in report.skipped[:10]:
            lines.append(f"    {s['candidate_id']}: {s['reason']}")
    for note in report.notes:
        lines.append(f"  NOTE: {note}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    # `.env` FIRST, then the ceiling -- the same order as cli.main, for the
    # same reason: the guard's own configuration (the ceiling, the declared
    # subscriptions, the trusted bench, OLLAMA_HOST) lives exactly there.
    # MEASURED 2026-07-29, first live run: this entry point skipped the load,
    # so the router saw no reachable local lane, escalated every docref task
    # to the paid tier, and the free-lane gate bounced all three attempts with
    # "belongs to the senior crew" -- a loop that could only refuse. The
    # bounce was CORRECT; the blindness was the bug.
    from .dotenv import DotEnvRefused, load as _load_dotenv

    try:
        _load_dotenv()
    except DotEnvRefused as exc:
        print(f"[daedalus] REFUSED: {exc}", file=sys.stderr)
        return 2

    # THE CEILING GOES ON BEFORE ANYTHING ELSE IN THIS PROCESS, including
    # argument parsing -- the same posture as every other spend entry point in
    # this tree (tests/test_spend_coverage.py enforces it). A loop driver is
    # the entry point where forgetting it costs the most.
    from .budget import install_process_guard

    install_process_guard()

    p = argparse.ArgumentParser(
        prog="python -m daedalus.loop",
        description="Run pick -> attempt -> gate -> promote -> re-pick until a "
                    "bound stops it. Stop it from anywhere with "
                    "`python -m daedalus.spine.killswitch stop`.")
    p.add_argument("--repo-root", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    p.add_argument("--max-wall-clock-s", type=float, default=DEFAULT_MAX_WALL_CLOCK_S)
    p.add_argument("--max-spend-usd", type=float, default=DEFAULT_MAX_SPEND_USD)
    p.add_argument("--max-attempts-per-candidate", type=int,
                   default=DEFAULT_MAX_ATTEMPTS_PER_CANDIDATE)
    p.add_argument("--queue-limit", type=int, default=25)
    p.add_argument("--dry-run", action="store_true",
                   help="pick and preview every iteration; attempt nothing, "
                        "spend nothing, persist nothing")
    p.add_argument("--json", action="store_true", help="emit the report as JSON")
    p.add_argument("--arm", action="store_true",
                   help="arm the kill switch before starting. REFUSES if a "
                        "human stopped a previous run (clear it deliberately).")
    args = p.parse_args(list(argv) if argv is not None else None)

    try:
        bounds = LoopBounds(
            max_iterations=args.max_iterations,
            max_wall_clock_s=args.max_wall_clock_s,
            max_spend_usd=args.max_spend_usd,
            max_attempts_per_candidate=args.max_attempts_per_candidate)
    except LoopMisconfigured as e:
        print(f"refusing to start: {e}", file=sys.stderr)
        return 2

    driver = LoopDriver(args.repo_root, project=args.project, bounds=bounds,
                        dry_run=args.dry_run, queue_limit=args.queue_limit)

    if args.arm:
        try:
            driver.switch.arm(note=f"loop {driver.run_id}")
        except LoopHalted as e:
            # A human stopped a previous run and the marker is still there.
            # Re-arming automatically here is exactly the "supervisor restarts
            # the loop and the 3am stop evaporates" failure arm() refuses.
            print(str(e), file=sys.stderr)
            return 4

    report = driver.run()
    print(json.dumps(report.to_dict(), indent=2) if args.json else render(report))
    # Exit codes an operator (or a supervisor) can branch on without parsing.
    if report.stop_reason == "error":
        return 1
    if report.stop_reason == "killswitch":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
