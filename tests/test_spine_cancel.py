# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Cancellation must kill the whole tree, not just the child we hold a handle to.

The discriminating test is ``test_cancel_kills_grandchild``: with the old
``send_signal(SIGINT)`` approach the grandchild keeps appending to its file
after the caller believes the attempt was cancelled.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from daedalus.spine.cancel import (
    BACKEND,
    CancellationUnavailable,
    ManagedProcess,
    PosixSessionBackend,
    WindowsJobBackend,
    console_ctrl_available,
    select_backend,
)

_IS_WINDOWS = os.name == "nt"

# A child that ignores the graceful stage, so only the container kill can stop it.
_DEAF_PREAMBLE = """
import os, signal, sys, time

def _deaf(*_args):
    return None

for _name in ("SIGBREAK", "SIGINT", "SIGTERM"):
    _sig = getattr(signal, _name, None)
    if _sig is not None:
        try:
            signal.signal(_sig, _deaf)
        except (ValueError, OSError):
            pass
"""

_GRANDCHILD_SRC = _DEAF_PREAMBLE + """
target = sys.argv[1]
with open(target + ".gcpid", "w") as fh:
    fh.write(str(os.getpid()))
with open(target, "a") as fh:
    while True:
        fh.write("g")
        fh.flush()
        time.sleep(0.05)
"""

_PARENT_SRC = _DEAF_PREAMBLE + """
import subprocess

target = sys.argv[1]
grandchild = sys.argv[2]
with open(target + ".ppid", "w") as fh:
    fh.write(str(os.getpid()))
subprocess.Popen([sys.executable, grandchild, target])
while True:
    time.sleep(0.05)
"""

