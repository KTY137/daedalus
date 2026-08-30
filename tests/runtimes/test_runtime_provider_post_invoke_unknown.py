# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.effect_recovery import issue_external_effect_observation
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
    RuntimeProviderReconciliationRequired,
    run_runtime_provider,
)
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.runtimes.recovery import reconcile_runtime_provider_unknown
from daedalus.spine.envelope import canonical_sha


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
PROVIDER_ID = "provider.external-runtime-fixture"
OBSERVATION_KEY_ID = "post-provider-observation-key"
OBSERVATION_KEY = b"post-provider-observation-key-material-at-least-32-bytes"
AUTHORITY_KEY_ID = "post-provider-authority-key"
AUTHORITY_KEY = b"post-provider-authority-key-material-at-least-32-bytes"
RECORD_KEY = b"post-provider-record-key-material-at-least-32-bytes"
OUTPUT_SHA = "7" * 64


def _load_authority_fixture():
    name = "daedalus_test_runtime_authority_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _constant_runtime_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: fixture.NOW,
    )
    monkeypatch.setattr(
        "daedalus.runtimes.broker._utc_now",
        lambda: fixture.NOW,
    )


def _observation_authority(tmp_path: Path, authorization, execution):
    entrypoint_id = fixture._request().entrypoint_id
    ledger = ProviderObservationBindingLedger(
        tmp_path / "provider-observation.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="post-provider-binding",
        provider_id=PROVIDER_ID,
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )
    return authority, ledger


def test_exact_runtime_provider_refuses_without_observation_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    _constant_runtime_clock(monkeypatch)
    called: list[str] = []
    with pytest.raises(
        RuntimeProviderBindingMismatch,
        match="require ProviderObservationAuthority",
    ):
        run_runtime_provider(
            fixture._request().entrypoint_id,
            authorization=authorization,
            execution=execution,
            invoke=lambda: called.append("invoked"),
            output_digests=lambda value: (OUTPUT_SHA,),
        )
    assert called == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_forged_observation_authority_refuses_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    _constant_runtime_clock(monkeypatch)
    observation_authority, observation_ledger = _observation_authority(
        tmp_path,
        authorization,
        execution,
    )
    forged = dataclasses.replace(
        observation_authority,
        signature_sha256="0" * 64,
    )
    called: list[str] = []
    with pytest.raises(
        RuntimeProviderBindingMismatch,
        match="could not authenticate and bind",
    ):
        run_runtime_provider(
            fixture._request().entrypoint_id,
            authorization=authorization,
            execution=execution,
            invoke=lambda: called.append("invoked"),
            output_digests=lambda value: (OUTPUT_SHA,),
            observation_authority=forged,
            observation_binding_ledger=observation_ledger,
        )
    assert called == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "FAILED"


def test_returned_provider_with_evidence_callback_failure_stays_started_and_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    entrypoint_id = fixture._request().entrypoint_id
    _constant_runtime_clock(monkeypatch)
    observation_authority, observation_ledger = _observation_authority(
        tmp_path,
        authorization,
        execution,
    )
    provider_commits: list[str] = []

    def invoke() -> dict[str, str]:
        retained = observation_ledger.load(execution.execution_id)
        assert retained is not None
        acknowledgement = canonical_sha(
            {
                "provider_id": retained.authority.provider_id,
                "idempotency_key": execution.idempotency_key,
                "output_sha256": OUTPUT_SHA,
            }
        )
        provider_commits.append(acknowledgement)
        return {"acknowledgement_sha256": acknowledgement}

    def fail_evidence(value: dict[str, str]):
        assert value["acknowledgement_sha256"] == provider_commits[0]
        raise RuntimeError("local evidence materialization failed")

    with pytest.raises(RuntimeProviderReconciliationRequired) as captured:
        run_runtime_provider(
            entrypoint_id,
            authorization=authorization,
            execution=execution,
            invoke=invoke,
            output_digests=fail_evidence,
            observation_authority=observation_authority,
            observation_binding_ledger=observation_ledger,
        )

    error = captured.value
    assert len(provider_commits) == 1
    acknowledgement = provider_commits[0]
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"
    assert error.start_receipt.execution_id == execution.execution_id
    assert error.start_receipt.idempotency_key == execution.idempotency_key
    assert error.__cause__ is not None
    assert not hasattr(error, "value")

    retained = observation_ledger.load(execution.execution_id)
    assert retained is not None
    assert retained.authority == observation_authority
    assert retained.start_receipt == error.start_receipt

    replay = run_runtime_provider(
        entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=lambda: provider_commits.append("duplicate") or {},
        output_digests=lambda value: (OUTPUT_SHA,),
        observation_authority=observation_authority,
        observation_binding_ledger=observation_ledger,
    )
    assert replay.executed is False
    assert replay.start_receipt == error.start_receipt
    assert replay.terminal_receipt is None
    assert replay.value is None
    assert provider_commits == [acknowledgement]

    observation = issue_external_effect_observation(
        observation_id="post-provider-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=error.start_receipt,
        acknowledgement_sha256=acknowledgement,
        output_digests=(OUTPUT_SHA,),
        issuer_key_id=OBSERVATION_KEY_ID,
        issuer_secret=OBSERVATION_KEY,
        source_revision=authorization.capability.source_revision,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    recovered = reconcile_runtime_provider_unknown(
        entrypoint_id,
        authorization=authorization,
        execution=execution,
        start_receipt=error.start_receipt,
        observation=observation,
        observation_binding_ledger=observation_ledger,
        reconciled_at=fixture.NOW + timedelta(seconds=2),
    )
    assert recovered.reconciled is True
    assert recovered.terminal_receipt.outcome == "COMPLETED"
    assert recovered.terminal_receipt.output_digests == (OUTPUT_SHA,)
    assert recovered.terminal_receipt.detail_sha256 == observation.digest
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert provider_commits == [acknowledgement]
