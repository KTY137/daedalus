"""Baseline for G1-IKARUS-28: path-based vision forms and the bytes seam.

Two kinds of test live here on purpose.

* The ``test_baseline_*`` tests are plain and must PASS. They pin the refusals
  that exist in the tree today, so the packet's baseline is a measurement and
  not an assumption. Two of them pin the *absence* of the proposed seam; the
  build phase deletes those with a note rather than weakening them.
* The remaining tests are strict xfails. They are the acceptance tests for the
  behaviour G1-IKARUS-28 proposes and has not built. Each marker names what is
  missing. When the seam lands they turn green; a premature green is a failure.

Nothing here executes a vision algorithm: OpenCV decoding belongs to
G1-IKARUS-CV-01. This file is about which bytes are allowed to reach it.
"""
from __future__ import annotations

import inspect
import json

import pytest

from daedalus.kernel.policy.computer import (
    ComputerPolicy,
    ComputerRefused,
    PATH_IO_RELEASE_REFUSAL,
    RELEASE_DISABLED_TOOLS,
    RELEASE_OBSERVATION_ONLY_TOOLS,
    VISION_TOOLS,
    enforce_release_tool_fence,
    policy_path,
    refuse_workspace_path_io,
)
from daedalus.runtimes import computer as subject
from daedalus.runtimes import computer_files
from daedalus.runtimes.computer_vision import VisionLimits
from daedalus.spine import killswitch


# A real 1x1 RGB PNG, so a future green build measures the sniff and not a stub.
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
)
SECRET_TEXT = b"AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"


def _xfail(what: str):
    return pytest.mark.xfail(strict=True, reason=f"G1-IKARUS-28 not built: {what}")


@pytest.fixture
def workspace_policy(tmp_path):
    """A policy that grants every vision tool, so refusals cannot be grant misses."""
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    (workspace / "shot.png").write_bytes(PNG_1X1)
    (workspace / "template.png").write_bytes(PNG_1X1)
    (workspace / "notes.txt").write_bytes(SECRET_TEXT)
    return ComputerPolicy(workspace=workspace, tools=VISION_TOOLS), workspace


@pytest.fixture
def vision_service(tmp_path, monkeypatch):
    """A real ComputerService whose policy grants the vision tools.

    Control, killswitch and profile state are test-owned, mirroring the
    isolation of tests/runtimes/test_computer_service.py.
    """
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    (workspace / "shot.png").write_bytes(PNG_1X1)
    policy = ComputerPolicy(workspace=workspace, tools=VISION_TOOLS + ("desktop.observe",))
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="G1-IKARUS-28 vision path baseline").running
    service = subject.ComputerService(authority)
    yield service, workspace
    service.close()


# --------------------------------------------------------------------------
# Baseline: the refusals that exist today. These must pass.
# --------------------------------------------------------------------------


def test_baseline_release_fence_inventory_is_the_vision_path_forms():
    """policy/computer.py:48 and :53 after the G1-IKARUS-25 file-tool lift."""
    assert RELEASE_DISABLED_TOOLS == frozenset({"vision.match", "vision.changes"})
    assert RELEASE_OBSERVATION_ONLY_TOOLS == frozenset({"vision.inspect", "vision.ocr"})


@pytest.mark.parametrize("tool, args", [
    ("vision.match", {"path": "shot.png", "template": "template.png"}),
    # The whole tool is disabled, so even the desktop-observation form refuses.
    ("vision.match", {"observation_id": "obs-1", "template": "template.png"}),
    ("vision.changes", {"before": "a.png", "after": "b.png"}),
])
def test_baseline_match_and_changes_are_release_disabled(tool, args):
    """enforce_release_tool_fence, policy/computer.py:87-88."""
    with pytest.raises(ComputerRefused) as caught:
        enforce_release_tool_fence(tool, args)
    assert str(caught.value) == PATH_IO_RELEASE_REFUSAL


