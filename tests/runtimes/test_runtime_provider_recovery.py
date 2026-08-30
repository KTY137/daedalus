from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import daedalus.runtimes.recovery as recovery_module
from daedalus.kernel.effect_recovery import (
    EffectRecoverySignatureError,
    issue_external_effect_observation,
)
from daedalus.runtimes.broker import (
    RuntimeProviderReconciliationRequired,
    _run_runtime_provider_test_double as run_runtime_provider,
)
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.runtimes.recovery import (
    RuntimeProviderRecoveryBindingError,
    reconcile_runtime_provider_unknown,
)


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
PROVIDER_ID = "provider.external-runtime-fixture"
OBSERVATION_KEY_ID = "runtime-recovery-observation-key"
OBSERVATION_KEY = b"runtime-recovery-observation-key-material-at-least-32-bytes"
AUTHORITY_KEY_ID = "runtime-recovery-authority-key"
AUTHORITY_KEY = b"runtime-recovery-authority-key-material-at-least-32-bytes"
RECORD_KEY = b"runtime-recovery-record-key-material-at-least-32-bytes"
ACKNOWLEDGEMENT_SHA = "7" * 64
OUTPUT_SHA = "8" * 64


def _load_authority_fixture():
    name = "daedalus_test_runtime_recovery_authority_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _ledger(
    tmp_path: Path,
    *,
    path_name: str = "provider-observation.sqlite3",
    observation_key_id: str = OBSERVATION_KEY_ID,
    observation_key: bytes = OBSERVATION_KEY,
    record_key: bytes = RECORD_KEY,
) -> ProviderObservationBindingLedger:
    return ProviderObservationBindingLedger(
        tmp_path / path_name,
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={observation_key_id: observation_key},
        record_secret=record_key,
    )


def _authority(authorization, execution, *, provider_id: str = PROVIDER_ID):
    return issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="runtime-recovery-provider-binding",
        provider_id=provider_id,
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=fixture._request().entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )


def _started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: fixture.NOW,
    )
    monkeypatch.setattr(
        "daedalus.runtimes.broker._utc_now",
        lambda: fixture.NOW,
    )
    execution = fixture._execution()
    ledger = _ledger(tmp_path)
    authority = _authority(authorization, execution)
    with pytest.raises(RuntimeProviderReconciliationRequired) as captured:
        run_runtime_provider(
            fixture._request().entrypoint_id,
            authorization=authorization,
            execution=execution,
            invoke=lambda: "provider-output",
            output_digests=lambda value: (_ for _ in ()).throw(
                RuntimeError("local evidence failure")
            ),
            observation_authority=authority,
            observation_binding_ledger=ledger,
        )
    start = captured.value.start_receipt
    observation = issue_external_effect_observation(
        observation_id="runtime-recovery-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=start,
        acknowledgement_sha256=ACKNOWLEDGEMENT_SHA,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id=OBSERVATION_KEY_ID,
        issuer_secret=OBSERVATION_KEY,
        source_revision=authorization.capability.source_revision,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    return authorization, execution, start, observation, ledger, authority


def _recover(
    authorization,
    execution,
    start_receipt,
    observation,
    ledger,
    *,
    entrypoint_id: str | None = None,
):
    return reconcile_runtime_provider_unknown(
        entrypoint_id or fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        start_receipt=start_receipt,
        observation=observation,
        observation_binding_ledger=ledger,
        reconciled_at=fixture.NOW + timedelta(seconds=2),
    )


def test_runtime_bound_adapter_derives_retained_provider_and_reconciles_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation, ledger, authority = _started(
        tmp_path,
        monkeypatch,
    )
    retained = ledger.load(execution.execution_id)
    assert retained is not None
    assert retained.authority == authority
    result = _recover(authorization, execution, start, observation, ledger)
    assert result.reconciled is True
    assert result.terminal_receipt.execution_id == execution.execution_id
    assert result.terminal_receipt.lease_sha256 == authorization.capability.lease.digest
    assert result.terminal_receipt.output_digests == (OUTPUT_SHA,)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="already terminal"):
        _recover(authorization, execution, start, observation, ledger)


@pytest.mark.parametrize(
    "dimension",
    ["lease_sha256", "execution_id", "idempotency_key", "execution_request_sha256"],
)
def test_foreign_start_or_execution_binding_refuses_before_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dimension: str,
) -> None:
    authorization, execution, start, observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
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
            ledger,
        )
    assert delegated["value"] is False
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_provider_and_issuer_identity_are_derived_from_retained_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
    foreign_provider = issue_external_effect_observation(
        observation_id="foreign-provider-observation",
        provider_id="provider.foreign-runtime",
        execution=execution,
        start_receipt=start,
        acknowledgement_sha256=ACKNOWLEDGEMENT_SHA,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id=OBSERVATION_KEY_ID,
        issuer_secret=OBSERVATION_KEY,
        source_revision=authorization.capability.source_revision,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="provider differs"):
        _recover(authorization, execution, start, foreign_provider, ledger)

    foreign_key = b"foreign-observation-key-material-at-least-32-bytes"
    foreign_issuer = issue_external_effect_observation(
        observation_id="foreign-issuer-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=start,
        acknowledgement_sha256=ACKNOWLEDGEMENT_SHA,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id="foreign-observation-key",
        issuer_secret=foreign_key,
        source_revision=authorization.capability.source_revision,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="issuer is not retained"):
        _recover(authorization, execution, start, foreign_issuer, ledger)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_same_issuer_with_wrong_key_material_fails_signature_without_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, _observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
    forged = issue_external_effect_observation(
        observation_id="forged-key-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=start,
        acknowledgement_sha256=ACKNOWLEDGEMENT_SHA,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id=OBSERVATION_KEY_ID,
        issuer_secret=b"wrong-observation-key-material-at-least-32-bytes",
        source_revision=authorization.capability.source_revision,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    with pytest.raises(EffectRecoverySignatureError):
        _recover(authorization, execution, start, forged, ledger)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_substituted_observation_ledger_key_set_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
    foreign = _ledger(
        tmp_path,
        path_name=ledger.path.name,
        observation_key=(
            b"foreign-observation-key-material-at-least-32-bytes"
        ),
    )
    with pytest.raises(
        RuntimeProviderRecoveryBindingError,
        match="observation authority failed authentication",
    ):
        _recover(authorization, execution, start, observation, foreign)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_foreign_runtime_registry_and_malformed_rows_refuse_in_recovery_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
    entrypoint_id = fixture._request().entrypoint_id
    spec = authorization.registry[entrypoint_id]
    foreign = dataclasses.replace(
        authorization,
        registry={entrypoint_id: dataclasses.replace(spec, runtime_id="foreign-runtime")},
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="spec_runtime"):
        _recover(foreign, execution, start, observation, ledger)

    malformed = dataclasses.replace(
        authorization,
        registry={entrypoint_id: object()},
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="malformed"):
        _recover(malformed, execution, start, observation, ledger)


def test_forged_runtime_capability_and_foreign_entrypoint_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, start, observation, ledger, _authority_value = _started(
        tmp_path,
        monkeypatch,
    )
    forged = dataclasses.replace(
        authorization,
        capability=dataclasses.replace(
            authorization.capability,
            signature_sha256="0" * 64,
        ),
    )
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="authenticated replay"):
        _recover(forged, execution, start, observation, ledger)
    with pytest.raises(RuntimeProviderRecoveryBindingError, match="absent"):
        _recover(
            authorization,
            execution,
            start,
            observation,
            ledger,
            entrypoint_id="provider.foreign-runtime",
        )
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"
