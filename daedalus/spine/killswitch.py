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

OPERATOR WRITES ARE SERIALISED; READERS NEVER WAIT
--------------------------------------------------
Atomic replacement prevents a torn permit, but it does not prevent two
operators from reading generation N and both publishing N+1. ``arm`` and
``stop`` therefore take one stable sibling OS lock. POSIX uses ``flock`` and
Windows opens the lock file with sharing disabled. Failure to acquire it is a
refusal, never a no-op lock.

The authoritative sibling ``.generation`` counter is committed and flushed
before a RUN permit carrying the same value. A crash between those writes is
STOP because counter and permit disagree. ``clear`` deliberately preserves the
counter and lock, so delete/re-arm cannot make an old execution generation
valid again. Pollers never take this lock: reads remain bounded and any missing,
corrupt, or mismatched counter is already STOP.
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
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..atomic import write_text_atomic
from typing import Any, Iterable, Iterator

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
_GENERATION_SUFFIX = ".generation"
_OPERATOR_LOCK_SUFFIX = ".lock"


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
    generation: int | None = None

    @property
    def stopped(self) -> bool:
        return not self.running

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "reason": self.reason,
            "path": self.path,
            "token": self.token,
            "generation": self.generation,
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
        self._generation_path = self._path.with_name(
            self._path.name + _GENERATION_SUFFIX
        )
        self._operator_lock_path = self._path.with_name(
            self._path.name + _OPERATOR_LOCK_SUFFIX
        )
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
    def generation_path(self) -> Path:
        """Durable monotone counter paired with :attr:`path`."""

        return self._generation_path

    @property
    def operator_lock_path(self) -> Path:
        """Stable sibling used only to serialize explicit arm/stop writes."""

        return self._operator_lock_path

    @property
    def reason(self) -> str | None:
        """Why the switch latched, or ``None`` while it has not."""
        return self._reason

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<KillSwitch path={self._path} tripped={self._tripped}>"

    @staticmethod
    def _strict_path_present(path: Path, role: str) -> tuple[bool, str | None]:
        try:
            os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return False, None
        except OSError as exc:
            return False, f"{role} could not be examined ({exc})"
        return True, None

    def _read_generation_counter(self) -> tuple[int | None, str | None]:
        """Read the authoritative counter; missing is distinct from corrupt."""

        path = self._generation_path
        try:
            metadata = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return None, None
        except OSError as exc:
            return None, f"the generation counter could not be examined ({exc})"
        if not stat.S_ISREG(metadata.st_mode):
            return None, "the generation counter is not a regular file"
        if metadata.st_size > 128:
            return None, "the generation counter is implausibly large"
        try:
            raw = path.read_bytes()
            text = raw.decode("ascii")
        except (OSError, UnicodeError) as exc:
            return None, f"the generation counter could not be read ({exc})"
        if not text.endswith("\n") or text.count("\n") != 1:
            return None, "the generation counter is not canonical"
        digits = text[:-1]
        if not digits or not digits.isascii() or not digits.isdigit():
            return None, "the generation counter is not a non-negative integer"
        value = int(digits)
        if str(value) != digits:
            return None, "the generation counter has a non-canonical integer"
        return value, None

    @staticmethod
    def _embedded_generation(path: Path) -> tuple[int | None, bool, str | None]:
        """Return ``(generation, exists, error)`` for legacy bootstrap only."""

        try:
            metadata = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return None, False, None
        except OSError as exc:
            return None, True, f"{path.name} could not be examined ({exc})"
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PERMIT_BYTES:
            return None, True, f"{path.name} is not a bounded regular state file"
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            return None, True, f"{path.name} could not be read ({exc})"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] not in {RUN_TOKEN, STOP_TOKEN}:
            return None, True, f"{path.name} has no canonical switch token"
        generations = [
            line.split("=", 1)[1].strip()
            for line in lines[1:]
            if line.startswith("generation=")
        ]
        if len(generations) > 1:
            return None, True, f"{path.name} contains multiple generations"
        if not generations:
            return 0, True, None
        digits = generations[0]
        if not digits or not digits.isascii() or not digits.isdigit():
            return None, True, f"{path.name} generation is invalid"
        return int(digits), True, None

    def _bootstrap_generation(self, *, lock_preexisted: bool) -> int:
        counter, error = self._read_generation_counter()
        if error is not None:
            raise LoopHalted(f"refusing operator write: {error}")
        if counter is not None:
            return counter
        if lock_preexisted:
            raise LoopHalted(
                "refusing operator write: the authoritative generation counter "
                "is missing after this switch identity was initialized"
            )
        observed: list[int] = []
        any_state = False
        for path in (self._path, self._marker):
            generation, exists, state_error = self._embedded_generation(path)
            any_state = any_state or exists
            if state_error is not None:
                raise LoopHalted(
                    "refusing first generation initialization: " + state_error
                )
            if generation is not None:
                observed.append(generation)
        if any_state and not observed:
            raise LoopHalted(
                "refusing first generation initialization from unreadable state"
            )
        return max(observed, default=0)

    @contextmanager
    def _operator_lock_scope(self, *, wait_forever: bool = False) -> Iterator[bool]:
        """Exclusively serialize explicit operator writes, never pollers.

        Ordinary arm/clear operations use a bounded refusal.  ``stop`` first
        publishes its emergency marker and then waits without a false-success
        timeout: it must overtake any in-flight force-arm and reassert STOP as
        the final serialized writer before reporting completion.
        """

        lock_path = self._operator_lock_path
        present, error = self._strict_path_present(lock_path, "operator lock")
        if error is not None:
            raise LoopHalted(error)
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LoopHalted(f"operator lock parent could not be created ({exc})") from exc

        deadline = None if wait_forever else time.monotonic() + REPLACE_RETRY_S
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes

            create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
            create_file.argtypes = (
                ctypes.wintypes.LPCWSTR,
                ctypes.wintypes.DWORD,
                ctypes.wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.wintypes.DWORD,
                ctypes.wintypes.DWORD,
                ctypes.wintypes.HANDLE,
            )
            create_file.restype = ctypes.wintypes.HANDLE
            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            close_handle.argtypes = (ctypes.wintypes.HANDLE,)
            close_handle.restype = ctypes.wintypes.BOOL
            invalid = ctypes.wintypes.HANDLE(-1).value
            handle = invalid
            while handle == invalid:
                handle = create_file(
                    os.fspath(lock_path),
                    0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                    0,  # no sharing: this handle is the lock
                    None,
                    4,  # OPEN_ALWAYS
                    0x80,  # FILE_ATTRIBUTE_NORMAL
                    None,
                )
                if handle != invalid:
                    break
                winerror = ctypes.get_last_error()
                if winerror not in {32, 33} or (
                    deadline is not None and time.monotonic() >= deadline
                ):
                    raise LoopHalted(
                        "operator lock could not be acquired "
                        f"({ctypes.FormatError(winerror)})"
                    )
                time.sleep(0.02)
            try:
                yield present
            finally:
                close_handle(handle)
            return

        import fcntl

        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if deadline is not None and time.monotonic() >= deadline:
                        raise LoopHalted("operator lock acquisition timed out") from exc
                    time.sleep(0.02)
            yield present
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _write_generation_counter(self, generation: int) -> None:
        self._atomic_write(
            self._generation_path,
            f"{generation}\n",
            newline="",
        )
        # Flush the published name, then its directory where the platform
        # exposes directory fsync. Counter-before-permit is the crash fence.
        with self._generation_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        if os.name != "nt":
            descriptor = os.open(
                self._generation_path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

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

        generation: int | None = None

        def halt(reason: str, token: str | None = None) -> SwitchState:
            return SwitchState(False, reason, str(p), token, generation)

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
        generation_values: list[str] = []
        for line in text.splitlines():
            if line.strip():
                if token is None:
                    token = line.strip()
                elif line.startswith("generation="):
                    generation_values.append(line.split("=", 1)[1].strip())
        if token is None:
            return halt("the permit is empty")
        if len(generation_values) > 1:
            return halt("the permit contains multiple generations", token)
        if generation_values:
            raw_generation = generation_values[0]
            if not raw_generation.isascii() or not raw_generation.isdigit():
                return halt("the permit generation is not a non-negative integer", token)
            generation = int(raw_generation)
        else:
            # Historical `RUN\n` permits remain readable as generation zero;
            # only a never-initialized path may use this compatibility form.
            generation = 0
        if token != RUN_TOKEN:
            if token == STOP_TOKEN:
                return halt("stop was requested", token)
            return halt(f"the permit holds an unrecognised token {token!r}", token)

        counter, counter_error = self._read_generation_counter()
        if counter_error is not None:
            return halt(counter_error, token)
        lock_present, lock_error = self._strict_path_present(
            self._operator_lock_path,
            "the operator lock",
        )
        if lock_error is not None:
            return halt(lock_error, token)
        if counter is None and (lock_present or generation_values):
            # The counter is authoritative once either our stable lock identity
            # or a generation-bearing state file proves that this is not a
            # pristine legacy ``RUN\n`` permit.  Requiring BOTH sidecars here
            # made deleting counter+lock revive a stale permit (generation ABA).
            return halt(
                "the authoritative generation counter is missing after initialization",
                token,
            )
        if counter is not None:
            if not generation_values:
                return halt(
                    "the permit omits the initialized generation counter",
                    token,
                )
            if generation != counter:
                return halt(
                    "the permit generation disagrees with the authoritative counter",
                    token,
                )

        present, unreadable = self._marker_present()
        if unreadable is not None:
            return halt(unreadable, token)
        if present:
            return halt("a stop marker is present beside the permit", token)

        return SwitchState(True, "armed", str(p), token, generation)

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

    def _atomic_write(
        self,
        target: Path,
        text: str,
        retry_s: float = REPLACE_RETRY_S,
        *,
        newline: str | None = None,
    ) -> None:
        """Replace ``target`` atomically, retrying a Windows sharing conflict.

        MEASURED, and the reason this retry exists: on win32 a poller reading
        the permit holds it open WITHOUT ``FILE_SHARE_DELETE`` (CPython's
        ``open()`` offers no way to ask for it), so ``MoveFileEx`` over it
        returns ERROR_ACCESS_DENIED. With a 50 ms poll that raced often enough
        to break the operator's own stop command -- i.e. the kill switch could
        fail to engage precisely because something was watching it. The window
        is one ``read_bytes`` of a <1 KiB file, so a bounded retry closes it;
        the caller decides what an exhausted retry means.

        This is where that retry was first measured and written. It now
        delegates to :mod:`daedalus.atomic`, which is this same loop lifted so
        the four other publishers that documented themselves as atomic and
        omitted it (``arch_memory.save``, ``shift._write_atomic``,
        ``file_bridge._write_json_atomic``, ``loop.LoopLedger.save``) share one
        implementation instead of four divergent copies. Behaviour here is
        unchanged: same temp-sibling scheme, same bounded retry, same raise on
        an exhausted deadline.
        """
        write_text_atomic(target, text, retry_s=retry_s, newline=newline)

    @staticmethod
    def _unlink_durable(target: Path, *, missing_ok: bool = False) -> None:
        """Remove one exact name and durably publish the directory change.

        Callers decide the safety order.  In particular, this helper never
        swallows a sharing violation: an operator command must not claim that a
        permit or marker disappeared when Windows kept it alive.
        """

        try:
            os.unlink(target)
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        if os.name != "nt":
            descriptor = os.open(
                target.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def arm(self, *, force: bool = False, note: str = "") -> SwitchState:
        """Write the permit so work may proceed.

        REFUSES if a stop marker is present unless ``force=True``. That refusal
        is the guard against the most likely way an unattended system undoes a
        human decision: the loop crashes, a supervisor restarts it, its startup
        path calls ``arm()``, and the 3am stop evaporates. Re-arming after a
        deliberate stop has to be a deliberate act.
        """
        with self._operator_lock_scope() as lock_preexisted:
            prior_generation = self._bootstrap_generation(
                lock_preexisted=lock_preexisted
            )
            present, unreadable = self._marker_present()
            if (present or unreadable is not None) and not force:
                raise LoopHalted(
                    f"refusing to arm: a stop marker is present at {self._marker}. "
                    f"A human stopped this loop; clear it explicitly "
                    f"(arm(force=True), or `python -m daedalus.spine.killswitch "
                    f"clear`) rather than re-arming automatically.")
            if unreadable is not None:
                raise LoopHalted(f"refusing to arm: {unreadable}")
            generation = prior_generation + 1
            body = (
                f"{RUN_TOKEN}\ngeneration={generation}\n"
                f"armed_at={_now_iso()}\npid={os.getpid()}\n"
            )
            if note:
                body += f"note={note.splitlines()[0][:200]}\n"
            # Counter first makes the old permit stale.  The new permit is
            # published while a pre-existing stop marker still vetoes it.  The
            # marker is removed LAST, so every crash prefix remains STOPPED.
            try:
                self._write_generation_counter(generation)
                self._atomic_write(self._path, body)
            except OSError as exc:
                raise LoopHalted(
                    "refusing to arm: the new generation could not be "
                    f"published ({exc})"
                ) from exc
            if force and present:
                try:
                    self._unlink_durable(self._marker)
                except OSError as exc:
                    raise LoopHalted(
                        "new generation remains stopped: stop marker could not "
                        f"be removed ({exc})"
                    ) from exc
            state = self.read_state()
            if not state.running or state.generation != generation:
                raise LoopHalted(
                    "arm did not publish one matching permit/counter generation: "
                    + state.reason
                )
            return state

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
        errors: list[str] = []
        emergency_body = f"{STOP_TOKEN}\nat={_now_iso()}\nreason={first}\n"
        # Emergency revocation must not queue behind a wedged operator writer.
        # Marker presence alone is the reader's fail-closed ground truth, so
        # publish it before attempting the serialised bookkeeping path.
        try:
            self._atomic_write(self._marker, emergency_body)
        except OSError as exc:
            errors.append(f"{self._marker.name}: {exc}")

        try:
            with self._operator_lock_scope(wait_forever=True) as lock_preexisted:
                generation_bootstrapped = True
                try:
                    generation = self._bootstrap_generation(
                        lock_preexisted=lock_preexisted
                    )
                except LoopHalted as exc:
                    # A stop must still take when generation evidence is damaged.
                    # Marker presence is the fail-closed ground truth; generation
                    # repair is deferred to an operator rather than reset here.
                    generation = 0
                    generation_bootstrapped = False
                    errors.append(str(exc))
                body = (
                    f"{STOP_TOKEN}\ngeneration={generation}\n"
                    f"at={_now_iso()}\nreason={first}\n"
                )
                # Reassert the marker after acquiring the lock.  If a force-arm
                # was already in flight when the emergency marker landed, its
                # critical section completes first and this write wins last.
                for target in (self._marker, self._path):
                    try:
                        self._atomic_write(target, body)
                    except OSError as exc:
                        errors.append(f"{target.name}: {exc}")
                counter, counter_error = self._read_generation_counter()
                if (
                    generation_bootstrapped
                    and not lock_preexisted
                    and counter is None
                    and counter_error is None
                ):
                    try:
                        self._write_generation_counter(generation)
                    except OSError as exc:
                        errors.append(f"{self._generation_path.name}: {exc}")
        except LoopHalted as exc:
            # The pre-lock marker may already have stopped every reader.  Keep
            # that safety effect even when bookkeeping serialization times out.
            errors.append(str(exc))
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
        """Fence the current generation, then remove permit and marker.

        ``clear`` is deliberately not an emergency-stop substitute.  It first
        advances the durable generation under the operator lock, which makes
        any old RUN permit invalid.  It then removes the permit BEFORE the
        marker.  If either publication cannot be proved, it raises and retains
        the marker whenever possible; it never reports a partial clear as
        success.
        """

        with self._operator_lock_scope() as lock_preexisted:
            prior_generation = self._bootstrap_generation(
                lock_preexisted=lock_preexisted
            )
            try:
                self._write_generation_counter(prior_generation + 1)
            except OSError as exc:
                raise LoopHalted(
                    f"clear refused: generation fence could not be published ({exc})"
                ) from exc
            try:
                self._unlink_durable(self._path, missing_ok=True)
            except OSError as exc:
                raise LoopHalted(
                    "clear refused: permit could not be removed; the stop "
                    f"marker was retained ({exc})"
                ) from exc
            try:
                self._unlink_durable(self._marker, missing_ok=True)
            except OSError as exc:
                raise LoopHalted(
                    f"clear incomplete: stop marker could not be removed ({exc})"
                ) from exc
            state = self.read_state()
            if state.running:
                raise LoopHalted(
                    "THE CLEAR DID NOT TAKE: switch still reads as armed after "
                    "generation fence and ordered removal"
                )


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
        try:
            switch.clear()
        except LoopHalted as exc:
            print(str(exc))
            return 4
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
