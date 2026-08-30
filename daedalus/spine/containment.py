# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
worktree labelled Low:

    REFUSED BY THE KERNEL                    ALLOWED
      write into the primary checkout          write inside the worktree
      delete a file outside                    write %USERPROFILE%\\AppData\\LocalLow
      rename a file outside                    READ the primary checkout
      rmtree the primary checkout              READ the user profile
      MOVE-IN the whole checkout               APPEND to its own Low log
      create a junction to the checkout
      write through such a junction
      hardlink to a file outside
      write HKCU registry
      spawn a Medium-integrity child
      write through an UNBOUNDED inherited handle

THE LOAD-BEARING INVARIANT
--------------------------
    NO CAPABILITY CROSSES THE BOUNDARY THAT THE LOW CHILD COULD NOT HAVE
    OBTAINED ITSELF.

This is sharper than the rule it replaces ("handle inheritance is off, full
stop"), and it is the rule the code now enforces. The old rule was a proxy for
this one, chosen because the measured attack -- ``bInheritHandles=True`` and a
Medium-integrity file handle the parent had already opened, through which a Low
child wrote a file it could not itself have opened -- is a violation of it. MIC
authorises a handle when it is OPENED, not on every write through it, so an
unbounded inherited handle is an authorisation laundered across the boundary.

BOUNDED INHERITANCE, AND WHY IT IS NOT A WEAKENING
--------------------------------------------------
The gate has to execute candidate code AND capture its output. Output cannot go
to a pipe: the caller polls a cancel token instead of draining, so a chatty run
deadlocks. Output therefore goes to a FILE outside the worktree, and a file
redirection on win32 IS an inherited handle. The alternatives were considered
and rejected: a wrapper process does not remove inheritance, it moves it from
the parent to the wrapper; leaving the gate uncontained makes the boundary
worthless, since the gate is the point at which candidate code actually runs.

So inheritance is bounded rather than forbidden:

  * EXACTLY ONE handle crosses, selected by name via
    ``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``. Every other handle in this process
    -- inheritable or not -- is invisible to the child. MEASURED: a deliberately
    inheritable handle on a Medium file, left off the allowlist, came back
    ``ERROR_INVALID_HANDLE`` (6) in the child and the file was unchanged.
  * That handle carries ``FILE_APPEND_DATA | FILE_READ_ATTRIBUTES |
    SYNCHRONIZE`` and NOTHING else -- see :data:`WHY_READ_ATTRIBUTES` for the
    one right the ruling did not name and the measurement that forced it. The
    handle is opened with ``NtCreateFile`` rather than ``CreateFileW`` because
    CreateFileW adds rights of its own accord (measured: ``0x00100084`` handed
    back when ``0x00100004`` was requested), and a mask you did not choose
    cannot be checked as an equality. NtCreateFile grants exactly what is
    asked. MEASURED IN THE CHILD, with the mask actually shipped: read ->
    ``ERROR_ACCESS_DENIED`` (5), ``SetEndOfFile`` -> ``ERROR_ACCESS_DENIED``
    (5).
  * The target must be a LOW-labelled file, and that is checked ON THE OPENED
    HANDLE, never on the path -- otherwise a reparse point or a swap between
    check and open reopens the whole bypass. An unlabelled file is implicitly
    Medium and is REFUSED.
  * The share mode excludes ``FILE_SHARE_DELETE`` and ``FILE_SHARE_WRITE``.
    Without that the child DELETES its own log by path -- measured, the first
    guarded run destroyed the file -- because a Low-labelled file is fully
    writable by a Low process, and could then replace it with fabricated gate
    output. With it: ``PermissionError``.
  * ``bInheritHandles=True`` is written as ``allowlist is not None``. There is
    no state in which inheritance is on and the allowlist is off, because they
    are the same expression.

A handle to a Low-labelled, append-only log does not violate the invariant: a
Low child could have opened that file itself. A handle to a Medium file does,
and is refused.

THE CLAIM, AND ITS EXACT LIMITS:

  * WRITE containment: strong. Eleven distinct write/destroy vectors were tried
    and refused, including the move-in that no code check can close.
  * CONFIDENTIALITY: NONE. MIC is a write-UP barrier. A contained candidate may
    read the whole checkout and the user profile. Nothing here prevents
    exfiltration and no caller may read it that way.
  * NOT a write allowlist. ``AppData\\LocalLow`` and other Low-labelled objects
    stay writable. This is damage limitation.
  * NETWORK: unrestricted. A Low process still has a network stack, and NO Job
    Object limit can change that -- see :data:`JOB_LIMITS_DO_NOT_COVER`.
  * NAMED PIPES: UNMEASURED. Review declined to call MIC a reliable IPC boundary
    and so does this module -- see :func:`unmeasured_vectors`, which GREW when
    bounded inheritance landed and must never shrink silently.

THE JOB OBJECT: A RESOURCE BOUND, NOT A SECOND SECURITY BOUNDARY
----------------------------------------------------------------
MIC bounds what the child may WRITE. It says nothing about how much the child
may CONSUME, and a gate that a candidate can wedge by forking is a denial of
service against the loop even though not one byte escaped. So the job carries
caps as well as a lifetime (:func:`_create_job`):

  * ``KILL_ON_JOB_CLOSE`` -- the tree dies with the last handle, so a leaked
    test process cannot outlive the attempt and keep writing into a worktree
    that is about to be removed.
  * ``ACTIVE_PROCESS`` -- :data:`JOB_ACTIVE_PROCESS_LIMIT` concurrent
    processes. Past it ``CreateProcess`` IN THE CHILD fails with
    ``ERROR_NOT_ENOUGH_QUOTA`` (1816); the job is not killed, so a fork bomb
    stalls instead of taking the box.
  * ``JOB_MEMORY`` -- :data:`JOB_MEMORY_LIMIT_BYTES` of committed memory across
    the WHOLE tree, not per process, because per-process caps compose badly
    with a process cap: N children each just under the line is still N times
    the line.
  * ``DIE_ON_UNHANDLED_EXCEPTION`` -- a crashing candidate dies instead of
    raising a Windows Error Reporting dialog that no one is there to dismiss,
    which on an unattended gate is an infinite hang dressed as a slow test.
  * BREAKAWAY IS DENIED BY OMISSION. Neither ``BREAKAWAY_OK`` nor
    ``SILENT_BREAKAWAY_OK`` is set, so ``CREATE_BREAKAWAY_FROM_JOB`` in the
    child fails. That is the default, and defaults are exactly what drift, so
    the read-back below ASSERTS their absence rather than assuming it.

EVERY ONE OF THOSE IS READ BACK out of the kernel with
``QueryInformationJobObject`` and compared before a child is allowed to start.
``SetInformationJobObject`` returning TRUE is a claim; ``LimitFlags`` coming
back out of the kernel is a fact, and only facts reach the attestation.

WHAT CONTAINMENT DOES *NOT* COVER, STATED SO SILENCE IS NOT MISTAKEN FOR COVER
-----------------------------------------------------------------------------
Only the GATE CHILD is contained. The harness process that spawns it, the git
calls it makes, and ``attempt.py``'s ``_persist`` all run at the invoking user's
full integrity, by construction -- something has to hold the Medium handles.

That matters for one race in particular. ``daedalus.primary_tree``'s fence
resolves a path and then writes to it, and a junction swapped in between those
two steps is NOT closed by Python; nothing written in Python can close it. MIC
containment of the child is the mechanism that actually bounds that class,
because the swap only buys the attacker a write the KERNEL will still refuse at
Low integrity. It bounds it; it does not close it, and it does nothing at all
for the uncontained harness code on the other side of the boundary.

An AppContainer or a restricted token with its own SID would bound network, IPC,
capabilities and confidentiality. That belongs in its own ADR with its own
threat model. This is the first step that is measurably better than nothing.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ContainedProcess",
    "ContainmentAttestation",
    "ContainmentUnavailable",
    "JOB_ACTIVE_PROCESS_LIMIT",
    "JOB_LIMITS_DO_NOT_COVER",
    "JOB_MEMORY_LIMIT_BYTES",
    "JobLimits",
    "LOW_APPEND_ACCESS",
    "LOW_INTEGRITY_SID",
    "LowIntegrityLog",
    "integrity_label",
    "job_accounting",
    "label_low_integrity",
    "label_low_integrity_file",
    "open_low_append_log",
    "platform_supported",
    "spawn_contained",
    "unmeasured_vectors",
]

