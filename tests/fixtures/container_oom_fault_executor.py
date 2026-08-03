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
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

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

_REPORT_SCHEMA = "daedalus-container-oom-fault-report/2"
_MARKER_SCHEMA = "daedalus-cgroup-oom-observation/1"
_SCENARIO_ID = "runtime.process.oom"
_IMAGE_SHA256 = "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
_IMAGE = "python:3.12-alpine@sha256:" + _IMAGE_SHA256
_MEMORY = "64m"
_TIMEOUT_S = 30
_OOM_OBSERVED_RETURNCODE = 70
_MAX_MARKER_BYTES = 4096


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
            "marker_schema": _MARKER_SCHEMA,
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
    elapsed_ms: int = 0,
    started_marker_exists: bool = False,
) -> HostFaultResult:
    payload = {
        **_base_payload(
            scenario=scenario,
            docker_cli_sha256=docker_cli_sha256,
            elapsed_ms=elapsed_ms,
        ),
        "status": "blocked",
        "detail_code": detail_code,
        "receipt": None if receipt is None else {
            **receipt.to_dict(),
            "receipt_sha256": receipt.digest,
        },
        "started_marker_exists": started_marker_exists,
        "oom_marker_status": "not-read",
        "oom_marker_sha256": None,
        "oom_marker": None,
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
    # One small parent observes the kernel-owned cgroup v2 memory.events file.
    # Its child only allocates and touches memory. The successful fault path is
    # therefore not inferred from exit code 137: it requires a strict marker
    # showing that oom_kill increased and that the allocating child died by
    # SIGKILL. The parent exits 70 only after retaining those kernel facts.
    script = (
        "import json, os, time\n"
        "from pathlib import Path\n"
        "events_path = Path('/sys/fs/cgroup/memory.events')\n"
        "start_marker = Path('/workspace/oom-started')\n"
        "result_marker = Path('/workspace/oom-observed.json')\n"
        "def read_events():\n"
        "    rows = {}\n"
        "    for line in events_path.read_text(encoding='utf-8').splitlines():\n"
        "        key, value = line.split()\n"
        "        rows[key] = int(value)\n"
        "    return rows\n"
        "before = read_events()\n"
        "start_marker.write_text('started', encoding='utf-8')\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    blocks = []\n"
        "    while True:\n"
        "        block = bytearray(8 * 1024 * 1024)\n"
        "        block[:] = b'x' * len(block)\n"
        "        blocks.append(block)\n"
        "deadline = time.monotonic() + 20\n"
        "observed = False\n"
        "child_exitcode = None\n"
        "after = before\n"
        "while time.monotonic() < deadline:\n"
        "    after = read_events()\n"
        "    if after.get('oom_kill', 0) > before.get('oom_kill', 0):\n"
        "        _, status = os.waitpid(pid, 0)\n"
        "        child_exitcode = os.waitstatus_to_exitcode(status)\n"
        "        observed = True\n"
        "        break\n"
        "    done, status = os.waitpid(pid, os.WNOHANG)\n"
        "    if done:\n"
        "        child_exitcode = os.waitstatus_to_exitcode(status)\n"
        "        after = read_events()\n"
        "        observed = after.get('oom_kill', 0) > before.get('oom_kill', 0)\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "after = read_events()\n"
        "payload = {\n"
        "    'schema': 'daedalus-cgroup-oom-observation/1',\n"
        "    'observed': observed,\n"
        "    'before_oom': before.get('oom', 0),\n"
        "    'after_oom': after.get('oom', 0),\n"
        "    'before_oom_kill': before.get('oom_kill', 0),\n"
        "    'after_oom_kill': after.get('oom_kill', 0),\n"
        "    'child_exitcode': child_exitcode,\n"
        "}\n"
        "result_marker.write_text(\n"
        "    json.dumps(payload, sort_keys=True, separators=(',', ':')),\n"
        "    encoding='utf-8',\n"
        ")\n"
        "raise SystemExit(70 if observed else 71)\n"
    )
    return ("python", "-c", script)


def _strict_object(pairs):
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate marker key")
        result[key] = value
    return result


def _read_oom_marker(path: Path) -> tuple[Mapping[str, Any] | None, str, str | None]:
    if not path.is_file():
        return None, "missing", None
    try:
        payload_bytes = path.read_bytes()
    except OSError:
        return None, "unreadable", None
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if not payload_bytes or len(payload_bytes) > _MAX_MARKER_BYTES:
        return None, "invalid", digest
    try:
        payload = json.loads(
            payload_bytes.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("non-finite marker value")
            ),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None, "invalid", digest
    expected = {
        "schema",
        "observed",
        "before_oom",
        "after_oom",
        "before_oom_kill",
        "after_oom_kill",
        "child_exitcode",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None, "invalid", digest
    if payload["schema"] != _MARKER_SCHEMA or not isinstance(payload["observed"], bool):
        return None, "invalid", digest
    for name in (
        "before_oom",
        "after_oom",
        "before_oom_kill",
        "after_oom_kill",
    ):
        value = payload[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, "invalid", digest
    child_exitcode = payload["child_exitcode"]
    if child_exitcode is not None and (
        isinstance(child_exitcode, bool) or not isinstance(child_exitcode, int)
    ):
        return None, "invalid", digest
    return payload, "valid", digest


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
        start_marker = workspace / "oom-started"
        result_marker = workspace / "oom-observed.json"
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
        started_marker_exists = start_marker.is_file()

        if receipt.refused_before_start:
            return _blocked_result(
                scenario,
                detail_code="sandbox-unavailable",
                docker_cli_sha256=docker_cli_sha256,
                receipt=receipt,
                elapsed_ms=elapsed_ms,
                started_marker_exists=started_marker_exists,
            )

        marker, marker_status, marker_sha256 = _read_oom_marker(result_marker)
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
            "started_marker_exists": started_marker_exists,
            "oom_marker_status": marker_status,
            "oom_marker_sha256": marker_sha256,
            "oom_marker": marker,
            "host_fallback_observed": False,
        }
        exact_oom = (
            receipt.launch_state == "completed"
            and receipt.returncode == _OOM_OBSERVED_RETURNCODE
            and receipt.timed_out is False
            and receipt.error_code is None
            and started_marker_exists
            and marker_status == "valid"
            and marker is not None
            and marker["observed"] is True
            and marker["after_oom"] > marker["before_oom"]
            and marker["after_oom_kill"] > marker["before_oom_kill"]
            and marker["child_exitcode"] == -9
            and 0 < elapsed_ms < (_TIMEOUT_S + 15) * 1000
        )
        if exact_oom:
            return HostFaultResult(
                status="passed",
                observed_outcome="failed",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("child-exitcode", "-9"),
                    HostFaultFact("docker-cli-sha256", docker_cli_sha256),
                    HostFaultFact("image-sha256", _IMAGE_SHA256),
                    HostFaultFact("launch-state", "completed"),
                    HostFaultFact("memory-limit", _MEMORY),
                    HostFaultFact("oom-kill-increased", "true"),
                    HostFaultFact("returncode", str(_OOM_OBSERVED_RETURNCODE)),
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
                HostFaultFact("marker-status", marker_status),
                HostFaultFact(
                    "returncode",
                    "none" if receipt.returncode is None else str(receipt.returncode),
                ),
                HostFaultFact("started-marker", str(started_marker_exists).lower()),
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
