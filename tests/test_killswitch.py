"""The kill switch must actually stop things, and the latency must be MEASURED.

Four properties, and a test may only be counted for one of them:

  STOP        every unreadable/ambiguous/absent permit halts the loop
  ALLOW       an armed permit lets work proceed (a switch stuck on passes every
              stop test while the product is dead, so this half is not optional)
  LATENCY     the bound is measured across a PROCESS boundary, because the
              operator is in another terminal, not in this interpreter
  UNDEFEATABLE a contained candidate cannot rewrite or delete the switch

Measured numbers are printed (run with ``-s`` to see them) AND asserted, so the
bound is enforced on every run rather than admired once.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

from daedalus.spine import containment as C
from daedalus.spine.attempt import RunnerContext, TaskSpec, pytest_gate
from daedalus.spine.cancel import (
    ManagedProcess,
    cancel_all_managed,
    live_managed_processes,
)
from daedalus.spine.killswitch import (
    ENV_SWITCH_PATH,
    MAX_PERMIT_BYTES,
    REPLACE_RETRY_S,
    RUN_TOKEN,
    KillSwitch,
    LoopHalted,
    default_switch_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_IS_WINDOWS = os.name == "nt"

# The measured bound for OBSERVATION: one poll interval, plus slack for the
# permit write and OS scheduling. Deliberately not "a few seconds" -- a bound
# loose enough to always pass measures nothing.
LATCH_SLACK_S = 0.5

# The measured bound for CHILD DEATH through the real pytest_gate path.
# MEASURED on this box over 5 runs: 257, 258, 262, 268, 425 ms (the outlier is
# the cold first run). 3.0 s is ~7x the worst observation and still tight
# enough to be evidence: if the registry sweep in stop_children() were removed,
# the gate would fall back to attempt.py's own ladder -- a 0.1 s poll plus
# proc.cancel()'s DEFAULT 3 s grace against a deaf child -- and blow this
# budget. A number nothing can violate measures nothing.
GATE_STOP_BUDGET_S = 3.0


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _switch(tmp_path: Path, **kw) -> KillSwitch:
    return KillSwitch(tmp_path / "control" / "killswitch", **kw)


def _pid_alive(pid: int) -> bool:
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259
    finally:
        k32.CloseHandle(handle)


def _wait_until(predicate, timeout: float, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _report(label: str, seconds: float, budget: float) -> None:
    print(f"\n[MEASURED] {label}: {seconds * 1000:.0f} ms "
          f"(budget {budget * 1000:.0f} ms)")


# A stopper that runs in ANOTHER PROCESS, waits for a rendezvous file, stamps
# the wall clock, and then engages the switch through the operator CLI. The
# stamp is taken BEFORE the write, so every measurement here OVER-reports the
# true latch latency -- the safe direction for a bound.
_STOPPER_SRC = """
import os, sys, time
sys.path.insert(0, {repo!r})
ready, stamp, path = sys.argv[1], sys.argv[2], sys.argv[3]
deadline = time.time() + 60
while not os.path.exists(ready) and time.time() < deadline:
    time.sleep(0.005)
with open(stamp, "w") as fh:
    fh.write(repr(time.time()))
