from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.broker import RuntimeProviderTrustFenceError
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = (
    ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
)
REVISION = "b" * 40


def _load_executor_module():
    name = "daedalus_test_runtime_trust_contention_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime-trust contention fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()


def test_binding_is_catalog_exact_and_covers_broker_store_and_timeout() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.runtime-trust.lock-contention"
    ]
    binding = executor.runtime_trust_contention_binding()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "broker_sha256": executor._module_source_sha256(
                executor.broker_module, "production runtime broker"
            ),
            "trust_store_sha256": executor._module_source_sha256(
                executor.trust_store_module, "production runtime trust store"
            ),
            "busy_timeout_ms": executor._BUSY_TIMEOUT_MS,
            "min_elapsed_ms": executor._MIN_ELAPSED_MS,
            "max_elapsed_ms": executor._MAX_ELAPSED_MS,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_recombined_or_mutated_scenario_refuses_before_execution() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.runtime-trust.lock-contention"
    ]
    mutated = dataclasses.replace(
        scenario,
        expected_outcome="failed",
    )
    with pytest.raises(
        executor.RuntimeTrustContentionFaultError,
        match="expected_outcome",
    ):
        executor.runtime_trust_contention_binding().execute(mutated)


def test_legacy_sqlite_operational_error_is_classified_without_new_attributes() -> None:
    error = sqlite3.OperationalError("database is locked")
    assert executor._sqlite_base_code(error) in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }


def test_exact_real_writer_contention_cancels_and_withholds_output(monkeypatch) -> None:
    monkeypatch.setattr(executor.sys, "platform", "linux")

    run = executor.run_runtime_trust_contention(source_revision=REVISION)

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "cancelled"
    assert run.observation.detail_code is None
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["writer_active_before_release"] is True
    assert payload["provider_invoked"] is True
    assert payload["output_evidence_built"] is True
    assert payload["provider_value_returned"] is False
    assert payload["exception_module"] == RuntimeProviderTrustFenceError.__module__
    assert payload["exception_type"] == RuntimeProviderTrustFenceError.__qualname__
    assert payload["cause_module"] == sqlite3.OperationalError.__module__
    assert payload["cause_type"] == sqlite3.OperationalError.__qualname__
    assert payload["sqlite_base_code"] in {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_LOCKED,
    }
    assert executor._MIN_ELAPSED_MS <= payload["elapsed_ms"] < executor._MAX_ELAPSED_MS
    assert payload["verify_calls"] == 2
    assert payload["terminal_rows"] == [
        {
            "outcome": "cancelled",
            "output_digest_count": 0,
            "detail_present": True,
            "receipt_sha256": payload["terminal_rows"][0]["receipt_sha256"],
        }
    ]
    assert len(payload["terminal_rows"][0]["receipt_sha256"]) == 64
    assert payload["durable_state"] == "ACTIVE"
    assert len(payload["durable_record_sha256"]) == 64
    assert payload["trusted"] is False
    assert payload["attested"] is False
    assert payload["gate_closure_claimed"] is False
    assert "output-must-be-withheld" not in run.raw_evidence.decode("utf-8")
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_non_linux_is_blocked_not_passed(monkeypatch) -> None:
    monkeypatch.setattr(executor.sys, "platform", "win32")
    run = executor.run_runtime_trust_contention(source_revision=REVISION)
    assert run.observation.status == "blocked"
    assert run.observation.observed_outcome is None
    assert run.observation.detail_code == "linux-required"


def test_published_files_remain_explicitly_untrusted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(executor.sys, "platform", "linux")
    output = tmp_path / "reports"
    summary = executor.publish_runtime_trust_contention(
        source_revision=REVISION,
        output_dir=output,
    )
    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "cancelled"
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
    assert b"output-must-be-withheld" not in raw


def test_output_directory_symlink_refuses_without_writing(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(
        executor.RuntimeTrustContentionFaultError,
        match="must not be a symlink",
    ):
        executor.publish_runtime_trust_contention(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_executor_identity_changes_with_broker_or_store_source() -> None:
    first = executor.implementation_sha256()
    original = executor._module_source_sha256
    try:
        executor._module_source_sha256 = lambda module, label: "f" * 64
        second = executor.implementation_sha256()
    finally:
        executor._module_source_sha256 = original
    assert first != second


@pytest.mark.skipif(
    os.environ.get("DAEDALUS_RUN_REAL_RUNTIME_TRUST_CONTENTION") != "1",
    reason="real contention execution is retained by the dedicated Linux job",
)
def test_retained_runtime_trust_contention_is_exact_pass() -> None:
    run = executor.run_runtime_trust_contention(source_revision=REVISION)
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "cancelled"
