# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Reliable cancellation of child process *trees*.

``Popen.send_signal(signal.SIGINT)`` does not cancel a tree on win32: it is
delivered (via the CRT console machinery) to the immediate child only, so
grandchildren survive and keep writing files after the caller believes the
attempt was cancelled.  A leaked writer racing a "cancelled" attempt is a
correctness hazard, not untidiness -- it can corrupt the very artifact the
cancelled attempt was judged on.

The cancellation ladder here has two verified stages:

1. ``graceful``  -- ask the whole process group to stop.
   win32: ``GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pgid)``;
   posix: ``killpg(pgid, SIGINT)``.
2. ``tree_kill`` -- if anything is still alive after the grace window, destroy
   the container.  win32: ``TerminateJobObject``; posix: ``killpg(SIGKILL)``.

On win32 containment is a Job Object carrying
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``.  The child is created *suspended* and
resumed only after ``AssignProcessToJobObject`` succeeded, so there is no
window in which the child can spawn a grandchild outside the job.  If the job
cannot be created, configured, or assigned, spawning fails closed
(``CancellationUnavailable``) rather than handing back a process whose tree we
could not later kill.

Pure ctypes -- no pywin32.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "CancellationUnavailable",
    "CancelResult",
    "ManagedProcess",
    "PosixSessionBackend",
    "WindowsJobBackend",
    "cancel_all_managed",
    "console_ctrl_available",
    "live_managed_processes",
    "select_backend",
    "BACKEND",
    "BACKEND_NAME",
    "DEFAULT_GRACE_S",
]

DEFAULT_GRACE_S = 3.0

STAGE_NOT_STARTED = "not_started"
STAGE_ALREADY_EXITED = "already_exited"
STAGE_GRACEFUL = "graceful"
STAGE_TREE_KILL = "tree_kill"


class CancellationUnavailable(RuntimeError):
    """Raised when a process cannot be spawned inside a killable container.

    Fail-closed: better to refuse the launch than to run work we cannot cancel.
    """


@dataclass(frozen=True)
class CancelResult:
    """Which rung of the ladder actually stopped the tree."""

    stage: str
    graceful: bool
    signal_sent: bool
    returncode: int | None
    elapsed_s: float

    @property
    def killed(self) -> bool:
        return self.stage in (STAGE_GRACEFUL, STAGE_TREE_KILL)


# --------------------------------------------------------------------------
# win32 backend
# --------------------------------------------------------------------------

_IS_WINDOWS = os.name == "nt"

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CTRL_BREAK_EVENT = 1

_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_RESUME_THREAD_FAILED = 0xFFFFFFFF


if _IS_WINDOWS:  # pragma: no branch - platform split is exercised via select_backend
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    # Explicit prototypes: without them ctypes truncates HANDLEs to int on x64.
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenThread.restype = wintypes.HANDLE
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32First.restype = wintypes.BOOL
    _kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32Next.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    _kernel32.GetConsoleProcessList.argtypes = [
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]
    _kernel32.GetConsoleProcessList.restype = wintypes.DWORD
else:  # pragma: no cover - selected by platform
    _kernel32 = None


def console_ctrl_available() -> bool:
    """Whether stage 1 (``CTRL_BREAK_EVENT``) can be delivered at all.

    ``GenerateConsoleCtrlEvent`` needs the caller to own a console; a process
    started without one (pythonw, a service, some IDE runners) can only ever
    reach stage 2.  Callers that assert on the graceful stage must gate on this.
    """
    if not _IS_WINDOWS:
        return True
    buffer = (wintypes.DWORD * 1)()
    return _kernel32.GetConsoleProcessList(buffer, 1) > 0


def _win_error(call: str) -> CancellationUnavailable:
    code = ctypes.get_last_error()
    return CancellationUnavailable(f"{call} failed (GetLastError={code})")


