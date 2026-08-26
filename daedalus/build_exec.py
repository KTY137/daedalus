"""Wave executor -- the missing half of the build-session abstraction.

``daedalus.build`` plans a multi-wave, frontier-first build and writes it to
``runs/build/*.json``. Nothing in that module runs anything; its own
docstring says so ("planning state around the harness, not a replacement for
it"). This module is the replacement's other half: it takes a saved
:class:`daedalus.build.BuildSession`, dispatches each :class:`~daedalus.build.Wave`
through :class:`daedalus.kairos.scheduler.KairosScheduler`, and collects the
results back onto each :class:`~daedalus.build.BuildTask` (and back to disk).

THE ONE RULE THIS MODULE EXISTS TO ENFORCE
--------------------------------------------
Concurrent WRITE tasks are unsafe against a shared checkout today: every
``offload()`` call gets a fresh provider whose rollback snapshot is per-call
while the FILES are shared, so a failing verify in task A can roll back over
task B's already-landed write with no error raised. ``KairosScheduler.dispatch``
already refuses this correctly (``can_parallel = parallel and not has_writes``)
-- but it refuses *quietly*: ask it for ``parallel=True`` over a batch that
turns out to contain a write and it silently runs sequential anyway, leaving
only a ``{"status": "note", ...}`` dict *prepended* to its return list as the
trace (see ``dispatch()`` in daedalus/kairos/scheduler.py). That prepend also
means the return list is ``len(tasks) + 1`` long in exactly that case -- a
positional zip against the input tasks silently misattributes results if you
don't know to look for it.

This executor never lets that path trigger. It classifies a wave (via
``KairosScheduler.accept`` -- pure routing, no execution) *before* deciding
whether to ask ``dispatch()`` for ``parallel=True``, so it only ever requests
parallel when the wave is already known to be write-free. If a caller asks
:func:`WaveExecutor.run_wave` for ``parallel=True`` over a wave that turns out
to contain a write, it refuses loudly (:class:`UnsafeParallelWriteError`)
instead of downgrading the request. :func:`WaveExecutor.run`, the normal
entry point, never triggers that refusal itself -- it classifies first and
asks for the right thing -- so the exception exists as a hard contract for
anyone (including future code) calling ``run_wave`` directly.

PER-TASK WRITE ISOLATION (wired 2026-07-29)
--------------------------------------------
A LIVE write-containing wave no longer forces ``dispatch(..., parallel=False)``
(the old whole-checkout-snapshot, no-review auto-land). The write branch below
(look for ``_WRITE_WAVE_POLICY``) calls
:func:`daedalus.kairos.gated_writes.run_write_wave`, which runs every write
task concurrently, each in its own worktree via ``daedalus.spine.attempt
.TaskAttempt`` (``KairosScheduler.gate_concurrent_writes``'s own isolation),
and returns gated ``PatchArtifact`` candidates -- never a live write in the
primary checkout at ``repo_root``.

Every candidate remains held in the external artifact archive until an owner
explicitly invokes the separate promotion path. ``write_wave_policy`` now
resolves only to ``never``; historical auto-promotion values are denied. A DRY
RUN wave (or a write-free wave) is unaffected -- it still goes through
``KairosScheduler.dispatch()`` below, because ``gate_candidates`` always runs
a real ``offload()`` attempt and has no dry-run mode to preview through.

Every other line in this module is unaffected by any of this -- the
wave-by-wave loop, the resume logic, and the status bookkeeping all operate on
results, not on how those results were produced. ``BuildTask.status`` still
only ever coarses a write-wave outcome to "landed" when ``repo_root`` itself
changed (never true for a gated candidate, promoted or not) -- see the coarse
mapping comment on ``_task_status`` below.

Run it: ``python -m daedalus.build_exec runs/build/<slug>-<ts>.json`` defaults
to a dry-run preview (no provider touched, nothing written -- see
``KairosScheduler.dispatch``'s own dry_run path, which returns before
``offload()`` is ever called). Pass ``--live`` to actually dispatch.
"""

from __future__ import annotations

import inspect
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import progress
from .build import BuildSession, Wave, load_session, wave_path_conflicts
from .kairos.scheduler import (
    SPEND_REFUSED_SKIPPED_STATUS,
    SPEND_REFUSED_STATUS,
    Assignment,
    KairosScheduler,
    spend_refused_result,
)


class UnsafeParallelWriteError(RuntimeError):
    """Raised when a caller asks :func:`WaveExecutor.run_wave` to run a
    WRITE-mode wave concurrently. Refused, not downgraded: concurrent
    ``offload()`` calls share one working tree but each gets an independent
    rollback snapshot, so a failing verify in one task can silently overwrite
    another task's already-landed write (see ``KairosScheduler.dispatch``'s
    ``can_parallel`` comment for the full argument). Sequential is the only
    safe mode through this executor until per-task worktree isolation is
    wired in -- see the module docstring's "WHEN PER-TASK WRITE ISOLATION
    LANDS" section for exactly where that wiring goes."""


# Coarse dispatch-result -> BuildTask.status mapping. Deliberately fails
# TOWARD "bounced" (did not land): only the exact live success action and the
# exact dry-run preview action map anywhere else. Any status this executor
# has not seen before -- a new offload() action, a scheduler.py change, the
# "note" dict this module is specifically built to never encounter -- lands
# here too, rather than being mistaken for a landed write. Full detail is
# never lost: the raw dict this coarse label was computed from always rides
# along in BuildTask.last_result.
_LANDED_STATUSES = {"offloaded"}
_PLANNED_STATUSES = {"planned"}
# NOT landed, on purpose: daedalus.kairos.gated_writes.run_write_wave's own
# current statuses ("gated_held", "gated_artifact_lost",
# "write_gate_failed") all fall through to "bounced" below. Historical or
# injected adapters may still return "gated_promoted"/"gated_refused"; those
# also remain non-landed. "Landed" here has only ever meant repo_root's PRIMARY
# checkout changed, and the gated path never does that. The full status string
# and reason are preserved in BuildTask.last_result.


#: Attribution for every progress event this module records. A ProgressEvent
#: with no source is refused at construction (progress.ProgressEvent.__post_init__)
#: precisely so an observation can never be read without knowing who made it.
PROGRESS_SOURCE = "daedalus.build_exec"

#: How often a blocked wave proves its dispatching thread is still alive.
#: Matches progress_sources.track_call's own default rather than inventing a
#: second cadence, and sits well inside progress.DEFAULT_STALL_BUDGET_S (90s)
#: so a HEALTHY wave never drifts into the stall window between beats -- the
#: stall detector should fire on a wedged wave, not on a quiet one.
_HEARTBEAT_INTERVAL_S = 15.0


def _attempt_unit_id(wave_index: int, pos: int, nonce: str) -> str:
    """The progress unit id for ONE task in ONE wave dispatch.

    Readable on sight (which wave, which slot) and unique per dispatch, so two
    runs of the same wave never collide in the log. It is deliberately NOT the
    spine attempt's ``task_id``: that id is minted inside ``_spec_for`` and does
    not exist yet when the attempt STARTS, and a lifecycle that cannot name its
    own start is the exact gap this function closes. The real attempt task_id
    is recorded in the finish event's detail once it is known, and the ambient
    trace_id (stamped on every event by progress._record) is what joins the two
    together with the driving loop's own iteration events.
    """
    return f"wave{int(wave_index)}-t{int(pos)}-{nonce}"


