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
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "unauthorized_egress_fault_executor.py"
REVISION = "a" * 40
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _load_executor():
    name = "daedalus_test_unauthorized_egress_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


def _receipt(*, state="completed", returncode=73, timed_out=False, error_code=None):
    return SandboxExecutionReceipt(
        argv_sha256="a" * 64,
        returncode=returncode,
        timed_out=timed_out,
        stdout_sha256=EMPTY_SHA,
        stderr_sha256=EMPTY_SHA,
        launch_state=state,
        error_code=error_code,
    )


def _marker(**changes):
    value = {
        "schema": executor._MARKER_SCHEMA,
        "supported": True,
        "interfaces": ["lo"],
        "default_route": False,
        "endpoint_host": executor._ENDPOINT_HOST,
        "endpoint_port": executor._ENDPOINT_PORT,
        "connect_succeeded": False,
        "errno": executor._CONNECT_ERRNO,
    }
    value.update(changes)
    return value


def _fake_docker(tmp_path: Path) -> Path:
    binary = tmp_path / "docker"
    binary.write_bytes(b"bounded fake docker identity")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def _simulate(tmp_path, monkeypatch, receipt, *, marker=None, started=True):
    binary = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(binary))
    monkeypatch.setattr(executor.os, "access", lambda path, mode: True)
    moments = iter((100.0, 100.125))
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: next(moments)))

    def invoke(policy, command):
        assert policy.image == executor._IMAGE
        assert policy.network == "none"
        assert policy.memory == "128m"
        assert tuple(command) == executor._network_probe_command()
        if started:
            (policy.candidate_workspace / "egress-started").write_text("started")
        if marker is not None:
            raw = marker if isinstance(marker, bytes) else json.dumps(
                marker, sort_keys=True, separators=(",", ":")
            ).encode()
            (policy.candidate_workspace / "egress-observed.json").write_bytes(raw)
        return receipt

    monkeypatch.setattr(executor, "run_in_docker_sandbox", invoke)
    return executor.run_unauthorized_egress(source_revision=REVISION)


def test_binding_is_catalog_exact_and_content_addressed() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.egress.unauthorized-endpoint"]
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "marker_schema": executor._MARKER_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "sandbox_sha256": hashlib.sha256(executor._sandbox_source_path().read_bytes()).hexdigest(),
            "image": executor._IMAGE,
            "network": executor._NETWORK_MODE,
            "endpoint_host": executor._ENDPOINT_HOST,
            "endpoint_port": executor._ENDPOINT_PORT,
            "connect_errno": executor._CONNECT_ERRNO,
            "timeout_s": executor._TIMEOUT_S,
        }
    )
    binding = executor.unauthorized_egress_binding()
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected


def test_mutated_scenario_refuses_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map["runtime.egress.unauthorized-endpoint"]
    mutated = dataclasses.replace(scenario, invariant="candidate-selected invariant")
    with pytest.raises(executor.UnauthorizedEgressFaultError, match="scenario_sha256"):
        executor.unauthorized_egress_binding().execute(mutated)


def test_missing_docker_is_blocked(monkeypatch) -> None:
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: None)
    run = executor.run_unauthorized_egress(source_revision=REVISION)
    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "docker-cli-unavailable"


def test_exact_network_none_denial_passes(tmp_path, monkeypatch) -> None:
    run = _simulate(tmp_path, monkeypatch, _receipt(), marker=_marker())
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "failed"
    payload = json.loads(run.raw_evidence)
    assert payload["network"] == "none"
    assert payload["started_marker_exists"] is True
    assert payload["egress_marker"]["interfaces"] == ["lo"]
    assert payload["egress_marker"]["default_route"] is False
    assert payload["egress_marker"]["connect_succeeded"] is False
    assert payload["egress_marker"]["errno"] == executor._CONNECT_ERRNO


@pytest.mark.parametrize(
    "marker",
    [
        None,
        b"not-json",
        b'{"schema":"a","schema":"b"}',
        _marker(errno=1),
        _marker(connect_succeeded=True, errno=None),
        _marker(default_route=True),
        _marker(interfaces=["eth0", "lo"]),
        _marker(endpoint_host="203.0.113.1"),
        _marker(supported=False),
    ],
)
def test_malformed_or_weakened_oracle_cannot_pass(tmp_path, monkeypatch, marker) -> None:
    run = _simulate(tmp_path, monkeypatch, _receipt(), marker=marker)
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "unauthorized-egress-invariant"


