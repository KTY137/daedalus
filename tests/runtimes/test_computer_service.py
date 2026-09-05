"""Independent computer-tool acceptance through real persisted kernel leases."""
from __future__ import annotations

from dataclasses import replace
import json
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


def test_saved_file_grants_are_not_capabilities_or_executable(configured):
    service, workspace, _, _, _, grants = configured
    assert not [tool for tool in service.capabilities()["tools"] if tool["name"].startswith("file.")]
    assert "handle-relative" in service.capabilities()["path_io_release_lock"]
    calls = [
        ("file.list", {"path": "."}),
        ("file.read", {"path": "hello.txt"}),
        ("file.write", {"path": "hello.txt", "text": "Hello Ikarus\n"}),
        ("file.mkdir", {"path": "folder"}),
        ("file.move", {"source": "a", "destination": "b", "expected_sha256": "0" * 64}),
    ]
    for index, (tool, arguments) in enumerate(calls):
        result = run(service, tool, arguments, f"release-fence-{index}")
        assert result["state"] == "blocked", result
        assert "handle-relative" in result["error"]
    assert list(workspace.iterdir()) == []
    assert grants == []


def test_release_capability_projection_contains_no_path_based_vision_schema():
    assert subject._release_tool_spec("file.read") is None
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


def test_ancestor_swap_after_checkpoint_cannot_escape_release_fence(configured, monkeypatch):
    service, workspace, _, _, _, grants = configured
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    checked = service._policy.path("sub/escaped.txt")
    assert checked == workspace / "sub" / "escaped.txt"
    swapped = False

    def swap_checked_ancestor():
        nonlocal swapped
        if swapped:
            return
        (workspace / "sub").rename(workspace / "sub-original")
        try:
            (workspace / "sub").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable on host: {exc}")
        swapped = True

    monkeypatch.setattr(service, "check_cancelled", swap_checked_ancestor)
    monkeypatch.setattr(service, "_dispatch", lambda *args: pytest.fail("release fence entered adapter"))
    result = run(service, "file.write", {"path": "sub/escaped.txt", "text": "escaped"}, "swap-race")
    assert swapped is True
    assert result["state"] == "blocked"
    assert "handle-relative" in result["error"]
    assert not (outside / "escaped.txt").exists()
    assert grants == []


def test_repeated_disabled_attempt_never_reaches_lease_or_adapter(configured, monkeypatch):
    service, workspace, _, _, _, grants = configured
    monkeypatch.setattr(service, "_dispatch", lambda *args: pytest.fail("release fence entered adapter"))
    args = {"path": "once.txt", "text": "once"}
    assert run(service, "file.write", args)["state"] == "blocked"
    assert run(service, "file.write", args)["state"] == "blocked"
    assert not workspace.joinpath("once.txt").exists()
    assert grants == []


def test_private_file_and_path_read_seams_are_also_fail_closed(configured):
    service, workspace, _, _, _, _ = configured
    with pytest.raises(subject.ComputerRefused, match="handle-relative"):
        service._file("file.write", {"path": "private.txt", "text": "never"})
    with pytest.raises(subject.ComputerRefused, match="handle-relative"):
        service._read_bytes("private.txt")
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
