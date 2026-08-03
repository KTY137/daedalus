from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "linux_effect_ledger_lock_fault_executor.py"
REVISION = "a" * 40


def _load_executor_module():
    name = "daedalus_test_linux_effect_ledger_lock_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Effect-Ledger lock fault executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="canonical SQLite host contention fault requires Linux"
)


def _payload(run):
    return json.loads(run.raw_evidence.decode("utf-8"))


def test_real_writer_contention_refuses_before_effect_start() -> None:
    run = executor.run_effect_lock_fault(source_revision=REVISION)
    payload = _payload(run)

    assert run.observation.scenario_id == "runtime.effect-ledger.lock-contention"
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"
    assert payload["lock_refused"] is True
    assert payload["execution_rows_while_locked"] == 0
    assert payload["persisted_execution_state"] is None
    assert payload["provider_marker_exists"] is False
    assert payload["error_type"] == "OperationalError"
    assert payload["busy_timeout_ms"] == executor._BUSY_TIMEOUT_MS
    assert payload["scenario_sha256"] == RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ].digest
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_binding_is_exactly_catalog_bound_and_covers_production_effects_module() -> None:
    binding = executor.effect_lock_binding()
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    payload = {
        "schema": executor._REPORT_SCHEMA,
        "executor_sha256": executor._file_sha256(EXECUTOR_PATH),
        "production_effects_sha256": executor._file_sha256(
            Path(executor.effects_module.__file__).resolve()
        ),
        "busy_timeout_ms": executor._BUSY_TIMEOUT_MS,
    }
    from daedalus.spine.envelope import canonical_sha

    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == canonical_sha(payload)
    assert binding.implementation_sha256 == executor.implementation_sha256()


def test_published_artifacts_are_untrusted_and_self_consistent(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_effect_lock_fault(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
    assert summary["run"]["status"] == "passed"

    persisted = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert persisted == summary
    prefix = summary["run"]["scenario_id"]
    evidence = LinuxHostFaultEvidence.from_dict(
        json.loads((output / f"{prefix}.evidence.json").read_text(encoding="utf-8"))
    )
    observation = json.loads(
        (output / f"{prefix}.observation.json").read_text(encoding="utf-8")
    )
    raw = (output / f"{prefix}.raw").read_bytes()
    assert evidence.digest == summary["run"]["evidence_sha256"]
    assert observation["evidence_sha256"] == evidence.digest
    assert hashlib.sha256(raw).hexdigest() == evidence.raw_evidence_sha256


def test_output_directory_symlink_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(
        executor.LinuxEffectLedgerLockFaultError,
        match="must not be a symlink",
    ):
        executor.publish_effect_lock_fault(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_stale_or_malformed_revision_is_refused_before_executor_call(monkeypatch) -> None:
    called = False

    def forbidden(_scenario):
        nonlocal called
        called = True
        raise AssertionError("executor must not run")

    binding = executor.effect_lock_binding()
    monkeypatch.setattr(binding, "execute", forbidden, raising=False)
    with pytest.raises(ValueError, match="revision"):
        executor.run_effect_lock_fault(source_revision="not-a-revision")
    assert called is False


def test_cli_emits_only_untrusted_lock_fault_artifacts(tmp_path: Path) -> None:
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
    assert stdout["run"]["status"] == "passed"