def _cancel_requested(cancel: Any) -> bool:
    """Has this cancel token been tripped?

    Delegates to ``daedalus.spine.attempt._as_predicate`` -- the normalizer
    ``run_attempt`` itself uses -- rather than re-deriving "callable, or
    ``.is_set()``, or ``.stopped``" here. Importing a private name is the
    lesser evil: a SECOND normalizer is a second answer to one question, and
    the two would agree right up until the day someone taught one of them a
    new token type. This executor and the attempt it dispatches must never
    disagree about whether a stop was requested.

    Inherits that function's fail-OPEN posture (a token that raises reads as
    "not cancelled"). With a ``KillSwitch`` that branch is unreachable by
    construction -- ``should_stop`` latches STOP on any internal failure and
    is documented never to raise -- so the posture only applies to a caller
    that supplied some other, less careful token.
    """
    from .spine.attempt import _as_predicate

    return bool(_as_predicate(cancel)())


def _accepts_kwarg(fn: Any, name: str) -> bool:
    """Does ``fn`` take a keyword called ``name``? Asked of the callable, never
    assumed, so a seam starts working the instant the parameter lands
    downstream and needs no flag day to coordinate."""
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins, C callables, odd wrappers
        return False


def _accepts_cancel(fn: Any) -> bool:
    """Does ``fn`` take a ``cancel`` keyword? See :func:`_accepts_kwarg`."""
    return _accepts_kwarg(fn, "cancel")


@dataclass(frozen=True)
class EffectBounds:
    """What a wave's Effect Lease is bounded BY, supplied by whoever owns the run.

    Passed to :class:`WaveExecutor` at construction rather than to
    :meth:`WaveExecutor.run_wave`, deliberately: ``run_wave``'s signature is a
    protocol that injected executor adapters implement (see ``LoopDriver``'s
    ``executor=`` seam), and adding a mandatory-looking keyword to it would
    break every adapter that already implements the old one. A constructor
    keyword is invisible to an adapter that was handed in ready-made.

    ``source_revision`` is the revision the RUN started at, captured once by the
    driver -- not re-read per wave, because a lease's provenance must name the
    tree the run was reasoning about even if another lane commits mid-run.
    """

    mission_id: str
    source_revision: str
    max_spend_usd: float | None = None
    timeout_s: float | None = None
    trace_id: str | None = None
    #: The run's own KillSwitch. Shared so the lease's generation and the
    #: loop's cancel token read ONE permit; two switches could disagree.
    switch: Any = None


def _leaseable_paths(paths: Any, repo_root: str) -> tuple[list[str], list[str]]:
    """``(repository-relative paths, rejected)`` for an effect scope.

    The canonical contracts refuse absolute or drive-qualified paths outright
    (``schemas._repo_path``), so an absolute declaration is rewritten relative
    to the checkout when it is inside it and REPORTED when it is not, rather
    than crashing a wave over a declaration that was only ever a hint.
    """
    keep: list[str] = []
    rejected: list[str] = []
    root = Path(repo_root).resolve()
    for raw in (paths or []):
        text = str(raw).strip().replace("\\", "/")
        if not text:
            continue
        candidate = Path(text)
        if candidate.is_absolute() or (len(text) > 1 and text[1] == ":"):
            try:
                text = candidate.resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                rejected.append(str(raw))
                continue
        if not text or text.startswith("../") or text == "..":
            rejected.append(str(raw))
            continue
        if text not in keep:
            keep.append(text)
    return keep, rejected


def _task_status(dispatch_status: str) -> str:
    if dispatch_status in _LANDED_STATUSES:
        return "landed"
    if dispatch_status in _PLANNED_STATUSES:
        return "planned"
    # NOTE for the spend-refusal statuses: both fall through to "bounced", and
    # that is the right coarse lifecycle -- nothing landed and nothing is still
    # planned. The specific fact ("the leased ceiling refused this draw", with
    # the lease id and the realized spend) survives in full on the result dict
    # itself, which BuildTask.mark() keeps as `last_result`.
    return "bounced"


def _spend_refusal_rows(results: Any) -> list[dict[str, Any]]:
    """Every result in ``results`` that a leased spend ceiling refused."""
    return [r for r in (results or [])
            if isinstance(r, Mapping)
            and str(r.get("status") or "") in (SPEND_REFUSED_STATUS,
                                               SPEND_REFUSED_SKIPPED_STATUS)]


@dataclass
class WaveResult:
    """What happened when one :class:`~daedalus.build.Wave` was dispatched."""
    index: int
    mode: str                              # "parallel" | "sequential" | "gated"
    dry_run: bool
    write_tasks: int
    advisory_tasks: int
    landed_tasks: int
    bounced_tasks: int
    forced_sequential_reason: str | None
    path_conflicts: list[dict[str, Any]]
    results: list[dict[str, Any]]          # dispatch()'s raw per-task dicts (or, for
                                            # mode=="gated", gated_writes.run_write_wave's --
                                            # same position-matched contract either way
    #: WHAT THE LEASED CEILING COST. ``{"cap_usd": ..., "spent_usd": ...}`` from
    #: the wave's budget envelope (see WaveExecutor._open_spend_envelope), so a
    #: report carries the money actually spent NEXT TO the money that was
    #: authorised, instead of only the declaration.
    spend_envelope: dict[str, Any] | None = None
    #: THE MISSION THIS WAVE SERVES (plan §7). Read off the session, which
    #: binds it at construction, so a receipt and its rows cannot name two.
    mission_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "mode": self.mode, "dry_run": self.dry_run,
            "write_tasks": self.write_tasks, "advisory_tasks": self.advisory_tasks,
            "landed_tasks": self.landed_tasks, "bounced_tasks": self.bounced_tasks,
            "forced_sequential_reason": self.forced_sequential_reason,
            "path_conflicts": self.path_conflicts, "results": self.results,
            "spend_envelope": self.spend_envelope, "mission_id": self.mission_id,
        }


@dataclass
class BuildRunReport:
    """What happened when a whole :class:`~daedalus.build.BuildSession` was run."""
    feature: str
    slug: str
    repo_root: str
    dry_run: bool
    waves: list[WaveResult] = field(default_factory=list)
    skipped_waves: list[int] = field(default_factory=list)   # already-terminal, skipped by resume
    snapshot_path: str | None = None
    mission_id: str = ""

    def summary(self) -> dict[str, int]:
        return {
            "waves_run": len(self.waves),
            "waves_skipped": len(self.skipped_waves),
            "landed": sum(w.landed_tasks for w in self.waves),
            "bounced": sum(w.bounced_tasks for w in self.waves),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature, "slug": self.slug, "repo_root": self.repo_root,
            "dry_run": self.dry_run, "summary": self.summary(),
            "skipped_waves": self.skipped_waves, "snapshot_path": self.snapshot_path,
            "waves": [w.to_dict() for w in self.waves], "mission_id": self.mission_id,
        }