#: The Low mandatory level SID.
LOW_INTEGRITY_SID = "S-1-16-4096"

_FILE_APPEND_DATA = 0x0004
_FILE_READ_ATTRIBUTES = 0x0080
_SYNCHRONIZE = 0x00100000

#: The ONLY access mask a handle may carry across the boundary. Append, so the
#: child cannot rewrite what it already wrote; SYNCHRONIZE, so it can wait on
#: its own I/O; READ_ATTRIBUTES, for the measured reason in
#: :data:`WHY_READ_ATTRIBUTES`. Nothing else -- no READ_DATA, no WRITE_DATA, no
#: WRITE_ATTRIBUTES, no EA, no EXECUTE, no DELETE, no READ_CONTROL, no
#: WRITE_DAC, no WRITE_OWNER. Checked as an EQUALITY, so an addition cannot
#: slip in unnoticed.
LOW_APPEND_ACCESS = (_FILE_APPEND_DATA | _FILE_READ_ATTRIBUTES
                     | _SYNCHRONIZE)                          # 0x00100084

#: A DEVIATION FROM THE LETTER OF THE RULING, AND WHY IT IS NOT ONE FROM ITS
#: SUBSTANCE. The ruling said "APPEND and SYNCHRONIZE rights only". That mask
#: was implemented, measured, and BLINDS THE GATE: ``os.fstat(1)`` needs
#: FILE_READ_ATTRIBUTES, and when it raises, pytest concludes fd 1 is invalid
#: and redirects all output to ``os.devnull``. Measured with the strict mask --
#: ``python -m pytest -q`` exited 0 and produced ZERO bytes, i.e. a gate that
#: reports PASS with no evidence whatsoever. That is the "empty green" this
#: project forbids, bought with a right that buys the child nothing:
#: FILE_READ_ATTRIBUTES is a READ right, MIC does not restrict reads at all
#: (a limit this module already states and a test already pins), and the target
#: is a Low-labelled file the child could open for itself. So it does not
#: violate "no capability crosses the boundary that the Low child could not
#: have obtained itself" -- and blinding our own evidence channel to avoid it
#: would have been the worse trade. Measured with the mask below: reading and
#: truncating through the handle are still refused.
#: Concurrent processes allowed inside the gate's job. MEASURED, not guessed: a
#: real contained ``python -m pytest`` of this repo's own tests was run with the
#: job's accounting counters read back afterwards, and the number below is that
#: measured peak with a wide margin over it. See ``JobLimits.measured_note``.
#:
#: The cap is a CEILING ON DAMAGE, not a scheduling policy. Set it near a real
#: run's peak and an unlucky-but-honest candidate fails its gate for a reason
#: that has nothing to do with its patch -- which this repo has already shipped
#: once, with ``pytest docs/THAT.md``, and calls fail-closed-but-useless.
JOB_ACTIVE_PROCESS_LIMIT = 96

#: Committed memory for the WHOLE job, in bytes. Same reasoning: far above a
#: measured real run, far below "this box stops responding".
JOB_MEMORY_LIMIT_BYTES = 4 * 1024 * 1024 * 1024

#: What the job caps DO NOT do. Named because a resource limit reads, to a
#: hurried reader, like a security boundary, and these three are the ones
#: somebody will assume are covered.
JOB_LIMITS_DO_NOT_COVER = (
    "network egress: there is no Job Object limit for it. Codex CLI's Windows "
    "sandbox closes network with a FIREWALL RULE SCOPED TO A DEDICATED USER "
    "PRINCIPAL, not with the job -- a different mechanism with its own "
    "privileged setup step. Unimplemented here, and so still unrestricted",
    "confidentiality: the caps bound consumption, not reads. MIC is a write-up "
    "barrier and the job is a resource bound; neither stops a Low child "
    "reading the checkout or the user profile",
    "disk: JOB_OBJECT_LIMIT_JOB_MEMORY is COMMITTED MEMORY. A candidate that "
    "fills the volume inside its own Low-labelled worktree or temp directory "
    "is bounded by neither the job nor MIC",
    "the harness itself: only the gate CHILD is in the job. This process, its "
    "git calls and attempt.py's _persist are uncontained by construction",
)

WHY_READ_ATTRIBUTES = (
    "FILE_READ_ATTRIBUTES is granted because os.fstat(1) needs it and pytest "
    "silently redirects all output to os.devnull when it fails -- measured: "
    "exit 0 with zero bytes captured. It is a read right on a Low-labelled "
    "file the contained child could have opened itself, so no capability "
    "crosses that it did not already have.")