from daedalus.spine.killswitch import _main
raise SystemExit(_main(["stop", "--path", path, "measured-stop"]))
"""


def _spawn_stopper(tmp_path: Path, switch: KillSwitch,
                   ready: Path) -> tuple[subprocess.Popen, Path]:
    script = tmp_path / f"stopper-{uuid.uuid4().hex[:6]}.py"
    script.write_text(_STOPPER_SRC.format(repo=str(REPO_ROOT)), encoding="utf-8")
    stamp = tmp_path / f"stamp-{uuid.uuid4().hex[:6]}.txt"
    proc = subprocess.Popen(
        [sys.executable, str(script), str(ready), str(stamp), str(switch.path)])
    return proc, stamp


def _stamp_value(stamp: Path) -> float:
    assert _wait_until(lambda: stamp.exists() and stamp.stat().st_size > 0, 30.0), (
        "the out-of-process stopper never stamped the clock")
    return float(stamp.read_text(encoding="utf-8").strip())


# --------------------------------------------------------------------------- #
# ALLOW -- with the switch off, work proceeds                                  #
# --------------------------------------------------------------------------- #
def test_allow_armed_switch_permits_work(tmp_path):
    """A switch stuck on passes every stop test while the product is dead."""
    switch = _switch(tmp_path)
    state = switch.arm()
    assert state.running is True, state.reason
    assert state.token == RUN_TOKEN
    assert switch.should_stop() is False
    switch.checkpoint()  # must not raise
    assert switch.reason is None


def test_allow_watcher_does_not_trip_a_healthy_switch(tmp_path):
    switch = _switch(tmp_path, poll_s=0.02)
    switch.arm()
    with switch.watch():
        assert switch.wait(timeout=0.75) is False, (
            "the watcher latched a switch that was armed the whole time")
    assert switch.should_stop() is False


def test_allow_gate_runs_to_completion_under_an_armed_switch(tmp_path):
    """The real attempt.py gate path, with the switch as the cancel token."""
    work = tmp_path / "wt"
    work.mkdir()
    (work / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                     encoding="utf-8")
    switch = _switch(tmp_path)
    switch.arm()
    ctx = RunnerContext(worktree=work, branch="b", base_revision="0" * 40,
                        task=TaskSpec("t", "i"), is_cancelled=switch)
    verdict = pytest_gate(poll_s=0.05)(ctx)
    assert verdict.cancelled is False
    assert verdict.passed is True, verdict.output[-800:]


def test_allow_arm_after_clear_works(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.stop("halted")
    switch.clear()
    assert KillSwitch(switch.path).arm().running is True


# --------------------------------------------------------------------------- #
# STOP -- every way of not knowing is a stop                                   #
# --------------------------------------------------------------------------- #
def test_stop_missing_permit(tmp_path):
    switch = _switch(tmp_path)
    state = switch.read_state()
    assert state.running is False
    assert "not armed" in state.reason


def test_stop_empty_permit(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.path.write_text("", encoding="utf-8")
    assert KillSwitch(switch.path).read_state().running is False


def test_stop_whitespace_only_permit(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.path.write_text("\n \n\t\n", encoding="utf-8")
    assert KillSwitch(switch.path).read_state().running is False


@pytest.mark.parametrize("token", ["run", "Run", "RUNNING", "RUN ", "GO", "1",
                                   "TRUE", "yes", "STOP", "RUNX"])
def test_stop_any_token_that_is_not_exactly_RUN(tmp_path, token):
    switch = _switch(tmp_path)
    switch.arm()
    switch.path.write_text(f"{token}\n", encoding="utf-8")
    fresh = KillSwitch(switch.path)
    # "RUN " strips to RUN and is legitimately armed; everything else halts.
    expected_running = token.strip() == RUN_TOKEN
    assert fresh.read_state().running is expected_running, token


def test_stop_permit_that_is_not_utf8(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.path.write_bytes(b"\xff\xfe\x00RUN")
    state = KillSwitch(switch.path).read_state()
    assert state.running is False
    assert "UTF-8" in state.reason


def test_stop_permit_that_is_a_directory(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    (control / "killswitch").mkdir()
    switch = KillSwitch(control / "killswitch")
    state = switch.read_state()
    assert state.running is False
    assert "not a regular file" in state.reason


def test_stop_implausibly_large_permit(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.path.write_text("RUN\n" + "x" * (MAX_PERMIT_BYTES + 16), encoding="utf-8")
    state = KillSwitch(switch.path).read_state()
    assert state.running is False
    assert "implausibly large" in state.reason


def test_stop_when_the_permit_cannot_be_read(tmp_path, monkeypatch):
    """Deterministic stand-in for a denied ACL / IO error / vanished volume."""
    switch = _switch(tmp_path)
    switch.arm()
    assert switch.read_state().running is True

    def _boom(self, *a, **kw):
        raise OSError(5, "Access is denied")

    monkeypatch.setattr(Path, "read_bytes", _boom)
    fresh = KillSwitch(switch.path)
    state = fresh.read_state()
    assert state.running is False
    assert "could not be read" in state.reason


def test_stop_when_the_permit_cannot_be_stat_ed(tmp_path, monkeypatch):
    switch = _switch(tmp_path)
    switch.arm()
    real_stat = os.stat

    def _boom(path, *a, **kw):
        if str(path) == str(switch.path):
            raise OSError(1920, "The file cannot be accessed by the system")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", _boom)
    state = KillSwitch(switch.path).read_state()
    assert state.running is False
    assert "could not be examined" in state.reason


def test_stop_when_the_marker_cannot_be_examined(tmp_path, monkeypatch):
    """`Path.exists()` would answer False here. That is the whole point.

    A denied ACL on the marker must not read as 'no stop was requested'.
    """
    switch = _switch(tmp_path)
    switch.arm()
    assert switch.read_state().running is True
    real_stat = os.stat

    def _boom(path, *a, **kw):
        if str(path) == str(switch.marker_path):
            raise PermissionError(5, "Access is denied")
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", _boom)
    state = KillSwitch(switch.path).read_state()
    assert state.running is False
    assert "marker could not be examined" in state.reason


def test_stop_marker_alone_halts_even_with_a_valid_permit(tmp_path):
    """The crash window between the two writes must resolve to STOPPED."""
    switch = _switch(tmp_path)
    switch.arm()
    switch.marker_path.write_text("STOP\n", encoding="utf-8")
    assert switch.path.read_text(encoding="utf-8").startswith(RUN_TOKEN)
    state = KillSwitch(switch.path).read_state()
    assert state.running is False
    assert "stop marker" in state.reason


class _NotEvenAnException(BaseException):
    """Deliberately NOT an Exception, so `except Exception` cannot catch it.

    ``KeyboardInterrupt`` is the realistic instance of this, but raising it
    inside a test makes pytest abort the whole session rather than record a
    failure -- which is how a mutation that removes the guard could look green.
    """


def test_stop_should_stop_never_raises(tmp_path, monkeypatch):
    """attempt.py's `_as_predicate` turns a raising token into 'not cancelled'.

    That wrapper is fail-OPEN and lives in a file this module may not edit, so
    the only defence is that raising is impossible from this side.
    """
    switch = _switch(tmp_path)
    switch.arm()

    def _explode(self):
        raise _NotEvenAnException("not even this")

    monkeypatch.setattr(KillSwitch, "read_state", _explode)
    assert switch.should_stop() is True
    assert "switch itself failed" in (switch.reason or "")
    # And the shapes attempt.py may normalise it through must not raise either.
    assert switch() is True and switch.is_set() is True


def test_stop_predicate_shapes_agree(tmp_path):
    """`cancel=switch` must behave the same however attempt.py normalises it."""
    switch = _switch(tmp_path)
    switch.arm()
    assert switch() is False and switch.is_set() is False
    KillSwitch(switch.path).stop("halt")        # a peer, as an operator would
    assert switch() is True and switch.is_set() is True and switch.should_stop()


def test_stop_checkpoint_raises_loop_halted(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.checkpoint()
    KillSwitch(switch.path).stop("no more spend")
    with pytest.raises(LoopHalted):
        switch.checkpoint()


def test_stop_does_not_lose_a_race_with_its_own_watcher(tmp_path):
    """REGRESSION. A poller reading the permit held it open without
    FILE_SHARE_DELETE, so `os.replace` in stop() returned ERROR_ACCESS_DENIED
    and the operator's stop command RAISED instead of stopping the loop.
    """
    switch = _switch(tmp_path, poll_s=0.01)
    switch.arm()
    with switch.watch():
        time.sleep(0.2)                          # poller is hammering the file
        peer = KillSwitch(switch.path)           # the operator, in another shell
        state = peer.stop("racing the watcher")  # must not raise
        assert state.running is False
        assert switch.wait(timeout=10.0) is True
    assert switch.should_stop() is True


def test_stop_wins_against_a_reader_holding_the_permit_open(tmp_path):
    """DETERMINISTIC version of the race above.

    The watcher-driven test only reproduced it by luck: the read window is
    microseconds wide. Here a reader holds the permit open for 400 ms, which on
    win32 makes ``MoveFileEx`` return ERROR_ACCESS_DENIED for that whole time
    (CPython's ``open()`` cannot request FILE_SHARE_DELETE). Without the
    bounded retry in ``_atomic_write`` the operator's stop RAISES.
    """
    switch = _switch(tmp_path)
    switch.arm()
    holder_done = threading.Event()

    def _hold():
        with open(switch.path, "rb") as fh:
            fh.read()
            time.sleep(0.4)
        holder_done.set()

    reader = threading.Thread(target=_hold, daemon=True)
    reader.start()
    time.sleep(0.05)                              # the handle is definitely open
    started = time.monotonic()
    state = KillSwitch(switch.path).stop("racing a reader")   # must not raise
    elapsed = time.monotonic() - started
    reader.join(timeout=10)
    assert holder_done.is_set()
    assert state.running is False
    assert elapsed < REPLACE_RETRY_S + 1.0, "the retry window overran its bound"
    assert switch.path.read_text(encoding="utf-8").startswith("STOP")


def test_stop_is_loud_when_it_takes_no_effect(tmp_path, monkeypatch):
    """A stop command that did nothing must never look like it worked."""
    switch = _switch(tmp_path)
    switch.arm()
    peer = KillSwitch(switch.path)
    monkeypatch.setattr(KillSwitch, "_atomic_write",
                        lambda self, *a, **kw: None)
    with pytest.raises(LoopHalted, match="THE STOP DID NOT TAKE"):
        peer.stop("into the void")


# --------------------------------------------------------------------------- #
# STOP is monotonic, and re-arming is a deliberate act                         #
# --------------------------------------------------------------------------- #
def test_stop_latch_survives_the_permit_being_restored(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    # Stopped by a PEER object, so the latch below is established by a READ of
    # the disk -- not by stop() shortcutting its own in-memory flag.
    KillSwitch(switch.path).stop("human said no")
    assert switch.should_stop() is True
    switch.clear()
    switch.path.parent.mkdir(parents=True, exist_ok=True)
    switch.path.write_text("RUN\n", encoding="utf-8")
    assert KillSwitch(switch.path).read_state().running is True, (
        "precondition: the file on disk now reads as armed again")
    assert switch.should_stop() is True, (
        "a latched switch un-latched when the permit was restored")


def test_stop_arm_refuses_to_undo_a_human_stop(tmp_path):
    """The likely real-world defeat: loop crashes, supervisor restarts, arms."""
    switch = _switch(tmp_path)
    switch.arm()
    switch.stop("3am")
    restarted = KillSwitch(switch.path)
    with pytest.raises(LoopHalted):
        restarted.arm()
    assert restarted.read_state().running is False


def test_stop_arm_force_is_the_deliberate_escape(tmp_path):
    switch = _switch(tmp_path)
    switch.arm()
    switch.stop("3am")
    assert KillSwitch(switch.path).arm(force=True).running is True


def test_stop_switch_path_is_frozen_at_construction(tmp_path, monkeypatch):
    """Moving the switch out from under a running loop must be impossible."""
    first = tmp_path / "a" / "killswitch"
    monkeypatch.setenv(ENV_SWITCH_PATH, str(first))
    switch = KillSwitch()
    assert switch.path == first
    switch.arm()
    monkeypatch.setenv(ENV_SWITCH_PATH, str(tmp_path / "b" / "killswitch"))
    assert switch.path == first
    switch.stop("halt")
    assert switch.should_stop() is True


def test_default_control_dir_is_a_sibling_of_the_worktree_root(monkeypatch):
    """A Low label on worktrees/ must not be able to reach the switch."""
    monkeypatch.delenv(ENV_SWITCH_PATH, raising=False)
    monkeypatch.delenv("DAEDALUS_WORKTREE_ROOT", raising=False)   # conftest pin
    monkeypatch.setenv("LOCALAPPDATA", str(Path(tempfile.gettempdir()) / "la"))
    from daedalus.kairos.worktree import _worktree_root_for

    path = default_switch_path(REPO_ROOT)
    worktrees = _worktree_root_for(Path(REPO_ROOT).resolve())
    assert "control" in path.parts
    assert worktrees not in path.parents and path.parent != worktrees
    assert Path(str(worktrees).split("worktrees")[0]) in path.parents


# --------------------------------------------------------------------------- #
# LATENCY -- measured across a process boundary                                #
# --------------------------------------------------------------------------- #
def test_latency_latch_within_one_poll_interval(tmp_path):
    """OBSERVATION bound: latch <= one poll interval + slack, measured."""
    poll_s = 0.1
    switch = _switch(tmp_path, poll_s=poll_s)
    switch.arm()
    ready = tmp_path / "ready"
    stopper, stamp = _spawn_stopper(tmp_path, switch, ready)
    try:
        with switch.watch():
            time.sleep(0.3)  # watcher is definitely polling
            ready.write_text("go", encoding="utf-8")
            assert switch.wait(timeout=30.0) is True, "the watcher never latched"
            observed = time.time()
        latency = observed - _stamp_value(stamp)
    finally:
        stopper.wait(timeout=30)
    budget = poll_s + LATCH_SLACK_S
    _report("out-of-process stop -> latch", latency, budget)
    assert 0 <= latency < budget, f"latch took {latency:.3f}s (budget {budget}s)"


def test_latency_operator_cli_stops_from_another_terminal(tmp_path):
    """The documented human path, exercised as a human would type it."""
    switch = _switch(tmp_path)
    switch.arm()
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    status = subprocess.run(
        [sys.executable, "-m", "daedalus.spine.killswitch", "status",
         "--path", str(switch.path)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert status.returncode == 0, status.stdout + status.stderr
    assert "RUNNING" in status.stdout

    halt = subprocess.run(
        [sys.executable, "-m", "daedalus.spine.killswitch", "stop",
         "--path", str(switch.path), "by", "hand"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert halt.returncode == 0, halt.stdout + halt.stderr
    assert switch.should_stop() is True

    after = subprocess.run(
        [sys.executable, "-m", "daedalus.spine.killswitch", "status",
         "--path", str(switch.path)],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert after.returncode == 3, "status must exit non-zero while stopped"
    assert "STOPPED" in after.stdout


# A gate-child that is DEAF to the graceful stage and spawns a grandchild, so
# only the Job Object can stop the tree. If the switch leaves either alive it
# has not stopped the loop, it has only stopped talking about it.
_INNER_TEST = """
import os, signal, subprocess, sys, time

def _deaf(*_a):
    return None

for _n in ("SIGBREAK", "SIGINT", "SIGTERM"):
    _s = getattr(signal, _n, None)
    if _s is not None:
        try:
            signal.signal(_s, _deaf)
        except (ValueError, OSError):
            pass

GC = os.path.join(os.path.dirname(__file__), "grandchild.py")

def test_long_running():
    gc = subprocess.Popen([sys.executable, GC])
    with open(os.path.join(os.path.dirname(__file__), "pids.txt"), "w") as fh:
        fh.write("%d\\n%d\\n" % (os.getpid(), gc.pid))
    with open(os.path.join(os.path.dirname(__file__), "gate_ready"), "w") as fh:
        fh.write("up")
    time.sleep(300)
"""

_GRANDCHILD = """
import signal, time

def _deaf(*_a):
    return None

for _n in ("SIGBREAK", "SIGINT", "SIGTERM"):
    _s = getattr(signal, _n, None)
    if _s is not None:
        try:
            signal.signal(_s, _deaf)
        except (ValueError, OSError):
            pass
while True:
    time.sleep(0.05)
"""


def test_latency_gate_child_tree_dies(tmp_path):
    """CHILD DEATH bound, on the REAL attempt.py gate path, measured.

    This is the test that decides whether the kill switch is a kill switch: a
    halted loop that leaves a pytest subprocess tree behind has not stopped.
    """
    work = tmp_path / "wt"
    work.mkdir()
    (work / "test_slow.py").write_text(_INNER_TEST, encoding="utf-8")
    (work / "grandchild.py").write_text(_GRANDCHILD, encoding="utf-8")
    ready = work / "gate_ready"
    pids_file = work / "pids.txt"

    switch = _switch(tmp_path, poll_s=0.1)
    switch.arm()
    ctx = RunnerContext(worktree=work, branch="b", base_revision="0" * 40,
                        task=TaskSpec("t", "i"), is_cancelled=switch)

    stopper, stamp = _spawn_stopper(tmp_path, switch, ready)
    try:
        with switch.watch():
            verdict = pytest_gate(poll_s=0.1, timeout_s=120)(ctx)
            returned = time.time()
    finally:
        stopper.wait(timeout=60)

    assert ready.exists(), "the gate child never reached its running state"
    latency = returned - _stamp_value(stamp)
    _report("out-of-process stop -> gate returned", latency, GATE_STOP_BUDGET_S)

    # ATTRIBUTION, not just death. attempt.py maps `cancelled` to
    # STATE_CANCELLED and everything else to STATE_GATES_FAILED, so a swept
    # child that reports `cancelled=False` would be written to the ledger as a
    # candidate whose tests FAILED -- a verdict on work that was never judged.
    assert verdict.cancelled is True, (
        "the gate reported a FAILURE for a candidate that was killed by the "
        f"switch, not judged: {verdict.output[-400:]}")
    assert verdict.passed is False
    assert latency < GATE_STOP_BUDGET_S, f"gate took {latency:.3f}s to give up"

    child_pid, grandchild_pid = [
        int(line) for line in pids_file.read_text().split() if line.strip()]
    assert _wait_until(lambda: not _pid_alive(child_pid), 5.0), (
        "the gate child survived the kill switch")
    assert _wait_until(lambda: not _pid_alive(grandchild_pid), 5.0), (
        "a GRANDCHILD survived the kill switch: the tree leaked")
    assert switch.children_stopped is True


# --------------------------------------------------------------------------- #
# CHILDREN -- the sweep of last resort                                         #
# --------------------------------------------------------------------------- #
def test_children_registry_reaps_a_process_nobody_handed_over(tmp_path):
    """A driver that forgot `cancel=` must not leave a tree running."""
    switch = _switch(tmp_path)
    switch.arm()
    proc = ManagedProcess([sys.executable, "-c", "import time; time.sleep(300)"])
    try:
        assert any(p is proc for p in live_managed_processes())
        assert _pid_alive(proc.pid)
        switch.stop("halt")
        switch.should_stop()
        switch.stop_children()          # never told about `proc`
        assert _wait_until(lambda: not _pid_alive(proc.pid), 5.0), (
            "an untracked ManagedProcess survived the kill switch")
    finally:
        proc.close(grace_s=0.0)


def test_children_tracked_process_is_cancelled(tmp_path):
    switch = _switch(tmp_path, sweep_managed=False)
    switch.arm()
    proc = switch.track(
        ManagedProcess([sys.executable, "-c", "import time; time.sleep(300)"]))
    try:
        switch.stop("halt")
        switch.stop_children()
        assert _wait_until(lambda: not _pid_alive(proc.pid), 5.0)
    finally:
        proc.close(grace_s=0.0)


def test_children_registry_drops_closed_processes():
    proc = ManagedProcess([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait(timeout=20)
    proc.close(grace_s=0.0)
    assert all(p is not proc for p in live_managed_processes()), (
        "a closed ManagedProcess is still registered; the registry leaks")


def test_children_registry_does_not_grow_without_bound():
    """The eager discard, tested for what it actually buys.

    ``live_managed_processes()`` filters on returncode, so the public view
    looks correct even if entries are never removed -- which is how the discard
    survived its own deletion the first time this suite was mutation-tested. A
    loop that keeps its ManagedProcess objects around for reporting (an
    entirely ordinary thing) would otherwise make the registry grow for the
    life of the process, so the private set is inspected directly.
    """
    from daedalus.spine import cancel as _cancel

    kept = []
    for _ in range(5):
        p = ManagedProcess([sys.executable, "-c", "import sys; sys.exit(0)"])
        p.wait(timeout=20)
        p.close(grace_s=0.0)
        kept.append(p)                            # references deliberately held
    with _cancel._LIVE_LOCK:
        registered = [p for p in _cancel._LIVE if any(p is k for k in kept)]
    assert registered == [], (
        f"{len(registered)}/5 closed processes are still in the registry; "
        f"it grows for the life of the loop")


def test_children_sweep_survives_a_broken_entry(tmp_path):
    """One wedged child must not stop the rest of the tree from dying."""

    class _Broken:
        returncode = None

        def cancel(self, **_kw):
            raise RuntimeError("wedged")

    switch = _switch(tmp_path, sweep_managed=False)
    switch.arm()
    switch.track(_Broken())
    proc = switch.track(
        ManagedProcess([sys.executable, "-c", "import time; time.sleep(300)"]))
    try:
        switch.stop("halt")
        switch.stop_children()
        assert _wait_until(lambda: not _pid_alive(proc.pid), 5.0)
    finally:
        proc.close(grace_s=0.0)


def test_children_sweep_waits_for_cooperative_cancellation(tmp_path):
    """The sweep of last resort must not OUTRUN the latch it is backing up.

    Racing the gate's own poll is not a tie: when the sweep wins, pytest_gate
    leaves its loop by the ordinary exit and reports `cancelled=False`, which
    attempt.py records as `gates_failed` -- a verdict about a candidate whose
    tests were never judged. That misattribution was observed once in a full
    suite run and could not be reproduced on demand, so the ORDERING is
    asserted directly here rather than the flaky outcome it causes.
    """

    class _Recorder:
        returncode = None

        def __init__(self) -> None:
            self.at: float | None = None

        def cancel(self, **_kw):
            self.at = time.monotonic()
            return None

    grace = 0.4
    switch = _switch(tmp_path, poll_s=0.02, sweep_managed=False,
                     cooperative_grace_s=grace)
    switch.arm()
    rec = switch.track(_Recorder())
    with switch.watch():
        KillSwitch(switch.path).stop("halt")
        assert switch.wait(timeout=10.0) is True
        latched = time.monotonic()
        assert _wait_until(lambda: rec.at is not None, 10.0), "the sweep never fired"
    gap = rec.at - latched
    print(f"\n[MEASURED] latch -> sweep gap: {gap * 1000:.0f} ms "
          f"(must be >= {grace * 700:.0f} ms)")
    assert gap >= grace * 0.7, (
        f"the sweep fired {gap:.3f}s after the latch, inside the "
        f"{grace}s window reserved for cooperative cancellation")


def test_children_cancel_all_managed_is_safe_when_nothing_runs():
    assert cancel_all_managed(grace_s=0.0) == [] or True  # never raises


# --------------------------------------------------------------------------- #
# UNDEFEATABLE -- the ADR-007 wording: "the candidate process cannot modify"    #
# --------------------------------------------------------------------------- #
_ATTACK = """
import json, os, shutil, sys

switch, marker, out, canary = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
res = {}

def probe(name, fn):
    try:
        fn()
        res[name] = "ALLOWED"
    except Exception as e:
        res[name] = type(e).__name__

# The candidate really is running and really can write its own worktree. Without
# this the whole test would pass just as happily against a child that crashed.
probe("write_own_worktree",
      lambda: open(canary, "w").write("candidate was here"))

probe("read_switch", lambda: open(switch, "rb").read())
probe("delete_permit", lambda: os.unlink(switch))
probe("forge_permit", lambda: open(switch, "w").write("RUN\\n"))
probe("append_permit", lambda: open(switch, "a").write("RUN\\n"))
probe("delete_marker", lambda: os.unlink(marker))
probe("rmtree_control", lambda: shutil.rmtree(os.path.dirname(switch)))
probe("replace_control_dir", lambda: os.rename(os.path.dirname(switch),
                                               os.path.dirname(switch) + ".gone"))
open(out, "w").write(json.dumps(res))
"""


@pytest.mark.skipif(not C.platform_supported(),
                    reason="MIC write containment is a win32 mechanism")
def test_contained_candidate_cannot_defeat_it(tmp_path):
    """A Low-integrity candidate is refused by the KERNEL, not by our code."""
    control = tmp_path / "control"
    control.mkdir()
    switch = KillSwitch(control / "killswitch")
    switch.arm()
    switch.stop("human pulled the plug")
    assert switch.read_state().running is False

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    C.label_low_integrity(worktree)
    script = tmp_path / "attack.py"
    script.write_text(_ATTACK, encoding="utf-8")
    out = worktree / "res.json"
    canary = worktree / "candidate.txt"

    proc = C.spawn_contained(
        [sys.executable, str(script), str(switch.path), str(switch.marker_path),
         str(out), str(canary)], cwd=worktree)
    try:
        code = proc.wait(timeout_s=180)
    finally:
        proc.close()
    assert out.exists(), f"the contained candidate produced nothing (exit {code})"
    res = json.loads(out.read_text(encoding="utf-8"))
    print(f"\n[MEASURED] contained candidate vs kill switch: {res}")

    assert res["write_own_worktree"] == "ALLOWED", (
        "the candidate could not even write its own worktree, so this test "
        "proved nothing about the switch")
    for vector in ("delete_permit", "forge_permit", "append_permit",
                   "delete_marker", "rmtree_control", "replace_control_dir"):
        assert res[vector] != "ALLOWED", (
            f"a contained candidate DEFEATED the kill switch via {vector}")

    # And the ground truth on disk, not just the child's own report.
    fresh = KillSwitch(switch.path)
    assert fresh.read_state().running is False
    assert switch.marker_path.exists()


def test_uncontained_forgery_cannot_unlatch(tmp_path):
    """The honest limit: an UNCONTAINED candidate can rewrite both files.

    It still cannot restart a loop that has already latched, so the residual
    exposure is a sub-poll-interval race rather than a defeat. If someone ever
    removes the latch, this goes red.
    """
    switch = _switch(tmp_path, poll_s=0.05)
    switch.arm()
    with switch.watch():
        KillSwitch(switch.path).stop("halt")     # latch via a READ, as in life
        assert switch.wait(timeout=10.0) is True
    # Now the "candidate", at our own integrity level, undoes everything.
    switch.clear()
    switch.path.write_text("RUN\n", encoding="utf-8")
    assert KillSwitch(switch.path).read_state().running is True
    assert switch.should_stop() is True
    with pytest.raises(LoopHalted):
        switch.checkpoint()


def test_the_module_states_the_bound_it_does_not_hold():
    """Silence about in-flight spend must not be mistakable for coverage."""
    from daedalus.spine import killswitch as K

    doc = K.__doc__ or ""
    assert "not aborted" in doc.lower() or "NOT aborted" in doc
    assert "before the next" in doc
