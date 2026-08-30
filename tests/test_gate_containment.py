# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""BOUNDED HANDLE INHERITANCE, and the gate that now runs behind it.

THE GATE IS THE EXECUTION POINT. `_capture_patch` was launching candidate-
selected programs through git filters and that has been closed; what remains,
and what matters more, is that `pytest_gate` runs pytest OVER CANDIDATE-WRITTEN
CODE. Containing everything except the gate contains nothing.

THE CONFLICT THIS FILE EXISTS TO PIN. Containment needed handle inheritance
OFF -- measured, with it on a Low child wrote a Medium-integrity file through a
handle its parent had already opened, because MIC authorises a handle when it
is OPENED, not per write. But the gate's output redirection IS an inherited
handle, and it cannot become a pipe: the loop polls a cancel token instead of
draining, so a chatty run deadlocks.

The ruling was bounded inheritance: EXACTLY ONE handle crosses, named through
PROC_THREAD_ATTRIBUTE_HANDLE_LIST, on a Low-labelled file, append-only, with
target and rights checked ON THE OPENED HANDLE. The invariant it serves:

    NO CAPABILITY CROSSES THE BOUNDARY THAT THE LOW CHILD COULD NOT HAVE
    OBTAINED ITSELF.

EVERY REFUSAL BELOW HAS A CONTROL. A refusal test with no control proves only
that something failed; several of these controls reconstruct the attack by
hand (`_spawn_unbounded`) so that what is being claimed is "the guard stops
it", not "it did not happen today".
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path

import pytest

import daedalus.spine.attempt as attempt_mod
from daedalus.spine import containment as C

pytestmark = pytest.mark.skipif(
    not C.platform_supported(),
    reason="MIC write containment is a win32 mechanism")


