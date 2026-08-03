#!/usr/bin/env python3
"""Execute the canonical Docker-daemon-unavailable host fault.

The resulting observation remains untrusted until an external host issuer signs
its exact digest through ``RuntimeFaultAttestation``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from daedalus.kernel.sandbox import DockerSandboxPolicy, run_in_docker_sandbox
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_REPORT_SCHEMA = "daedalus-sandbox-unavailable-fault-report/1"
_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX_SOURCE = _ROOT / "daedalus" / "kernel" / "sandbox.py"
_IMAGE = "daedalus-fault-probe@sha256:" + "a" * 64
_DOCKER_ENV = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
)


class SandboxUnavailableFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__)),
            "sandbox_sha256": _file_sha256(_SANDBOX_SOURCE),
        }
    )


@contextmanager
def _unavailable_docker_environment(socket_path: Path) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in _DOCKER_ENV}
    try:
        os.environ["DOCKER_HOST"] = "unix://" + str(socket_path)
        for name in _DOCKER_ENV[1:]:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _execute_sandbox_unavailable(scenario) -> HostFaultResult:
    with tempfile.TemporaryDirectory(prefix="daedalus-sandbox-unavailable-") as temporary:
        root = Path(temporary)
        workspace = root / "candidate"
        workspace.mkdir()
        missing_socket = root / "missing-docker.sock"
        marker = workspace / "fallback-marker"
        policy = DockerSandboxPolicy(
            image=_IMAGE,
            candidate_workspace=workspace,
            network="none",
            timeout_s=10,
        )
        with _unavailable_docker_environment(missing_socket):
            receipt = run_in_docker_sandbox(
                policy,
                (
                    "python",
                    "-c",
                    "from pathlib import Path; Path('/workspace/fallback-marker').write_text('bad')",
                ),
            )
        marker_exists = marker.exists()
        payload = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "sandbox_source_sha256": _file_sha256(_SANDBOX_SOURCE),
            "receipt": {
                "argv_sha256": receipt.argv_sha256,
                "returncode": receipt.returncode,
                "timed_out": receipt.timed_out,
                "stdout_sha256": receipt.stdout_sha256,
                "stderr_sha256": receipt.stderr_sha256,
                "launch_state": receipt.launch_state,
                "error_code": receipt.error_code,
                "receipt_sha256": receipt.digest,
            },
            "workspace_marker_exists": marker_exists,
            "docker_host_class": "missing-unix-socket",
            "host_fallback_observed": marker_exists,
        }
        if receipt.refused_before_start and not marker_exists:
            return HostFaultResult(
                status="passed",
                observed_outcome="refused-before-start",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("docker-error-code", receipt.error_code or "none"),
                    HostFaultFact("host-fallback-observed", "false"),
                    HostFaultFact("launch-state", receipt.launch_state),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="sandbox-unavailable-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("host-fallback-observed", "true" if marker_exists else "false"),
                HostFaultFact("launch-state", receipt.launch_state),
            ),
        )


def sandbox_unavailable_binding() -> LinuxHostExecutorBinding:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.sandbox.daemon-unavailable"]
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_sandbox_unavailable,
    )


def run_sandbox_unavailable(*, source_revision: str) -> LinuxHostFaultRun:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.sandbox.daemon-unavailable"]
    return run_linux_host_fault(
        scenario,
        source_revision=source_revision,
        executor=sandbox_unavailable_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SandboxUnavailableFaultError("refusing to replace an output symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_sandbox_unavailable(*, source_revision: str, output_dir: Path) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise SandboxUnavailableFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_sandbox_unavailable(source_revision=source_revision)
    _atomic_write(
        output_dir / "evidence.json",
        (canonical_json(run.evidence.to_dict()) + "\n").encode("utf-8"),
    )
    _atomic_write(
        output_dir / "observation.json",
        (canonical_json(run.observation.to_dict()) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "raw", run.raw_evidence)
    summary = {
        "schema": _REPORT_SCHEMA,
        "source_revision": source_revision,
        "scenario_id": run.observation.scenario_id,
        "status": run.observation.status,
        "observed_outcome": run.observation.observed_outcome,
        "evidence_sha256": run.evidence.digest,
        "observation_sha256": run.observation.digest,
        "run_sha256": run.digest,
        "executor_implementation_sha256": implementation_sha256(),
        "trusted": False,
        "attested": False,
        "gate_closure_claimed": False,
    }
    _atomic_write(
        output_dir / "summary.json",
        (canonical_json(summary) + "\n").encode("utf-8"),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = publish_sandbox_unavailable(
        source_revision=args.source_revision,
        output_dir=args.output_dir,
    )
    print(canonical_json(summary))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