#: Surfaces this module does NOT claim to have measured. Stated so that silence
#: is never mistaken for coverage. This tuple GROWS when a mechanism lands; a
#: test fails if the three original entries ever disappear.
UNMEASURED = (
    "named pipes: a Medium server with a Low client was not measured, and MIC "
    "is not documented here as a reliable IPC boundary",
    "network egress: a Low process still has a full network stack",
    "reading: MIC is a write-up barrier and does not restrict reads at all",
    "log path disclosure: the child can recover the log's full path from the "
    "inherited handle via GetFinalPathNameByHandle (measured, it works). The "
    "path is disclosed; the file is not reachable by any other route while the "
    "handle is open, because the share mode refuses a second opener",
    "the log AFTER the run: once this process closes the inherited handle the "
    "share-mode guard is gone. The child is dead by then (Job Object, "
    "KILL_ON_JOB_CLOSE) and the scratch tree is removed through the guarded "
    "walker, but a surviving Low writer racing that window was not measured",
    "handle-value reuse: the allowlist is verified immediately before "
    "CreateProcessAsUserW, on handles this process owns and does not close. A "
    "second thread closing one of them inside that window, and the value being "
    "reissued for another object, is not defended against -- spawning is "
    "assumed single-threaded",
    "GrantedAccess is the kernel's accounting of OUR handle. That the child's "
    "copy carries the same mask was measured by OPERATION (read and truncate "
    "were refused in the child), not proven for every operation class",
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
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

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
    _advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD]
    _advapi32.SetTokenInformation.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
    _advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.GetSecurityInfo.restype = wintypes.DWORD
    _advapi32.GetSecurityDescriptorSacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    _advapi32.GetSecurityDescriptorSacl.restype = wintypes.BOOL
    _advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.GetAce.restype = wintypes.BOOL

    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                             ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t)]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,
                                                   wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD,
                                                   wintypes.DWORD]
    _kernel32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    _ntdll.NtCreateFile.restype = ctypes.c_long
    _ntdll.NtQueryObject.restype = ctypes.c_long

    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_QUERY = 0x0008
    _TOKEN_ADJUST_DEFAULT = 0x0080
    _TOKEN_ADJUST_SESSIONID = 0x0100
    _SECURITY_IMPERSONATION = 2
    _TOKEN_PRIMARY = 1
    _TOKEN_INTEGRITY_LEVEL = 25
    _SE_GROUP_INTEGRITY = 0x00000020
    _CREATE_SUSPENDED = 0x00000004
    _CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    _STARTF_USESTDHANDLES = 0x00000100
    _STILL_ACTIVE = 259
    _CTRL_BREAK_EVENT = 1

    _PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002

    _JobObjectBasicAccountingInformation = 1
    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    # NEVER SET. Named so that the read-back can assert their ABSENCE: with
    # either of these a child may call CreateProcess with
    # CREATE_BREAKAWAY_FROM_JOB and step outside every limit above, which would
    # make the whole job decorative. Absence is the Windows default, and a
    # default is precisely the kind of thing that changes without telling you.
    _JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
    _JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000

    _FILE_SHARE_READ = 0x00000001
    _READ_CONTROL = 0x00020000
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80

    # NtCreateFile
    _OBJ_INHERIT = 0x00000002
    _OBJ_CASE_INSENSITIVE = 0x00000040
    _FILE_OPEN = 1
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_NON_DIRECTORY_FILE = 0x00000040

    _ObjectBasicInformation = 0
    _FileIdInfo = 18
    _LABEL_SECURITY_INFORMATION = 0x00000010
    _SE_FILE_OBJECT = 1
    _SYSTEM_MANDATORY_LABEL_ACE_TYPE = 0x11

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

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", _STARTUPINFOW),
                    ("lpAttributeList", ctypes.c_void_p)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]

    class _UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT),
                    ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class _OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_ulong),
                    ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
                    ("Attributes", ctypes.c_ulong),
                    ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class _IO_STATUS_BLOCK(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p),
                    ("Information", ctypes.c_void_p)]

    class _PUBLIC_OBJECT_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = [("Attributes", ctypes.c_ulong),
                    ("GrantedAccess", ctypes.c_ulong),
                    ("HandleCount", ctypes.c_ulong),
                    ("PointerCount", ctypes.c_ulong),
                    ("Reserved", ctypes.c_ulong * 10)]

    class _FILE_ID_INFO(ctypes.Structure):
        _fields_ = [("VolumeSerialNumber", ctypes.c_ulonglong),
                    ("FileId", ctypes.c_ubyte * 16)]

    class _ACL(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort), ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort)]

    class _ACE_HEADER(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_longlong),
                    ("TotalKernelTime", ctypes.c_longlong),
                    ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                    ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                    ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation",
                     _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _win_error(call: str) -> ContainmentUnavailable:
    code = ctypes.get_last_error() if os.name == "nt" else 0
    return ContainmentUnavailable(f"{call} failed (winerror {code})")


def _require_win32(what: str) -> None:
    if not platform_supported():
        raise ContainmentUnavailable(
            f"{what} is a win32 mechanism; this is {os.name!r}")


# --------------------------------------------------------------------------- #
# integrity labels -- always read back, never assumed from an exit code        #
# --------------------------------------------------------------------------- #
def _label_sid_from_handle(handle: int) -> str | None:
    """The mandatory-label SID of the file this HANDLE refers to, or None.

    None means "no label ACE", which Windows treats as an implicit Medium. The
    handle must carry READ_CONTROL; the append handle deliberately does not, so
    this is always called on the separate verification handle.
    """
    sd = ctypes.c_void_p()
    err = _advapi32.GetSecurityInfo(
        wintypes.HANDLE(handle), _SE_FILE_OBJECT, _LABEL_SECURITY_INFORMATION,
        None, None, None, None, ctypes.byref(sd))
    if err != 0:
        raise ContainmentUnavailable(
            f"GetSecurityInfo could not read the integrity label (error {err})")
    try:
        present = wintypes.BOOL()
        sacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if not _advapi32.GetSecurityDescriptorSacl(
                sd, ctypes.byref(present), ctypes.byref(sacl),
                ctypes.byref(defaulted)):
            raise _win_error("GetSecurityDescriptorSacl")
        if not present.value or not sacl:
            return None
        acl = ctypes.cast(sacl, ctypes.POINTER(_ACL)).contents
        for index in range(acl.AceCount):
            ace = ctypes.c_void_p()
            if not _advapi32.GetAce(sacl, index, ctypes.byref(ace)):
                continue
            header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
            if header.AceType != _SYSTEM_MANDATORY_LABEL_ACE_TYPE:
                continue
            # SYSTEM_MANDATORY_LABEL_ACE = ACE_HEADER + ACCESS_MASK + SID.
            sid_ptr = ctypes.c_void_p(
                ace.value + ctypes.sizeof(_ACE_HEADER) + 4)
            text = wintypes.LPWSTR()
            if not _advapi32.ConvertSidToStringSidW(sid_ptr,
                                                    ctypes.byref(text)):
                raise _win_error("ConvertSidToStringSidW")
            try:
                return text.value
            finally:
                _kernel32.LocalFree(text)
        return None
    finally:
        _kernel32.LocalFree(sd)


def integrity_label(path: str | Path) -> str | None:
    """The mandatory-label SID of ``path``, read through an opened handle.

    ``None`` means the object carries no label ACE, i.e. it is implicitly
    Medium. Used to VERIFY a labelling actually took effect rather than
    trusting ``icacls``'s exit code.
    """
    _require_win32("reading an integrity label")
    handle = _kernel32.CreateFileW(
        str(path), _READ_CONTROL, 0x7, None, _OPEN_EXISTING,
        0x02000000 | _FILE_ATTRIBUTE_NORMAL, None)   # FILE_FLAG_BACKUP_SEMANTICS
    if handle == ctypes.c_void_p(-1).value or not handle:
        raise _win_error(f"CreateFileW({path}) for label read")
    try:
        return _label_sid_from_handle(handle)
    finally:
        _kernel32.CloseHandle(wintypes.HANDLE(handle))