# --------------------------------------------------------------------------- #
# arena                                                                        #
# --------------------------------------------------------------------------- #
def _arena(tmp_path: Path):
    """A Medium scratch dir, a Low worktree, a Low TEMP, and a Medium canary."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    C.label_low_integrity(worktree)
    low_temp = tmp_path / "lowtemp"
    low_temp.mkdir()
    C.label_low_integrity(low_temp)
    canary = tmp_path / "medium_canary.txt"
    canary.write_text("original\n", encoding="utf-8")
    return worktree, low_temp, canary


def _child_env(low_temp: Path) -> dict:
    env = dict(os.environ)
    env["TEMP"] = env["TMP"] = str(low_temp)
    return env


# The probe runs INSIDE the contained child and reports through the one handle
# it is allowed to have. Everything it prints is therefore also evidence that
# appending works -- a probe that could not report would look like a refusal.
_PROBE = r'''
import ctypes, os, sys
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.GetStdHandle.restype = ctypes.c_void_p
h = ctypes.c_void_p(k.GetStdHandle(-11))

def emit(name, value):
    line = ("%s=%s\n" % (name, value)).encode()
    n = ctypes.c_ulong()
    k.WriteFile(h, line, len(line), ctypes.byref(n), None)

emit("alive", os.getpid())

buf = ctypes.create_string_buffer(64)
n = ctypes.c_ulong()
ok = k.ReadFile(h, buf, 64, ctypes.byref(n), None)
emit("read", "ALLOWED" if ok else "REFUSED:%d" % ctypes.get_last_error())

ok = k.SetEndOfFile(h)
emit("truncate", "ALLOWED" if ok else "REFUSED:%d" % ctypes.get_last_error())

sentinel = int(sys.argv[1])
n2 = ctypes.c_ulong()
ok = k.WriteFile(ctypes.c_void_p(sentinel), b"PWNED", 5, ctypes.byref(n2), None)
emit("sentinel", "ALLOWED" if ok else "REFUSED:%d" % ctypes.get_last_error())

p = ctypes.create_unicode_buffer(1024)
k.GetFinalPathNameByHandleW(h, p, 1024, 0)
path = p.value.replace("\\\\?\\", "")
emit("path", path)
for label, fn in (("delete", lambda: os.remove(path)),
                  ("rename", lambda: os.rename(path, path + ".moved")),
                  ("reopen_write", lambda: open(path, "w").close())):
    try:
        fn()
        emit(label, "ALLOWED")
    except Exception as e:
        emit(label, "REFUSED:%s" % type(e).__name__)

try:
    open(sys.argv[2], "w").write("PWNED")
    emit("medium_by_path", "ALLOWED")
except Exception as e:
    emit("medium_by_path", "REFUSED:%s" % type(e).__name__)
'''


def _inheritable_write_handle(path: Path) -> int:
    """A deliberately INHERITABLE write handle on a Medium file: the sentinel.

    This is the exact shape of the measured bypass -- a capability the parent
    holds and the child could not obtain for itself. It is planted on purpose
    so the allowlist has something real to hide.
    """
    from ctypes import wintypes

    class _SA(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD),
                    ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    sa = _SA(ctypes.sizeof(_SA), None, True)
    handle = C._kernel32.CreateFileW(
        str(path), 0x0002 | 0x00100000,          # FILE_WRITE_DATA|SYNCHRONIZE
        0x7, ctypes.byref(sa), 3, 0x80, None)    # OPEN_EXISTING
    assert handle and handle != ctypes.c_void_p(-1).value, "sentinel not opened"
    return int(handle)


def _spawn_unbounded(argv, cwd, env, log_handle):
    """THE CONTROL: Low integrity, bInheritHandles=True, NO allowlist.

    Deliberately not reachable through `spawn_contained` -- the module makes
    this state unrepresentable, so the only way to demonstrate that the
    allowlist is what stops the attack is to rebuild the attack by hand. If
    this ever STOPS working, the refusal tests below have quietly become
    vacuous and the control is what says so.
    """
    from ctypes import wintypes

    token, _sid = C._low_integrity_token()
    startup = C._STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(C._STARTUPINFOEXW)
    startup.StartupInfo.dwFlags = C._STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = None
    startup.StartupInfo.hStdOutput = wintypes.HANDLE(log_handle)
    startup.StartupInfo.hStdError = wintypes.HANDLE(log_handle)
    items = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
    block = ctypes.create_unicode_buffer(items)
    info = C._PROCESS_INFORMATION()
    ok = C._advapi32.CreateProcessAsUserW(
        token, None,
        ctypes.create_unicode_buffer(subprocess.list2cmdline(
            [str(a) for a in argv])),
        None, None,
        True,                                    # <-- unbounded inheritance
        C._CREATE_NEW_PROCESS_GROUP | C._CREATE_UNICODE_ENVIRONMENT,
        block, str(cwd), ctypes.byref(startup), ctypes.byref(info))
    assert ok, f"the control could not launch (winerror {ctypes.get_last_error()})"
    C._kernel32.WaitForSingleObject(info.hProcess, 120000)
    code = wintypes.DWORD()
    C._kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    for handle in (info.hProcess, info.hThread):
        C._kernel32.CloseHandle(wintypes.HANDLE(handle))
    return int(code.value)


def _parse(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """Run the probe ONCE under bounded inheritance; every test reads a field.

    One spawn rather than seven: the properties are independent assertions
    about the same measured run, and a contained spawn costs three icacls
    round-trips.
    """
    tmp_path = tmp_path_factory.mktemp("bounded")
    worktree, low_temp, canary = _arena(tmp_path)
    script = worktree / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    sentinel = _inheritable_write_handle(canary)

    log = C.open_low_append_log(tmp_path / "gate.out")
    proc = C.spawn_contained(
        [sys.executable, str(script), str(sentinel), str(canary)],
        cwd=worktree, env=_child_env(low_temp), log=log)
    try:
        code = proc.wait(timeout_s=120)
    finally:
        proc.close()
        log.close()
    text = (tmp_path / "gate.out").read_text(encoding="utf-8", errors="replace")
    assert text.strip(), f"the contained child reported nothing (exit {code})"
    return _parse(text), canary, log


# --------------------------------------------------------------------------- #
# THE ALLOW SIDE. Without this the rest is a refusal machine.                   #
# --------------------------------------------------------------------------- #
def test_LOW_APPEND_THROUGH_THE_INHERITED_HANDLE_WORKS(probe):
    """Every other test in this file is worthless if this one fails."""
    fields, _canary, _log = probe
    assert fields.get("alive"), "the child never wrote a byte through its handle"
    assert int(fields["alive"]) > 0
    # and the LAST field arrived too, so the handle stayed usable throughout
    assert fields.get("medium_by_path"), "the handle stopped working mid-run"


def test_a_contained_pytest_gate_passes_a_real_worktree(tmp_path):
    """The product-level allow case: contained, and still a usable gate.

    A gate that refuses everything would satisfy every refusal test in this
    file while making the loop unusable, so this runs a real pytest -- including
    a `capfd` test, because pytest's fd-level capture is the thing that broke
    when the handle's rights were first set too tight.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (worktree / "test_capfd.py").write_text(
        'def test_capfd(capfd):\n'
        '    print("hello")\n'
        '    assert capfd.readouterr().out == "hello\\n"\n', encoding="utf-8")
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=300)(ctx)

    assert verdict.passed is True, verdict.output[-2000:]
    assert "2 passed" in verdict.output
    assert verdict.containment is not None
    assert verdict.containment.contained is True


