"""Service-level acceptance for G1-IKARUS-25: file tools through the anchored adapter.

These cases describe the contract the wiring packet must satisfy: the five
file tools execute through ``WorkspaceFiles`` behind the unchanged canonical
admission, a refusal that provably performed no host effect is reported as
``blocked`` (not ``reconciliation_required``), the secret floor stays in the
service, and the vision path forms and skill reads stay fenced.

These cases were ``xfail(strict=True)`` until G1-IKARUS-25 phase 2 lifted the
fence for the file tools (replacement of an existing file stays fenced).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import (
    ComputerPolicy, ComputerRefused, FILE_TOOLS, enforce_release_tool_fence, policy_path,
    refuse_workspace_path_io,
)
from daedalus.runtimes import computer as subject
from daedalus.spine import killswitch

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def link_directory(target: Path, link: Path) -> None:
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.fixture
def configured(tmp_path, monkeypatch):
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
    assert switch.arm(note="isolated computer file acceptance fixture").running
    service = subject.ComputerService(authority)
    grants = []
    real_acquire = subject.acquire_effect_lease

    def acquire(*args, **kwargs):
        result = real_acquire(*args, **kwargs)
        grants.append(result)
        return result

    monkeypatch.setattr(subject, "acquire_effect_lease", acquire)
    yield service, workspace, policy, path, switch, grants
    service.close()


def run(service, tool, args, attempt):
    return service.execute(tool, args, mission_id="computer-files-fixture", attempt_id=attempt)


def test_file_tools_execute_through_the_anchored_adapter_with_persisted_leases(configured):
    service, workspace, _, _, _, grants = configured
    projected = {tool["name"] for tool in service.capabilities()["tools"]}
    assert set(FILE_TOOLS) <= projected
    written = run(service, "file.write", {"path": "hello.txt", "text": "Hello Ikarus\n"}, "w1")
    assert written["state"] == "completed", written
    assert written["result"]["postcondition_verified"] is True
    assert (workspace / "hello.txt").read_bytes() == b"Hello Ikarus\n"
    read = run(service, "file.read", {"path": "hello.txt"}, "r1")
    assert read["state"] == "completed" and read["result"]["text"] == "Hello Ikarus\n"
    made = run(service, "file.mkdir", {"path": "folder"}, "m1")
    assert made["state"] == "completed" and made["result"]["created"] is True
    listed = run(service, "file.list", {}, "l1")
    assert [entry["path"] for entry in listed["result"]["entries"]] == ["folder", "hello.txt"]
    moved = run(service, "file.move", {"source": "hello.txt", "destination": "folder/hello.txt",
                                       "expected_sha256": sha(b"Hello Ikarus\n")}, "v1")
    assert moved["state"] == "completed" and moved["result"]["postcondition_verified"] is True
    assert (workspace / "folder" / "hello.txt").read_bytes() == b"Hello Ikarus\n"
    assert not (workspace / "hello.txt").exists()
    assert len(grants) == 5
    for result in (written, read, made, listed, moved):
        assert {"artifact", "lease_sha256", "start_sha256", "terminal_sha256"} <= set(result["evidence"])
        assert result["evidence"]["artifact"]["sha256"]


def test_ancestor_swap_at_the_checkpoint_is_blocked_with_zero_effect(configured, monkeypatch):
    service, workspace, _, _, _, grants = configured
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    real_check = service.check_cancelled
    outcome: list[str] = []

    def swap_checked_ancestor():
        real_check()
        # The service also checkpoints before admission; the retained race is
        # the checkpoint the adapter runs AFTER the parent handle is open.
        if outcome or service._files is None:
            return
        try:
            (workspace / "sub").rename(workspace / "sub-original")
        except PermissionError:
            outcome.append("pinned")
            return
        link_directory(outside, workspace / "sub")
        outcome.append("moved")

    monkeypatch.setattr(service, "check_cancelled", swap_checked_ancestor)
    result = run(service, "file.write", {"path": "sub/escaped.txt", "text": "escaped"}, "swap-race")
    assert outcome in (["pinned"], ["moved"])
    assert list(outside.iterdir()) == []
    if outcome == ["pinned"]:
        assert result["state"] == "completed" and result["result"]["postcondition_verified"] is True
        assert (workspace / "sub" / "escaped.txt").read_bytes() == b"escaped"
    else:
        assert result["state"] == "blocked", result
        assert "changed during" in result["error"]
        assert not (workspace / "sub-original" / "escaped.txt").exists()
    assert len(grants) == 1


def test_parent_moved_out_of_the_workspace_never_receives_model_bytes(configured, monkeypatch):
    """Cerberus finding on G1-IKARUS-24: the assertion is 'nothing outside', not a flag."""
    service, workspace, _, _, _, grants = configured
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    real_check = service.check_cancelled
    attempts: list[str] = []

    def move_out():
        real_check()
        if attempts or service._files is None:
            return   # only the adapter's own checkpoint, after the parent is open
        try:
            (workspace / "sub").rename(outside / "sub")
            attempts.append("moved")
        except PermissionError:
            attempts.append("pinned")

    monkeypatch.setattr(service, "check_cancelled", move_out)
    result = run(service, "file.write", {"path": "sub/escaped.txt", "text": "MODEL BYTES"}, "move-out")
    assert attempts, "the checkpoint never ran"
    assert not list(outside.rglob("*")), "bytes reached the outside tree"
    if attempts == ["pinned"]:
        assert result["state"] == "completed" and result["result"]["postcondition_verified"] is True
        assert (workspace / "sub" / "escaped.txt").read_bytes() == b"MODEL BYTES"
    else:
        assert result["state"] == "blocked" and "changed during" in result["error"]
    assert len(grants) == 1


def test_file_tools_are_unavailable_outside_windows_in_this_release(configured, monkeypatch):
    service, _, _, _, _, _ = configured
    monkeypatch.setattr(os, "name", "posix")
    projected = {tool["name"] for tool in service.capabilities()["tools"]}
    assert not (set(FILE_TOOLS) & projected)
    unavailable = service.capabilities()["unavailable"]
    assert all("Windows" in unavailable[tool] for tool in FILE_TOOLS)


def test_secret_content_is_refused_before_the_adapter_and_withheld_on_read(configured):
    service, workspace, _, _, _, _ = configured
    leaked = "AKIA" + "ABCDEFGHIJKLMNOP"
    refused = run(service, "file.write", {"path": "creds.txt", "text": f"aws {leaked}\n"}, "s1")
    assert refused["state"] == "blocked" and "secret" in refused["error"]
    assert not (workspace / "creds.txt").exists()
    (workspace / "leaked.txt").write_text(f"key {leaked}\n", encoding="utf-8")
    read = run(service, "file.read", {"path": "leaked.txt"}, "s2")
    assert leaked not in json.dumps(read)
    assert read["state"] == "blocked" or read["result"].get("withheld") is True


def test_stale_or_missing_hash_refusals_are_blocked_not_reconciliation(configured):
    service, workspace, _, _, _, grants = configured
    assert run(service, "file.write", {"path": "a.txt", "text": "one"}, "h0")["state"] == "completed"
    missing = run(service, "file.write", {"path": "a.txt", "text": "two"}, "h1")
    assert missing["state"] == "blocked", missing
    assert "expected_sha256" in missing["error"]
    # Replacement itself stays fenced in this release: refused before any lease.
    stale = run(service, "file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"stale")}, "h2")
    assert stale["state"] == "blocked", stale
    assert "replac" in stale["error"]
    assert (workspace / "a.txt").read_bytes() == b"one"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]
    assert len(grants) == 2


def test_vision_path_forms_and_skill_reads_stay_fenced_after_the_lift():
    assert subject._release_tool_spec("vision.match") is None
    assert subject._release_tool_spec("vision.changes") is None
    for tool in FILE_TOOLS:
        assert subject._release_tool_spec(tool) is not None
    with pytest.raises(ComputerRefused, match="handle-relative"):
        enforce_release_tool_fence("vision.inspect", {"path": "shot.png"})
    with pytest.raises(ComputerRefused, match="handle-relative"):
        enforce_release_tool_fence("vision.match", {"observation_id": "fresh", "template": "t.png"})
    enforce_release_tool_fence("file.write", {"path": "a.txt", "text": "x"})
    enforce_release_tool_fence("file.list", {})
    with pytest.raises(ComputerRefused, match="handle-relative"):
        refuse_workspace_path_io()
