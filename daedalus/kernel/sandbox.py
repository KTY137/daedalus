"""Explicit Docker sandbox policy and fail-closed launch classification.

The policy is converted to argv without invoking a shell. It rejects privileged
or host-coupled configurations, makes the root filesystem read-only, grants one
bounded candidate workspace as the only writable bind mount, and keeps network
access off unless an explicit internal proxy network is selected.

A Docker CLI failure is not treated as an attempt result. Missing or
non-executable runtimes, operating-system launch failures, and Docker exit code
125 are represented as ``refused-before-start``. This module contains no host
fallback path.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from daedalus.spine.envelope import canonical_sha

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LAUNCH_STATES = frozenset({"completed", "timed-out", "refused-before-start"})


class SandboxPolicyError(ValueError):
    pass


def _sha256(value: str, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _hash(value: bytes | None) -> str:
    return hashlib.sha256(value or b"").hexdigest()


@dataclass(frozen=True)
class SandboxMount:
    source: Path
    target: str
    read_only: bool

    def __post_init__(self) -> None:
        source = Path(self.source).resolve()
        if not source.is_absolute():
            raise SandboxPolicyError("sandbox mount source must be absolute")
        if not self.target.startswith("/") or ".." in Path(self.target).parts:
            raise SandboxPolicyError("sandbox mount target must be absolute and normalized")
        object.__setattr__(self, "source", source)


@dataclass(frozen=True)
class DockerSandboxPolicy:
    image: str
    candidate_workspace: Path
    reference_mounts: tuple[SandboxMount, ...] = ()
    network: str = "none"
    user: str = "65532:65532"
    memory: str = "4g"
    cpus: str = "2"
    pids_limit: int = 256
    timeout_s: int = 1800
    tmpfs_size: str = "512m"

    def __post_init__(self) -> None:
        if not self.image.strip() or "latest" in self.image or "@sha256:" not in self.image:
            raise SandboxPolicyError("sandbox image must be pinned by sha256 digest")
        workspace = Path(self.candidate_workspace).resolve()
        if not workspace.is_dir():
            raise SandboxPolicyError("candidate workspace must be an existing directory")
        object.__setattr__(self, "candidate_workspace", workspace)
        if self.network != "none" and not self.network.startswith("daedalus-egress-"):
            raise SandboxPolicyError("sandbox network must be none or a bounded Daedalus proxy network")
        if self.user in {"0", "0:0", "root"}:
            raise SandboxPolicyError("sandbox must run as non-root")
        if self.pids_limit < 1 or self.timeout_s < 1:
            raise SandboxPolicyError("sandbox resource limits must be positive")
        writable = [mount for mount in self.reference_mounts if not mount.read_only]
        if writable:
            raise SandboxPolicyError("reference mounts must be read-only")
        forbidden = {"/var/run/docker.sock", "/run/docker.sock"}
        for mount in self.reference_mounts:
            if mount.target in forbidden or str(mount.source) in forbidden:
                raise SandboxPolicyError("Docker socket mounts are forbidden")
            if mount.source == workspace:
                raise SandboxPolicyError("candidate workspace cannot be duplicated as a reference mount")

    def argv(self, command: Iterable[str]) -> tuple[str, ...]:
        cmd = tuple(str(part) for part in command)
        if not cmd or any(not part for part in cmd):
            raise SandboxPolicyError("sandbox command must be non-empty")
        argv = [
            "docker", "run", "--rm", "--init", "--read-only",
            "--network", self.network,
            "--memory", self.memory,
            "--memory-swap", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", str(self.pids_limit),
            "--user", self.user,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--mount", f"type=bind,src={self.candidate_workspace},dst=/workspace",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={self.tmpfs_size}",
            "--workdir", "/workspace",
        ]
        for mount in sorted(self.reference_mounts, key=lambda item: item.target):
            spec = f"type=bind,src={mount.source},dst={mount.target}"
            if mount.read_only:
                spec += ",ro"
            argv.extend(["--mount", spec])
        argv.append(self.image)
        argv.extend(cmd)
        return tuple(argv)


@dataclass(frozen=True)
class SandboxExecutionReceipt:
    argv_sha256: str
    returncode: int | None
    timed_out: bool
    stdout_sha256: str
    stderr_sha256: str
    launch_state: str = ""
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv_sha256", _sha256(self.argv_sha256, "argv_sha256"))
        object.__setattr__(self, "stdout_sha256", _sha256(self.stdout_sha256, "stdout_sha256"))
        object.__setattr__(self, "stderr_sha256", _sha256(self.stderr_sha256, "stderr_sha256"))
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be boolean")
        if self.returncode is not None and (
            isinstance(self.returncode, bool) or not isinstance(self.returncode, int)
        ):
            raise ValueError("returncode must be an integer or null")

        state = self.launch_state
        error_code = self.error_code
        if not state:
            if self.timed_out:
                state = "timed-out"
            elif self.returncode == 125:
                state = "refused-before-start"
                error_code = error_code or "docker-cli-refused"
            else:
                state = "completed"
            object.__setattr__(self, "launch_state", state)
            object.__setattr__(self, "error_code", error_code)
        if state not in _LAUNCH_STATES:
            raise ValueError(f"launch_state must be one of {sorted(_LAUNCH_STATES)}")
        if state == "timed-out":
            if not self.timed_out or self.returncode is not None:
                raise ValueError("timed-out receipt must have timed_out=true and null returncode")
            if error_code not in {None, "timeout"}:
                raise ValueError("timed-out receipt has an invalid error_code")
        elif state == "refused-before-start":
            if self.timed_out or self.returncode not in {None, 125}:
                raise ValueError("refused receipt must not represent an attempt result")
            if not isinstance(error_code, str) or not error_code:
                raise ValueError("refused receipt requires an error_code")
        else:
            if self.timed_out or self.returncode is None:
                raise ValueError("completed receipt requires a terminal returncode")
            if self.returncode == 125:
                raise ValueError("Docker returncode 125 cannot be a completed attempt")
            if error_code is not None:
                raise ValueError("completed receipt must not carry an error_code")

    @property
    def refused_before_start(self) -> bool:
        return self.launch_state == "refused-before-start"

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv_sha256": self.argv_sha256,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "launch_state": self.launch_state,
            "error_code": self.error_code,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _receipt(
    argv: tuple[str, ...],
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: bytes | None,
    stderr: bytes | None,
    launch_state: str,
    error_code: str | None,
) -> SandboxExecutionReceipt:
    return SandboxExecutionReceipt(
        argv_sha256=canonical_sha(list(argv)),
        returncode=returncode,
        timed_out=timed_out,
        stdout_sha256=_hash(stdout),
        stderr_sha256=_hash(stderr),
        launch_state=launch_state,
        error_code=error_code,
    )


#: Substrings the Docker CLI prints when it cannot reach an engine at all.
#: Matched case-insensitively against stderr, and only when the exit code is
#: non-zero, so a container whose own output happens to contain one of these
#: phrases still classifies as a completed attempt.
_ENGINE_UNREACHABLE_MARKERS = (
    "cannot connect to the docker daemon",
    "error during connect",
    "the system cannot find the file specified",
    "docker daemon is not running",
    "open //./pipe/docker_engine",
    "dial unix /var/run/docker.sock",
    "is the docker daemon running",
)


def _engine_unreachable(stderr: bytes | None) -> bool:
    """Did the CLI fail because no engine answered, rather than the command?"""
    if not stderr:
        return False
    text = stderr.decode("utf-8", "replace").lower()
    return any(marker in text for marker in _ENGINE_UNREACHABLE_MARKERS)


def run_in_docker_sandbox(
    policy: DockerSandboxPolicy,
    command: Iterable[str],
) -> SandboxExecutionReceipt:
    """Run one Docker command or return an explicit pre-start refusal.

    Docker exit code 125 belongs to the Docker CLI rather than the attempted
    command and is therefore classified as refusal before attempt execution.
    Exit codes from a started container remain ordinary completed receipts.
    """

    argv = policy.argv(command)
    try:
        proc = subprocess.run(
            argv,
            text=False,
            capture_output=True,
            timeout=policy.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _receipt(
            argv,
            returncode=None,
            timed_out=True,
            stdout=exc.stdout,
            stderr=exc.stderr,
            launch_state="timed-out",
            error_code="timeout",
        )
    except FileNotFoundError:
        return _receipt(
            argv,
            returncode=None,
            timed_out=False,
            stdout=None,
            stderr=None,
            launch_state="refused-before-start",
            error_code="runtime-not-found",
        )
    except PermissionError:
        return _receipt(
            argv,
            returncode=None,
            timed_out=False,
            stdout=None,
            stderr=None,
            launch_state="refused-before-start",
            error_code="runtime-not-executable",
        )
    except OSError:
        return _receipt(
            argv,
            returncode=None,
            timed_out=False,
            stdout=None,
            stderr=None,
            launch_state="refused-before-start",
            error_code="runtime-launch-error",
        )
    if proc.returncode == 125:
        return _receipt(
            argv,
            returncode=125,
            timed_out=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
            launch_state="refused-before-start",
            error_code="docker-cli-refused",
        )
    if proc.returncode != 0 and _engine_unreachable(proc.stderr):
        # Phase-0 case A9c1, MEASURED: with the Docker engine pipe absent, the
        # CLI exits 1 -- not 125 -- and this function classified that as a
        # COMPLETED attempt with returncode 1. An attempt that never started is
        # not an attempt that failed: the difference decides whether a fault
        # receipt is evidence about the candidate or evidence about the host,
        # and treating "no engine" as a completed run lets an unreachable
        # sandbox read as a real isolated execution.
        #
        # ``returncode=None`` is required, not cosmetic: the receipt schema
        # already says a refused receipt "must not represent an attempt
        # result", and the CLI's exit 1 is the CLI's, not the container's.
        return _receipt(
            argv,
            returncode=None,
            timed_out=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
            launch_state="refused-before-start",
            error_code="runtime-engine-unreachable",
        )
    return _receipt(
        argv,
        returncode=proc.returncode,
        timed_out=False,
        stdout=proc.stdout,
        stderr=proc.stderr,
        launch_state="completed",
        error_code=None,
    )


__all__ = [
    "DockerSandboxPolicy",
    "SandboxExecutionReceipt",
    "SandboxMount",
    "SandboxPolicyError",
    "run_in_docker_sandbox",
]
