"""A small, explicit Docker sandbox boundary for Gate 0 attempts.

The policy is converted to argv without invoking a shell. It rejects privileged
or host-coupled configurations, makes the root filesystem read-only, grants one
bounded candidate workspace as the only writable bind mount, and keeps network
access off unless an explicit internal proxy network is selected.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from daedalus.spine.envelope import canonical_sha


class SandboxPolicyError(ValueError):
    pass


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
            "--mount", f"type=bind,src={self.candidate_workspace},dst=/workspace,rw",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,size={self.tmpfs_size}",
            "--workdir", "/workspace",
        ]
        for mount in sorted(self.reference_mounts, key=lambda item: item.target):
            mode = "ro" if mount.read_only else "rw"
            argv.extend(["--mount", f"type=bind,src={mount.source},dst={mount.target},{mode}"])
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

    @property
    def digest(self) -> str:
        return canonical_sha(
            {
                "argv_sha256": self.argv_sha256,
                "returncode": self.returncode,
                "timed_out": self.timed_out,
                "stdout_sha256": self.stdout_sha256,
                "stderr_sha256": self.stderr_sha256,
            }
        )


def run_in_docker_sandbox(
    policy: DockerSandboxPolicy,
    command: Iterable[str],
) -> SandboxExecutionReceipt:
    argv = policy.argv(command)
    try:
        proc = subprocess.run(
            argv,
            text=False,
            capture_output=True,
            timeout=policy.timeout_s,
            check=False,
        )
        return SandboxExecutionReceipt(
            argv_sha256=canonical_sha(list(argv)),
            returncode=proc.returncode,
            timed_out=False,
            stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(proc.stderr).hexdigest(),
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxExecutionReceipt(
            argv_sha256=canonical_sha(list(argv)),
            returncode=None,
            timed_out=True,
            stdout_sha256=hashlib.sha256(exc.stdout or b"").hexdigest(),
            stderr_sha256=hashlib.sha256(exc.stderr or b"").hexdigest(),
        )


__all__ = [
    "DockerSandboxPolicy",
    "SandboxExecutionReceipt",
    "SandboxMount",
    "SandboxPolicyError",
    "run_in_docker_sandbox",
]