@pytest.mark.parametrize("tool", ["vision.inspect", "vision.ocr"])
def test_baseline_inspect_and_ocr_admit_only_a_bare_observation_id(tool):
    """The exact-argument-set check at policy/computer.py:96-99."""
    assert enforce_release_tool_fence(tool, {"observation_id": "obs-1"}) is None
    for refused in ({"path": "shot.png"},
                    {"path": "shot.png", "observation_id": "obs-1"},
                    {"observation_id": ""},
                    {}):
        with pytest.raises(ComputerRefused) as caught:
            enforce_release_tool_fence(tool, refused)
        assert str(caught.value) == PATH_IO_RELEASE_REFUSAL


def test_baseline_policy_admit_refuses_path_vision_even_when_granted(workspace_policy):
    """ComputerPolicy.admit re-enters the fence at policy/computer.py:228."""
    policy, _ = workspace_policy
    assert set(VISION_TOOLS) <= set(policy.tools)
    for tool, args in (("vision.match", {"path": "shot.png", "template": "template.png"}),
                       ("vision.changes", {"before": "shot.png", "after": "template.png"}),
                       ("vision.inspect", {"path": "shot.png"}),
                       ("vision.ocr", {"path": "shot.png"})):
        with pytest.raises(ComputerRefused) as caught:
            policy.admit(tool, args)
        assert str(caught.value) == PATH_IO_RELEASE_REFUSAL


def test_baseline_service_read_bytes_is_fenced_before_it_touches_the_workspace(vision_service):
    """computer.py:328 refuses before the path work at :329-336."""
    service, workspace = vision_service
    assert workspace.joinpath("shot.png").read_bytes() == PNG_1X1
    with pytest.raises(ComputerRefused) as caught:
        service._read_bytes("shot.png")
    # The exact fence message, not "not regular"/"exceeds size": proves the
    # refusal happens before the file is resolved, opened or measured.
    assert str(caught.value) == PATH_IO_RELEASE_REFUSAL


def test_baseline_refuse_workspace_path_io_is_the_only_gate_at_the_seam():
    """Pins that the fence is unconditional and first. Deleted by the build."""
    with pytest.raises(ComputerRefused) as caught:
        refuse_workspace_path_io()
    assert str(caught.value) == PATH_IO_RELEASE_REFUSAL
    body = inspect.getsource(subject.ComputerService._read_bytes).splitlines()
    assert body[1].strip() == "refuse_workspace_path_io()", body[:3]


def test_baseline_capability_projection_hides_the_path_forms(vision_service):
    """_release_tool_spec, computer.py:73-74 and :83-85."""
    service, _ = vision_service
    assert subject._release_tool_spec("vision.match") is None
    assert subject._release_tool_spec("vision.changes") is None
    for tool in ("vision.inspect", "vision.ocr"):
        _, parameters = subject._release_tool_spec(tool)
        assert "path" not in parameters["properties"]
        assert parameters["required"] == ["observation_id"]
    lock = service.capabilities()["path_io_release_lock"]
    assert PATH_IO_RELEASE_REFUSAL in lock and lock.startswith("path-based vision")


def test_baseline_tool_specs_still_declare_the_path_forms():
    """computer.py:55-58: the schemas G1-IKARUS-28 must keep, not re-invent."""
    match = subject.TOOL_SPECS["vision.match"][1]
    assert set(match["properties"]) == {"path", "observation_id", "template", "threshold"}
    assert match["required"] == ["template"]
    changes = subject.TOOL_SPECS["vision.changes"][1]
    assert set(changes["properties"]) == {"before", "after"}
    assert changes["required"] == ["before", "after"]
    for tool in ("vision.inspect", "vision.ocr"):
        assert set(subject.TOOL_SPECS[tool][1]["properties"]) == {"path", "observation_id"}