# --------------------------------------------------------------------------- #
# A MEDIUM-INTEGRITY TARGET IS REFUSED                                         #
# --------------------------------------------------------------------------- #
def test_a_medium_integrity_log_target_is_REFUSED(tmp_path):
    """The target is checked ON THE HANDLE, and an unlabelled file is Medium.

    This is the guard that keeps bounded inheritance honest: a handle on a
    Medium file is precisely the capability the child could not have obtained
    itself, which is the measured bypass.
    """
    target = tmp_path / "medium.out"
    target.write_bytes(b"")

    with pytest.raises(C.ContainmentUnavailable) as excinfo:
        C.LowIntegrityLog(target)

    assert "non-Low target" in str(excinfo.value)
    assert "Medium" in str(excinfo.value)


def test_a_low_labelled_log_target_is_ACCEPTED(tmp_path):
    """The control for the refusal above: the SAME file, labelled Low."""
    target = tmp_path / "low.out"
    target.write_bytes(b"")
    C.label_low_integrity_file(target)

    with C.LowIntegrityLog(target) as log:
        assert log.integrity_label == C.LOW_INTEGRITY_SID
        assert log.granted_access == C.LOW_APPEND_ACCESS


def test_the_verified_target_cannot_be_SWAPPED_while_the_handle_is_open(tmp_path):
    """A path-only check would lose to a swap. Two things stop one here.

    1. IDENTITY, NOT NAME. The label is read through a second handle and tied
       to the append handle by 128-bit FILE ID, so what was verified is the
       object the child will write to.
    2. THE NAME CANNOT MOVE AT ALL. FILE_SHARE_READ only means no second opener
       gets DELETE, and a rename needs DELETE -- so the swap cannot even be
       staged. Strong enough that THIS process, at Medium, cannot do it either,
       which is the point: the guarantee does not depend on who is asking.
    """
    target = tmp_path / "low.out"
    target.write_bytes(b"")
    C.label_low_integrity_file(target)
    with C.LowIntegrityLog(target) as log:
        with pytest.raises(PermissionError):
            target.rename(tmp_path / "moved.out")
        with pytest.raises(PermissionError):
            target.unlink()
        with pytest.raises(PermissionError):
            target.write_bytes(b"forged gate output")
        log.verify()                                # unchanged, still Low
        assert log.integrity_label == C.LOW_INTEGRITY_SID
    # ...and once the handle is closed the ordinary world resumes: the guard is
    # the open handle, not a permanent property of the file.
    target.unlink()


def test_a_raw_handle_can_never_be_handed_to_the_spawner(tmp_path):
    """`log` is typed, so "bounded" is structural rather than a convention."""
    worktree, low_temp, _canary = _arena(tmp_path)
    for forged in (7, "7", object(), None.__class__):
        with pytest.raises(C.ContainmentUnavailable) as excinfo:
            C.spawn_contained([sys.executable, "-c", "pass"], cwd=worktree,
                              env=_child_env(low_temp), log=forged)
        assert "LowIntegrityLog" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# A HANDLE NOT ON THE ALLOWLIST IS INVISIBLE                                   #
