from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from daedalus.kernel.sandbox import (
    DockerSandboxPolicy,
    SandboxMount,
    SandboxPolicyError,
    run_in_docker_sandbox,
)

IMAGE = "daedalus-attempt@sha256:" + "a" * 64


def test_docker_policy_builds_non_root_offline_bounded_argv(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    reference = tmp_path / "reference"
    workspace.mkdir()
    reference.mkdir()
    policy = DockerSandboxPolicy(
        image=IMAGE,
        candidate_workspace=workspace,
        reference_mounts=(SandboxMount(reference, "/reference", True),),
    )
    argv = policy.argv(("python", "-m", "fixture"))
    joined = " ".join(argv)
    assert "--read-only" in argv
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges:true" in joined
    assert f"src={workspace.resolve()},dst=/workspace,rw" in joined
    assert f"src={reference.resolve()},dst=/reference,ro" in joined
    assert "--memory" in argv and "--cpus" in argv and "--pids-limit" in argv


def test_docker_policy_refuses_unpinned_root_network_and_unsafe_mounts(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    reference = tmp_path / "reference"
    workspace.mkdir()
    reference.mkdir()
    with pytest.raises(SandboxPolicyError, match="pinned"):
        DockerSandboxPolicy(image="daedalus:latest", candidate_workspace=workspace)
    with pytest.raises(SandboxPolicyError, match="non-root"):
        DockerSandboxPolicy(image=IMAGE, candidate_workspace=workspace, user="0:0")
    with pytest.raises(SandboxPolicyError, match="proxy network"):
        DockerSandboxPolicy(image=IMAGE, candidate_workspace=workspace, network="host")
    with pytest.raises(SandboxPolicyError, match="read-only"):
        DockerSandboxPolicy(
            image=IMAGE,
            candidate_workspace=workspace,
            reference_mounts=(SandboxMount(reference, "/reference", False),),
        )
    with pytest.raises(SandboxPolicyError, match="Docker socket"):
        DockerSandboxPolicy(
            image=IMAGE,
            candidate_workspace=workspace,
            reference_mounts=(SandboxMount(reference, "/var/run/docker.sock", True),),
        )


def test_runner_records_timeout_and_never_uses_shell(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    policy = DockerSandboxPolicy(image=IMAGE, candidate_workspace=workspace, timeout_s=1)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b"ok", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    receipt = run_in_docker_sandbox(policy, ("python", "-V"))
    assert receipt.returncode == 0
    assert receipt.timed_out is False
    assert seen["argv"][0:2] == ("docker", "run")
    assert "shell" not in seen["kwargs"]