def _resume_all_threads(pid: int) -> int:
    """Resume every thread of ``pid``; returns how many resume calls succeeded.

    ``Popen`` closes the initial thread handle before returning, so the only
    way back to a ``CREATE_SUSPENDED`` child is a thread snapshot.
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INVALID_HANDLE_VALUE:
        raise _win_error("CreateToolhelp32Snapshot")
    resumed = 0
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(_THREADENTRY32)
        more = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                )
                if thread:
                    try:
                        while True:
                            previous = _kernel32.ResumeThread(thread)
                            if previous == _RESUME_THREAD_FAILED:
                                break
                            resumed += 1
                            if previous <= 1:
                                break
                    finally:
                        _kernel32.CloseHandle(thread)
            entry.dwSize = ctypes.sizeof(_THREADENTRY32)
            more = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return resumed


class WindowsJobBackend:
    """Contain the tree in a Job Object that dies with its handle."""

    name = "windows-job"

    def __init__(self) -> None:
        if not _IS_WINDOWS:  # pragma: no cover - guarded by select_backend
            raise CancellationUnavailable("WindowsJobBackend requires win32")
        self._job: int | None = None

    def popen_kwargs(self) -> dict[str, Any]:
        return {"creationflags": CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP}

    def before_spawn(self) -> None:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise _win_error("CreateJobObjectW")
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            _kernel32.CloseHandle(job)
            raise _win_error("SetInformationJobObject")
        self._job = job

    def after_spawn(self, process: subprocess.Popen) -> None:
        handle = _kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid
        )
        if not handle:
            raise _win_error("OpenProcess")
        try:
            if not _kernel32.AssignProcessToJobObject(self._job, handle):
                raise _win_error("AssignProcessToJobObject")
        finally:
            _kernel32.CloseHandle(handle)
        # Only now is it safe to let the child run: anything it spawns from
        # here on is born inside the job.
        if _resume_all_threads(process.pid) == 0:
            raise CancellationUnavailable(
                f"no suspended thread resumed for pid {process.pid}"
            )

    def signal_group(self, process: subprocess.Popen) -> bool:
        return bool(_kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, process.pid))

    def kill_tree(self, process: subprocess.Popen) -> None:
        if self._job is not None:
            _kernel32.TerminateJobObject(self._job, 1)
        else:  # pragma: no cover - only after release()
            process.kill()

    def release(self) -> None:
        if self._job is not None:
            # KILL_ON_JOB_CLOSE: closing the last handle destroys any survivor.
            _kernel32.CloseHandle(self._job)
            self._job = None


# --------------------------------------------------------------------------
# posix backend
# --------------------------------------------------------------------------


class PosixSessionBackend:
    """Contain the tree in its own session/process group."""

    name = "posix-session"

    def popen_kwargs(self) -> dict[str, Any]:
        return {"start_new_session": True}

    def before_spawn(self) -> None:
        return None

    def after_spawn(self, process: subprocess.Popen) -> None:
        return None

    @staticmethod
    def _pgid(process: subprocess.Popen) -> int:
        try:
            return os.getpgid(process.pid)
        except (OSError, AttributeError):
            return process.pid

    def signal_group(self, process: subprocess.Popen) -> bool:
        try:
            os.killpg(self._pgid(process), signal.SIGINT)
        except (OSError, AttributeError):
            return False
        return True

    def kill_tree(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(self._pgid(process), signal.SIGKILL)
        except (OSError, AttributeError):
            try:
                process.kill()
            except OSError:
                pass

    def release(self) -> None:
        return None


def select_backend(platform: str) -> type:
    """Pick the containment backend for a platform string (``sys.platform``).

    Split out as a pure function so the platform decision is assertable from
    either OS without spawning anything.
    """
    return WindowsJobBackend if platform.startswith("win") else PosixSessionBackend


BACKEND = select_backend(sys.platform)
BACKEND_NAME = BACKEND.name


# --------------------------------------------------------------------------
# live-process registry
# --------------------------------------------------------------------------
#
# WHY A REGISTRY AND NOT JUST THE CANCEL TOKEN. The cancel token reaches a
# child only if every layer between the loop driver and the spawn remembered to
# thread it through. The kill switch may not depend on that: a driver that
# forgot one `cancel=` argument would leave a pytest tree or a vendor CLI
# running after the operator pulled the plug, and "the loop stopped but its
# children did not" is not stopping. This is the sweep of last resort --
# :func:`daedalus.spine.killswitch.KillSwitch.stop_children` calls it on every
# trip.
#
# A WeakSet, so registration cannot keep a finished process object alive and
# cannot leak; entries are also discarded eagerly on close().

_LIVE: "weakref.WeakSet[ManagedProcess]" = weakref.WeakSet()
_LIVE_LOCK = threading.Lock()


def live_managed_processes() -> list["ManagedProcess"]:
    """Snapshot of every contained child alive in THIS interpreter."""
    with _LIVE_LOCK:
        return [p for p in _LIVE if p.returncode is None]


def cancel_all_managed(grace_s: float = 0.0) -> list[CancelResult]:
    """Cancel every live :class:`ManagedProcess` tree. Returns what each did.

    Never raises: one wedged child must not stop the rest from being killed.
    The default grace is 0.0, not :data:`DEFAULT_GRACE_S` -- this is the
    emergency path, where the whole point is to be fast, and a child that would
    have exited politely within three seconds is no less dead for being killed
    now.
    """
    results: list[CancelResult] = []
    for proc in live_managed_processes():
        try:
            results.append(proc.cancel(grace_s=grace_s))
        except Exception:  # noqa: BLE001 - reported by absence, never propagated
            continue
    return results


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


class ManagedProcess:
    """A child process whose whole tree can be cancelled.

    Use as a context manager; leaving the block cancels anything still running
    and then releases the container.  Dropping the last reference also releases
    the container, which on win32 kills any survivor -- an orphaned
    ``ManagedProcess`` must not leave writers behind.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        backend: Any = None,
    ) -> None:
        if not argv:
            raise ValueError("argv must not be empty")
        self._argv = [str(part) for part in argv]
        self._backend = backend if backend is not None else BACKEND()
        self._process: subprocess.Popen | None = None
        self._released = False

        self._backend.before_spawn()
        try:
            self._process = subprocess.Popen(
                self._argv,
                cwd=str(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                **self._backend.popen_kwargs(),
            )
        except BaseException:
            self._backend.release()
            self._released = True
            raise

        try:
            self._backend.after_spawn(self._process)
        except BaseException:
            # A child we cannot contain must never be left running.
            try:
                self._process.kill()
                self._process.wait(timeout=5)
            except Exception:
                pass
            self._backend.release()
            self._released = True
            raise

        # Registered ONLY here: after containment is established. A process we
        # failed to contain is killed above and must never appear in a registry
        # that promises "cancelling this reaps its tree".
        with _LIVE_LOCK:
            _LIVE.add(self)

    # -- introspection ----------------------------------------------------

    @property
    def pid(self) -> int:
        assert self._process is not None
        return self._process.pid

    @property
    def process(self) -> subprocess.Popen:
        """The underlying ``Popen`` (for stdio); do not signal it directly."""
        assert self._process is not None
        return self._process

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def returncode(self) -> int | None:
        if self._process is None:
            return None
        return self._process.poll()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        assert self._process is not None
        return self._process.wait(timeout=timeout)

    # -- cancellation -----------------------------------------------------

    def cancel(self, grace_s: float = DEFAULT_GRACE_S) -> CancelResult:
        """Stop the tree, escalating from a group signal to a container kill.

        Idempotent: cancelling an already-exited process is a no-op that
        reports ``already_exited``.
        """
        started = time.monotonic()
        if self._process is None:  # pragma: no cover - constructor raises first
            return CancelResult(STAGE_NOT_STARTED, False, False, None, 0.0)

        if self._process.poll() is not None:
            return CancelResult(
                STAGE_ALREADY_EXITED,
                False,
                False,
                self._process.returncode,
                time.monotonic() - started,
            )

        signal_sent = False
        try:
            signal_sent = bool(self._backend.signal_group(self._process))
        except OSError:
            signal_sent = False

        if signal_sent and grace_s > 0:
            try:
                self._process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                pass

        if self._process.poll() is not None:
            return CancelResult(
                STAGE_GRACEFUL,
                True,
                signal_sent,
                self._process.returncode,
                time.monotonic() - started,
            )

        self._backend.kill_tree(self._process)
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - container kill is final
            pass
        return CancelResult(
            STAGE_TREE_KILL,
            False,
            signal_sent,
            self._process.returncode,
            time.monotonic() - started,
        )

    def close(self, grace_s: float = DEFAULT_GRACE_S) -> CancelResult | None:
        """Cancel if still running, then release the container. Idempotent."""
        if self._released:
            return None
        result = None
        try:
            if self._process is not None and self._process.poll() is None:
                result = self.cancel(grace_s=grace_s)
        finally:
            self._backend.release()
            self._released = True
            with _LIVE_LOCK:
                _LIVE.discard(self)
        return result

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "ManagedProcess":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - GC timing
        try:
            self.close(grace_s=0.0)
        except Exception:
            pass
