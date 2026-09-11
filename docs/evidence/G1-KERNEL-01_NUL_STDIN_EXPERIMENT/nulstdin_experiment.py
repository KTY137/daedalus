"""Controlled A/B on hStdInput in the production contained-gate spawn.

READ-ONLY on the repository. Nothing here imports for its side effects beyond
what daedalus.spine.containment already does; no repo file is written.

The only variable between arm A and arm B is STARTUPINFO.hStdInput (NULL vs an
inheritable handle on the NUL device, which then must also be on the
PROC_THREAD_ATTRIBUTE_HANDLE_LIST allowlist). Everything else -- token,
job, flags, env scrub, low-labelled cwd/TEMP, the LowIntegrityLog handle -- is
the production path, imported from the production module.

spawn_contained() deliberately has NO parameter that can carry a stdin handle,
so the CreateProcessAsUserW call itself is copied here verbatim (with the one
extra assignment) rather than monkeypatched.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

REPO = Path(r"<USERPROFILE>\Desktop\PROJECTS\daedalus")
sys.path.insert(0, str(REPO))

from daedalus.spine import containment as C          # noqa: E402
from daedalus.kernel.promotion_trust_root import scrubbed_child_env  # noqa: E402

OUT = Path(__file__).resolve().parent

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


def open_inheritable_nul() -> int:
    """CreateFileW("NUL", GENERIC_READ, SHARE_READ|WRITE, inheritable)."""
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True
    h = C._kernel32.CreateFileW("NUL", GENERIC_READ,
                                FILE_SHARE_READ | FILE_SHARE_WRITE,
                                ctypes.byref(sa), OPEN_EXISTING,
                                FILE_ATTRIBUTE_NORMAL, None)
    if h == ctypes.c_void_p(-1).value or not h:
        raise OSError(f"CreateFileW(NUL) failed winerror={ctypes.get_last_error()}")
    return int(h)


def spawn(argv, cwd, env, log, stdin_handle: int | None):
    """spawn_contained() verbatim, plus the single hStdInput variable.

    Copied from daedalus/spine/containment.py::spawn_contained because that
    function's signature forbids passing a stdin handle by design.
    """
    C._require_win32("low-integrity spawn")
    log.verify()
    token, token_sid = C._low_integrity_token()
    cmdline = subprocess.list2cmdline([str(a) for a in argv])
    startup = C._STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(C._STARTUPINFOEXW)
    info = C._PROCESS_INFORMATION()

    flags = (C._CREATE_NEW_PROCESS_GROUP | C._CREATE_SUSPENDED
             | C._EXTENDED_STARTUPINFO_PRESENT)
    items = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
    block = ctypes.create_unicode_buffer(items)
    flags |= C._CREATE_UNICODE_ENVIRONMENT

    handles = [log.handle] if stdin_handle is None else [log.handle, stdin_handle]
    allowlist = C._HandleAllowlist(handles)
    startup.lpAttributeList = allowlist.pointer
    startup.StartupInfo.dwFlags = C._STARTF_USESTDHANDLES
    # ---- THE ONE VARIABLE --------------------------------------------------
    startup.StartupInfo.hStdInput = (None if stdin_handle is None
                                     else wintypes.HANDLE(stdin_handle))
    # ------------------------------------------------------------------------
    startup.StartupInfo.hStdOutput = wintypes.HANDLE(log.handle)
    startup.StartupInfo.hStdError = wintypes.HANDLE(log.handle)

    job, job_limits = C._create_job(C.JOB_ACTIVE_PROCESS_LIMIT,
                                    C.JOB_MEMORY_LIMIT_BYTES)
    try:
        inherit = allowlist is not None
        ok = C._advapi32.CreateProcessAsUserW(
            token, None, ctypes.create_unicode_buffer(cmdline), None, None,
            inherit, flags, block, str(cwd), ctypes.byref(startup),
            ctypes.byref(info))
        if not ok:
            raise C._win_error("CreateProcessAsUserW")
    except BaseException:
        C._kernel32.CloseHandle(wintypes.HANDLE(job))
        raise
    finally:
        allowlist.close()

    if not C._kernel32.AssignProcessToJobObject(job, info.hProcess):
        raise C._win_error("AssignProcessToJobObject")
    if C._kernel32.ResumeThread(info.hThread) == 0xFFFFFFFF:
        raise C._win_error("ResumeThread")

    att = C.ContainmentAttestation(
        requested=True, executes_candidate=True, contained=True,
        platform=sys.platform, mechanism="mic-low+job+bounded-inherit",
        token_integrity_sid=token_sid, worktree_label=None,
        log_label=log.integrity_label, log_granted_access=log.granted_access,
        inherited_handle_count=allowlist.count, job_limits=job_limits)
    return C.ContainedProcess(handle=info.hProcess, thread=info.hThread,
                              pid=int(info.dwProcessId), job=job,
                              attestation=att), len(handles)


def py_pids() -> set[int]:
    raw = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV",
                          "/NH"], capture_output=True, text=True).stdout
    out = set()
    for line in raw.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].strip().isdigit():
            out.add(int(parts[1]))
    return out


def run_arm(name: str, argv, stdin_nul: bool) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"odysseus-{name}-", dir=str(OUT)))
    worktree = root / "worktree"
    worktree.mkdir()
    lowtemp = root / "lowtemp"
    lowtemp.mkdir()
    C.label_low_integrity(worktree)
    C.label_low_integrity(lowtemp)
    out_path = root / "gate.out"
    log = C.open_low_append_log(out_path)

    nul = open_inheritable_nul() if stdin_nul else None
    nul_access = C._granted_access(nul) if nul is not None else None

    env = scrubbed_child_env()
    env["TEMP"] = env["TMP"] = str(lowtemp)

    before = py_pids()
    rec: dict = {"arm": name, "argv": [str(a) for a in argv],
                 "stdin": "NUL-device handle" if stdin_nul else "NULL",
                 "nul_granted_access": (None if nul_access is None
                                        else f"0x{nul_access:08x}")}
    try:
        proc, n_handles = spawn(argv, worktree, env, log, nul)
        rec["inherited_handle_count"] = n_handles
        rec["mechanism"] = proc.attestation.mechanism
        rec["exit_code"] = proc.wait(timeout_s=60.0)
        acct = proc.job_accounting()
        rec["job_accounting"] = acct
        rec["in_job"] = bool(acct and acct.get("total_processes", 0) >= 1)
        proc.close()
    finally:
        log.close()
        if nul is not None:
            C._kernel32.CloseHandle(wintypes.HANDLE(nul))
    after = py_pids()
    rec["leaked_python_pids"] = sorted(after - before)
    rec["merged_log_bytes"] = repr(out_path.read_bytes())
    return rec


def main() -> None:
    print(f"sys.executable       = {sys.executable}")
    print(f"sys._base_executable = {sys._base_executable}")
    print(f"LOW_APPEND_ACCESS    = 0x{C.LOW_APPEND_ACCESS:08x}")
    print()
    arms = [
        ("A_stub_nullstdin", [sys.executable, "-I", "-S", "-c", "print('x')"], False),
        ("B_stub_nulstdin", [sys.executable, "-I", "-S", "-c", "print('x')"], True),
        ("C_base_nullstdin", [sys._base_executable, "-I", "-S", "-c", "print('x')"], False),
        ("D_base_opens_nul", [sys._base_executable, "-c",
                              "open('NUL','rb').close(); print('nul-ok')"], False),
    ]
    results = []
    for name, argv, stdin_nul in arms:
        try:
            rec = run_arm(name, argv, stdin_nul)
        except Exception as exc:                       # noqa: BLE001
            rec = {"arm": name, "error": f"{type(exc).__name__}: {exc}"}
        results.append(rec)
        print(json.dumps(rec, indent=2, default=str))
        print("-" * 78)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str),
                                      encoding="utf-8")


if __name__ == "__main__":
    main()