class WaveExecutor:
    """Runs a :class:`~daedalus.build.BuildSession`'s waves, in order, through
    :class:`daedalus.kairos.scheduler.KairosScheduler`.

    Stateless apart from ``availability`` (an environment fact, not a session
    fact): a fresh ``KairosScheduler`` is built per :meth:`run` call from the
    session's own ``project``, mirroring exactly how ``daedalus.build.plan_build``
    derived its scheduler -- so ``max_workers``/``active_agents``/``policy``
    come from the same place planning used them. ``max_workers`` is then
    pinned to ``session.max_workers`` explicitly (see :meth:`_scheduler_for`)
    so the executor's concurrency bound can never drift from the bound the
    plan's waves were actually sized against, even if the project's team
    config changed between planning and running.

    Known, accepted limitation: routing itself (which agent/lane/mode a task
    gets) is re-derived live at dispatch time, not replayed from the plan. If
    the project's roster or policy changed since planning, a task's real
    dispatch-time routing can differ from what ``plan_build`` recorded. This
    executor does not attempt to pin or detect that drift; it dispatches
    whatever the task's ``objective``/``paths`` route to right now.
    """

    def __init__(self, availability: dict | None = None,
                 progress_log: Any = None,
                 effect_bounds: "EffectBounds | None" = None) -> None:
        self.availability = availability
        # WHAT THIS WAVE'S CAPABILITY IS BOUNDED BY. None means "not supplied",
        # and that is not the same as "unbounded": _acquire_wave_lease then
        # leases ZERO spend and reads the run's revision from the checkout, so
        # the missing declaration narrows the grant instead of widening it.
        self.effect_bounds = effect_bounds
        # WHERE THE ATTEMPT-LIFECYCLE EVENTS GO. Defaulted to None (=
        # daedalus.progress.default_log()) so every existing construction is
        # unchanged. A driver that already owns a log -- LoopDriver does --
        # passes its own, so one run's iteration events and its attempt events
        # land in ONE file. Splitting them across two logs would reintroduce
        # exactly the join-by-hand this whole change exists to remove.
        self._progress_log = progress_log

    def _scheduler_for(self, session: BuildSession) -> KairosScheduler:
        scheduler = KairosScheduler(availability=self.availability, project=session.project)
        scheduler.max_workers = max(1, int(session.max_workers))
        return scheduler

    @staticmethod
    def _task_dicts(wave: Wave,
                    curated_gates: Mapping[int, Mapping[str, Any]] | None = None
                    ) -> list[dict[str, Any]]:
        """The task dicts ``KairosScheduler.accept``/``dispatch`` consume.

        ``curated_gates`` maps a position in ``wave.tasks`` to that task's OWN
        execution hints (the curated command gate and, when measured,
        ``rewrite_windows``). It rides on the task dict under "gate" because
        that dict is what
        ``run_write_wave`` receives position-matched to its assignments, and
        because ``accept()`` reads only "objective"/"paths" -- an extra key is
        inert on every path that does not look for it.

        Keyed by POSITION rather than carried on BuildTask because BuildTask
        lives in daedalus/build.py, which this change does not own. The
        position key is the same 1:1 correspondence tasks/assignments/results
        already rely on throughout this file (and which run_wave length-checks
        after dispatch), so it introduces no new alignment assumption.
        """
        out = [{"objective": t.objective, "paths": list(t.paths),
                "work_item_id": t.work_item_id} for t in wave.tasks]
        for pos, gate in (curated_gates or {}).items():
            if gate and 0 <= int(pos) < len(out):
                out[int(pos)]["gate"] = dict(gate)
        return out

    def _source_revision(self, repo_root: str) -> str | None:
        """The run's revision, declared if the driver declared one, else read.

        Read-only and best effort: a checkout whose HEAD cannot be resolved
        gets no lease at all (a provenance-bearing contract may not carry a
        made-up revision), which is why the failure returns None instead of a
        placeholder.
        """
        bounds = self.effect_bounds
        if bounds is not None and bounds.source_revision:
            return bounds.source_revision
        import subprocess

        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        head = (proc.stdout or "").strip().lower()
        return head if len(head) == 40 and all(
            c in "0123456789abcdef" for c in head) else None

    @staticmethod
    def _wave_concurrency(scheduler: KairosScheduler, wave: Wave, *,
                          gated: bool, parallel: bool) -> int:
        """How many attempts of this wave can be IN FLIGHT AT ONCE.

        The lease's ``max_concurrency`` is the ceiling the effect ledger
        enforces (``daedalus/kernel/effects.py``: a start past it raises
        ``EffectLeaseConcurrencyError``). Handing it ``len(wave.tasks)`` made
        that ceiling equal to the number of executions the wave derives, so it
        could never bind -- a bound that is always slack is not a bound.

        These are the REAL numbers, read from the same scheduler that will run
        the wave: ``ThreadPoolExecutor(max_workers=self.max_workers)`` for an
        advisory parallel dispatch, ``min(max_parallel_writes, max_workers)``
        for the gated write path (``KairosScheduler.gate_concurrent_writes``),
        and exactly one for a sequential dispatch. Capped by the wave size,
        because a lease may not authorise more concurrency than the wave can
        possibly use.
        """
        workers = max(1, int(getattr(scheduler, "max_workers", 1) or 1))
        if gated:
            writes = max(1, int(getattr(scheduler, "max_parallel_writes", 1) or 1))
            bound = min(writes, workers)
        elif parallel:
            bound = workers
        else:
            bound = 1
        return max(1, min(len(wave.tasks) or 1, bound))

    def _acquire_wave_lease(self, scheduler: KairosScheduler, wave: Wave,
                            assignments: list[Assignment], repo_root: str, *,
                            session: Any = None,
                            task_dicts: list[dict[str, Any]],
                            attempt_id: str, gated: bool, has_writes: bool,
                            parallel: bool = False) -> Any:
        """Acquire the ONE ``python.offload`` Effect Lease this wave runs under.

        Once per wave, here, because this is the last scope that knows the whole
        wave: which lanes it routes to, which paths it declared, and whether the
        attempts below it are contained. ``_run_one`` cannot know any of that,
        and an entrypoint that mints its own authorization is not authorised by
        anything -- see ``daedalus.offload.offload``'s docstring, which forbids
        exactly that, and ``daedalus.kernel.offload_lease`` for the issuer.

        Returns a ``WaveOffloadLease``, a ``WaveLeaseDenied``, or None when
        the wave has no live work to lease. Raises
        ``WaveLeaseKillSwitchEngaged`` (a ``LoopHalted``) when the permit is
        not armed -- a revoked permit is an instruction to stop the run, not a
        verdict about this wave.
        """
        from .kernel.offload_lease import acquire_wave_offload_lease

        live = [a for a in assignments if a.accepted]
        if not live:
            return None
        revision = self._source_revision(repo_root)
        bounds = self.effect_bounds

        declared: list[str] = []
        rejected: list[str] = []
        for task in wave.tasks:
            keep, drop = _leaseable_paths(getattr(task, "paths", ()), repo_root)
            declared.extend(p for p in keep if p not in declared)
            rejected.extend(drop)

        # The write-policy contract, run rather than asserted. `path_write_blocked`
        # is this repository's ONE implementation of "may this path be written",
        # so calling it is the difference between a receipt that names a guard
        # and a receipt whose guard actually ran.
        from .sensitivity import path_write_blocked

        blocked = [p for p in declared
                   if path_write_blocked(p, scheduler.policy)]
        blocked.extend(f"{p} (outside the checkout)" for p in rejected)

        # The curated gate's own program is a tool this wave may spawn, and a
        # process-effect lease has to name its exact tools. argv[0] only: the
        # arguments are not tools.
        tools: list[str] = []
        for row in task_dicts:
            for word in ((row.get("gate") or {}).get("argv") or ())[:1]:
                name = Path(str(word)).name
                if name and name not in tools:
                    tools.append(name)

        if revision is None:
            from .kernel.offload_lease import WaveLeaseDenied
            from .schemas import ContractProvenance, EffectScope, PolicyDecision
            import hashlib as _hashlib

            reason = (f"the revision of {repo_root} could not be read, so no "
                      "provenance-bearing capability can be issued for it")
            # A denial still has to be a canonical record; with no revision to
            # bind, it is the one case this module builds by hand.
            zero = "0" * 40
            subject = _hashlib.sha256(reason.encode("utf-8")).hexdigest()
            return WaveLeaseDenied(
                policy_decision=PolicyDecision(
                    decision_id=f"{attempt_id}-deny",
                    subject_id=attempt_id,
                    subject_sha256=subject,
                    policy_version="daedalus.wave-offload-lease/1",
                    policy_sha256=subject,
                    verdict="deny",
                    reasons=(reason,),
                    effect_scope=EffectScope(),
                    provenance=ContractProvenance(
                        origin="build_exec.wave-lease",
                        source_revision=zero,
                        created_at=progress.now_iso(),
                        input_digests=(subject,),
                    ),
                ),
                reasons=(reason,),
            )

        return acquire_wave_offload_lease(
            repo_root,
            source_revision=revision,
            mission_id=(getattr(session, "mission_id", "")
                        or (bounds.mission_id if bounds else "")
                        or f"build-wave-{wave.index}"),
            attempt_id=attempt_id,
            # THE WAVE'S REAL CONCURRENCY, not its size. See
            # _wave_concurrency: `positions` is the issuer's name for the
            # lease's `max_concurrency`, and passing the task count made the
            # effect ledger's concurrency ceiling unfireable by construction.
            positions=self._wave_concurrency(scheduler, wave, gated=gated,
                                             parallel=parallel),
            writable_paths=declared,
            lanes=sorted({a.lane for a in live}),
            tools=tools,
            max_spend_usd=(bounds.max_spend_usd if bounds else None),
            timeout_s=(bounds.timeout_s if bounds else None),
            contained=(gated or not has_writes),
            containment_evidence=(
                f"{len(live)} write task(s) run through gated_writes.run_write_wave, "
                "each in its own TaskAttempt worktree; the primary checkout is "
                "never written by this path"
                if gated else
                f"wave {wave.index} routes {len(live)} advisory attempt(s) through "
                "KairosScheduler.dispatch; no write-mode assignment is present, so "
                "no attempt can mutate the primary checkout"
                if not has_writes else
                "a write-mode assignment would reach the unisolated dispatch path"
            ),
            write_policy_blocked=blocked,
            switch=(bounds.switch if bounds else None),
            trace_id=(bounds.trace_id if bounds else None),
        )

    @staticmethod
    def _open_spend_envelope(lease: Any, wave: Wave) -> tuple[Any, dict[str, Any] | None]:
        """Turn the lease's ``max_cost_microusd`` into money that actually stops.

        THE GAP THIS CLOSES. ``EffectScope.max_cost_microusd`` was, until this
        call, compared only against another declaration
        (``daedalus/kernel/effects.py::_validate_narrowed_scope`` checks the
        execution's claim against the lease's claim). No code subtracted a
        dollar from it. The only ceiling a live wave ever ran under was
        ``daedalus.budget``'s PERIOD ceiling -- ``DAEDALUS_BUDGET_USD``,
        default $5.00/day -- which has nothing to do with the
        ``--max-spend-usd`` the operator typed and the lease then published.

        So the wave places a budget RESERVATION for exactly its leased ceiling
        before it dispatches anything. From here until the envelope closes,
        ``daedalus.budget``'s process guard refuses at the LEASE's number
        (naming the lease in the refusal), not at the day's; the unused hold is
        released at wave end and the realized spend is reported back for the
        receipt.

        Returns ``(envelope, refusal)``. A refusal is a wave that must not run:
        the money it was authorised for cannot be pre-authorised, or the ledger
        cannot be read at all -- and an unreadable budget is a refusal
        everywhere else in this repository too.
        """
        if lease is None or not getattr(lease, "granted", False):
            return None, None
        from . import budget

        scope = lease.lease.effect_scope
        micro = scope.max_cost_microusd
        cap_usd = 0.0 if not micro else float(micro) / 1_000_000.0
        # The envelope outlives the lease by nothing: a hold whose wave is over
        # must stop holding the day's money. `timeout_s` is the wave's own
        # bound, doubled so a wave that ends exactly at its timeout still
        # closes its envelope itself rather than being closed by expiry.
        ttl = None
        if scope.timeout_s:
            ttl = max(60.0, float(scope.timeout_s) * 2.0)
        try:
            envelope = budget.ledger().open_envelope(
                cap_usd,
                label=(f"wave {wave.index} "
                       f"({getattr(lease.request, 'mission_id', '') or '?'})"),
                lease_id=lease.lease.lease_id,
                ttl_s=ttl)
        except budget.BudgetRefused as exc:
            return None, {"reason": exc.message(), "detail": exc.as_dict(),
                          "cap_usd": cap_usd}
        except budget.BudgetUnavailable as exc:
            return None, {"reason": (
                f"the budget ledger could not be established ({exc}), so the "
                "leased spend ceiling cannot be enforced; a wave that cannot "
                "measure its own spend does not dispatch"),
                "detail": None, "cap_usd": cap_usd}
        return envelope, None

    def classify_wave(self, scheduler: KairosScheduler, wave: Wave, repo_root: str) -> list[Assignment]:
        """Read-only: route every task in ``wave`` without executing anything.
        ``KairosScheduler.accept`` never touches a provider or writes a file
        -- it is the same call ``.plan()`` uses for its own dry-run verdict
        -- so this is always safe to call, live or dry-run, before deciding
        whether a wave may run concurrently."""
        return scheduler.accept(self._task_dicts(wave), repo_root=repo_root)

    def _emit(self, fn: Any, unit_id: str, **kw: Any) -> None:
        """Record one progress observation. Best-effort BY DESIGN: losing an
        observation must never take down the wave being observed. Mirrors
        ``LoopDriver._emit`` deliberately -- two different swallow-policies for
        the same log would make a missing event ambiguous between "it did not
        happen" and "it happened and this one crashed"."""
        try:
            fn(unit_id, source=PROGRESS_SOURCE, log=self._progress_log, **kw)
        except Exception:  # noqa: BLE001
            pass

    def _emit_attempt_finished(self, unit_id: str, *, wave: Wave, position: int,
                               result: Mapping[str, Any], duration_s: float,
                               dry_run: bool, gated: bool, curated: bool) -> None:
        """The terminal events for one task: its gate verdict (when it actually
        reached a gate) and its DONE.

        Every value here is READ from the result, never re-derived from a
        status string that happens to look encouraging -- the same discipline
        ``LoopDriver._outcome_of`` applies one level up.
        """
        status = str(result.get("status") or "")
        state = str(result.get("attempt_state") or "")
        reason = str(result.get("reason") or "")
        # changed_paths (gated path) and wrote (dispatch path) are both the
        # MEASURED before/after diff. `paths` is the task's declared hint and
        # is deliberately NOT used as a fallback: counting a declaration as a
        # change is how a self-report gets laundered into evidence.
        changed = result.get("changed_paths")
        if changed is None:
            changed = result.get("wrote")
        files_changed = len(changed or [])

        # A gate verdict is emitted ONLY when an attempt really ran one. A
        # bounce ("belongs to the senior crew") and a dry-run preview never
        # reached a gate, and inventing a passed=False verdict for them would
        # be indistinguishable from a real gate failure -- the same
        # fail-closed-but-wrong confusion picker.py documents for docref.
        if state:
            self._emit(progress.record_gate_verdict, unit_id,
                       # Named from what actually wired the gate, which this
                       # method knows for certain: a curated argv becomes
                       # attempt.command_gate(name="queue-command"); otherwise
                       # gated_writes._relay_gate names itself "offload-verify".
                       name=("queue-command" if curated else "offload-verify"),
                       passed=(state == "clean"),
                       detail={"wave": wave.index, "position": position,
                               "attempt_state": state, "status": status,
                               "reason": reason,
                               "attempt_task_id": result.get("task_id"),
                               "integration_branch": result.get("integration_branch")})

        if dry_run or status == "planned":
            succeeded: bool | None = None      # nothing ran; there is no verdict
        elif state:
            succeeded = (state == "clean")
        else:
            succeeded = (_task_status(status) == "landed")

        # "applied" means THE PRIMARY CHECKOUT CHANGED. The gated path never
        # changes it: current production writes persist a held artifact and do
        # not invoke promotion. Historical/injected promoted results are also
        # integration-only, never primary-checkout writes.
        applied: bool | None
        if dry_run:
            applied = None
        elif gated:
            applied = False
        else:
            applied = bool(result.get("wrote"))

        self._emit(progress.record_done, unit_id, succeeded=succeeded,
                   applied=applied, reason=reason or status or state,
                   detail={"wave": wave.index, "position": position,
                           "status": status, "attempt_state": state,
                           "lane": result.get("lane"), "worker": result.get("worker"),
                           "files_changed": files_changed,
                           "duration_s": round(float(duration_s), 3),
                           "attempt_task_id": result.get("task_id"),
                           "integration_branch": result.get("integration_branch"),
                           "dry_run": dry_run})

    def run_wave(self, scheduler: KairosScheduler, wave: Wave, repo_root: str, *,
                 session: Any = None, dry_run: bool = True, parallel: bool = True,
                 cancel: Any = None,
                 curated_gates: Mapping[int, Mapping[str, Any]] | None = None
                 ) -> WaveResult:
        """Dispatch one wave. ``parallel=True`` is a promise, not a hint: if
        classification finds a write-mode task in this wave, that promise is
        refused (:class:`UnsafeParallelWriteError`), never silently honored
        as sequential. Callers that don't already know a wave is write-free
        should classify first (see :meth:`run`, which does exactly that).

        ``cancel`` is a cancel token (anything
        :func:`daedalus.spine.attempt._as_predicate` accepts -- a callable, a
        ``threading.Event``, or a :class:`daedalus.spine.killswitch.KillSwitch`)
        and exists for a LOOP DRIVER, which is the only caller that dispatches
        wave after wave unattended and therefore the only one that needs a
        human to be able to interrupt it mid-flight. It is checked once here,
        at the last instant before anything is dispatched, and then handed
        down -- see ``_accepts_cancel`` for why the hand-down is conditional.
        """
        tasks = self._task_dicts(wave, curated_gates)
        assignments = scheduler.accept(tasks, repo_root=repo_root)
        write_n = sum(1 for a in assignments if a.accepted and a.mode == "write")
        advisory_n = sum(1 for a in assignments if a.accepted and a.mode != "write")
        has_writes = write_n > 0
        conflicts = wave_path_conflicts(wave)

        if parallel and has_writes:
            raise UnsafeParallelWriteError(
                f"wave {wave.index}: {write_n} write-mode task(s) present; refusing "
                "parallel=True rather than silently downgrading to sequential. "
                "This flag means 'dispatch every task through KairosScheduler.dispatch "
                "with no per-task isolation' (shared files, per-call rollback snapshots "
                "-- see that method's `can_parallel` comment), which stays unsafe for "
                "writes regardless of write_wave_policy. Re-call with parallel=False: a "
                "LIVE write-containing wave is then routed through "
                "daedalus.kairos.gated_writes.run_write_wave, which already isolates "
                "and concurrently gates every write task in its own worktree -- "
                "`parallel=False` here does not mean sequential for writes, it means "
                "'let this method choose the safe path'."
            )

        # _WRITE_WAVE_POLICY: the one and only place a write-containing wave's
        # dispatch mode is decided. A DRY RUN (or a write-free wave) still goes
        # through KairosScheduler.dispatch() unchanged below -- gate_candidates
        # always runs a real offload() attempt (see gated_writes.gate_candidates),
        # so it has no dry-run mode to preview through and must never be reached
        # while dry_run is True. A LIVE write-containing wave is routed through
        # daedalus.kairos.gated_writes.run_write_wave: every write-mode task
        # gets its own isolated worktree (concurrent, not forced-sequential --
        # see gate_candidates), and every resulting candidate is held for an
        # explicit owner-controlled promotion call. `write_wave_policy`
        # remains a compatibility field but resolves only to `never`.
        # This path never writes repo_root's primary checkout, so
        # BuildTask.status below correctly coarsens the result to "bounced".
        wave_parallel = bool(parallel and not has_writes)
        forced_reason = None
        gated_write_wave = has_writes and not dry_run
        write_wave_policy = None
        if has_writes:
            if gated_write_wave:
                from .config import resolve_project, resolve_write_wave_policy

                pdata = resolve_project(repo_root, scheduler.project)
                write_wave_policy = resolve_write_wave_policy(pdata)
                forced_reason = (
                    f"{write_n} write-mode task(s) in this wave; routed through "
                    "the gated, isolated-worktree write path (concurrent per-task "
                    f"worktrees, write_wave_policy={write_wave_policy!r}) -- see "
                    "daedalus.kairos.gated_writes.run_write_wave")
            else:
                forced_reason = (
                    f"{write_n} write-mode task(s) in this wave; dry-run preview "
                    "stays on KairosScheduler.dispatch() (gate_candidates has no "
                    "dry-run mode -- it always runs a real attempt)")

        # THE LAST INSTANT BEFORE ANYTHING IS DISPATCHED. Everything above this
        # line is classification -- pure reads, no spend. Everything below it
        # costs money. A loop driver's own between-iteration checkpoint cannot
        # cover the inside of a wave, so the check is repeated here rather than
        # trusted to the caller.
        if cancel is not None and _cancel_requested(cancel):
            from .spine.killswitch import LoopHalted

            raise LoopHalted(
                f"wave {wave.index}: cancelled before dispatch; no task in this "
                f"wave was started, so nothing here was spent and no task was "
                f"marked 'dispatched'")

        # ---- THE CAPABILITY, ACQUIRED ONCE, BEFORE ANY TASK IS DISPATCHED - #
        # A live wave that cannot obtain its lease is refused HERE, above the
        # "dispatched" marks and above the lifecycle events, so a refused wave
        # leaves no half-open attempt behind and nothing downstream has to
        # distinguish "was never authorised" from "was attempted and failed".
        # This is also the reason the refusal is not left to offload(): by the
        # time offload refuses, the wave has already paid for routing, marked
        # its tasks dispatched, and gated an empty patch as a candidate --
        # which is precisely what runs/loop/blocker_9887a98e.json measured.
        nonce = uuid.uuid4().hex[:8]
        lease = None
        envelope = None
        if not dry_run:
            lease = self._acquire_wave_lease(
                scheduler, wave, assignments, repo_root, session=session, task_dicts=tasks,
                attempt_id=f"w{wave.index}-{nonce}",
                gated=gated_write_wave, has_writes=has_writes,
                parallel=wave_parallel)
            if lease is not None and not getattr(lease, "granted", False):
                receipt = lease.receipt()
                refused = [
                    {"worker": a.worker, "lane": a.lane, "mode": a.mode,
                     "owner": a.owner, "objective": a.objective,
                     "paths": list(a.paths),
                     "status": "effect_lease_denied",
                     "reason": "; ".join(lease.reasons),
                     "wrote": [], "changed_paths": [],
                     "provider_receipt": receipt,
                     "effect_lease": receipt}
                    for a in assignments
                ]
                for pos, t in enumerate(wave.tasks):
                    t.mark("bounced")
                    if pos < len(refused):
                        refused[pos]["work_item"] = t.work_item_stamp()
                return WaveResult(
                    index=wave.index, mode="lease_denied", dry_run=dry_run,
                    write_tasks=write_n, advisory_tasks=advisory_n,
                    landed_tasks=0, bounced_tasks=len(refused),
                    forced_sequential_reason=(
                        "no python.offload Effect Lease was issued for this wave: "
                        + "; ".join(lease.reasons)),
                    path_conflicts=conflicts, results=refused,
                    mission_id=getattr(session, "mission_id", ""))

            # ---- THE MONEY, RESERVED AT THE LEASE'S CEILING --------------- #
            # Immediately after the grant and before anything is dispatched,
            # for the same reason the lease itself is acquired here: a wave
            # that cannot hold its own budget must leave no half-open attempt
            # behind. Without this the lease's max_cost_microusd was a number
            # in a receipt and the only real cap was the day's.
            envelope, spend_refusal = self._open_spend_envelope(lease, wave)
            if spend_refusal is not None:
                receipt = lease.receipt() if lease is not None else None
                refused = [
                    {"worker": a.worker, "lane": a.lane, "mode": a.mode,
                     "owner": a.owner, "objective": a.objective,
                     "paths": list(a.paths),
                     "status": "spend_envelope_denied",
                     "reason": spend_refusal["reason"],
                     "wrote": [], "changed_paths": [],
                     "provider_receipt": receipt,
                     "effect_lease": receipt,
                     "budget_refusal": spend_refusal["detail"]}
                    for a in assignments
                ]
                for pos, t in enumerate(wave.tasks):
                    t.mark("bounced")
                    if pos < len(refused):
                        refused[pos]["work_item"] = t.work_item_stamp()
                return WaveResult(
                    index=wave.index, mode="spend_denied", dry_run=dry_run,
                    write_tasks=write_n, advisory_tasks=advisory_n,
                    landed_tasks=0, bounced_tasks=len(refused),
                    forced_sequential_reason=(
                        "the leased spend ceiling could not be reserved on the "
                        "budget ledger: " + spend_refusal["reason"]),
                    path_conflicts=conflicts, results=refused,
                    spend_envelope={"cap_usd": spend_refusal["cap_usd"],
                                    "spent_usd": 0.0, "opened": False},
                    mission_id=getattr(session, "mission_id", ""))

        if not dry_run:
            for t in wave.tasks:
                t.mark("dispatched")

        # ---- ATTEMPT LIFECYCLE: OPEN ------------------------------------- #
        # Emitted HERE, at the wave/attempt seam, because this is the last
        # place that still knows a task's WAVE POSITION and its ASSIGNMENT
        # (lane/worker/mode/accepted) in the same scope. Below this line the
        # tasks scatter: write-mode ones go through run_write_wave into
        # per-task worktrees, the rest through dispatch, and neither hands
        # back a "started" signal -- both are blocking calls that report only
        # at the end. That silence is precisely what makes a running wave
        # unobservable today.
        #
        # Dry runs emit too. A dry run is a real lifecycle (it routes, it
        # decides, it reports a status) and it is the ONLY way to watch this
        # machinery without spending money -- muting it would make the cheap
        # path the unobservable one, which is backwards.
        batch_id = f"wave-{wave.index}-{nonce}"
        units = [_attempt_unit_id(wave.index, i, nonce)
                 for i in range(len(wave.tasks))]
        for i, (task, a) in enumerate(zip(wave.tasks, assignments)):
            self._emit(progress.open_unit, units[i], batch_id=batch_id,
                       detail={"wave": wave.index, "position": i,
                               "objective": task.objective[:200],
                               "paths": list(task.paths),
                               "lane": a.lane, "worker": a.worker,
                               "owner": a.owner, "mode": a.mode,
                               "accepted": a.accepted,
                               # The routing REASON at open time. For a bounce
                               # this is already the whole answer ("belongs to
                               # the senior crew -> return to Adam") and it is
                               # now visible the instant it is decided, not
                               # only in a post-mortem of the result dict.
                               "routing_reason": a.reason,
                               # Declared, not measured: BuildTask.builder is
                               # this repo's routing label (claude|ollama), not
                               # an observation of which model answered.
                               "builder": getattr(task, "builder", ""),
                               "tier": getattr(task, "tier", ""),
                               "curated_gate": list(
                                   (tasks[i].get("gate") or {}).get("argv") or ()),
                               "rewrite_windows": dict(
                                   (tasks[i].get("gate") or {}).get(
                                       "rewrite_windows") or {}),
                               "dry_run": dry_run})
            self._emit(progress.claim_unit, units[i],
                       detail={"wave": wave.index, "position": i,
                               "dispatch": "gated_writes" if gated_write_wave
                                           else "scheduler.dispatch"})

        # LIVENESS WHILE THE WAVE BLOCKS. A gated write wave can run for many
        # minutes inside one call; with no signal in between, a working wave
        # and a wedged one are indistinguishable from outside. HEARTBEAT is
        # deliberately the weakest kind in this vocabulary -- proof the
        # dispatching thread is alive, never proof of forward progress (see
        # progress.heartbeat, and UnitProgress.stalled, which refuses to let a
        # heartbeat clear a stall). Anything stronger would need a per-round
        # hook that neither offload() nor dispatch() exposes; this does not
        # invent one. progress.heartbeat is reused rather than
        # progress_sources.track_call because track_call wraps ONE call into
        # ONE unit's terminal event, and this is one call behind N units.
        beat_stop = threading.Event()

        def _beat() -> None:
            n = 0
            while not beat_stop.wait(_HEARTBEAT_INTERVAL_S):
                n += 1
                for u in units:
                    self._emit(progress.heartbeat, u,
                               detail={"beat": n, "wave": wave.index,
                                       "waiting_on": "gated_writes"
                                                     if gated_write_wave
                                                     else "scheduler.dispatch"})

        beat_thread = threading.Thread(
            target=_beat, daemon=True, name=f"build-exec-heartbeat-w{wave.index}")
        beat_thread.start()
        dispatch_started = time.monotonic()

        if gated_write_wave:
            from .kairos.gated_writes import run_write_wave

            # CONDITIONAL HAND-DOWN, and this is a coordination seam, not
            # cleverness: `run_write_wave` -> `gate_candidates` ->
            # `_attempt_assignment` -> `run_attempt(..., cancel=)` is the only
            # production path from here to a cancellable attempt, and it does
            # not thread `cancel` yet (gated_writes.py is owned elsewhere; the
            # request is filed). Passing an unsupported keyword would be a
            # TypeError, and hard-coding "it doesn't take one" would silently
            # keep the loop uncancellable for one wave AFTER the parameter
            # lands. Asking the callable itself is the only answer that cannot
            # go stale.
            #
            # Until it lands, a stop still kills the gate children -- KillSwitch's
            # watcher sweeps every live ManagedProcess process-wide -- but the
            # sweep races pytest_gate's own poll and the loser records
            # `gates_failed` for a candidate that was never judged (measured,
            # ~50/50; see killswitch.py's _watch_loop comment). That is why
            # LoopDriver discards an interrupted iteration's outcome instead of
            # believing it.
            extra = {"cancel": cancel} if (
                cancel is not None and _accepts_cancel(run_write_wave)) else {}
            # SAME CONDITIONAL HAND-DOWN, SAME REASON, for the lease. The gated
            # write path reaches offload() through TaskAttempt/run_attempt and
            # therefore needs the capability too, but gated_writes.py is owned
            # elsewhere and does not take one yet -- so this asks the callable
            # instead of assuming either answer. Until it lands, a live WRITE
            # wave still ends in offload's `effect_lease_required` refusal; the
            # advisory dispatch path below is what this change unblocks, and the
            # receipt says which of the two ran.
            if lease is not None and _accepts_kwarg(run_write_wave,
                                                    "effect_authorization"):
                extra["effect_authorization"] = lease.authorization
                extra["effect_executions"] = {
                    pos: lease.execution_for(
                        pos, _leaseable_paths(t.paths, repo_root)[0])
                    for pos, t in enumerate(wave.tasks)}

            def _dispatch() -> list[dict[str, Any]]:
                return run_write_wave(scheduler, repo_root, tasks, assignments,
                                      auto_promote=write_wave_policy, **extra)
        else:
            executions = {
                pos: lease.execution_for(
                    pos, _leaseable_paths(t.paths, repo_root)[0])
                for pos, t in enumerate(wave.tasks)} if lease is not None else None

            def _dispatch() -> list[dict[str, Any]]:
                return scheduler.dispatch(
                    repo_root, tasks, dry_run=dry_run, parallel=wave_parallel,
                    effect_authorization=(lease.authorization
                                          if lease is not None else None),
                    effect_executions=executions)

        # ONE stop point for the beat, on EVERY exit including a raise. The
        # thread is a daemon, so a leak would not hold the interpreter open --
        # but this executor also runs inside a long-lived process (the web API),
        # where a leaked beat would keep appending events for a wave that ended
        # long ago. A stale "still working" signal is worse than no signal: it
        # is the exact lie the stall detector exists to catch.
        from . import budget

        # THE WAVE-LEVEL NET FOR A REFUSED DRAW. `KairosScheduler.dispatch`
        # already translates a `BudgetRefused` per POSITION (so a wave keeps the
        # results of the positions that ran before the refusal), but that is one
        # of two dispatch paths: the gated write path goes through
        # `gated_writes.run_write_wave`, which is owned elsewhere and does not
        # translate. Without this, a refusal on THAT path still escaped run_wave
        # and destroyed the whole loop run. Caught here rather than swallowed:
        # the wave still ends, it just ends with a receipt instead of a
        # traceback, and nothing retries the refused call.
        wave_refusal: Any = None
        try:
            if envelope is not None:
                # INSIDE THE ENVELOPE. Entering it publishes the envelope id in
                # the environment, so a child process that installs
                # daedalus.budget's own process guard draws on the SAME leased
                # ceiling instead of only on the day's; leaving it releases the
                # unused hold on every exit, including a raise, so an
                # interrupted wave does not keep the day's money hostage.
                with envelope:
                    raw = _dispatch()
            else:
                raw = _dispatch()
        except budget.BudgetRefused as exc:
            # The position is UNKNOWN on this path -- run_write_wave reports
            # only at the end -- so every task in the wave is reported refused
            # rather than guessing which one asked for the money. Deliberately
            # not `attempted=False` for the rest: on this path nothing came
            # back at all, and claiming a specific one was "never attempted"
            # would be an invention.
            wave_refusal = exc
            raw = [spend_refused_result(a, exc, objective=t.objective,
                                        paths=list(t.paths))
                   for a, t in zip(assignments, wave.tasks)]
        finally:
            beat_stop.set()
            beat_thread.join(timeout=2.0)

        # THE ENVELOPE IS CLOSED BEFORE THE RECEIPT IS WRITTEN, always. The
        # `with envelope:` block above closes on every exit including a raise
        # (SpendEnvelope.__exit__), so this is normally a no-op that reads back
        # what was already reported -- but an envelope opened without ever
        # being entered (no dispatch path taken) would otherwise hold the day's
        # money against a wave that is over. `close()` is idempotent.
        if envelope is not None and envelope.result is None:
            try:
                envelope.close(reason=(
                    f"wave {wave.index} ended without entering its envelope"
                    if wave_refusal is None else
                    f"wave {wave.index} refused at its leased ceiling"))
            except Exception:  # noqa: BLE001 - a receipt must not die here
                pass
        # Guaranteed len(tasks) long, position-matched to `tasks`/`wave.tasks`:
        # dispatch() builds its return list 1:1 from accept()'s own 1:1 pass
        # over `tasks`, UNLESS its internal parallel-write downgrade path fires
        # (which prepends a {"status": "note"} entry) -- and the raise above
        # guarantees that path can never fire for a call this method makes.
        # Checked explicitly rather than trusted, because a silent length drift
        # here would misattribute one task's result onto a different task.
        if len(raw) != len(wave.tasks):
            raise RuntimeError(
                f"wave {wave.index}: dispatch() returned {len(raw)} result(s) for "
                f"{len(wave.tasks)} task(s) -- executor/dispatch contract drifted "
                "(see the note-prepend path in KairosScheduler.dispatch's parallel-"
                "write downgrade; this call should never be able to trigger it)")

        landed_n = bounced_n = 0
        elapsed = time.monotonic() - dispatch_started
        # THE LEASE RIDES ON EVERY RESULT. Stamped from the wave's own lease
        # object rather than read back out of a provider receipt, so a result
        # can never claim a capability that was not the one actually issued --
        # and so an operator reading runs/loop/loop-*.json can join a spend to
        # the exact lease id, effect set and execution that authorised it.
        # THE TERMINAL RECORDS, ONCE PER WAVE, and here because this is the
        # first moment every dispatched execution has reached a terminal state:
        # `offload` calls `finish_effect` on all three exits (completed,
        # failed, cancelled) inside `_dispatch()` above. Until this call the
        # write-evidence store held a lease subject and one execution identity
        # per position and nothing saying any of them ended -- the producer
        # half wired, the consumer half not.
        #
        # NOT ON A DRY RUN. A dry run derives every execution identity and
        # starts none, so a sweep there would append one "no durable start"
        # refusal per position on every planning pass and drown the refusals
        # that mean something -- a LIVE position that was issued and never ran.
        #
        # Retention cannot fail the wave: `retain_terminal_records` reports on
        # the lease and returns refusals, exactly as the issuer's own
        # `lease-subject` and `disjointness` retention does.
        terminal_refusals: tuple[str, ...] = ()
        if (not dry_run and lease is not None
                and getattr(lease, "granted", False)
                and hasattr(lease, "retain_terminal_records")):
            _terminal_records, terminal_refusals = lease.retain_terminal_records()
        lease_receipt = lease.receipt() if lease is not None else None
        if lease_receipt is not None and terminal_refusals:
            # Named on the receipt the operator already reads, not only inside
            # a lease object the loop drops at the end of the wave.
            lease_receipt["terminal_record_refusals"] = list(terminal_refusals)
        # WHAT THE CEILING ACTUALLY COST, closed and measured by the block
        # above. Carried beside `max_cost_microusd` (the declaration) so a
        # reader of runs/loop/*.json sees authorised and realized money in one
        # place instead of inferring the second from a ledger elsewhere.
        spend_envelope = (dict(envelope.result) if envelope is not None
                          and envelope.result else None)
        if lease_receipt is not None and spend_envelope is not None:
            lease_receipt["spend_envelope"] = spend_envelope
        for pos, (task, result) in enumerate(zip(wave.tasks, raw)):
            if lease_receipt is not None and isinstance(result, dict):
                stamped = dict(lease_receipt)
                execution = lease.issued_execution(pos)
                stamped["execution_id"] = (execution.execution_id
                                           if execution is not None else None)
                result["effect_lease"] = stamped
            task.last_result = result
            # ---- ATTEMPT LIFECYCLE: CLOSE -------------------------------- #
            # Before the `dry_run` short-circuit below, so a dry run closes
            # every unit it opened. A lifecycle that opens and never closes
            # renders as STALLED forever (progress.UnitProgress.stalled), which
            # would turn the cheapest, safest path into the one that looks
            # permanently broken.
            self._emit_attempt_finished(
                units[pos], wave=wave, position=pos, result=result,
                duration_s=elapsed, dry_run=dry_run,
                gated=gated_write_wave, curated=bool(tasks[pos].get("gate")))
            if dry_run:
                if isinstance(result, dict) and task.work_item_id:
                    result.setdefault("work_item", task.work_item_stamp())
                continue
            coarse = _task_status(str(result.get("status", "")))
            task.mark(coarse, result)
            if coarse == "landed":
                landed_n += 1
            elif coarse == "bounced":
                bounced_n += 1

        result_mode = "gated" if gated_write_wave else ("parallel" if wave_parallel else "sequential")
        # THE REFUSAL IS VISIBLE ON THE WAVE, not only buried in the per-task
        # results. `mode` is how "lease_denied"/"spend_denied" already report a
        # wave that money stopped BEFORE dispatch; "spend_refused" is the same
        # fact discovered DURING dispatch, and a caller that switches on mode
        # should not have to scan N result dicts to find it.
        refused_rows = _spend_refusal_rows(raw)
        if refused_rows:
            result_mode = "spend_refused"
            first = refused_rows[0]
            why = (f"the leased spend ceiling refused a draw mid-wave: "
                   f"{first.get('reason') or 'no reason reported'}")
            forced_reason = f"{forced_reason}; {why}" if forced_reason else why
        return WaveResult(
            index=wave.index, mode=result_mode,
            dry_run=dry_run, write_tasks=write_n, advisory_tasks=advisory_n,
            landed_tasks=landed_n, bounced_tasks=bounced_n,
            forced_sequential_reason=forced_reason, path_conflicts=conflicts, results=raw,
            spend_envelope=spend_envelope,
            mission_id=getattr(session, "mission_id", ""),
        )

    def run(self, session: BuildSession, *, repo_root: str | None = None,
            dry_run: bool = True, parallel_advisory: bool = True,
            resume: bool = True, stop_on_bounce: bool = False,
            checkpoint_every_wave: bool = False,
            runs_dir: str | Path | None = None,
            update_architecture: bool = True) -> BuildRunReport:
        """Execute every wave of ``session``, in order, collecting results back
        onto each task and (unless ``dry_run``) persisting the session.

        ``parallel_advisory`` controls only advisory-only waves -- a write-
        containing wave is ALWAYS sequential, decided per-wave from a real
        classification computed before dispatch, and recorded on that wave's
        :class:`WaveResult` (``forced_sequential_reason``), never silently.

        ``resume=True`` (default) skips any wave whose tasks are already all
        terminal (``landed``/``bounced``) -- safe to call repeatedly on the
        same session as it progresses, or after a crash.

        ``checkpoint_every_wave=False`` (default) saves the session once, at
        the end. ``BuildSession.save()`` mints a fresh second-resolution
        timestamped filename on every call (``daedalus/build.py``'s
        ``_stamp()``); saving after every wave in a fast (e.g. dry-run) loop
        can collide two waves into the same filename within one second,
        silently overwriting an earlier checkpoint. That's a real, pre-
        existing gap this executor is simply the first caller to exercise
        (nothing before this module ever called ``.save()`` more than once
        per session) -- the fix, if you want per-wave durability badly enough
        to accept it, is the same one ``daedalus/council/canary.py`` already
        uses for its own stamped filenames: append a short random suffix
        (``secrets.token_hex(3)``). Not applied here by default because it
        changes a shared helper (``_stamp()``) used by five other files for
        their own run-ledger filenames, and this executor only needs it when
        a caller opts in.
        """
        root = repo_root or session.repo_root
        scheduler = self._scheduler_for(session)
        wave_results: list[WaveResult] = []
        skipped: list[int] = []

        for wave in session.waves:
            if resume and wave.tasks and all(t.status in ("landed", "bounced") for t in wave.tasks):
                skipped.append(wave.index)
                continue

            # Decide concurrency BEFORE dispatch, from a real classification --
            # this is what lets run_wave()'s own parallel-write guard stay a
            # pure safety net instead of firing on every ordinary run.
            assignments = self.classify_wave(scheduler, wave, root)
            has_writes = any(a.accepted and a.mode == "write" for a in assignments)
            wave_parallel = bool(parallel_advisory and not has_writes)

            result = self.run_wave(scheduler, wave, root, session=session, dry_run=dry_run, parallel=wave_parallel)
            wave_results.append(result)

            if checkpoint_every_wave and not dry_run:
                session.save(runs_dir, update_architecture=update_architecture)

            if stop_on_bounce and result.bounced_tasks:
                break

            # A REFUSED CEILING STOPS THE SESSION, whatever stop_on_bounce
            # says. Every wave opens its OWN envelope for the full
            # `effect_bounds.max_spend_usd`, so continuing here would hand the
            # next wave a fresh, complete authorisation immediately after the
            # ledger refused the last one -- turning one operator gesture into
            # N caps. The refusal is already on this wave's result
            # (mode="spend_refused", with the lease and the reason), and the
            # waves that did not run are visible as the ones missing from the
            # report; nothing retries the refused call.
            if result.mode == "spend_refused":
                break

        snapshot_path = None
        if not dry_run:
            snapshot_path = str(session.save(runs_dir, update_architecture=update_architecture))

        return BuildRunReport(
            feature=session.feature, slug=session.slug, repo_root=root, dry_run=dry_run,
            waves=wave_results, skipped_waves=skipped, snapshot_path=snapshot_path,
            mission_id=getattr(session, "mission_id", ""),
        )


