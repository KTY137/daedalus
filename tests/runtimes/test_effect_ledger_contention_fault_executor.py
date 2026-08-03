from __future__ import annotations

import dataclasses
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
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "effect_ledger_contention_fault_executor.py"
REVISION = "a" * 40


def _load_executor_module():
    name = "daedalus_test_effect_ledger_contention_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load effect-ledger contention fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="canonical ledger contention fault is Linux-host evidence"
)


def test_real_writer_contention_refuses_before_effect_start() -> None:
    run = executor.run_effect_contention(source_revision=REVISION)
    payload = json.loads(run.raw_evidence.decode("utf-8"))

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "refused-before-start"
    assert run.observation.detail_code is None
    assert payload["writer_lock_held"] is True
    assert payload["contention_observed"] is True
    assert payload["provider_called"] is False
    assert payload["execution_row_count"] == 0
    assert payload["busy_timeout_ms"] == executor._BUSY_TIMEOUT_MS
    assert payload["elapsed_ms"] >= (
        executor._BUSY_TIMEOUT_MS - executor._TIMEOUT_TOLERANCE_MS
    )
    assert payload["elapsed_ms"] < 5_000
    assert payload["exception_type"] == "OperationalError"
    assert "database_path" not in payload
    assert "exception_message" not in payload
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_binding_is_exact_to_catalog_executor_and_effect_ledger_bytes() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    binding = executor.effect_contention_binding()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "effect_ledger_sha256": hashlib.sha256(
                executor._effects_source_path().read_bytes()
            ).hexdigest(),
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_mutated_scenario_refuses_before_opening_a_ledger() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    mutated = dataclasses.replace(
        scenario,
        invariant="candidate-controlled replacement invariant",
    )
    with pytest.raises(
        executor.EffectLedgerContentionFaultError,
        match="scenario_sha256",
    ):
        executor.effect_contention_binding().execute(mutated)


def test_unrecognized_operational_error_cannot_be_laundered_as_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor, "_is_lock_contention", lambda exc: False)

    run = executor.run_effect_contention(source_revision=REVISION)

    assert run.observation.status == "failed"
    assert run.observation.detail_code == "effect-ledger-contention-invariant"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["writer_lock_held"] is True
    assert payload["provider_called"] is False
    assert payload["execution_row_count"] == 0


def test_published_material_is_untrusted_and_digest_bound(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_effect_contention(
        source_revision=REVISION,
        output_dir=output,
    )

    assert summary["status"] == "passed"
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


def test_output_directory_symlink_refuses(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(
        executor.EffectLedgerContentionFaultError,
        match="must not be a symlink",
    ):
        executor.publish_effect_contention(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


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
        timeout=10,
    )
    summary = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert summary["status"] == "passed"
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
