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
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "undeclared_secret_fault_executor.py"
REVISION = "a" * 40
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
CANARY = "de" * 32


def _load_executor_module():
    name = "daedalus_test_undeclared_secret_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load undeclared-secret executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()


def _receipt(
    *,
    launch_state: str = "completed",
    returncode: int | None = 76,
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


def _valid_marker(**changes):
    payload = {
        "schema": executor._MARKER_SCHEMA,
        "supported": True,
        "secret_name": executor._SECRET_NAME,
        "secret_name_present": False,
        "secret_value_read": False,
        "environment_names_sha256": "1" * 64,
        "mountinfo_sha256": "2" * 64,
        "secret_mount_detected": False,
        "secret_artifact_count": 0,
        "artifact_scan_bounded": True,
    }
    payload.update(changes)
    return payload


def _unsupported_marker():
    return _valid_marker(
        supported=False,
        environment_names_sha256=executor._ZERO_SHA256,
        mountinfo_sha256=executor._ZERO_SHA256,
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
    monkeypatch.setattr(executor.secrets, "token_hex", lambda size: CANARY)
    monkeypatch.delenv(executor._SECRET_NAME, raising=False)
    return binary


def _simulate(
    tmp_path: Path,
    monkeypatch,
    receipt: SandboxExecutionReceipt,
    *,
    create_start_marker: bool,
    marker_payload: dict | bytes | None,
    mutate_host_secret: bool = False,
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
        assert policy.network == "none"
        assert policy.reference_mounts == ()
        assert policy.memory == "128m"
        assert policy.pids_limit == 32
        assert tuple(command) == executor._secret_probe_command()
        assert os.environ[executor._SECRET_NAME] == CANARY
        if create_start_marker:
            (policy.candidate_workspace / "secret-started").write_text(
                "started", encoding="utf-8"
            )
        if marker_payload is not None:
            content = (
                marker_payload
                if isinstance(marker_payload, bytes)
                else json.dumps(
                    marker_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            (policy.candidate_workspace / "secret-observed.json").write_bytes(content)
        if mutate_host_secret:
            os.environ[executor._SECRET_NAME] = "mutated"
        return receipt

    monkeypatch.setattr(executor, "run_in_docker_sandbox", invoke)
    run = executor.run_undeclared_secret(source_revision=REVISION)
    assert executor._SECRET_NAME not in os.environ
    return run


def test_binding_is_catalog_exact_and_covers_boundary_name_roots_and_image() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.secrets.undeclared-access"
    ]
    binding = executor.undeclared_secret_binding()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "marker_schema": executor._MARKER_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "sandbox_sha256": hashlib.sha256(
                executor._sandbox_source_path().read_bytes()
            ).hexdigest(),
            "image": executor._IMAGE,
            "secret_name": executor._SECRET_NAME,
            "secret_roots": list(executor._SECRET_ROOTS),
            "timeout_s": executor._TIMEOUT_S,
            "max_secret_artifacts": executor._MAX_SECRET_ARTIFACTS,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_recombined_or_mutated_scenario_refuses_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.secrets.undeclared-access"
    ]
    mutated = dataclasses.replace(
        scenario,
        invariant="candidate-controlled replacement invariant",
    )
    with pytest.raises(executor.UndeclaredSecretFaultError, match="scenario_sha256"):
        executor.undeclared_secret_binding().execute(mutated)


def test_missing_docker_cli_is_blocked_not_passed(monkeypatch) -> None:
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: None)
    monkeypatch.delenv(executor._SECRET_NAME, raising=False)

    run = executor.run_undeclared_secret(source_revision=REVISION)

    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "docker-cli-unavailable"


def test_exact_environment_and_mount_isolation_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=True,
        marker_payload=_valid_marker(),
    )

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["receipt"]["returncode"] == 76
    assert payload["started_marker_exists"] is True
    assert payload["host_environment_restored"] is True
    assert payload["secret_marker_status"] == "valid"
    marker = payload["secret_marker"]
    assert marker["secret_name_present"] is False
    assert marker["secret_value_read"] is False
    assert marker["secret_mount_detected"] is False
    assert marker["secret_artifact_count"] == 0
    assert CANARY not in run.raw_evidence.decode("utf-8")
    assert payload["canary_sha256"] == hashlib.sha256(CANARY.encode()).hexdigest()
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


@pytest.mark.parametrize(
    "marker_payload",
    [
        None,
        _valid_marker(secret_name_present=True),
        _valid_marker(secret_value_read=True),
        _valid_marker(secret_mount_detected=True),
        _valid_marker(secret_artifact_count=1),
        _valid_marker(artifact_scan_bounded=False),
        _valid_marker(environment_names_sha256=executor._ZERO_SHA256),
        _valid_marker(mountinfo_sha256=executor._ZERO_SHA256),
        _valid_marker(secret_name="FOREIGN_SECRET"),
        b'{"schema":"duplicate","schema":"duplicate"}',
        b"not-json",
    ],
)
def test_missing_malformed_or_weakened_marker_cannot_pass(
    tmp_path: Path,
    monkeypatch,
    marker_payload,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=True,
        marker_payload=marker_payload,
    )
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "secret-isolation-invariant"


def test_marker_containing_canary_is_rejected_before_retention(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=True,
        marker_payload=_valid_marker(environment_names_sha256=CANARY),
    )
    assert run.observation.status == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["secret_marker_status"] == "invalid"
    assert payload["secret_marker"] is None
    assert CANARY not in run.raw_evidence.decode("utf-8")


def test_marker_without_start_cannot_pass(tmp_path: Path, monkeypatch) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=False,
        marker_payload=_valid_marker(),
    )
    assert run.observation.status == "failed"


