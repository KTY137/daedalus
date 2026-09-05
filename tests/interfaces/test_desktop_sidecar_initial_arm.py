"""Crash/refusal contracts for the packaged desktop's one-shot initial arm."""
from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.interfaces.desktop import sidecar
from daedalus.spine.killswitch import ENV_SWITCH_PATH, KillSwitch


def _paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    switch = tmp_path / "control" / "killswitch"
    claim = switch.with_name(switch.name + ".desktop-initial-arm.claim")
    monkeypatch.setenv(ENV_SWITCH_PATH, str(switch))
    monkeypatch.setenv(sidecar.DESKTOP_INITIAL_ARM_CLAIM_ENV, str(claim))
    return switch, claim


def test_initial_arm_runs_only_after_the_existing_sidecar_boundary() -> None:
    source = inspect.getsource(sidecar.main)

    assert source.index("begin_effect(") < source.index("prepare_runtime()")
    assert source.index("begin_effect(") < source.index(
        "initialize_desktop_switch_once()"
    )


def test_fresh_packaged_control_root_claims_then_arms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)

    state = sidecar.initialize_desktop_switch_once()

    assert state is not None and state.running is True
    assert claim_path.read_bytes() == (
        b"daedalus-desktop-initial-arm/1\nstate=COMPLETE\n"
    )
    assert os.lstat(claim_path).st_nlink == 1
    assert os.lstat(switch_path).st_nlink == 1
    assert KillSwitch(path=switch_path, sweep_managed=False).read_state().running is True


@pytest.mark.skipif(os.name != "nt", reason="NTFS stat/fstat contract")
def test_windows_checked_entry_accepts_one_unchanged_real_file(
    tmp_path: Path,
) -> None:
    entry = tmp_path / "unchanged"
    entry.write_bytes(b"RUN\r\n")

    evidence = sidecar._read_checked_entry(tmp_path, entry.name, None)

    assert evidence is not None
    assert evidence[0] == b"RUN\r\n"
    assert (evidence[1].st_dev, evidence[1].st_ino) == (
        os.lstat(entry).st_dev,
        os.lstat(entry).st_ino,
    )


def test_existing_claim_never_rearms_a_manually_deleted_permit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    assert sidecar.initialize_desktop_switch_once().running is True
    switch_path.unlink()

    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail("an existing claim must suppress arm()"),
    )
    state = sidecar.initialize_desktop_switch_once()

    assert state is not None and state.running is False
    assert claim_path.is_file()
    assert not switch_path.exists()


def test_sticky_stop_alone_never_auto_rearms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    assert sidecar.initialize_desktop_switch_once().running is True
    switch = KillSwitch(path=switch_path, sweep_managed=False)
    assert switch.stop("test operator stop").running is False
    # Prove the sticky marker is independently suppressive, even if both the
    # permit and the original one-shot claim were manually removed.
    switch_path.unlink()
    claim_path.unlink()

    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail("a sticky stop must suppress arm()"),
    )
    state = sidecar.initialize_desktop_switch_once()

    assert state is not None and state.running is False
    assert switch_path.with_name("killswitch.stopped").is_file()
    assert not claim_path.exists()


def test_crash_after_durable_claim_is_permanently_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    calls = 0

    def crash_after_claim(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic crash after claim")

    monkeypatch.setattr(KillSwitch, "arm", crash_after_claim)
    with pytest.raises(RuntimeError, match="synthetic crash after claim"):
        sidecar.initialize_desktop_switch_once()

    assert calls == 1
    assert claim_path.is_file()
    assert not switch_path.exists()

    state = sidecar.initialize_desktop_switch_once()
    assert calls == 1, "the retained claim must suppress every later arm attempt"
    assert state is not None and state.running is False


def test_arm_that_publishes_run_then_raises_requires_proven_revocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_arm = KillSwitch.arm

    def publish_then_raise(self, *args, **kwargs):
        assert real_arm(self, *args, **kwargs).running is True
        raise OSError("synthetic arm return-path failure")

    monkeypatch.setattr(KillSwitch, "arm", publish_then_raise)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("synthetic revocation failure")
        ),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert claim_path.read_bytes().endswith(b"state=PENDING\n")
    assert switch_path.read_bytes().splitlines()[0] == b"RUN"


