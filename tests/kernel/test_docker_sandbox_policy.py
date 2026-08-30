# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
    assert f"src={workspace.resolve()},dst=/workspace" in joined
    assert f"src={reference.resolve()},dst=/reference,ro" in joined
    assert "--memory" in argv and "--cpus" in argv and "--pids-limit" in argv


# Docker's --mount parser accepts only these bare (valueless) fields. A bare
# "rw" is rejected with exit 125, which run_in_docker_sandbox classifies as
# refused-before-start -- so an invalid spelling here silently degrades every
# sandboxed attempt into a refusal that never runs the container at all.
_BARE_MOUNT_FIELDS = frozenset({"readonly", "ro"})
_KEYED_MOUNT_FIELDS = frozenset(
    {
        "type",
        "source",
        "src",
        "destination",
        "dst",
        "target",
        "readonly",
        "ro",
        "bind-propagation",
        "consistency",
        "volume-nocopy",
        "volume-driver",
        "tmpfs-size",
        "tmpfs-mode",
    }
)


def test_every_mount_spec_uses_only_fields_the_docker_cli_accepts(tmp_path: Path) -> None:
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
    specs = [argv[index + 1] for index, part in enumerate(argv) if part == "--mount"]
    assert len(specs) == 2
    for spec in specs:
        for field in spec.split(","):
            if "=" in field:
                key = field.split("=", 1)[0]
                assert key in _KEYED_MOUNT_FIELDS, f"invalid --mount key {key!r} in {spec!r}"
            else:
                assert field in _BARE_MOUNT_FIELDS, (
                    f"invalid bare --mount field {field!r} in {spec!r}; "
                    "the Docker CLI rejects it with exit 125"
                )


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
