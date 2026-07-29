"""KILL SWITCH for the unattended loop. A loop you cannot stop is one you may not start.

ADR-013's precondition list, and ADR-007 line 19, name this as unmet:
*"Acceptance requires ... a kill switch that the candidate process cannot
modify."* This module is that switch, and every claim it makes below is a
claim someone measured, not a claim someone hoped.

THE MECHANISM, AND WHY THIS ONE
-------------------------------
A **permit file**, not a stop file. The loop runs only while a file on disk
holds the exact token ``RUN`` on its first non-empty line. A human in another
terminal halts the loop with::

    python -m daedalus.spine.killswitch stop

which is a rename-over of that file plus a sticky ``.stopped`` marker beside
it. ``del`` on the permit works just as well, which matters at 3am.

Presence-means-stop (the obvious design) was rejected because it fails OPEN on
every interesting failure. ``Path.exists()`` returns ``False`` for "the file is
not there" AND for "the volume is gone", "the ACL denies you", "the name is too
long", "the handle table is exhausted" -- so a switch built on it silently
answers *continue* exactly when the machine is least trustworthy. Absence-means-
stop inverts every one of those: any question this module cannot answer becomes
STOP. That is requirement 4, and it is structural rather than promised, because
there is no code path in :meth:`KillSwitch.read_state` that returns "running"
without having positively read the token.

THE LATENCY CONTRACT, WHICH IS THE WHOLE DELIVERABLE
----------------------------------------------------
A bound nobody measured is a promise. Three bounds, three different things,
stated separately because they are NOT the same number:

1. **OBSERVATION** -- the switch latches within ONE poll interval of the permit
   changing on disk (default 0.25 s). MEASURED at a 0.1 s poll, across a
   *process boundary* because the operator is in another terminal and not in
   this interpreter: **215 / 222 / 225 / 233 / 239 ms** over five runs, against
   a 600 ms budget (``test_latency_latch_within_one_poll_interval``). The
   stamp is taken BEFORE the stop is written, so every figure over-reports.
2. **CHILD DEATH** -- the whole process TREE is dead, and the gate has given
   up, within the same window. MEASURED on the real
   :func:`daedalus.spine.attempt.pytest_gate` path against a child that ignores
   ``CTRL_BREAK_EVENT`` and has spawned a grandchild: **257 / 258 / 262 / 268 /
   425 ms** (cold first run last), against a 3.0 s budget
   (``test_latency_gate_child_tree_dies``). Both pids are asserted dead, not
   merely "cancelled".
3. **NO NEW SPEND** -- no attempt and no provider call is *started* after the
   latch, because :meth:`checkpoint` raises. An HTTP request already in flight
   is NOT aborted. That is a real hole and it is named here rather than papered
   over: the bound is *before the next* billable call, not *during* this one.

MONOTONIC BY CONSTRUCTION
-------------------------
Once :meth:`should_stop` has answered True it answers True forever, in memory,
for the life of the object. Restoring the permit file does not un-latch it.
This is what turns "a candidate might win a race against the poller" from a
defeat into a 0.25 s window that must ALSO get past the kernel (below).

WHAT A CANDIDATE CAN AND CANNOT DO -- MEASURED ON THIS BOX
----------------------------------------------------------
The permit lives in ``%LOCALAPPDATA%/daedalus/control/<repo-digest>/``, a
SIBLING of ``%LOCALAPPDATA%/daedalus/worktrees/`` where candidate worktrees go.
That is deliberate: :func:`daedalus.spine.containment.label_low_integrity`
stamps ``(OI)(CI)Low`` on a worktree, and inheritance flows DOWN a tree, never
sideways -- so no amount of labelling in ``worktrees/`` can ever reach
``control/``.

  * A candidate under :func:`daedalus.spine.containment.spawn_contained`
    (Low integrity) is refused by the KERNEL when it tries to delete the
    permit, overwrite it with ``RUN``, delete the ``.stopped`` marker, or
    create either. Measured in ``test_contained_candidate_cannot_defeat_it``,
    which also asserts the same candidate CAN write its own worktree -- without
    that half, the test would pass just as happily against a candidate that
    never ran.
  * A candidate NOT under containment, running at the operator's own integrity
    level, CAN rewrite both files. It still cannot un-latch a switch that has
    already read STOP (``test_uncontained_forgery_cannot_unlatch``). So the
    residual exposure is a sub-poll-interval race, not a defeat -- and it
    closes entirely when the loop uses containment, which is why ADR-007's
    wording ("cannot modify") is only satisfied in the contained configuration.

THE SWEEP IS PROCESS-WIDE, SO THE LOOP MUST OWN ITS INTERPRETER
---------------------------------------------------------------
:meth:`KillSwitch.stop_children` calls
:func:`daedalus.spine.cancel.cancel_all_managed`, which cancels EVERY live
``ManagedProcess`` in this interpreter -- not merely the ones handed to
:meth:`KillSwitch.track`. That breadth is deliberate: the backstop exists
precisely for the child whose loop driver forgot to thread ``cancel=`` through,
and a registry that only reaps what it was told about would not have caught it.

The cost is that a kill switch in a process that hosts more than the loop (a
web API, a REPL) will also kill that other work. For an unattended loop driver
that is correct and is the point; for anything else, construct the switch with
``sweep_managed=False`` and rely on :meth:`track` plus the cancel token. Do not
run the loop inside a long-lived multi-purpose process and expect the sweep to
be discriminating -- it is not, and it is not trying to be.

WHY THERE IS NO LOCK HERE
-------------------------
``runs/council/room.py::_RoomLock`` is this repo's cross-process locking idiom
and it is the right one for the room -- it degrades to a no-op when the lock
cannot be taken, on the reasoning that losing serialisation beats losing a
human's message. That trade is exactly inverted here: a kill switch that
degrades is not a kill switch. So rather than reuse a fail-open lock or invent
a third mechanism, this module needs no lock at all: writes go through
``os.replace`` (atomic on both platforms), so a reader sees the old bytes or
the new bytes and never a torn file, and a read that fails for ANY reason --
including a Windows sharing violation -- is already STOP.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from daedalus.spine.cancel import cancel_all_managed

__all__ = [
    "DEFAULT_POLL_S",
    "ENV_SWITCH_PATH",
    "KillSwitch",
    "LoopHalted",
    "MAX_PERMIT_BYTES",
    "REPLACE_RETRY_S",
    "RUN_TOKEN",
    "STOP_TOKEN",
    "SwitchState",
    "default_switch_path",
]

#: The only token that means "keep going". Anything else means stop.
RUN_TOKEN = "RUN"
STOP_TOKEN = "STOP"

#: Poll interval for :meth:`KillSwitch.watch`, and the unit of the OBSERVATION
#: bound. 0.25 s matches the poll in :func:`daedalus.spine.attempt.pytest_gate`,
#: so the two loops cannot disagree about how stale a verdict may be.
DEFAULT_POLL_S = 0.25

#: A permit larger than this is refused unread. Candidate code cannot be
#: allowed to make the switch's own read slow (or memory-hungry) by growing the
#: file it is being watched by.
MAX_PERMIT_BYTES = 64 * 1024

#: How long an atomic replace may retry a sharing conflict. See
#: :meth:`KillSwitch._atomic_write` -- a poller reading the permit can block the
#: operator's own write on win32, and that raced in practice.
REPLACE_RETRY_S = 2.0

ENV_SWITCH_PATH = "DAEDALUS_KILLSWITCH"

#: Repo root, mirroring the convention in :mod:`daedalus.spine.attempt`.
ROOT = Path(__file__).resolve().parents[2]

_MARKER_SUFFIX = ".stopped"


class LoopHalted(RuntimeError):
    """Raised by :meth:`KillSwitch.checkpoint` when the loop must not proceed.

    An exception rather than a return value on purpose: a checkpoint placed
    before a billable call must be impossible to ignore by forgetting to look
    at a bool.
    """


@dataclass(frozen=True)
class SwitchState:
    """One reading of the permit. ``running`` is never true by default."""

    running: bool
    reason: str
    path: str
    token: str | None = None

    @property
    def stopped(self) -> bool:
        return not self.running

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "reason": self.reason,
            "path": self.path,
            "token": self.token,
        }


def default_switch_path(repo_root: str | Path | None = None) -> Path:
    """Where the permit lives for ``repo_root``.

    Placement mirrors :func:`daedalus.kairos.worktree._worktree_root_for` so an
    operator can correlate the two by their shared repo digest -- but under
    ``control/`` rather than ``worktrees/``. That sibling relationship is the
    load-bearing part: a Low integrity label applied to a worktree propagates
    down its own tree and cannot reach a sibling.

    ``DAEDALUS_KILLSWITCH`` overrides it, which is how tests and an operator
    with an unusual layout point at another file.
    """
    override = os.environ.get(ENV_SWITCH_PATH)
    if override:
        return Path(os.path.abspath(override))
    local_appdata = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_appdata) if local_appdata else Path(tempfile.gettempdir())
    repo = Path(repo_root).resolve() if repo_root else ROOT
    digest = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:12]
    return base_dir / "daedalus" / "control" / digest / "killswitch"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KillSwitch:
    """A latching, fail-closed permit that a human can revoke from anywhere.

    Usage in a loop driver::

        switch = KillSwitch()
        with switch.watch():                 # background poller + child reaper
            while True:
                switch.checkpoint()          # raises LoopHalted; no new spend
                run_attempt(task, cancel=switch, ...)

    ``cancel=switch`` works unmodified because
    :func:`daedalus.spine.attempt._as_predicate` accepts any callable, and this
    object is callable. It also exposes ``is_set()`` so it can stand in for a
    ``threading.Event`` anywhere one is expected.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        poll_s: float = DEFAULT_POLL_S,
        repo_root: str | Path | None = None,
        kill_grace_s: float = 0.0,
        cooperative_grace_s: float = DEFAULT_POLL_S,
        sweep_managed: bool = True,
    ) -> None:
        # RESOLVED ONCE. Re-reading the environment on every check would let
        # anything that can set an env var in this process move the switch out
        # from under a running loop; the path a loop was started with is the
        # path it is stopped by.
        self._path = Path(path) if path is not None else default_switch_path(repo_root)
        self._path = Path(os.path.abspath(str(self._path)))
        self._marker = self._path.with_name(self._path.name + _MARKER_SUFFIX)
        self.poll_s = max(0.01, float(poll_s))
        self.kill_grace_s = max(0.0, float(kill_grace_s))
        self.cooperative_grace_s = max(0.0, float(cooperative_grace_s))
        self._sweep_managed = bool(sweep_managed)

        self._lock = threading.Lock()
        self._tripped = False
        self._reason: str | None = None
        self._event = threading.Event()
        self._tracked: list[Any] = []
        self._watcher: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self._children_stopped = False

    # -- identity ---------------------------------------------------------- #

    @property
    def path(self) -> Path:
        """The permit path, frozen at construction."""
        return self._path

    @property
    def marker_path(self) -> Path:
        return self._marker

    @property
    def reason(self) -> str | None:
        """Why the switch latched, or ``None`` while it has not."""
        return self._reason

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<KillSwitch path={self._path} tripped={self._tripped}>"

    # -- reading ----------------------------------------------------------- #

    def _marker_present(self) -> tuple[bool, str | None]:
        """``(present, unreadable_reason)``.

        NOT ``Path.exists()``. ``exists()`` swallows every OSError and answers
        False, so an ACL that denies us the marker would read as "no stop was
        requested" -- the precise fail-open this module exists to avoid. Only
        ``FileNotFoundError``/``NotADirectoryError`` mean absent; anything else
        means we could not tell, and could-not-tell is STOP.
        """
        try:
            os.stat(self._marker)
        except (FileNotFoundError, NotADirectoryError):
            return False, None
        except OSError as e:
            return True, f"the stop marker could not be examined ({e})"
        return True, None

    def read_state(self) -> SwitchState:
        """Read the permit from disk. Never raises; defaults to stopped.

        Every early return below is a STOP. There is exactly one ``running``
        exit, and it is reached only after the token was positively read and no
        stop marker was found.
        """
        p = self._path

        def halt(reason: str, token: str | None = None) -> SwitchState:
            return SwitchState(False, reason, str(p), token)

        try:
            st = os.stat(p)
        except (FileNotFoundError, NotADirectoryError):
            return halt("no permit file: the loop is not armed")
        except OSError as e:
            return halt(f"the permit could not be examined ({e})")
        except Exception as e:  # noqa: BLE001 - a switch may not raise, ever
            return halt(f"the permit could not be examined ({type(e).__name__}: {e})")

        if not stat.S_ISREG(st.st_mode):
            return halt("the permit path is not a regular file")
        if st.st_size > MAX_PERMIT_BYTES:
            return halt(f"the permit is implausibly large ({st.st_size} bytes)")

        try:
            data = p.read_bytes()
        except OSError as e:
            return halt(f"the permit could not be read ({e})")
        except Exception as e:  # noqa: BLE001
            return halt(f"the permit could not be read ({type(e).__name__}: {e})")

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return halt("the permit is not valid UTF-8")

        token: str | None = None
        for line in text.splitlines():
            if line.strip():
                token = line.strip()
                break
        if token is None:
            return halt("the permit is empty")
        if token != RUN_TOKEN:
            if token == STOP_TOKEN:
                return halt("stop was requested", token)
            return halt(f"the permit holds an unrecognised token {token!r}", token)

        present, unreadable = self._marker_present()
        if unreadable is not None:
            return halt(unreadable, token)
        if present:
            return halt("a stop marker is present beside the permit", token)

        return SwitchState(True, "armed", str(p), token)

    # -- latching ---------------------------------------------------------- #

    def should_stop(self) -> bool:
        """True once, then True forever. NEVER raises, and NEVER returns False
        because something went wrong.

        The never-raises property is not politeness. ``_as_predicate`` in
        :mod:`daedalus.spine.attempt` wraps a cancel token in
        ``try/except -> False``, i.e. a token that raises is treated as *not
        cancelled*. That is fail-open, it lives in a file this module may not
        edit, and the only defence available from this side is to make raising
        impossible: any internal failure here latches STOP instead of escaping.
        """
        with self._lock:
            if self._tripped:
                return True
        try:
            state = self.read_state()
            stopped, reason = state.stopped, state.reason
        except BaseException as e:  # noqa: BLE001 - see docstring
            stopped, reason = True, f"the switch itself failed ({type(e).__name__}: {e})"
        if not stopped:
            return False
        with self._lock:
            if not self._tripped:
                self._tripped = True
                self._reason = reason
            self._event.set()
        return True

    # Interchangeable with a callable token and with a threading.Event, so it
    # drops into `cancel=` (attempt.TaskAttempt) either way.
    def __call__(self) -> bool:
        return self.should_stop()

    def is_set(self) -> bool:
        return self.should_stop()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the watcher latches. Only meaningful under :meth:`watch`."""
        return self._event.wait(timeout)

    def checkpoint(self) -> None:
        """Raise :class:`LoopHalted` if the loop must not proceed.

        Call this immediately before anything that costs money or writes: it is
        the enforcement point for the "no new spend after the latch" bound.
        """
        if self.should_stop():
            raise LoopHalted(f"kill switch engaged: {self._reason} [{self._path}]")

    # -- children ---------------------------------------------------------- #

    def track(self, managed: Any) -> Any:
        """Register a :class:`~daedalus.spine.cancel.ManagedProcess` to reap.

        Returns its argument so it can wrap a constructor inline. Tracking is
        belt-and-braces: :func:`~daedalus.spine.cancel.cancel_all_managed`
        already sweeps every live ``ManagedProcess`` in this interpreter, which
        is what stops a gate child whose loop driver forgot to thread the
        cancel token through.
        """
        with self._lock:
            self._tracked.append(managed)
        return managed

    def stop_children(self) -> list:
        """Cancel every tracked tree, and (by default) every live managed tree.

        Returns the cancel results. Idempotent per trip; a second call after
        everything is already dead is cheap and harmless.
        """
        results = []
        with self._lock:
            tracked = list(self._tracked)
            self._children_stopped = True
        for proc in tracked:
            try:
                results.append(proc.cancel(grace_s=self.kill_grace_s))
            except Exception:  # noqa: BLE001 - one stuck child may not block the rest
                pass
        if self._sweep_managed:
            try:
                results.extend(cancel_all_managed(grace_s=self.kill_grace_s))
            except Exception:  # noqa: BLE001
                pass
        return results

    @property
    def children_stopped(self) -> bool:
        return self._children_stopped

    # -- the watcher ------------------------------------------------------- #

    def start_watch(self) -> None:
        """Start the background poller. Idempotent.

        A DAEMON thread that exits on the first trip: a watcher that outlives
        its trip is the "stale watcher still running old code" failure this
        repo has already paid for once.
        """
        with self._lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            self._watch_stop.clear()
            self._watcher = threading.Thread(
                target=self._watch_loop, name="daedalus-killswitch", daemon=True)
            watcher = self._watcher
        watcher.start()

    def stop_watch(self, timeout: float = 5.0) -> None:
        """Stop the poller and join it. Idempotent; safe after a trip."""
        self._watch_stop.set()
        with self._lock:
            watcher = self._watcher
            self._watcher = None
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=timeout)

    def _watch_loop(self) -> None:
        while True:
            if self.should_stop():
                # THE LATCH IS ALREADY SET at this point, so every cooperative
                # poller (pytest_gate's loop over ctx.is_cancelled(), and any
                # `cancel=switch` checkpoint) can already see it. Wait one gate
                # poll before the sweep of last resort fires.
                #
                # WHY, and this cost a measured bug: the sweep and the gate's
                # own poll race for the same child. When the sweep won, the
                # gate saw `proc.poll()` return non-None, left its loop by the
                # ordinary exit, and reported `cancelled=False, returncode=1`
                # -- which attempt.py then records as `gates_failed` rather
                # than `cancelled`. That is a FABRICATED VERDICT about a
                # candidate whose tests were never judged, and it would feed
                # the picker as if the candidate had been measured and lost.
                # Observed flapping ~50/50 across runs before this wait.
                #
                # The sweep is not weakened by yielding: the gate's own
                # `proc.cancel()` blocks for its DEFAULT 3 s grace against a
                # child that ignores CTRL_BREAK, and the sweep's grace-0
                # kill_tree cuts that wait short the moment it fires. So the
                # cooperative path gets the correct ATTRIBUTION and the sweep
                # still supplies the SPEED.
                if self.cooperative_grace_s > 0:
                    self._watch_stop.wait(self.cooperative_grace_s)
                # Unconditional: we have tripped, so children die even if the
                # watcher was also asked to shut down during the grace.
                self.stop_children()
                return
            # wait() returns True only when asked to shut down, so an armed
            # switch costs one syscall per poll and no busy loop.
            if self._watch_stop.wait(self.poll_s):
                return

    def watch(self) -> "_WatchScope":
        """Context manager wrapping :meth:`start_watch`/:meth:`stop_watch`."""
        return _WatchScope(self)

    def __enter__(self) -> "KillSwitch":
        self.start_watch()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop_watch()

    # -- operator side ----------------------------------------------------- #

    def _atomic_write(self, target: Path, text: str,
                      retry_s: float = REPLACE_RETRY_S) -> None:
        """Replace ``target`` atomically, retrying a Windows sharing conflict.

        MEASURED, and the reason this retry exists: on win32 a poller reading
        the permit holds it open WITHOUT ``FILE_SHARE_DELETE`` (CPython's
        ``open()`` offers no way to ask for it), so ``MoveFileEx`` over it
        returns ERROR_ACCESS_DENIED. With a 50 ms poll that raced often enough
        to break the operator's own stop command -- i.e. the kill switch could
        fail to engage precisely because something was watching it. The window
        is one ``read_bytes`` of a <1 KiB file, so a bounded retry closes it;
        the caller decides what an exhausted retry means.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(text, encoding="utf-8")
        deadline = time.monotonic() + max(0.0, retry_s)
        while True:
            try:
                os.replace(tmp, target)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                time.sleep(0.02)

    def arm(self, *, force: bool = False, note: str = "") -> SwitchState:
        """Write the permit so work may proceed.

        REFUSES if a stop marker is present unless ``force=True``. That refusal
        is the guard against the most likely way an unattended system undoes a
        human decision: the loop crashes, a supervisor restarts it, its startup
        path calls ``arm()``, and the 3am stop evaporates. Re-arming after a
        deliberate stop has to be a deliberate act.
        """
        present, unreadable = self._marker_present()
        if (present or unreadable is not None) and not force:
            raise LoopHalted(
                f"refusing to arm: a stop marker is present at {self._marker}. "
                f"A human stopped this loop; clear it explicitly "
                f"(arm(force=True), or `python -m daedalus.spine.killswitch "
                f"clear`) rather than re-arming automatically.")
        if force:
            try:
                os.unlink(self._marker)
            except OSError:
                pass
        body = f"{RUN_TOKEN}\narmed_at={_now_iso()}\npid={os.getpid()}\n"
        if note:
            body += f"note={note.splitlines()[0][:200]}\n"
        self._atomic_write(self._path, body)
        return self.read_state()

    def stop(self, reason: str = "operator request") -> SwitchState:
        """Revoke the permit and drop a sticky marker. The operator entry point.

        MARKER FIRST, and that order is load-bearing twice over:

        * If the process dies between the two writes, the permit still says
          ``RUN`` -- but the marker alone already means stop, so the crash
          window resolves to STOPPED rather than to running.
        * :meth:`_marker_present` uses ``os.stat``, which does not open the
          file, so nothing a poller does can block the marker being written.
          The permit rewrite is the one that can lose a sharing race, and by
          then the stop has ALREADY taken effect.

        Neither write failing is swallowed and neither is allowed to abort a
        stop that did take: this raises only if, after both attempts, the
        switch still reads as running. An operator's stop command must be loud
        when it did nothing and quiet when it worked.
        """
        first = reason.splitlines()[0][:200] if reason else "operator request"
        body = f"{STOP_TOKEN}\nat={_now_iso()}\nreason={first}\n"
        errors: list[str] = []
        for target in (self._marker, self._path):
            try:
                self._atomic_write(target, body)
            except OSError as e:
                errors.append(f"{target.name}: {e}")
        # Latch THIS object too. The operator asked this switch to stop; that
        # must not depend on a subsequent read of a disk that just misbehaved.
        with self._lock:
            if not self._tripped:
                self._tripped = True
                self._reason = f"stop requested: {first}"
            self._event.set()
        state = self.read_state()
        if state.running:
            raise LoopHalted(
                f"THE STOP DID NOT TAKE: {self._path} still reads as armed "
                f"after writing both files ({'; '.join(errors) or 'no error'}). "
                f"Kill the loop process directly.")
        return state

    def clear(self) -> None:
        """Remove permit and marker. Leaves the switch STOPPED (no permit)."""
        for target in (self._marker, self._path):
            try:
                os.unlink(target)
            except OSError:
                pass