def _icacls_low(target: Path, inheritable: bool) -> None:
    spec = "(OI)(CI)Low" if inheritable else "Low"
    proc = subprocess.run(
        ["icacls", str(target), "/setintegritylevel", spec],
        capture_output=True, encoding="utf-8", errors="replace", timeout=300)
    if proc.returncode != 0:
        raise ContainmentUnavailable(
            f"icacls could not label {target}: "
            f"{(proc.stderr or proc.stdout or '').strip()[-200:]}")
    # READ IT BACK. icacls returning 0 is icacls's opinion; the label is the
    # fact, and every attestation this module emits has to be a fact.
    actual = integrity_label(target)
    if actual != LOW_INTEGRITY_SID:
        raise ContainmentUnavailable(
            f"{target} is not Low after labelling (label={actual!r}); refusing "
            f"to report containment that is not there")


def label_low_integrity(path: str | Path) -> None:
    """Mark ``path`` and everything created under it writable at Low.

    Without this the contained child could not write its own worktree, and
    containment that stops the candidate doing its job is not containment, it
    is an outage. Raises rather than returning a status: a caller who ignored a
    status would run against an unlabelled directory and see mysterious
    permission errors instead of a clear refusal.
    """
    _require_win32("integrity labelling")
    target = Path(path)
    if not target.is_dir():
        raise ContainmentUnavailable(f"not a directory: {target}")
    _icacls_low(target, inheritable=True)


def label_low_integrity_file(path: str | Path) -> None:
    """Label a single FILE Low, without object/container inheritance.

    Separate from :func:`label_low_integrity` because the two are not
    interchangeable: ``(OI)(CI)`` on a file is meaningless, and labelling the
    log's PARENT directory Low would hand the child a writable directory next
    to the log -- a capability it is not supposed to have.
    """
    _require_win32("integrity labelling")
    target = Path(path)
    if not target.is_file():
        raise ContainmentUnavailable(f"not a file: {target}")
    _icacls_low(target, inheritable=False)


# --------------------------------------------------------------------------- #
# the ONE handle that may cross the boundary                                   #
# --------------------------------------------------------------------------- #
def _granted_access(handle: int) -> int:
    """The kernel's own accounting of what this handle may do."""
    info = _PUBLIC_OBJECT_BASIC_INFORMATION()
    status = _ntdll.NtQueryObject(wintypes.HANDLE(handle),
                                  _ObjectBasicInformation, ctypes.byref(info),
                                  ctypes.sizeof(info), None)
    if status != 0:
        raise ContainmentUnavailable(
            f"NtQueryObject(ObjectBasicInformation) failed (status "
            f"{status & 0xFFFFFFFF:#010x}); the rights on the handle could not "
            f"be verified, so it does not cross")
    return int(info.GrantedAccess)


def _file_identity(handle: int) -> tuple[int, bytes]:
    """(volume serial, 128-bit file id) -- identity, not a name.

    Measured: this works on a handle carrying only APPEND|SYNCHRONIZE, so the
    identity of the handle that actually crosses can be compared against the
    identity of the handle the label was read from. Comparing paths instead
    would leave the reparse-point and swap races open, which is the whole
    reason the ruling said "on the opened handle".
    """
    info = _FILE_ID_INFO()
    if not _kernel32.GetFileInformationByHandleEx(
            wintypes.HANDLE(handle), _FileIdInfo, ctypes.byref(info),
            ctypes.sizeof(info)):
        raise _win_error("GetFileInformationByHandleEx(FileIdInfo)")
    return int(info.VolumeSerialNumber), bytes(info.FileId)


def _nt_open_append(path: Path) -> int:
    """Open ``path`` with EXACTLY ``LOW_APPEND_ACCESS``, inheritable.

    ``NtCreateFile`` and not ``CreateFileW``: measured on this box, CreateFileW
    asked for 0x00100004 and produced a handle with GrantedAccess 0x00100084 --
    it adds rights of its own accord. NtCreateFile grants exactly the requested
    mask (measured), which is what lets the rights check be an EQUALITY rather
    than a hopeful subset. The two masks coincide today; that is a coincidence
    of one measurement, not a contract, and an equality check against a mask we
    chose ourselves does not depend on it staying true.

    The share mode is FILE_SHARE_READ ONLY. Not sharing DELETE is load-bearing
    and was found by measurement: with FILE_SHARE_DELETE the contained child
    deleted its own log by path (the file is Low, so a Low process may delete
    it) and could then have written a replacement full of fabricated gate
    output. Not sharing WRITE stops the same trick via truncate-and-rewrite.
    """
    handle = wintypes.HANDLE()
    nt_path = "\\??\\" + str(path)
    buffer = ctypes.create_unicode_buffer(nt_path)
    name = _UNICODE_STRING()
    name.Buffer = ctypes.cast(buffer, wintypes.LPWSTR)
    name.Length = len(nt_path) * 2
    name.MaximumLength = name.Length + 2
    attributes = _OBJECT_ATTRIBUTES()
    attributes.Length = ctypes.sizeof(attributes)
    attributes.RootDirectory = None
    attributes.ObjectName = ctypes.pointer(name)
    attributes.Attributes = _OBJ_CASE_INSENSITIVE | _OBJ_INHERIT
    attributes.SecurityDescriptor = None
    attributes.SecurityQualityOfService = None
    iosb = _IO_STATUS_BLOCK()
    status = _ntdll.NtCreateFile(
        ctypes.byref(handle), ctypes.c_ulong(LOW_APPEND_ACCESS),
        ctypes.byref(attributes), ctypes.byref(iosb), None, ctypes.c_ulong(0),
        ctypes.c_ulong(_FILE_SHARE_READ), ctypes.c_ulong(_FILE_OPEN),
        ctypes.c_ulong(_FILE_SYNCHRONOUS_IO_NONALERT | _FILE_NON_DIRECTORY_FILE),
        None, ctypes.c_ulong(0))
    if status != 0:
        raise ContainmentUnavailable(
            f"NtCreateFile({path}) failed (status {status & 0xFFFFFFFF:#010x})")
    return int(handle.value)


