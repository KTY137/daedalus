"""Full permit/ref/generation chain for the executor kill-switch binding."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from daedalus.kernel.resolved_kill_switch import (
    ResolvedKillSwitch,
    kill_switch_path_sha256,
    kill_switch_ref_for_path,
)
from daedalus.spine.killswitch import KillSwitch, LoopHalted


def test_live_permit_ref_generation_stop_and_rearm_chain(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "control" / "permit", sweep_managed=False)
    first_state = switch.arm(note="claim-chain")
    assert first_state.running is True
    assert first_state.generation == 1

    expected_ref = kill_switch_ref_for_path(switch.path)
    resolved = ResolvedKillSwitch.resolve(
        switch,
        expected_kill_switch_ref=expected_ref,
        expected_generation=1,
    )
    assert resolved.path_sha256 == kill_switch_path_sha256(switch.path)
    assert resolved.kill_switch_ref == kill_switch_ref_for_path(switch.path)
    assert resolved.generation == 1
    resolved.checkpoint()
    with pytest.raises(TypeError, match="live permit"):
        ResolvedKillSwitch(
            switch=switch,
            kill_switch_ref=resolved.kill_switch_ref,
            generation=resolved.generation,
            path_sha256=resolved.path_sha256,
        )
    with pytest.raises(AttributeError, match="immutable"):
        resolved.generation = 9  # type: ignore[misc]

    stopped = switch.stop("test stop")
    assert stopped.running is False
    assert stopped.generation == 1
    with pytest.raises(LoopHalted, match="engaged"):
        resolved.checkpoint()

    second_state = switch.arm(force=True, note="explicit rearm")
    assert second_state.running is True
    assert second_state.generation == 2
    with pytest.raises(LoopHalted, match="generation"):
        resolved.checkpoint()
    restarted = KillSwitch(switch.path, sweep_managed=False)
    second = ResolvedKillSwitch.resolve(
        restarted,
        expected_kill_switch_ref=expected_ref,
        expected_generation=2,
    )
    assert second.kill_switch_ref == resolved.kill_switch_ref
    assert second.generation == 2
    second.checkpoint()

    legacy = KillSwitch(tmp_path / "legacy" / "permit", sweep_managed=False)
    legacy.path.parent.mkdir(parents=True)
    legacy.path.write_text("RUN\n", encoding="utf-8")
    legacy_ref = kill_switch_ref_for_path(legacy.path)
    with pytest.raises(LoopHalted, match="explicitly re-armed"):
        ResolvedKillSwitch.resolve(
            legacy,
            expected_kill_switch_ref=legacy_ref,
            expected_generation=0,
        )
    migrated = legacy.arm()
    assert migrated.generation == 1
    legacy_resolved = ResolvedKillSwitch.resolve(
        legacy,
        expected_kill_switch_ref=legacy_ref,
        expected_generation=1,
    )
    legacy_resolved.checkpoint()


def test_generation_counter_crash_concurrency_and_aba_chain(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "durable" / "permit", sweep_managed=False)
    first = switch.arm()
    stale = ResolvedKillSwitch.resolve(
        switch,
        expected_kill_switch_ref=kill_switch_ref_for_path(switch.path),
        expected_generation=1,
    )
    assert first.generation == 1

    # Deleting or corrupting only the permit can never reset the sidecar.
    switch.path.unlink()
    assert switch.read_state().running is False
    second = switch.arm(force=True)
    assert second.generation == 2
    switch.path.write_bytes(b"not-a-permit")
    assert switch.read_state().running is False
    third = switch.arm(force=True)
    assert third.generation == 3
    with pytest.raises(LoopHalted, match="generation"):
        stale.checkpoint()

    # Counter-before-permit is the deliberate crash order: mismatch is STOP,
    # and recovery skips the incomplete generation rather than reusing it.
    switch._write_generation_counter(4)
    mismatch = KillSwitch(switch.path, sweep_managed=False)
    assert mismatch.read_state().running is False
    assert "disagrees" in mismatch.read_state().reason
    recovered = mismatch.arm(force=True)
    assert recovered.generation == 5

    # Eight concurrent operator arms are serialized by the OS lock. Each call
    # returns the generation it itself committed; the final counter is exact.
    def rearm(_index: int) -> int:
        state = KillSwitch(switch.path, sweep_managed=False).arm(force=True)
        assert state.generation is not None
        return state.generation

    with ThreadPoolExecutor(max_workers=8) as pool:
        generations = sorted(pool.map(rearm, range(8)))
    assert generations == list(range(6, 14))
    current = KillSwitch(switch.path, sweep_managed=False)
    assert current.read_state().generation == 13

    # Once initialized, losing the authoritative counter is a permanent
    # refusal, even for force-arm. Resetting to one would revive `stale` (ABA).
    current.generation_path.unlink()
    assert current.read_state().running is False
    with pytest.raises(LoopHalted, match="counter is missing"):
        current.arm(force=True)

    corrupt = KillSwitch(tmp_path / "corrupt-counter" / "permit", sweep_managed=False)
    corrupt.arm()
    corrupt.generation_path.write_text("garbage\n", encoding="ascii")
    assert corrupt.read_state().running is False
    with pytest.raises(LoopHalted, match="generation counter"):
        corrupt.arm(force=True)


def test_signed_ref_generation_and_missing_sidecars_chain(tmp_path: Path) -> None:
    switch = KillSwitch(tmp_path / "signed" / "permit", sweep_managed=False)
    state = switch.arm()
    expected_ref = kill_switch_ref_for_path(switch.path)
    assert state.generation == 1

    with pytest.raises(LoopHalted, match="signed effect scope"):
        ResolvedKillSwitch.resolve(
            switch,
            expected_kill_switch_ref=kill_switch_ref_for_path(tmp_path / "other"),
            expected_generation=1,
        )
    with pytest.raises(LoopHalted, match="signed execution authority"):
        ResolvedKillSwitch.resolve(
            switch,
            expected_kill_switch_ref=expected_ref,
            expected_generation=2,
        )

    stale = ResolvedKillSwitch.resolve(
        switch,
        expected_kill_switch_ref=expected_ref,
        expected_generation=1,
    )
    switch.generation_path.unlink()
    switch.operator_lock_path.unlink()
    observed = KillSwitch(switch.path, sweep_managed=False)
    assert observed.read_state().running is False
    assert "counter is missing" in observed.read_state().reason
    with pytest.raises(LoopHalted):
        stale.checkpoint()

    forged = KillSwitch(tmp_path / "forged" / "permit", sweep_managed=False)
    forged.path.parent.mkdir(parents=True)
    forged.path.write_text("RUN\ngeneration=999\n", encoding="utf-8")
    assert forged.read_state().running is False
    assert "counter is missing" in forged.read_state().reason


def test_real_process_serialization_and_emergency_stop_chain(tmp_path: Path) -> None:
    permit = tmp_path / "processes" / "permit"
    ready_dir = tmp_path / "ready"
    ready_dir.mkdir()
    go = tmp_path / "go"
    repo_root = Path(__file__).resolve().parents[2]
    worker = r"""
