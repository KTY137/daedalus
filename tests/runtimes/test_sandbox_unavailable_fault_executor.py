from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "sandbox_unavailable_fault_executor.py"
REVISION = "a" * 40


def _load_executor_module():
    name = "daedalus_test_sandbox_unavailable_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load sandbox-unavailable executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="canonical sandbox unavailability fault requires Linux"
)


def test_real_missing_docker_endpoint_refuses_before_attempt_start() -> None:
    run = executor.run_sandbox_unavailable(source_revision=REVISION)
    assert run.observation.scenario_id == "runtime.sandbox.daemon-unavailable"
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["launch_state"] == "refused-before-start"
    assert payload["receipt"]["error_code"] in {
        "docker-cli-refused",
        "runtime-not-found",
        "runtime-not-executable",
        "runtime-launch-error",
    }
    assert payload["workspace_marker_exists"] is False
    assert payload["host_fallback_observed"] is False
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_fault_executor_restores_all_docker_environment(monkeypatch) -> None:
    original = {
        "DOCKER_HOST": "tcp://127.0.0.1:2375",
        "DOCKER_CONTEXT": "example-context",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": "/tmp/certs",
    }
    for name, value in original.items():
        monkeypatch.setenv(name, value)
    executor.run_sandbox_unavailable(source_revision=REVISION)
    assert {name: os.environ.get(name) for name in original} == original


def test_published_files_remain_explicitly_untrusted(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_sandbox_unavailable(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "refused-before-start"
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False

    evidence = LinuxHostFaultEvidence.from_dict(
        json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    )
    observation = json.loads(
        (output / "observation.json").read_text(encoding="utf-8")
    )
    raw = (output / "raw").read_bytes()
    assert evidence.digest == summary["evidence_sha256"]
    assert observation["evidence_sha256"] == evidence.digest
    assert hashlib.sha256(raw).hexdigest() == evidence.raw_evidence_sha256


def test_output_directory_symlink_refuses_without_writing(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(executor.SandboxUnavailableFaultError, match="must not be a symlink"):
        executor.publish_sandbox_unavailable(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_executor_implementation_binds_sandbox_boundary_bytes() -> None:
    first = executor.implementation_sha256()
    original = executor._SANDBOX_SOURCE
    try:
        executor._SANDBOX_SOURCE = EXECUTOR_PATH
        second = executor.implementation_sha256()
    finally:
        executor._SANDBOX_SOURCE = original
    assert first != second


def test_cli_emits_only_untrusted_fault_material(tmp_path: Path) -> None:
    import subprocess

    output = tmp_path / "cli"
    completed = subprocess.run(
        [
            sys.executable,
            str(EXECUTOR_PATH),
            "--source-revision",
            REVISION,
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        timeout=20,
    )
    summary = json.loads(completed.stdout)
    assert summary["status"] == "passed"
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
