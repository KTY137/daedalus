from __future__ import annotations

import concurrent.futures
import dataclasses
import importlib.util
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.effect_recovery import (
    EffectRecoveryBindingError,
    EffectRecoverySignatureError,
    EffectRecoveryStateError,
    ExternalEffectObservation,
    issue_external_effect_observation,
    reconcile_unknown_effect,
    verify_external_effect_observation,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "unknown_outcome_reconciliation_fault_executor.py"
REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
ACK = "1" * 64
OUTPUT = "2" * 64
SECRET = b"unknown-outcome-observation-key-material-32-bytes"


def _load_fixture():
    name = "daedalus_test_unknown_outcome_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture()


def _started(tmp_path: Path):
    ledger, authorization, execution = fixture._authority(
        root=tmp_path,
        source_revision=REVISION,
        now=NOW,
    )
    start = authorization.begin_effect(execution, started_at=NOW)
    assert start.execute is True
    return ledger, authorization, execution, start.receipt


def _observation(execution, start_receipt, **changes):
    values = {
        "observation_id": "observation-1",
        "provider_id": fixture._PROVIDER_ID,
        "execution": execution,
        "start_receipt": start_receipt,
        "acknowledgement_sha256": ACK,
        "output_digests": (OUTPUT,),
        "issuer_key_id": "observation-key",
        "issuer_secret": SECRET,
        "source_revision": REVISION,
        "observed_at": NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return issue_external_effect_observation(**values)


def _verify(observation, execution, start_receipt, **changes):
    values = {
        "execution": execution,
        "start_receipt": start_receipt,
        "keyring": {"observation-key": SECRET},
        "expected_provider_id": fixture._PROVIDER_ID,
        "expected_source_revision": REVISION,
        "now": NOW + timedelta(seconds=2),
    }
    values.update(changes)
    return verify_external_effect_observation(observation, **values)


def _resign(observation):
    return dataclasses.replace(
        observation,
        signature_sha256=fixture.recovery_module._signature(
            observation.signing_digest,
            SECRET,
        ),
    )


def test_observation_round_trip_signature_and_exact_evidence_binding(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    assert ExternalEffectObservation.from_dict(observation.to_dict()) == observation
    assert observation.signature_sha256 != "0" * 64
    assert observation.provenance.input_digests == tuple(
        sorted((start.receipt_sha256, ACK, OUTPUT))
    )
    _verify(observation, execution, start)


def test_provenance_cannot_add_unrelated_signed_inputs(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    expanded = dataclasses.replace(
        observation.provenance,
        input_digests=tuple(
            sorted((*observation.provenance.input_digests, "f" * 64))
        ),
    )
    with pytest.raises(ValueError, match="exactly"):
        dataclasses.replace(observation, provenance=expanded)


def test_issue_requires_exact_start_scope_and_post_start_acknowledgement(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    with pytest.raises(EffectRecoveryBindingError, match="predates"):
        _observation(
            execution,
            start,
            observed_at=NOW - timedelta(microseconds=1),
        )
    foreign_scope = dataclasses.replace(
        start,
        execution_request_sha256="8" * 64,
    )
    with pytest.raises(EffectRecoveryBindingError, match="execution_request_sha256"):
        _observation(execution, foreign_scope)


def test_signed_predating_observation_is_refused_at_verification(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    predating = (NOW - timedelta(microseconds=1)).isoformat(timespec="microseconds")
    provenance = dataclasses.replace(
        observation.provenance,
        created_at=predating,
    )
    changed = dataclasses.replace(
        observation,
        observed_at=predating,
        signature_sha256="0" * 64,
        provenance=provenance,
    )
    with pytest.raises(EffectRecoveryBindingError, match="predates"):
        _verify(_resign(changed), execution, start)


def test_signature_unknown_key_future_and_stale_refuse(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    tampered = dataclasses.replace(observation, acknowledgement_sha256="3" * 64)
    with pytest.raises(EffectRecoverySignatureError, match="signature"):
        _verify(tampered, execution, start)
    with pytest.raises(EffectRecoverySignatureError, match="unknown"):
        _verify(observation, execution, start, keyring={})
    with pytest.raises(EffectRecoveryBindingError, match="future"):
        _verify(observation, execution, start, now=NOW)
    stale = _observation(
        execution,
        start,
        observed_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(EffectRecoveryBindingError, match="stale"):
        _verify(stale, execution, start, now=NOW + timedelta(hours=25, seconds=2))


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "provider.foreign"),
        ("execution_id", "execution-foreign"),
        ("idempotency_key", "idempotency-foreign"),
    ],
)
def test_signed_foreign_binding_dimensions_refuse(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    changed = _resign(dataclasses.replace(observation, **{field: value}))
    with pytest.raises(EffectRecoveryBindingError):
        _verify(changed, execution, start)


def test_source_revision_and_start_receipt_bindings_refuse(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    with pytest.raises(EffectRecoveryBindingError, match="source_revision"):
        _verify(
            observation,
            execution,
            start,
            expected_source_revision="b" * 40,
        )
    changed_execution = dataclasses.replace(start, execution_id="execution-foreign")
    with pytest.raises(EffectRecoveryBindingError, match="execution_id"):
        _verify(observation, execution, changed_execution)
    changed_digest = dataclasses.replace(start, receipt_sha256="4" * 64)
    with pytest.raises(EffectRecoveryBindingError, match="start_receipt_sha256"):
        _verify(observation, execution, changed_digest)


def test_reconcile_is_terminal_exact_and_idempotent(tmp_path: Path) -> None:
    ledger, authorization, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    first = reconcile_unknown_effect(
        ledger,
        execution=execution,
        start_receipt=start,
        observation=observation,
        keyring={"observation-key": SECRET},
        expected_provider_id=fixture._PROVIDER_ID,
        expected_source_revision=REVISION,
        reconciled_at=NOW + timedelta(seconds=2),
    )
    second = reconcile_unknown_effect(
        ledger,
        execution=execution,
        start_receipt=start,
        observation=observation,
        keyring={"observation-key": SECRET},
        expected_provider_id=fixture._PROVIDER_ID,
        expected_source_revision=REVISION,
        reconciled_at=NOW + timedelta(seconds=3),
    )
    replay = authorization.begin_effect(
        execution,
        started_at=NOW + timedelta(seconds=3),
    )

    assert first.reconciled is True
    assert second.reconciled is False
    assert first.terminal_receipt == second.terminal_receipt
    assert first.terminal_receipt.outcome == "COMPLETED"
    assert first.terminal_receipt.output_digests == (OUTPUT,)
    assert first.terminal_receipt.detail_sha256 == observation.digest
    assert ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert replay.execute is False
    assert replay.receipt == start


def test_concurrent_reconciliation_has_one_commit_and_one_exact_replay(tmp_path: Path) -> None:
    ledger, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)

    def reconcile(index: int):
        return reconcile_unknown_effect(
            ledger,
            execution=execution,
            start_receipt=start,
            observation=observation,
            keyring={"observation-key": SECRET},
            expected_provider_id=fixture._PROVIDER_ID,
            expected_source_revision=REVISION,
            reconciled_at=NOW + timedelta(seconds=2),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile, range(2)))
    assert sorted(result.reconciled for result in results) == [False, True]
    assert results[0].terminal_receipt == results[1].terminal_receipt


def test_changed_acknowledgement_or_output_cannot_repack_terminal(tmp_path: Path) -> None:
    ledger, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    reconcile_unknown_effect(
        ledger,
        execution=execution,
        start_receipt=start,
        observation=observation,
        keyring={"observation-key": SECRET},
        expected_provider_id=fixture._PROVIDER_ID,
        expected_source_revision=REVISION,
        reconciled_at=NOW + timedelta(seconds=2),
    )
    for changed in (
        _observation(execution, start, acknowledgement_sha256="5" * 64),
        _observation(execution, start, output_digests=("6" * 64,)),
    ):
        with pytest.raises(EffectRecoveryStateError, match="different recovery"):
            reconcile_unknown_effect(
                ledger,
                execution=execution,
                start_receipt=start,
                observation=changed,
                keyring={"observation-key": SECRET},
                expected_provider_id=fixture._PROVIDER_ID,
                expected_source_revision=REVISION,
                reconciled_at=NOW + timedelta(seconds=3),
            )


def test_failed_or_cancelled_execution_cannot_be_rewritten_completed(tmp_path: Path) -> None:
    for outcome in ("FAILED", "CANCELLED"):
        root = tmp_path / outcome.lower()
        ledger, authorization, execution, start = _started(root)
        authorization.finish_effect(
            start,
            outcome=outcome,
            detail_sha256="7" * 64,
            finished_at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(EffectRecoveryStateError, match="different recovery"):
            reconcile_unknown_effect(
                ledger,
                execution=execution,
                start_receipt=start,
                observation=_observation(execution, start),
                keyring={"observation-key": SECRET},
                expected_provider_id=fixture._PROVIDER_ID,
                expected_source_revision=REVISION,
                reconciled_at=NOW + timedelta(seconds=2),
            )


def test_corrupt_or_duplicate_terminal_json_refuses_replay(tmp_path: Path) -> None:
    ledger, _, execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    reconcile_unknown_effect(
        ledger,
        execution=execution,
        start_receipt=start,
        observation=observation,
        keyring={"observation-key": SECRET},
        expected_provider_id=fixture._PROVIDER_ID,
        expected_source_revision=REVISION,
        reconciled_at=NOW + timedelta(seconds=2),
    )
    with sqlite3.connect(str(ledger.path)) as connection:
        connection.execute(
            "UPDATE effect_executions SET terminal_receipt_json=? WHERE execution_id=?",
            ('{"outcome":"COMPLETED","outcome":"FAILED"}', execution.execution_id),
        )
    with pytest.raises(EffectRecoveryStateError, match="malformed"):
        reconcile_unknown_effect(
            ledger,
            execution=execution,
            start_receipt=start,
            observation=observation,
            keyring={"observation-key": SECRET},
            expected_provider_id=fixture._PROVIDER_ID,
            expected_source_revision=REVISION,
            reconciled_at=NOW + timedelta(seconds=3),
        )


def test_observation_parser_rejects_extra_fields_and_non_sequence_outputs(tmp_path: Path) -> None:
    _, _, execution, start = _started(tmp_path)
    payload = _observation(execution, start).to_dict()
    payload["foreign"] = True
    with pytest.raises(ValueError, match="fields"):
        ExternalEffectObservation.from_dict(payload)
    payload.pop("foreign")
    payload["output_digests"] = OUTPUT
    with pytest.raises(ValueError, match="sequence"):
        ExternalEffectObservation.from_dict(payload)
