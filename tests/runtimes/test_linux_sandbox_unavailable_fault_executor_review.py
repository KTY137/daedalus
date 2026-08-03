from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = (
    ROOT / "tests" / "fixtures" / "linux_sandbox_unavailable_fault_executor.py"
)
SANDBOX_PATH = ROOT / "daedalus" / "kernel" / "sandbox.py"


def _load_executor_module():
    name = "daedalus_review_linux_sandbox_unavailable_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Linux sandbox fault executor fixture")
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
        if isinstance(node, ast.Call):
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


def test_production_sandbox_has_one_explicit_subprocess_boundary_and_no_fallback() -> None:
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
            owner = node.func.value.id
            name = node.func.attr
            if (owner, name) == ("subprocess", "run"):
                subprocess_runs.append(node)
            if (owner, name) in {
                ("subprocess", "Popen"),
                ("os", "system"),
                ("os", "popen"),
            }:
                host_fallbacks.append((owner, name))
        for keyword in node.keywords:
            assert not (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
    assert len(subprocess_runs) == 1
    assert host_fallbacks == []
    assert '"docker", "run"' in source


def test_raw_evidence_contract_retains_digests_not_daemon_output() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert '"stdout_sha256"' in source
    assert '"stderr_sha256"' in source
    assert '"stdout":' not in source
    assert '"stderr":' not in source
    assert "exception message" not in source.lower()


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXECUTOR_PATH))
    forbidden_true = {"trusted", "attested", "gate_closure_claimed"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (
                isinstance(key, ast.Constant)
                and key.value in forbidden_true
                and isinstance(value, ast.Constant)
            ):
                assert value.value is False


def test_missing_socket_path_is_not_retained_in_plaintext() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert '"missing_socket_path_sha256"' in source
    assert '"missing_socket_path"' not in source
    assert "str(missing_socket).encode" in source


def test_control_flow_exceptions_are_not_laundered_into_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "linux" or shutil.which("docker") is None:
        pytest.skip("requires Linux and a readable Docker CLI")

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
    with executor._isolated_docker_environment(missing):
        assert os.environ["DOCKER_HOST"].startswith("unix://")
        assert "DOCKER_CONTEXT" not in os.environ
        assert "DOCKER_TLS_VERIFY" not in os.environ
        assert "DOCKER_CERT_PATH" not in os.environ
    assert {key: os.environ.get(key) for key in original} == original