class LowIntegrityLog:
    """The single handle allowed across the containment boundary.

    A caller cannot hand :func:`spawn_contained` a raw handle: the parameter is
    typed to this class and nothing else is accepted. That makes "bounded"
    structural rather than a convention -- the module chooses the target, the
    rights and the share mode, and re-verifies all of them immediately before
    the spawn.

    TWO handles are held, and only one of them is inheritable:

      * ``handle``  -- APPEND|SYNCHRONIZE, inheritable, on the allowlist. This
        is the one the child gets.
      * ``_verify`` -- READ_CONTROL, NOT inheritable, NOT on the allowlist.
        Reading the mandatory label needs READ_CONTROL, and granting the child
        READ_CONTROL is not on the table, so the label is read through a second
        handle whose FILE IDENTITY is proven equal to the first. Both stay open
        for the lifetime of the object, so the file object cannot be swapped
        underneath the check.
    """

    __slots__ = ("_handle", "_verify", "_identity", "_granted", "_label",
                 "_path", "_closed")

    def __init__(self, path: str | Path) -> None:
        _require_win32("an append-only Low log handle")
        self._path = Path(path)
        self._closed = False
        self._handle = _nt_open_append(self._path)
        try:
            verify = _kernel32.CreateFileW(
                str(self._path), _READ_CONTROL, _FILE_SHARE_READ, None,
                _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None)
            if verify == ctypes.c_void_p(-1).value or not verify:
                raise _win_error(f"CreateFileW({self._path}) for label read")
            self._verify = int(verify)
        except BaseException:
            _kernel32.CloseHandle(wintypes.HANDLE(self._handle))
            raise
        try:
            self._identity = _file_identity(self._handle)
            if _file_identity(self._verify) != self._identity:
                raise ContainmentUnavailable(
                    f"{self._path} changed identity between opening the append "
                    f"handle and opening the verification handle; refusing to "
                    f"inherit a handle whose target could not be pinned")
            self._granted = _granted_access(self._handle)
            self._label = _label_sid_from_handle(self._verify)
            self.verify()
        except BaseException:
            self.close()
            raise

    # -- the checks, run at construction AND again immediately before spawn -- #
    def verify(self) -> None:
        """Re-check target and rights ON THE HANDLES. Raises, never returns bad.

        Called again from :func:`spawn_contained` because construction and
        spawn are not the same instant, and a check that is not re-run at the
        moment of use is a time-of-check/time-of-use bug wearing a guard's hat.
        """
        if self._closed:
            raise ContainmentUnavailable("the log handle is already closed")
        granted = _granted_access(self._handle)
        if granted != LOW_APPEND_ACCESS:
            raise ContainmentUnavailable(
                f"the handle that would cross the boundary carries "
                f"{granted:#010x}, not {LOW_APPEND_ACCESS:#010x} "
                f"(APPEND|READ_ATTRIBUTES|SYNCHRONIZE); refusing to inherit it")
        if _file_identity(self._handle) != self._identity:
            raise ContainmentUnavailable(
                "the inheritable handle no longer refers to the file that was "
                "verified")
        if _file_identity(self._verify) != self._identity:
            raise ContainmentUnavailable(
                "the verification handle no longer refers to the file that was "
                "verified")
        label = _label_sid_from_handle(self._verify)
        if label != LOW_INTEGRITY_SID:
            shown = label if label else "none (implicitly Medium)"
            raise ContainmentUnavailable(
                f"refusing to inherit a handle on a non-Low target: "
                f"{self._path} has integrity label {shown}, and a handle a Low "
                f"child could not have opened itself is exactly the measured "
                f"MIC bypass")
        self._label = label

    # -- read-only facts, for the attestation ------------------------------- #
    @property
    def handle(self) -> int:
        return self._handle

    @property
    def path(self) -> Path:
        return self._path

    @property
    def granted_access(self) -> int:
        return self._granted

    @property
    def integrity_label(self) -> str | None:
        return self._label

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for attribute in ("_handle", "_verify"):
            handle = getattr(self, attribute, None)
            if handle:
                try:
                    _kernel32.CloseHandle(wintypes.HANDLE(handle))
                except Exception:               # noqa: BLE001
                    pass

    def __enter__(self) -> "LowIntegrityLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def open_low_append_log(path: str | Path) -> LowIntegrityLog:
    """Create ``path``, label it Low, and open the one handle that may cross.

    The file is created EMPTY by this process (Medium) and then labelled, so a
    Low child can neither pre-create it nor choose its contents. The label is
    then read back off the opened handle, so what is verified is the object the
    child will actually write to and not a path that may since have moved.
    """
    _require_win32("an append-only Low log handle")
    target = Path(path)
    if target.exists():
        raise ContainmentUnavailable(
            f"refusing to reuse an existing log target {target}: it must be "
            f"created by this process so its contents and label are ours")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb"):
        pass
    label_low_integrity_file(target)
    return LowIntegrityLog(target)


