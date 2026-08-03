from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.sandbox import SandboxExecutionReceipt
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "container_oom_fault_executor.py"
REVISION = "a" * 40
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _load_executor_module():
    name = "daedalus_test_container_oom_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load container OOM executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()


def _receipt(
    *,
    launch_state: str = "completed",
    returncode: int | None = 137,
    timed_out: bool = False,
    error_code: str | None = None,
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


def _fake_docker(tmp_path: Path) -> Path:
    binary = tmp_path / "docker"
    binary.write_bytes(b"bounded fake docker identity")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def _linux_with_docker(tmp_path: Path, monkeypatch) -> Path:
    binary = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(binary))
    monkeypatch.setattr(executor.os, "access", lambda path, mode: True)
    return binary


def _simulate(
    tmp_path: Path,
    monkeypatch,
    receipt: SandboxExecutionReceipt,
    *,
    create_marker: bool,
):
    _linux_with_docker(tmp_path, monkeypatch)
    moments = iter((100.0, 100.125))
    monkeypatch.setattr(
        executor,
        "time",
        SimpleNamespace(monotonic=lambda: next(moments)),
    )

    def invoke(policy, command):
        assert policy.image == executor._IMAGE
        assert policy.memory == executor._MEMORY
        assert policy.network == "none"
        assert policy.pids_limit == 32
        assert tuple(command) == executor._allocation_command()
        if create_marker:
            (policy.candidate_workspace / "oom-started").write_text(
                "started", encoding="utf-8"
            )
        return receipt

    monkeypatch.setattr(executor, "run_in_docker_sandbox", invoke)
    return executor.run_container_oom(source_revision=REVISION)


def test_binding_is_catalog_exact_and_covers_boundary_image_and_limits() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.oom"]
    binding = executor.container_oom_binding()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "sandbox_sha256": hashlib.sha256(
                executor._sandbox_source_path().read_bytes()
            ).hexdigest(),
            "image": executor._IMAGE,
            "memory": executor._MEMORY,
            "timeout_s": executor._TIMEOUT_S,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_recombined_or_mutated_scenario_refuses_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.oom"]
    mutated = dataclasses.replace(
        scenario,
        invariant="candidate-controlled replacement invariant",
    )
    with pytest.raises(executor.ContainerOomFaultError, match="scenario_sha256"):
        executor.container_oom_binding().execute(mutated)


def test_missing_docker_cli_is_blocked_not_passed(monkeypatch) -> None:
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: None)

    run = executor.run_container_oom(source_revision=REVISION)

    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "docker-cli-unavailable"


def test_exact_started_container_sigkill_observation_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=137),
        create_marker=True,
    )

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["launch_state"] == "completed"
    assert payload["receipt"]["returncode"] == 137
    assert payload["receipt"]["timed_out"] is False
    assert payload["started_marker_exists"] is True
    assert payload["memory"] == executor._MEMORY
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_returncode_137_without_started_marker_cannot_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=137),
        create_marker=False,
    )

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "container-oom-invariant"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["started_marker_exists"] is False


@pytest.mark.parametrize("returncode", [0, 1, 126, 127, 143])
def test_other_completed_results_cannot_pass(
    tmp_path: Path,
    monkeypatch,
    returncode: int,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=returncode),
        create_marker=True,
    )

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "container-oom-invariant"


def test_timeout_cannot_be_laundered_as_oom(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(
            launch_state="timed-out",
            returncode=None,
            timed_out=True,
            error_code="timeout",
        ),
        create_marker=True,
    )

    assert run.observation.status == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["launch_state"] == "timed-out"


def test_sandbox_prestart_refusal_is_blocked_not_oom(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(
            launch_state="refused-before-start",
            returncode=125,
            error_code="docker-cli-refused",
        ),
        create_marker=False,
    )

    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "sandbox-unavailable"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["returncode"] == 125


def test_published_files_remain_explicitly_untrusted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _linux_with_docker(tmp_path, monkeypatch)
    moments = iter((100.0, 100.125))
    monkeypatch.setattr(
        executor,
        "time",
        SimpleNamespace(monotonic=lambda: next(moments)),
    )

    def oom(policy, command):
        (policy.candidate_workspace / "oom-started").write_text(
            "started", encoding="utf-8"
        )
        return _receipt(returncode=137)

    monkeypatch.setattr(executor, "run_in_docker_sandbox", oom)
    output = tmp_path / "reports"
    summary = executor.publish_container_oom(
        source_revision=REVISION,
        output_dir=output,
    )

    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "failed"
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
    with pytest.raises(executor.ContainerOomFaultError, match="must not be a symlink"):
        executor.publish_container_oom(
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


@pytest.mark.skipif(
    os.environ.get("DAEDALUS_RUN_REAL_CONTAINER_OOM") != "1",
    reason="real container OOM execution is retained by the dedicated host job",
)
def test_real_container_oom_is_exact_pass() -> None:
    run = executor.run_container_oom(source_revision=REVISION)
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["returncode"] == 137
    assert payload["started_marker_exists"] is True
