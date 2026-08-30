# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
EXECUTOR = ROOT / "tests" / "fixtures" / "unknown_outcome_reconciliation_fault_executor.py"
REVISION = "a" * 40
OUTPUT_VALUE = "fe" * 32


def _load():
    name = "daedalus_test_unknown_outcome_fault"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="canonical unknown-outcome crash evidence is Linux-host scoped",
)


def test_real_child_crash_is_reconciled_without_second_external_effect(monkeypatch) -> None:
    monkeypatch.setattr(executor.secrets, "token_hex", lambda size: OUTPUT_VALUE)
    run = executor.run_unknown_outcome(source_revision=REVISION)
    payload = json.loads(run.raw_evidence.decode("utf-8"))

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "unknown-reconciled"
    assert payload["worker_returncode"] == executor._CRASH_RETURN_CODE
    assert payload["worker_stdout_sha256"] == hashlib.sha256(b"").hexdigest()
    assert payload["worker_stderr_sha256"] == hashlib.sha256(b"").hexdigest()
    assert payload["state_after_crash"] == "STARTED"
    assert payload["external_row_count_after_crash"] == 1
    assert payload["external_row_count_after_recovery"] == 1
    assert payload["first_reconciled"] is True
    assert payload["second_reconciled"] is False
    assert payload["terminal_outcome"] == "COMPLETED"
    assert payload["terminal_output_count"] == 1
    assert payload["final_state"] == "COMPLETED"
    assert payload["exact_replay_execute"] is False
    assert OUTPUT_VALUE not in run.raw_evidence.decode("utf-8")


def test_binding_matches_catalog_and_production_sources() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect.unknown-outcome-replay"
    ]
    binding = executor.unknown_outcome_binding(authority_revision=REVISION)
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR.read_bytes()).hexdigest(),
            "recovery_sha256": hashlib.sha256(
                executor._module_path(
                    executor.recovery_module,
                    "effect recovery",
                ).read_bytes()
            ).hexdigest(),
            "effects_sha256": hashlib.sha256(
                executor._module_path(
                    executor.effects_module,
                    "effect ledger",
                ).read_bytes()
            ).hexdigest(),
            "crash_return_code": executor._CRASH_RETURN_CODE,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_scenario_drift_refuses_before_authority_setup(monkeypatch) -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect.unknown-outcome-replay"
    ]
    mutated = dataclasses.replace(scenario, expected_outcome="completed")
    invoked = False

    def authority(**kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("authority must not be constructed")

    monkeypatch.setattr(executor, "_authority", authority)
    with pytest.raises(executor.UnknownOutcomeFaultError, match="expected_outcome"):
        executor.unknown_outcome_binding(
            authority_revision=REVISION
        ).execute(mutated)
    assert invoked is False


def test_published_artifacts_remain_untrusted_and_digest_bound(tmp_path: Path) -> None:
    output = tmp_path / "reports"
    summary = executor.publish_unknown_outcome(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "unknown-reconciled"
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
        pytest.skip("symlink creation unavailable")
    with pytest.raises(executor.UnknownOutcomeFaultError, match="must not be a symlink"):
        executor.publish_unknown_outcome(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_crash_worker_refuses_incomplete_arguments(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(EXECUTOR), "--crash-worker"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        timeout=10,
    )
    assert completed.returncode != 0
    assert "arguments are incomplete" in completed.stderr
