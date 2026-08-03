from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "linux_process_fault_executor.py"
REVISION = "a" * 40


def _load_executor_module():
    name = "daedalus_test_linux_process_fault_executor"
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


def _payload(run):
    return json.loads(run.raw_evidence.decode("utf-8"))


def test_real_timeout_and_ignored_sigterm_faults_terminate_the_process_tree() -> None:
    runs = executor.run_process_faults(source_revision=REVISION)
    assert tuple(run.observation.scenario_id for run in runs) == (
        "runtime.process.timeout",
        "runtime.process.ignored-sigterm",
    )
    assert all(run.observation.status == "passed" for run in runs)
    assert all(run.observation.observed_outcome == "cancelled" for run in runs)

    timeout, ignored = map(_payload, runs)
    assert timeout["timed_out"] is True
    assert timeout["sent_sigterm"] is True
    assert timeout["escalated_sigkill"] is False
    assert timeout["returncode"] == -15
    assert timeout["live_group_members"] == []

    assert ignored["timed_out"] is True
    assert ignored["sent_sigterm"] is True
    assert ignored["escalated_sigkill"] is True
    assert ignored["returncode"] == -9
    assert ignored["live_group_members"] == []

    for run, payload in zip(runs, (timeout, ignored), strict=True):
        metadata = payload["metadata"]
        assert metadata["parent_pid"] == metadata["process_group_id"]
        assert len(metadata["child_pids"]) == 1
        assert payload["scenario_sha256"] == RUNTIME_FAULT_CATALOG.scenario_map[
            run.observation.scenario_id
        ].digest
        assert hashlib.sha256(run.raw_evidence).hexdigest() == (
            run.evidence.raw_evidence_sha256
        )


def test_executor_bindings_are_exactly_catalog_bound_and_content_addressed() -> None:
    bindings = executor.process_fault_bindings()
    scenarios = tuple(
        RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]
        for scenario_id in (
            "runtime.process.timeout",
            "runtime.process.ignored-sigterm",
        )
    )
    assert set(bindings) == {row.executor for row in scenarios}
    implementation = executor.implementation_sha256()
    assert len(implementation) == 64
    assert all(
        bindings[row.executor].locator == row.executor
        and bindings[row.executor].implementation_sha256 == implementation
        for row in scenarios
    )


def test_published_artifacts_are_untrusted_and_self_consistent(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_process_faults(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    assert len(summary["runs"]) == 2

    persisted_summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert persisted_summary == summary
    for row in summary["runs"]:
        prefix = row["scenario_id"]
        evidence = LinuxHostFaultEvidence.from_dict(
            json.loads((output / f"{prefix}.evidence.json").read_text(encoding="utf-8"))
        )
        observation = json.loads(
            (output / f"{prefix}.observation.json").read_text(encoding="utf-8")
        )
        raw = (output / f"{prefix}.raw").read_bytes()
        assert evidence.digest == row["evidence_sha256"]
        assert observation["evidence_sha256"] == evidence.digest
        assert hashlib.sha256(raw).hexdigest() == evidence.raw_evidence_sha256


def test_output_directory_symlink_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(executor.LinuxProcessFaultError, match="must not be a symlink"):
        executor.publish_process_faults(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_readiness_parser_rejects_duplicate_and_foreign_fields() -> None:
    duplicate = (
        '{"schema":"daedalus-linux-process-tree-fixture/1",'
        '"schema":"daedalus-linux-process-tree-fixture/1",'
        '"parent_pid":123,"process_group_id":123,"child_pids":[124],'
        '"ignore_sigterm":false}'
    )
    with pytest.raises(executor.LinuxProcessFaultError, match="duplicate readiness key"):
        executor._strict_readiness(duplicate, process_pid=123, ignore_sigterm=False)

    foreign = (
        '{"schema":"daedalus-linux-process-tree-fixture/1",'
        '"parent_pid":123,"process_group_id":123,"child_pids":[124],'
        '"ignore_sigterm":false,"trusted":true}'
    )
    with pytest.raises(executor.LinuxProcessFaultError, match="fields"):
        executor._strict_readiness(foreign, process_pid=123, ignore_sigterm=False)


def test_cli_emits_only_untrusted_process_fault_artifacts(tmp_path: Path) -> None:
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
    assert stdout["trusted"] is False
    assert stdout["attested"] is False
    assert stdout["gate_closure_claimed"] is False
    assert all(row["status"] == "passed" for row in stdout["runs"])
