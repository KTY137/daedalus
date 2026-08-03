#!/usr/bin/env python3
"""Execute the canonical undeclared-secret Linux host fault.

The executor places one random canary in the Docker CLI process environment and
calls the production Docker sandbox without any environment or secret mount
injection. The container probe retains names, booleans and digests only. The
canary value is never written to retained evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
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

_REPORT_SCHEMA = "daedalus-undeclared-secret-fault-report/1"
_MARKER_SCHEMA = "daedalus-secret-isolation-observation/1"
_SCENARIO_ID = "runtime.secrets.undeclared-access"
_IMAGE_SHA256 = "6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
_IMAGE = "python:3.12-alpine@sha256:" + _IMAGE_SHA256
_SECRET_NAME = "DAEDALUS_UNDECLARED_SECRET_PROBE"
_SECRET_ROOTS = ("/run/secrets", "/var/run/secrets", "/run/credentials")
_TIMEOUT_S = 20
_ISOLATED_RETURNCODE = 76
_LEAK_RETURNCODE = 77
_INSPECTION_UNAVAILABLE_RETURNCODE = 78
_MAX_MARKER_BYTES = 4096
_MAX_SECRET_ARTIFACTS = 1024
_ZERO_SHA256 = "0" * 64
_HOST_ENV_LOCK = threading.Lock()


class UndeclaredSecretFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sandbox_source_path() -> Path:
    source = getattr(sandbox_module, "__file__", None)
    if not source:
        raise UndeclaredSecretFaultError(
            "production sandbox module has no source-file identity"
        )
    path = Path(source).resolve()
    if not path.is_file():
        raise UndeclaredSecretFaultError(
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
            "secret_name": _SECRET_NAME,
            "secret_roots": list(_SECRET_ROOTS),
            "timeout_s": _TIMEOUT_S,
            "max_secret_artifacts": _MAX_SECRET_ARTIFACTS,
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
        raise UndeclaredSecretFaultError(
            "undeclared-secret scenario binding mismatch: " + ", ".join(mismatches)
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
    canary_sha256: str | None,
    host_environment_restored: bool,
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
        "secret_name": _SECRET_NAME,
        "secret_roots": list(_SECRET_ROOTS),
        "canary_sha256": canary_sha256,
        "timeout_s": _TIMEOUT_S,
        "elapsed_ms": elapsed_ms,
        "host_environment_restored": host_environment_restored,
        "platform": sys.platform,
    }


def _blocked_result(
    scenario,
    *,
    detail_code: str,
    docker_cli_sha256: str | None = None,
    receipt=None,
    elapsed_ms: int = 0,
    canary_sha256: str | None = None,
    host_environment_restored: bool = True,
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
            canary_sha256=canary_sha256,
            host_environment_restored=host_environment_restored,
        ),
        "status": "blocked",
        "detail_code": detail_code,
        "receipt": None if receipt is None else {
            **receipt.to_dict(),
            "receipt_sha256": receipt.digest,
        },
        "started_marker_exists": started_marker_exists,
        "secret_marker_status": marker_status,
        "secret_marker_sha256": marker_sha256,
        "secret_marker": marker,
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


def _secret_probe_command() -> tuple[str, ...]:
    roots_literal = repr(_SECRET_ROOTS)
    script = (
        "import hashlib, json, os\n"
        "from pathlib import Path\n"
        f"secret_name = {_SECRET_NAME!r}\n"
        f"secret_roots = {roots_literal}\n"
        "mountinfo_path = Path('/proc/self/mountinfo')\n"
        "start_marker = Path('/workspace/secret-started')\n"
        "result_marker = Path('/workspace/secret-observed.json')\n"
        "def write_result(payload):\n"
        "    result_marker.write_text(\n"
        "        json.dumps(payload, sort_keys=True, separators=(',', ':')),\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "def unsupported():\n"
        "    write_result({\n"
        "        'schema': 'daedalus-secret-isolation-observation/1',\n"
        "        'supported': False,\n"
        "        'secret_name': secret_name,\n"
        "        'secret_name_present': False,\n"
        "        'secret_value_read': False,\n"
        "        'environment_names_sha256': '0' * 64,\n"
        "        'mountinfo_sha256': '0' * 64,\n"
        "        'secret_mount_detected': False,\n"
        "        'secret_artifact_count': 0,\n"
        "        'artifact_scan_bounded': True,\n"
        "    })\n"
        "    raise SystemExit(78)\n"
        "if not mountinfo_path.is_file():\n"
        "    unsupported()\n"
        "try:\n"
        "    mountinfo_bytes = mountinfo_path.read_bytes()\n"
        "    mount_lines = mountinfo_bytes.decode('utf-8').splitlines()\n"
        "    mountpoints = []\n"
        "    for line in mount_lines:\n"
        "        fields = line.split()\n"
        "        if len(fields) < 6:\n"
        "            raise ValueError('malformed mountinfo')\n"
        "        mountpoints.append(fields[4])\n"
        "except (OSError, UnicodeDecodeError, ValueError):\n"
        "    unsupported()\n"
        "start_marker.write_text('started', encoding='utf-8')\n"
        "environment_names = sorted(os.environ.keys())\n"
        "environment_names_sha256 = hashlib.sha256(\n"
        "    '\\0'.join(environment_names).encode('utf-8')\n"
        ").hexdigest()\n"
        "secret_name_present = secret_name in os.environ\n"
        "secret_value_read = False\n"
        "try:\n"
        "    os.environ[secret_name]\n"
        "    secret_value_read = True\n"
        "except KeyError:\n"
        "    pass\n"
        "secret_mount_detected = any(\n"
        "    point == root or point.startswith(root + '/')\n"
        "    for point in mountpoints\n"
        "    for root in secret_roots\n"
        ")\n"
        "artifact_count = 0\n"
        "artifact_scan_bounded = True\n"
        "for root_name in secret_roots:\n"
        "    root = Path(root_name)\n"
        "    if not root.exists():\n"
        "        continue\n"
        "    try:\n"
        "        for path in root.rglob('*'):\n"
        "            if path.is_file() or path.is_symlink():\n"
        "                artifact_count += 1\n"
        "                if artifact_count > 1024:\n"
        "                    artifact_scan_bounded = False\n"
        "                    break\n"
        "    except OSError:\n"
        "        artifact_scan_bounded = False\n"
        "    if not artifact_scan_bounded:\n"
        "        break\n"
        "write_result({\n"
        "    'schema': 'daedalus-secret-isolation-observation/1',\n"
        "    'supported': True,\n"
        "    'secret_name': secret_name,\n"
        "    'secret_name_present': secret_name_present,\n"
        "    'secret_value_read': secret_value_read,\n"
        "    'environment_names_sha256': environment_names_sha256,\n"
        "    'mountinfo_sha256': hashlib.sha256(mountinfo_bytes).hexdigest(),\n"
        "    'secret_mount_detected': secret_mount_detected,\n"
        "    'secret_artifact_count': artifact_count,\n"
        "    'artifact_scan_bounded': artifact_scan_bounded,\n"
        "})\n"
        "isolated = (\n"
        "    not secret_name_present\n"
        "    and not secret_value_read\n"
        "    and not secret_mount_detected\n"
        "    and artifact_count == 0\n"
        "    and artifact_scan_bounded\n"
        ")\n"
        "raise SystemExit(76 if isolated else 77)\n"
    )
    return ("python", "-c", script)


def _strict_object(pairs):
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate marker key")
        result[key] = value
    return result


def _read_marker(
    path: Path,
    *,
    forbidden_canary: bytes,
) -> tuple[Mapping[str, Any] | None, str, str | None]:
    if not path.is_file():
        return None, "missing", None
    try:
        payload_bytes = path.read_bytes()
    except OSError:
        return None, "unreadable", None
    digest = hashlib.sha256(payload_bytes).hexdigest()
    if (
        not payload_bytes
        or len(payload_bytes) > _MAX_MARKER_BYTES
        or forbidden_canary in payload_bytes
    ):
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
        "secret_name",
        "secret_name_present",
        "secret_value_read",
        "environment_names_sha256",
        "mountinfo_sha256",
        "secret_mount_detected",
        "secret_artifact_count",
        "artifact_scan_bounded",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None, "invalid", digest
    if payload["schema"] != _MARKER_SCHEMA or payload["secret_name"] != _SECRET_NAME:
        return None, "invalid", digest
    for name in (
        "supported",
        "secret_name_present",
        "secret_value_read",
        "secret_mount_detected",
        "artifact_scan_bounded",
    ):
        if not isinstance(payload[name], bool):
            return None, "invalid", digest
    for name in ("environment_names_sha256", "mountinfo_sha256"):
        value = payload[name]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            return None, "invalid", digest
    count = payload["secret_artifact_count"]
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        or count > _MAX_SECRET_ARTIFACTS + 1
    ):
        return None, "invalid", digest
    return payload, "valid", digest


def _execute_undeclared_secret(scenario) -> HostFaultResult:
    _assert_scenario(scenario)
    if sys.platform != "linux":
        return _blocked_result(scenario, detail_code="linux-required")

    docker_cli, prerequisite = _docker_cli()
    if prerequisite is not None or docker_cli is None:
        return _blocked_result(scenario, detail_code=prerequisite or "docker-cli-unavailable")
    docker_cli_sha256 = _file_sha256(docker_cli)

    with _HOST_ENV_LOCK:
        if _SECRET_NAME in os.environ:
            return _blocked_result(
                scenario,
                detail_code="host-secret-probe-name-collision",
                docker_cli_sha256=docker_cli_sha256,
            )
        canary = secrets.token_hex(32)
        canary_bytes = canary.encode("ascii")
        canary_sha256 = hashlib.sha256(canary_bytes).hexdigest()
        started = time.monotonic()
        receipt = None
        host_environment_restored = False
        with tempfile.TemporaryDirectory(prefix="daedalus-secret-fault-") as temporary:
            workspace = Path(temporary) / "candidate"
            workspace.mkdir(mode=0o777)
            workspace.chmod(0o777)
            start_marker = workspace / "secret-started"
            result_marker = workspace / "secret-observed.json"
            policy = DockerSandboxPolicy(
                image=_IMAGE,
                candidate_workspace=workspace,
                reference_mounts=(),
                network="none",
                memory="128m",
                cpus="1",
                pids_limit=32,
                timeout_s=_TIMEOUT_S,
                tmpfs_size="16m",
            )
            os.environ[_SECRET_NAME] = canary
            try:
                receipt = run_in_docker_sandbox(policy, _secret_probe_command())
            finally:
                retained = os.environ.get(_SECRET_NAME)
                if retained == canary:
                    del os.environ[_SECRET_NAME]
                    host_environment_restored = True
                else:
                    host_environment_restored = False
            elapsed_ms = int((time.monotonic() - started) * 1000)
            started_marker_exists = start_marker.is_file()

            if not host_environment_restored:
                payload = {
                    **_base_payload(
                        scenario=scenario,
                        docker_cli_sha256=docker_cli_sha256,
                        elapsed_ms=elapsed_ms,
                        canary_sha256=canary_sha256,
                        host_environment_restored=False,
                    ),
                    "status": "failed",
                    "detail_code": "host-secret-probe-mutated",
                    "receipt": None if receipt is None else {
                        **receipt.to_dict(),
                        "receipt_sha256": receipt.digest,
                    },
                    "started_marker_exists": started_marker_exists,
                    "secret_marker_status": "not-read",
                    "secret_marker_sha256": None,
                    "secret_marker": None,
                    "host_fallback_observed": False,
                }
                return HostFaultResult(
                    status="failed",
                    observed_outcome="failed",
                    detail_code="host-secret-probe-mutated",
                    raw_evidence=canonical_json(payload).encode("utf-8"),
                    facts=(HostFaultFact("host-environment-restored", "false"),),
                )

            if receipt is None:
                raise UndeclaredSecretFaultError("sandbox returned no execution receipt")
            if receipt.refused_before_start:
                return _blocked_result(
                    scenario,
                    detail_code="sandbox-unavailable",
                    docker_cli_sha256=docker_cli_sha256,
                    receipt=receipt,
                    elapsed_ms=elapsed_ms,
                    canary_sha256=canary_sha256,
                    host_environment_restored=True,
                    started_marker_exists=started_marker_exists,
                )

            marker, marker_status, marker_sha256 = _read_marker(
                result_marker,
                forbidden_canary=canary_bytes,
            )
            if (
                receipt.launch_state == "completed"
                and receipt.returncode == _INSPECTION_UNAVAILABLE_RETURNCODE
                and receipt.timed_out is False
                and receipt.error_code is None
                and started_marker_exists is False
                and marker_status == "valid"
                and marker is not None
                and marker["supported"] is False
                and marker["secret_name_present"] is False
                and marker["secret_value_read"] is False
                and marker["environment_names_sha256"] == _ZERO_SHA256
                and marker["mountinfo_sha256"] == _ZERO_SHA256
                and marker["secret_mount_detected"] is False
                and marker["secret_artifact_count"] == 0
                and marker["artifact_scan_bounded"] is True
            ):
                return _blocked_result(
                    scenario,
                    detail_code="secret-namespace-inspection-unavailable",
                    docker_cli_sha256=docker_cli_sha256,
                    receipt=receipt,
                    elapsed_ms=elapsed_ms,
                    canary_sha256=canary_sha256,
                    host_environment_restored=True,
                    marker=marker,
                    marker_status=marker_status,
                    marker_sha256=marker_sha256,
                )

            payload = {
                **_base_payload(
                    scenario=scenario,
                    docker_cli_sha256=docker_cli_sha256,
                    elapsed_ms=elapsed_ms,
                    canary_sha256=canary_sha256,
                    host_environment_restored=True,
                ),
                "status": "observed",
                "detail_code": None,
                "receipt": {
                    **receipt.to_dict(),
                    "receipt_sha256": receipt.digest,
                },
                "started_marker_exists": started_marker_exists,
                "secret_marker_status": marker_status,
                "secret_marker_sha256": marker_sha256,
                "secret_marker": marker,
                "host_fallback_observed": False,
            }
            exact_isolation = (
                receipt.launch_state == "completed"
                and receipt.returncode == _ISOLATED_RETURNCODE
                and receipt.timed_out is False
                and receipt.error_code is None
                and started_marker_exists
                and marker_status == "valid"
                and marker is not None
                and marker["supported"] is True
                and marker["secret_name_present"] is False
                and marker["secret_value_read"] is False
                and marker["environment_names_sha256"] != _ZERO_SHA256
                and marker["mountinfo_sha256"] != _ZERO_SHA256
                and marker["secret_mount_detected"] is False
                and marker["secret_artifact_count"] == 0
                and marker["artifact_scan_bounded"] is True
                and canary_bytes not in canonical_json(payload).encode("utf-8")
                and 0 < elapsed_ms < (_TIMEOUT_S + 10) * 1000
            )
            if exact_isolation:
                return HostFaultResult(
                    status="passed",
                    observed_outcome="failed",
                    detail_code=None,
                    raw_evidence=canonical_json(payload).encode("utf-8"),
                    facts=(
                        HostFaultFact("docker-cli-sha256", docker_cli_sha256),
                        HostFaultFact("host-environment-restored", "true"),
                        HostFaultFact("image-sha256", _IMAGE_SHA256),
                        HostFaultFact("secret-artifact-count", "0"),
                        HostFaultFact("secret-mount-detected", "false"),
                        HostFaultFact("secret-name-present", "false"),
                        HostFaultFact("secret-value-retained", "false"),
                    ),
                )
            return HostFaultResult(
                status="failed",
                observed_outcome="failed",
                detail_code="secret-isolation-invariant",
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


def undeclared_secret_binding() -> LinuxHostExecutorBinding:
    scenario = _canonical_scenario()
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_undeclared_secret,
    )


def run_undeclared_secret(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _canonical_scenario(),
        source_revision=source_revision,
        executor=undeclared_secret_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UndeclaredSecretFaultError("refusing to replace an output symlink")
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


def publish_undeclared_secret(
    *,
    source_revision: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise UndeclaredSecretFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_undeclared_secret(source_revision=source_revision)
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
    summary = publish_undeclared_secret(
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
