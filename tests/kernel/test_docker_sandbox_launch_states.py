from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest

from daedalus.kernel.sandbox import (
    DockerSandboxPolicy,
    SandboxExecutionReceipt,
    run_in_docker_sandbox,
)
from daedalus.spine.envelope import canonical_sha

IMAGE = "daedalus-attempt@sha256:" + "a" * 64
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def policy(tmp_path: Path) -> DockerSandboxPolicy:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    return DockerSandboxPolicy(
        image=IMAGE,
        candidate_workspace=workspace,
        timeout_s=1,
    )


def test_docker_cli_125_is_refused_before_attempt_start(tmp_path: Path, monkeypatch) -> None:
    seen = {}

    def refused(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 125, b"", b"daemon unavailable")

    monkeypatch.setattr(subprocess, "run", refused)
    receipt = run_in_docker_sandbox(policy(tmp_path), ("python", "-V"))
    assert receipt.launch_state == "refused-before-start"
    assert receipt.refused_before_start is True
    assert receipt.returncode == 125
    assert receipt.timed_out is False
    assert receipt.error_code == "docker-cli-refused"
    assert receipt.stderr_sha256 != EMPTY_SHA
    assert "shell" not in seen["kwargs"]
    assert seen["argv"][0:2] == ("docker", "run")


@pytest.mark.parametrize(
    ("exception", "error_code"),
    [
        (FileNotFoundError("docker"), "runtime-not-found"),
        (PermissionError("docker"), "runtime-not-executable"),
        (OSError("launch"), "runtime-launch-error"),
    ],
)
def test_os_launch_failures_are_pre_start_refusals(
    tmp_path: Path, monkeypatch, exception: OSError, error_code: str
) -> None:
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(subprocess, "run", fail)
    receipt = run_in_docker_sandbox(policy(tmp_path), ("python", "-V"))
    assert receipt.refused_before_start is True
    assert receipt.returncode is None
    assert receipt.timed_out is False
    assert receipt.error_code == error_code
    assert receipt.stdout_sha256 == EMPTY_SHA
    assert receipt.stderr_sha256 == EMPTY_SHA


def test_timeout_is_not_mislabeled_as_pre_start_refusal(tmp_path: Path, monkeypatch) -> None:
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1, output=b"partial", stderr=b"late")

    monkeypatch.setattr(subprocess, "run", timeout)
    receipt = run_in_docker_sandbox(policy(tmp_path), ("python", "-V"))
    assert receipt.launch_state == "timed-out"
    assert receipt.refused_before_start is False
    assert receipt.timed_out is True
    assert receipt.returncode is None
    assert receipt.error_code == "timeout"


def test_container_command_exit_127_remains_a_completed_attempt(
    tmp_path: Path, monkeypatch
) -> None:
    def completed(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 127, b"", b"command not found")

    monkeypatch.setattr(subprocess, "run", completed)
    receipt = run_in_docker_sandbox(policy(tmp_path), ("missing-command",))
    assert receipt.launch_state == "completed"
    assert receipt.refused_before_start is False
    assert receipt.returncode == 127
    assert receipt.error_code is None


def test_legacy_receipt_construction_infers_completed_or_timeout_state() -> None:
    completed = SandboxExecutionReceipt(
        argv_sha256="a" * 64,
        returncode=0,
        timed_out=False,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
    )
    timed_out = SandboxExecutionReceipt(
        argv_sha256="a" * 64,
        returncode=None,
        timed_out=True,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
    )
    assert completed.launch_state == "completed"
    assert timed_out.launch_state == "timed-out"


def test_malformed_launch_state_combinations_refuse() -> None:
    with pytest.raises(ValueError, match="terminal returncode"):
        SandboxExecutionReceipt(
            argv_sha256="a" * 64,
            returncode=None,
            timed_out=False,
            stdout_sha256=EMPTY_SHA,
            stderr_sha256=EMPTY_SHA,
            launch_state="completed",
        )
    with pytest.raises(ValueError, match="requires an error_code"):
        SandboxExecutionReceipt(
            argv_sha256="a" * 64,
            returncode=125,
            timed_out=False,
            stdout_sha256=EMPTY_SHA,
            stderr_sha256=EMPTY_SHA,
            launch_state="refused-before-start",
        )
    with pytest.raises(ValueError, match="attempt result"):
        SandboxExecutionReceipt(
            argv_sha256="a" * 64,
            returncode=1,
            timed_out=False,
            stdout_sha256=EMPTY_SHA,
            stderr_sha256=EMPTY_SHA,
            launch_state="refused-before-start",
            error_code="docker-cli-refused",
        )


def test_launch_classification_and_error_code_are_digest_bound() -> None:
    refused = SandboxExecutionReceipt(
        argv_sha256=canonical_sha(["docker", "run"]),
        returncode=125,
        timed_out=False,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
        launch_state="refused-before-start",
        error_code="docker-cli-refused",
    )
    changed = dataclasses.replace(refused, error_code="runtime-not-found", returncode=None)
    assert refused.digest != changed.digest