def test_baseline_argument_shape_layer_already_accepts_a_path(workspace_policy):
    """computer.py:100-101 admits the shape; only the fence stops execution."""
    assert subject._validate_arguments("vision.inspect", {"path": "shot.png"}) is None
    assert subject._validate_arguments("vision.ocr", {"path": "shot.png"}) is None
    assert subject._validate_arguments(
        "vision.changes", {"before": "a.png", "after": "b.png"}) is None
    assert subject._validate_arguments(
        "vision.match", {"path": "shot.png", "template": "template.png"}) is None
    for args in ({}, {"path": "shot.png", "observation_id": "obs-1"}):
        with pytest.raises(ComputerRefused, match="exactly one"):
            subject._validate_arguments("vision.inspect", args)


def test_baseline_adapter_has_no_bytes_observation_seam():
    """The absent seam. Deleted by the build phase, never weakened."""
    assert not hasattr(computer_files.WorkspaceFiles, "read_bytes")
    assert not hasattr(computer_files, "IMAGE_OBSERVATION_MAX_BYTES")
    assert not hasattr(computer_files, "ImageBytes")
    # execute() is file-tool-only, so no vision tool can reach the traversal
    # helpers today (computer_files.py:658, :60-67).
    assert set(computer_files._ARGUMENTS) == set(computer_files.FILE_TOOLS)
    assert not set(VISION_TOOLS) & set(computer_files._ARGUMENTS)


def test_baseline_text_bound_is_smaller_than_the_vision_modules_image_bound(workspace_policy):
    """Why the seam needs its own bound: 1 MiB text vs 8 MiB image."""
    policy, _ = workspace_policy
    assert policy.max_file_bytes == 1_048_576
    assert VisionLimits().max_image_bytes == 8 * 1024 * 1024
    assert policy.max_file_bytes < VisionLimits().max_image_bytes


# --------------------------------------------------------------------------
# Acceptance for the unbuilt behaviour. Strict xfail until G1-IKARUS-28 lands.
# --------------------------------------------------------------------------


@_xfail("WorkspaceFiles.read_bytes(name, *, tool, args) does not exist")
def test_adapter_exposes_a_bytes_observation_seam(workspace_policy):
    policy, _ = workspace_policy
    signature = inspect.signature(computer_files.WorkspaceFiles.read_bytes)
    parameters = list(signature.parameters.values())[1:]
    assert [p.name for p in parameters] == ["name", "tool", "args"]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters[1:])


@_xfail("no seam, so a workspace image cannot be read for a vision tool")
def test_bytes_seam_returns_image_bytes_with_provenance(workspace_policy):
    policy, _ = workspace_policy
    files = computer_files.WorkspaceFiles(policy, lambda: None)
    record = files.read_bytes("shot.png", tool="vision.inspect", args={"path": "shot.png"})
    assert record.data == PNG_1X1
    assert record.path == "shot.png"
    assert record.image_format == "png"
    assert record.sha256 == __import__("hashlib").sha256(PNG_1X1).hexdigest()


@_xfail("read_bytes does not admit through policy.admit for the real vision tool")
def test_bytes_seam_admits_the_actual_vision_tool_not_a_synthetic_file_read(tmp_path):
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    (workspace / "shot.png").write_bytes(PNG_1X1)
    # file.read is granted, the vision tool is NOT: the seam must still refuse.
    policy = ComputerPolicy(workspace=workspace, tools=("file.read",))
    files = computer_files.WorkspaceFiles(policy, lambda: None)
    with pytest.raises(ComputerRefused, match="not enabled"):
        files.read_bytes("shot.png", tool="vision.inspect", args={"path": "shot.png"})