def test_raw_parent_error_cannot_escape_prearm_absence_revocation_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_parent_identity = sidecar._parent_identity
    checks = 0

    def fail_absence_parent_proof(path: Path) -> tuple[int, int]:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise OSError("synthetic raw parent identity failure")
        return real_parent_identity(path)

    monkeypatch.setattr(sidecar, "_parent_identity", fail_absence_parent_proof)
    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic arm failure before permit")
        ),
    )
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: SimpleNamespace(running=False),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert checks == 3
    assert claim_path.read_bytes().endswith(b"state=PENDING\n")
    assert not switch_path.exists()


@pytest.mark.parametrize(
    "claim_body",
    [
        b"daedalus-desktop-initial-arm/1\nstate=PENDING\n",
        b"malformed-claim\n",
    ],
)
def test_restart_with_noncomplete_claim_and_run_is_fatal_without_rearm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    claim_body: bytes,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    claim_path.parent.mkdir()
    claim_path.write_bytes(claim_body)
    assert KillSwitch(path=switch_path, sweep_managed=False).arm().running is True

    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail(
            "a retained non-COMPLETE claim must never re-arm"
        ),
    )
    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert claim_path.read_bytes() == claim_body
    assert switch_path.read_bytes().splitlines()[0] == b"RUN"


def test_pending_claim_cannot_return_run_after_stop_marker_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    claim_path.parent.mkdir()
    claim_path.write_bytes(
        b"daedalus-desktop-initial-arm/1\nstate=PENDING\n"
    )
    switch = KillSwitch(path=switch_path, sweep_managed=False)
    assert switch.arm().running is True
    marker = switch.marker_path
    marker.write_bytes(b"STOP\n")
    real_read_state = KillSwitch.read_state
    reads = 0

    def remove_marker_during_reconciled_read(self):
        nonlocal reads
        reads += 1
        if reads == 2:
            marker.unlink()
        return real_read_state(self)

    monkeypatch.setattr(KillSwitch, "read_state", remove_marker_during_reconciled_read)

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert reads == 2
    assert claim_path.read_bytes().endswith(b"state=PENDING\n")
    assert switch_path.read_bytes().splitlines()[0] == b"RUN"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-parent race")
def test_parent_substitution_during_arm_cannot_hide_literal_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    old_parent = switch_path.parent.with_name("old-control")

    def substitute_parent_then_raise(self, *args, **kwargs):
        switch_path.parent.rename(old_parent)
        switch_path.parent.mkdir()
        switch_path.write_bytes(b"RUN\n")
        raise RuntimeError("synthetic path-based arm failure")

    monkeypatch.setattr(KillSwitch, "arm", substitute_parent_then_raise)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("stop failed")),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert (old_parent / claim_path.name).read_bytes().endswith(b"state=PENDING\n")
    assert switch_path.read_bytes() == b"RUN\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-parent race")
def test_complete_claim_in_substituted_parent_cannot_authorize_literal_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    claim_path.parent.mkdir()
    claim_path.write_bytes(
        b"daedalus-desktop-initial-arm/1\nstate=COMPLETE\n"
    )
    old_parent = switch_path.parent.with_name("old-control")
    real_read = sidecar._read_checked_entry
    swapped = False

    def swap_after_claim_snapshot(parent: Path, name: str, directory_fd: int | None):
        nonlocal swapped
        result = real_read(parent, name, directory_fd)
        if name == claim_path.name and result is not None and not swapped:
            swapped = True
            switch_path.parent.rename(old_parent)
            switch_path.parent.mkdir()
            switch_path.write_bytes(b"RUN\n")
        return result

    monkeypatch.setattr(sidecar, "_read_checked_entry", swap_after_claim_snapshot)

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert swapped is True
    assert switch_path.read_bytes() == b"RUN\n"


