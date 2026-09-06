"""Second angle: is the warning killed by the hStdInput FIELD or by the child
actually receiving the handle (allowlist membership)?

B2 sets StartupInfo.hStdInput to the inheritable NUL handle but does NOT add it
to PROC_THREAD_ATTRIBUTE_HANDLE_LIST, so inherited_handle_count stays 1. If the
warning stays gone, the allowlist is not load-bearing; if it comes back, arm B's
result requires widening the allowlist and therefore breaks the ==1 invariant.

Also replicates A and B to rule out a flake. READ-ONLY on the repository.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, r"<USERPROFILE>\Desktop\PROJECTS\daedalus")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from daedalus.spine import containment as C                      # noqa: E402
from daedalus.kernel.promotion_trust_root import scrubbed_child_env  # noqa: E402
from nulstdin_experiment import open_inheritable_nul, py_pids, OUT  # noqa: E402


def spawn2(argv, cwd, env, log, stdin_handle, allowlist_stdin: bool):
    C._require_win32("low-integrity spawn")
    log.verify()
    token, token_sid = C._low_integrity_token()
    cmdline = subprocess.list2cmdline([str(a) for a in argv])
    startup = C._STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(C._STARTUPINFOEXW)
    info = C._PROCESS_INFORMATION()
    flags = (C._CREATE_NEW_PROCESS_GROUP | C._CREATE_SUSPENDED
             | C._EXTENDED_STARTUPINFO_PRESENT | C._CREATE_UNICODE_ENVIRONMENT)
    block = ctypes.create_unicode_buffer(
        "".join(f"{k}={v}\0" for k, v in env.items()) + "\0")

    handles = [log.handle]
    if stdin_handle is not None and allowlist_stdin:
        handles.append(stdin_handle)
    allowlist = C._HandleAllowlist(handles)
    startup.lpAttributeList = allowlist.pointer
    startup.StartupInfo.dwFlags = C._STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = (None if stdin_handle is None
                                     else wintypes.HANDLE(stdin_handle))
    startup.StartupInfo.hStdOutput = wintypes.HANDLE(log.handle)
    startup.StartupInfo.hStdError = wintypes.HANDLE(log.handle)

    job, job_limits = C._create_job(C.JOB_ACTIVE_PROCESS_LIMIT,
                                    C.JOB_MEMORY_LIMIT_BYTES)
    try:
        ok = C._advapi32.CreateProcessAsUserW(
            token, None, ctypes.create_unicode_buffer(cmdline), None, None,
            True, flags, block, str(cwd), ctypes.byref(startup),
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
        token_integrity_sid=token_sid, log_label=log.integrity_label,
        log_granted_access=log.granted_access,
        inherited_handle_count=allowlist.count, job_limits=job_limits)
    return C.ContainedProcess(info.hProcess, info.hThread,
                              int(info.dwProcessId), job, att), len(handles)


def run(name, argv, stdin_nul, allowlist_stdin, probe=None):
    root = Path(tempfile.mkdtemp(prefix=f"odysseus-{name}-", dir=str(OUT)))
    wt = root / "worktree"; wt.mkdir()
    lt = root / "lowtemp"; lt.mkdir()
    C.label_low_integrity(wt); C.label_low_integrity(lt)
    log = C.open_low_append_log(root / "gate.out")
    nul = open_inheritable_nul() if stdin_nul else None
    env = scrubbed_child_env(); env["TEMP"] = env["TMP"] = str(lt)
    before = py_pids()
    rec = {"arm": name, "stdin_field": "NUL" if stdin_nul else "NULL",
           "nul_on_allowlist": allowlist_stdin if stdin_nul else None}
    try:
        proc, n = spawn2(argv, wt, env, log, nul, allowlist_stdin)
        rec["inherited_handle_count"] = n
        rec["exit_code"] = proc.wait(timeout_s=60.0)
        rec["job_accounting"] = proc.job_accounting()
        proc.close()
    finally:
        log.close()
        if nul is not None:
            C._kernel32.CloseHandle(wintypes.HANDLE(nul))
    rec["leaked_python_pids"] = sorted(py_pids() - before)
    rec["merged_log_bytes"] = repr((root / "gate.out").read_bytes())
    return rec


STUB = [sys.executable, "-I", "-S", "-c", "print('x')"]
# what does the child actually SEE on fd 0 / sys.stdin in each arm?
SEEN = [sys.executable, "-I", "-S", "-c",
        "import sys,os;"
        "print('stdin_is_none', sys.stdin is None);"
        "\nimport os\n" ]

PROBE = [sys.executable, "-I", "-S", "-c",
         "import sys, os\n"
         "print('sys.stdin', sys.stdin)\n"
         "try:\n"
         "    print('dup0', os.dup(0))\n"
         "except Exception as e:\n"
         "    print('dup0 FAILED', type(e).__name__, e)\n"]

cases = [
    ("A_rep", STUB, False, False),
    ("B_rep", STUB, True, True),
    ("B2_field_only_no_allowlist", STUB, True, False),
    ("A_probe_stdin", PROBE, False, False),
    ("B_probe_stdin", PROBE, True, True),
]
out = []
for name, argv, sn, al in cases:
    try:
        rec = run(name, argv, sn, al)
    except Exception as exc:                       # noqa: BLE001
        rec = {"arm": name, "error": f"{type(exc).__name__}: {exc}"}
    out.append(rec)
    print(json.dumps(rec, indent=2, default=str)); print("-" * 78)
(OUT / "discriminator.json").write_text(json.dumps(out, indent=2, default=str),
                                        encoding="utf-8")