# --------------------------------------------------------------------------- #
# the low token                                                                #
# --------------------------------------------------------------------------- #
def _token_integrity_sid(token) -> str | None:
    """Read the integrity level back OFF the token. Attest facts, not calls."""
    size = wintypes.DWORD()
    _advapi32.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, None, 0,
                                  ctypes.byref(size))
    if not size.value:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if not _advapi32.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, buffer,
                                         size.value, ctypes.byref(size)):
        raise _win_error("GetTokenInformation(TokenIntegrityLevel)")
    label = ctypes.cast(buffer,
                        ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
    text = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(label.Label.Sid,
                                            ctypes.byref(text)):
        raise _win_error("ConvertSidToStringSidW")
    try:
        return text.value
    finally:
        _kernel32.LocalFree(text)


def _low_integrity_token():
    """A primary token identical to ours except Integrity Level = Low.

    Lowering your own token needs no privilege; raising one does. That
    asymmetry is why this works unattended and without admin. The level is READ
    BACK afterwards: an attestation that says "Low" because SetTokenInformation
    returned TRUE is a claim, and this module only ships facts.
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
    actual = _token_integrity_sid(duplicate)
    if actual != LOW_INTEGRITY_SID:
        _kernel32.CloseHandle(duplicate)
        raise ContainmentUnavailable(
            f"the duplicated token reports integrity {actual!r}, not Low; "
            f"refusing to launch a child that is not contained")
    return duplicate, actual


# --------------------------------------------------------------------------- #
# the attestation -- what ACTUALLY happened, never what was asked for          #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContainmentAttestation:
    """The EFFECTIVE containment of one child. Every field is a measurement.

    A caller that records ``requested`` and calls it a security property has
    recorded an intention. The ledger gets this instead, so an attempt whose
    containment silently did not happen is visible afterwards rather than
    indistinguishable from one where it did.
    """

    requested: bool
    executes_candidate: bool
    contained: bool
    platform: str
    mechanism: str = "none"
    token_integrity_sid: str | None = None
    worktree_label: str | None = None
    log_label: str | None = None
    log_granted_access: int | None = None
    inherited_handle_count: int = 0
    reason: str | None = None
    #: The job's limits AS THE KERNEL REPORTS THEM, or None for a run that had
    #: no job (a refusal, or a caller that declared it executes no candidate
    #: code). Never the constants at the top of this file: those are what was
    #: asked for, and this dataclass only carries what was confirmed.
    job_limits: "JobLimits | None" = None

    @property
    def low_token_obtained(self) -> bool:
        return self.token_integrity_sid == LOW_INTEGRITY_SID

    @property
    def worktree_labelled(self) -> bool:
        return self.worktree_label == LOW_INTEGRITY_SID

    def summary(self) -> dict:
        return {
            "requested": bool(self.requested),
            "executes_candidate": bool(self.executes_candidate),
            "contained": bool(self.contained),
            "platform": self.platform,
            "mechanism": self.mechanism,
            "low_token_obtained": self.low_token_obtained,
            "token_integrity_sid": self.token_integrity_sid,
            "worktree_labelled": self.worktree_labelled,
            "worktree_label": self.worktree_label,
            "log_label": self.log_label,
            "log_granted_access": (None if self.log_granted_access is None
                                   else f"{self.log_granted_access:#010x}"),
            "inherited_handle_count": int(self.inherited_handle_count),
            "reason": self.reason,
            "job_limits": (self.job_limits.summary()
                           if self.job_limits is not None else None),
        }


def refusal_attestation(reason: str, *, requested: bool = True,
                        executes_candidate: bool = True
                        ) -> ContainmentAttestation:
    """The attestation for a run that could NOT be contained.

    Exists so the refusal path records the same shape as the success path; a
    result whose containment block is simply absent reads as "not applicable"
    when it means "we tried and failed".
    """
    return ContainmentAttestation(
        requested=requested, executes_candidate=executes_candidate,
        contained=False, platform=sys.platform, mechanism="none",
        reason=reason)


# --------------------------------------------------------------------------- #
# the contained child                                                          #
# --------------------------------------------------------------------------- #
class ContainedProcess:
    """A running Low-integrity child, inside a Job Object that dies with it.

    NOT a dataclass any more: it carries a job handle, a cancellation ladder
    and a registry entry. The ladder mirrors
    :class:`daedalus.spine.cancel.ManagedProcess` exactly -- ``graceful`` via
    CTRL_BREAK to the process group, then ``tree_kill`` via
    ``TerminateJobObject`` -- because the kill switch's sweep of last resort
    calls ``.cancel(grace_s=...)`` on whatever it finds and must not care which
    of the two spawn paths produced it.

    WHY A SECOND JOB-OBJECT IMPLEMENTATION EXISTS. ``ManagedProcess`` spawns
    through ``subprocess.Popen``, which cannot be given a token, so a Low child
    cannot come from it. The duplication is the price of the boundary. It is
    also slightly better: ``CreateProcessAsUserW`` hands back the initial
    THREAD handle, so the suspend/assign/resume sequence needs no toolhelp
    snapshot and has no window in which the child could spawn outside the job.
    """

    def __init__(self, handle: int, thread: int, pid: int, job: int | None,
                 attestation: ContainmentAttestation) -> None:
        self.handle = handle
        self.thread = thread
        self.pid = pid
        self._job = job
        self._returncode: int | None = None
        self._closed = False
        self.attestation = attestation
        self._register()

    # -- the kill switch's sweep must see this child ------------------------ #
    def _register(self) -> None:
        """Join the registry :func:`cancel.cancel_all_managed` sweeps.

        THE BACKSTOP IS NOT OPTIONAL. ``KillSwitch.stop_children`` cancels every
        live child in this interpreter precisely to catch the one whose driver
        forgot to thread the cancel token through. A contained gate child that
        is not in that registry would be the single process the kill switch
        cannot reach -- the exact regression this reaches into a private for.
        A test pins the coupling, so a rename in ``cancel`` breaks loudly here
        instead of quietly dropping the sweep.
        """
        try:
            from daedalus.spine import cancel as _cancel
            with _cancel._LIVE_LOCK:
                _cancel._LIVE.add(self)
        except Exception:                       # noqa: BLE001
            pass

    def _unregister(self) -> None:
        try:
            from daedalus.spine import cancel as _cancel
            with _cancel._LIVE_LOCK:
                _cancel._LIVE.discard(self)
        except Exception:                       # noqa: BLE001
            pass

    # -- introspection ------------------------------------------------------ #
    @property
    def returncode(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        if self._closed:
            return None
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return None
        if code.value == _STILL_ACTIVE:
            return None
        self._returncode = int(code.value)
        return self._returncode

    def poll(self) -> int | None:
        return self.returncode

    def job_accounting(self) -> dict | None:
        """How many processes this job has seen. ``None`` once closed.

        The point of measuring rather than asserting: the process cap is only
        an honest ceiling if somebody has looked at what a REAL gate run costs,
        and this is how that number is obtained. Must be read before
        :meth:`close`, which destroys the job along with its counters.
        """
        if self._closed or self._job is None:
            return None
        return job_accounting(self._job)

    def wait(self, timeout_s: float = 900.0) -> int:
        _kernel32.WaitForSingleObject(self.handle, int(timeout_s * 1000))
        code = self.returncode
        if code is None:
            self.kill()
            return 124
        return code

    # -- cancellation ------------------------------------------------------- #
    def cancel(self, grace_s: float = 3.0):
        """Stop the tree, escalating from a group signal to a job kill.

        Returns a :class:`daedalus.spine.cancel.CancelResult` so the two spawn
        paths are indistinguishable to every caller that cancels them.
        """
        from daedalus.spine.cancel import (CancelResult, STAGE_ALREADY_EXITED,
                                           STAGE_GRACEFUL, STAGE_TREE_KILL)
        started = time.monotonic()
        if self.returncode is not None:
            return CancelResult(STAGE_ALREADY_EXITED, False, False,
                                self.returncode, time.monotonic() - started)
        signal_sent = bool(
            _kernel32.GenerateConsoleCtrlEvent(_CTRL_BREAK_EVENT, self.pid))
        if signal_sent and grace_s > 0:
            deadline = time.monotonic() + float(grace_s)
            while time.monotonic() < deadline and self.returncode is None:
                time.sleep(0.02)
        if self.returncode is not None:
            return CancelResult(STAGE_GRACEFUL, True, signal_sent,
                                self.returncode, time.monotonic() - started)
        self.kill()
        _kernel32.WaitForSingleObject(self.handle, 10000)
        return CancelResult(STAGE_TREE_KILL, False, signal_sent,
                            self.returncode, time.monotonic() - started)

    def kill(self) -> None:
        """Destroy the whole tree, not just the immediate child."""
        try:
            if self._job is not None:
                _kernel32.TerminateJobObject(self._job, 1)
            else:                               # pragma: no cover - after close
                _kernel32.TerminateProcess(self.handle, 1)
        except Exception:                       # noqa: BLE001
            pass

    def close(self) -> None:
        """Cancel anything still running, then release the job. Idempotent."""
        if self._closed:
            return
        try:
            if self.returncode is None:
                self.cancel(grace_s=0.0)
        except Exception:                       # noqa: BLE001
            pass
        finally:
            self._closed = True
            self._unregister()
            for handle in (self.handle, self.thread, self._job):
                if handle:
                    try:
                        # KILL_ON_JOB_CLOSE: closing the last job handle
                        # destroys any survivor.
                        _kernel32.CloseHandle(wintypes.HANDLE(handle))
                    except Exception:           # noqa: BLE001
                        pass
            self._job = None

    def __enter__(self) -> "ContainedProcess":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@dataclass(frozen=True)
class JobLimits:
    """What the kernel SAYS is armed on a job, read back out of it.

    Not what was requested. :func:`_create_job` asks, then queries, then
    compares, and this object is built from the query -- so an attestation
    carrying it is reporting a fact about the running job rather than repeating
    the constant at the top of this file.
    """

    limit_flags: int
    active_process_limit: int
    job_memory_limit_bytes: int

    @property
    def kill_on_close(self) -> bool:
        return bool(self.limit_flags & _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)

    @property
    def breakaway_denied(self) -> bool:
        """True when NEITHER breakaway flag is present.

        Phrased as a positive property because ``not breakaway_ok`` is the kind
        of double negative a reader skims past, and this is the flag whose
        accidental arrival would silently void every other limit here.
        """
        return not (self.limit_flags & (_JOB_OBJECT_LIMIT_BREAKAWAY_OK
                                        | _JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK))

    def summary(self) -> dict:
        return {
            "limit_flags": f"{self.limit_flags:#010x}",
            "kill_on_close": self.kill_on_close,
            "breakaway_denied": self.breakaway_denied,
            "active_process_limit": self.active_process_limit,
            "job_memory_limit_bytes": self.job_memory_limit_bytes,
        }


def _query_job_limits(job: int) -> JobLimits:
    """The job's ACTUAL limits, from ``QueryInformationJobObject``."""
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    returned = wintypes.DWORD()
    if not _kernel32.QueryInformationJobObject(
            wintypes.HANDLE(job), _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)):
        raise _win_error("QueryInformationJobObject(ExtendedLimitInformation)")
    return JobLimits(
        limit_flags=int(info.BasicLimitInformation.LimitFlags),
        active_process_limit=int(info.BasicLimitInformation.ActiveProcessLimit),
        job_memory_limit_bytes=int(info.JobMemoryLimit))


