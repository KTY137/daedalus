from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = (
    ROOT / "tests" / "fixtures" / "linux_sandbox_unavailable_fault_executor.py"
)
REVISION = "b" * 40


def _load_executor_module():
    name = "daedalus_test_linux_sandbox_unavailable_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Linux sandbox fault executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()
requires_docker = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("docker") is None,
    reason="canonical sandbox-unavailable fault requires Linux and the Docker CLI",
)


@requires_docker
def test_real_missing_daemon_socket_refuses_without_host_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_host = "tcp://127.0.0.1:2375"
    monkeypatch.setenv("DOCKER_HOST", previous_host)
    run = executor.run_sandbox_unavailable_fault(source_revision=REVISION)

    assert os.environ["DOCKER_HOST"] == previous_host
    assert run.observation.scenario_id == "runtime.sandbox.daemon-unavailable"
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"

    payload = json.loads(run.raw_evidence.decode("utf-8"))
    receipt = payload["receipt"]
    assert payload["marker_exists"] is False
    assert payload["detail_code"] is None
    assert receipt["timed_out"] is False
    assert isinstance(receipt["returncode"], int)
    assert receipt["returncode"] != 0
    assert len(receipt["argv_sha256"]) == 64
    assert len(receipt["stdout_sha256"]) == 64
    assert len(receipt["stderr_sha256"]) == 64
    assert len(receipt["receipt_sha256"]) == 64
    assert hashlib.sha256(run.raw_evidence).hexdigest() == (
        run.evidence.raw_evidence_sha256
    )
    assert "stdout" not in payload
    assert "stderr" not in payload


def test_binding_is_exactly_catalog_bound_and_covers_production_sandbox_bytes() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    binding = executor.sandbox_unavailable_binding()
    sandbox_source = executor._sandbox_source_path()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "sandbox_module_sha256": hashlib.sha256(
                sandbox_source.read_bytes()
            ).hexdigest(),
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_recombined_or_mutated_scenario_is_refused_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    mutated = dataclasses.replace(
        scenario,
        invariant="a candidate-controlled replacement invariant",
    )
    with pytest.raises(
        executor.LinuxSandboxUnavailableFaultError,
        match="scenario_sha256",
    ):
        executor.sandbox_unavailable_binding().execute(mutated)


@requires_docker
def test_published_artifacts_are_untrusted_and_self_consistent(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_sandbox_unavailable_fault(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    assert len(summary["runs"]) == 1
    row = summary["runs"][0]
    assert row["status"] == "passed"

    prefix = row["scenario_id"]
    evidence = LinuxHostFaultEvidence.from_dict(
        json.loads(
            (output / f"{prefix}.evidence.json").read_text(encoding="utf-8")
        )
    )
    observation = json.loads(
        (output / f"{prefix}.observation.json").read_text(encoding="utf-8")
    )
    raw = (output / f"{prefix}.raw").read_bytes()
    persisted_summary = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )

    assert persisted_summary == summary
    assert evidence.digest == row["evidence_sha256"]
    assert observation["evidence_sha256"] == evidence.digest
    assert hashlib.sha256(raw).hexdigest() == evidence.raw_evidence_sha256


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation is privilege-dependent")
def test_output_directory_symlink_is_refused_without_touching_target(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(
        executor.LinuxSandboxUnavailableFaultError,
        match="must not be a symlink",
    ):
        executor.publish_sandbox_unavailable_fault(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_environment_is_restored_when_sandbox_invocation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux" or shutil.which("docker") is None:
        pytest.skip("requires Linux and a readable Docker CLI")
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "operator-context")

    def explode(policy, command):
        raise RuntimeError("collector-local injected failure")

    monkeypatch.setattr(executor, "run_in_docker_sandbox", explode)
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    result = executor._execute_sandbox_unavailable(scenario)

    assert result.status == "failed"
    assert result.detail_code == "sandbox-unavailable-invariant"
    assert os.environ["DOCKER_HOST"] == "tcp://127.0.0.1:2375"
    assert os.environ["DOCKER_CONTEXT"] == "operator-context"


@requires_docker
def test_cli_emits_only_untrusted_exact_revision_artifacts(
    tmp_path: Path,
) -> None:
    import subprocess

    output = tmp_path / "cli-reports"
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
    stdout = json.loads(completed.stdout)
    assert stdout["source_revision"] == REVISION
    assert stdout["trusted"] is False
    assert stdout["attested"] is False
    assert stdout["gate_closure_claimed"] is False
    assert stdout["runs"][0]["status"] == "passed"