@_xfail("no PNG/JPEG magic sniff: text and secrets can flow through the path seam")
def test_bytes_seam_refuses_non_image_bytes(workspace_policy):
    policy, workspace = workspace_policy
    (workspace / "secret.png").write_bytes(SECRET_TEXT)
    files = computer_files.WorkspaceFiles(policy, lambda: None)
    for name in ("notes.txt", "secret.png"):
        with pytest.raises(ComputerRefused) as caught:
            files.read_bytes(name, tool="vision.inspect", args={"path": name})
        assert "image" in str(caught.value)
        assert b"AWS_SECRET" not in str(caught.value).encode()


@_xfail("no explicit image byte bound; the seam would inherit the 1 MiB text bound")
def test_bytes_seam_bounds_images_independently_of_max_file_bytes(workspace_policy):
    policy, workspace = workspace_policy
    assert computer_files.IMAGE_OBSERVATION_MAX_BYTES == VisionLimits().max_image_bytes
    files = computer_files.WorkspaceFiles(policy, lambda: None)
    # Larger than max_file_bytes (1 MiB) but a legitimate image: must be read.
    big = PNG_1X1 + b"\x00" * (policy.max_file_bytes + 1)
    (workspace / "big.png").write_bytes(big)
    assert files.read_bytes("big.png", tool="vision.inspect",
                            args={"path": "big.png"}).data == big


@_xfail("read_bytes does not run the adapter checkpoint before the read")
def test_bytes_seam_checkpoints_before_returning_data(workspace_policy):
    policy, _ = workspace_policy

    def refusing_checkpoint():
        raise ComputerRefused("computer task cancellation requested")

    files = computer_files.WorkspaceFiles(policy, refusing_checkpoint)
    with pytest.raises(ComputerRefused, match="cancellation"):
        files.read_bytes("shot.png", tool="vision.inspect", args={"path": "shot.png"})


@_xfail("no seam, so escapes and protected names are unmeasured on this path")
def test_bytes_seam_refuses_paths_outside_the_workspace(workspace_policy):
    policy, _ = workspace_policy
    files = computer_files.WorkspaceFiles(policy, lambda: None)
    for name in ("../outside.png", "C:/Windows/win.ini", ".git/config"):
        with pytest.raises(ComputerRefused):
            files.read_bytes(name, tool="vision.inspect", args={"path": name})


@_xfail("no seam yet, so its Windows release gate is unmeasured")
def test_bytes_seam_is_windows_only_like_the_rest_of_the_adapter():
    source = inspect.getsource(computer_files.WorkspaceFiles.read_bytes)
    assert "_effect_host_available()" in source


@_xfail("_read_bytes calls refuse_workspace_path_io() unconditionally at computer.py:328")
def test_service_read_bytes_routes_through_the_adapter_seam():
    source = inspect.getsource(subject.ComputerService._read_bytes)
    assert "refuse_workspace_path_io()" not in source
    assert "read_bytes(" in source


@_xfail("vision.match is in RELEASE_DISABLED_TOOLS (policy/computer.py:48)")
def test_vision_match_admits_a_workspace_template():
    assert enforce_release_tool_fence(
        "vision.match", {"path": "shot.png", "template": "template.png"}) is None


@_xfail("vision.changes is in RELEASE_DISABLED_TOOLS (policy/computer.py:48)")
def test_vision_changes_admits_two_workspace_images():
    assert enforce_release_tool_fence(
        "vision.changes", {"before": "a.png", "after": "b.png"}) is None


@_xfail("the exact-argument-set check admits only observation_id (policy/computer.py:96-99)")
@pytest.mark.parametrize("tool", ["vision.inspect", "vision.ocr"])
def test_vision_inspect_and_ocr_admit_the_path_form(tool):
    assert enforce_release_tool_fence(tool, {"path": "shot.png"}) is None


@_xfail("_release_tool_spec hides match/changes and strips path (computer.py:73-85)")
def test_capability_projection_offers_the_path_forms():
    assert subject._release_tool_spec("vision.match") is not None
    assert subject._release_tool_spec("vision.changes") is not None
    _, parameters = subject._release_tool_spec("vision.inspect")
    assert "path" in parameters["properties"]