def job_accounting(job: int) -> dict:
    """``TotalProcesses``/``ActiveProcesses`` for a job. For MEASUREMENT.

    Exists so the process cap can be set from a number that was observed rather
    than picked: run a real gate, read ``total_processes``, and the margin
    between that and :data:`JOB_ACTIVE_PROCESS_LIMIT` is visible instead of
    asserted. ``total_processes`` is cumulative over the job's life, so it is an
    upper bound on peak concurrency, which is the safe direction to be wrong in
    when choosing a ceiling.
    """
    _require_win32("job accounting")
    info = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    returned = wintypes.DWORD()
    if not _kernel32.QueryInformationJobObject(
            wintypes.HANDLE(job), _JobObjectBasicAccountingInformation,
            ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)):
        raise _win_error("QueryInformationJobObject(BasicAccounting)")
    return {
        "total_processes": int(info.TotalProcesses),
        "active_processes": int(info.ActiveProcesses),
        "total_terminated_processes": int(info.TotalTerminatedProcesses),
    }


def _create_job(active_process_limit: int = JOB_ACTIVE_PROCESS_LIMIT,
                job_memory_limit_bytes: int = JOB_MEMORY_LIMIT_BYTES
                ) -> tuple[int, JobLimits]:
    """A job with a lifetime AND caps, every one of them verified by read-back.

    The parameters exist for MEASUREMENT and for the tests that prove the caps
    bite -- a test that had to allocate four gigabytes or fork ninety-six times
    to show the limit works would be a test nobody runs. They are NOT a
    loosening knob: there is no path from a gate to a call site that raises
    them, and :func:`spawn_contained` does not accept them.

    Raises :class:`ContainmentUnavailable` if the kernel hands back limits that
    are not the ones asked for, including the case where a breakaway flag
    appeared that was never set. A job whose limits could not be confirmed is
    not a bounded job, and this module does not ship an unbounded one under a
    bounded name.
    """
    if active_process_limit < 1:
        raise ContainmentUnavailable(
            f"an active-process limit of {active_process_limit} would refuse "
            f"the gate child itself")
    if job_memory_limit_bytes < 1:
        raise ContainmentUnavailable(
            f"a job memory limit of {job_memory_limit_bytes} bytes is not a "
            f"limit, it is an outage")
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _win_error("CreateJobObjectW")
    try:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        wanted = (_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                  | _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                  | _JOB_OBJECT_LIMIT_JOB_MEMORY
                  | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        info.BasicLimitInformation.LimitFlags = wanted
        info.BasicLimitInformation.ActiveProcessLimit = int(active_process_limit)
        info.JobMemoryLimit = ctypes.c_size_t(int(job_memory_limit_bytes))
        if not _kernel32.SetInformationJobObject(
                job, _JobObjectExtendedLimitInformation, ctypes.byref(info),
                ctypes.sizeof(info)):
            raise _win_error("SetInformationJobObject")

        # THE READ-BACK. Everything above is a request; this is the fact.
        limits = _query_job_limits(job)
        if limits.limit_flags != wanted:
            raise ContainmentUnavailable(
                f"the job reports LimitFlags {limits.limit_flags:#010x}, not "
                f"the {wanted:#010x} that was set; refusing to run candidate "
                f"code in a job whose limits could not be confirmed")
        if not limits.breakaway_denied:
            raise ContainmentUnavailable(
                "the job permits breakaway, which would let the child leave "
                "every limit above; refusing")
        if limits.active_process_limit != int(active_process_limit):
            raise ContainmentUnavailable(
                f"the job reports an active-process limit of "
                f"{limits.active_process_limit}, not {active_process_limit}")
        if limits.job_memory_limit_bytes != int(job_memory_limit_bytes):
            raise ContainmentUnavailable(
                f"the job reports a memory limit of "
                f"{limits.job_memory_limit_bytes} bytes, not "
                f"{job_memory_limit_bytes}")
    except BaseException:
        _kernel32.CloseHandle(wintypes.HANDLE(job))
        raise
    return int(job), limits


class _HandleAllowlist:
    """``PROC_THREAD_ATTRIBUTE_HANDLE_LIST`` over exactly the given handles.

    Holds a reference to the HANDLE array for its whole lifetime:
    ``UpdateProcThreadAttribute`` stores a POINTER to the value, so letting the
    array be collected before ``CreateProcessAsUserW`` would hand the kernel a
    dangling list -- and a dangling allowlist is an unbounded one.
    """

    def __init__(self, handles) -> None:
        self._handles = [int(h) for h in handles]
        if not self._handles:
            raise ContainmentUnavailable("an empty allowlist is not a list")
        size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 1, 0,
                                                    ctypes.byref(size))
        if not size.value:
            raise _win_error("InitializeProcThreadAttributeList (sizing)")
        self._buffer = ctypes.create_string_buffer(size.value)
        if not _kernel32.InitializeProcThreadAttributeList(
                self._buffer, 1, 0, ctypes.byref(size)):
            raise _win_error("InitializeProcThreadAttributeList")
        self._array = (wintypes.HANDLE * len(self._handles))(
            *[wintypes.HANDLE(h) for h in self._handles])
        if not _kernel32.UpdateProcThreadAttribute(
                self._buffer, 0, _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.byref(self._array), ctypes.sizeof(self._array), None,
                None):
            _kernel32.DeleteProcThreadAttributeList(self._buffer)
            raise _win_error("UpdateProcThreadAttribute(HANDLE_LIST)")

    @property
    def pointer(self):
        return ctypes.cast(self._buffer, ctypes.c_void_p)

    @property
    def count(self) -> int:
        return len(self._handles)

    def close(self) -> None:
        if getattr(self, "_buffer", None) is not None:
            _kernel32.DeleteProcThreadAttributeList(self._buffer)
            self._buffer = None


