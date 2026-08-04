from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.effect_recovery import (
    issue_external_effect_observation,
    reconcile_unknown_effect,
)
from daedalus.runtimes.broker import (
    RuntimeProviderReconciliationRequired,
    run_runtime_provider,
)
from daedalus.spine.envelope import canonical_sha


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
PROVIDER_ID = "provider.external-runtime-fixture"
OBSERVATION_KEY = b"post-provider-observation-key-material-at-least-32-bytes"
OUTPUT_SHA = "7" * 64
REVISION = "1" * 40


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


def test_returned_provider_with_evidence_callback_failure_stays_started_and_reconciles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    _constant_runtime_clock(monkeypatch)
    provider_commits: list[str] = []

    def invoke() -> dict[str, str]:
        acknowledgement = canonical_sha(
            {
                "provider_id": PROVIDER_ID,
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
            fixture._request().entrypoint_id,
            authorization=authorization,
            execution=execution,
            invoke=invoke,
            output_digests=fail_evidence,
        )

    error = captured.value
    assert provider_commits == [provider_commits[0]]
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"
    assert error.start_receipt.execution_id == execution.execution_id
    assert error.start_receipt.idempotency_key == execution.idempotency_key
    assert error.__cause__ is not None

    replay = run_runtime_provider(
        fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=lambda: provider_commits.append("duplicate") or {},
        output_digests=lambda value: (OUTPUT_SHA,),
    )
    assert replay.executed is False
    assert replay.start_receipt == error.start_receipt
    assert replay.terminal_receipt is None
    assert replay.value is None
    assert provider_commits == [provider_commits[0]]

    observation = issue_external_effect_observation(
        observation_id="post-provider-observation",
        provider_id=PROVIDER_ID,
        execution=execution,
        start_receipt=error.start_receipt,
        acknowledgement_sha256=provider_commits[0],
        output_digests=(OUTPUT_SHA,),
        issuer_key_id="post-provider-observation-key",
        issuer_secret=OBSERVATION_KEY,
        source_revision=REVISION,
        observed_at=fixture.NOW + timedelta(seconds=1),
    )
    recovered = reconcile_unknown_effect(
        authorization.effect_ledger,
        execution=execution,
        start_receipt=error.start_receipt,
        observation=observation,
        keyring={"post-provider-observation-key": OBSERVATION_KEY},
        expected_provider_id=PROVIDER_ID,
        expected_source_revision=REVISION,
        reconciled_at=fixture.NOW + timedelta(seconds=2),
    )
    assert recovered.reconciled is True
    assert recovered.terminal_receipt.outcome == "COMPLETED"
    assert recovered.terminal_receipt.output_digests == (OUTPUT_SHA,)
    assert recovered.terminal_receipt.detail_sha256 == observation.digest
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert provider_commits == [provider_commits[0]]


def test_reconciliation_error_does_not_retain_provider_value_or_cause_text() -> None:
    fixture_start = fixture._execution()
    assert not hasattr(RuntimeProviderReconciliationRequired, "value")
    assert fixture_start.execution_id not in str(RuntimeProviderReconciliationRequired)