def test_claim_durability_failure_leaves_a_suppressive_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_fsync = sidecar.os.fsync

    monkeypatch.setattr(
        sidecar.os,
        "fsync",
        lambda fd: (_ for _ in ()).throw(OSError("synthetic durability failure")),
    )
    with pytest.raises(OSError, match="synthetic durability failure"):
        sidecar.initialize_desktop_switch_once()

    assert claim_path.exists()
    assert not switch_path.exists()
    monkeypatch.setattr(sidecar.os, "fsync", real_fsync)
    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail(
            "an indeterminate retained claim must suppress arm()"
        ),
    )
    state = sidecar.initialize_desktop_switch_once()
    assert state is not None and state.running is False


def test_hard_linked_claim_refuses_without_touching_its_other_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    claim_path.parent.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("retain", encoding="utf-8")
    try:
        os.link(victim, claim_path)
    except OSError as exc:
        pytest.skip(f"hard links unavailable on this filesystem: {exc}")

    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail("a hard-linked claim must not arm"),
    )
    with pytest.raises(
        sidecar.DesktopSwitchInitializationRefused,
        match="redirected or hard-linked",
    ):
        sidecar.initialize_desktop_switch_once()

    assert victim.read_text(encoding="utf-8") == "retain"
    assert not switch_path.exists()


def test_redirected_parent_never_creates_claim_or_permit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    actual = tmp_path / "actual-control"
    actual.mkdir()
    linked = tmp_path / "linked-control"
    try:
        linked.symlink_to(actual, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable on this host: {exc}")
    switch_path = linked / "killswitch"
    claim_path = linked / "killswitch.desktop-initial-arm.claim"
    monkeypatch.setenv(ENV_SWITCH_PATH, str(switch_path))
    monkeypatch.setenv(sidecar.DESKTOP_INITIAL_ARM_CLAIM_ENV, str(claim_path))
    monkeypatch.setattr(
        KillSwitch,
        "arm",
        lambda *args, **kwargs: pytest.fail("a redirected parent must not arm"),
    )

    state = sidecar.initialize_desktop_switch_once()

    assert state is not None and state.running is False
    assert not (actual / "killswitch").exists()
    assert not (actual / "killswitch.desktop-initial-arm.claim").exists()


def test_claim_environment_without_switch_path_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(ENV_SWITCH_PATH, raising=False)
    monkeypatch.setenv(
        sidecar.DESKTOP_INITIAL_ARM_CLAIM_ENV,
        str(tmp_path / "claim"),
    )

    with pytest.raises(
        sidecar.DesktopSwitchInitializationRefused,
        match=ENV_SWITCH_PATH,
    ):
        sidecar.initialize_desktop_switch_once()


def test_post_arm_unproven_revocation_is_fatal_before_manager_or_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from daedalus import budget, desktop_runtime
    from daedalus.spine import effect_boundary

    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    lifecycle: list[object] = []
    real_checked = sidecar._checked_existing_entry

    def fail_running_permit_postcondition(
        parent: Path,
        name: str,
        directory_fd: int | None,
    ):
        state = real_checked(parent, name, directory_fd)
        if (
            name == switch_path.name
            and state is not None
            and (parent / name).read_bytes().splitlines()[0] == b"RUN"
        ):
            raise sidecar.DesktopSwitchInitializationRefused(
                "synthetic post-arm identity failure"
            )
        return state

    monkeypatch.setattr(sidecar, "_checked_existing_entry", fail_running_permit_postcondition)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("synthetic revocation failure")
        ),
    )
    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: lifecycle.append("guard") or object(),
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: lifecycle.append("boundary"),
    )
    monkeypatch.setattr(
        sidecar,
        "prepare_runtime",
        lambda: lifecycle.append("prepare") or tmp_path,
    )
    monkeypatch.setattr(
        sidecar.os,
        "chdir",
        lambda path: lifecycle.append("chdir"),
    )
    monkeypatch.setattr(
        desktop_runtime,
        "DesktopRuntimeManager",
        lambda root: lifecycle.append("manager") or pytest.fail(
            "fatal revocation ambiguity must precede manager construction"
        ),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.main([])

    assert lifecycle == ["guard", "boundary", "prepare"]
    assert claim_path.is_file()
    assert KillSwitch(path=switch_path, sweep_managed=False).read_state().running is True


def test_parent_identity_failure_after_arm_is_fatal_when_stop_cannot_revoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_parent_identity = sidecar._parent_identity
    checks = 0

    def changed_after_arm(path: Path) -> tuple[int, int]:
        nonlocal checks
        checks += 1
        if switch_path.exists() and switch_path.read_bytes().splitlines()[0] == b"RUN":
            raise sidecar.DesktopSwitchInitializationRefused(
                "synthetic post-arm parent identity failure"
            )
        return real_parent_identity(path)

    monkeypatch.setattr(sidecar, "_parent_identity", changed_after_arm)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("synthetic parent revocation failure")
        ),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert checks >= 3
    assert claim_path.is_file()
    assert KillSwitch(path=switch_path, sweep_managed=False).read_state().running is True


