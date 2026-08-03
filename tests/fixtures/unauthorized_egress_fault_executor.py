#!/usr/bin/env python3
"""Execute the canonical unauthorized-egress Linux host fault.

The fixture calls the production Docker sandbox with network mode ``none`` and
retains untrusted host evidence. An external RuntimeFaultAttestation remains
required before the observation can enter the trusted Gate-0 fault matrix.
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

_REPORT_SCHEMA = "daedalus-unauthorized-egress-fault-report/1"
_MARKER_SCHEMA = "daedalus-egress-denial-observation/1"
_SCENARIO_ID = "runtime.egress.unauthorized-endpoint"
_IMAGE_SHA256 = "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
_IMAGE = "python:3.12-alpine@sha256:" + _IMAGE_SHA256
_ENDPOINT_HOST = "198.51.100.1"
_ENDPOINT_PORT = 443
_NETWORK_MODE = "none"
_CONNECT_ERRNO = 101
_TIMEOUT_S = 20
_DENIED_RETURNCODE = 73
_INSPECTION_UNAVAILABLE_RETURNCODE = 75
_MAX_MARKER_BYTES = 4096


class UnauthorizedEgressFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sandbox_source_path() -> Path:
    source = getattr(sandbox_module, "__file__", None)
    if not source:
        raise UnauthorizedEgressFaultError(
            "production sandbox module has no source-file identity"
        )
    path = Path(source).resolve()
    if not path.is_file():
        raise UnauthorizedEgressFaultError(
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
            "network": _NETWORK_MODE,
            "endpoint_host": _ENDPOINT_HOST,
            "endpoint_port": _ENDPOINT_PORT,
            "connect_errno": _CONNECT_ERRNO,
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
        raise UnauthorizedEgressFaultError(
            "unauthorized-egress scenario binding mismatch: "
            + ", ".join(mismatches)
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
        "network": _NETWORK_MODE,
        "endpoint_host": _ENDPOINT_HOST,
        "endpoint_port": _ENDPOINT_PORT,
        "connect_errno": _CONNECT_ERRNO,
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
    marker: Mapping[str, Any] | None = None,
    marker_status: str = "not-read",
    marker_sha256: str | None = None,
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
        "egress_marker_status": marker_status,
        "egress_marker_sha256": marker_sha256,
        "egress_marker": marker,
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


def _network_probe_command() -> tuple[str, ...]:
    script = (
        "import json, socket\n"
        "from pathlib import Path\n"
        "interfaces_root = Path('/sys/class/net')\n"
        "routes_path = Path('/proc/net/route')\n"
        "start_marker = Path('/workspace/egress-started')\n"
        "result_marker = Path('/workspace/egress-observed.json')\n"
        "def write_result(payload):\n"
        "    result_marker.write_text(\n"
        "        json.dumps(payload, sort_keys=True, separators=(',', ':')),\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "def unsupported():\n"
        "    write_result({\n"
        "        'schema': 'daedalus-egress-denial-observation/1',\n"
        "        'supported': False,\n"
        "        'interfaces': [],\n"
        "        'default_route': False,\n"
        "        'endpoint_host': '198.51.100.1',\n"
        "        'endpoint_port': 443,\n"
        "        'connect_succeeded': False,\n"
        "        'errno': None,\n"
        "    })\n"
        "    raise SystemExit(75)\n"
        "if not interfaces_root.is_dir() or not routes_path.is_file():\n"
        "    unsupported()\n"
        "try:\n"
        "    interfaces = sorted(path.name for path in interfaces_root.iterdir())\n"
        "    rows = routes_path.read_text(encoding='utf-8').splitlines()[1:]\n"
        "    default_route = any(\n"
        "        len(fields) >= 8\n"
        "        and fields[1] == '00000000'\n"
        "        and fields[7] == '00000000'\n"
        "        and (int(fields[3], 16) & 1) != 0\n"
        "        for fields in (row.split() for row in rows)\n"
        "    )\n"
        "except (OSError, ValueError):\n"
        "    unsupported()\n"
        "start_marker.write_text('started', encoding='utf-8')\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "sock.settimeout(2.0)\n"
        "connected = False\n"
        "error_number = None\n"
        "try:\n"
        "    sock.connect(('198.51.100.1', 443))\n"
        "    connected = True\n"
        "except OSError as exc:\n"
        "    error_number = exc.errno\n"
        "finally:\n"
        "    sock.close()\n"
        "write_result({\n"
        "    'schema': 'daedalus-egress-denial-observation/1',\n"
        "    'supported': True,\n"
        "    'interfaces': interfaces,\n"
        "    'default_route': bool(default_route),\n"
        "    'endpoint_host': '198.51.100.1',\n"
        "    'endpoint_port': 443,\n"
        "    'connect_succeeded': connected,\n"
        "    'errno': error_number,\n"
        "})\n"
        "denied = (\n"
        "    interfaces == ['lo']\n"
        "    and not default_route\n"
        "    and not connected\n"
        "    and error_number == 101\n"
        ")\n"
        "raise SystemExit(73 if denied else 74)\n"
    )
    return ("python", "-c", script)


def _strict_object(pairs):
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate marker key")
        result[key] = value
    return result


def _read_marker(path: Path) -> tuple[Mapping[str, Any] | None, str, str | None]:
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
    except (UnicodeDecodeError, ValueError):
        return None, "invalid", digest
    expected = {
        "schema",
        "supported",
        "interfaces",
        "default_route",
        "endpoint_host",
        "endpoint_port",
        "connect_succeeded",
        "errno",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None, "invalid", digest
    if payload["schema"] != _MARKER_SCHEMA:
        return None, "invalid", digest
    if not isinstance(payload["supported"], bool):
        return None, "invalid", digest
    if not isinstance(payload["default_route"], bool):
        return None, "invalid", digest
    if not isinstance(payload["connect_succeeded"], bool):
        return None, "invalid", digest
    interfaces = payload["interfaces"]
    if (
        not isinstance(interfaces, list)
        or any(not isinstance(item, str) or not item for item in interfaces)
        or interfaces != sorted(set(interfaces))
        or len(interfaces) > 32
    ):
        return None, "invalid", digest
    if payload["endpoint_host"] != _ENDPOINT_HOST:
        return None, "invalid", digest
    if payload["endpoint_port"] != _ENDPOINT_PORT:
        return None, "invalid", digest
    error_number = payload["errno"]
    if error_number is not None and (
        isinstance(error_number, bool)
        or not isinstance(error_number, int)
        or error_number < 1
        or error_number > 4095
    ):
        return None, "invalid", digest
    return payload, "valid", digest


def _execute_unauthorized_egress(scenario) -> HostFaultResult:
    _assert_scenario(scenario)
    if sys.platform != "linux":
        return _blocked_result(scenario, detail_code="linux-required")

    docker_cli, prerequisite = _docker_cli()
    if prerequisite is not None or docker_cli is None:
        return _blocked_result(scenario, detail_code=prerequisite or "docker-cli-unavailable")
    docker_cli_sha256 = _file_sha256(docker_cli)

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="daedalus-egress-fault-") as temporary:
        workspace = Path(temporary) / "candidate"
        workspace.mkdir(mode=0o777)
        workspace.chmod(0o777)
        start_marker = workspace / "egress-started"
        result_marker = workspace / "egress-observed.json"
        policy = DockerSandboxPolicy(
            image=_IMAGE,
            candidate_workspace=workspace,
            network=_NETWORK_MODE,
            memory="128m",
            cpus="1",
            pids_limit=32,
            timeout_s=_TIMEOUT_S,
            tmpfs_size="16m",
        )
        receipt = run_in_docker_sandbox(policy, _network_probe_command())
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

        marker, marker_status, marker_sha256 = _read_marker(result_marker)
        if (
            receipt.launch_state == "completed"
            and receipt.returncode == _INSPECTION_UNAVAILABLE_RETURNCODE
            and receipt.timed_out is False
            and receipt.error_code is None
            and started_marker_exists is False
            and marker_status == "valid"
            and marker is not None
            and marker["supported"] is False
            and marker["interfaces"] == []
            and marker["default_route"] is False
            and marker["connect_succeeded"] is False
            and marker["errno"] is None
        ):
            return _blocked_result(
                scenario,
                detail_code="network-namespace-inspection-unavailable",
                docker_cli_sha256=docker_cli_sha256,
                receipt=receipt,
                elapsed_ms=elapsed_ms,
                marker=marker,
                marker_status=marker_status,
                marker_sha256=marker_sha256,
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
            "started_marker_exists": started_marker_exists,
            "egress_marker_status": marker_status,
            "egress_marker_sha256": marker_sha256,
            "egress_marker": marker,
            "host_fallback_observed": False,
        }
        exact_denial = (
            receipt.launch_state == "completed"
            and receipt.returncode == _DENIED_RETURNCODE
            and receipt.timed_out is False
            and receipt.error_code is None
            and started_marker_exists
            and marker_status == "valid"
            and marker is not None
            and marker["supported"] is True
            and marker["interfaces"] == ["lo"]
            and marker["default_route"] is False
            and marker["endpoint_host"] == _ENDPOINT_HOST
            and marker["endpoint_port"] == _ENDPOINT_PORT
            and marker["connect_succeeded"] is False
            and marker["errno"] == _CONNECT_ERRNO
            and 0 < elapsed_ms < (_TIMEOUT_S + 10) * 1000
        )
        if exact_denial:
            return HostFaultResult(
                status="passed",
                observed_outcome="failed",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("connect-errno", str(_CONNECT_ERRNO)),
                    HostFaultFact("default-route", "false"),
                    HostFaultFact("docker-cli-sha256", docker_cli_sha256),
                    HostFaultFact("endpoint", f"{_ENDPOINT_HOST}:{_ENDPOINT_PORT}"),
                    HostFaultFact("image-sha256", _IMAGE_SHA256),
                    HostFaultFact("interfaces", "lo"),
                    HostFaultFact("network", _NETWORK_MODE),
                    HostFaultFact("returncode", str(_DENIED_RETURNCODE)),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="unauthorized-egress-invariant",
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


def unauthorized_egress_binding() -> LinuxHostExecutorBinding:
    scenario = _canonical_scenario()
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_unauthorized_egress,
    )


def run_unauthorized_egress(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _canonical_scenario(),
        source_revision=source_revision,
        executor=unauthorized_egress_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UnauthorizedEgressFaultError("refusing to replace an output symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def publish_unauthorized_egress(
    *,
    source_revision: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise UnauthorizedEgressFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_unauthorized_egress(source_revision=source_revision)
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
    summary = publish_unauthorized_egress(
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
