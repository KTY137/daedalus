"""Independent computer-tool acceptance through real persisted kernel leases."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import ComputerPolicy, FILE_TOOLS, load_policy, policy_path
from daedalus.kernel.offload_lease import WaveLeaseDenied
from daedalus.runtimes import computer as subject
from daedalus.spine.envelope import canonical_sha
from daedalus.spine import killswitch


@pytest.fixture
def configured(tmp_path, monkeypatch):
    # All control/key/ledger state is test-owned. The OS-profile constant is
    # patched together with the environment, preserving their agreement check.
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace=workspace, tools=FILE_TOOLS)
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="isolated computer acceptance fixture").running
    service = subject.ComputerService(authority)
    # Observe real issuer outputs without substituting policy or lease logic.
    grants = []
    real_acquire = subject.acquire_effect_lease
    def acquire(*args, **kwargs):
        result = real_acquire(*args, **kwargs)
        grants.append(result)
        return result
    monkeypatch.setattr(subject, "acquire_effect_lease", acquire)
    yield service, workspace, policy, path, switch, grants
    service.close()


def run(service, tool, args, attempt="attempt-1"):
    return service.execute(tool, args, mission_id="computer-fixture", attempt_id=attempt)


def assert_no_lease_side_effects(service):
    assert not (service.control / "computer-execution.lock").exists()
    assert not (service.control / "effect-lease-issuer.key").exists()
    assert not (service.control / "effect-leases.sqlite3").exists()
    assert not (service.control / "computer-effect-evidence").exists()


def test_file_tools_are_projected_and_replacement_stays_fenced(configured):
    """G1-IKARUS-25: the five file tools are offered again through the
    handle-anchored adapter, while replacing an existing file (the two-rename
    protocol without a service-owned crash reconciliation) is neither offered
    nor executable, and its refusal never issues a lease."""
    service, workspace, _, _, _, grants = configured
    projected = {tool["name"]: tool for tool in service.capabilities()["tools"]}
    assert set(projected) == {"file.list", "file.read", "file.write", "file.mkdir", "file.move"}
    assert "expected_sha256" not in projected["file.write"]["parameters"]["properties"]
    assert "NEW" in projected["file.write"]["description"]
    assert "replac" in service.capabilities()["path_io_release_lock"]
    result = run(service, "file.write", {"path": "hello.txt", "text": "x", "expected_sha256": "0" * 64}, "replace")
    assert result["state"] == "blocked", result
    assert "replac" in result["error"] and "handle-relative" not in result["error"]
    assert list(workspace.iterdir()) == []
    assert grants == []
    assert_no_lease_side_effects(service)


def test_release_capability_projection_contains_no_path_based_vision_schema():
    assert subject._release_tool_spec("file.read") is not None
    assert subject._release_tool_spec("vision.match") is None
    assert subject._release_tool_spec("vision.changes") is None
    for tool in ("vision.inspect", "vision.ocr"):
        projected = subject._release_tool_spec(tool)
        assert projected is not None
        _, schema = projected
        assert schema["properties"] == {"observation_id": {"type": "string"}}
        assert schema["required"] == ["observation_id"]


def test_denied_tool_and_malformed_arguments_have_no_lease_or_effect(configured):
    service, workspace, _, _, _, grants = configured
    cases = [("desktop.type", {"observation_id": "x", "text": "bad", "expected": "never"}),
             ("file.write", {"path": "hello.txt", "text": "x", "extra": True}),
             ("file.write", {"path": "hello.txt"}),
             ("file.write", {"path": "../outside.txt", "text": "x"})]
    for tool, args in cases:
        result = run(service, tool, args)
        assert result["state"] == "blocked", result
    assert list(workspace.iterdir()) == []
    assert grants == []


@pytest.mark.parametrize("arguments", [{}, {"source": "image.png"},
                                        {"observation_id": "fresh", "source": "image.png"}])
def test_generic_issuer_refuses_non_observation_vision_shapes_without_state(configured, arguments):
    service, workspace, policy, path, switch, _ = configured
    service.close()
    observation_only = replace(policy, tools=("vision.inspect",))
    path.write_text(json.dumps(observation_only.to_dict()), encoding="utf-8")
    operation = {"tool": "vision.inspect", "arguments": arguments,
                 "policy_sha256": observation_only.digest}
    result = subject.acquire_effect_lease(
        service.authority_root, entrypoint_id=subject.ENTRYPOINT,
        source_revision="1" * 40, mission_id="issuer-observation-fixture",
        attempt_id="shape-" + canonical_sha(arguments)[:16],
        positions=1, tools=("vision.inspect",), operation_sha256=canonical_sha(operation),
        switch=switch, computer_operation=operation,
    )
    assert isinstance(result, WaveLeaseDenied), result
    assert any(not guard.allowed and guard.contract == "computer.tool_policy" for guard in result.guard_decisions)
    assert list(workspace.iterdir()) == []
    assert_no_lease_side_effects(service)


def test_unavailable_release_capability_refuses_before_lease_or_state(configured):
    service, workspace, policy, path, _, grants = configured
    service.close()
    observation_without_desktop = replace(policy, tools=("vision.inspect",))
    path.write_text(json.dumps(observation_without_desktop.to_dict()), encoding="utf-8")
    service = subject.ComputerService(service.authority_root)
    assert service.capabilities()["enabled"] is False
    result = run(service, "vision.inspect", {"observation_id": "not-observed"}, "unavailable")
    assert result["state"] == "blocked"
    assert "requires desktop.observe" in result["error"]
    assert grants == []
    assert list(workspace.iterdir()) == []
    assert_no_lease_side_effects(service)
    service.close()


def test_missing_current_observation_refuses_before_lease_or_state(configured, monkeypatch):
    service, workspace, policy, path, _, grants = configured
    service.close()
    observation_policy = replace(policy, tools=("desktop.observe", "vision.inspect"))
    path.write_text(json.dumps(observation_policy.to_dict()), encoding="utf-8")
    monkeypatch.setattr(subject, "_release_unavailable_reason", lambda _policy, _tool: "")
    service = subject.ComputerService(service.authority_root)
    result = run(service, "vision.inspect", {"observation_id": "not-observed"}, "missing-observation")
    assert result["state"] == "blocked"
    assert "current policy-scoped desktop observation" in result["error"]
    assert grants == []
    assert list(workspace.iterdir()) == []
    assert_no_lease_side_effects(service)
    service.close()


def test_observation_backed_vision_succeeds_with_desktop_coordinate_frame(configured, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")
    service, _, policy, path, _, grants = configured
    service.close()
    observation_policy = replace(policy, tools=("desktop.observe", "vision.inspect"))
    path.write_text(json.dumps(observation_policy.to_dict()), encoding="utf-8")
    monkeypatch.setattr(subject, "_release_unavailable_reason", lambda _policy, _tool: "")
    pixels = numpy.full((4, 5, 3), 127, dtype=numpy.uint8)
    encoded, png = cv2.imencode(".png", pixels)
    assert encoded

    class ObservedDesktop:
        def require_fresh_observation(self, observation_id):
            if observation_id != "fresh-observation":
                raise subject.ComputerRefused("desktop observation is stale or unavailable")

        def capture_png(self, observation_id):
            self.require_fresh_observation(observation_id)
            return png.tobytes(), {
                "origin_x": -100, "origin_y": 20, "monitor_id": "monitor-1",
                "window_id": "window-1", "captured_at": "2026-09-05T00:00:00+00:00",
            }

        def close(self):
            pass

    service = subject.ComputerService(service.authority_root)
    service._desktop = ObservedDesktop()
    assert "vision.inspect" in {tool["name"] for tool in service.capabilities()["tools"]}
    result = run(service, "vision.inspect", {"observation_id": "fresh-observation"}, "observed-vision")
    assert result["ok"] is True, result
    frame = result["result"]["image"]["coordinate_frame"]
    assert frame["coordinate_space"] == "desktop"
    assert frame["origin_x"] == -100
    assert frame["origin_y"] == 20
    assert frame["monitor_id"] == "monitor-1"
    assert frame["window_id"] == "window-1"
    assert len(grants) == 1 and grants[0].granted is True
    service.close()


def test_policy_drift_and_cancel_prevent_all_file_effects(configured):
    service, workspace, policy, path, switch, grants = configured
    path.write_text(json.dumps(replace(policy, tools=("file.read",)).to_dict()), encoding="utf-8")
    drifted = run(service, "file.write", {"path": "drift.txt", "text": "x"})
    assert drifted["state"] == "blocked"
    assert "policy changed" in drifted["error"]
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch.stop("fixture cancellation")
    stopped = run(service, "file.write", {"path": "stop.txt", "text": "x"})
    assert stopped["state"] == "blocked"
    assert list(workspace.iterdir()) == []
    assert grants == []


def test_ancestor_swap_at_the_checkpoint_never_writes_outside_the_workspace(configured, monkeypatch):
    """The retained COMPUTER-01 race, now answered by the adapter instead of
    the fence: on Windows the open parent is pinned so the swap itself fails
    and the write lands at the verified path; elsewhere the adapter refuses
    after the checkpoint. In no outcome does a byte reach ``outside``."""
    service, workspace, _, _, _, grants = configured
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    real_check = service.check_cancelled
    outcome: list[str] = []

    def swap_checked_ancestor():
        real_check()
        if outcome or service._files is None:
            return   # only the adapter's own checkpoint, after the parent is open
        try:
            (workspace / "sub").rename(workspace / "sub-original")
        except PermissionError:
            outcome.append("pinned")
            return
        try:
            (workspace / "sub").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            (workspace / "sub-original").rename(workspace / "sub")
            pytest.skip(f"symlink creation unavailable on host: {exc}")
        outcome.append("moved")

    monkeypatch.setattr(service, "check_cancelled", swap_checked_ancestor)
    result = run(service, "file.write", {"path": "sub/escaped.txt", "text": "escaped"}, "swap-race")
    assert outcome in (["pinned"], ["moved"])
    assert not (outside / "escaped.txt").exists() and list(outside.iterdir()) == []
    if outcome == ["pinned"]:
        assert result["state"] == "completed" and result["result"]["postcondition_verified"] is True
        assert (workspace / "sub" / "escaped.txt").read_bytes() == b"escaped"
    else:
        assert result["state"] == "blocked" and "changed during" in result["error"]
        assert not (workspace / "sub-original" / "escaped.txt").exists()
    assert len(grants) == 1


def test_replacement_attempts_never_reach_lease_or_adapter(configured, monkeypatch):
    service, workspace, _, _, _, grants = configured
    monkeypatch.setattr(service, "_dispatch", lambda *args: pytest.fail("release fence entered adapter"))
    args = {"path": "once.txt", "text": "once", "expected_sha256": "0" * 64}
    assert run(service, "file.write", args)["state"] == "blocked"
    assert run(service, "file.write", args)["state"] == "blocked"
    assert not workspace.joinpath("once.txt").exists()
    assert grants == []


def test_private_path_read_seam_is_still_fail_closed(configured):
    """Path-based vision reads keep the retired pathname helper fenced; the
    file tools no longer have a pathname seam at all."""
    service, workspace, _, _, _, _ = configured
    with pytest.raises(subject.ComputerRefused, match="handle-relative"):
        service._read_bytes("private.txt")
    assert not hasattr(service, "_file")
    assert not workspace.joinpath("private.txt").exists()


def test_deadline_refuses_before_admission(configured, monkeypatch):
    service, workspace, _, _, _, grants = configured
    monkeypatch.setattr(service, "_deadline", -1)
    result = run(service, "file.write", {"path": "late.txt", "text": "x"})
    assert result["state"] == "blocked"
    assert "deadline" in result["error"]
    assert grants == []
    assert list(workspace.iterdir()) == []


def test_setup_creates_fixed_workspace_and_retains_existing_policy(configured):
    service, _, policy, path, _, _ = configured
    before = path.read_bytes()
    existing = subject.setup_computer(service.authority_root, owner_confirmed=True)
    assert existing["created"] is False
    assert path.read_bytes() == before
    fresh = service.authority_root.parent / "fresh-authority"
    fresh.mkdir()
    created = subject.setup_computer(fresh, owner_confirmed=True)
    assert created["ok"] is True, created
    assert created["created"] is True
    assert Path(created["workspace"]).is_dir()
    assert Path(created["workspace"]) != policy.workspace
    assert load_policy(fresh).tools == ()
    assert created["tools"] == []
    assert killswitch.KillSwitch(repo_root=fresh).read_state().running
    assert created["evidence"]


def test_setup_requires_owner_intent_and_preserves_sticky_stop(configured):
    service, _, _, _, _, _ = configured
    fresh = service.authority_root.parent / "stopped-authority"
    fresh.mkdir()
    with pytest.raises(subject.ComputerRefused, match="owner"):
        subject.setup_computer(fresh)
    assert not policy_path(fresh).exists()
    switch = killswitch.KillSwitch(repo_root=fresh, sweep_managed=False)
    switch.stop("fixture operator stop before setup")
    with pytest.raises(killswitch.LoopHalted):
        subject.setup_computer(fresh, owner_confirmed=True)
    assert not switch.read_state().running
    assert not policy_path(fresh).exists()


@pytest.mark.parametrize("tamper", ["missing_operation", "wrong_digest", "wrong_tool", "extra_tool", "stale_policy"])
def test_generic_issuer_refuses_unbound_computer_authority(configured, tamper):
    service, workspace, policy, _, switch, _ = configured
    operation = {"tool": "file.write", "arguments": {"path": "unadmitted.txt", "text": "never"},
                 "policy_sha256": policy.digest}
    tools = ("file.write",)
    if tamper == "stale_policy":
        operation["policy_sha256"] = "0" * 64
    digest = canonical_sha(operation)
    if tamper == "wrong_digest":
        digest = "0" * 64
    elif tamper == "wrong_tool":
        tools = ("file.read",)
    elif tamper == "extra_tool":
        tools = ("file.write", "file.read")
    result = subject.acquire_effect_lease(
        service.authority_root, entrypoint_id=subject.ENTRYPOINT,
        source_revision="1" * 64, mission_id="issuer-computer-fixture", attempt_id=tamper,
        positions=1, tools=tools, operation_sha256=digest, switch=switch,
        computer_operation=None if tamper == "missing_operation" else operation,
    )
    assert isinstance(result, WaveLeaseDenied), result
    assert any(not guard.allowed and guard.contract == "computer.tool_policy" for guard in result.guard_decisions)
    assert list(workspace.iterdir()) == []


def _record_terminal_outcomes(monkeypatch):
    """Observe every terminal receipt the real kernel writes, without replacing it."""
    from daedalus.kernel import authorization
    terminals: list[dict] = []
    real = authorization.NonRuntimeEffectAuthorization.finish_effect

    def finish(self, receipt, *args, **kwargs):
        terminals.append({"outcome": kwargs.get("outcome", args[0] if args else None),
                          "detail_sha256": kwargs.get("detail_sha256")})
        return real(self, receipt, *args, **kwargs)

    monkeypatch.setattr(authorization.NonRuntimeEffectAuthorization, "finish_effect", finish)
    return terminals


@pytest.mark.parametrize("observed", ["cancellation", "policy drift", "typed no-effect interruption"])
def test_a_refusal_observed_after_the_effect_landed_is_never_reported_as_no_effect(configured, monkeypatch, observed):
    """Cerberus F1 (phase-2 review): the post-dispatch checkpoint raises a plain
    ComputerRefused after the host mutation. The classifier must not turn that
    into ``blocked`` with a CANCELLED terminal, because the effect happened;
    the lease stays STARTED for reconciliation."""
    service, workspace, policy, path, switch, grants = configured
    if os.name != "nt":
        pytest.skip("file tools are Windows-only in this release")
    outcomes = _record_terminal_outcomes(monkeypatch)
    target = workspace / "landed.txt"

    def probe() -> bool:
        if not target.exists():
            return False  # every pre-effect checkpoint passes; the write proceeds
        if observed == "policy drift":
            path.write_text(json.dumps(replace(policy, tools=("file.read",)).to_dict()), encoding="utf-8")
            return False  # the digest check behind the probe fires instead
        if observed == "typed no-effect interruption":
            # Council hint (local seat, 2026-09-05): an exception that CLAIMS
            # effect_state "none" after the adapter returned must not be
            # believed; the dispatched flag outranks the annotation.
            from daedalus.runtimes.computer_files import ComputerFileInterrupted
            raise ComputerFileInterrupted("late interrupt", effect_state="none")
        return True

    service.set_cancellation_probe(probe)
    result = run(service, "file.write", {"path": "landed.txt", "text": "landed"})
    assert target.read_text(encoding="utf-8") == "landed"
    assert result["state"] == "reconciliation_required", result
    assert all(terminal["outcome"] != "CANCELLED" for terminal in outcomes), outcomes
    assert len(grants) == 1


def _stored_artifact(service, sha256: str) -> dict:
    return json.loads((service.control / "computer-artifacts" / f"{sha256}.json").read_text(encoding="utf-8"))


def test_replacement_fence_claim_and_enforcement_share_one_source(configured, monkeypatch):
    """Cerberus F2: the projected schema, the capability claim and the kernel
    fence all read RELEASE_REPLACE_FENCED at call time, so the claim can never
    say "disabled" while the fence admits, or the reverse."""
    from daedalus.kernel.policy import computer as policy_module
    service, workspace, policy, path, switch, grants = configured
    replacement = {"path": "note.txt", "text": "data", "expected_sha256": "0" * 64}
    assert policy_module.RELEASE_REPLACE_FENCED is True  # the release state
    assert "expected_sha256" not in subject._release_tool_spec("file.write")[1]["properties"]
    assert "expected_sha256" in service.capabilities()["path_io_release_lock"]
    with pytest.raises(subject.ComputerRefused, match="replac"):
        policy_module.enforce_release_tool_fence("file.write", replacement)
    monkeypatch.setattr(policy_module, "RELEASE_REPLACE_FENCED", False)
    assert "expected_sha256" in subject._release_tool_spec("file.write")[1]["properties"]
    assert "expected_sha256" not in service.capabilities()["path_io_release_lock"]
    policy_module.enforce_release_tool_fence("file.write", replacement)


def test_failure_records_persist_the_adapter_recovery_paths(configured, monkeypatch):
    """Cerberus F3: a failure after the lease began leaves a digest-bound record
    in CAS carrying error class, message, effect_state and recovery_paths; the
    response points at it and a CANCELLED terminal binds the same digest."""
    from daedalus.runtimes.computer_files import ComputerFileEffectUncertain
    service, workspace, policy, path, switch, grants = configured
    if os.name != "nt":
        pytest.skip("file tools are Windows-only in this release")
    terminals = _record_terminal_outcomes(monkeypatch)
    recovery = ("note.txt", ".daedalus-internal-0000.daedalus-backup")

    def uncertain(tool, arguments):
        raise ComputerFileEffectUncertain("verification failed after the rename", recovery_paths=recovery)

    monkeypatch.setattr(service, "_dispatch", uncertain)
    result = run(service, "file.write", {"path": "note.txt", "text": "data"})
    assert result["state"] == "reconciliation_required", result
    stored = _stored_artifact(service, result["evidence"]["failure_record"]["sha256"])
    assert stored["schema"] == "daedalus-computer-failure/1"
    assert stored["error_type"] == "ComputerFileEffectUncertain"
    assert stored["effect_state"] == "uncertain"
    assert stored["recovery_paths"] == list(recovery)
    assert stored["tool"] == "file.write" and len(stored["operation_sha256"]) == 64
    assert terminals == []  # the lease stays STARTED for reconciliation

    def refused(tool, arguments):
        raise subject.ComputerRefused("changed during operation")

    monkeypatch.setattr(service, "_dispatch", refused)
    result = run(service, "file.write", {"path": "other.txt", "text": "data"}, attempt="attempt-2")
    assert result["state"] == "blocked", result
    record = result["evidence"]["failure_record"]["sha256"]
    assert _stored_artifact(service, record)["effect_state"] is None
    assert terminals == [{"outcome": "CANCELLED", "detail_sha256": record}]


def test_file_results_declare_the_handle_anchored_scope(configured):
    """The stored result names how the path was resolved: file tools run through
    the handle-anchored adapter, so their artifacts no longer claim the
    retired policy-relative pathname resolution."""
    service, workspace, policy, path, switch, grants = configured
    if os.name != "nt":
        pytest.skip("file tools are Windows-only in this release")
    result = run(service, "file.write", {"path": "scope.txt", "text": "data"})
    assert result["state"] == "completed", result
    stored = _stored_artifact(service, result["evidence"]["artifact"]["sha256"])
    assert stored["filesystem_scope_kind"] == "handle-anchored-computer-workspace"


def test_every_release_fence_constant_is_read_at_call_time(monkeypatch):
    """Odysseus O-1 (F2 generalised): no release constant may be bound by value
    into the runtime, or the projected capability and the kernel fence disagree
    the moment a release packet edits it."""
    from daedalus.kernel.policy import computer as policy_module

    move = {"source": "a", "destination": "b", "expected_sha256": "0" * 64}
    assert subject._release_tool_spec("file.move") is not None
    monkeypatch.setattr(policy_module, "RELEASE_DISABLED_TOOLS",
                        frozenset(policy_module.RELEASE_DISABLED_TOOLS | {"file.move"}))
    with pytest.raises(subject.ComputerRefused):
        policy_module.enforce_release_tool_fence("file.move", move)
    assert subject._release_tool_spec("file.move") is None, (
        "the projection still offers a tool the kernel fence now refuses")


def test_release_locked_tools_are_reported_unavailable_not_silently_dropped(configured, monkeypatch):
    """G1-IKARUS-26; the counter-cases are Codex's (room, 2026-09-05 16:49): every tool
    locked, a mixed policy, and a missing adapter dependency."""
    import importlib.util

    from daedalus.kernel.policy.computer import RELEASE_DISABLED_TOOLS, enforce_release_tool_fence

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: object()
        if name == "playwright"
        else real_find_spec(name, *a, **k),
    )

    # The locked set is read from the fence itself, not hardcoded: the main tree
    # lifted the file tools in G1-IKARUS-25 phase 2 while vision.match and
    # vision.changes stay locked (review session 6e, 2026-09-05 17:20).
    locked = tuple(sorted(RELEASE_DISABLED_TOOLS))
    assert locked, "the release fence names at least one locked tool"
    service, _, policy, path, _, _ = configured
    service.close()
    path.write_text(json.dumps(replace(policy, tools=locked).to_dict()), encoding="utf-8")
    locked_service = subject.ComputerService(service.authority_root)
    try:
        caps = locked_service.capabilities()
        assert caps["enabled"] is False and caps["tools"] == []
        assert set(caps["unavailable"]) == set(locked)
        assert all("handle-relative" in reason for reason in caps["unavailable"].values())
    finally:
        locked_service.close()
    path.write_text(json.dumps(replace(policy, tools=locked + ("browser.read",)).to_dict()), encoding="utf-8")
    mixed_service = subject.ComputerService(service.authority_root)
    try:
        caps = mixed_service.capabilities()
        assert caps["enabled"] is True
        assert [tool["name"] for tool in caps["tools"]] == ["browser.read"]
        assert set(caps["unavailable"]) == set(locked)
        enforce_release_tool_fence("browser.read", {})  # the executable shape is not fenced
        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name, *a, **k: None if name == "playwright" else real_find_spec(name, *a, **k))
        caps = mixed_service.capabilities()
        assert caps["enabled"] is False and caps["tools"] == []
        assert "Playwright" in caps["unavailable"]["browser.read"]
        assert all("handle-relative" in caps["unavailable"][tool] for tool in locked)
    finally:
        mixed_service.close()
