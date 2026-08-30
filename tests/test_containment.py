# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""MIC write containment: the claims in the docstring, each one measured here.

The module under test is `daedalus/spine/containment.py`. Its docstring lists
exactly what the kernel refuses and exactly what it does not. Every line of
that list is an assertion, so this file exists to make sure the list stays a
measurement rather than becoming a promise.

WHY THIS MATTERS MORE THAN USUAL. Prior containment in this repo was written in
Python -- path checks, reparse-point detection, no-follow walkers -- and a day
of adversarial review established its ceiling: the "move-in" attack
(`os.rename(primary_checkout, worktree/moved_in)`) uses no reparse point at all
and is recorded in the handoff as "open by construction and no reparse check
can ever close it". These tests check whether the OS closes what our code
could not.

TWO PROPERTIES ARE TESTED IN PAIRS, ALWAYS:
  * the attack is REFUSED under containment, and
  * the same operation SUCCEEDS without it (or inside the worktree).
A containment that refuses everything would pass every refusal test on its own
while making the product unusable, so the allow-side is never optional.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from daedalus.spine import containment as C

pytestmark = pytest.mark.skipif(
    not C.platform_supported(),
    reason="MIC write containment is a win32 mechanism")


def _arena():
    """A primary checkout with a canary, plus a Low-labelled worktree."""
    base = Path(tempfile.gettempdir()) / f"contain-{uuid.uuid4().hex[:8]}"
    worktree, primary = base / "worktree", base / "primary"
    worktree.mkdir(parents=True)
    primary.mkdir(parents=True)
    (primary / "victim.txt").write_text("canary\n", encoding="utf-8")
    C.label_low_integrity(worktree)
    return base, worktree, primary


