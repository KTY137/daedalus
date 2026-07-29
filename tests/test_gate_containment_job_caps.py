"""The Job Object caps on the gate child: they bite, AND they let work through.

WHY BOTH HALVES ARE IN ONE FILE. A containment that refuses everything passes
the "blocked" tests for free and is an outage, not a boundary. A containment
that allows everything passes the "allowed" tests for free and is decorative.
Neither half means anything without the other, so they are kept where a reader
cannot skim one and miss the other.

WHAT IS BEING PINNED. ``containment._create_job`` used to set exactly one flag,
``KILL_ON_JOB_CLOSE`` -- a lifetime, with no bound at all on what the candidate
could CONSUME while it had that lifetime. MIC bounds writes; it does not bound
forking or committing memory, so a candidate could wedge the box without
writing a byte outside its worktree. These tests pin the three caps that closed
that, the breakaway flag whose arrival would void all of them, and the fact
that the limits reaching the ledger are READ BACK OUT OF THE KERNEL rather than
copied from the constants that were requested.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

import daedalus.spine.attempt as attempt_mod
from daedalus.spine import containment as C

pytestmark = pytest.mark.skipif(
    not C.platform_supported(),
    reason="MIC write containment is a win32 mechanism")

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# arena                                                                        #
# --------------------------------------------------------------------------- #
def _arena(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    C.label_low_integrity(worktree)
    low_temp = tmp_path / "lowtemp"
    low_temp.mkdir()
    C.label_low_integrity(low_temp)
    return worktree, low_temp


def _run_contained(tmp_path: Path, worktree: Path, low_temp: Path, argv,
                   **caps) -> tuple[int, str, C.ContainmentAttestation]:
    """Run ``argv`` as the contained gate child; return (rc, output, attestation).

    Output comes back through the one handle allowed across the boundary, so a
    test that reads it has also proven the evidence channel survived the caps --
    the "empty green" this repo forbids would show up here as an empty string.
    """
    log = C.open_low_append_log(tmp_path / f"gate-{os.urandom(4).hex()}.out")
    try:
        env = dict(os.environ)
        env["TEMP"] = env["TMP"] = str(low_temp)
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = C.spawn_contained([str(a) for a in argv], cwd=worktree, env=env,
                                 log=log, **caps)
    except BaseException:
        log.close()
        raise
    try:
        rc = proc.wait(timeout_s=300)
        attestation = proc.attestation
    finally:
        log.close()
        proc.close()
    return rc, log.path.read_text(encoding="utf-8", errors="replace"), attestation


# --------------------------------------------------------------------------- #
# BLOCKED -- the caps actually bite                                            #
# --------------------------------------------------------------------------- #
def test_the_process_cap_refuses_a_fork_bomb_without_killing_the_job(tmp_path):
    """Past the cap CreateProcess FAILS; the job is not torn down.

    That distinction is the whole design. If exceeding the cap killed the job,
    an honest candidate that happened to be parallel would lose its verdict and
    the gate would report a failure that says nothing about the patch. Instead
    the offending spawn gets ERROR_NOT_ENOUGH_QUOTA (1816) and everything
    already running carries on -- damage limitation, not a hair trigger.
    """
    worktree, low_temp = _arena(tmp_path)
    probe = worktree / "forkbomb.py"
    probe.write_text(textwrap.dedent(r'''
        import subprocess, sys
        started, refused = 0, []
        kids = []
        for _ in range(12):
            try:
                kids.append(subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(20)"]))
                started += 1
            except OSError as e:
                refused.append(getattr(e, "winerror", None))
        for k in kids:
            k.kill()
        print("started=%d" % started)
        print("refused=%r" % (refused,))
    '''), encoding="utf-8")

    # cap=3: the gate child itself is one of the three.
    rc, out, att = _run_contained(tmp_path, worktree, low_temp,
                                  [sys.executable, str(probe)], max_processes=3)

    assert rc == 0, f"the probe itself did not complete: rc={rc}\n{out}"
    assert out.strip(), "the contained child produced no evidence at all"
    started = int(out.split("started=")[1].split()[0])
    assert started <= 2, (
        f"the job let {started} concurrent children start under an "
        f"ActiveProcessLimit of 3; the cap is not armed")
    assert "1816" in out, (
        f"a refused spawn did not report ERROR_NOT_ENOUGH_QUOTA (1816), so the "
        f"refusal did not come from the job's process cap:\n{out}")


def test_the_memory_cap_refuses_a_commit_larger_than_the_job_allows(tmp_path):
    """A candidate cannot commit its way past the job-wide memory limit.

    JOB memory, not PROCESS memory, and the difference is load-bearing: with a
    per-process cap, N processes each just under the line still commit N times
    the line, and the process cap is 96.
    """
    worktree, low_temp = _arena(tmp_path)
    probe = worktree / "memhog.py"
    probe.write_text(textwrap.dedent(r'''
        try:
            blocks = []
            for _ in range(16):            # 16 x 64 MiB = 1 GiB attempted
                blocks.append(bytearray(64 * 1024 * 1024))
            print("allocated=%d MiB" % (len(blocks) * 64))
        except MemoryError:
            print("REFUSED: MemoryError")
    '''), encoding="utf-8")

    rc, out, att = _run_contained(tmp_path, worktree, low_temp,
                                  [sys.executable, str(probe)],
                                  max_job_memory_bytes=256 * 1024 * 1024)

    assert out.strip(), "the contained child produced no evidence at all"
    assert "REFUSED: MemoryError" in out, (
        f"a 1 GiB commit succeeded under a 256 MiB job memory limit, so the "
        f"memory cap is not armed:\n{out}")
    assert att.job_limits.job_memory_limit_bytes == 256 * 1024 * 1024


def test_the_child_cannot_break_out_of_the_job(tmp_path):
    """CREATE_BREAKAWAY_FROM_JOB is refused, because BREAKAWAY_OK is never set.

    This is the flag that would make every other limit in this file
    decorative -- a child that can leave the job takes no cap with it. Denial
    is the Windows default, which is exactly why it is measured rather than
    assumed.
    """
    worktree, low_temp = _arena(tmp_path)
    probe = worktree / "breakaway.py"
    probe.write_text(textwrap.dedent(r'''
        import ctypes, sys
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)

        class SI(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("a", wintypes.LPWSTR),
                        ("b", wintypes.LPWSTR), ("c", wintypes.LPWSTR)] + [
                        (n, wintypes.DWORD) for n in
                        ("dwX","dwY","dwXS","dwYS","dwXC","dwYC","dwFill","dwFlags")] + [
                        ("wShow", wintypes.WORD), ("cbR2", wintypes.WORD),
                        ("lpR2", ctypes.c_void_p), ("hIn", wintypes.HANDLE),
                        ("hOut", wintypes.HANDLE), ("hErr", wintypes.HANDLE)]

        class PI(ctypes.Structure):
            _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                        ("dwPid", wintypes.DWORD), ("dwTid", wintypes.DWORD)]

        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        si, pi = SI(), PI()
        si.cb = ctypes.sizeof(SI)
        cmd = ctypes.create_unicode_buffer(
            '"%s" -c "import time; time.sleep(5)"' % sys.executable)
        ok = k.CreateProcessW(None, cmd, None, None, False,
                              CREATE_BREAKAWAY_FROM_JOB, None, None,
                              ctypes.byref(si), ctypes.byref(pi))
        print("breakaway=%s err=%d" % ("ALLOWED" if ok else "REFUSED",
                                       ctypes.get_last_error()))
        if ok:
            k.TerminateProcess(pi.hProcess, 1)
    '''), encoding="utf-8")

    rc, out, att = _run_contained(tmp_path, worktree, low_temp,
                                  [sys.executable, str(probe)])

    assert "breakaway=REFUSED" in out, (
        f"the contained child broke out of its Job Object, taking every "
        f"resource cap with it:\n{out}")
    assert att.job_limits.breakaway_denied


def test_the_caps_can_be_tightened_by_a_caller_and_never_loosened(tmp_path):
    """``max_processes`` is a min() against the ceiling, so it cannot weaken it.

    The parameter exists so a test can prove a cap bites without forking
    ninety-six times. The moment it can also RAISE a cap it is the
    ``contained=False`` knob this module refuses to have, so the clamp is
    pinned here rather than left to the reader of the min().
    """
    worktree, low_temp = _arena(tmp_path)
    probe = worktree / "noop.py"
    probe.write_text("print('ok')\n", encoding="utf-8")

    rc, out, att = _run_contained(
        tmp_path, worktree, low_temp, [sys.executable, str(probe)],
        max_processes=100_000, max_job_memory_bytes=1 << 60)

    assert rc == 0 and "ok" in out
    assert att.job_limits.active_process_limit == C.JOB_ACTIVE_PROCESS_LIMIT, (
        "a caller raised the process cap above the module ceiling")
    assert att.job_limits.job_memory_limit_bytes == C.JOB_MEMORY_LIMIT_BYTES, (
        "a caller raised the memory cap above the module ceiling")


def test_a_job_whose_limits_cannot_be_confirmed_is_refused():
    """Fail-closed at the job layer too: no confirmation, no job."""
    with pytest.raises(C.ContainmentUnavailable):
        C._create_job(0, C.JOB_MEMORY_LIMIT_BYTES)
    with pytest.raises(C.ContainmentUnavailable):
        C._create_job(C.JOB_ACTIVE_PROCESS_LIMIT, 0)


def test_the_attestation_carries_what_the_kernel_said_not_what_was_asked():
    """The limits in the ledger are a QueryInformationJobObject read-back.

    ``SetInformationJobObject`` returning TRUE is a claim. This module ships
    facts, and the way to tell the two apart is that the fact survives the
    round trip through the kernel.
    """
    job, limits = C._create_job()
    try:
        import ctypes
        from ctypes import wintypes
        assert limits.kill_on_close, "a leaked test process could outlive the attempt"
        assert limits.breakaway_denied
        assert limits.active_process_limit == C.JOB_ACTIVE_PROCESS_LIMIT
        assert limits.job_memory_limit_bytes == C.JOB_MEMORY_LIMIT_BYTES
        block = limits.summary()
        assert block["kill_on_close"] is True
        assert block["breakaway_denied"] is True
        # ACTIVE_PROCESS | JOB_MEMORY | DIE_ON_UNHANDLED_EXCEPTION | KILL_ON_CLOSE
        assert block["limit_flags"] == "0x00002608", block
    finally:
        import ctypes
        from ctypes import wintypes
        C._kernel32.CloseHandle(wintypes.HANDLE(job))


def test_a_refusal_attestation_claims_no_job_limits():
    """No job, no limits. An absent job must not read as an unbounded one."""
    att = C.refusal_attestation("no containment here")
    assert att.job_limits is None
    assert att.summary()["job_limits"] is None


def test_the_list_of_things_the_caps_do_not_cover_still_names_the_network():
    """A SHRINKING honesty list is itself the defect.

    Job Objects have no network limit and cannot acquire one. If somebody ever
    deletes this entry because "we have a sandbox now", the claim silently
    grows past the mechanism, which is the exact failure this module's name was
    chosen to prevent.
    """
    blob = " ".join(C.JOB_LIMITS_DO_NOT_COVER).lower()
    assert "network" in blob
    assert "confidentiality" in blob
    # And it must not have quietly vanished from the module-wide list either.
    assert any("network" in v.lower() for v in C.unmeasured_vectors())


# --------------------------------------------------------------------------- #
# ALLOWED -- the boundary still lets real gate work through                    #
# --------------------------------------------------------------------------- #
def test_a_real_pytest_gate_still_passes_under_the_production_caps(tmp_path):
    """The half that makes this a boundary instead of an outage.

    Production caps, no overrides: a genuine pytest run inside the worktree
    exits 0 AND produces evidence. MEASURED alongside this, with the job's own
    accounting counters: a git-subprocess-heavy run of this repo's
    ``tests/test_spine_attempt.py`` used 4 processes cumulatively against a cap
    of 96.
    """
    worktree, low_temp = _arena(tmp_path)
    (worktree / "test_real.py").write_text(textwrap.dedent('''
        import subprocess, sys

        def test_arithmetic_still_works():
            assert 2 + 2 == 4

        def test_the_candidate_may_still_spawn_a_subprocess():
            """A gate that cannot shell out is an outage for most real suites."""
            out = subprocess.run([sys.executable, "-c", "print(7*6)"],
                                 capture_output=True, text=True)
            assert out.stdout.strip() == "42"

        def test_the_candidate_may_still_write_inside_its_own_worktree(tmp_path):
            p = tmp_path / "scratch.txt"
            p.write_text("candidate output")
            assert p.read_text() == "candidate output"
    '''), encoding="utf-8")

    rc, out, att = _run_contained(
        tmp_path, worktree, low_temp,
        attempt_mod.pytest_gate_argv(["test_real.py"]))

    assert rc == 0, f"a legitimate contained pytest run failed: rc={rc}\n{out}"
    assert "3 passed" in out, f"the gate did not run the tests:\n{out}"
    assert att.job_limits.active_process_limit == C.JOB_ACTIVE_PROCESS_LIMIT


def test_the_docref_gate_reaches_a_verdict_as_the_contained_child(tmp_path):
    """The gate that was written to be containment's easiest customer.

    ``docref_gate`` advertises "pure reads, no git, no subprocess, no network;
    safe as the low-integrity contained gate child". This runs the real module
    as that child -- it scans a corpus with :mod:`ast`, reaches its own verdict
    and reports it through the one allowed handle. The verdict is FAIL here
    (the named reference was not fixed), which is the point: a gate that could
    only produce PASS under containment would be evidence of nothing.
    """
    worktree, low_temp = _arena(tmp_path)
    docs = worktree / "docs"
    docs.mkdir()
    (worktree / "mod.py").write_text("def real_function():\n    return 1\n",
                                     encoding="utf-8")
    (docs / "a.md").write_text(
        "See `mod.py` for the real thing, and `gone.py` for the broken claim.\n",
        encoding="utf-8")

    rc, out, att = _run_contained(tmp_path, worktree, low_temp, [
        sys.executable, "-m", "daedalus.spine.docref_gate",
        "--repo-root", ".", "--doc", "docs/a.md",
        "--expect-resolving", "1", "--ref", "gone.py"])

    assert out.strip(), "the docref gate produced NO evidence under containment"
    assert "docref-gate: after-scan" in out, (
        f"the corpus scan did not run inside the contained child, so this "
        f"proves nothing about docref_gate under containment:\n{out}")
    assert rc in (1, 2), f"unexpected verdict rc={rc}\n{out}"
    assert att.job_limits is not None and att.job_limits.kill_on_close