# Handles the graceful stage and exits with a distinctive code.
_POLITE_SRC = """
import os, signal, sys, time

def _stop(*_args):
    os._exit(7)

for _name in ("SIGBREAK", "SIGINT", "SIGTERM"):
    _sig = getattr(signal, _name, None)
    if _sig is not None:
        try:
            signal.signal(_sig, _stop)
        except (ValueError, OSError):
            pass

ready = sys.argv[1]
with open(ready, "w") as fh:
    fh.write("up")
while True:
    time.sleep(0.05)
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def _wait_until(predicate, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _pid_alive(pid: int) -> bool:
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _size_is_stable(path: Path, settle: float = 0.6) -> bool:
    before = path.stat().st_size
    time.sleep(settle)
    return path.stat().st_size == before


def _start_tree(tmp_path: Path) -> tuple[ManagedProcess, Path, int, int]:
    grandchild = _write(tmp_path, "grandchild.py", _GRANDCHILD_SRC)
    parent = _write(tmp_path, "parent.py", _PARENT_SRC)
    target = tmp_path / "ticks.txt"

    proc = ManagedProcess([sys.executable, str(parent), str(target), str(grandchild)])
    ppid_file = tmp_path / "ticks.txt.ppid"
    gcpid_file = tmp_path / "ticks.txt.gcpid"
    ok = _wait_until(
        lambda: ppid_file.exists()
        and gcpid_file.exists()
        and target.exists()
        and target.stat().st_size > 2,
        timeout=8.0,
    )
    if not ok:
        proc.close(grace_s=0.0)
        pytest.fail("child tree did not reach a running, writing state")
    return (
        proc,
        target,
        int(ppid_file.read_text().strip()),
        int(gcpid_file.read_text().strip()),
    )


# --------------------------------------------------------------------------
# platform split
# --------------------------------------------------------------------------


def test_backend_selection_is_explicit_per_platform():
    assert select_backend("win32") is WindowsJobBackend
    assert select_backend("linux") is PosixSessionBackend
    assert select_backend("darwin") is PosixSessionBackend
    assert select_backend("freebsd13") is PosixSessionBackend
    assert BACKEND is select_backend(sys.platform)


def test_backend_names_are_distinct():
    assert WindowsJobBackend.name != PosixSessionBackend.name


def test_empty_argv_rejected():
    with pytest.raises(ValueError):
        ManagedProcess([])


# --------------------------------------------------------------------------
# normal lifecycle
# --------------------------------------------------------------------------


def test_fast_exit_reports_returncode():
    with ManagedProcess([sys.executable, "-c", "import sys; sys.exit(3)"]) as proc:
        assert proc.wait(timeout=10) == 3
        assert proc.returncode == 3


def test_stdout_is_capturable():
    with ManagedProcess(
        [sys.executable, "-c", "print('hello-spine')"],
        stdout=subprocess.PIPE,
    ) as proc:
        out, _ = proc.process.communicate(timeout=10)
    assert b"hello-spine" in out


def test_cancel_on_exited_process_is_noop():
    with ManagedProcess([sys.executable, "-c", "import sys; sys.exit(5)"]) as proc:
        assert proc.wait(timeout=10) == 5
        result = proc.cancel(grace_s=1.0)
        assert result.stage == "already_exited"
        assert result.signal_sent is False
        assert result.graceful is False
        assert result.returncode == 5
        # idempotent
        assert proc.cancel(grace_s=1.0).stage == "already_exited"


def test_close_is_idempotent():
    proc = ManagedProcess([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait(timeout=10)
    assert proc.close() is None  # nothing left to cancel
    assert proc.close() is None


# --------------------------------------------------------------------------
# the defect: grandchildren must die too
# --------------------------------------------------------------------------


def test_cancel_kills_grandchild(tmp_path):
    proc, target, parent_pid, grandchild_pid = _start_tree(tmp_path)
    try:
        assert _pid_alive(grandchild_pid), "grandchild should be running before cancel"
        result = proc.cancel(grace_s=0.5)

        assert result.stage == "tree_kill"
        assert result.graceful is False
        assert _wait_until(lambda: not _pid_alive(parent_pid), 3.0), "parent survived"
        assert _wait_until(
            lambda: not _pid_alive(grandchild_pid), 3.0
        ), "grandchild survived cancellation (leaked tree)"
        # Disk truth: nothing is still appending.
        assert _size_is_stable(target), "a leaked writer is still touching the file"
    finally:
        proc.close(grace_s=0.0)


def test_context_manager_exit_kills_tree(tmp_path):
    proc, target, parent_pid, grandchild_pid = _start_tree(tmp_path)
    with proc:
        assert _pid_alive(grandchild_pid)
    assert _wait_until(lambda: not _pid_alive(parent_pid), 3.0)
    assert _wait_until(lambda: not _pid_alive(grandchild_pid), 3.0)
    assert _size_is_stable(target)


def test_grace_timeout_escalates(tmp_path):
    """The child ignores the graceful stage; stage 2 must still stop it."""
    proc, _target, parent_pid, grandchild_pid = _start_tree(tmp_path)
    try:
        started = time.monotonic()
        result = proc.cancel(grace_s=0.4)
        elapsed = time.monotonic() - started
        assert result.stage == "tree_kill"
        assert elapsed >= 0.4, "grace window was not honoured"
        assert elapsed < 8.0
        assert not _pid_alive(grandchild_pid) or _wait_until(
            lambda: not _pid_alive(grandchild_pid), 3.0
        )
        assert _wait_until(lambda: not _pid_alive(parent_pid), 3.0)
    finally:
        proc.close(grace_s=0.0)


@pytest.mark.skipif(
    not console_ctrl_available(),
    reason="no console attached: CTRL_BREAK_EVENT cannot be delivered",
)
def test_graceful_stage_when_child_handles_the_signal(tmp_path):
    script = _write(tmp_path, "polite.py", _POLITE_SRC)
    ready = tmp_path / "ready.txt"
    with ManagedProcess([sys.executable, str(script), str(ready)]) as proc:
        assert _wait_until(ready.exists, timeout=8.0), "child never started"
        result = proc.cancel(grace_s=5.0)
        assert result.signal_sent is True
        assert result.stage == "graceful"
        assert result.graceful is True
        assert result.returncode == 7


# --------------------------------------------------------------------------
# fail-closed containment
# --------------------------------------------------------------------------


class _UncontainableBackend:
    """Wraps the real backend but refuses to complete containment."""

    name = "uncontainable"

    def __init__(self) -> None:
        self._inner = BACKEND()
        self.observed_pid: int | None = None

    def popen_kwargs(self):
        return self._inner.popen_kwargs()

    def before_spawn(self):
        self._inner.before_spawn()

    def after_spawn(self, process):
        self.observed_pid = process.pid
        raise CancellationUnavailable("containment refused")

    def signal_group(self, process):
        return self._inner.signal_group(process)

    def kill_tree(self, process):
        self._inner.kill_tree(process)

    def release(self):
        self._inner.release()


def test_spawn_fails_closed_when_containment_fails():
    backend = _UncontainableBackend()
    with pytest.raises(CancellationUnavailable):
        ManagedProcess(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            backend=backend,
        )
    assert backend.observed_pid is not None
    assert _wait_until(lambda: not _pid_alive(backend.observed_pid), 5.0), (
        "a process we cannot contain was left running"
    )
