from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import LinuxHostFaultEvidence
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
REVISION = "a" * 40
PROVIDER_OUTPUT = "fe" * 32


def _load():
    name = "daedalus_test_runtime_trust_contention_fault_v2"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load()
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="canonical contention evidence is Linux-host scoped",
)


def test_real_terminal_fence_contention_cancels_and_replay_is_inert(monkeypatch) -> None:
    monkeypatch.setattr(executor.secrets, "token_hex", lambda size: PROVIDER_OUTPUT)
    run = executor.run_runtime_trust_contention(source_revision=REVISION)
    payload = json.loads(run.raw_evidence.decode("utf-8"))

    assert run.observation.status == "passed"
    assert run.observation.observed_outcome == "cancelled"
    assert payload["plain_verify_calls"] == 2
    assert payload["writer_lock_held"] is True
    assert payload["contention_observed"] is True
    assert payload["exception_type"] == "RuntimeProviderTrustFenceError"
    assert payload["cause_type"] == "OperationalError"
    assert payload["provider_called"] is True
    assert payload["output_digest_called"] is True
    assert payload["result_released"] is False
    assert payload["terminal_state"] == "CANCELLED"
    assert payload["terminal_outcome"] == "CANCELLED"
    assert payload["terminal_output_count"] == 0
    assert payload["terminal_detail_present"] is True
    assert payload["trust_record_still_active"] is True
    assert payload["replay_inert"] is True
    assert PROVIDER_OUTPUT not in run.raw_evidence.decode("utf-8")
    assert payload["elapsed_ms"] >= (
        executor._BUSY_TIMEOUT_MS - executor._TIMEOUT_TOLERANCE_MS
    )
    assert payload["elapsed_ms"] < 5_000


def test_binding_is_catalog_exact_and_binds_production_sources() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.trust-ledger.lock-contention"
    ]
    binding = executor.runtime_trust_contention_binding(
        authority_revision=REVISION
    )
    expected = canonical_sha(
        {
            "schema": executor._REPORT_SCHEMA,
            "executor_sha256": hashlib.sha256(EXECUTOR.read_bytes()).hexdigest(),
            "broker_sha256": hashlib.sha256(
                executor._module_path(executor.broker_module, "broker").read_bytes()
            ).hexdigest(),
            "trust_store_sha256": hashlib.sha256(
                executor._module_path(
                    executor.trust_store_module, "trust store"
                ).read_bytes()
            ).hexdigest(),
            "runtime_effects_sha256": hashlib.sha256(
                executor._module_path(
                    executor.runtime_effects_module, "runtime effects"
                ).read_bytes()
            ).hexdigest(),
            "effect_ledger_sha256": hashlib.sha256(
                executor._module_path(
                    executor.effects_module, "effect ledger"
                ).read_bytes()
            ).hexdigest(),
            "provider_observation_sha256": hashlib.sha256(
                executor._module_path(
                    executor.provider_observation_module, "provider observation"
                ).read_bytes()
            ).hexdigest(),
            "busy_timeout_ms": executor._BUSY_TIMEOUT_MS,
            "timeout_tolerance_ms": executor._TIMEOUT_TOLERANCE_MS,
        }
    )
    assert binding.locator == scenario.executor
    assert binding.implementation_sha256 == expected
    assert executor.implementation_sha256() == expected


def test_scenario_drift_refuses_before_effect_setup(monkeypatch) -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.trust-ledger.lock-contention"
    ]
    mutated = dataclasses.replace(scenario, invariant="candidate replacement")
    invoked = False

    def authority(**kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("authority must not be built")

    monkeypatch.setattr(executor, "_authority", authority)
    with pytest.raises(executor.RuntimeTrustContentionFaultError, match="scenario_sha256"):
        executor.runtime_trust_contention_binding(
            authority_revision=REVISION
        ).execute(mutated)
    assert invoked is False


def test_extended_busy_and_locked_codes_classify_without_message_dependency() -> None:
    class Fault:
        def __init__(self, code: int) -> None:
            self.sqlite_errorcode = code

        def __str__(self) -> str:
            return "redacted"

    for base in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        assert executor._is_contention(Fault(base | (3 << 8))) is True
    assert executor._is_contention(Fault(sqlite3.SQLITE_CONSTRAINT)) is False


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
        pytest.skip("symlink creation unavailable")
    with pytest.raises(
        executor.RuntimeTrustContentionFaultError,
        match="must not be a symlink",
    ):
        executor.publish_runtime_trust_contention(
            source_revision=REVISION,
            output_dir=linked,
        )
    assert list(real.iterdir()) == []


def test_cli_emits_only_untrusted_material(tmp_path: Path) -> None:
    output = tmp_path / "cli"
    completed = subprocess.run(
        [
            sys.executable,
            str(EXECUTOR),
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
    assert summary["trusted"] is False
    assert summary["attested"] is False
    assert summary["gate_closure_claimed"] is False