def test_inspection_unavailable_is_an_exact_block(tmp_path, monkeypatch) -> None:
    marker = _marker(supported=False, interfaces=[], connect_succeeded=False, errno=None)
    run = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(returncode=executor._INSPECTION_UNAVAILABLE_RETURNCODE),
        marker=marker,
        started=False,
    )
    assert run.observation.status == "blocked"
    assert run.observation.detail_code == "network-namespace-inspection-unavailable"


@pytest.mark.parametrize("returncode", [0, 1, 72, 74, 76, 126, 127])
def test_other_completed_transport_cannot_pass(tmp_path, monkeypatch, returncode) -> None:
    run = _simulate(tmp_path, monkeypatch, _receipt(returncode=returncode), marker=_marker())
    assert run.observation.status == "failed"


def test_timeout_and_prestart_refusal_cannot_be_laundered(tmp_path, monkeypatch) -> None:
    timeout = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(state="timed-out", returncode=None, timed_out=True, error_code="timeout"),
        marker=_marker(),
    )
    assert timeout.observation.status == "failed"

    refused = _simulate(
        tmp_path,
        monkeypatch,
        _receipt(state="refused-before-start", returncode=125, error_code="docker-cli-refused"),
        marker=None,
        started=False,
    )
    assert refused.observation.status == "blocked"
    assert refused.observation.detail_code == "sandbox-unavailable"


def test_published_files_are_digest_bound_and_untrusted(tmp_path, monkeypatch) -> None:
    binary = _fake_docker(tmp_path)
    monkeypatch.setattr(executor.sys, "platform", "linux")
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(binary))
    monkeypatch.setattr(executor.os, "access", lambda path, mode: True)
    moments = iter((100.0, 100.125))
    monkeypatch.setattr(executor, "time", SimpleNamespace(monotonic=lambda: next(moments)))

    def denied(policy, command):
        (policy.candidate_workspace / "egress-started").write_text("started")
        (policy.candidate_workspace / "egress-observed.json").write_text(
            json.dumps(_marker(), sort_keys=True, separators=(",", ":"))
        )
        return _receipt()

    monkeypatch.setattr(executor, "run_in_docker_sandbox", denied)
    output = tmp_path / "reports"
    summary = executor.publish_unauthorized_egress(source_revision=REVISION, output_dir=output)
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    evidence = LinuxHostFaultEvidence.from_dict(json.loads((output / "evidence.json").read_text()))
    raw = (output / "raw").read_bytes()
    assert evidence.digest == summary["evidence_sha256"]
    assert hashlib.sha256(raw).hexdigest() == evidence.raw_evidence_sha256


def test_output_directory_symlink_refuses(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(executor.UnauthorizedEgressFaultError, match="must not be a symlink"):
        executor.publish_unauthorized_egress(source_revision=REVISION, output_dir=linked)
    assert list(real.iterdir()) == []


def test_implementation_digest_changes_with_sandbox_source() -> None:
    first = executor.implementation_sha256()
    original = executor._sandbox_source_path
    try:
        executor._sandbox_source_path = lambda: EXECUTOR_PATH
        second = executor.implementation_sha256()
    finally:
        executor._sandbox_source_path = original
    assert first != second


@pytest.mark.skipif(
    os.environ.get("DAEDALUS_RUN_REAL_UNAUTHORIZED_EGRESS") != "1",
    reason="real Docker egress fault is retained by the dedicated host job",
)
def test_real_unauthorized_egress_is_exact_pass() -> None:
    run = executor.run_unauthorized_egress(source_revision=REVISION)
    assert run.observation.status == "passed"
    payload = json.loads(run.raw_evidence)
    assert payload["network"] == "none"
    assert payload["started_marker_exists"] is True
    assert payload["egress_marker"]["interfaces"] == ["lo"]
    assert payload["egress_marker"]["default_route"] is False
    assert payload["egress_marker"]["connect_succeeded"] is False
    assert payload["egress_marker"]["errno"] == executor._CONNECT_ERRNO
