# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.kernel.sandbox import SandboxExecutionReceipt
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "sandbox_unavailable_fault_executor.py"
REVISION = "a" * 40
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


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


def _fake_docker(tmp_path: Path) -> Path:
    binary = tmp_path / "docker"
    binary.write_bytes(b"#!/bin/sh\nexit 125\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def _receipt(
    *,
    launch_state: str,
    error_code: str | None,
    returncode: int | None,
    timed_out: bool = False,
) -> SandboxExecutionReceipt:
    return SandboxExecutionReceipt(
        argv_sha256="a" * 64,
        returncode=returncode,
        timed_out=timed_out,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
        launch_state=launch_state,
        error_code=error_code,
    )


def test_real_missing_docker_endpoint_is_exact_pass_or_explicit_block() -> None:
    run = executor.run_sandbox_unavailable(source_revision=REVISION)
    assert run.observation.scenario_id == "runtime.sandbox.daemon-unavailable"
    payload = json.loads(run.raw_evidence.decode("utf-8"))

    if run.observation.status == "blocked":
        assert run.observation.observed_outcome is None
        assert run.observation.detail_code in {
            "docker-cli-unavailable",
            "docker-cli-unreadable",
        }
        assert payload["receipt"] is None
        assert payload["workspace_marker_exists"] is False
        return

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"
    assert payload["receipt"]["launch_state"] == "refused-before-start"
    assert payload["receipt"]["error_code"] == "docker-cli-refused"
    assert payload["receipt"]["returncode"] == 125
    assert payload["receipt"]["timed_out"] is False
    assert payload["docker_cli_sha256"] is not None
    assert payload["workspace_marker_exists"] is False
    assert payload["host_fallback_observed"] is False
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_binding_is_catalog_exact_and_covers_production_boundary_bytes() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    binding = executor.sandbox_unavailable_binding()
    sandbox_source = executor._sandbox_source_path()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "sandbox_sha256": hashlib.sha256(sandbox_source.read_bytes()).hexdigest(),
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_recombined_or_mutated_scenario_refuses_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    mutated = dataclasses.replace(
        scenario,
        invariant="candidate-controlled replacement invariant",
    )
    with pytest.raises(
        executor.SandboxUnavailableFaultError,
        match="scenario_sha256",
    ):
        executor.sandbox_unavailable_binding().execute(mutated)


def test_missing_docker_cli_is_blocked_not_passed(monkeypatch) -> None:
    monkeypatch.setattr(executor.shutil, "which", lambda name: None)

    run = executor.run_sandbox_unavailable(source_revision=REVISION)

    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "docker-cli-unavailable"


def test_non_daemon_prestart_refusal_cannot_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))
    monkeypatch.setattr(
        executor,
        "run_in_docker_sandbox",
        lambda policy, command: _receipt(
            launch_state="refused-before-start",
            error_code="runtime-not-found",
            returncode=None,
        ),
    )

    run = executor.run_sandbox_unavailable(source_revision=REVISION)

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "sandbox-unavailable-invariant"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["error_code"] == "runtime-not-found"


def test_arbitrary_nonzero_completed_result_cannot_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))
    monkeypatch.setattr(
        executor,
        "run_in_docker_sandbox",
        lambda policy, command: _receipt(
            launch_state="completed",
            error_code=None,
            returncode=1,
        ),
    )

    run = executor.run_sandbox_unavailable(source_revision=REVISION)

    assert run.observation.status == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["launch_state"] == "completed"
    assert payload["receipt"]["returncode"] == 1


def test_exact_125_refusal_passes_and_restores_docker_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))

    observed_host: list[str | None] = []

    def refuse(policy, command):
        observed_host.append(os.environ.get("DOCKER_HOST"))
        assert os.environ.get("DOCKER_CONTEXT") is None
        assert os.environ.get("DOCKER_TLS_VERIFY") is None
        assert os.environ.get("DOCKER_CERT_PATH") is None
        return _receipt(
            launch_state="refused-before-start",
            error_code="docker-cli-refused",
            returncode=125,
        )

    monkeypatch.setattr(executor, "run_in_docker_sandbox", refuse)
    original = {
        "DOCKER_HOST": "tcp://127.0.0.1:2375",
        "DOCKER_CONTEXT": "example-context",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": "/tmp/certs",
    }
    for name, value in original.items():
        monkeypatch.setenv(name, value)

    run = executor.run_sandbox_unavailable(source_revision=REVISION)

    assert run.observation.status == "passed"
    assert observed_host and observed_host[0].startswith("unix://")
    assert {name: os.environ.get(name) for name in original} == original


def test_environment_restores_when_sandbox_boundary_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))
    original = {
        "DOCKER_HOST": "tcp://127.0.0.1:2375",
        "DOCKER_CONTEXT": "operator-context",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": "/operator/certs",
    }
    for name, value in original.items():
        monkeypatch.setenv(name, value)

    def explode(policy, command):
        raise RuntimeError("collector-local injected failure")

    monkeypatch.setattr(executor, "run_in_docker_sandbox", explode)
    with pytest.raises(RuntimeError, match="collector-local"):
        executor.run_sandbox_unavailable(source_revision=REVISION)
    assert {name: os.environ.get(name) for name in original} == original


def test_published_files_remain_explicitly_untrusted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))
    monkeypatch.setattr(
        executor,
        "run_in_docker_sandbox",
        lambda policy, command: _receipt(
            launch_state="refused-before-start",
            error_code="docker-cli-refused",
            returncode=125,
        ),
    )
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
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(executor.SandboxUnavailableFaultError, match="must not be a symlink"):
        executor.publish_sandbox_unavailable(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_executor_implementation_changes_with_sandbox_boundary_bytes() -> None:
    first = executor.implementation_sha256()
    original = executor._sandbox_source_path
    try:
        executor._sandbox_source_path = lambda: EXECUTOR_PATH
        second = executor.implementation_sha256()
    finally:
        executor._sandbox_source_path = original
    assert first != second


def test_cli_emits_only_untrusted_fault_material(tmp_path: Path) -> None:
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
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        timeout=20,
    )
    summary = json.loads(completed.stdout)
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    if summary["status"] == "passed":
        assert completed.returncode == 0
    elif summary["status"] == "blocked":
        assert completed.returncode == 2
        assert summary["detail_code"] in {
            "docker-cli-unavailable",
            "docker-cli-unreadable",
        }
    else:
        assert completed.returncode == 1