def test_parent_failure_with_direct_stop_artifacts_is_safe_and_keeps_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_parent_identity = sidecar._parent_identity
    checks = 0

    def changed_after_arm(path: Path) -> tuple[int, int]:
        nonlocal checks
        checks += 1
        if switch_path.exists() and switch_path.read_bytes().splitlines()[0] == b"RUN":
            raise sidecar.DesktopSwitchInitializationRefused(
                "synthetic post-arm parent identity failure"
            )
        return real_parent_identity(path)

    monkeypatch.setattr(sidecar, "_parent_identity", changed_after_arm)

    with pytest.raises(
        sidecar.DesktopSwitchInitializationRefused,
        match="persistent STOP representation",
    ):
        sidecar.initialize_desktop_switch_once()

    assert claim_path.read_bytes() == (
        b"daedalus-desktop-initial-arm/1\nstate=PENDING\n"
    )
    assert switch_path.read_bytes().splitlines()[0] == b"STOP"
    assert switch_path.with_name("killswitch.stopped").read_bytes().splitlines()[
        0
    ] == b"STOP"


def test_transient_stopped_returns_are_not_revocation_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    real_arm = KillSwitch.arm
    real_parent_identity = sidecar._parent_identity
    checks = 0

    def arm_then_make_reads_transiently_stopped(self, *args, **kwargs):
        state = real_arm(self, *args, **kwargs)
        monkeypatch.setattr(
            self,
            "read_state",
            lambda: SimpleNamespace(running=False, reason="transient STOP"),
        )
        return state

    def changed_after_arm(path: Path) -> tuple[int, int]:
        nonlocal checks
        checks += 1
        if switch_path.exists() and switch_path.read_bytes().splitlines()[0] == b"RUN":
            raise sidecar.DesktopSwitchInitializationRefused(
                "synthetic post-arm parent identity failure"
            )
        return real_parent_identity(path)

    monkeypatch.setattr(KillSwitch, "arm", arm_then_make_reads_transiently_stopped)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda self, *args, **kwargs: self.read_state(),
    )
    monkeypatch.setattr(sidecar, "_parent_identity", changed_after_arm)

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.initialize_desktop_switch_once()

    assert claim_path.read_bytes() == (
        b"daedalus-desktop-initial-arm/1\nstate=PENDING\n"
    )
    assert switch_path.read_bytes().splitlines()[0] == b"RUN"


