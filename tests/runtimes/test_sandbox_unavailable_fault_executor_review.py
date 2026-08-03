from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "sandbox_unavailable_fault_executor.py"
SANDBOX_PATH = ROOT / "daedalus" / "kernel" / "sandbox.py"


def _load_executor_module():
    name = "daedalus_review_sandbox_unavailable_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load sandbox fault executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()


def test_executor_has_no_second_process_launcher_or_shell_escape() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    forbidden_attributes = {
        ("subprocess", "Popen"),
        ("subprocess", "run"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("os", "system"),
        ("os", "popen"),
    }
    observed: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            assert not (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            observed.add((node.func.value.id, node.func.attr))
    assert not (observed & forbidden_attributes)
    assert "run_in_docker_sandbox" in source


def test_production_sandbox_has_one_process_boundary_and_no_host_fallback() -> None:
    source = SANDBOX_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SANDBOX_PATH))
    subprocess_runs = []
    host_fallbacks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            pair = (node.func.value.id, node.func.attr)
            if pair == ("subprocess", "run"):
                subprocess_runs.append(node)
            if pair in {
                ("subprocess", "Popen"),
                ("os", "system"),
                ("os", "popen"),
            }:
                host_fallbacks.append(pair)
        for keyword in node.keywords:
            assert not (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
    assert len(subprocess_runs) == 1
    assert host_fallbacks == []
    assert '"docker", "run"' in source


def test_daemon_fault_requires_cli_presence_and_exact_125_classification() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert 'shutil.which("docker")' in source
    assert 'detail_code="docker-cli-unavailable"' in source
    assert 'receipt.error_code == "docker-cli-refused"' in source
    assert "receipt.returncode == 125" in source
    assert 'receipt.launch_state == "refused-before-start"' in source
    assert 'HostFaultFact("docker-cli-sha256"' in source


def test_raw_evidence_retains_digests_not_daemon_output_or_socket_path() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert '"stdout_sha256"' in source
    assert '"stderr_sha256"' in source
    assert '"stdout":' not in source
    assert '"stderr":' not in source
    assert '"missing_socket_path_sha256"' in source
    assert '"missing_socket_path"' not in source
    assert "str(missing_socket).encode" in source


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    forbidden_true = {"trusted", "attested", "gate_closure_claimed"}
    observed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value in forbidden_true:
                observed.add(key.value)
                assert isinstance(value, ast.Constant)
                assert value.value is False
    assert observed == forbidden_true


def test_control_flow_baseexception_is_not_laundered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux":
        pytest.skip("canonical host fault is Linux-only")
    fake = tmp_path / "docker"
    fake.write_bytes(b"docker")
    fake.chmod(0o755)
    monkeypatch.setattr(executor.shutil, "which", lambda name: str(fake))

    class StopRun(BaseException):
        pass

    def stop(policy, command):
        raise StopRun()

    monkeypatch.setattr(executor, "run_in_docker_sandbox", stop)
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.sandbox.daemon-unavailable"
    ]
    with pytest.raises(StopRun):
        executor._execute_sandbox_unavailable(scenario)


def test_environment_restoration_covers_every_mutated_docker_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = {
        "DOCKER_HOST": "tcp://operator.invalid:2375",
        "DOCKER_CONTEXT": "operator",
        "DOCKER_TLS_VERIFY": "1",
        "DOCKER_CERT_PATH": "/operator/certs",
    }
    for key, value in original.items():
        monkeypatch.setenv(key, value)
    missing = Path("/tmp/daedalus-review-definitely-missing.sock")
    if missing.exists() or missing.is_symlink():
        pytest.skip("review fixture path unexpectedly exists")
    with executor._unavailable_docker_environment(missing):
        assert os.environ["DOCKER_HOST"].startswith("unix://")
        assert "DOCKER_CONTEXT" not in os.environ
        assert "DOCKER_TLS_VERIFY" not in os.environ
        assert "DOCKER_CERT_PATH" not in os.environ
    assert {key: os.environ.get(key) for key in original} == original