import sys, time
from pathlib import Path
from daedalus.spine.killswitch import KillSwitch
permit, ready, go = map(Path, sys.argv[1:])
ready.write_text("ready", encoding="ascii")
deadline = time.monotonic() + 20.0
while not go.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("barrier timeout")
    time.sleep(0.005)
state = KillSwitch(permit, sweep_managed=False).arm(force=True)
print(state.generation, flush=True)
"""
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker,
                str(permit),
                str(ready_dir / str(index)),
                str(go),
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(8)
    ]
    deadline = time.monotonic() + 20.0
    while len(list(ready_dir.iterdir())) != len(workers):
        if time.monotonic() >= deadline:
            raise AssertionError("real process workers did not reach the barrier")
        time.sleep(0.01)
    go.write_text("go", encoding="ascii")
    completed = [process.communicate(timeout=30.0) for process in workers]
    for process, (_stdout, stderr) in zip(workers, completed):
        assert process.returncode == 0, stderr
    generations = sorted(int(stdout.strip()) for stdout, _stderr in completed)
    assert generations == list(range(1, 9))
    current = KillSwitch(permit, sweep_managed=False)
    assert current.read_state().generation == 8

    # A slow force-arm must not win after stop reports success.  The child has
    # already observed the old marker and holds the real OS lock before its
    # counter publication is delayed.  Stop publishes a new marker immediately,
    # waits, overtakes that exact in-flight re-arm, and reasserts STOP last.
    assert current.stop("prepare force-arm race").running is False
    lock_ready = tmp_path / "lock-ready"
    release_arm = tmp_path / "release-arm"
    holder = r"""