def test_final_complete_read_failure_is_fatal_before_runtime_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from daedalus import budget, desktop_runtime
    from daedalus.spine import effect_boundary

    switch_path, claim_path = _paths(monkeypatch, tmp_path)
    lifecycle: list[str] = []
    real_read = sidecar._read_checked_entry
    complete_reads = 0

    def fail_second_complete_read(parent: Path, name: str, directory_fd: int | None):
        nonlocal complete_reads
        result = real_read(parent, name, directory_fd)
        if (
            name == claim_path.name
            and result is not None
            and result[0]
            == b"daedalus-desktop-initial-arm/1\nstate=COMPLETE\n"
        ):
            complete_reads += 1
            if complete_reads == 2:
                raise sidecar.DesktopSwitchInitializationRefused(
                    "synthetic final COMPLETE read failure"
                )
        return result

    monkeypatch.setattr(sidecar, "_read_checked_entry", fail_second_complete_read)
    monkeypatch.setattr(
        KillSwitch,
        "stop",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("synthetic revocation failure")
        ),
    )
    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: lifecycle.append("guard") or object(),
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: lifecycle.append("boundary"),
    )
    monkeypatch.setattr(
        sidecar,
        "prepare_runtime",
        lambda: lifecycle.append("prepare") or tmp_path,
    )
    monkeypatch.setattr(sidecar.os, "chdir", lambda path: lifecycle.append("chdir"))
    monkeypatch.setattr(
        desktop_runtime,
        "DesktopRuntimeManager",
        lambda root: lifecycle.append("manager"),
    )

    with pytest.raises(
        sidecar.DesktopSwitchRevocationUnproven,
        match="permit may still be RUN",
    ):
        sidecar.main([])

    assert lifecycle == ["guard", "boundary", "prepare"]
    assert claim_path.read_bytes() == (
        b"daedalus-desktop-initial-arm/1\nstate=PENDING\n"
    )
    assert switch_path.read_bytes().splitlines()[0] == b"RUN"


def test_safely_stopped_initialization_refusal_still_starts_read_only_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from daedalus import budget, desktop_runtime
    from daedalus.foundation import env as foundation_env
    from daedalus.interfaces.http import web_api
    from daedalus.spine import effect_boundary

    lifecycle: list[object] = []

    class HarnessStop(RuntimeError):
        pass

    class Manager:
        def __init__(self, root: Path) -> None:
            lifecycle.append(("manager", root))

        def bootstrap(self) -> None:
            lifecycle.append("bootstrap")

        def close(self) -> None:
            lifecycle.append("close")

    def fake_web_main(argv, *, on_bound=None):
        lifecycle.append(("web", argv))
        assert on_bound is not None
        on_bound()
        raise HarnessStop("end read-only harness")

    monkeypatch.setattr(
        budget,
        "process_guard_boundary_decision",
        lambda: lifecycle.append("guard") or SimpleNamespace(),
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: lifecycle.append("boundary"),
    )
    monkeypatch.setattr(
        sidecar,
        "prepare_runtime",
        lambda: lifecycle.append("prepare") or tmp_path,
    )
    monkeypatch.setattr(
        sidecar,
        "initialize_desktop_switch_once",
        lambda: (_ for _ in ()).throw(
            sidecar.DesktopSwitchInitializationRefused("safely stopped")
        ),
    )
    monkeypatch.setattr(
        sidecar.os,
        "chdir",
        lambda root: lifecycle.append(("chdir", root)),
    )
    monkeypatch.setattr(
        foundation_env,
        "load_env",
        lambda path: lifecycle.append(("env", path)),
    )
    monkeypatch.setattr(desktop_runtime, "DesktopRuntimeManager", Manager)
    monkeypatch.setattr(
        desktop_runtime,
        "install_tunnel_egress_policy",
        lambda: lifecycle.append("policy"),
    )
    monkeypatch.setattr(
        desktop_runtime,
        "install_web_integration",
        lambda module, manager: lifecycle.append("integration"),
    )
    monkeypatch.setattr(web_api, "main", fake_web_main)

    with pytest.raises(HarnessStop, match="end read-only harness"):
        sidecar.main(["--port", "9876"])

    assert lifecycle == [
        "guard",
        "boundary",
        "prepare",
        ("chdir", tmp_path),
        ("env", tmp_path / ".env"),
        ("manager", tmp_path),
        "policy",
        "integration",
        ("web", ["--port", "9876"]),
        "bootstrap",
        "close",
    ]
