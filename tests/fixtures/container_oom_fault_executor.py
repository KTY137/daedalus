#!/usr/bin/env python3
"""Execute the canonical container-memory-exhaustion Linux host fault.

The fixture calls the production Docker sandbox boundary with a pinned image
and an exact cgroup memory limit. It emits untrusted host evidence only;
external RuntimeFaultAttestation is still required before the observation may
enter the trusted Gate-0 fault digest set.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

import daedalus.kernel.sandbox as sandbox_module
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

_REPORT_SCHEMA = "daedalus-container-oom-fault-report/1"
_SCENARIO_ID = "runtime.process.oom"
_IMAGE_SHA256 = "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
_IMAGE = "python:3.12-alpine@sha256:" + _IMAGE_SHA256
_MEMORY = "64m"
_TIMEOUT_S = 30
_OOM_RETURNCODE = 137


class ContainerOomFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sandbox_source_path() -> Path:
    source = getattr(sandbox_module, "__file__", None)
    if not source:
        raise ContainerOomFaultError(
            "production sandbox module has no source-file identity"
        )
    path = Path(source).resolve()
    if not path.is_file():
        raise ContainerOomFaultError(
            "production sandbox source file is unavailable"
        )
    return path


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "sandbox_sha256": _file_sha256(_sandbox_source_path()),
            "image": _IMAGE,
            "memory": _MEMORY,
            "timeout_s": _TIMEOUT_S,
        }
    )


def _canonical_scenario():
    return RUNTIME_FAULT_CATALOG.scenario_map[_SCENARIO_ID]


def _assert_scenario(scenario) -> None:
    canonical = _canonical_scenario()
    comparisons = {
        "scenario_id": (scenario.scenario_id, canonical.scenario_id),
        "scenario_sha256": (scenario.digest, canonical.digest),
        "authority": (scenario.authority, canonical.authority),
        "executor": (scenario.executor, canonical.executor),
        "expected_outcome": (
            scenario.expected_outcome,
            canonical.expected_outcome,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise ContainerOomFaultError(
            "container OOM scenario binding mismatch: " + ", ".join(mismatches)
        )


def _docker_cli() -> tuple[Path | None, str | None]:
    docker_name = shutil.which("docker")
    if docker_name is None:
        return None, "docker-cli-unavailable"
    docker_cli = Path(docker_name).resolve()
    if not docker_cli.is_file() or not os.access(docker_cli, os.X_OK):
        return None, "docker-cli-unreadable"
    try:
        _file_sha256(docker_cli)
    except OSError:
        return None, "docker-cli-unreadable"
    return docker_cli, None


def _base_payload(
    *,
    scenario,
    docker_cli_sha256: str | None,
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "schema": _REPORT_SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.digest,
        "executor_implementation_sha256": implementation_sha256(),
        "sandbox_source_sha256": _file_sha256(_sandbox_source_path()),
        "docker_cli_sha256": docker_cli_sha256,
        "image": _IMAGE,
        "image_sha256": _IMAGE_SHA256,
        "memory": _MEMORY,
        "timeout_s": _TIMEOUT_S,
        "elapsed_ms": elapsed_ms,
        "platform": sys.platform,
    }


def _blocked_result(
    scenario,
    *,
    detail_code: str,
    docker_cli_sha256: str | None = None,
    receipt=None,
    marker_exists: bool = False,
) -> HostFaultResult:
    payload = {
        **_base_payload(
            scenario=scenario,
            docker_cli_sha256=docker_cli_sha256,
            elapsed_ms=0,
        ),
        "status": "blocked",
        "detail_code": detail_code,
        "receipt": None if receipt is None else {
            **receipt.to_dict(),
            "receipt_sha256": receipt.digest,
        },
        "started_marker_exists": marker_exists,
        "host_fallback_observed": False,
    }
    return HostFaultResult(
        status="blocked",
        observed_outcome=None,
        detail_code=detail_code,
        raw_evidence=canonical_json(payload).encode("utf-8"),
        facts=(
            HostFaultFact("platform", sys.platform),
            HostFaultFact("prerequisite", detail_code),
        ),
    )


def _allocation_command() -> tuple[str, ...]:
    # The program has no voluntary exit, signal, shell, network, or child-process
    # path. After publishing the start marker it repeatedly touches fresh memory.
    # Under the exact Docker cgroup limit, terminal code 137 is therefore the
    # expected host observation rather than a candidate-authored success signal.
    script = (
        "from pathlib import Path\n"
        "Path('/workspace/oom-started').write_text('started', encoding='utf-8')\n"
        "blocks = []\n"
        "while True:\n"
        "    block = bytearray(16 * 1024 * 1024)\n"
        "    block[:] = b'x' * len(block)\n"
        "    blocks.append(block)\n"
    )
    return ("python", "-c", script)


def _execute_container_oom(scenario) -> HostFaultResult:
    _assert_scenario(scenario)
    if sys.platform != "linux":
        return _blocked_result(scenario, detail_code="linux-required")

    docker_cli, prerequisite = _docker_cli()
    if prerequisite is not None or docker_cli is None:
        return _blocked_result(scenario, detail_code=prerequisite or "docker-cli-unavailable")
    docker_cli_sha256 = _file_sha256(docker_cli)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="daedalus-container-oom-") as temporary:
        workspace = Path(temporary) / "candidate"
        workspace.mkdir(mode=0o777)
        workspace.chmod(0o777)
        marker = workspace / "oom-started"
        policy = DockerSandboxPolicy(
            image=_IMAGE,
            candidate_workspace=workspace,
            network="none",
            memory=_MEMORY,
            cpus="1",
            pids_limit=32,
            timeout_s=_TIMEOUT_S,
            tmpfs_size="16m",
        )
        receipt = run_in_docker_sandbox(policy, _allocation_command())
        elapsed_ms = int((time.monotonic() - started) * 1000)
        marker_exists = marker.is_file()

        if receipt.refused_before_start:
            return _blocked_result(
                scenario,
                detail_code="sandbox-unavailable",
                docker_cli_sha256=docker_cli_sha256,
                receipt=receipt,
                marker_exists=marker_exists,
            )

        payload = {
            **_base_payload(
                scenario=scenario,
                docker_cli_sha256=docker_cli_sha256,
                elapsed_ms=elapsed_ms,
            ),
            "status": "observed",
            "detail_code": None,
            "receipt": {
                **receipt.to_dict(),
                "receipt_sha256": receipt.digest,
            },
            "started_marker_exists": marker_exists,
            "host_fallback_observed": False,
        }
        exact_oom = (
            receipt.launch_state == "completed"
            and receipt.returncode == _OOM_RETURNCODE
            and receipt.timed_out is False
            and receipt.error_code is None
            and marker_exists
            and 0 < elapsed_ms < (_TIMEOUT_S + 15) * 1000
        )
        if exact_oom:
            return HostFaultResult(
                status="passed",
                observed_outcome="failed",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("docker-cli-sha256", docker_cli_sha256),
                    HostFaultFact("image-sha256", _IMAGE_SHA256),
                    HostFaultFact("launch-state", "completed"),
                    HostFaultFact("memory-limit", _MEMORY),
                    HostFaultFact("returncode", str(_OOM_RETURNCODE)),
                    HostFaultFact("started-marker", "true"),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="container-oom-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("launch-state", receipt.launch_state),
                HostFaultFact(
                    "returncode",
                    "none" if receipt.returncode is None else str(receipt.returncode),
                ),
                HostFaultFact("started-marker", str(marker_exists).lower()),
                HostFaultFact("timed-out", str(receipt.timed_out).lower()),
            ),
        )


def container_oom_binding() -> LinuxHostExecutorBinding:
    scenario = _canonical_scenario()
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_container_oom,
    )


def run_container_oom(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _canonical_scenario(),
        source_revision=source_revision,
        executor=container_oom_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ContainerOomFaultError("refusing to replace an output symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def publish_container_oom(
    *,
    source_revision: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise ContainerOomFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_container_oom(source_revision=source_revision)
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
        "detail_code": run.observation.detail_code,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = publish_container_oom(
        source_revision=args.source_revision,
        output_dir=args.output_dir,
    )
    print(canonical_json(summary))
    if summary["status"] == "passed":
        return 0
    if summary["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