import sys, time
from pathlib import Path
from daedalus.spine.killswitch import KillSwitch
permit, ready, release = map(Path, sys.argv[1:])
switch = KillSwitch(permit, sweep_managed=False)
write_generation = switch._write_generation_counter
def delayed_write(generation):
    ready.write_text("held-before-counter", encoding="ascii")
    deadline = time.monotonic() + 20.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("force-arm release timeout")
        time.sleep(0.005)
    write_generation(generation)
switch._write_generation_counter = delayed_write
state = switch.arm(force=True)
print(state.generation, flush=True)
"""
    lock_process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder,
            str(permit),
            str(lock_ready),
            str(release_arm),
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10.0
    while not lock_ready.exists():
        if time.monotonic() >= deadline:
            raise AssertionError("lock holder did not acquire the real OS lock")
        time.sleep(0.01)
    def release_slow_arm() -> None:
        time.sleep(5.0)
        release_arm.write_text("release", encoding="ascii")

    with ThreadPoolExecutor(max_workers=1) as pool:
        release_future = pool.submit(release_slow_arm)
        started = time.monotonic()
        stopped = current.stop("emergency races an in-flight force-arm")
        elapsed = time.monotonic() - started
        release_future.result(timeout=10.0)
    assert stopped.running is False
    assert current.marker_path.exists()
    assert elapsed >= 4.0, "stop falsely completed before overtaking the lock holder"
    assert elapsed < 8.0, "released lock was not acquired in bounded test time"
    stdout, stderr = lock_process.communicate(timeout=10.0)
    assert lock_process.returncode == 0, stderr
    assert int(stdout.strip()) == 9
    final_state = KillSwitch(permit, sweep_managed=False).read_state()
    assert final_state.running is False
    assert final_state.generation == 9


@pytest.mark.skipif(os.name != "nt", reason="real Windows sharing semantics")
def test_windows_sharing_faults_never_reopen_marker_stopped_chain(
    tmp_path: Path,
) -> None:
    clear_switch = KillSwitch(tmp_path / "clear" / "permit", sweep_managed=False)
    assert clear_switch.arm().generation == 1
    clear_switch._atomic_write(clear_switch.marker_path, "STOP\nreason=fault\n")
    assert clear_switch.read_state().running is False
    with clear_switch.path.open("rb"):
        with pytest.raises(LoopHalted, match="permit could not be removed"):
            clear_switch.clear()
        after_clear_fault = KillSwitch(clear_switch.path, sweep_managed=False)
        assert after_clear_fault.read_state().running is False
        assert after_clear_fault.marker_path.exists()

    arm_switch = KillSwitch(tmp_path / "arm" / "permit", sweep_managed=False)
    assert arm_switch.arm().generation == 1
    arm_switch._atomic_write(arm_switch.marker_path, "STOP\nreason=fault\n")
    with arm_switch.generation_path.open("rb"):
        with pytest.raises(LoopHalted, match="new generation"):
            arm_switch.arm(force=True)
        after_arm_fault = KillSwitch(arm_switch.path, sweep_managed=False)
        assert after_arm_fault.read_state().running is False
        assert after_arm_fault.marker_path.exists()
        assert after_arm_fault.read_state().generation == 1