@pytest.mark.parametrize("returncode", [0, 1, 73, 75, 77, 78, 125, 137])
def test_other_completed_results_cannot_pass(
    tmp_path: Path,
    monkeypatch,
    returncode: int,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=returncode),
        create_start_marker=True,
        marker_payload=_valid_marker(),
    )
    assert run.observation.status == "failed"


def test_secret_namespace_inspection_unavailability_is_exact_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=78),
        create_start_marker=False,
        marker_payload=_unsupported_marker(),
    )
    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "secret-namespace-inspection-unavailable"


def test_unsupported_claim_with_wrong_transport_cannot_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=False,
        marker_payload=_unsupported_marker(),
    )
    assert run.observation.status == "failed"


def test_host_secret_name_collision_blocks_without_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _linux_with_docker(tmp_path, monkeypatch)
    monkeypatch.setenv(executor._SECRET_NAME, "preexisting")
    invoked = False

    def invoke(policy, command):
        nonlocal invoked
        invoked = True
        return _receipt()

    monkeypatch.setattr(executor, "run_in_docker_sandbox", invoke)
    run = executor.run_undeclared_secret(source_revision=REVISION)
    assert run.observation.status == "blocked"
    assert run.observation.detail_code == "host-secret-probe-name-collision"
    assert os.environ[executor._SECRET_NAME] == "preexisting"
    assert invoked is False


def test_host_environment_mutation_is_explicit_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=76),
        create_start_marker=True,
        marker_payload=_valid_marker(),
        mutate_host_secret=True,
    )
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "host-secret-probe-mutated"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["host_environment_restored"] is False
    assert CANARY not in run.raw_evidence.decode("utf-8")


def test_unexpected_sandbox_exception_still_restores_host_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _linux_with_docker(tmp_path, monkeypatch)

    def explode(policy, command):
        assert os.environ[executor._SECRET_NAME] == CANARY
        raise RuntimeError("synthetic sandbox failure")

    monkeypatch.setattr(executor, "run_in_docker_sandbox", explode)
    with pytest.raises(RuntimeError, match="synthetic"):
        executor.run_undeclared_secret(source_revision=REVISION)
    assert executor._SECRET_NAME not in os.environ


def test_timeout_cannot_be_laundered_as_isolation(
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
        create_start_marker=True,
        marker_payload=_valid_marker(),
    )
    assert run.observation.status == "failed"


def test_sandbox_prestart_refusal_is_blocked_not_isolation(
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
        create_start_marker=False,
        marker_payload=None,
    )
    assert run.observation.status == "blocked"
    assert run.observation.detail_code == "sandbox-unavailable"


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

    def isolate(policy, command):
        assert os.environ[executor._SECRET_NAME] == CANARY
        (policy.candidate_workspace / "secret-started").write_text(
            "started", encoding="utf-8"
        )
        (policy.candidate_workspace / "secret-observed.json").write_text(
            json.dumps(_valid_marker(), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return _receipt(returncode=76)

    monkeypatch.setattr(executor, "run_in_docker_sandbox", isolate)
    output = tmp_path / "reports"
    summary = executor.publish_undeclared_secret(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "failed"
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    assert executor._SECRET_NAME not in os.environ

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
    assert CANARY.encode() not in raw


def test_output_directory_symlink_refuses_without_writing(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(executor.UndeclaredSecretFaultError, match="must not be a symlink"):
        executor.publish_undeclared_secret(
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
    os.environ.get("DAEDALUS_RUN_REAL_SECRET_ISOLATION") != "1",
    reason="real secret-isolation execution is retained by the dedicated host job",
)
def test_real_undeclared_secret_is_exact_pass() -> None:
    run = executor.run_undeclared_secret(source_revision=REVISION)
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "failed"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    marker = payload["secret_marker"]
    assert payload["receipt"]["returncode"] == 76
    assert marker["secret_name_present"] is False
    assert marker["secret_value_read"] is False
    assert marker["secret_mount_detected"] is False
    assert marker["secret_artifact_count"] == 0