# --------------------------------------------------------------------------- #
def test_a_handle_off_the_allowlist_is_INVISIBLE_to_the_child(probe):
    """The sentinel: inheritable, write access, Medium file, NOT allowlisted."""
    fields, canary, _log = probe
    assert fields["sentinel"].startswith("REFUSED"), (
        "a handle the parent never allowlisted was usable in the child")
    assert fields["sentinel"].endswith(":6"), (
        f"expected ERROR_INVALID_HANDLE (6), got {fields['sentinel']}")
    assert canary.read_text(encoding="utf-8") == "original\n"


def test_CONTROL_the_same_sentinel_IS_usable_without_the_allowlist(tmp_path):
    """THE ATTACK, WORKING. Remove the allowlist and the bypass comes back.

    Same Low child, same inheritable sentinel handle, same Medium target. The
    only difference is that `bInheritHandles=True` is not paired with
    PROC_THREAD_ATTRIBUTE_HANDLE_LIST. The canary is overwritten through a
    handle the child could never have opened -- MIC bypassed, exactly as the
    module docstring records. If this test ever goes green-by-refusal, the
    guarded test above has stopped proving anything.
    """
    worktree, low_temp, canary = _arena(tmp_path)
    script = worktree / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    sentinel = _inheritable_write_handle(canary)
    log = C.open_low_append_log(tmp_path / "gate.out")
    try:
        _spawn_unbounded([sys.executable, str(script), str(sentinel),
                          str(canary)],
                         worktree, _child_env(low_temp), log.handle)
    finally:
        log.close()
    fields = _parse((tmp_path / "gate.out").read_text(encoding="utf-8",
                                                      errors="replace"))

    assert fields.get("sentinel") == "ALLOWED", (
        "the unbounded control did not reproduce the bypass, so the guarded "
        "test above proves nothing -- fix the control before trusting it")
    assert "PWNED" in canary.read_text(encoding="utf-8"), (
        "the Low child did not actually write the Medium canary")
    # ...and MIC alone would have stopped it. The handle is the whole bypass.
    assert fields["medium_by_path"].startswith("REFUSED")


# --------------------------------------------------------------------------- #
# READ, TRUNCATE AND DELETE THROUGH THE INHERITED HANDLE ALL FAIL              #
# --------------------------------------------------------------------------- #
def test_READ_through_the_inherited_handle_fails(probe):
    fields, _canary, _log = probe
    assert fields["read"] == "REFUSED:5", (
        f"the child could read its own log back: {fields['read']}")


def test_TRUNCATE_through_the_inherited_handle_fails(probe):
    """Append without WRITE_DATA: the child cannot unwrite what it wrote."""
    fields, _canary, _log = probe
    assert fields["truncate"] == "REFUSED:5", (
        f"SetEndOfFile succeeded through the handle: {fields['truncate']}")


def test_DELETE_and_REPLACE_of_the_log_by_path_both_fail(probe):
    """Not a rights property -- a SHARE-MODE property, and it was measured.

    The log is Low-labelled (that is what makes the handle safe), so a Low
    child may delete it. The first guarded run did exactly that, and could then
    have written a replacement full of fabricated gate output. FILE_SHARE_READ
    only -- no SHARE_DELETE, no SHARE_WRITE -- is what closes it.
    """
    fields, _canary, _log = probe
    assert fields["delete"].startswith("REFUSED"), fields["delete"]
    assert fields["rename"].startswith("REFUSED"), fields["rename"]
    assert fields["reopen_write"].startswith("REFUSED"), fields["reopen_write"]


def test_CONTROL_read_and_truncate_work_on_a_fully_opened_handle(tmp_path):
    """It is the RIGHTS that refuse, not the file being unreadable.

    Without this, `read=REFUSED` would be consistent with "there was nothing to
    read" or "this file object cannot be read at all".
    """
    target = tmp_path / "low.out"
    target.write_bytes(b"some captured output\n")
    C.label_low_integrity_file(target)

    with open(target, "r+b") as handle:          # full access, same process
        assert handle.read() == b"some captured output\n"
        handle.seek(0)
        handle.truncate()
    assert target.read_bytes() == b""
    target.unlink()                              # ...and DELETE works too