def main() -> None:
    import argparse

    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape. This
    # module has NO subcommand at all: `daedalus build` only plans, and the
    # tail is the only way to execute a plan. One invocation can start a whole
    # multi-wave run through KairosScheduler, which makes it the highest-fanout
    # console door in the tree -- and it was the least visible, because main()
    # holds no sink of its own and the scanner therefore never classified it.
    #
    # Above --live deliberately: the dry-run default is a property of the
    # current flag table, not of this function.
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.build_exec",
        REGISTRY_BY_ID["cli.build_exec"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(
        prog="python -m daedalus.build_exec",
        description=("Execute a saved build session's waves through KairosScheduler.dispatch. "
                     "Defaults to a side-effect-free dry-run preview; pass --live to actually "
                     "dispatch (which can invoke real providers, including the local Ollama "
                     "bench, for accepted tasks)."))
    parser.add_argument("session", help="path to a runs/build/*.json snapshot (see: daedalus build)")
    parser.add_argument("--live", action="store_true", help="actually dispatch (default: dry-run preview)")
    parser.add_argument("--no-parallel-advisory", action="store_true",
                        help="force every wave sequential, even pure-advisory ones")
    parser.add_argument("--stop-on-bounce", action="store_true",
                        help="stop after the first wave containing a bounced task")
    parser.add_argument("--no-resume", action="store_true",
                        help="re-run every wave, including already-terminal ones")
    parser.add_argument("--repo-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    session = load_session(args.session)
    executor = WaveExecutor()
    report = executor.run(
        session, repo_root=args.repo_root, dry_run=not args.live,
        parallel_advisory=not args.no_parallel_advisory, resume=not args.no_resume,
        stop_on_bounce=args.stop_on_bounce, checkpoint_every_wave=args.live,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return

    mode = "LIVE" if args.live else "dry-run preview"
    print(f"build run: {report.feature}  [{mode}]")
    if report.skipped_waves:
        print(f"  skipped (already terminal): {report.skipped_waves}")
    for wr in report.waves:
        line = (f"  wave {wr.index}: {wr.mode:<10} landed={wr.landed_tasks} "
                f"bounced={wr.bounced_tasks} write={wr.write_tasks} advisory={wr.advisory_tasks}")
        if wr.forced_sequential_reason:
            line += f"\n    -> {wr.forced_sequential_reason}"
        if wr.path_conflicts:
            line += f"\n    ! path conflicts: {wr.path_conflicts}"
        print(line)
    s = report.summary()
    print(f"\n{s['waves_run']} wave(s) run, {s['waves_skipped']} skipped -- "
          f"{s['landed']} landed, {s['bounced']} bounced.")
    if report.snapshot_path:
        print(f"snapshot: {report.snapshot_path}")


if __name__ == "__main__":
    main()
