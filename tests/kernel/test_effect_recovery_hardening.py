# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.effect_recovery import (
    EffectRecoveryBindingError,
    issue_external_effect_observation,
    verify_external_effect_observation,
)
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "unknown_outcome_reconciliation_fault_executor.py"
)
REVISION = "a" * 40
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
ACK = "1" * 64
OUTPUT = "2" * 64
SECRET = b"unknown-outcome-observation-key-material-32-bytes"


def _load_fixture():
    name = "daedalus_test_unknown_outcome_fixture_hardening"
    spec = importlib.util.spec_from_file_location(name, FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture()


def _started(tmp_path: Path):
    _, authorization, execution = fixture._authority(
        root=tmp_path,
        source_revision=REVISION,
        now=NOW,
    )
    result = authorization.begin_effect(execution, started_at=NOW)
    assert result.execute is True
    return execution, result.receipt


def _observation(execution, start):
    return issue_external_effect_observation(
        observation_id="observation-hardening",
        provider_id=fixture._PROVIDER_ID,
        execution=execution,
        start_receipt=start,
        acknowledgement_sha256=ACK,
        output_digests=(OUTPUT,),
        issuer_key_id="observation-key",
        issuer_secret=SECRET,
        source_revision=REVISION,
        observed_at=NOW + timedelta(seconds=1),
    )


def _resign(observation):
    return dataclasses.replace(
        observation,
        signature_sha256=fixture.recovery_module._signature(
            observation.signing_digest,
            SECRET,
        ),
    )


def _canonical_start(start, **changes):
    candidate = dataclasses.replace(
        start,
        **changes,
        receipt_sha256="0" * 64,
    )
    payload = {
        "lease_sha256": candidate.lease_sha256,
        "execution_id": candidate.execution_id,
        "idempotency_key": candidate.idempotency_key,
        "execution_request_sha256": candidate.execution_request_sha256,
        "boundary_receipt_sha256": candidate.boundary_receipt_sha256,
        "started_at": candidate.started_at,
    }
    return dataclasses.replace(
        candidate,
        receipt_sha256=canonical_sha(payload),
    )


def _verify(observation, execution, start):
    return verify_external_effect_observation(
        observation,
        execution=execution,
        start_receipt=start,
        keyring={"observation-key": SECRET},
        expected_provider_id=fixture._PROVIDER_ID,
        expected_source_revision=REVISION,
        now=NOW + timedelta(seconds=2),
    )


def test_canonically_repacked_start_idempotency_is_rejected(tmp_path: Path) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    foreign_start = _canonical_start(
        start,
        idempotency_key="foreign-idempotency",
    )
    with pytest.raises(EffectRecoveryBindingError, match="start_idempotency_key"):
        _verify(observation, execution, foreign_start)


def test_canonically_repacked_execution_request_digest_is_rejected(
    tmp_path: Path,
) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    foreign_start = _canonical_start(
        start,
        execution_request_sha256="3" * 64,
    )
    with pytest.raises(
        EffectRecoveryBindingError,
        match="start_execution_request_sha256",
    ):
        _verify(observation, execution, foreign_start)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lease_sha256", "3" * 64),
        ("boundary_receipt_sha256", "4" * 64),
        (
            "started_at",
            (NOW + timedelta(microseconds=1)).isoformat(timespec="microseconds"),
        ),
    ],
)
def test_raw_start_receipt_tampering_fails_digest_validation(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    tampered = dataclasses.replace(start, **{field: value})
    with pytest.raises(EffectRecoveryBindingError, match="start_receipt_sha256"):
        _verify(observation, execution, tampered)


def test_signed_foreign_start_receipt_digest_is_rejected(tmp_path: Path) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    foreign_digest = "5" * 64
    foreign_provenance = dataclasses.replace(
        observation.provenance,
        input_digests=tuple(sorted((foreign_digest, ACK, OUTPUT))),
    )
    repacked = _resign(
        dataclasses.replace(
            observation,
            start_receipt_sha256=foreign_digest,
            provenance=foreign_provenance,
        )
    )
    with pytest.raises(EffectRecoveryBindingError, match="start_receipt_sha256"):
        _verify(repacked, execution, start)


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("origin", "tests.foreign-recovery", "provenance_origin"),
        (
            "created_at",
            (NOW + timedelta(seconds=1, microseconds=1)).isoformat(
                timespec="microseconds"
            ),
            "provenance_created_at",
        ),
        ("trace_id", "foreign-execution", "provenance_trace_id"),
    ],
)
def test_signed_repacked_provenance_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
    expected_error: str,
) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    foreign_provenance = dataclasses.replace(
        observation.provenance,
        **{field: value},
    )
    repacked = _resign(
        dataclasses.replace(observation, provenance=foreign_provenance)
    )
    with pytest.raises(EffectRecoveryBindingError, match=expected_error):
        _verify(repacked, execution, start)


def test_signed_foreign_source_revision_is_rejected(tmp_path: Path) -> None:
    execution, start = _started(tmp_path)
    observation = _observation(execution, start)
    foreign_provenance = dataclasses.replace(
        observation.provenance,
        source_revision="b" * 40,
    )
    repacked = _resign(
        dataclasses.replace(observation, provenance=foreign_provenance)
    )
    with pytest.raises(EffectRecoveryBindingError, match="source_revision"):
        _verify(repacked, execution, start)