def test_the_shipped_mask_is_exactly_append_read_attributes_synchronize(tmp_path):
    """An EQUALITY, so a widened mask cannot arrive unnoticed.

    FILE_READ_ATTRIBUTES is the one right the ruling did not name, and the
    module states why in `WHY_READ_ATTRIBUTES`: without it `os.fstat(1)` raises,
    pytest concludes fd 1 is invalid and sends every byte to os.devnull --
    measured, exit 0 with an empty report. The forbidden bits are asserted
    individually so the reason for each is visible.
    """
    target = tmp_path / "low.out"
    target.write_bytes(b"")
    C.label_low_integrity_file(target)
    with C.LowIntegrityLog(target) as log:
        assert log.granted_access == C.LOW_APPEND_ACCESS == 0x00100084
        for bit, meaning in ((0x0001, "FILE_READ_DATA"),
                             (0x0002, "FILE_WRITE_DATA"),
                             (0x0008, "FILE_READ_EA"),
                             (0x0010, "FILE_WRITE_EA"),
                             (0x0020, "FILE_EXECUTE"),
                             (0x0100, "FILE_WRITE_ATTRIBUTES"),
                             (0x00010000, "DELETE"),
                             (0x00020000, "READ_CONTROL"),
                             (0x00040000, "WRITE_DAC"),
                             (0x00080000, "WRITE_OWNER"),
                             (0x01000000, "ACCESS_SYSTEM_SECURITY")):
            assert not (log.granted_access & bit), (
                f"the inherited handle carries {meaning}")
    assert "os.fstat" in C.WHY_READ_ATTRIBUTES
    assert "devnull" in C.WHY_READ_ATTRIBUTES


# --------------------------------------------------------------------------- #
# A CHATTY GATE DOES NOT BLOCK CANCELLATION                                    #
# --------------------------------------------------------------------------- #
def _chatty_source(count: int = 400, width: int = 400) -> str:
    """`count` SEPARATE failing tests -- one test with `count` asserts stops at
    the first, which produced a 996-byte report and proved nothing."""
    return "\n".join(
        f"def test_fail_{i}():\n    assert False, {'x' * width!r}\n"
        for i in range(count))

_SLOW = (
    "import pathlib, time\n"
    "def test_slow():\n"
    "    pathlib.Path(__file__).with_name('gate_ready').write_text('up')\n"
    "    for _ in range(600):\n"
    "        print('still here ' * 30)\n"
    "        time.sleep(0.1)\n")


def test_a_CHATTY_contained_gate_completes_instead_of_deadlocking(tmp_path):
    """Far more output than a pipe buffer, and the gate still finishes.

    400 failing assertions with 400-byte messages is a report of hundreds of
    kilobytes through the one inherited handle, while this loop is polling the
    cancel token and reading nothing. On a pipe that is a deadlock; on a file
    it is just a big file.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_chatty.py").write_text(_chatty_source(), encoding="utf-8")
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=300, poll_s=0.05)(ctx)

    assert verdict.timed_out is False, "the chatty gate wedged"
    assert verdict.cancelled is False
    assert verdict.passed is False               # the candidate's tests failed
    assert len(verdict.output) > 64 * 1024, (
        f"only {len(verdict.output)} bytes came back; this test is not "
        f"exercising a full pipe buffer any more")


def test_a_chatty_contained_gate_is_still_CANCELLABLE(tmp_path):
    """The property the file redirect exists for: cancel wins over output."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_slow.py").write_text(_SLOW, encoding="utf-8")
    ready = worktree / "gate_ready"
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"),
        is_cancelled=lambda: ready.exists())

    started = time.monotonic()
    verdict = attempt_mod.pytest_gate(timeout_s=300, poll_s=0.05)(ctx)
    elapsed = time.monotonic() - started

    assert ready.exists(), "the gate child never reached its running state"
    assert verdict.cancelled is True, verdict.output[-800:]
    assert verdict.passed is False
    assert elapsed < 60.0, f"cancellation took {elapsed:.1f}s"