def spawn_contained(argv, cwd: str | Path, env: dict | None = None, *,
                    log: LowIntegrityLog | None = None,
                    worktree_label: str | None = None,
                    max_processes: int | None = None,
                    max_job_memory_bytes: int | None = None
                    ) -> ContainedProcess:
    """Start ``argv`` at Low integrity with ``cwd`` as its working directory.

    ``max_processes`` and ``max_job_memory_bytes`` TIGHTEN the job's caps and
    cannot loosen them: each is combined with the module ceiling by ``min()``,
    written as one expression so there is no state in which a caller asked for
    more and got it. They exist because proving a cap bites should not require
    forking ninety-six times or committing four gigabytes, and a proof nobody
    can afford to run is not a proof. Passing ``None`` -- what every production
    caller does -- gets :data:`JOB_ACTIVE_PROCESS_LIMIT` and
    :data:`JOB_MEMORY_LIMIT_BYTES`.

    HANDLE INHERITANCE IS BOUNDED, NOT CONFIGURABLE. There is no ``inherit``
    parameter, no ``close_fds``, and no way to pass a raw handle: ``log`` is
    typed to :class:`LowIntegrityLog`, an object only this module can
    construct, on a target only this module labels, with rights only this
    module chooses. ``bInheritHandles`` is written as ``allowlist is not None``
    so inheritance and the allowlist can never disagree.

    With ``log=None`` no handle crosses at all and the child has no stdio; that
    is the original behaviour and remains the default.

    Raises :class:`ContainmentUnavailable` on any platform or API failure, and
    never falls back to an ordinary spawn.
    """
    _require_win32("low-integrity spawn")
    if not argv:
        raise ContainmentUnavailable("argv must not be empty")
    if log is not None and not isinstance(log, LowIntegrityLog):
        raise ContainmentUnavailable(
            f"log must be a LowIntegrityLog opened by this module, not "
            f"{type(log).__name__}; a raw handle cannot be verified and so "
            f"cannot cross the boundary")
    if log is not None:
        # RE-VERIFIED HERE, not merely at construction: target and rights are
        # checked on the handle at the moment of use.
        log.verify()

    token, token_sid = _low_integrity_token()
    # CreateProcessAsUserW takes ONE command line, not an argv vector, and the
    # callee re-parses it -- so every element is quoted rather than joined.
    cmdline = subprocess.list2cmdline([str(a) for a in argv])
    startup = _STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    info = _PROCESS_INFORMATION()

    block = None
    # CREATE_SUSPENDED so the child cannot spawn a grandchild before it is
    # inside the job; resumed below, only once assignment succeeded.
    flags = (_CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED
             | _EXTENDED_STARTUPINFO_PRESENT)
    if env is not None:
        # A Low child cannot write %TEMP% (Medium), so a caller that wants a
        # usable child gives it a TEMP inside a Low-labelled directory.
        items = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        block = ctypes.create_unicode_buffer(items)
        flags |= _CREATE_UNICODE_ENVIRONMENT

    allowlist = None
    if log is not None:
        allowlist = _HandleAllowlist([log.handle])
        startup.lpAttributeList = allowlist.pointer
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        # stdin is NULL, deliberately: a handle on the null device would be a
        # SECOND inherited handle for no security benefit. Measured: the child
        # sees sys.stdin is None and os.dup(0) still succeeds, so pytest's fd
        # capture is unaffected.
        startup.StartupInfo.hStdInput = None
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(log.handle)
        startup.StartupInfo.hStdError = wintypes.HANDLE(log.handle)

    # TIGHTENING ONLY. min() with the module ceiling is the whole mechanism:
    # there is no argument that makes the blast radius larger than the constant
    # at the top of this file, so this pair can never become the loosening knob
    # that "there is no contained=False" exists to prevent.
    processes = (JOB_ACTIVE_PROCESS_LIMIT if max_processes is None
                 else min(int(max_processes), JOB_ACTIVE_PROCESS_LIMIT))
    job_memory = (JOB_MEMORY_LIMIT_BYTES if max_job_memory_bytes is None
                  else min(int(max_job_memory_bytes), JOB_MEMORY_LIMIT_BYTES))
    job, job_limits = _create_job(processes, job_memory)
    try:
        # THE ONE PLACE INHERITANCE IS DECIDED. `inherit` is literally
        # "is there an allowlist?", so there is no reachable state in which
        # handles are inheritable and the allowlist is absent.
        inherit = allowlist is not None
        ok = _advapi32.CreateProcessAsUserW(
            token, None, ctypes.create_unicode_buffer(cmdline), None, None,
            inherit,                            # bInheritHandles == allowlisted
            flags, block, str(cwd), ctypes.byref(startup), ctypes.byref(info))
        if not ok:
            raise _win_error("CreateProcessAsUserW")
    except BaseException:
        _kernel32.CloseHandle(wintypes.HANDLE(job))
        raise
    finally:
        if allowlist is not None:
            allowlist.close()

    try:
        if not _kernel32.AssignProcessToJobObject(job, info.hProcess):
            raise _win_error("AssignProcessToJobObject")
        if _kernel32.ResumeThread(info.hThread) == 0xFFFFFFFF:
            raise _win_error("ResumeThread")
    except BaseException:
        # A child we cannot contain must never be left running.
        try:
            _kernel32.TerminateProcess(info.hProcess, 1)
        except Exception:                       # noqa: BLE001
            pass
        for handle in (info.hProcess, info.hThread, job):
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(handle))
            except Exception:                   # noqa: BLE001
                pass
        raise

    attestation = ContainmentAttestation(
        requested=True, executes_candidate=True, contained=True,
        platform=sys.platform,
        # THE LABEL IS DELIBERATELY UNCHANGED by the arrival of the caps. It is
        # a coarse name, and the caps are not a coarse fact: `job_limits` below
        # carries the LimitFlags the kernel handed back, which is what a reader
        # comparing two ledger entries actually needs. An old record has
        # `job_limits: null` and a capped one does not, so the two are still
        # told apart -- by a measurement rather than by a string.
        mechanism="mic-low+job" + ("+bounded-inherit" if log else ""),
        token_integrity_sid=token_sid,
        worktree_label=worktree_label,
        log_label=log.integrity_label if log else None,
        log_granted_access=log.granted_access if log else None,
        inherited_handle_count=(allowlist.count if allowlist else 0),
        job_limits=job_limits)
    return ContainedProcess(handle=info.hProcess, thread=info.hThread,
                            pid=int(info.dwProcessId), job=job,
                            attestation=attestation)