class _WatchScope:
    def __init__(self, switch: KillSwitch) -> None:
        self._switch = switch

    def __enter__(self) -> KillSwitch:
        self._switch.start_watch()
        return self._switch

    def __exit__(self, exc_type, exc, tb) -> None:
        self._switch.stop_watch()


# --------------------------------------------------------------------------- #
# operator CLI -- `python -m daedalus.spine.killswitch <verb>`                  #
# --------------------------------------------------------------------------- #
def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    verb = args[0] if args else "status"
    path: str | None = None
    rest: list[str] = []
    i = 1
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            path = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1

    switch = KillSwitch(path)
    if verb == "stop":
        state = switch.stop(" ".join(rest) or "operator request")
        print(f"STOPPED {switch.path}: {state.reason}")
        return 0
    if verb == "arm":
        force = "--force" in rest
        try:
            state = switch.arm(force=force, note=" ".join(w for w in rest if w != "--force"))
        except LoopHalted as e:
            print(str(e))
            return 4
        print(f"{'ARMED' if state.running else 'NOT ARMED'} {switch.path}: {state.reason}")
        return 0 if state.running else 3
    if verb == "clear":
        switch.clear()
        print(f"CLEARED {switch.path} (loop remains stopped: no permit)")
        return 0
    if verb == "status":
        state = switch.read_state()
        print(f"{'RUNNING' if state.running else 'STOPPED'} {switch.path}: {state.reason}")
        return 0 if state.running else 3
    print(f"usage: python -m daedalus.spine.killswitch "
          f"{{status|arm|stop|clear}} [--path P] [--force] [reason...]")
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(_main(sys.argv[1:]))
