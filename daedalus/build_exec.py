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

Whether a candidate then auto-advances into a disposable integration
worktree/branch (``daedalus.kairos.gated_writes.promote_candidates``) or waits
for a human is this project's ``write_wave_policy`` (``never`` / ``low_risk`` /
``always`` -- see ``daedalus.config.resolve_write_wave_policy``), and that
knob is itself ANDed against ``daedalus.core.get_governance()``'s
``promotion_allowed`` inside ``run_write_wave`` -- no level of it, including
``always``, promotes anything while this repo's discrimination receipt is
stale, absent, or unreadable. At EVERY level, "promoted" still never means
"merged into ``repo_root``": that step stays a human ``git merge`` of the
integration branch, same as before this was wired. A DRY RUN wave (or a
write-free wave) is unaffected -- it still goes through
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .build import BuildSession, Wave, load_session, wave_path_conflicts
from .kairos.scheduler import Assignment, KairosScheduler


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
# statuses ("gated_promoted", "gated_held", "gated_refused",
# "write_gate_failed") all fall through to "bounced" below, even a clean,
# fully-auto-promoted candidate. That is correct, not an omission --
# "landed" here has only ever meant repo_root's PRIMARY checkout changed, and
# a gated candidate never does that, no matter how far it advanced (see
# run_write_wave's own docstring: promotion lands in a disposable integration
# worktree/branch, never repo_root). The full status string and reason are
# never lost -- they ride along in the raw per-task result dict
# (BuildTask.last_result).


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


def _accepts_cancel(fn: Any) -> bool:
    """Does ``fn`` take a ``cancel`` keyword? Asked of the callable, never
    assumed, so this seam starts working the instant the parameter lands
    downstream and needs no flag day to coordinate."""
    try:
        return "cancel" in inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins, C callables, odd wrappers
        return False


def _task_status(dispatch_status: str) -> str:
    if dispatch_status in _LANDED_STATUSES:
        return "landed"
    if dispatch_status in _PLANNED_STATUSES:
        return "planned"
    return "bounced"


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "mode": self.mode, "dry_run": self.dry_run,
            "write_tasks": self.write_tasks, "advisory_tasks": self.advisory_tasks,
            "landed_tasks": self.landed_tasks, "bounced_tasks": self.bounced_tasks,
            "forced_sequential_reason": self.forced_sequential_reason,
            "path_conflicts": self.path_conflicts, "results": self.results,
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
            "waves": [w.to_dict() for w in self.waves],
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

    def __init__(self, availability: dict | None = None) -> None:
        self.availability = availability

    def _scheduler_for(self, session: BuildSession) -> KairosScheduler:
        scheduler = KairosScheduler(availability=self.availability, project=session.project)
        scheduler.max_workers = max(1, int(session.max_workers))
        return scheduler

    @staticmethod
    def _task_dicts(wave: Wave) -> list[dict[str, Any]]:
        return [{"objective": t.objective, "paths": list(t.paths)} for t in wave.tasks]

    def classify_wave(self, scheduler: KairosScheduler, wave: Wave, repo_root: str) -> list[Assignment]:
        """Read-only: route every task in ``wave`` without executing anything.
        ``KairosScheduler.accept`` never touches a provider or writes a file
        -- it is the same call ``.plan()`` uses for its own dry-run verdict
        -- so this is always safe to call, live or dry-run, before deciding
        whether a wave may run concurrently."""
        return scheduler.accept(self._task_dicts(wave), repo_root=repo_root)

    def run_wave(self, scheduler: KairosScheduler, wave: Wave, repo_root: str, *,
                 dry_run: bool = True, parallel: bool = True,
                 cancel: Any = None) -> WaveResult:
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
        tasks = self._task_dicts(wave)
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
        # see gate_candidates), and whether the resulting candidate then
        # auto-advances to the integration branch or waits for a human is this
        # project's configured `write_wave_policy` (daedalus.config
        # .resolve_write_wave_policy), itself ANDed against
        # daedalus.core.get_governance()'s promotion_allowed inside
        # run_write_wave -- see that function's docstring. NEITHER path ever
        # writes repo_root's primary checkout for a write-mode task in this
        # wave: a promoted candidate lands only in a disposable integration
        # worktree/branch, so BuildTask.status below still coarses every one of
        # these outcomes to "bounced" (never "landed") -- that is correct, not
        # a regression, because "landed" in this file has only ever meant "the
        # primary checkout changed", and none of these outcomes do that.
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

        if not dry_run:
            for t in wave.tasks:
                t.mark("dispatched")

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
            raw = run_write_wave(scheduler, repo_root, tasks, assignments,
                                 auto_promote=write_wave_policy, **extra)
        else:
            raw = scheduler.dispatch(repo_root, tasks, dry_run=dry_run, parallel=wave_parallel)
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
        for task, result in zip(wave.tasks, raw):
            task.last_result = result
            if dry_run:
                continue
            coarse = _task_status(str(result.get("status", "")))
            task.mark(coarse, result)
            if coarse == "landed":
                landed_n += 1
            elif coarse == "bounced":
                bounced_n += 1

        result_mode = "gated" if gated_write_wave else ("parallel" if wave_parallel else "sequential")
        return WaveResult(
            index=wave.index, mode=result_mode,
            dry_run=dry_run, write_tasks=write_n, advisory_tasks=advisory_n,
            landed_tasks=landed_n, bounced_tasks=bounced_n,
            forced_sequential_reason=forced_reason, path_conflicts=conflicts, results=raw,
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

            result = self.run_wave(scheduler, wave, root, dry_run=dry_run, parallel=wave_parallel)
            wave_results.append(result)

            if checkpoint_every_wave and not dry_run:
                session.save(runs_dir, update_architecture=update_architecture)

            if stop_on_bounce and result.bounced_tasks:
                break

        snapshot_path = None
        if not dry_run:
            snapshot_path = str(session.save(runs_dir, update_architecture=update_architecture))

        return BuildRunReport(
            feature=session.feature, slug=session.slug, repo_root=root, dry_run=dry_run,
            waves=wave_results, skipped_waves=skipped, snapshot_path=snapshot_path,
        )


def main() -> None:
    import argparse

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