def _run_contained(worktree: Path, body: str, spec: dict) -> dict:
    """Execute `body` inside a contained child and return its findings."""
    script = worktree.parent / f"probe-{uuid.uuid4().hex[:6]}.py"
    script.write_text(
        "import json, os, shutil, subprocess, sys\n"
        "spec = json.loads(sys.argv[1])\n"
        "res = {}\n"
        "def rec(name, fn):\n"
        "    try:\n"
        "        fn()\n"
        "        res[name] = 'ALLOWED'\n"
        "    except Exception as e:\n"
        "        res[name] = type(e).__name__\n"
        f"{body}\n"
        "open(sys.argv[2], 'w').write(json.dumps(res))\n",
        encoding="utf-8")
    out = worktree / f"res-{uuid.uuid4().hex[:6]}.json"
    proc = C.spawn_contained([sys.executable, str(script), json.dumps(spec),
                              str(out)], cwd=worktree)
    try:
        code = proc.wait(timeout_s=120)
    finally:
        proc.close()
    assert out.exists(), f"the contained child produced nothing (exit {code})"
    return json.loads(out.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# the allow side -- without it every refusal below proves nothing              #
# --------------------------------------------------------------------------- #
def test_a_contained_child_can_still_do_its_job():
    base, worktree, _primary = _arena()
    res = _run_contained(
        worktree,
        "rec('write_own_worktree', lambda: open(spec['inside'], 'w').write('x'))\n"
        "rec('mkdir_own_worktree', lambda: os.makedirs(spec['subdir']))",
        {"inside": str(worktree / "ok.txt"), "subdir": str(worktree / "sub")})
    assert res["write_own_worktree"] == "ALLOWED"
    assert res["mkdir_own_worktree"] == "ALLOWED"


# --------------------------------------------------------------------------- #
# the refusals, one property per test                                          #
# --------------------------------------------------------------------------- #
def test_the_primary_checkout_cannot_be_written():
    base, worktree, primary = _arena()
    res = _run_contained(
        worktree,
        "rec('write', lambda: open(spec['target'], 'w').write('x'))",
        {"target": str(primary / "escape.txt")})
    assert res["write"] != "ALLOWED", "a contained child wrote the primary checkout"
    assert not (primary / "escape.txt").exists()


def test_a_file_outside_cannot_be_deleted_or_renamed():
    """Deleting is not the same permission as writing, so it gets its own test."""
    base, worktree, primary = _arena()
    victim = primary / "victim.txt"
    res = _run_contained(
        worktree,
        "rec('delete', lambda: os.remove(spec['victim']))\n"
        "rec('rename', lambda: os.rename(spec['victim'], spec['victim'] + '.moved'))\n"
        "rec('rmtree', lambda: shutil.rmtree(spec['primary']))",
        {"victim": str(victim), "primary": str(primary)})
    assert res["delete"] != "ALLOWED"
    assert res["rename"] != "ALLOWED"
    assert res["rmtree"] != "ALLOWED"
    assert victim.read_text(encoding="utf-8").strip() == "canary"


def test_THE_MOVE_IN_ATTACK_IS_REFUSED():
    """The one the handoff calls unclosable by any code check.

    `os.rename(primary_checkout, worktree/moved_in)` involves no reparse point,
    so no amount of link inspection can stop it. It is a WRITE on the primary
    checkout, and that is what the kernel refuses.
    """
    base, worktree, primary = _arena()
    res = _run_contained(
        worktree,
        "rec('move_in', lambda: os.rename(spec['primary'], spec['target']))",
        {"primary": str(primary), "target": str(worktree / "moved_in")})
    assert res["move_in"] != "ALLOWED", "the move-in attack succeeded"
    assert primary.is_dir()
    assert (primary / "victim.txt").exists()


def test_a_junction_cannot_be_used_to_reach_outside():
    base, worktree, primary = _arena()
    res = _run_contained(
        worktree,
        "def mk():\n"
        "    r = subprocess.run(['cmd', '/c', 'mklink', '/J', spec['link'],\n"
        "                        spec['primary']], capture_output=True, text=True)\n"
        "    if r.returncode != 0:\n"
        "        raise OSError('mklink refused')\n"
        "rec('create_junction', mk)\n"
        "rec('write_through', lambda: open(os.path.join(spec['link'], 'x.txt'), 'w').write('x'))",
        {"link": str(worktree / "link"), "primary": str(primary)})
    assert res["write_through"] != "ALLOWED"
    assert not (primary / "x.txt").exists()


def test_a_medium_integrity_child_cannot_be_spawned():
    """If a contained process could start an uncontained one, this is theatre."""
    base, worktree, primary = _arena()
    target = primary / "via_child.txt"
    res = _run_contained(
        worktree,
        "def spawn():\n"
        "    r = subprocess.run([sys.executable, '-c',\n"
        "                        \"open(r'\" + spec['target'] + \"','w').write('x')\"],\n"
        "                       capture_output=True)\n"
        "    if not os.path.exists(spec['target']):\n"
        "        raise OSError('child did not write')\n"
        "rec('escape_via_child', spawn)",
        {"target": str(target)})
    assert res["escape_via_child"] != "ALLOWED"
    assert not target.exists()


# --------------------------------------------------------------------------- #
# THE BYPASS REVIEW FOUND, AND THE RULE THAT REPLACED THE OLD ONE               #
#                                                                               #
# THIS SECTION USED TO ASSERT `bInheritHandles=False` AS A LITERAL. That test   #
# was correct about the design it guarded and is deliberately GONE, not         #
# quietly deleted: it is replaced here, in place, by the sharper invariant the  #
# ruling put in its place. The old rule ("inheritance is off, full stop") was   #
# a proxy for:                                                                  #
#                                                                               #
#     NO CAPABILITY CROSSES THE BOUNDARY THAT THE LOW CHILD COULD NOT HAVE      #
#     OBTAINED ITSELF.                                                          #
#                                                                               #
# The proxy had to go because the gate -- the one place candidate code actually #
# runs -- needs its output redirected to a file, and on win32 that IS an        #
# inherited handle. Refusing the mechanism outright meant leaving the execution #
# point uncontained, which is strictly worse. So inheritance is BOUNDED: one    #
# handle, named through PROC_THREAD_ATTRIBUTE_HANDLE_LIST, append-only, on a    #
# Low-labelled target verified ON THE HANDLE. The measured attack -- a Medium   #
# file handle -- is still refused, and tests/test_gate_containment.py           #
# reproduces it working with the allowlist removed.                             #
# --------------------------------------------------------------------------- #
def test_inheritance_is_bounded_and_never_a_plain_boolean():
    """The structural half: there is no way to ask for unbounded inheritance."""
    import inspect

    sig = inspect.signature(C.spawn_contained)
    for forbidden in ("inherit", "inherit_handles", "bInheritHandles",
                      "close_fds", "handles", "stdout", "stderr", "fds"):
        assert forbidden not in sig.parameters, (
            f"spawn_contained exposes {forbidden!r}; a caller-supplied handle "
            f"cannot be verified, and an unverified inherited handle bypasses "
            f"MIC")
    # The ONLY way a handle crosses is an object this module built, on a target
    # this module labelled, with rights this module chose.
    assert sig.parameters["log"].default is None, (
        "inheriting a handle is no longer opt-in")
    assert sig.parameters["log"].annotation == "LowIntegrityLog | None", (
        "the log parameter is no longer typed to LowIntegrityLog, so a raw "
        "handle could be passed")

    src = inspect.getsource(C.spawn_contained)
    assert "inherit = allowlist is not None" in src, (
        "bInheritHandles is no longer the SAME EXPRESSION as 'is there an "
        "allowlist?'; the two can now disagree, and the state where they do is "
        "the measured bypass")
    assert "inherit,                            # bInheritHandles == allowlisted" in src
    assert "True," not in src.split("CreateProcessAsUserW(")[1].split(")")[0], (
        "bInheritHandles is a bare True somewhere in the spawn call")


def test_the_allowlisted_handle_carries_only_the_rights_this_module_chose():
    """The rights half, as a constant a reader can check against the docstring.

    FILE_READ_ATTRIBUTES is present and the module says why in
    `WHY_READ_ATTRIBUTES`: without it `os.fstat(1)` raises inside the child,
    pytest concludes fd 1 is invalid and sends every byte to os.devnull --
    measured, exit 0 with a zero-byte report. It is a READ right on a
    Low-labelled file the child could have opened itself, so nothing crosses
    that it did not already have. The write-shaped bits must all be absent.
    """
    assert C.LOW_APPEND_ACCESS == 0x0004 | 0x0080 | 0x00100000
    for bit, meaning in ((0x0001, "FILE_READ_DATA"),
                         (0x0002, "FILE_WRITE_DATA"),
                         (0x0100, "FILE_WRITE_ATTRIBUTES"),
                         (0x00010000, "DELETE"),
                         (0x00040000, "WRITE_DAC"),
                         (0x00080000, "WRITE_OWNER")):
        assert not (C.LOW_APPEND_ACCESS & bit), f"the mask grants {meaning}"
    assert "os.fstat" in C.WHY_READ_ATTRIBUTES
    assert "could have opened itself" in C.WHY_READ_ATTRIBUTES


def test_a_medium_target_is_still_refused_the_way_it_always_was(tmp_path):
    """The property the old literal-False test was really protecting.

    Bounded inheritance did not make a Medium-integrity handle acceptable. It
    made ONE Low-integrity handle acceptable.
    """
    medium = tmp_path / "medium.out"
    medium.write_bytes(b"")
    with pytest.raises(C.ContainmentUnavailable):
        C.LowIntegrityLog(medium)


# --------------------------------------------------------------------------- #
# the contract when containment is impossible                                  #
# --------------------------------------------------------------------------- #
def test_containment_never_downgrades_silently(monkeypatch):
    """A caller that asked for containment must not receive a bare process."""
    monkeypatch.setattr(C, "platform_supported", lambda: False)
    with pytest.raises(C.ContainmentUnavailable):
        C.spawn_contained([sys.executable, "-c", "pass"], cwd=os.getcwd())
    with pytest.raises(C.ContainmentUnavailable):
        C.label_low_integrity(os.getcwd())


def test_labelling_a_missing_directory_is_refused_not_ignored():
    with pytest.raises(C.ContainmentUnavailable):
        C.label_low_integrity(Path(tempfile.gettempdir()) / f"nope-{uuid.uuid4().hex}")


def test_the_module_states_what_it_did_NOT_measure():
    """Silence must never be mistaken for coverage.

    Reads are unrestricted, the network is unrestricted, and named pipes were
    not measured. All three are stated by the module itself, and this pins that
    they stay stated.

    A SHRINKING LIST IS ITSELF A DEFECT. Adding a mechanism is the moment the
    temptation to quietly drop an inconvenient line is strongest, so the count
    is pinned too: bounded inheritance ADDED four limits (path disclosure, the
    window after the handle closes, handle-value reuse, and what GrantedAccess
    does and does not prove) and removed none.
    """
    vectors = C.unmeasured_vectors()
    unmeasured = " ".join(vectors).lower()
    assert "named pipe" in unmeasured
    assert "network" in unmeasured
    assert "read" in unmeasured
    assert len(vectors) >= 7, (
        f"the unmeasured list shrank to {len(vectors)} entries; bounded "
        f"inheritance added four limits and none of them stopped being true")
    for added in ("getfinalpathnamebyhandle", "handle-value reuse",
                  "grantedaccess"):
        assert added in unmeasured, (
            f"a limit bounded inheritance introduced ({added}) is no longer "
            f"stated")
    doc = (C.__doc__ or "").lower()
    assert "confidentiality: none" in doc, (
        "the module no longer says plainly that it provides no confidentiality")


def test_reads_are_NOT_contained_and_the_docs_say_so():
    """An uncomfortable property, asserted rather than left implicit.

    If this ever starts failing because reads became restricted, that is good
    news -- but the claim in the docstring would then be wrong, and a wrong
    claim is the thing this repo keeps paying for.
    """
    base, worktree, primary = _arena()
    res = _run_contained(
        worktree,
        "rec('read_outside', lambda: open(spec['victim']).read())",
        {"victim": str(primary / "victim.txt")})
    assert res["read_outside"] == "ALLOWED", (
        "reads are now contained -- update the module's stated limits")