def test_CONTROL_an_undrained_PIPE_wedges_the_same_chatty_writer(tmp_path):
    """THE DEADLOCK, DEMONSTRATED. This is why output goes to a file.

    Identical polling loop, identical chatty child, output on a pipe nobody
    reads. The child blocks on a full pipe buffer and the loop never sees it
    exit -- which on the real path would mean an attempt that cannot be
    cancelled at exactly the moment cancelling matters.
    """
    from daedalus.spine.cancel import ManagedProcess

    script = tmp_path / "chatty.py"
    script.write_text(
        "import sys\n"
        "for _ in range(200000):\n"
        "    sys.stdout.write('noise ' * 40 + '\\n')\n", encoding="utf-8")

    proc = ManagedProcess([sys.executable, str(script)], cwd=str(tmp_path),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 8.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)                     # poll, never drain
        assert proc.poll() is None, (
            "the chatty writer finished through an undrained pipe, so this "
            "control no longer demonstrates the deadlock the gate avoids")
    finally:
        proc.close(grace_s=0.0)


# --------------------------------------------------------------------------- #
# THE ATTESTATION -- what happened, not what was asked for                     #
# --------------------------------------------------------------------------- #
def test_the_attestation_records_MEASURED_facts(tmp_path):
    """Every field is read back off the object it describes.

    The token's level is read from the token, the labels from the objects, the
    rights from the handle. An attestation assembled from the arguments the
    caller passed would say "contained" for a run that was not.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                         encoding="utf-8")
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=300)(ctx)
    att = verdict.containment

    assert att.contained is True
    assert att.requested is True and att.executes_candidate is True
    assert att.low_token_obtained is True
    assert att.token_integrity_sid == C.LOW_INTEGRITY_SID
    assert att.worktree_labelled is True
    assert att.worktree_label == C.LOW_INTEGRITY_SID
    assert att.log_label == C.LOW_INTEGRITY_SID
    assert att.log_granted_access == C.LOW_APPEND_ACCESS
    assert att.inherited_handle_count == 1, "more than one handle crossed"
    assert att.platform == sys.platform
    assert att.reason is None


def test_the_attestation_reaches_the_LEDGER_shape(tmp_path):
    """`GateResult.summary()` is what is written to the spine ledger."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                         encoding="utf-8")
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    block = attempt_mod.pytest_gate(timeout_s=300)(ctx).summary()["containment"]

    assert json.loads(json.dumps(block)) == block, "not JSON-safe"
    assert block["contained"] is True
    assert block["low_token_obtained"] is True
    assert block["worktree_labelled"] is True
    assert block["log_granted_access"] == "0x00100084"
    assert block["inherited_handle_count"] == 1
    assert block["mechanism"] == "mic-low+job+bounded-inherit"


def test_an_unsupported_platform_is_a_HARD_REFUSAL_not_a_downgrade(tmp_path,
                                                                   monkeypatch):
    """The whole contract in one test: no silent uncontained run, ever."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                         encoding="utf-8")
    monkeypatch.setattr(C, "platform_supported", lambda: False)
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=300)(ctx)

    assert verdict.passed is False, "an uncontainable gate returned a PASS"
    assert "without MIC write containment" in verdict.output
    assert verdict.containment.contained is False
    assert verdict.containment.requested is True
    assert verdict.containment.reason and "win32" in verdict.containment.reason
    # and it did not quietly run anyway
    assert verdict.returncode is None


def test_a_caller_declares_the_WORKLOAD_not_a_weaker_security_default():
    """There is no `contained=False`. The escape hatch names the workload.

    A boolean called `contained` reads as a knob and would be turned; a boolean
    called `executes_candidate` is a claim about the runner that a reviewer can
    check. The default is the safe one either way.
    """
    import inspect

    sig = inspect.signature(attempt_mod.pytest_gate)
    assert sig.parameters["executes_candidate"].default is True
    for forbidden in ("contained", "containment", "uncontained", "unsafe",
                      "skip_containment", "allow_uncontained"):
        assert forbidden not in sig.parameters, (
            f"pytest_gate exposes {forbidden!r}: containment became a knob")


def test_declaring_no_candidate_code_takes_the_uncontained_path(tmp_path):
    """The allow case for the declaration -- and it is ATTESTED as uncontained.

    A gate that does not execute candidate code is a legitimate configuration;
    a gate that quietly reports itself contained when it is not is the thing
    this whole attestation exists to prevent.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                         encoding="utf-8")
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=300,
                                      executes_candidate=False)(ctx)

    assert verdict.passed is True, verdict.output[-1000:]
    assert verdict.containment.contained is False
    assert verdict.containment.requested is False
    assert verdict.containment.executes_candidate is False
    assert "does not execute candidate code" in verdict.containment.reason


