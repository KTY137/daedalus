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
EXECUTOR_PATH = (
    ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
)
REVISION = "a" * 40
PROVIDER_OUTPUT = "fe" * 32


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
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="canonical runtime-trust contention fault is Linux-host evidence",
)


def test_real_writer_contention_withholds_provider_output_and_cancels() -> None:
    original = executor.secrets.token_hex
    try:
        executor.secrets.token_hex = lambda size: PROVIDER_OUTPUT
        run = executor.run_runtime_trust_contention(source_revision=REVISION)
    finally:
        executor.secrets.token_hex = original

    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "cancelled"
    assert run.observation.detail_code is None
    assert payload["writer_lock_held"] is True
    assert payload["contention_observed"] is True
    assert payload["provider_called"] is True
    assert payload["output_digest_called"] is False
    assert payload["result_released"] is False
    assert payload["terminal_state"] == "CANCELLED"
    assert payload["terminal_outcome"] == "CANCELLED"
    assert payload["terminal_output_count"] == 0
    assert payload["terminal_detail_present"] is True
    assert payload["trust_record_still_active"] is True
    assert payload["elapsed_ms"] >= (
        executor._BUSY_TIMEOUT_MS - executor._TIMEOUT_TOLERANCE_MS
    )
    assert payload["elapsed_ms"] < 5_000
    assert PROVIDER_OUTPUT not in run.raw_evidence.decode("utf-8")
    assert "exception_message" not in payload
    assert "database_path" not in payload
    assert hashlib.sha256(run.raw_evidence).hexdigest() == run.evidence.raw_evidence_sha256


def test_binding_is_exact_to_catalog_and_all_production_boundary_bytes() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.trust-ledger.lock-contention"
    ]
    binding = executor.runtime_trust_contention_binding()
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest(),
            "broker_sha256": hashlib.sha256(
                executor._module_source_path(
                    executor.broker_module,
                    "production runtime broker",
                ).read_bytes()
            ).hexdigest(),
            "trust_store_sha256": hashlib.sha256(
                executor._module_source_path(
                    executor.trust_store_module,
                    "production runtime trust ledger",
                ).read_bytes()
            ).hexdigest(),
            "runtime_effects_sha256": hashlib.sha256(
                executor._module_source_path(
                    executor.runtime_effects_module,
                    "runtime effect authority",
                ).read_bytes()
            ).hexdigest(),
            "effect_ledger_sha256": hashlib.sha256(
                executor._module_source_path(
                    executor.effects_module,
                    "production effect ledger",
                ).read_bytes()
            ).hexdigest(),
            "busy_timeout_ms": executor._BUSY_TIMEOUT_MS,
            "timeout_tolerance_ms": executor._TIMEOUT_TOLERANCE_MS,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_mutated_scenario_refuses_before_authority_setup() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.trust-ledger.lock-contention"
    ]
    mutated = dataclasses.replace(
        scenario,
        invariant="candidate-controlled replacement invariant",
    )
    original = executor._authority
    invoked = False

    def authority(**kwargs):
        nonlocal invoked
        invoked = True
        return original(**kwargs)

    executor._authority = authority
    try:
        with pytest.raises(
            executor.RuntimeTrustContentionFaultError,
            match="scenario_sha256",
        ):
            executor.runtime_trust_contention_binding().execute(mutated)
    finally:
        executor._authority = original
    assert invoked is False


def test_unrecognized_operational_error_cannot_be_laundered_as_contention() -> None:
    original = executor._is_lock_contention
    try:
        executor._is_lock_contention = lambda exc: False
        run = executor.run_runtime_trust_contention(source_revision=REVISION)
    finally:
        executor._is_lock_contention = original
    assert run.observation.status == "failed"
    assert run.observation.detail_code == "runtime-trust-contention-invariant"
    payload = json.loads(run.raw_evidence.decode("utf-8"))
    assert payload["provider_called"] is True
    assert payload["result_released"] is False
    assert payload["terminal_state"] == "CANCELLED"


def test_extended_sqlite_busy_and_locked_codes_are_classified() -> None:
    class Fault:
        def __init__(self, code: int) -> None:
            self.sqlite_errorcode = code

        def __str__(self) -> str:
            return "redacted"

    for base in (executor.sqlite3.SQLITE_BUSY, executor.sqlite3.SQLITE_LOCKED):
        assert executor._is_lock_contention(Fault(base | (3 << 8))) is True
    assert executor._is_lock_contention(Fault(executor.sqlite3.SQLITE_CONSTRAINT)) is False


def test_published_material_is_untrusted_and_digest_bound(tmp_path: Path) -> None:
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


def test_output_directory_symlink_refuses(tmp_path: Path) -> None:
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
        timeout=15,
    )
    summary = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert summary["status"] == "passed"
    assert summary["observed_outcome"] == "cancelled"
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False


def test_implementation_identity_changes_with_each_production_boundary() -> None:
    first = executor.implementation_sha256()
    original = executor._module_source_path
    try:
        executor._module_source_path = lambda module, label: EXECUTOR_PATH
        second = executor.implementation_sha256()
    finally:
        executor._module_source_path = original
    assert first != second
