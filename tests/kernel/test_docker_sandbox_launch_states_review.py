# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from daedalus.kernel import sandbox
from daedalus.kernel.sandbox import (
    DockerSandboxPolicy,
    SandboxExecutionReceipt,
    run_in_docker_sandbox,
)

IMAGE = "daedalus-attempt@sha256:" + "a" * 64
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def policy(tmp_path: Path) -> DockerSandboxPolicy:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    return DockerSandboxPolicy(image=IMAGE, candidate_workspace=workspace, timeout_s=1)


def test_legacy_returncode_125_is_intrinsically_inferred_as_refusal() -> None:
    receipt = SandboxExecutionReceipt(
        argv_sha256="a" * 64,
        returncode=125,
        timed_out=False,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
    )
    assert receipt.launch_state == "refused-before-start"
    assert receipt.error_code == "docker-cli-refused"
    assert receipt.refused_before_start is True


def test_explicit_completed_returncode_125_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be a completed attempt"):
        SandboxExecutionReceipt(
            argv_sha256="a" * 64,
            returncode=125,
            timed_out=False,
            stdout_sha256=EMPTY_SHA,
            stderr_sha256=EMPTY_SHA,
            launch_state="completed",
        )


def test_os_exception_message_is_not_retained_in_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise FileNotFoundError("credential=SUPER-SECRET")

    monkeypatch.setattr(subprocess, "run", fail)
    receipt = run_in_docker_sandbox(policy(tmp_path), ("python", "-V"))
    assert receipt.error_code == "runtime-not-found"
    assert "SUPER-SECRET" not in str(receipt.to_dict())


def test_sandbox_boundary_contains_no_host_fallback_dispatch() -> None:
    source = Path(sandbox.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "fallback" not in source.lower().replace("no host\nfallback", "")
    assert "subprocess.run" in source