# --------------------------------------------------------------------------- #
# NO EMPTY GREEN -- the regression this work actually produced                 #
# --------------------------------------------------------------------------- #
class _FakeProc:
    """A child that exits 0. Whether it wrote anything is the parameter."""

    def __init__(self, log, text):
        self._log, self._text = log, text
        self.attestation = C.refusal_attestation("fake")

    def poll(self):
        if self._text:
            with open(self._log, "ab") as handle:
                handle.write(self._text)
            self._text = b""
        return 0

    @property
    def returncode(self):
        return 0

    def cancel(self, grace_s=0.0):
        return None

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None


def _fake_gate_child(text, monkeypatch):
    def _factory(argv, worktree, out_path, tmpdir):
        out_path.write_bytes(b"")
        return _FakeProc(out_path, text), _NullLog()
    monkeypatch.setattr(attempt_mod, "_contained_gate_child", _factory)


class _NullLog:
    def close(self):
        return None


def test_a_gate_that_exits_0_with_NO_output_is_not_a_PASS(tmp_path, monkeypatch):
    """MEASURED REGRESSION, not a hypothetical.

    With the log handle opened without FILE_READ_ATTRIBUTES, `os.fstat(1)`
    raised inside the child, pytest concluded fd 1 was invalid, redirected
    every byte to os.devnull and exited 0. The gate reported PASS on a
    zero-byte report. The mask was fixed; this guard stays, because the next
    thing to blind the evidence channel will not announce itself either.
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _fake_gate_child(b"", monkeypatch)
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=60)(ctx)

    assert verdict.returncode == 0
    assert verdict.passed is False, "a zero-byte gate report was reported green"
    assert "NO output" in verdict.output


def test_CONTROL_the_same_gate_WITH_output_is_a_pass(tmp_path, monkeypatch):
    """Otherwise the guard above would be indistinguishable from "always fail"."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _fake_gate_child(b"1 passed in 0.01s\n", monkeypatch)
    ctx = attempt_mod.RunnerContext(
        worktree=worktree, branch="b", base_revision="0" * 40,
        task=attempt_mod.TaskSpec("t", "i"), is_cancelled=lambda: False)

    verdict = attempt_mod.pytest_gate(timeout_s=60)(ctx)

    assert verdict.passed is True
    assert "1 passed" in verdict.output


# --------------------------------------------------------------------------- #
# THE KILL SWITCH MUST STILL REACH THE CONTAINED CHILD                         #
# --------------------------------------------------------------------------- #
def test_a_contained_child_joins_the_kill_switchs_sweep(tmp_path):
    """The backstop is not optional, and the coupling is pinned here.

    `KillSwitch.stop_children` sweeps every live child in this interpreter
    precisely to catch the one whose driver forgot to thread the cancel token
    through. The contained gate child comes from a different spawn path than
    `ManagedProcess`, so without an explicit registration it would be the one
    process the kill switch cannot reach. If `cancel`'s registry is ever
    renamed, this goes red instead of the sweep going quietly blind.
    """
    from daedalus.spine.cancel import live_managed_processes

    worktree, low_temp, _canary = _arena(tmp_path)
    script = worktree / "sleeper.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    log = C.open_low_append_log(tmp_path / "gate.out")
    proc = C.spawn_contained([sys.executable, str(script)], cwd=worktree,
                             env=_child_env(low_temp), log=log)
    try:
        assert proc in live_managed_processes(), (
            "a contained child is invisible to the kill switch's sweep")
        result = proc.cancel(grace_s=0.0)
        assert result.killed is True
        assert proc not in live_managed_processes()
    finally:
        proc.close()
        log.close()
