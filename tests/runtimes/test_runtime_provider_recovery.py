from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import daedalus.runtimes.recovery as recovery_module
from daedalus.kernel.effect_recovery import issue_external_effect_observation
from daedalus.runtimes.recovery import (
    RuntimeProviderRecoveryBindingError,
    reconcile_runtime_provider_unknown,
)


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
PROVIDER_ID = "provider.external-runtime-fixture"
OBSERVATION_KEY = b"runtime-recovery-observation-key-material-at-least-32-bytes"
ACKNOWLEDGEMENT_SHA = "7" * 64
OUTPUT_SHA = "8" * 64
REVISION = "1" * 40


def _load_authority_fixture():
    name = "daedalus_test_runtime_recovery_authority_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: fixture.NOW,
    )
    execution = fixture._execution()
    authorization.grant()
    start = authorization.begin_effect(execution)
    assert start.execute is True
    observation = issue_external_effect_observation(
        observation_id="runtime-recovery-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=start.receipt,
        acknowledgement_sha256=ACKNOWLEDGEMENT_SHA,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id="runtime-recovery-observation-key",
        issuer_secret=OBSERVATION_KEY,
        source_revision=REVISION,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    return authorization, execution, start.receipt, observation


def _recover(
    authorization,
    execution,
    start_receipt,
    observation,
    *,
    entrypoint_id: str | None = None,
    source_revision: str = REVISION,
):
    return reconcile_runtime_provider_unknown(
        entrypoint_id or fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        start_receipt=start_receipt,
        observation=observation,
        observation_keyring={"runtime-recovery-observation-key": OBSERVATION_KEY},
        expected_provider_id=PROVIDER_ID,
        expected_source_revision=source_revision,
        reconciled_at=fixture.NOW + timedelta(seconds=2),
    )


def test_runtime_bound_adapter_reconciles_exact_started_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation = _started(tmp_path, monkeypatch)
    result = _recover(authorization, execution, start, observation)
    assert result.reconciled is True
    assert result.terminal_receipt.execution_id == execution.execution_id
    assert result.terminal_receipt.lease_sha256 == authorization.capability.lease.digest
    assert result.terminal_receipt.output_digests == (OUTPUT_SHA,)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"


@pytest.mark.parametrize(
    "dimension",
    ["lease_sha256", "execution_id", "idempotency_key", "execution_request_sha256"],
)
def test_foreign_start_or_execution_binding_refuses_before_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dimension: str,
) -> None:
    authorization, execution, start, observation = _started(tmp_path, monkeypatch)
    if dimension == "lease_sha256":
        changed_start = dataclasses.replace(start, lease_sha256="9" * 64)
        changed_execution = execution
    elif dimension == "execution_id":
        changed_start = start
        changed_execution = dataclasses.replace(execution, execution_id="foreign-execution")
    elif dimension == "idempotency_key":
        changed_start = start
        changed_execution = dataclasses.replace(
            execution,
            idempotency_key="foreign-idempotency",
        )
    else:
        changed_start = dataclasses.replace(
            start,
            execution_request_sha256="a" * 64,
        )
        changed_execution = execution

    delegated = {"value": False}

    def forbidden(*args, **kwargs):
        delegated["value"] = True
        raise AssertionError("generic reconciliation ran after foreign runtime binding")

    monkeypatch.setattr(recovery_module, "reconcile_unknown_effect", forbidden)
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="binding mismatch"):
        _recover(
            authorization,
            changed_execution,
            changed_start,
            observation,
        )
    assert delegated["value"] is False
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_foreign_runtime_registry_refuses_before_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation = _started(tmp_path, monkeypatch)
    entrypoint_id = fixture._request().entrypoint_id
    spec = authorization.registry[entrypoint_id]
    foreign = dataclasses.replace(
        authorization,
        registry={entrypoint_id: dataclasses.replace(spec, runtime_id="foreign-runtime")},
    )
    delegated = {"value": False}

    def forbidden(*args, **kwargs):
        delegated["value"] = True
        raise AssertionError("generic reconciliation ran after runtime substitution")

    monkeypatch.setattr(recovery_module, "reconcile_unknown_effect", forbidden)
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="spec_runtime"):
        _recover(foreign, execution, start, observation)
    assert delegated["value"] is False
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_forged_runtime_capability_and_wrong_revision_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation = _started(tmp_path, monkeypatch)
    forged = dataclasses.replace(
        authorization,
        capability=dataclasses.replace(
            authorization.capability,
            signature_sha256="0" * 64,
        ),
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="authentication"):
        _recover(forged, execution, start, observation)
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="source_revision"):
        _recover(
            authorization,
            execution,
            start,
            observation,
            source_revision="2" * 40,
        )
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_foreign_entrypoint_refuses_without_recovery_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation = _started(tmp_path, monkeypatch)
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="absent"):
        _recover(
            authorization,
            execution,
            start,
            observation,
            entrypoint_id="provider.foreign-runtime",
        )
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"
