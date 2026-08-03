from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "linux_effect_ledger_lock_fault_executor.py"
SOURCE = EXECUTOR_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _load_executor_module():
    name = "daedalus_review_linux_effect_ledger_lock_fault_executor"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Effect-Ledger lock fault executor fixture")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor_module()


def test_fixture_is_not_a_second_process_or_shell_boundary() -> None:
    imported_modules = {
        alias.name
        for node in TREE.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in TREE.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "subprocess" not in imported_modules
    assert "subprocess" not in imported_from
    assert "os.system" not in SOURCE
    assert "shell=True" not in SOURCE


def test_provider_marker_can_only_follow_a_successful_persisted_start() -> None:
    begin_index = SOURCE.index("start = ledger.begin(")
    execute_index = SOURCE.index("if start.execute:")
    marker_index = SOURCE.index('marker.write_text("provider callback executed')
    assert begin_index < execute_index < marker_index
    assert "marker.write_text" not in SOURCE[:begin_index]


def test_raw_evidence_does_not_retain_database_paths_or_exception_messages() -> None:
    forbidden_keys = {
        "database_path",
        "temporary_directory",
        "exception_message",
        "sqlite_message",
    }
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    if sys.platform == "linux":
        result = executor._execute_effect_lock_fault(scenario)
        payload = json.loads(result.raw_evidence.decode("utf-8"))
        assert forbidden_keys.isdisjoint(payload)
        assert all("daedalus-effect-lock-" not in str(value) for value in payload.values())


def test_executor_identity_covers_fixture_production_boundary_and_timeout() -> None:
    assert '"executor_sha256"' in SOURCE
    assert '"production_effects_sha256"' in SOURCE
    assert '"busy_timeout_ms"' in SOURCE
    assert executor._BUSY_TIMEOUT_MS > 0
    assert executor._BUSY_TIMEOUT_MS <= 1000
    assert len(executor.implementation_sha256()) == 64


def test_source_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE


@pytest.mark.skipif(sys.platform != "linux", reason="mutation requires Linux SQLite")
def test_mutation_returning_execute_true_is_killed_by_provider_marker_invariant(monkeypatch) -> None:
    def bypass_begin(*_args, **_kwargs):
        return SimpleNamespace(execute=True)

    monkeypatch.setattr(executor._ShortBusyEffectLeaseLedger, "begin", bypass_begin)
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    result = executor._execute_effect_lock_fault(scenario)
    payload = json.loads(result.raw_evidence.decode("utf-8"))
    assert result.status == "failed"
    assert result.detail_code == "effect-lock-invariant"
    assert payload["provider_marker_exists"] is True


@pytest.mark.skipif(sys.platform != "linux", reason="mutation requires Linux SQLite")
def test_mutation_laundering_a_started_row_is_killed(monkeypatch) -> None:
    def locked_begin(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(executor._ShortBusyEffectLeaseLedger, "begin", locked_begin)
    monkeypatch.setattr(
        executor._ShortBusyEffectLeaseLedger,
        "execution_state",
        lambda *_args, **_kwargs: "STARTED",
    )
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    result = executor._execute_effect_lock_fault(scenario)
    payload = json.loads(result.raw_evidence.decode("utf-8"))
    assert result.status == "failed"
    assert payload["persisted_execution_state"] == "STARTED"


def test_fixture_does_not_change_the_canonical_fault_requirement() -> None:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[
        "runtime.effect-ledger.lock-contention"
    ]
    assert scenario.authority == "linux-host"
    assert scenario.boundary == "effect-ledger"
    assert scenario.expected_outcome == "refused-before-start"
    assert scenario.executor == "host-fixture:runtime-effect-lock-contention"
