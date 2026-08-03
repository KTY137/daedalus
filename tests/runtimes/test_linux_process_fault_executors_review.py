from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "linux_process_fault_executor.py"
REVISION = "a" * 40


def _load_executor_module():
    name = "daedalus_test_linux_process_fault_executor_review"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Linux process fault executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="canonical host process faults require Linux"
)


def _terminated(pid: int) -> bool:
    state = executor._proc_state(pid)
    return state is None or state == "Z"


def _wait_terminated(pids: tuple[int, ...]) -> bool:
    deadline = time.monotonic() + 3.0
    while True:
        if all(_terminated(pid) for pid in pids):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def test_malformed_readiness_cannot_leave_a_live_process_tree(
    tmp_path: Path, monkeypatch
) -> None:
    pid_file = tmp_path / "pids.txt"
    malicious = tmp_path / "malformed_fixture.py"
    malicious.write_text(
        "\n".join(
            (
                "import os, subprocess, sys, time",
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
                f"open({str(pid_file)!r}, 'w', encoding='utf-8').write(f'{{os.getpid()}},{{child.pid}}')",
                "print('{malformed-json', flush=True)",
                "time.sleep(60)",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(executor, "_FIXTURE", malicious)
    row = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.timeout"]
    result = executor._execute_process_fault(row, ignore_sigterm=False)
    assert result.status == "failed"
    assert result.detail_code == "process-fault-invariant"
    pids = tuple(int(value) for value in pid_file.read_text(encoding="utf-8").split(","))
    assert _wait_terminated(pids), f"live process escaped malformed readiness: {pids}"


def test_executor_never_delegates_command_parsing_to_a_shell() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "start_new_session=True" in source
    assert "os.killpg" in source


def test_fault_output_cannot_claim_trust_or_gate_closure_in_source() -> None:
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert '"trusted": False' in source
    assert '"attested": False' in source
    assert '"gate_closure_claimed": False' in source
    assert '"trusted": True' not in source
    assert '"attested": True' not in source
    assert '"gate_closure_claimed": True' not in source


def test_fixture_and_executor_implementation_are_both_digest_bound() -> None:
    first = executor.implementation_sha256()
    original = executor._FIXTURE
    try:
        executor._FIXTURE = EXECUTOR_PATH
        second = executor.implementation_sha256()
    finally:
        executor._FIXTURE = original
    assert first != second
