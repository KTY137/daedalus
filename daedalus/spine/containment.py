"""MIC WRITE CONTAINMENT for candidate code (Windows integrity levels).

DELIBERATELY NOT CALLED A SANDBOX. Cross-vendor review insisted on the name and
was right: "sandbox" invites a reader to assume confidentiality, network limits
and IPC limits, and this mechanism provides none of them. What it provides is
write containment, and the name says exactly that.

WHY IT EXISTS. Every containment this repo had before was written in Python:
path checks, reparse-point detection, no-follow walkers. A day of adversarial
review established the ceiling of that approach -- the "move-in" attack
(``os.rename(primary_checkout, worktree/moved_in)``) involves no reparse point
at all, and the handoff records it as *"open by construction and no reparse
check can ever close it"*. That is true, which is why the boundary has to come
from somewhere other than our own code.

MEASURED ON THIS BOX, NOT ASSUMED. A child launched at Low integrity, with the
worktree labelled Low and handle inheritance OFF:

    REFUSED BY THE KERNEL                    ALLOWED
      write into the primary checkout          write inside the worktree
      delete a file outside                    write %USERPROFILE%\\AppData\\LocalLow
      rename a file outside                    READ the primary checkout
      rmtree the primary checkout              READ the user profile
      MOVE-IN the whole checkout
      create a junction to the checkout
      write through such a junction
      hardlink to a file outside
      write HKCU registry
      spawn a Medium-integrity child
      write through an INHERITED handle

THE INHERITED-HANDLE BYPASS IS REAL, AND CLOSING IT IS LOAD-BEARING. MIC checks
integrity when a handle is OPENED, not on every write through it. Measured both
ways: with ``bInheritHandles=True`` a Low child wrote straight into a
Medium-integrity file through a handle the parent had already opened -- MIC
bypassed completely. With inheritance off, the same attempt fails. So
inheritance is not merely "currently off" here; it is refused structurally, and
a test fails if anyone makes it configurable.

THE CLAIM, AND ITS EXACT LIMITS:

  * WRITE containment: strong. Eleven distinct write/destroy vectors were tried
    and refused, including the move-in that no code check can close.
  * CONFIDENTIALITY: NONE. MIC is a write-UP barrier. A contained candidate may
    read the whole checkout and the user profile. Nothing here prevents
    exfiltration and no caller may read it that way.
  * NOT a write allowlist. ``AppData\\LocalLow`` and other Low-labelled objects
    stay writable. This is damage limitation.
  * NETWORK: unrestricted. A Low process still has a network stack.
  * NAMED PIPES: UNMEASURED. Review declined to call MIC a reliable IPC boundary
    and so does this module -- see :func:`unmeasured_vectors`.

An AppContainer or a restricted token with its own SID would bound network, IPC,
capabilities and confidentiality. That belongs in its own ADR with its own
threat model. This is the first step that is measurably better than nothing.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ContainmentUnavailable",
    "ContainedProcess",
    "label_low_integrity",
    "platform_supported",
    "spawn_contained",
    "unmeasured_vectors",
]

#: The Low mandatory level SID.
LOW_INTEGRITY_SID = "S-1-16-4096"

#: Surfaces this module does NOT claim to have measured. Stated so that silence
#: is never mistaken for coverage.
UNMEASURED = (
    "named pipes: a Medium server with a Low client was not measured, and MIC "
    "is not documented here as a reliable IPC boundary",
    "network egress: a Low process still has a full network stack",
    "reading: MIC is a write-up barrier and does not restrict reads at all",
)


def unmeasured_vectors() -> tuple[str, ...]:
    return UNMEASURED


class ContainmentUnavailable(RuntimeError):
    """Containment could not be established. NEVER downgraded silently.

    A caller that asked for containment and cannot have it must decide what
    that means. This module refuses to decide by handing back an uncontained
    process that looks contained -- which is the failure mode the whole file
    exists to remove.
    """


def platform_supported() -> bool:
    """True only where the measured mechanism exists. No optimism."""
    return os.name == "nt"


if os.name == "nt":  # pragma: no cover - exercised on win32 only
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # EXPLICIT SIGNATURES. Without them ctypes assumes c_int and truncates the
    # 64-bit pseudo-handle from GetCurrentProcess; that surfaces as
    # ERROR_INVALID_HANDLE and reads exactly like "the OS refused us", which
    # cost a debugging round the first time this was measured.
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.c_void_p, ctypes.c_int,
                                           ctypes.c_int,
                                           ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.DuplicateTokenEx.restype = wintypes.BOOL
    _advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD]
    _advapi32.SetTokenInformation.restype = wintypes.BOOL
    _advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                             ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_QUERY = 0x0008
    _TOKEN_ADJUST_DEFAULT = 0x0080
    _TOKEN_ADJUST_SESSIONID = 0x0100
    _SECURITY_IMPERSONATION = 2
    _TOKEN_PRIMARY = 1
    _TOKEN_INTEGRITY_LEVEL = 25
    _SE_GROUP_INTEGRITY = 0x00000020
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _STILL_ACTIVE = 259

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", _SID_AND_ATTRIBUTES)]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]


def _win_error(call: str) -> ContainmentUnavailable:
    code = ctypes.get_last_error() if os.name == "nt" else 0
    return ContainmentUnavailable(f"{call} failed (winerror {code})")


def label_low_integrity(path: str | Path) -> None:
    """Mark ``path`` and everything created under it writable at Low.

    Without this the contained child could not write its own worktree, and
    containment that stops the candidate doing its job is not containment, it
    is an outage. Raises rather than returning a status: a caller who ignored a
    status would run against an unlabelled directory and see mysterious
    permission errors instead of a clear refusal.
    """
    if not platform_supported():
        raise ContainmentUnavailable(
            f"integrity labelling is a win32 mechanism; this is {os.name!r}")
    target = Path(path)
    if not target.is_dir():
        raise ContainmentUnavailable(f"not a directory: {target}")
    proc = subprocess.run(
        ["icacls", str(target), "/setintegritylevel", "(OI)(CI)Low"],
        capture_output=True, encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0:
        raise ContainmentUnavailable(
            f"icacls could not label {target}: "
            f"{(proc.stderr or proc.stdout or '').strip()[-200:]}")


def _low_integrity_token():
    """A primary token identical to ours except Integrity Level = Low.

    Lowering your own token needs no privilege; raising one does. That
    asymmetry is why this works unattended and without admin.
    """
    current = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(),
            _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT
            | _TOKEN_ASSIGN_PRIMARY | _TOKEN_ADJUST_SESSIONID,
            ctypes.byref(current)):
        raise _win_error("OpenProcessToken")
    duplicate = wintypes.HANDLE()
    if not _advapi32.DuplicateTokenEx(current, 0, None, _SECURITY_IMPERSONATION,
                                      _TOKEN_PRIMARY, ctypes.byref(duplicate)):
        raise _win_error("DuplicateTokenEx")
    sid = ctypes.c_void_p()
    if not _advapi32.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid)):
        raise _win_error("ConvertStringSidToSidW")
    label = _TOKEN_MANDATORY_LABEL()
    label.Label.Sid = sid
    label.Label.Attributes = _SE_GROUP_INTEGRITY
    if not _advapi32.SetTokenInformation(duplicate, _TOKEN_INTEGRITY_LEVEL,
                                         ctypes.byref(label),
                                         ctypes.sizeof(label)):
        raise _win_error("SetTokenInformation")
    return duplicate


@dataclass
class ContainedProcess:
    """A running Low-integrity child. Deliberately a small surface."""

    handle: int
    thread: int
    pid: int

    def wait(self, timeout_s: float = 900.0) -> int:
        _kernel32.WaitForSingleObject(self.handle, int(timeout_s * 1000))
        code = wintypes.DWORD()
        _kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code))
        if code.value == _STILL_ACTIVE:
            self.kill()
            return 124
        return int(code.value)

    def kill(self) -> None:
        try:
            _kernel32.TerminateProcess(self.handle, 1)
        except Exception:                       # noqa: BLE001
            pass

    def close(self) -> None:
        for h in (self.handle, self.thread):
            try:
                _kernel32.CloseHandle(h)
            except Exception:                   # noqa: BLE001
                pass


def spawn_contained(argv, cwd: str | Path,
                    env: dict | None = None) -> ContainedProcess:
    """Start ``argv`` at Low integrity with ``cwd`` as its working directory.

    HANDLE INHERITANCE IS OFF AND IS NOT AN OPTION. There is deliberately no
    parameter for it. MIC authorises a handle when it is OPENED, so a Medium
    parent that leaks an inheritable write handle hands the Low child a way
    straight through the boundary -- measured: with inheritance on, a Low child
    overwrote a Medium-integrity file it could not have opened itself. Making
    that configurable would put the containment one keyword argument away from
    being decorative.

    Raises :class:`ContainmentUnavailable` on any platform or API failure, and
    never falls back to an ordinary spawn.
    """
    if not platform_supported():
        raise ContainmentUnavailable(
            f"low-integrity spawn is a win32 mechanism; this is {os.name!r}")
    if not argv:
        raise ContainmentUnavailable("argv must not be empty")

    token = _low_integrity_token()
    # CreateProcessAsUserW takes ONE command line, not an argv vector, and the
    # callee re-parses it -- so every element is quoted rather than joined.
    cmdline = subprocess.list2cmdline([str(a) for a in argv])
    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    info = _PROCESS_INFORMATION()

    block = None
    flags = _CREATE_NEW_PROCESS_GROUP
    if env is not None:
        # A Low child cannot write %TEMP% (Medium), so a caller that wants a
        # usable child gives it a TEMP inside the labelled worktree.
        items = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        block = ctypes.create_unicode_buffer(items)
        flags |= _CREATE_UNICODE_ENVIRONMENT

    ok = _advapi32.CreateProcessAsUserW(
        token, None, ctypes.create_unicode_buffer(cmdline), None, None,
        False,                                  # bInheritHandles -- see docstring
        flags, block, str(cwd), ctypes.byref(startup), ctypes.byref(info))
    if not ok:
        raise _win_error("CreateProcessAsUserW")
    return ContainedProcess(handle=info.hProcess, thread=info.hThread,
                            pid=int(info.dwProcessId))
